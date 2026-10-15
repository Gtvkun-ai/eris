# -*- coding: utf-8 -*-
"""Regression: Root nạp full Self một lần, về sau chỉ có delta.

Không cần gọi DeepSeek thật; fake trả raw JSON để kiểm tra transcript đúng
trên đường wire, không phải JSON tái tạo sau parse.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from runtime.conversation.agent import ROOT_STEP_SCHEMA, RuntimeModelRootAgent
from runtime.conversation.context import RootCapabilityRegistry
from runtime.conversation.contracts import ConversationEvent, NextConversationMove
from runtime.conversation.root_session import RootConversationSession, _changed, _read_self


class FakeState:
    def __init__(self):
        self.data = {
            "identity": {"beliefs": {f"belief_{i}": {"strength": i / 100} for i in range(25)}},
            "relationship": {"closeness": 0.5},
            "personality": {"temperament": {"curious": 0.8}},
            "open_loops": [],
            "goal_records": [],
            "latest_observation": {"hidden_current_observation": "not self"},
        }
    def to_dict(self):
        return copy.deepcopy(self.data)


class FakeHost:
    def __init__(self):
        self.mind = FakeState()
        self.ai_state_reducer = SimpleNamespace(snapshot=lambda: self.mind)
        self.subject_service = SimpleNamespace(self_view=lambda: {
            "facets": [{"facet_id": f"f{i}", "statement": f"Belief facet {i}"} for i in range(15)],
            "generated_at": 12345,
        })
        self.memory_state = {"long_term": ["one", "two"]}
        self.long_term_memory = ["first memory", "second memory"]


class FakeClient:
    base_url = "http://localhost:6011/v1"
    model_name = "deepseek-v4-flash"


class FakeRouter:
    def __init__(self):
        self.executive_client = FakeClient()
        self.calls = []
        self.fail_once = False

    def invoke_structured_worker(self, _client, **kwargs):
        self.calls.append(kwargs)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("upstream_interrupted")
        messages = kwargs.get("conversation_messages")
        if messages is None:
            return {"kind": "move", "intent": "fallback", "say": "fallback", "delivery": "natural", "after": "wait_user"}
        if any('root_session_bootstrap' in item['content'] for item in messages[-1:]):
            text = '{ "kind" : "no_reply" , "reason" : "self_loaded" }'
        else:
            text = '{ "kind" : "move" , "intent":"live", "say":"reply", "delivery":"tự nhiên", "after":"wait_user" }'
        kwargs["raw_reply_sink"].append(text)
        return json.loads(text)


def root_payload(text="hello", step=0):
    return {
        "step_index": step,
        "event": {"event_id": "e1", "kind": "user_turn", "text": text},
        "recent_public_history": [],
        "runtime_context": {"personality_context": "selected five", "affective_voice_state": {"curiosity": 0.7}},
        "tool_results": [],
    }


def ask(session, router, system="system", payload=None, history=()):
    payload = payload or root_payload()
    return session.ask(router=router, client=router.executive_client, system=system,
                       schema=ROOT_STEP_SCHEMA, payload=payload, runtime_context={}, recent_history=history)


def test_full_self_bootstrap_without_top_k():
    host = FakeHost()
    read = _read_self(host)
    assert len(read["mind_state"]["identity"]["beliefs"]) == 25
    assert len(read["subject_self"]["facets"]) == 15
    assert "generated_at" not in read["subject_self"]
    assert "latest_observation" in read["mind_state"]
    assert read["long_term_memory"] == ["first memory", "second memory"]

    router = FakeRouter()
    session = RootConversationSession()
    session._host = host
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_STEP_SCHEMA)
    bootstrap = json.loads(router.calls[0]["conversation_messages"][1]["content"])
    assert len(bootstrap["eris_self_full"]["mind_state"]["identity"]["beliefs"]) == 25
    assert session._messages[-1]["content"] == '{ "kind" : "no_reply" , "reason" : "self_loaded" }'


def test_delta_turn_does_not_repeat_self_and_retains_raw_response(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    host, router = FakeHost(), FakeRouter()
    session = RootConversationSession()
    session._host = host
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_STEP_SCHEMA)
    first = ask(session, router, history=({"role": "user", "content": "hi"},))
    assert first["kind"] == "move"
    messages = router.calls[1]["conversation_messages"]
    assert len(messages) == 4
    first_delta = json.loads(messages[-1]["content"])
    assert "eris_self_full" not in first_delta
    assert "personality_context" not in str(first_delta)
    assert first_delta["recent_public_history_delta"] == [{"role": "user", "content": "hi"}]
    assert first_delta["self_changes_since_last_step"] == {}
    assert session._messages[-1]["content"] == '{ "kind" : "move" , "intent":"live", "say":"reply", "delivery":"tự nhiên", "after":"wait_user" }'

    host.mind.data["identity"]["beliefs"]["belief_0"]["strength"] = 0.9
    second = ask(session, router, payload=root_payload("new"), history=(
        {"role": "user", "content": "hi"}, {"role": "assistant", "content": "spoken"},
        {"role": "user", "content": "new"},
    ))
    assert second["kind"] == "move"
    new_delta = json.loads(router.calls[2]["conversation_messages"][-1]["content"])
    assert new_delta["self_changes_since_last_step"] == {"mind_state": {"identity": {"beliefs": {"belief_0": {"strength": .9}}}}}
    assert new_delta["recent_public_history_delta"][-1]["content"] == "new"
    assert len(router.calls[2]["conversation_messages"]) == 6
    assert "eris_self_full" not in new_delta


def test_failure_resets_and_reloads_full_self(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    router, session = FakeRouter(), RootConversationSession()
    session._host = FakeHost()
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_STEP_SCHEMA)
    router.fail_once = True
    assert ask(session, router) is None
    assert not session._started
    assert ask(session, router)["kind"] == "move"
    # Bootstrap được nạp lại trước khi được phép nối phiên mới.
    boots = [call for call in router.calls if call.get("conversation_messages")
             and "root_session_bootstrap" in call["conversation_messages"][-1]["content"]]
    assert len(boots) == 2


def test_background_bootstrap_busy_does_not_block_user_turn(monkeypatch):
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    session = RootConversationSession()
    session._host = FakeHost()
    router = FakeRouter()
    session._lock.acquire()
    try:
        assert ask(session, router) is None
        assert not router.calls
    finally:
        session._lock.release()


def test_stable_root_system_prompt_across_bootstrap_and_chat():
    root = RuntimeModelRootAgent(FakeRouter())
    assert root._system_prompt(RootCapabilityRegistry({})) == root._system_prompt(
        RootCapabilityRegistry({"research": object()})
    )


def test_removed_self_field_is_explicitly_marked():
    assert _changed({"identity": {"beliefs": {"x": 1, "y": 2}}}, {"identity": {"beliefs": {"y": 2}}}) == {
        "identity": {"beliefs": {"x": {"__erased_from_self": True}}}}


def test_root_preflight_allows_large_self_but_writer_cap_unchanged(monkeypatch):
    from llm.token_budget import preflight
    from runtime.inference_broker import inference_context
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    monkeypatch.setenv("ERIS_ROOT_SESSION_PROMPT_CAP_TOKENS", "90000")
    original = [{"role": "system", "content": "full root context " * 1900},
                {"role": "user", "content": "test"}]
    with inference_context("chat_tool_required", metadata={"cognitive_lane": "root_conversation"}):
        rooted = preflight(original, base_url="http://localhost:6011/v1", model="deepseek-v4-flash")
    with inference_context("chat_main", metadata={"cognitive_lane": "public_reply"}):
        writer = preflight(original, base_url="http://localhost:6011/v1", model="deepseek-v4-flash")
    assert rooted == original
    assert writer != original
    assert len(writer[0]["content"]) < len(original[0]["content"])


def test_real_client_gateway_session_continuation_for_root(monkeypatch):
    """Kiểm chứng Client→Whale2API session header bằng mocked HTTP response."""
    import llm.client as client_module
    from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter
    monkeypatch.setenv("ERIS_RUNTIME_SESSION_ID", "test-root-warmup-v12")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    calls = []

    class Response:
        status_code = 200
        headers = {}
        def __init__(self, raw):
            self.raw = raw
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": self.raw}, "finish_reason": "stop"}]}

    def post(**kwargs):
        calls.append(kwargs)
        message = kwargs["json"]["messages"][-1]["content"]
        if "root_session_bootstrap" in message:
            return Response('{ "kind" : "no_reply" , "reason" : "self_loaded" }')
        return Response('{ "kind" : "move" , "intent":"live", "say":"reply", "delivery":"tự nhiên", "after":"wait_user" }')

    monkeypatch.setattr(client_module, "_brokered_post", post)
    client = client_module.OpenAICompatibleClient(
        base_url="http://localhost:6011/v1", api_key="sk-integration-root-v12",
        model_name="deepseek-v4-flash", provider_circuit_id="test-root-v12-isolated",
    )
    router = AIRuntimeModelRouter(SimpleNamespace(executive_client=client))
    session = RootConversationSession()
    session._host = FakeHost()
    root = RuntimeModelRootAgent(router)
    system = root._system_prompt(RootCapabilityRegistry({}))
    assert session._prime(router=router, client=client, system=system, schema=ROOT_STEP_SCHEMA)
    assert ask(session, router, system=system) is not None
    assert len(calls) == 2
    assert calls[0]["headers"]["X-Session-ID"] == calls[1]["headers"]["X-Session-ID"]
    assert len(calls[0]["json"]["messages"]) == 2
    assert len(calls[1]["json"]["messages"]) == 4
    assert "eris_self_full" in calls[0]["json"]["messages"][1]["content"]
    assert "eris_self_full" not in calls[1]["json"]["messages"][-1]["content"]


def test_sliding_public_history_only_sends_unseen_turns(monkeypatch):
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    router, session = FakeRouter(), RootConversationSession()
    session._host = FakeHost()
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_STEP_SCHEMA)
    old = tuple({"role": "user", "content": f"turn{i}"} for i in range(32))
    assert ask(session, router, history=old)
    nxt = old[1:] + ({"role": "user", "content": "turn32"},)
    assert ask(session, router, history=nxt)
    packet = json.loads(router.calls[-1]["conversation_messages"][-1]["content"])
    assert packet["recent_public_history_delta"] == [{"role": "user", "content": "turn32"}]
    assert "recent_public_history_reconcile" not in packet


def test_nullable_self_delta_not_lost():
    assert _changed({"belief": {"confidence": 0.5}}, {"belief": {"confidence": None}}) == {
        "belief": {"confidence": {"__value_now_null": True}}}


def test_delivery_status_changes_are_sent_as_delta_not_replayed_history(monkeypatch):
    """pending -> cancelled không được làm session tưởng lịch sử bị rewrite."""
    monkeypatch.setenv("ERIS_ROOT_SESSION_BOOTSTRAP", "1")
    monkeypatch.setenv("ERIS_WEB_SESSION_MODE", "isolated")
    router, session = FakeRouter(), RootConversationSession()
    session._host = FakeHost()
    assert session._prime(router=router, client=router.executive_client, system="system", schema=ROOT_STEP_SCHEMA)
    history_pending = [
        {"role": "user", "content": "ô", "raw_content": "ô", "history_id": "turn:u1"},
        {"role": "assistant", "content": "[Đã hiển thị; TTS chưa xác nhận phát xong] xin chào",
         "raw_content": "xin chào", "history_id": "turn:a1", "delivery_id": "audio:1", "delivery_status": "pending"},
    ]
    assert ask(session, router, history=history_pending)["kind"] == "move"
    first = json.loads(router.calls[-1]["conversation_messages"][-1]["content"])
    assert first["recent_public_history_delta"][-1]["content"] == "xin chào"
    assert first["recent_public_delivery_updates"] == [{"delivery_id": "audio:1", "status": "pending"}]
    history_cancelled = [dict(x) for x in history_pending]
    history_cancelled[-1]["content"] = "[Đã hiển thị; âm thanh bị ngắt giữa chừng] xin chào"
    history_cancelled[-1]["delivery_status"] = "cancelled"
    assert ask(session, router, history=history_cancelled)["kind"] == "move"
    second = json.loads(router.calls[-1]["conversation_messages"][-1]["content"])
    assert "recent_public_history_delta" not in second
    assert "recent_public_history_reconcile" not in second
    assert second["recent_public_delivery_updates"] == [{"delivery_id": "audio:1", "status": "cancelled"}]
