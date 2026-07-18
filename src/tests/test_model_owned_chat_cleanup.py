from __future__ import annotations

import inspect
import json
import os

from domain import Decision
from llm.contracts import DECISION_JSON_FIELDS
from llm.prompt_compaction import CACHEABLE_CHAT_PREFIX_V2
from llm.service import LlmService
from parser_grounding.service import DecisionParser
from runtime.coordinator import RuntimeCoordinator
from runtime.relational_voice_seed_adapter import RelationalVoiceSeedAdapter


FORBIDDEN_MODEL_FIELDS = {
    "intent",
    "action",
    "reasoning_tags",
    "confidence",
    "debug_trace",
    "extracted_fact",
    "parse_mode",
}


class _CaptureClient:
    model_name = "test-model"
    base_url = "http://test.invalid"

    def __init__(self, payload: dict | None = None):
        self.payload = payload or {
            "text": "Có tôi đây.",
            "should_speak": True,
            "animation": "stand",
            "next_animation": "",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "system_action": "",
            "action_input": "",
            "delivery_hint": "quiet",
            "nonverbal_cue": "small_smile",
            "stage_motion": "still",
        }
        self.calls: list[dict] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {"content": json.dumps(self.payload, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ]
        }


def _parser() -> DecisionParser:
    return DecisionParser(Decision(text="", animation="stand", should_speak=False))


def test_model_contract_contains_only_transport_stage_and_tool_fields() -> None:
    assert not (FORBIDDEN_MODEL_FIELDS & set(DECISION_JSON_FIELDS))
    folded = CACHEABLE_CHAT_PREFIX_V2.casefold()
    for field in FORBIDDEN_MODEL_FIELDS - {"action"}:
        assert f"{field}," not in folded
        assert f"{field}." not in folded


def test_chat_prompt_ignores_ni_ti_fe_and_social_marker_context() -> None:
    client = _CaptureClient()
    service = LlmService(client)
    raw = service.generate_chat_reply(
        chat_history=[{"role": "assistant", "content": "Lượt trước."}],
        user_message="Xin chào.",
        raw_user_text="Xin chào.",
        ni_context="NI_MARKER_SHOULD_NOT_LEAK",
        ti_context="TI_MARKER_SHOULD_NOT_LEAK",
        fe_context="FE_MARKER_SHOULD_NOT_LEAK",
        appraisal_context="APPRAISAL_MARKER_SHOULD_NOT_LEAK",
        internal_state_context="STATE_MARKER_SHOULD_NOT_LEAK",
        memory_context="MEMORY_FACT_ALLOWED",
        grounding_context="GROUNDING_FACT_ALLOWED",
    )
    payload = json.loads(raw)
    assert payload["text"] == "Có tôi đây."
    prompt = json.dumps(client.calls[-1]["messages"], ensure_ascii=False)
    assert "NI_MARKER_SHOULD_NOT_LEAK" not in prompt
    assert "TI_MARKER_SHOULD_NOT_LEAK" not in prompt
    assert "FE_MARKER_SHOULD_NOT_LEAK" not in prompt
    assert "APPRAISAL_MARKER_SHOULD_NOT_LEAK" not in prompt
    assert "STATE_MARKER_SHOULD_NOT_LEAK" not in prompt
    assert "MEMORY_FACT_ALLOWED" in prompt
    assert "GROUNDING_FACT_ALLOWED" in prompt


def test_startup_greeting_lane_drops_memory_and_cognitive_context() -> None:
    client = _CaptureClient()
    service = LlmService(client)
    service.generate_directive(
        telemetry_data="TELEMETRY_MARKER_SHOULD_NOT_LEAK",
        ni_context="NI_MARKER_SHOULD_NOT_LEAK",
        ti_context="TI_MARKER_SHOULD_NOT_LEAK",
        fe_context="FE_MARKER_SHOULD_NOT_LEAK",
        appraisal_context="APPRAISAL_MARKER_SHOULD_NOT_LEAK",
        internal_state_context="STATE_MARKER_SHOULD_NOT_LEAK",
        memory_context="MEMORY_MARKER_SHOULD_NOT_LEAK",
        speech_intent="session_ritual",
    )
    prompt = json.dumps(client.calls[-1]["messages"], ensure_ascii=False)
    for marker in (
        "TELEMETRY_MARKER_SHOULD_NOT_LEAK",
        "NI_MARKER_SHOULD_NOT_LEAK",
        "TI_MARKER_SHOULD_NOT_LEAK",
        "FE_MARKER_SHOULD_NOT_LEAK",
        "APPRAISAL_MARKER_SHOULD_NOT_LEAK",
        "STATE_MARKER_SHOULD_NOT_LEAK",
        "MEMORY_MARKER_SHOULD_NOT_LEAK",
    ):
        assert marker not in prompt


def test_parser_preserves_metaphor_without_model_authored_audit_fields() -> None:
    raw = json.dumps(
        {
            "text": "Nếu bạn là mảnh thủy tinh, tôi vẫn sẽ nâng niu bạn.",
            "should_speak": True,
            "animation": "stand",
            "next_animation": "",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "system_action": "",
            "action_input": "",
            "delivery_hint": "low_quiet",
            "nonverbal_cue": "small_smile",
            "stage_motion": "lean_in_small",
            "reasoning_tags": ["capability_violation"],
            "debug_trace": "rewrite_me",
            "extracted_fact": "invented",
        },
        ensure_ascii=False,
    )
    decision = _parser().parse(raw, user_hint="Nếu tui là mảnh thủy tinh thì sao?")
    assert decision.text == "Nếu bạn là mảnh thủy tinh, tôi vẫn sẽ nâng niu bạn."
    assert decision.reasoning_tags == ()
    assert decision.debug_trace == ""
    assert decision.extracted_fact == ""
    assert decision.delivery_hint == "low_quiet"
    assert decision.stage_motion == "lean_in_small"


def test_body_payload_hides_debug_markers_by_default() -> None:
    decision = Decision(
        text="Một câu sạch.",
        animation="stand",
        intent="legacy_intent",
        reasoning_tags=("legacy_marker",),
        debug_trace="legacy_trace",
        parse_mode="legacy_parse",
        confidence=0.9,
    )
    old = os.environ.pop("ERIS_EXPOSE_DEBUG_PAYLOAD", None)
    try:
        payload = decision.to_payload()
        assert FORBIDDEN_MODEL_FIELDS.isdisjoint(payload)
        os.environ["ERIS_EXPOSE_DEBUG_PAYLOAD"] = "1"
        debug_payload = decision.to_payload()
        assert debug_payload["reasoning_tags"] == ["legacy_marker"]
        assert debug_payload["debug_trace"] == "legacy_trace"
    finally:
        if old is None:
            os.environ.pop("ERIS_EXPOSE_DEBUG_PAYLOAD", None)
        else:
            os.environ["ERIS_EXPOSE_DEBUG_PAYLOAD"] = old


def test_relational_seed_and_director_second_pass_are_retired() -> None:
    assert RelationalVoiceSeedAdapter().try_answer("tui nhớ em") is None
    assert LlmService(_CaptureClient()).generate_director_candidates(user_message="x") == []


def test_coordinator_no_longer_inherits_legacy_generation_editors() -> None:
    names = {base.__name__ for base in RuntimeCoordinator.__mro__}
    assert "PostGenerationFiltersMixin" not in names
    assert "SelfCritiqueEscalationMixin" not in names
    source = inspect.getsource(RuntimeCoordinator)
    assert "_apply_post_generation_filters(" not in source
    assert "_maybe_escalate_chat_decision(" not in source
