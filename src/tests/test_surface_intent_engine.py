from __future__ import annotations

from dataclasses import dataclass

from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine


@dataclass
class _State:
    version: int = 3


class _Reducer:
    def __init__(self):
        self.events = []

    def snapshot(self):
        return _State()

    def submit(self, event):
        self.events.append(event)


class _Router:
    def __init__(self, payload):
        self.surface_client = object()
        self.payload = payload
        self.requests = []

    def plan_surface_intent(self, snapshot):
        self.requests.append(snapshot)
        return dict(self.payload)

    def build_surface_public_payload(self, *, text, plan, mode):
        return {
            "text": text,
            "should_speak": True,
            "performance_hint": plan.performance_hint,
            "mode": mode,
        }


def _snapshot(**overrides):
    data = {
        "telemetry": {},
        "screen_context": {
            "fresh": False,
            "privacy_blocked": False,
            "evidence_refs": [],
            "visible_text": [],
            "changed_text": [],
        },
        "vision_facts": [],
        "conversation_baton": {
            "reply_expected": False,
            "assistant_may_continue": False,
            "thread_fresh": False,
            "thread_key": "none",
        },
        "self_context": {"has_public_seed": False},
        "engagement_context": {"active": False},
        "commentary_expectation": {"due": True},
        "seconds_since_assistant": 180.0,
        "open_loops": [],
        "recent_public_history": [],
    }
    data.update(overrides)
    return data


def test_surface_worker_writes_small_talk_in_one_call():
    router = _Router(
        {
            "decision": "speak",
            "mode": "dry_tease",
            "topic": "user has been quiet for a while",
            "text": "Im lâu vậy, tôi sắp tính phí làm vật trang trí rồi đó.",
            "confidence": 0.84,
            "performance_hint": "dry",
            "anchor_type": "idle",
            "anchor_id": "",
            "evidence_refs": [],
            "reason": "idle cadence is due",
        }
    )
    reducer = _Reducer()
    engine = SurfaceIntentEngine(router, reducer)

    result = engine.deliberate(_snapshot(), turn_seq=9)

    assert result is not None
    assert result.mode == "dry_tease"
    assert result.plan.speak is True
    assert result.plan.strategy == "dry_tease"
    assert result.public_payload["text"].startswith("Im lâu")
    assert router.requests[0]["surface_contract"]["allowed_modes"]
    assert len(reducer.events) == 1


def test_surface_screen_comment_is_rejected_without_fresh_evidence():
    router = _Router(
        {
            "decision": "speak",
            "mode": "screen_comment",
            "topic": "current screen",
            "text": "Tôi thấy cậu đang mở bàn cờ.",
            "confidence": 0.91,
            "performance_hint": "curious",
            "anchor_type": "screen",
            "anchor_id": "screen:board",
            "evidence_refs": ["screen:board"],
            "reason": "screen changed",
        }
    )
    engine = SurfaceIntentEngine(router, _Reducer())

    result = engine.deliberate(_snapshot(), turn_seq=10)

    assert result is not None
    assert result.mode == "silence"
    assert result.plan.speak is False
    assert result.reason.startswith("surface_mode_not_allowed")


def test_surface_keeps_engagement_focused_on_task():
    router = _Router(
        {
            "decision": "speak",
            "mode": "random_chat",
            "topic": "unrelated banter",
            "text": "Tự nhiên tôi muốn kiếm chuyện với cậu.",
            "confidence": 0.80,
            "performance_hint": "playful",
            "anchor_type": "idle",
            "anchor_id": "",
            "evidence_refs": [],
            "reason": "idle",
        }
    )
    engine = SurfaceIntentEngine(router, _Reducer())

    result = engine.deliberate(
        _snapshot(engagement_context={"active": True, "kind": "chess"}),
        turn_seq=11,
    )

    assert result is not None
    assert result.plan.speak is False
    assert result.reason == "surface_mode_not_allowed:random_chat"
