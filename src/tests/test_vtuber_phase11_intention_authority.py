# -*- coding: utf-8 -*-
"""Test Phase 11: ý định public phải có target + handler + result."""

from domain.decision import Decision
from runtime.intention_authority import IntentionAuthorityGate
from runtime.stage_contracts import StageFrameBuilder


def test_unanchored_memory_review_is_suppressed():
    verdict = IntentionAuthorityGate().validate(
        "Mình muốn rà lại những dấu vết còn sót, cho đầu óc gọn hơn.",
        {
            "kind": "presence_maintenance",
            "evidence_refs": ("silent_cycles=10", "surface_seed=Mình muốn rà lại..."),
        },
    )
    assert verdict.accepted is False
    assert verdict.text == ""
    assert verdict.body_only is True
    assert set(verdict.missing_contract) == {"target", "handler", "result"}


def test_anchored_memory_intention_without_handler_becomes_honest_state():
    verdict = IntentionAuthorityGate().validate(
        "Mình muốn kiểm lại vài mảnh ký ức còn sót, rồi mới yên tâm.",
        {
            "kind": "memory_resonance",
            "evidence_refs": ("memory_id=mem_42", "memory_activation:episode_42"),
        },
    )
    assert verdict.accepted is True
    assert verdict.rewritten is True
    assert "Một chuyện cũ vừa nổi lên" in verdict.text
    assert "handler" in verdict.missing_contract
    assert "result" in verdict.missing_contract


def test_complete_execution_contract_keeps_intention():
    original = "Tôi sẽ kiểm lại lỗi TTS này."
    verdict = IntentionAuthorityGate().validate(
        original,
        {
            "kind": "task_failure",
            "target_ref": "error_id=tts_403",
            "execution_handler": "tts_diagnostics",
            "handler_available": True,
            "result_event": "tts_diagnostics_completed",
        },
    )
    assert verdict.accepted is True
    assert verdict.rewritten is False
    assert verdict.text == original
    assert verdict.mode == "executable_intention"


def test_persona_future_phrase_is_not_mistaken_for_tool_claim():
    verdict = IntentionAuthorityGate().validate("Không, tôi không hứa sẽ ngoan.", {})
    assert verdict.accepted is True
    assert verdict.text == "Không, tôi không hứa sẽ ngoan."
    assert verdict.missing_contract == ()


def test_immediate_speech_act_is_self_executing():
    verdict = IntentionAuthorityGate().validate("Tôi muốn nói thẳng một câu.", {})
    assert verdict.accepted is True
    assert verdict.mode == "self_executing"


def test_stage_builder_applies_intention_authority_to_autonomous_text():
    decision = Decision(
        text="Mình muốn kiểm lại vài mảnh ký ức còn sót, rồi mới yên tâm.",
        animation="stand",
        intent="presence_maintenance",
        should_speak=True,
    )
    payload = decision.to_payload()
    payload["autonomous_plan"] = {
        "scene": {"name": "private_idle"},
        "selected_opportunity": {
            "kind": "memory_callback",
            "evidence_refs": ["memory_id=mem_42"],
        },
        "show_format": {"anchor_policy": "require_surface_anchor"},
    }
    frame = StageFrameBuilder(language_hint="vi").build(
        decision,
        payload=payload,
        channel="autonomous",
    )
    assert frame.display_text.startswith("Một chuyện cũ vừa nổi lên")
    assert payload["intention_authority"]["rewritten"] is True


def test_stage_builder_suppresses_unanchored_fake_intention():
    decision = Decision(
        text="Mình muốn rà lại vài thứ rồi mới yên tâm.",
        animation="stand",
        intent="presence_maintenance",
        should_speak=True,
    )
    payload = decision.to_payload()
    payload["autonomous_plan"] = {
        "scene": {"name": "private_idle"},
        "selected_opportunity": {
            "kind": "presence_maintenance",
            "evidence_refs": [],
        },
        "show_format": {"anchor_policy": "require_surface_anchor"},
    }
    frame = StageFrameBuilder(language_hint="vi").build(
        decision,
        payload=payload,
        channel="autonomous",
    )
    # AnchorGuard có thể hạ câu về một line im lặng an toàn trước khi gate ý định.
    # Dù theo nhánh nào, output cuối không còn claim "sẽ rà/kiểm" giả.
    assert "rà" not in frame.display_text.lower()
    assert "kiểm" not in frame.display_text.lower()
