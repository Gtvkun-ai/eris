# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v12_session_state_has_no_retired_semantic_fields():
    text = (ROOT / "runtime/conversation/contracts.py").read_text(encoding="utf-8")
    session_block = text.split("class ConversationSessionState", 1)[1].split("class ContinuationLease", 1)[0]
    for symbol in ("planned_threads", "desired_shape", "continuation_feel", "verbal_bridge_hint"):
        assert symbol not in session_block


def test_root_agent_schema_is_small():
    text = (ROOT / "runtime/conversation/agent.py").read_text(encoding="utf-8")
    schema = text.split("NEXT_MOVE_SCHEMA", 1)[1].split("class RootAgent", 1)[0]
    for retired in ("public_beats", "speech_plan", "turn_projection", "max_sentences", "desired_shape"):
        assert retired not in schema
    for required in ("intent", "say", "delivery", "after"):
        assert required in schema


def test_production_bootstrap_uses_conversation_kernel():
    text = (ROOT / "runtime/agent_loop/runtime.py").read_text(encoding="utf-8")
    ensure = text.split("def ensure_agent_turn_runtime", 1)[1]
    assert "ConversationKernel" in ensure
    assert "V12AgentTurnRuntime" in ensure
    # V11 runtime class vẫn là compatibility/test surface, không được bootstrap.
    assert "runtime = TurnAgentRuntime(" not in ensure
