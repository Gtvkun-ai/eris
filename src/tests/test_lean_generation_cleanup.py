from __future__ import annotations

import json

from domain import Decision
from llm.prompt_compaction import CACHEABLE_CHAT_PREFIX_V2
from llm.service import LlmService
from runtime.final_passthrough_policy import audit_only
from semantic_authority import SemanticAuthorityPolicy


class _NeverCalledClient:
    def create_chat_completion(self, **kwargs):  # pragma: no cover - must stay unused
        raise AssertionError("auxiliary rewrite client must not be called")


def test_generation_audit_is_silent_by_default(monkeypatch):
    monkeypatch.delenv("ERIS_VERBOSE_POLICY_AUDIT", raising=False)
    decision = Decision(text="Giữ nguyên câu này.", animation="stand", debug_trace="raw", reasoning_tags=("raw",))

    out = audit_only(decision, "legacy_guard", attempted_text="câu khác")

    assert out is decision
    assert out.text == "Giữ nguyên câu này."
    assert out.debug_trace == "raw"
    assert out.reasoning_tags == ("raw",)


def test_semantic_policy_disables_marker_and_second_pass_pipeline():
    policy = SemanticAuthorityPolicy.from_runtime()

    assert policy.qwen_first is True
    assert policy.include_chat_act_markers is False
    assert policy.include_director_prompt is False
    assert policy.allow_pre_llm_intercepts is False
    assert policy.allow_relational_pre_llm_intercept is False
    assert policy.enforce_response_contract is False
    assert policy.generate_director_candidates is False
    assert policy.bounded_refine_enabled is False


def test_pre_parser_guard_does_not_rewrite_relational_feedback():
    service = LlmService(_NeverCalledClient())
    raw = json.dumps(
        {
            "text": "Tôi không đồng ý, nhưng tôi hiểu vì sao bạn thấy câu đó lạnh.",
            "intent": "defensive",
            "action": "reply",
        },
        ensure_ascii=False,
    )

    assert service._guard_chat_output(raw, raw_user_text="lạnh lùng quá") == raw


def test_guard_reroll_returns_original_without_calling_auxiliary_model():
    service = LlmService(_NeverCalledClient(), style_client=_NeverCalledClient())
    original = "Nếu bạn là mảnh thủy tinh, tôi vẫn sẽ nâng niu bạn."

    out = service.rewrite_guard_violation_text(
        original_text=original,
        violation_rule="legacy_marker",
        violation_reason="obsolete",
        channel="chat",
    )

    assert out == original


def test_chat_prompt_is_compact_and_contains_no_runtime_marker_constitution():
    lowered = CACHEABLE_CHAT_PREFIX_V2.lower()
    assert "actionplanner decision" not in lowered
    assert "response_contract" not in lowered
    assert "social cognition" not in lowered
    assert "correction_triggers_repair" not in lowered
    assert "operational flags" not in lowered
    assert len(CACHEABLE_CHAT_PREFIX_V2.split()) < 170


def test_style_block_is_compact_and_ignores_synthetic_state_labels():
    service = LlmService(_NeverCalledClient())
    block = service._build_chat_style_block()

    assert "cold_soft" not in block
    assert "repair_pressure" not in block
    assert "memory_replay" not in block
    assert len(block.split()) < 45


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "text": "Tôi nghe đây.",
                                "intent": "reply",
                                "action": {"type": "none"},
                                "animation": "stand",
                                "reasoning_tags": [],
                                "should_speak": True,
                                "confidence": 0.8,
                                "direction": 0,
                                "target_x": -1.0,
                                "bounce_action": "",
                                "extracted_fact": "",
                                "debug_trace": "",
                                "next_animation": "",
                                "system_action": "",
                                "action_input": "",
                                "delivery_hint": "",
                                "nonverbal_cue": "",
                                "stage_motion": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def test_chat_service_discards_legacy_marker_contexts():
    client = _RecordingClient()
    service = LlmService(client)

    service.generate_chat_reply(
        chat_history=[{"role": "assistant", "content": "Câu public trước."}],
        user_message="trả lời câu này",
        raw_user_text="trả lời câu này",
        ni_context="NI_MARKER_SHOULD_NOT_APPEAR",
        ti_context="ACTIONPLANNER_MARKER_SHOULD_NOT_APPEAR",
        fe_context="FE_MARKER_SHOULD_NOT_APPEAR",
        appraisal_context="REPAIR_SCORE_SHOULD_NOT_APPEAR",
        internal_state_context="PRIVATE_MIND_MARKER_SHOULD_NOT_APPEAR",
        conversation_context="TURN_FRAME_MARKER_SHOULD_NOT_APPEAR",
    )

    prompt = "\n".join(str(item.get("content", "")) for item in client.calls[0]["messages"])
    assert "NI_MARKER_SHOULD_NOT_APPEAR" not in prompt
    assert "ACTIONPLANNER_MARKER_SHOULD_NOT_APPEAR" not in prompt
    assert "FE_MARKER_SHOULD_NOT_APPEAR" not in prompt
    assert "REPAIR_SCORE_SHOULD_NOT_APPEAR" not in prompt
    assert "PRIVATE_MIND_MARKER_SHOULD_NOT_APPEAR" not in prompt
    assert "TURN_FRAME_MARKER_SHOULD_NOT_APPEAR" not in prompt
    assert "trả lời câu này" in prompt
    assert "Câu public trước." in prompt
