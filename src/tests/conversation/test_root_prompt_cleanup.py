from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from runtime.conversation.agent import ROOT_BATCH_STEP_SCHEMA, RuntimeModelRootAgent
from runtime.conversation.context import RootCapabilityRegistry
from runtime.conversation.contracts import ConversationEvent
from runtime.conversation.root_session import RootConversationSession, _read_self
from runtime.conversation.self_prompt_view import compact_profile, project_self_view, project_runtime_context
from runtime.conversation.self_prompt_view import state_difference
from runtime.conversation.tool_guides import TOOL_GUIDES, read_tool_guide


class Router:
    def __init__(self, *steps):
        self.executive_client = SimpleNamespace(base_url="http://localhost:6011/v1", model_name="deepseek-v4-flash")
        self.calls = []
        self.steps = iter(steps)

    def invoke_structured_worker(self, client, **kwargs):
        self.calls.append(copy.deepcopy({k: v for k, v in kwargs.items() if k != "raw_reply_sink"}))
        messages = kwargs.get("conversation_messages")
        bootstrap = messages and json.loads(messages[-1]["content"]).get("kind") == "root_session_bootstrap"
        reply = {"kind": "no_reply", "reason": "self_loaded"} if bootstrap else next(self.steps, {"kind": "no_reply", "reason": "done"})
        if "raw_reply_sink" in kwargs:
            kwargs["raw_reply_sink"].append(json.dumps(reply))
        return reply


def apply_overlay(original, patch):
    """Independent wire consumer, including null vs deletion and array replacement."""
    if patch == {"__value_now_null": True}:
        return None
    if not isinstance(original, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(original)
    for key, value in patch.items():
        if value == {"__erased_from_self": True}:
            out.pop(key, None)
        else:
            out[key] = apply_overlay(out.get(key), value)
    return out


def ask(session, router, context):
    result = session.ask(router=router, client=router.executive_client, system="system", schema=ROOT_BATCH_STEP_SCHEMA,
                         payload={"event": {"kind": "user_turn", "text": "next"}, "runtime_context": context},
                         runtime_context=context, recent_history=[])
    assert result is not None
    messages = router.calls[-1]["conversation_messages"]
    bootstrap = json.loads(messages[1]["content"])["eris_self_full"]
    step = json.loads(messages[-1]["content"])
    return apply_overlay(bootstrap, step["self_changes_since_bootstrap"]), step


def test_every_request_can_reconstruct_current_self_and_context(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    host = SimpleNamespace(memory_state={"fact": "A", "nullable": "x", "remove": 1, "items": [1, 2]})
    router, session = Router(), RootConversationSession()
    session._host = host
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_BATCH_STEP_SCHEMA)
    prefix = session._state.self_ref.content_json
    host.memory_state = {"fact": "B", "nullable": None, "items": [], "added": {"weak": 0.01}}
    context = {"grounding_context": "screen context stays byte-for-byte", "flag": False}
    for _ in range(3):
        current, step = ask(session, router, context)
        assert current == _read_self(host)
        assert step["runtime_context"] == context
        assert step["self_base_fingerprint"] == session._state.self_ref.fingerprint
        assert "self_changes_since_last_step" not in step
    host.memory_state["fact"] = "A"
    del host.memory_state["added"]
    current, step = ask(session, router, {})
    assert current == _read_self(host)
    assert step["runtime_context"] == {}
    assert session._state.self_ref.content_json == prefix


def test_overflow_never_sends_a_partial_overlay(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    router, session = Router(), RootConversationSession()
    session._host = SimpleNamespace(memory_state={"old": 1})
    assert session._prime(router=router, client=router.executive_client, system="system", schema={})
    session._host.memory_state = {"large": "x" * 10000}
    session._fits = lambda client, messages: len(messages) <= 3
    assert session.ask(router=router, client=router.executive_client, system="system", schema={},
                       payload={"runtime_context": {}}, runtime_context={}, recent_history=[]) is None
    assert len(router.calls) == 1  # No truncated request reaches the router.


def test_overlay_preserves_bool_number_type_changes():
    patch = state_difference({"flag": False, "rows": [True]}, {"flag": 0, "rows": [1]})
    assert json.dumps(apply_overlay({"flag": False, "rows": [True]}, patch)) == '{"flag": 0, "rows": [1]}'


def test_compact_profile_roundtrips_qualifiers_exceptions_and_timestamps():
    rows = [
        {"id": str(i), "path": "communication.style", "value": {"when": "roleplay", "style": "cute"},
         "scope": {"kind": "session", "key": "s"}, "status": "active", "sensitivity": "normal",
         "source": "profile_model", "value_type": "object", "cardinality": "multi", "tier": "working",
         "recurrence": 1, "confidence": 0.4 + i / 10, "explicitness": "inferred", "evidence_ids": [f"u:{i}"],
         "valid_from": 10, "created_at": 10 if i != 1 else 9, "updated_at": 20,
         "last_confirmed_at": 20 if i != 2 else 18, "valid_until": None, "expires_at": None,
         "metadata": {"reason": "Only in this scene; not a permanent preference", "unrecognised_qualifier": i}}
        for i in range(3)
    ]
    rows[2]["scope"] = {"kind": "project", "key": "other"}
    source = {"version": 1, "record_count": 3, "records": rows}
    before = copy.deepcopy(source)
    projected = compact_profile(source)
    decoded = []
    for row in projected["records"]:
        full = {**copy.deepcopy(projected["defaults"]), **copy.deepcopy(row)}
        for key, target in projected["aliases"].items():
            if key not in full:
                full[key] = copy.deepcopy(full[target])
        decoded.append(full)
    assert decoded == rows
    assert source == before
    assert compact_profile(projected) == projected


def test_self_view_removes_debug_and_clones_without_changing_owner():
    mind = {"identity": {"beliefs": ["uncertain", "opposing"]}, "relationship": {"last_event": "current"},
            "latest_observation": {"turn_id": "old", "confidence": 0.4}}
    persisted = copy.deepcopy(mind)
    persisted["relationship"]["last_event"] = "persisted variant"
    source = {"mind_state": mind, "memory_state": {
        "ai_orchestrated_state": persisted, "internal_state": {"energy": 0.1},
        "active_state": {"metadata": {"internal_state": {"energy": 0.1}}},
        "living_user": {"replay": {"timeline": ["raw debug"]}, "pending_turns": 3,
                        "recent_episodes": [{"summary": "real memory"}], "last_dream_report": {"applied": 1}},
    }}
    original = copy.deepcopy(source)
    view = project_self_view(source)
    assert source == original
    assert view["mind_state"] == mind
    assert view["memory_state"]["persisted_mind_variants"] == {"relationship": {"last_event": "persisted variant"}}
    assert "internal_state" not in view["memory_state"]["active_state"]["metadata"]
    assert view["memory_state"]["living_user"] == {"recent_episodes": [{"summary": "real memory"}]}
    assert project_self_view(view) == view
    context = {"conversation_status": {"latest_observation": mind["latest_observation"]},
               "grounding_context": "vision detail unchanged", "other": 1}
    projected = project_runtime_context(context, view)
    assert projected["conversation_status"] == {"latest_observation_ref": "mind_state.latest_observation"}
    assert projected["grounding_context"] == context["grounding_context"]
    context["conversation_status"]["latest_observation"] = {"turn_id": "different"}
    assert project_runtime_context(context, view) == context


def test_root_loads_guide_then_executes_with_same_schema_and_no_fake_receipt(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    executions = []
    class Action:
        def invoke_for_root(self, **kwargs):
            executions.append(kwargs)
            return {"status": "success"}
    registry = RootCapabilityRegistry({"action": Action()})
    router = Router(
        {"kind": "read_tool_guide", "guide": "math_workspace"},
        {"kind": "batch", "actions": [{"kind": "use_capability", "capability": "action", "arguments": {"action_id": "math_workspace", "arguments": {"kind": "simplify", "expression": "1+1"}}}]},
        {"kind": "no_reply", "reason": "done"},
    )
    agent = RuntimeModelRootAgent(router)
    agent._root_session._host = SimpleNamespace(memory_state={"fact": "x"})
    decision = agent.decide(event=ConversationEvent(event_id="e1", session_id="s", kind="user_turn", text="calculate"), recent_history=[], note="",
                            runtime_context={"__root_capabilities": registry})
    assert decision.reason == "done"
    assert len(executions) == 1
    assert all(call["schema"] == ROOT_BATCH_STEP_SCHEMA for call in router.calls)
    step = json.loads(router.calls[2]["conversation_messages"][-1]["content"])
    guide = step["tool_results"][0]
    assert guide["documentation"] == TOOL_GUIDES["math_workspace"]
    assert guide["authority"] == "documentation_only_not_execution"
    assert "receipt_ref" not in guide
    assert "Đặc biệt khi đề bài" not in router.calls[0]["system"]


def test_loaded_guides_survive_more_than_six_tool_results():
    guide = {"kind": "tool_guide_result", "status": "found", "guide": "work", "documentation": "manual"}
    payload = RuntimeModelRootAgent._payload(
        event=ConversationEvent(event_id="e", session_id="s", kind="user_turn", text="next"), recent_history=[], note="", runtime_context={},
        tool_results=[guide] + [{"kind": "capability_result", "i": n} for n in range(10)], step_index=10,
    )
    assert payload["tool_results"][0] == guide
    assert len(payload["tool_results"]) == 7


def test_unknown_guide_does_not_count_as_progress():
    result = read_tool_guide("unknown")
    assert result["status"] == "unavailable"
    assert not RuntimeModelRootAgent._is_meaningful_result(result, prior_fingerprints=set())
