# -*- coding: utf-8 -*-
"""Worker semantic event-driven cho Deep Environment.

Mục tiêu của module này là tách đường:
    native event -> semantic -> UserSituation
khỏi nhịp self-turn. Native callback chỉ đưa event đã qua privacy/coalesce vào
queue; một daemon thread riêng mới làm UIA enrichment, Chromium reconcile cục
bộ, TaskGraph/RegionMemory và cập nhật ``UserSituation``.

Nhờ vậy cognition không phải đợi autonomous loop ngủ vài giây mới biết một
``command_failed`` vừa xảy ra. Self-turn chỉ đọc snapshot đã được xử lý sẵn.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .desktop_semantics import DesktopSemanticRuntime, UserSituation
from .environment_event_bus import NormalizedEnvironmentEvent


_CHROMIUM_PROCESSES = {"chrome.exe", "msedge.exe", "brave.exe", "chromium.exe"}
_NATIVE_ENRICH_SOURCES = {"winevent", "foreground_reconcile"}


@dataclass(frozen=True, slots=True)
class _QueuedEnvironmentEvent:
    """Envelope runtime-only; timing này không đi qua privacy payload/persistence."""

    event: NormalizedEnvironmentEvent
    ingress_monotonic_ns: int
    ingress_wall_time: float


class SemanticEnvironmentWorker:
    """Consumer duy nhất cho structured semantic path của DesktopSemanticRuntime.

    ``DesktopSemanticRuntime`` và ``TaskGraph`` đều có state mutable. Worker giữ
    một lock chung khi mutate chúng để self-turn chỉ được phép gọi fallback OCR/
    screen qua ``build_perception_situation``. Cách này tránh hai thread cùng sửa
    TaskGraph rồi tạo ra một task rất meta: debug race condition của TaskGraph.
    """

    def __init__(
        self,
        *,
        host: Any,
        runtime: DesktopSemanticRuntime,
        publish_event: Callable[[NormalizedEnvironmentEvent], NormalizedEnvironmentEvent | None],
        uia_adapter: Any = None,
        chromium_adapter: Any = None,
        max_queue: int = 1024,
        batch_window_ms: float = 8.0,
        chromium_refresh_min_ms: float = 120.0,
    ) -> None:
        self.host = host
        self.runtime = runtime
        self._publish_event = publish_event
        self._uia_adapter = uia_adapter
        self._chromium_adapter = chromium_adapter
        self._queue: queue.Queue[_QueuedEnvironmentEvent] = queue.Queue(maxsize=max(64, int(max_queue)))
        self._batch_window_seconds = max(0.0, float(batch_window_ms)) / 1000.0
        self._chromium_refresh_min_ns = int(max(20.0, float(chromium_refresh_min_ms)) * 1_000_000.0)
        self._last_chromium_refresh_ns = 0

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._runtime_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._latest_telemetry: dict[str, Any] = {}
        self._latest_situation: UserSituation | None = None
        self._processed: deque[tuple[int, NormalizedEnvironmentEvent]] = deque(maxlen=512)
        self._revision = 0
        self._last_perception_revision = 0

    def start(self) -> "SemanticEnvironmentWorker":
        """Khởi động daemon thread nếu chưa chạy."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="eris-semantic-environment",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 1.5) -> None:
        """Dừng worker có giới hạn thời gian; shutdown không được treo theo sensor."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))

    def set_uia_adapter(self, adapter: Any) -> None:
        self._uia_adapter = adapter

    def set_chromium_adapter(self, adapter: Any) -> None:
        self._chromium_adapter = adapter

    @property
    def latest_situation(self) -> UserSituation | None:
        with self._state_lock:
            return self._latest_situation

    @property
    def revision(self) -> int:
        with self._state_lock:
            return self._revision

    @property
    def pending_attention_level(self) -> int:
        """Attention structured chưa được self-turn consume, dùng để bypass cooldown xã hội."""
        with self._state_lock:
            if self._revision <= self._last_perception_revision or self._latest_situation is None:
                return 0
            return max(0, min(4, int(self._latest_situation.max_attention_level or 0)))

    def update_telemetry(self, telemetry: Mapping[str, Any] | None) -> None:
        """Giữ snapshot telemetry nhỏ, không mang raw page/clipboard content vào worker."""
        if not isinstance(telemetry, Mapping):
            return
        allow = (
            "active_process",
            "active_app",
            "active_window_title",
            "window_class",
            "foreground_pid",
            "foreground_hwnd",
            "idle_seconds",
            "interaction_state",
            "active_window_kind",
            "active_file",
            "selected_file",
        )
        compact = {key: telemetry.get(key) for key in allow if key in telemetry}
        with self._state_lock:
            self._latest_telemetry = compact

    def submit(
        self,
        event: NormalizedEnvironmentEvent,
        *,
        ingress_monotonic_ns: int | None = None,
        ingress_wall_time: float | None = None,
    ) -> bool:
        """Đưa event vào queue mà không block native callback.

        Khi queue đầy, bỏ event cũ nhất rồi nhận event mới. Structured sensing
        ưu tiên trạng thái mới nhất hơn việc giữ backlog nhiều giây, vì backlog
        chính là thứ PDF muốn loại khỏi critical path.
        """
        item = _QueuedEnvironmentEvent(
            event=event,
            ingress_monotonic_ns=int(ingress_monotonic_ns or time.monotonic_ns()),
            ingress_wall_time=float(time.time() if ingress_wall_time is None else ingress_wall_time),
        )
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._metric_increment("environment_semantic_queue_drop_total")
            try:
                self._queue.put_nowait(item)
                return True
            except queue.Full:
                return False

    def wait_until_revision(self, revision: int, timeout: float = 1.0) -> bool:
        """Helper deterministic cho test/probe, không dùng polling nóng trong production."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        target = max(0, int(revision))
        while time.monotonic() < deadline:
            if self.revision >= target:
                return True
            time.sleep(0.005)
        return self.revision >= target

    def build_perception_situation(
        self,
        screen_context: Any,
        *,
        telemetry: Mapping[str, Any] | None,
        observer_frame: Any = None,
        now: float | None = None,
    ) -> tuple[tuple[NormalizedEnvironmentEvent, ...], UserSituation]:
        """Ghép fallback screen/OCR với structured snapshot đã xử lý trước đó.

        Structured event chỉ mang ``max_attention_level`` sang self-turn đúng một
        lần, tại perception đầu tiên sau khi worker xử lý event. Nếu không có event
        mới, task/busy/interruption vẫn được giữ nhưng attention cũ không được đánh
        thức cognition lần thứ hai.
        """
        now = time.time() if now is None else float(now)
        self.update_telemetry(telemetry)

        with self._state_lock:
            structured = self._latest_situation
            new_events = tuple(
                event for revision, event in self._processed
                if revision > self._last_perception_revision
            )
            if self._revision > self._last_perception_revision:
                self._last_perception_revision = self._revision

        # observe(screen) vẫn là fallback hợp lệ, nhưng phải đi qua cùng runtime
        # lock để không race với observe_events() của worker.
        with self._runtime_lock:
            base = self.runtime.observe(
                screen_context,
                telemetry=telemetry,
                observer_frame=observer_frame,
                now=now,
            )

        return new_events[-128:], self._merge_situations(
            base=base,
            structured=structured,
            has_new_structured=bool(new_events),
            now=now,
        )

    @staticmethod
    def _merge_situations(
        *,
        base: UserSituation,
        structured: UserSituation | None,
        has_new_structured: bool,
        now: float,
    ) -> UserSituation:
        if structured is None:
            return base

        def prefer_structured(value: str, fallback: str) -> str:
            text = str(value or "").strip()
            return text if text and text != "unknown" else fallback

        # TaskGraph/structured source quyết định task/phase. Focus hiện tại từ
        # telemetry/screen có độ mới tốt hơn nên base được ưu tiên ở focused_*.
        max_attention = max(
            int(base.max_attention_level or 0),
            int(structured.max_attention_level or 0) if has_new_structured else 0,
        )
        semantic_delta = bool(base.semantic_delta or (has_new_structured and structured.semantic_delta))
        wake_recommended = bool(base.wake_recommended or (has_new_structured and structured.wake_recommended))
        recent = structured.recent_events or base.recent_events
        refs = tuple(dict.fromkeys((*base.evidence_refs, *structured.evidence_refs)))[:12]

        return UserSituation(
            timestamp=now,
            activity=prefer_structured(structured.activity, base.activity),
            task_hint=prefer_structured(structured.task_hint, base.task_hint),
            phase=prefer_structured(structured.phase, base.phase),
            focused_app=base.focused_app or structured.focused_app,
            focused_process=base.focused_process or structured.focused_process,
            focused_object=base.focused_object or structured.focused_object,
            last_action=(structured.last_action if has_new_structured else base.last_action) or base.last_action,
            last_outcome=prefer_structured(structured.last_outcome, base.last_outcome),
            attention_state=prefer_structured(structured.attention_state, base.attention_state),
            interruption_cost=max(float(base.interruption_cost or 0.0), float(structured.interruption_cost or 0.0)),
            busy_score=max(float(base.busy_score or 0.0), float(structured.busy_score or 0.0)),
            confidence=max(float(base.confidence or 0.0), float(structured.confidence or 0.0)),
            semantic_delta=semantic_delta,
            wake_recommended=wake_recommended,
            max_attention_level=max(0, min(4, max_attention)),
            recent_events=recent,
            evidence_refs=refs,
        )

    def _run(self) -> None:
        """Main loop: batch cực ngắn để giảm overhead nhưng không tạo backlog."""
        while not self._stop_event.is_set():
            try:
                first = self._queue.get(timeout=0.20)
            except queue.Empty:
                continue

            batch = [first]
            batch_deadline = time.monotonic() + self._batch_window_seconds
            while len(batch) < 64 and time.monotonic() < batch_deadline:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            try:
                self._process_batch(batch)
            except Exception as exc:  # noqa: BLE001
                logger = getattr(self.host, "logger", None)
                if logger is not None:
                    try:
                        logger.warning("[deep environment] semantic worker batch lỗi: %s", exc)
                    except Exception:
                        pass
                self._metric_increment("environment_semantic_worker_error_total")

    def _process_batch(self, batch: list[_QueuedEnvironmentEvent]) -> None:
        if not batch:
            return

        # UIA enrichment tuyệt đối không chạy trong WinEvent callback. Nó chạy ở
        # daemon consumer này, sau đó publish lại để cùng privacy/coalesce path.
        for queued in batch:
            event = queued.event
            if self._uia_adapter is not None and event.source in _NATIVE_ENRICH_SOURCES:
                try:
                    enriched = self._uia_adapter.enrich(event)
                    if enriched is not None:
                        self._publish_event(enriched)
                except Exception as exc:  # noqa: BLE001
                    self._debug("UIA enrichment lỗi: %s", exc)

        # Với Chromium, native selection/name/focus event được dùng như trigger
        # để IA2/UIA adapter diff ngay, thay vì chờ self-turn poll 15 giây.
        chromium_triggers = [
            item.event for item in batch
            if str(item.event.process_name or "").lower() in _CHROMIUM_PROCESSES
            and item.event.source in _NATIVE_ENRICH_SOURCES
        ]
        if self._chromium_adapter is not None and chromium_triggers:
            now_ns = time.monotonic_ns()
            if now_ns - self._last_chromium_refresh_ns >= self._chromium_refresh_min_ns:
                self._last_chromium_refresh_ns = now_ns
                trigger = min(chromium_triggers, key=lambda item: float(item.timestamp or 0.0))
                try:
                    for chromium_event in tuple(self._chromium_adapter.poll_all() or ()):
                        # Gắn timestamp của native trigger vào event Chromium để
                        # metric native -> browser semantic tính luôn thời gian IA2/UIA
                        # diff, không tự đẹp số bằng cách bắt đầu đồng hồ sau poll.
                        metadata = dict(chromium_event.metadata or {})
                        metadata.setdefault("trigger_source", trigger.source)
                        metadata.setdefault("trigger_event_type", trigger.event_type)
                        triggered_event = replace(
                            chromium_event,
                            timestamp=min(float(chromium_event.timestamp), float(trigger.timestamp)),
                            metadata=metadata,
                            event_id="",
                        )
                        self._publish_event(triggered_event)
                except Exception as exc:  # noqa: BLE001
                    self._debug("Chromium event-triggered refresh lỗi: %s", exc)

        events = tuple(item.event for item in batch)
        telemetry = self._telemetry_for_events(events)
        semantic_wall_done = time.time()
        with self._runtime_lock:
            situation = self.runtime.observe_events(
                events,
                telemetry=telemetry,
                base_situation=None,
                now=semantic_wall_done,
            )
        semantic_done_ns = time.monotonic_ns()
        semantic_wall_done = time.time()

        self._record_semantic_metrics(batch, situation, semantic_done_ns, semantic_wall_done)

        with self._state_lock:
            self._latest_situation = situation
            for item in batch:
                self._revision += 1
                self._processed.append((self._revision, item.event))

        # Worker chỉ đánh thức vòng autonomous. Quyền deliberation/speech vẫn nằm
        # trong TemporalMind + initiative governor của self-turn.
        if situation.semantic_delta and int(situation.max_attention_level or 0) >= 2:
            wake = getattr(self.host, "_wake_autonomous_loop", None)
            if callable(wake):
                kinds = ",".join(dict.fromkeys(event.event_type for event in events))[:120]
                try:
                    wake(f"environment_semantic:{kinds or 'event'}")
                except Exception as exc:  # noqa: BLE001
                    self._debug("không đánh thức được autonomous loop: %s", exc)

    def _telemetry_for_events(self, events: tuple[NormalizedEnvironmentEvent, ...]) -> dict[str, Any]:
        with self._state_lock:
            telemetry = dict(self._latest_telemetry)

        # Nếu event đến trước perception đầu tiên, tự dựng identity tối thiểu từ
        # structured source để UserSituation không rơi về focused_process rỗng.
        for event in reversed(events):
            if event.process_name:
                telemetry.setdefault("active_process", event.process_name)
                telemetry.setdefault("active_app", event.process_name)
            if event.pid:
                telemetry.setdefault("foreground_pid", event.pid)
            if event.hwnd:
                telemetry.setdefault("foreground_hwnd", event.hwnd)
            if event.window_class:
                telemetry.setdefault("window_class", event.window_class)
            if event.title:
                telemetry.setdefault("active_window_title", event.title)
            if event.event_type == "foreground_changed":
                telemetry["active_process"] = event.process_name or telemetry.get("active_process", "")
                telemetry["active_app"] = event.process_name or telemetry.get("active_app", "")
                telemetry["foreground_pid"] = event.pid or telemetry.get("foreground_pid", 0)
                telemetry["foreground_hwnd"] = event.hwnd or telemetry.get("foreground_hwnd", 0)
                telemetry["active_window_title"] = event.title or telemetry.get("active_window_title", "")
                break
        telemetry.setdefault("idle_seconds", 0.0)
        return telemetry

    def _record_semantic_metrics(
        self,
        batch: list[_QueuedEnvironmentEvent],
        situation: UserSituation,
        semantic_done_ns: int,
        semantic_wall_done: float,
    ) -> None:
        observability = getattr(self.host, "observability", None)
        if observability is None:
            return
        try:
            mechanical = all(item.event.attention_level == 0 or not item.event.semantic for item in batch)
            kinds = tuple(str(item.event.event_type or "unknown") for item in batch)
            for item in batch:
                event = item.event
                provider = str((event.metadata or {}).get("provider", "") or event.source or "unknown")[:40]
                ingress_to_semantic_ms = max(0.0, (semantic_done_ns - item.ingress_monotonic_ns) / 1_000_000.0)
                source_to_semantic_ms = max(0.0, (semantic_wall_done - float(event.timestamp or semantic_wall_done)) * 1000.0)
                tags = {
                    "source": event.source or "unknown",
                    "event_type": event.event_type or "unknown",
                    "provider": provider,
                }
                observability.observe("environment_ingress_to_semantic_ms", ingress_to_semantic_ms, tags=tags)
                observability.observe("environment_source_to_semantic_ms", source_to_semantic_ms, tags=tags)
                # Giữ tên metric cũ để dashboard/probe hiện tại không gãy; từ V4
                # giá trị của nó là source -> semantic thật, không còn phụ thuộc self-turn tick.
                observability.observe("environment_event_to_semantic_ms", source_to_semantic_ms, tags=tags)
                if event.event_type == "foreground_changed":
                    observability.observe("foreground_to_user_situation_ms", source_to_semantic_ms, tags=tags)

            wake_from_environment = bool(situation.semantic_delta and situation.max_attention_level >= 2)
            if mechanical and wake_from_environment:
                observability.increment("environment_false_wake_mechanical_total")
            observability.increment(
                "user_situation_from_environment_total",
                tags={
                    "phase": situation.phase or "unknown",
                    "attention_state": situation.attention_state or "unknown",
                    "max_attention": str(max(0, min(4, int(situation.max_attention_level or 0)))),
                    "semantic_delta": str(bool(situation.semantic_delta)).lower(),
                    "wake": str(wake_from_environment).lower(),
                },
                fields={
                    "event_count": len(batch),
                    "event_types": list(dict.fromkeys(kinds))[:12],
                    "task_hint": situation.task_hint,
                    "busy_score": round(float(situation.busy_score or 0.0), 4),
                    "interruption_cost": round(float(situation.interruption_cost or 0.0), 4),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._debug("ghi observability semantic lỗi: %s", exc)

    def _metric_increment(self, name: str) -> None:
        observability = getattr(self.host, "observability", None)
        if observability is None:
            return
        try:
            observability.increment(name)
        except Exception:
            pass

    def _debug(self, message: str, *args: Any) -> None:
        logger = getattr(self.host, "logger", None)
        if logger is None:
            return
        try:
            logger.debug("[deep environment] " + message, *args)
        except Exception:
            pass


__all__ = ["SemanticEnvironmentWorker"]
