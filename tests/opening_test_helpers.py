# -*- coding: utf-8 -*-
"""Fixture nhỏ cho test Opening Director; giữ dữ liệu rõ thay vì mock cả vũ trụ."""
from __future__ import annotations

from typing import Any

from runtime.ai_orchestrated.opening_contracts import OpeningInput


def make_opening_input(**overrides: Any) -> OpeningInput:
    payload: dict[str, Any] = {
        "event": {
            "kind": "startup",
            "session_id": "test-session",
            "timestamp": 100.0,
            "seconds_since_last_session": 1800,
            "restart_detected": False,
            "greeted_recently": False,
        },
        "screen_evidence": [
            {
                "evidence_id": "screen:facebook",
                "source": "screen",
                "kind": "foreground_app",
                "subject": "Facebook",
                "claim": "Facebook là ứng dụng foreground",
                "confidence": 0.91,
                "freshness_ms": 620,
                "privacy_class": "ordinary_ui",
                "allowed_for_surface": True,
            }
        ],
        "continuity": {
            "consent_scope": "session_only",
            "active_goal": "",
            "open_loops": [],
            "recent_public_history": [],
            "last_session_summary": "không được giữ khi chỉ consent theo session",
        },
        "session_state": {
            "time_of_day": "afternoon",
            "weekday_vi": "Chủ nhật",
            "chat_mode": False,
            "user_speaking": False,
            "public_turn_busy": False,
            "startup_force_speak": True,
            "runtime_health": "normal",
        },
        "recent_moves": {},
        "user_signals": {
            "availability": "available",
            "recent_laugh": False,
            "recent_counter_tease": False,
            "recent_low_engagement": False,
            "explicit_boundary": False,
            "recent_barge_in": False,
        },
        "scene_partner": {
            "availability": "available",
            "closeness_band": "familiar",
            "tease_tolerance_estimate": 0.70,
            "tease_tolerance_confidence": 0.70,
            "play_balance": "balanced",
            "boundary_flags": [],
            "risk_context": [],
        },
        "policy": {
            "age_band": "unknown",
            "romantic_flirt_allowed": False,
            "romantic_flirt_opt_in": False,
            "sexual_content_allowed": False,
            "cross_session_personalization_allowed": False,
            "speech_allowed": True,
            "allow_screen_hook": True,
            "allow_continuity_hook": True,
            "max_beats": 3,
            "max_questions": 1,
            "blocked_topics": [],
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return OpeningInput.from_mapping(payload, now=100.0)
