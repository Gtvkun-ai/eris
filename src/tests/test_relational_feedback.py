# -*- coding: utf-8 -*-
"""Regression tests cho cold/distant tone feedback.

Đặt file này vào: tests/test_relational_feedback.py
Chạy:
    pytest tests/test_relational_feedback.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cortex.conversation_dynamics import ConversationDynamicsEngine
from cortex.relationship_dynamics import RelationshipDynamicsEngine
from cortex.relational_feedback import RelationalFeedbackAnalyzer, merge_affect_with_relational_feedback


class _Affect:
    technicality = 0.0
    distress = 0.0
    intimacy = 0.0
    attachment = 0.0
    conflict = 0.0
    correction = 0.0
    objectification = 0.0
    playfulness = 0.0
    relational_pressure = 0.0
    perceived_rejection = 0.0
    attachment_bid = 0.0
    playful_distress = 0.0
    romantic_boundary_probe = 0.0
    ambiguity = 0.0
    evidence = ()


def test_coldness_feedback_signal_detects_short_direct_feedback():
    signal = RelationalFeedbackAnalyzer().analyze(
        "lạnh lùng vl luôn",
        previous_assistant_text="Tôi chỉ đang trả lời đúng những gì bạn hỏi.",
    )

    assert signal.detected is True
    assert signal.kind == "coldness_feedback"
    assert signal.intensity >= 0.65
    assert signal.repair_needed >= 0.55
    assert signal.warmth_request >= 0.35
    assert "coldness_marker" in signal.evidence


def test_coldness_feedback_routes_conversation_to_relational_repair():
    signal = RelationalFeedbackAnalyzer().analyze(
        "lạnh lùng vl luôn",
        previous_assistant_text="Tôi chỉ đang trả lời đúng những gì bạn hỏi.",
    )
    report = ConversationDynamicsEngine().evaluate_chat(
        None,
        user_text="lạnh lùng vl luôn",
        last_assistant_text="Tôi chỉ đang trả lời đúng những gì bạn hỏi.",
        relational_feedback=signal,
    )

    assert report.state.mode == "relational_repair"
    assert report.state.last_failure.type == "tone_distance_mismatch"
    assert "acknowledge_tone_feedback" in report.state.adaptation_flags
    assert "forbid_defensive_clarification" in report.state.adaptation_flags
    assert "warmth_floor_required" in report.state.adaptation_flags


def test_relationship_state_nudges_closer_without_dignity_defense():
    engine = RelationshipDynamicsEngine()
    signal = RelationalFeedbackAnalyzer().analyze("xa cách quá")
    event = engine.infer_event(
        user_text="xa cách quá",
        previous_assistant_text="Tôi là ERIS.",
        relational_feedback=signal,
    )
    report = engine.update(None, event)

    assert report.event_scores["relational_repair_requested"] >= 0.35
    assert report.state.repair > 0.05
    assert report.state.preferred_distance < 0.58
    assert report.state.attachment_visibility > 0.12
    assert report.state.dignity_defense == 0.0
    assert any("coldness_feedback_acknowledged" in note for note in report.notes)


def test_feedback_bridge_opens_fe_relational_repair_gate_without_farming_friendliness():
    signal = RelationalFeedbackAnalyzer().analyze("robot quá")
    merged = merge_affect_with_relational_feedback(_Affect(), signal)

    assert merged["perceived_rejection"] >= 0.50
    assert merged["relational_pressure"] >= 0.35
    # Bridge only lifts attachment enough for repair routing; it should not become romance/waifu bait.
    assert 0.45 <= merged["attachment"] <= 0.55


def test_llm_service_does_not_rewrite_defensive_relational_reply():
    pytest = __import__("pytest")
    service_mod = pytest.importorskip("llm.service")

    class DummyClient:
        pass

    service = service_mod.LlmService(DummyClient())
    raw = json.dumps(
        {
            "text": "Tôi chỉ đang trả lời đúng những gì bạn hỏi.",
            "intent": "defensive_clarification",
            "action": {"type": "none"},
            "animation": "stand",
            "reasoning_tags": [],
            "should_speak": True,
            "confidence": 0.85,
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": "",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        },
        ensure_ascii=False,
    )

    guarded = service._guard_chat_output(raw, raw_user_text="lạnh lùng vl luôn")
    payload = json.loads(guarded)

    assert payload["intent"] == "defensive_clarification"
    assert payload["text"] == "Tôi chỉ đang trả lời đúng những gì bạn hỏi."
    assert payload["reasoning_tags"] == []
