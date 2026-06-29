# -*- coding: utf-8 -*-
"""tts_task_manager.py — quản lý thứ tự, prefetch, cancel và cache TTS.

Backend TTS chỉ nên biết cách sinh/phát audio.  Manager này nhận các
``StageFrame`` đã có ``turn_id``/``segment_id`` rồi:

- bỏ segment rỗng;
- sinh audio song song để giảm khoảng chờ giữa câu;
- phát lại theo đúng thứ tự segment;
- hủy phần đang phát và phần pending khi user chen vào;
- gửi emotion/motion event trước khi phát audio;
- cache WAV ngắn hạn để các segment giống nhau không gọi TTS lại.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from runtime.stage_audio_bus import StageAudioBus

logger = logging.getLogger("TTS.TaskManager")


@dataclass(frozen=True, slots=True)
class TtsSegmentTask:
    frame: Any
    text: str
    order: int
    valence: float
    arousal: float
    stance: str

    @property
    def key(self) -> tuple[str, int]:
        return (str(getattr(self.frame, "turn_id", "") or ""), int(self.order))


class TtsTaskManager:
    """Queue cấp lượt nói, tách khỏi engine Gemini cụ thể."""

    def __init__(self, *, audio_bus: StageAudioBus | None = None) -> None:
        self.audio_bus = audio_bus or StageAudioBus()
        self._lock = threading.RLock()
        self._generation = 0
        self._cancel_event = threading.Event()
        self._playback_stop = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._playback_thread: threading.Thread | None = None
        self._current_task: TtsSegmentTask | None = None
        self._pending_tasks: dict[tuple[str, int], TtsSegmentTask] = {}
        self._pending_callbacks: dict[tuple[str, int], Callable[[Any, Any], None] | None] = {}
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def dispatch_frames(
        self,
        frames: Iterable[Any],
        *,
        backend: Any,
        valence: float,
        arousal: float,
        stance: str,
        on_first_start: Callable[[], None] | None = None,
        on_event: Callable[[Any, Any], None] | None = None,
    ) -> bool:
        """Nhận một lượt stage và bắt đầu synth/playback không blocking."""

        synthesize = getattr(backend, "synthesize", None)
        play_audio = getattr(backend, "play_audio", None)
        if not callable(synthesize) or not callable(play_audio):
            return False

        tasks = self._build_tasks(frames, valence=valence, arousal=arousal, stance=stance)
        if not tasks:
            return False

        self.cancel_current(reason="replaced", only_interruptible=False)
        cancel_event = threading.Event()
        playback_stop = threading.Event()
        workers = _prefetch_workers()
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="TTS-Prefetch")

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._cancel_event = cancel_event
            self._playback_stop = playback_stop
            self._executor = executor
            self._current_task = None
            self._pending_tasks = {task.key: task for task in tasks}
            self._pending_callbacks = {task.key: on_event for task in tasks}

        futures: dict[tuple[str, int], Future[bytes]] = {}
        for task in tasks:
            self.audio_bus.emit_lifecycle("audio_queued", stage_frame=task.frame, text=task.text, callback=on_event)
            futures[task.key] = executor.submit(
                self._synthesize_task,
                task,
                backend=backend,
                cancel_event=cancel_event,
            )

        thread = threading.Thread(
            target=self._playback_loop,
            name="TTS-TaskPlayback",
            daemon=True,
            args=(generation, tasks, futures, backend, executor, cancel_event, playback_stop, on_first_start, on_event),
        )
        with self._lock:
            self._playback_thread = thread
        thread.start()
        return True

    def cancel_current(self, *, reason: str = "cancelled", only_interruptible: bool = True) -> bool:
        """Dừng audio hiện tại và đánh dấu các segment pending là hủy."""

        with self._lock:
            current = self._current_task
            if current is not None and only_interruptible and not bool(getattr(current.frame, "interruptible", True)):
                return False
            pending = list(self._pending_tasks.values())
            callbacks = dict(self._pending_callbacks)
            cancel_event = self._cancel_event
            playback_stop = self._playback_stop
            executor = self._executor
            self._pending_tasks = {}
            self._pending_callbacks = {}

        cancel_event.set()
        playback_stop.set()
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

        emitted = False
        for task in pending:
            callback = callbacks.get(task.key)
            self.audio_bus.emit_lifecycle(
                "audio_cancelled",
                stage_frame=task.frame,
                text=task.text,
                reason=reason,
                callback=callback,
            )
            emitted = True
        return emitted or current is not None

    def shutdown(self) -> None:
        self.cancel_current(reason="shutdown", only_interruptible=False)

    def _build_tasks(
        self,
        frames: Iterable[Any],
        *,
        valence: float,
        arousal: float,
        stance: str,
    ) -> list[TtsSegmentTask]:
        tasks: list[TtsSegmentTask] = []
        for index, frame in enumerate(frames):
            text = str(getattr(frame, "tts_text", "") or "").strip()
            if not text:
                continue
            try:
                order = int(getattr(frame, "segment_id", index) or index)
            except (TypeError, ValueError):
                order = index
            tasks.append(
                TtsSegmentTask(
                    frame=frame,
                    text=text,
                    order=order,
                    valence=float(valence),
                    arousal=float(arousal),
                    stance=str(stance or ""),
                )
            )
        return sorted(tasks, key=lambda task: task.order)

    def _synthesize_task(self, task: TtsSegmentTask, *, backend: Any, cancel_event: threading.Event) -> bytes:
        if cancel_event.is_set():
            raise RuntimeError("cancelled_before_synth")
        cache_key = self._cache_key(task, backend=backend)
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        wav_bytes = backend.synthesize(
            task.text,
            valence=task.valence,
            arousal=task.arousal,
            stance=task.stance,
            prosody_style=str(getattr(task.frame, "prosody_style", "") or ""),
            prosody_notes=str(getattr(task.frame, "prosody_notes", "") or ""),
            turn_id=str(getattr(task.frame, "turn_id", "") or ""),
            segment_id=int(task.order),
            interruptible=bool(getattr(task.frame, "interruptible", True)),
            **_performance_kwargs(task.frame),
        )
        if cancel_event.is_set():
            raise RuntimeError("cancelled_after_synth")
        self._cache_put(cache_key, wav_bytes)
        return wav_bytes

    def _playback_loop(
        self,
        generation: int,
        tasks: list[TtsSegmentTask],
        futures: dict[tuple[str, int], Future[bytes]],
        backend: Any,
        executor: ThreadPoolExecutor,
        cancel_event: threading.Event,
        playback_stop: threading.Event,
        on_first_start: Callable[[], None] | None,
        on_event: Callable[[Any, Any], None] | None,
    ) -> None:
        first_started = False
        emotion_signature = ""
        try:
            for task in tasks:
                if cancel_event.is_set():
                    break

                try:
                    wav_bytes = self._wait_future(futures[task.key], cancel_event=cancel_event)
                except Exception as exc:
                    if cancel_event.is_set():
                        break
                    if not first_started:
                        first_started = True
                        _call_once(on_first_start)
                    self.audio_bus.emit_lifecycle(
                        "audio_failed",
                        stage_frame=task.frame,
                        text=task.text,
                        error=str(exc),
                        callback=on_event,
                    )
                    continue
                if cancel_event.is_set():
                    break

                if not wav_bytes:
                    self.audio_bus.emit_lifecycle(
                        "audio_cancelled",
                        stage_frame=task.frame,
                        text=task.text,
                        reason="empty_audio",
                        callback=on_event,
                    )
                    continue

                emotion_signature = self.audio_bus.emit_emotion_if_changed(
                    stage_frame=task.frame,
                    previous_emotion=emotion_signature,
                    callback=on_event,
                )
                if not first_started:
                    first_started = True
                    _call_once(on_first_start)

                with self._lock:
                    if generation != self._generation:
                        break
                    self._current_task = task
                    self._pending_tasks.pop(task.key, None)
                    self._pending_callbacks.pop(task.key, None)

                self.audio_bus.emit_lifecycle("audio_start", stage_frame=task.frame, text=task.text, callback=on_event)
                backend.play_audio(wav_bytes, playback_stop)
                if playback_stop.is_set() or cancel_event.is_set():
                    self.audio_bus.emit_lifecycle(
                        "audio_cancelled",
                        stage_frame=task.frame,
                        text=task.text,
                        reason="cancelled_during_playback",
                        callback=on_event,
                    )
                else:
                    self.audio_bus.emit_lifecycle("audio_done", stage_frame=task.frame, text=task.text, callback=on_event)

                with self._lock:
                    if self._current_task is task:
                        self._current_task = None
        except Exception as exc:
            if not first_started:
                first_started = True
                _call_once(on_first_start)
            failed = self._current_task or (tasks[0] if tasks else None)
            self.audio_bus.emit_lifecycle(
                "audio_failed",
                stage_frame=getattr(failed, "frame", None),
                text=str(getattr(failed, "text", "") or ""),
                error=str(exc),
                callback=on_event,
            )
            logger.warning("[tts-task-manager] playback failed: %s", exc)
        finally:
            if not first_started:
                _call_once(on_first_start)
            with self._lock:
                if generation == self._generation:
                    self._current_task = None
                    self._pending_tasks = {}
                    self._pending_callbacks = {}
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

    def _wait_future(self, future: Future[bytes], *, cancel_event: threading.Event) -> bytes:
        while not cancel_event.is_set():
            try:
                return future.result(timeout=0.05)
            except TimeoutError:
                continue
        raise RuntimeError("cancelled_while_waiting_for_synth")

    def _cache_key(self, task: TtsSegmentTask, *, backend: Any) -> str:
        signature = ""
        signer = getattr(backend, "cache_signature", None)
        if callable(signer):
            try:
                signature = str(signer() or "")
            except Exception:
                signature = ""
        payload = "\n".join(
            [
                signature,
                task.text,
                str(task.valence),
                str(task.arousal),
                task.stance,
                str(getattr(task.frame, "prosody_style", "") or ""),
                str(getattr(task.frame, "prosody_notes", "") or ""),
                repr(_performance_kwargs(task.frame)),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()

    def _cache_get(self, key: str) -> bytes | None:
        with self._lock:
            value = self._cache.get(key)
            if value:
                self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: str, wav_bytes: bytes) -> None:
        if not wav_bytes or _audio_cache_size() <= 0:
            return
        with self._lock:
            self._cache[key] = wav_bytes
            self._cache.move_to_end(key)
            limit = _audio_cache_size()
            while len(self._cache) > limit:
                self._cache.popitem(last=False)


def _prefetch_workers() -> int:
    raw = os.environ.get("ERIS_TTS_PREFETCH_WORKERS", "2").strip()
    try:
        return max(1, min(6, int(raw)))
    except ValueError:
        return 2


def _audio_cache_size() -> int:
    raw = os.environ.get("ERIS_TTS_TASK_AUDIO_CACHE_SIZE", "24").strip()
    try:
        return max(0, min(96, int(raw)))
    except ValueError:
        return 24


def _performance_kwargs(frame: Any) -> dict[str, str]:
    delivery = getattr(frame, "delivery", {}) if frame is not None else {}
    if not isinstance(delivery, dict):
        return {}
    act = delivery.get("performance_act")
    if not isinstance(act, dict):
        return {}
    return {
        "vocal_cache_kind": str(act.get("kind", "") or ""),
        "vocal_prefix": str(act.get("audible_prefix", "") or ""),
    }


def _call_once(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    try:
        callback()
    except Exception as exc:
        logger.debug("[tts-task-manager] on_first_start failed: %s", exc)


__all__ = ["TtsSegmentTask", "TtsTaskManager"]
