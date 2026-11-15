# -*- coding: utf-8 -*-
"""Evidence/grounding bridge cho foreground V12.

Module chỉ thu sensor/source evidence và dựng SourceGroundingReport. Nó không
phân loại social intent, không chọn câu trả lời và không tạo public fallback.
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from runtime.source_grounding import SourceGroundingEngine


class ConversationEvidenceAssembler:
    def __init__(self, host: Any) -> None:
        self.host = host

    def assemble_chat(self, user_text: str, *, previous_public_turn: Any = None) -> dict[str, Any]:
        host = self.host
        evidence_started = time.perf_counter()
        text = str(user_text or "")
        snapshot = self._telemetry_snapshot()
        if snapshot is not None:
            try:
                host._chat_snapshot_for_vision = snapshot
            except Exception:
                pass

        screen_data_uri = ""
        capture = getattr(host, "_capture_screen_frame_for_chat", None)
        if callable(capture):
            try:
                screen_data_uri = str(capture(text, previous_public_turn=previous_public_turn) or "")
            except Exception as exc:
                self._debug("screen_capture", exc)

        engine = getattr(host, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            try:
                host.source_grounding_engine = engine
            except Exception:
                pass

        memory_resonance = None
        memory_started = time.perf_counter()
        recall = getattr(host, "_recall_memory_resonance", None)
        if callable(recall):
            try:
                memory_resonance = recall(snapshot=snapshot, user_text=text, channel="chat")
            except Exception as exc:
                self._debug("memory_resonance", exc)

        memory_finished = time.perf_counter()
        report = None
        builder = getattr(host, "_build_chat_source_grounding_report", None)
        if callable(builder):
            try:
                report = builder(
                    user_text=text,
                    frame=None,
                    snapshot=snapshot,
                    memory_resonance=memory_resonance,
                    screen_image_data_uri=screen_data_uri,
                )
            except Exception as exc:
                self._debug("source_grounding", exc)
        if report is None:
            try:
                report = engine.analyze(text, runtime_state=snapshot, allow_web=False, attach_to_frame=False)
            except Exception as exc:
                self._debug("source_grounding_fallback", exc)

        vision_status = ""
        render_status = getattr(host, "_chat_vision_status_prompt_context", None)
        if callable(render_status):
            try:
                vision_status = str(render_status(screen_image_data_uri=screen_data_uri) or "")
            except Exception as exc:
                self._debug("vision_status", exc)

        game_context = ""
        try:
            from screen.game_knowledge import detect_game_from_window, format_game_prompt_context
            window_title = ""
            process_name = ""
            if snapshot is not None:
                window_title = str(getattr(snapshot, "active_window_title", "") or getattr(snapshot, "active_window", "") or "")
                process_name = str(getattr(snapshot, "active_app", "") or "")
            if not window_title and not process_name:
                telemetry = getattr(host, "telemetry_service", None)
                if telemetry is not None:
                    get_fg = getattr(telemetry, "_get_foreground_window", None) or getattr(telemetry, "_resolve_foreground_identity", None)
                    if callable(get_fg):
                        fg = get_fg() or {}
                        window_title = str(fg.get("title", "") or "")
                        process_name = str(fg.get("process", "") or fg.get("process_name", "") or "")
            if not window_title and not process_name:
                window_title = str(getattr(host, "_last_game_title", "") or "")
                process_name = str(getattr(host, "_last_game_process", "") or "")
            game_profile = detect_game_from_window(window_title, process_name)
            if game_profile is not None:
                game_context = format_game_prompt_context(game_profile)
        except Exception as exc:
            self._debug("game_knowledge", exc)

        vision_perception_context = ""
        try:
            from screen.vision_perception_worker import ensure_vision_perception_service
            v_snap = ensure_vision_perception_service().get_latest_snapshot()
            if v_snap is not None and not v_snap.is_stale(max_age_seconds=180.0):
                vision_perception_context = v_snap.prompt_context()
        except Exception as exc:
            self._debug("vision_perception", exc)

        prompt_context = str(getattr(report, "prompt_context", "") or "") if report is not None else ""
        if vision_perception_context and "[VISION_STATUS]" in vision_status:
            vision_status = ""
        prompt_context = "\n\n".join(
            part for part in (prompt_context, vision_status, vision_perception_context, game_context) if part.strip()
        )[:14000]
        logger_fn = getattr(host, "_log_chat_source_grounding", None)
        if callable(logger_fn) and report is not None:
            try:
                logger_fn(report)
            except Exception:
                pass
        from runtime.diagnostic_logging import safe_log
        safe_log(getattr(host, "logger", None), "info",
                 "[chat-stage] evidence_ms=%d memory_recall_ms=%d",
                 int((time.perf_counter() - evidence_started) * 1000),
                 int((memory_finished - memory_started) * 1000))
        return {
            "source_grounding_context": prompt_context,
            "screen_image_data_uri": screen_data_uri,
            "__source_grounding_report": report,
            "__source_grounding_engine": engine,
        }

    def assemble_autonomous(self) -> dict[str, Any]:
        """Grounding report nhẹ cho self-turn; lấy ambient telemetry và background vision."""
        host = self.host
        snapshot = self._telemetry_snapshot()
        engine = getattr(host, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            try:
                host.source_grounding_engine = engine
            except Exception:
                pass
        runtime_facts = ()
        build_runtime = getattr(host, "_chat_runtime_grounding_facts", None)
        if callable(build_runtime):
            try:
                runtime_facts = tuple(build_runtime(snapshot, "") or ())
            except Exception as exc:
                self._debug("autonomous_runtime_facts", exc)
        try:
            report = engine.analyze(
                "", runtime_facts=runtime_facts, runtime_state=snapshot,
                allow_web=False, attach_to_frame=False,
            )
        except Exception as exc:
            self._debug("autonomous_grounding", exc)
            report = None

        game_context = ""
        try:
            from screen.game_knowledge import detect_game_from_window, format_game_prompt_context
            window_title = ""
            process_name = ""
            if snapshot is not None:
                window_title = str(getattr(snapshot, "active_window_title", "") or getattr(snapshot, "active_window", "") or "")
                process_name = str(getattr(snapshot, "active_app", "") or "")
            if not window_title and not process_name:
                telemetry = getattr(host, "telemetry_service", None)
                if telemetry is not None:
                    get_fg = getattr(telemetry, "_get_foreground_window", None) or getattr(telemetry, "_resolve_foreground_identity", None)
                    if callable(get_fg):
                        fg = get_fg() or {}
                        window_title = str(fg.get("title", "") or "")
                        process_name = str(fg.get("process", "") or fg.get("process_name", "") or "")
            if not window_title and not process_name:
                window_title = str(getattr(host, "_last_game_title", "") or "")
                process_name = str(getattr(host, "_last_game_process", "") or "")
            game_profile = detect_game_from_window(window_title, process_name)
            if game_profile is not None:
                game_context = format_game_prompt_context(game_profile)
        except Exception as exc:
            self._debug("autonomous_game_knowledge", exc)

        vision_perception_context = ""
        try:
            from screen.vision_perception_worker import ensure_vision_perception_service
            v_snap = ensure_vision_perception_service().get_latest_snapshot()
            if v_snap is not None and not v_snap.is_stale(max_age_seconds=180.0):
                vision_perception_context = v_snap.prompt_context()
        except Exception as exc:
            self._debug("autonomous_vision_perception", exc)

        prompt_context = "\n\n".join(
            part for part in (
                str(getattr(report, "prompt_context", "") or ""),
                vision_perception_context,
                game_context,
            ) if part.strip()
        )[:14000]

        return {
            "source_grounding_context": prompt_context,
            "__source_grounding_report": report,
            "__source_grounding_engine": engine,
        }

    def _telemetry_snapshot(self) -> Any | None:
        host = self.host
        service = getattr(host, "telemetry_service", None)
        capture = getattr(service, "capture_snapshot", None)
        if not callable(capture):
            return None
        try:
            return capture(
                mood_score=getattr(host, "mood_score", 0.0),
                inferred_pos_x=getattr(host, "inferred_pos_x", 0.0),
            )
        except TypeError:
            try:
                return capture()
            except Exception as exc:
                self._debug("telemetry_snapshot", exc)
                return None
        except Exception as exc:
            self._debug("telemetry_snapshot", exc)
            return None

    def _debug(self, operation: str, exc: Exception) -> None:
        logger = getattr(self.host, "logger", None)
        fn = getattr(logger, "debug", None) if logger is not None else None
        if callable(fn):
            try:
                fn("[conversation-evidence] %s degraded: %s", operation, exc)
            except Exception:
                pass


def ensure_conversation_evidence_assembler(host: Any) -> ConversationEvidenceAssembler:
    existing = getattr(host, "conversation_evidence_assembler", None)
    if isinstance(existing, ConversationEvidenceAssembler):
        return existing
    assembler = ConversationEvidenceAssembler(host)
    try:
        host.conversation_evidence_assembler = assembler
    except Exception:
        pass
    return assembler


__all__ = ["ConversationEvidenceAssembler", "ensure_conversation_evidence_assembler"]
