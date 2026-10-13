# -*- coding: utf-8 -*-
"""FEAT-001: bước SELF-VERIFY trước khi finalize một move.

Khi model trả kind=move, Root KHÔNG finalize ngay mà gửi lại chính move đó cho
model với vài câu hỏi tự kiểm; model trả confirm/revise/withdraw. Verify là lượt
model THỨ HAI sau move, chạy tối đa một lần mỗi finalize, và luôn fail-soft:
mọi lỗi/kết quả lạ đều rơi về move gốc, không ném exception ra khỏi decide().

Fake router chỉ trả JSON đã định trước; test không tuyên bố model thật tự kiểm
tốt, chỉ bảo đảm runtime thi hành đúng vòng verify và biên NoReply|Move.
"""
from __future__ import annotations

from runtime.conversation.agent import VERIFY_SCHEMA, RuntimeModelRootAgent
from runtime.conversation.contracts import ConversationEvent, NextConversationMove, NoReply


class FakeRouter:
    """Trả lần lượt từ hàng đợi; move là lượt 1, verify là lượt 2."""

    executive_client = object()

    def __init__(self, *results, error: Exception | None = None) -> None:
        self.results = list(results)
        self.error = error
        self.requests: list[dict] = []

    def invoke_structured_worker(self, _client, **kwargs):
        self.requests.append(dict(kwargs))
        if self.error is not None and kwargs.get("name") == "eris_root_self_verify_v12":
            raise self.error
        assert self.results, "Root called model more times than expected"
        return self.results.pop(0)


def _event(text: str = "chào Eris", kind: str = "user_turn") -> ConversationEvent:
    return ConversationEvent(event_id="e1", session_id="s", kind=kind, text=text)


def _move(say: str = "trả lời trực tiếp câu user") -> dict:
    return {"kind": "move", "intent": "đáp lượt user", "say": say,
            "delivery": "tự nhiên", "after": "wait_user"}


def _decide(router, *, event=None, context=None) -> object:
    return RuntimeModelRootAgent(router).decide(
        event=event or _event(), recent_history=(), note="",
        runtime_context=context or {},
    )


def test_verify_schema_has_three_quality_check_outcomes():
    kinds = set()
    for schema in VERIFY_SCHEMA["oneOf"]:
        kinds.update(schema["properties"]["kind"].get("enum", []))
    assert kinds == {"confirm", "revise", "withdraw"}
    revise = next(s for s in VERIFY_SCHEMA["oneOf"]
                  if s["properties"]["kind"]["enum"] == ["revise"])
    assert set(revise["required"]) == {"kind", "intent", "say", "delivery", "after"}


def test_self_verify_confirm_keeps_move():
    router = FakeRouter(_move("giữ nguyên câu này"), {"kind": "confirm"})
    decision = _decide(router)
    assert isinstance(decision, NextConversationMove)
    assert "giữ nguyên câu này" in decision.say
    assert len(router.requests) == 2
    assert router.requests[1]["name"] == "eris_root_self_verify_v12"


def test_self_verify_revise_uses_new_move_without_reverify():
    router = FakeRouter(
        _move("câu gốc có thể lặp"),
        {"kind": "revise", "intent": "đổi hướng cho đỡ lặp",
         "say": "câu đã sửa, mở tình huống mới", "delivery": "vui",
         "after": "may_continue"},
    )
    decision = _decide(router)
    assert isinstance(decision, NextConversationMove)
    assert "câu đã sửa" in decision.say
    assert decision.after.value == "may_continue"
    # Đúng 2 lượt: move + verify, KHÔNG verify lại move đã revise.
    assert len(router.requests) == 2


def test_self_verify_withdraw_becomes_no_reply():
    router = FakeRouter(_move("câu không nên nói ra"), {"kind": "withdraw"})
    decision = _decide(router)
    assert isinstance(decision, NoReply)
    assert "withdraw" in decision.reason
    assert len(router.requests) == 2


def test_self_verify_failsoft_keeps_original_move_on_exception():
    router = FakeRouter(_move("câu gốc fail-soft"), error=RuntimeError("verify provider down"))
    decision = _decide(router)
    assert isinstance(decision, NextConversationMove)
    assert "câu gốc fail-soft" in decision.say
    assert len(router.requests) == 2


def test_self_verify_failsoft_keeps_original_move_on_garbage():
    router = FakeRouter(_move("câu gốc rác"), {})  # verify trả rác -> kind lạ
    decision = _decide(router)
    assert isinstance(decision, NextConversationMove)
    assert "câu gốc rác" in decision.say
    assert len(router.requests) == 2


def test_self_verify_preempt_before_verify_returns_preempted():
    # still_active True ở move, False trước khi gọi verify.
    active = [True]
    calls = {"n": 0}

    class Router(FakeRouter):
        def invoke_structured_worker(self, client, **kwargs):
            calls["n"] += 1
            answer = super().invoke_structured_worker(client, **kwargs)
            if calls["n"] == 1:  # ngay sau khi move trả về, user chen vào
                active[0] = False
            return answer

    router = Router(_move("câu bị chen ngang"), {"kind": "confirm"})
    decision = _decide(router, context={"__root_run_active": lambda: active[0]})
    assert isinstance(decision, NoReply)
    assert decision.reason == "root_turn_preempted"
    # Preempt kiểm NGAY khi vào verify -> không được gọi model verify.
    assert len(router.requests) == 1


def test_self_verify_preempt_after_verify_returns_preempted():
    # still_active True ở move và lúc vào verify, nhưng False SAU khi verify trả.
    active = [True]

    class Router(FakeRouter):
        def invoke_structured_worker(self, client, **kwargs):
            answer = super().invoke_structured_worker(client, **kwargs)
            if kwargs.get("name") == "eris_root_self_verify_v12":
                active[0] = False  # user chen vào khi verify còn chạy
            return answer

    router = Router(_move("câu verify xong bị chen"), {"kind": "confirm"})
    decision = _decide(router, context={"__root_run_active": lambda: active[0]})
    assert isinstance(decision, NoReply)
    assert decision.reason == "root_turn_preempted"
    assert len(router.requests) == 2  # verify đã chạy nhưng kết quả bị bỏ


def test_no_reply_is_not_verified():
    router = FakeRouter({"kind": "no_reply", "reason": "nothing_worth_saying"})
    decision = _decide(router, event=_event(kind="autonomous_signal"))
    assert isinstance(decision, NoReply)
    assert decision.reason == "nothing_worth_saying"
    assert len(router.requests) == 1  # no_reply finalize NGAY, không verify
