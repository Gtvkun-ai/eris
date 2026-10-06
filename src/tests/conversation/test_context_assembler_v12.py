# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from runtime.conversation.context_assembler import ConversationContextAssembler


class _Relationship:
    familiarity = 0.8
    closeness = 0.7
    playful_safety = 0.7
    boundary_safety = 0.9
    rupture = 0.0

    def prompt_summary(self):
        return "RELATIONSHIP: đã quen lâu, nói chuyện khá gần và có lịch sử chung."


class _State:
    version = 12
    last_applied_turn_seq = 9
    open_loops = ("đang sửa Eris V12",)
    latest_observation = {"relationship_meaning": "closeness_bid", "confidence": 0.8}
    relationship = _Relationship()
    personality = SimpleNamespace()

    def personality_prompt_context(self):
        return "PERSONALITY: Eris trực tiếp, hài khô, tự bộc lộ có chọn lọc."


class _Reducer:
    def snapshot(self):
        return _State()


class _Memory:
    def render_context(self, query, **kwargs):
        assert query == "ê sửa tiếp đi"
        assert kwargs["session_id"] == "session:test"
        return "MEMORY: user và Eris đang sửa ConversationKernel V12."


class _Host:
    ai_state_reducer = _Reducer()
    memory_kernel = _Memory()
    conversation_id = "session:test"
    logger = None

    def _get_internal_state(self):
        return None


def test_context_assembler_reconnects_identity_memory_world_and_affect_without_planning():
    host = _Host()
    context = ConversationContextAssembler(host).assemble(
        user_text="ê sửa tiếp đi",
        channel="chat",
        previous_public_context="câu Eris vừa nói",
    )

    assert "PERSONALITY" in context["personality_context"]
    assert "RELATIONSHIP" in context["relationship_context"]
    assert "MEMORY" in context["memory_context"]
    assert "WORLD_STATE_V1" in context["grounding_context"]
    assert "RUNTIME_CLOCK_FACT" in context["grounding_context"]
    assert context["affective_voice_state"]["channel"] == "chat"
    assert context["previous_public_excerpt"] == "câu Eris vừa nói"
    assert host.last_personality_context == context["personality_context"]


def test_context_assembler_does_not_feed_last_grounding_back_into_itself():
    host = _Host()
    assembler = ConversationContextAssembler(host)
    first = assembler.assemble(user_text="ê sửa tiếp đi", channel="chat")
    first_grounding = first["grounding_context"]
    host.last_grounding_context = "STALE_SELF_OUTPUT_SHOULD_NOT_BE_REINGESTED\n" + first_grounding

    second = assembler.assemble(user_text="ê sửa tiếp đi", channel="chat")

    assert "STALE_SELF_OUTPUT_SHOULD_NOT_BE_REINGESTED" not in second["grounding_context"]
    # Clock có thể đổi giây, nhưng packet không được phình theo số turn.
    assert abs(len(second["grounding_context"]) - len(first_grounding)) < 80
