from __future__ import annotations

import json
from types import SimpleNamespace

from cortex.internal_state import PersistentInternalState
from runtime.social_cognition_v2 import SocialCognitionEngine
from runtime.social_model_router import SocialModelRouter
from runtime.social_observer import SocialObservation, SocialObserverRuntime


class _Client:
    def __init__(self, payload, model_name: str):
        self.payload = payload
        self.model_name = model_name
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class _Service:
    def __init__(self):
        self.social_parser_client = _Client(
            {
                "act": "affection_bid",
                "closeness_bid": 0.82,
                "vulnerability": 0.35,
                "compliment": 0.65,
                "playfulness": 0.30,
                "correction": 0.0,
                "repair_signal": 0.0,
                "assistant_fault_probability": 0.0,
                "hostility": 0.0,
                "acceptance": 0.55,
                "boundary_probe": 0.0,
                "user_requests_less_distance": 0.72,
                "ambiguity": 0.62,
                "confidence": 0.61,
                "memory_worthy": True,
                "evidence": ["tui nhớ em quá"],
                "notes": "closeness bid rõ nhưng cần deep review",
            },
            "openai/gpt-oss-20b",
        )
        self.social_critic_client = _Client(
            {
                "act": "affection_bid",
                "closeness_bid": 0.91,
                "vulnerability": 0.54,
                "compliment": 0.40,
                "playfulness": 0.18,
                "correction": 0.0,
                "repair_signal": 0.0,
                "assistant_fault_probability": 0.0,
                "hostility": 0.0,
                "acceptance": 0.60,
                "boundary_probe": 0.0,
                "user_requests_less_distance": 0.84,
                "ambiguity": 0.12,
                "confidence": 0.88,
                "memory_worthy": True,
                "evidence": ["không biết eris có nghĩ về tui"],
                "notes": "affection bid trực tiếp",
            },
            "openai/gpt-oss-120b",
        )
        self.social_fallback_client = _Client({}, "llama-3.1-8b-instant")
        self.client = None


class _Host:
    def __init__(self):
        self._state = PersistentInternalState()
        self.social_cognition_v2 = SocialCognitionEngine()
        self.latest_social_observation = None
        self.current_social_observation = None
        self.pending_social_repair = False

    def _get_internal_state(self):
        return self._state

    def _set_internal_state(self, state):
        self._state = state


def test_router_uses_strict_primary_and_deep_review() -> None:
    service = _Service()
    router = SocialModelRouter(service)
    observation = router.observe_turn(
        user_text="Hôm nay trời mưa, làm tui nhớ em quá, không biết Eris có nghĩ về tui",
        previous_assistant_text="",
        previous_user_text="",
        history=(),
    )

    assert observation.source == "groq_social_deep"
    assert observation.act == "affection_bid"
    assert observation.confidence == 0.88
    primary_format = service.social_parser_client.calls[0]["response_format"]
    deep_format = service.social_critic_client.calls[0]["response_format"]
    assert primary_format["type"] == "json_schema"
    assert primary_format["json_schema"]["strict"] is True
    assert deep_format["json_schema"]["strict"] is True


def test_observer_runtime_updates_state_after_completion_without_public_rewrite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ERIS_MEMORY_CORE_DIR", str(tmp_path))
    service = _Service()
    router = SocialModelRouter(service)
    runtime = SocialObserverRuntime(router, max_workers=1)
    host = _Host()
    user_meta = {}
    assistant_meta = {}

    previous_frame = SimpleNamespace(outcome=None, metadata={})
    ticket = runtime.submit(
        user_text="Tui nhớ em quá",
        previous_assistant_text="",
        previous_user_text="",
        history=(),
        turn_id="turn-1",
        metadata_target=user_meta,
        previous_frame=previous_frame,
    )
    ticket.future.result(timeout=3)
    runtime.complete(
        ticket,
        host=host,
        assistant_text="Tôi nghe thấy rồi.",
        assistant_meta=assistant_meta,
    )

    assert user_meta["social_observer"]["act"] == "affection_bid"
    assert user_meta["social_observer_pending"] is False
    assert assistant_meta["social_observer_source"] == "groq_social_deep"
    assert host.latest_social_observation.act == "affection_bid"
    assert host._state.relationship_dynamics.last_event == "ai_observer:affection_bid"
    assert host._state.relationship_dynamics.engagement_investment > 0.0
    assert previous_frame.outcome is not None
    assert "ai_social_observer" in previous_frame.outcome.tags
    assert previous_frame.metadata["ai_social_feedback"]["act"] == "affection_bid"
    panel_payload = json.loads((tmp_path / "panel_snapshot.json").read_text(encoding="utf-8"))
    assert panel_payload["social_observer"]["act"] == "affection_bid"
    assert panel_payload["relationship_state"]["last_event"] == "ai_observer:affection_bid"
    # Observer chỉ nhận assistant_text để ghi context; không có API nào trả text thay thế.
    assert not hasattr(host.latest_social_observation, "text")
    runtime.shutdown()


def test_prompt_context_is_compact_and_only_uses_previous_observation() -> None:
    host = _Host()
    host.latest_social_observation = SocialObservation(
        act="correction",
        correction=0.88,
        repair_signal=0.81,
        confidence=0.90,
        source="test",
    )
    context = SocialObserverRuntime.build_prompt_context(host)
    assert "cần sửa" in context
    assert "response_move" not in context
    assert len(context) < 220
