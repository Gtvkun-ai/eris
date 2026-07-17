# -*- coding: utf-8 -*-
"""scripted_take.py — đạo diễn take có beat, không giả vờ autonomous.

Take JSON được validate thành các beat hữu hạn rồi chạy theo pipeline thật:

    text beat -> StageFrame -> stage_segment/body_timeline -> TTS queue
    tutor_lookup -> mở đạo cụ Tutor -> lấy answer/cache -> đóng panel
    pause -> wait có cancel

Runtime chạy trên một thread riêng để panel debug không bị khóa. Mỗi take có một
cancel token; chạy take mới sẽ hủy take cũ và queue TTS hiện hành nếu có.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from runtime.stage_audio_bus import StageAudioEvent
from runtime.stage_contracts import StageFrame, StageFrameBuilder
from runtime.stage_dispatcher import StageDispatcher
from runtime.stage_output import StageOutputPipeline
from runtime.stage_protocol_adapter import playback_event, stage_segment_event, stage_state_event
from runtime.take_reaction_director import TutorReactionDirector, clean_tutor_answer
from runtime.workspace_manager import default_eris_home


_MAX_TAKE_BYTES = 512 * 1024
_MAX_BEATS = 64
_MAX_TEXT = 1600


@dataclass(frozen=True, slots=True)
class ScriptedTakeBeat:
    kind: str
    text: str = ""
    pause_after_ms: int = 0
    pause_jitter_ms: int = 0
    motion: str = ""
    emotion: str = ""
    tts_style: str = ""
    thinking_motion: str = "thinking_small"
    query: str = ""
    show_panel: bool = True
    close_panel: bool = True
    cached_answer: str = ""
    fallback_answer: str = ""
    speak_answer: bool = False
    answer_prefix: str = ""
    research: bool = False
    search: bool = False
    lead_in: str = ""
    expectation: str = ""
    locked_summary: str = ""
    afterthought: str = ""
    angle: str = ""
    use_model_rewrite: bool = False
    max_sentences: int = 2
    response_hold_ms: int = 320
    arc_phase: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def active_beat_payload(self) -> dict[str, Any]:
        return {
            "kind": "speech",
            "text": self.text,
            "pause_after_ms": self.pause_after_ms,
            "pause_jitter_ms": self.pause_jitter_ms,
            "thinking_motion": self.thinking_motion,
            "motion_intent": self.motion,
            "emotion": self.emotion,
            "tts_style": self.tts_style,
            "arc_phase": self.arc_phase,
            "pause_reason": "scripted_take_beat",
            "cancel_on_user_input": True,
        }


@dataclass(frozen=True, slots=True)
class ScriptedTakeDefinition:
    title: str
    beats: tuple[ScriptedTakeBeat, ...]
    source_path: str = ""
    profile: str = "recording"


@dataclass(frozen=True, slots=True)
class ScriptedTakeStatus:
    state: str
    take_id: str = ""
    title: str = ""
    beat_index: int = -1
    source_path: str = ""
    error: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "take_id": self.take_id,
            "title": self.title,
            "beat_index": self.beat_index,
            "source_path": self.source_path,
            "error": self.error,
        }


class ScriptedTakeLoader:
    def __init__(self, owner: Any | None = None) -> None:
        self.owner = owner

    def load(self, raw_path: str | Path) -> ScriptedTakeDefinition:
        path = self.resolve_path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy take JSON: {path}")
        if path.suffix.lower() != ".json":
            raise ValueError("Take chỉ nhận file .json, không thực thi script tùy ý.")
        if path.stat().st_size > _MAX_TAKE_BYTES:
            raise ValueError("Take JSON quá lớn; giới hạn 512 KB.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Take JSON phải là object.")
        raw_beats = payload.get("beats")
        if not isinstance(raw_beats, list) or not raw_beats:
            raise ValueError("Take cần mảng beats không rỗng.")
        if len(raw_beats) > _MAX_BEATS:
            raise ValueError(f"Take có quá nhiều beat; giới hạn {_MAX_BEATS}.")
        beats = tuple(self._parse_beat(item, index) for index, item in enumerate(raw_beats))
        title = _text(payload.get("title") or path.stem, 180)
        profile = str(payload.get("profile", "recording") or "recording").strip().lower()
        if profile not in {"recording", "conversation"}:
            profile = "recording"
        return ScriptedTakeDefinition(title=title, beats=beats, source_path=str(path), profile=profile)

    def resolve_path(self, raw_path: str | Path) -> Path:
        raw = str(raw_path or "").strip().strip('"\'')
        if not raw:
            raise ValueError("Thiếu đường dẫn take.")
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path.resolve()
        runtime_home = default_eris_home()
        source_root = Path(__file__).resolve().parent.parent
        candidates = [
            Path.cwd() / path,
            runtime_home / path,
            runtime_home / "takes" / path,
            source_root / path,
            source_root / "takes" / path,
        ]
        manager = getattr(self.owner, "workspace_manager", None)
        active_path = getattr(manager, "active_path", None)
        try:
            workspace = active_path() if callable(active_path) else None
        except Exception:
            workspace = None
        if workspace is not None:
            candidates.extend((Path(workspace) / path, Path(workspace) / "takes" / path))
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return candidates[0].resolve()

    def _parse_beat(self, raw: Any, index: int) -> ScriptedTakeBeat:
        if not isinstance(raw, Mapping):
            raise ValueError(f"Beat {index} phải là object.")
        kind = str(raw.get("kind", "") or "").strip().lower()
        if not kind:
            kind = "tutor_lookup" if raw.get("tutor_lookup") else "text" if raw.get("text") is not None else ""
        if kind in {"speech", "say"}:
            kind = "text"
        if kind in {"tutor", "lookup"}:
            kind = "tutor_lookup"
        if kind in {"reaction", "tutor_response", "tutor_react"}:
            kind = "tutor_reaction"
        if kind not in {"text", "pause", "tutor_lookup", "tutor_panel", "tutor_reaction"}:
            raise ValueError(f"Beat {index} có kind không hỗ trợ: {kind!r}")

        text = _text(raw.get("text"), _MAX_TEXT)
        query = _text(raw.get("query") or raw.get("topic") or raw.get("tutor_lookup"), 600)
        if kind == "text" and not text:
            raise ValueError(f"Beat {index} thiếu text.")
        if kind == "tutor_lookup" and not query:
            raise ValueError(f"Beat {index} thiếu query/tutor_lookup.")

        pause = _int(raw.get("pause_after_ms", raw.get("duration_ms", 0)), 0, 0, 10_000)
        return ScriptedTakeBeat(
            kind=kind,
            text=text,
            pause_after_ms=pause,
            pause_jitter_ms=_int(raw.get("pause_jitter_ms", 0), 0, 0, 1200),
            motion=_text(raw.get("motion") or raw.get("motion_intent"), 80),
            emotion=_text(raw.get("emotion"), 80),
            tts_style=_text(raw.get("tts_style"), 80),
            thinking_motion=_text(raw.get("thinking_motion") or "thinking_small", 80),
            query=query,
            show_panel=bool(raw.get("show_panel", True)),
            close_panel=bool(raw.get("close_panel", True)),
            cached_answer=_text(raw.get("cached_answer"), 4000),
            fallback_answer=_text(raw.get("fallback_answer"), 4000),
            speak_answer=bool(raw.get("speak_answer", False)),
            answer_prefix=_text(raw.get("answer_prefix"), 500),
            research=bool(raw.get("research", False)),
            search=bool(raw.get("search", False)),
            lead_in=_text(raw.get("lead_in"), 120),
            expectation=_text(raw.get("expectation"), 500),
            locked_summary=_text(raw.get("locked_summary") or raw.get("summary"), 1000),
            afterthought=_text(raw.get("afterthought"), 500),
            angle=_text(raw.get("angle"), 500),
            use_model_rewrite=bool(raw.get("use_model_rewrite", raw.get("use_model", False))),
            max_sentences=_int(raw.get("max_sentences", 2), 2, 1, 3),
            response_hold_ms=_int(raw.get("response_hold_ms", 320), 320, 80, 2000),
            arc_phase=_text(raw.get("arc_phase"), 80),
            metadata={str(k): v for k, v in raw.items() if str(k) not in {
                "kind", "text", "pause_after_ms", "pause_jitter_ms", "duration_ms", "motion", "motion_intent",
                "emotion", "tts_style", "thinking_motion", "query", "topic", "tutor_lookup",
                "show_panel", "close_panel", "cached_answer", "fallback_answer", "speak_answer", "answer_prefix",
                "research", "search", "lead_in", "expectation", "locked_summary", "summary",
                "afterthought", "angle", "use_model_rewrite", "use_model", "max_sentences",
                "response_hold_ms", "arc_phase",
            }},
        )


class ScriptedTakeRuntime:
    """Chạy take trên các adapter đã có của Coordinator."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.loader = ScriptedTakeLoader(owner)
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = ScriptedTakeStatus("idle")
        self._active_take_id = ""
        self._open_tutor: tuple[str, int, str] | None = None
        self.reaction_director = TutorReactionDirector(owner)

    def start_file(self, path: str | Path) -> ScriptedTakeStatus:
        take = self.loader.load(path)
        self.cancel("replaced")
        cancel = threading.Event()
        take_id = f"take_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._cancel = cancel
            self._active_take_id = take_id
            self._status = ScriptedTakeStatus(
                "starting", take_id=take_id, title=take.title, source_path=take.source_path,
            )
            thread = threading.Thread(
                target=self._run_guarded,
                name=f"ERIS-ScriptedTake-{take_id[-6:]}",
                daemon=True,
                args=(take, take_id, cancel),
            )
            self._thread = thread
        thread.start()
        return self.status()

    def run_definition(self, take: ScriptedTakeDefinition) -> ScriptedTakeStatus:
        """Chạy đồng bộ cho test/tooling; không mở thread."""
        self.cancel("replaced")
        cancel = threading.Event()
        take_id = f"take_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._cancel = cancel
            self._active_take_id = take_id
            self._status = ScriptedTakeStatus(
                "starting", take_id=take_id, title=take.title, source_path=take.source_path,
            )
        self._run_guarded(take, take_id, cancel)
        return self.status()

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._lock:
            thread = self._thread
            active = thread is not None and thread.is_alive()
            self._cancel.set()
            active_take_id = self._active_take_id
        self._cancel_tts(reason)
        self._close_open_tutor(expected_take_id=active_take_id)
        if active:
            self._set_status(state="cancelled", error=reason)
        return active

    def status(self) -> ScriptedTakeStatus:
        with self._lock:
            return self._status

    def _run_guarded(self, take: ScriptedTakeDefinition, take_id: str, cancel: threading.Event) -> None:
        context: dict[str, str] = {
            "tutor_answer": "",
            "tutor_answer_raw": "",
            "tutor_summary": "",
            "take_title": take.title,
        }
        current_index = 0
        try:
            self._set_status(
                expected_take_id=take_id,
                state="running", take_id=take_id, title=take.title,
                source_path=take.source_path, beat_index=0, error="",
            )
            self._emit_take_state("scripted_take_started", take_id, take, beat_index=0)
            index = 0
            while index < len(take.beats) and not cancel.is_set():
                current_index = index
                self._set_status(expected_take_id=take_id, beat_index=index)
                beat = take.beats[index]
                if beat.kind == "text":
                    group: list[tuple[int, ScriptedTakeBeat]] = []
                    while index < len(take.beats) and take.beats[index].kind == "text":
                        group.append((index, take.beats[index]))
                        index += 1
                    self._run_text_group(take, take_id, group, context, cancel)
                    continue
                if beat.kind == "pause":
                    self._wait(cancel, beat.pause_after_ms)
                elif beat.kind == "tutor_panel":
                    action = str(beat.metadata.get("action", beat.text or "open") or "open").strip().lower()
                    self._emit_tutor_prop(action, take_id=take_id, beat_index=index, query=beat.query)
                elif beat.kind == "tutor_lookup":
                    next_kind = take.beats[index + 1].kind if index + 1 < len(take.beats) else ""
                    self._run_tutor_beat(
                        take,
                        take_id,
                        index,
                        beat,
                        context,
                        cancel,
                        defer_close=next_kind == "tutor_reaction",
                    )
                elif beat.kind == "tutor_reaction":
                    self._run_tutor_reaction_beat(take, take_id, index, beat, context, cancel)
                index += 1
            if cancel.is_set():
                self._emit_take_state("scripted_take_cancelled", take_id, take, beat_index=current_index)
                self._set_status(expected_take_id=take_id, state="cancelled")
            else:
                self._close_open_tutor(expected_take_id=take_id)
                self._emit_take_state("scripted_take_finished", take_id, take, beat_index=len(take.beats) - 1)
                self._set_status(
                    expected_take_id=take_id,
                    state="completed",
                    beat_index=len(take.beats) - 1,
                )
        except Exception as exc:
            self._log("warning", "[scripted-take] failed: %s", exc)
            self._close_open_tutor(expected_take_id=take_id)
            self._emit_take_state("scripted_take_failed", take_id, take, beat_index=current_index, error=str(exc))
            self._set_status(expected_take_id=take_id, state="failed", error=str(exc))
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _run_text_group(
        self,
        take: ScriptedTakeDefinition,
        take_id: str,
        group: list[tuple[int, ScriptedTakeBeat]],
        context: dict[str, str],
        cancel: threading.Event,
    ) -> None:
        builder = StageFrameBuilder(language_hint=self._language())
        pipeline = StageOutputPipeline(profile=take.profile)
        frames: list[StageFrame] = []
        for beat_index, beat in group:
            rendered = _render_template(beat.text, context)
            decision = SimpleNamespace(
                text=rendered,
                intent="scripted_take",
                animation=beat.motion or "stand",
                should_speak=True,
                delivery_hint=beat.tts_style,
                stage_motion=beat.motion,
            )
            active_beat = beat.active_beat_payload()
            active_beat["take_beat_index"] = beat_index
            frame = builder.build(
                decision,
                payload={
                    "text": rendered,
                    "should_speak": True,
                    "delivery_hint": beat.tts_style,
                    "stage_motion": beat.motion,
                    "preset_emotion": beat.emotion,
                    "scripted_beat": active_beat,
                },
                channel="scripted_take",
                turn_id=take_id,
                segment_id=beat_index,
            )
            # Mỗi JSON beat là một đơn vị đạo diễn. Nếu câu trong beat phải tách
            # thêm, cấp seq liên tục toàn take; không để beat sau quay lại seq=0.
            for subframe in pipeline.frames_for_tts(frame):
                frames.append(replace(subframe, segment_id=len(frames)))

        engine = self._tts_engine()
        has_tts = engine is not None and bool(getattr(engine, "_ok", False)) and not cancel.is_set()

        # Stage bus được biết trước toàn bộ segment để debug/prefetch. Godot thì
        # không: text + body timeline chỉ được gửi lúc audio_start của đúng
        # segment. Nếu phát cả nhóm ngay tại đây, bubble nhảy tới câu cuối và ba
        # motion chồng lên nhau trước khi Eris kịp nói câu đầu. Rất hiệu quả nếu
        # mục tiêu là dựng một con rối bị ma nhập, không phải performer.
        self._emit_frames(
            frames,
            take_id=take_id,
            title=take.title,
            send_transport=not has_tts,
        )
        if not has_tts:
            self._wait(cancel, sum(max(0, beat.pause_after_ms) for _, beat in group))
            return

        dispatcher = StageDispatcher(profile=take.profile)
        scheduled = dispatcher.dispatch_tts(
            frames,
            tts_engine=engine,
            valence=0.0,
            arousal=0.35,
            stance="scripted_take",
            on_event=self._handle_tts_event,
        )
        if not scheduled:
            # Backend TTS vừa mất khả năng queue sau khi ta đã quyết định sync
            # theo audio. Fail mềm về payload thường để take vẫn nhìn thấy được.
            for frame in frames:
                self._send_frame_to_transport(
                    frame, take_id=take_id, title=take.title, sync="dispatch_fallback"
                )
            self._wait(cancel, sum(max(0, beat.pause_after_ms) for _, beat in group))
            return

        manager = getattr(engine, "task_manager", None)
        waiter = getattr(manager, "wait_until_idle", None)
        if callable(waiter):
            waiter(timeout=120.0)
        # Pause của task cuối không được continuation manager chạy vì không còn
        # segment kế tiếp. Thi hành tại ranh giới group để Tutor không bật quá sớm.
        if group and group[-1][1].pause_after_ms > 0 and not cancel.is_set():
            self._emit_manual_thinking(frames[-1] if frames else None, group[-1][1], cancel)

    def _run_tutor_beat(
        self,
        take: ScriptedTakeDefinition,
        take_id: str,
        beat_index: int,
        beat: ScriptedTakeBeat,
        context: dict[str, str],
        cancel: threading.Event,
        defer_close: bool = False,
    ) -> None:
        query = _render_template(beat.query, context)
        if beat.show_panel:
            self._emit_tutor_prop("open", take_id=take_id, beat_index=beat_index, query=query)
            self._emit_tutor_prop("asking", take_id=take_id, beat_index=beat_index, query=query)
        answer = beat.cached_answer
        if not answer and not cancel.is_set():
            request = getattr(self.owner, "request_tutor_answer", None)
            if callable(request):
                answer = str(request(
                    query,
                    context=f"Scripted take: {take.title}",
                    research=beat.research,
                    search=beat.search,
                ) or "").strip()
        if not answer:
            answer = beat.fallback_answer
        if cancel.is_set():
            self._close_open_tutor(expected_take_id=take_id)
            return
        clean_answer = clean_tutor_answer(answer, max_sentences=3)
        context["tutor_answer_raw"] = answer
        # Compatibility: template cũ {{tutor_answer}} vẫn chạy, nhưng không còn
        # đọc bullet/URL/citation như một robot đang tuyên bố danh mục tài liệu.
        context["tutor_answer"] = clean_answer
        if beat.show_panel:
            self._emit_tutor_prop(
                "answered" if answer else "failed",
                take_id=take_id,
                beat_index=beat_index,
                query=query,
                answer=answer,
            )
        if beat.speak_answer and answer and not cancel.is_set():
            spoken = f"{beat.answer_prefix} {clean_answer}".strip()
            speech_beat = ScriptedTakeBeat(
                kind="text", text=spoken, pause_after_ms=beat.pause_after_ms,
                motion=beat.motion or "read", emotion=beat.emotion or "curious",
                tts_style=beat.tts_style or "curious_explain",
            )
            self._run_text_group(take, take_id, [(beat_index, speech_beat)], context, cancel)
        elif beat.pause_after_ms > 0:
            self._wait(cancel, beat.pause_after_ms)
        if beat.show_panel and beat.close_panel and not defer_close:
            self._emit_tutor_prop("close", take_id=take_id, beat_index=beat_index, query=query, answer=answer)

    def _run_tutor_reaction_beat(
        self,
        take: ScriptedTakeDefinition,
        take_id: str,
        beat_index: int,
        beat: ScriptedTakeBeat,
        context: dict[str, str],
        cancel: threading.Event,
    ) -> None:
        """Biến knowledge thành reaction arc thay vì đọc nguyên answer."""

        raw_answer = context.get("tutor_answer_raw", "") or context.get("tutor_answer", "")
        query = str((self._open_tutor or (take_id, beat_index, ""))[2] or beat.query or "")
        reaction = self.reaction_director.direct(
            query=query,
            answer=raw_answer,
            lead_in=beat.lead_in or "À...",
            expectation=beat.expectation,
            locked_summary=beat.locked_summary,
            afterthought=beat.afterthought,
            angle=beat.angle,
            use_model=beat.use_model_rewrite,
            max_sentences=beat.max_sentences,
            response_hold_ms=beat.response_hold_ms,
            final_pause_ms=beat.pause_after_ms or 760,
            emotion=beat.emotion or "curious_warm",
            motion=beat.motion or "assimilate",
            tts_style=beat.tts_style or "curious_discovery",
        )
        context["tutor_summary"] = reaction.spoken_summary
        context["tutor_answer"] = reaction.clean_answer or context.get("tutor_answer", "")

        if self._open_tutor is not None:
            self._emit_tutor_prop(
                "assimilating",
                take_id=take_id,
                beat_index=beat_index,
                query=query,
                answer=raw_answer,
            )
        if not self._wait(cancel, reaction.pre_hold_ms):
            return

        speech_beats: list[tuple[int, ScriptedTakeBeat]] = []
        for line in reaction.lines:
            speech_beats.append((
                beat_index,
                ScriptedTakeBeat(
                    kind="text",
                    text=line.text,
                    pause_after_ms=line.pause_after_ms,
                    pause_jitter_ms=0,
                    motion=line.motion,
                    emotion=line.emotion,
                    tts_style=line.tts_style,
                    thinking_motion="thinking_small",
                    arc_phase=line.phase,
                    metadata={"reaction_source": reaction.source},
                ),
            ))
        self._run_text_group(take, take_id, speech_beats, context, cancel)
        if beat.close_panel:
            self._close_open_tutor(expected_take_id=take_id)

    def _emit_frames(
        self,
        frames: list[StageFrame],
        *,
        take_id: str,
        title: str,
        send_transport: bool = True,
    ) -> None:
        bus = getattr(self.owner, "stage_event_bus", None)
        for frame in frames:
            if bus is not None:
                try:
                    bus.emit(stage_segment_event(frame, segment_count=len(frames)))
                except Exception:
                    pass
            if send_transport:
                self._send_frame_to_transport(
                    frame, take_id=take_id, title=title, sync="immediate_no_tts"
                )

    def _send_frame_to_transport(
        self,
        frame: StageFrame,
        *,
        take_id: str,
        title: str,
        sync: str = "audio_start",
    ) -> None:
        transport = getattr(self.owner, "transport", None)
        sender = getattr(transport, "send_json", None)
        if not callable(sender):
            return
        payload = {
            "parse_mode": "scripted_take",
            "should_speak": True,
            "animation": _legacy_body_animation(frame),
            "text": frame.display_text,
            "memory_text": frame.memory_text,
            "scripted_take": {
                "take_id": take_id,
                "title": title,
                "beat_index": int(
                    ((frame.delivery.get("active_beat") or {}).get("take_beat_index", frame.segment_id))
                    if isinstance(frame.delivery, dict) else frame.segment_id
                ),
                "arc_phase": str(
                    ((frame.delivery.get("active_beat") or {}).get("arc_phase", ""))
                    if isinstance(frame.delivery, dict) else ""
                ),
                "sync": sync,
            },
        }
        payload.update(frame.to_payload_patch())
        try:
            sender(payload)
        except Exception:
            pass

    def _send_lifecycle_to_transport(self, event: Any, frame: StageFrame | None) -> None:
        """Đẩy các state không có câu nói sang Godot bằng hình dạng legacy-safe."""

        if frame is None:
            return
        event_type = str(getattr(event, "type", "") or "")
        protocol = playback_event(event, stage_frame=frame)
        data = dict(protocol.data or {})
        timeline = data.get("body_timeline") if isinstance(data.get("body_timeline"), Mapping) else {}
        transport = getattr(self.owner, "transport", None)
        sender = getattr(transport, "send_json", None)
        if not callable(sender):
            return
        payload = protocol.to_payload()
        # Body hiện tại đọc text/animation theo contract cũ nhưng đã hiểu
        # body_timeline protocol v2. Gửi cả hai thay vì bắt frontend đoán tiếp.
        payload.update({
            "parse_mode": "scripted_take_lifecycle",
            "should_speak": False,
            "animation": protocol.motion or "stand",
            "text": "",
        })
        if timeline:
            payload["body_timeline"] = dict(timeline)
        try:
            sender(payload)
        except Exception:
            pass

    def _emit_tutor_prop(
        self,
        stage: str,
        *,
        take_id: str,
        beat_index: int,
        query: str = "",
        answer: str = "",
    ) -> None:
        normalized_stage = str(stage or "").strip().lower()
        with self._lock:
            if normalized_stage == "open":
                self._open_tutor = (take_id, beat_index, query)
            elif normalized_stage == "close":
                current = self._open_tutor
                if current is not None and current[0] == take_id:
                    self._open_tutor = None
        payload = {
            "take_id": take_id,
            "beat_index": beat_index,
            "stage": stage,
            "query": query,
            "answer": answer[:1200],
        }
        bus = getattr(self.owner, "stage_event_bus", None)
        if bus is not None:
            try:
                bus.emit(stage_state_event(event_type="tutor_prop", reason=stage, data=payload))
            except Exception:
                pass
        transport = getattr(self.owner, "transport", None)
        send = getattr(transport, "send_json", None)
        if callable(send):
            try:
                send({
                    "parse_mode": "tutor_event",
                    "should_speak": False,
                    "animation": "read" if stage not in {"close", "failed"} else "stand",
                    "tutor": {
                        "episode_id": take_id,
                        "stage": stage,
                        "question_preview": query[:120],
                        "question": query,
                        "answer": answer[:400],
                        "claims": 0,
                        "fail_reason": "" if stage != "failed" else "no_answer",
                        "scripted_take": True,
                        "beat_index": beat_index,
                    },
                })
            except Exception:
                pass

    def _close_open_tutor(self, *, expected_take_id: str = "") -> bool:
        with self._lock:
            current = self._open_tutor
        if current is None:
            return False
        take_id, beat_index, query = current
        if expected_take_id and take_id != expected_take_id:
            return False
        self._emit_tutor_prop(
            "close",
            take_id=take_id,
            beat_index=beat_index,
            query=query,
        )
        return True

    def _emit_take_state(
        self,
        event_type: str,
        take_id: str,
        take: ScriptedTakeDefinition,
        *,
        beat_index: int,
        error: str = "",
    ) -> None:
        bus = getattr(self.owner, "stage_event_bus", None)
        if bus is None:
            return
        try:
            bus.emit(stage_state_event(
                event_type=event_type,
                reason=error,
                data={
                    "take_id": take_id,
                    "title": take.title,
                    "beat_index": beat_index,
                    "source_path": take.source_path,
                    "profile": take.profile,
                },
            ))
        except Exception:
            pass

    def _emit_manual_thinking(self, frame: StageFrame | None, beat: ScriptedTakeBeat, cancel: threading.Event) -> None:
        if frame is None:
            self._wait(cancel, beat.pause_after_ms)
            return
        start = StageAudioEvent(
            type="thinking_started", turn_id=frame.turn_id, segment_id=frame.segment_id,
            reason="scripted_take_boundary",
        )
        self._handle_tts_event(start, frame)
        cancelled = cancel.wait(beat.pause_after_ms / 1000.0)
        end = StageAudioEvent(
            type="continuation_cancelled" if cancelled else "thinking_finished",
            turn_id=frame.turn_id, segment_id=frame.segment_id,
            reason="cancelled" if cancelled else "scripted_take_boundary_elapsed",
        )
        self._handle_tts_event(end, frame)

    def _handle_tts_event(self, event: Any, frame: StageFrame | None = None) -> None:
        event_type = str(getattr(event, "type", "") or "")
        if event_type == "audio_start" and frame is not None:
            with self._lock:
                title = self._status.title
            self._send_frame_to_transport(
                frame,
                take_id=str(getattr(frame, "turn_id", "") or self._active_take_id),
                title=title,
            )
        elif event_type in {"thinking_started", "thinking_finished", "continuation_cancelled"}:
            self._send_lifecycle_to_transport(event, frame)

        handler = getattr(self.owner, "_handle_tts_playback_event", None)
        if callable(handler):
            handler(event, stage_frame=frame)
            return
        bus = getattr(self.owner, "stage_event_bus", None)
        if bus is not None:
            try:
                bus.emit(playback_event(event, stage_frame=frame))
            except Exception:
                pass

    def _cancel_tts(self, reason: str) -> None:
        engine = self._tts_engine()
        manager = getattr(engine, "task_manager", None) if engine is not None else None
        cancel = getattr(manager, "cancel_current", None)
        if callable(cancel):
            try:
                cancel(reason=reason, only_interruptible=False)
            except Exception:
                pass

    def _tts_engine(self) -> Any:
        getter = getattr(self.owner, "_get_runtime_provider", None)
        if callable(getter):
            try:
                provider = getter("speech")
                engine = getattr(provider, "engine", None) if provider is not None else None
                if engine is not None:
                    return engine
            except Exception:
                pass
        return getattr(self.owner, "tts_engine", None)

    def _language(self) -> str:
        from runtime.runtime_settings_store import runtime_text
        return runtime_text("tts", "language", default="vi") or "vi"

    def _wait(self, cancel: threading.Event, delay_ms: int) -> bool:
        if delay_ms <= 0:
            return not cancel.is_set()
        return not cancel.wait(delay_ms / 1000.0)

    def _set_status(self, *, expected_take_id: str | None = None, **changes: Any) -> None:
        with self._lock:
            # Take cũ có thể vừa thoát sau khi take mới đã bắt đầu. Không cho
            # thread cũ ghi đè status của take mới thành cancelled/completed.
            if expected_take_id is not None and self._active_take_id != expected_take_id:
                return
            current = self._status.to_payload()
            current.update({key: value for key, value in changes.items() if value is not None})
            self._status = ScriptedTakeStatus(**current)

    def _log(self, level: str, message: str, *args: Any) -> None:
        logger = getattr(self.owner, "logger", None)
        method = getattr(logger, level, None)
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass



def _legacy_body_animation(frame: StageFrame) -> str:
    """Chọn animation thật cho payload Godot cũ, giữ motion abstract ở stage."""

    timeline = getattr(frame, "body_timeline", {})
    if isinstance(timeline, Mapping):
        events = timeline.get("events")
        if isinstance(events, list):
            for item in events:
                if isinstance(item, Mapping):
                    name = str(item.get("name", "") or "").strip()
                    if name:
                        return name
    motion = str(getattr(frame, "motion", "") or "").strip()
    return motion if motion in {
        "stand", "sit", "read", "stand_walk", "hop", "jump", "sleep",
        "sad", "food", "affection", "clone", "divine", "idle",
    } else "stand"


def _render_template(text: str, context: Mapping[str, str]) -> str:
    rendered = str(text or "")
    for key, value in context.items():
        rendered = rendered.replace("{{" + str(key) + "}}", str(value or ""))
    return " ".join(rendered.split()).strip()


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[: max(1, int(limit))]


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


__all__ = [
    "ScriptedTakeBeat",
    "ScriptedTakeDefinition",
    "ScriptedTakeLoader",
    "ScriptedTakeRuntime",
    "ScriptedTakeStatus",
]
