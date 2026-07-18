# -*- coding: utf-8 -*-
"""Nối SessionRitualReport với Decision/Stage/TTS cho greeting preset.

Module này cố ý nhỏ: cognition chọn preset; runtime chỉ phát nó. Nếu report có
anchor động thì không tạo Decision preset, Qwen vẫn giữ quyền viết câu mở đầu.
"""

from __future__ import annotations

import logging
from typing import Any

from cortex.greeting_presets import GreetingPresetResolver
from cortex.startup_anchor_gate import StartupAnchorGate
from domain import Decision

logger = logging.getLogger("GreetingPreset.Runtime")


def decision_from_session_ritual(report: Any) -> Decision | None:
    preset_id = str(getattr(report, "greeting_preset_id", "") or "").strip()
    text = str(getattr(report, "greeting_preset_text", "") or "").strip()
    if not preset_id or not text:
        return None

    # Defense in depth: resolver đã lọc preset, nhưng report có thể được tạo bởi
    # code cũ hoặc dữ liệu cache. Gate chỉ audit; tuyệt đối không rewrite preset
    # cuối nữa. Nếu câu thiếu neo, ghi trace để soi, còn text/audio vẫn đi nguyên.
    frame = getattr(report, "greeting_frame", None)
    anchor_audit = ""
    if frame is not None:
        gate = StartupAnchorGate()
        verdict = gate.validate(text, frame)
        if verdict.unsupported_presuppositions:
            anchor_audit = "; startup_anchor_audit=" + ",".join(verdict.unsupported_presuppositions)

    return Decision(
        text=text,
        animation="stand",
        intent="session_ritual",
        reasoning_tags=("session_ritual", "startup_greeting", "greeting_preset"),
        should_speak=True,
        confidence=1.0,
        parse_mode="session_ritual_preset",
        debug_trace=f"session_ritual_layer; source=preset; preset_id={preset_id}; tone={getattr(report, 'tone', '')}{anchor_audit}",
        delivery_hint=str(getattr(report, "greeting_preset_prosody", "") or ""),
        stage_motion=str(getattr(report, "greeting_preset_motion", "") or ""),
        speech_act="greeting_start",
        preset_id=preset_id,
        audio_asset=str(getattr(report, "greeting_audio_asset", "") or ""),
        preset_emotion=str(getattr(report, "greeting_preset_emotion", "") or ""),
    )


def emit_session_ritual_preset(runtime: Any, report: Any) -> bool:
    """Phát preset ngay và bỏ qua call LLM startup nếu report đã chọn preset."""
    decision = decision_from_session_ritual(report)
    if decision is None:
        return False
    try:
        runtime.last_text = decision.text
        spoken_at = __import__("time").time()
        note_spoken = getattr(runtime, "_note_autonomous_spoken", None)
        if callable(note_spoken):
            note_spoken(now=spoken_at)
        block = getattr(runtime, "_block_autonomous_presence_after_public_turn", None)
        if callable(block):
            block(now=spoken_at)
        runtime._send_decision_to_body(decision, channel="session_ritual")
        resolver = getattr(getattr(runtime, "session_ritual_engine", None), "preset_resolver", None)
        if resolver is None:
            resolver = GreetingPresetResolver()
        resolver.mark_used(decision.preset_id)
        audio_mode = "asset_then_live_fallback" if str(decision.audio_asset or "").strip() else "live_tts"
        logger.info(
            "[startup] greeting=%s tone=%s situation=%s audio=%s",
            decision.preset_id,
            str(getattr(report, "tone", "") or "unknown"),
            str(getattr(getattr(report, "greeting_frame", None), "situation", "") or "unknown"),
            audio_mode,
        )
        return True
    except Exception as exc:
        logger.warning("[greeting-preset] emit failed, fallback to Qwen: %s", exc)
        return False


__all__ = ["decision_from_session_ritual", "emit_session_ritual_preset"]
