from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from domain import Decision
from parser_grounding import DecisionParser
from runtime.ai_orchestrated.contracts import CognitiveObservation, StateEvent
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter, PUBLIC_REPLY_SCHEMA
from runtime.ai_orchestrated.observer import PostTurnObserver
from runtime.ai_orchestrated.panel_adapter import build_ai_panel_payload
from runtime.ai_orchestrated.stage_planner import StagePlanner
from runtime.ai_orchestrated.state_reducer import StateReducer
from runtime.ai_orchestrated.views import build_cognitive_views


def _observation(turn_seq: int, **overrides) -> CognitiveObservation:
    payload = {
        "user_act": "correction",
        "relationship_meaning": "technical_correction",
        "continuity": "continues_current_task",
        "repair_needed": False,
        "assistant_fault_probability": 0.8,
        "memory_worthy": False,
        "confidence": 0.9,
        "ambiguity": 0.1,
        "relational_delta": 0.0,
        "competence_delta": -0.8,
        "factual_delta": -0.7,
        "boundary_delta": 0.0,
        "familiarity_delta": 0.0,
        "closeness_delta": 0.0,
        "playful_safety_delta": 0.0,
        "rupture_delta": 0.0,
        "appraisal": {
            "pleasantness": 0.4,
            "curiosity": 0.3,
            "tenderness": 0.0,
            "embarrassment": 0.0,
            "irritation": 0.1,
            "pressure": 0.2,
            "novelty": 0.1,
        },
        "open_loop": "",
        "memory_candidate": "",
        "evidence": ["user corrected a function signature"],
        "notes": "",
    }
    payload.update(overrides)
    return CognitiveObservation.from_mapping(
        payload,
        turn_id=f"turn-{turn_seq}",
        turn_seq=turn_seq,
        source="test",
    )


def test_state_reducer_is_single_writer_and_drops_old_or_duplicate_turns():
    reducer = StateReducer()
    try:
        newer = _observation(12, closeness_delta=0.9, competence_delta=0.0, factual_delta=0.0)
        older = _observation(11, closeness_delta=-1.0, competence_delta=0.0, factual_delta=0.0)

        assert reducer.apply_now(StateEvent.from_observation(newer)) is True
        after_new = reducer.snapshot()
        assert after_new.last_applied_turn_seq == 12
        assert after_new.relationship.closeness > 0.20

        assert reducer.apply_now(StateEvent.from_observation(older)) is False
        assert reducer.apply_now(StateEvent.from_observation(newer)) is False
        after_rejected = reducer.snapshot()
        assert after_rejected.relationship.closeness == after_new.relationship.closeness
    finally:
        reducer.close()


def test_technical_correction_changes_competence_not_relationship_rupture():
    reducer = StateReducer()
    try:
        before = reducer.snapshot().relationship
        assert reducer.apply_now(StateEvent.from_observation(_observation(1))) is True
        after = reducer.snapshot().relationship
        assert after.competence_trust < before.competence_trust
        assert after.factual_reliability < before.factual_reliability
        assert after.relational_trust == before.relational_trust
        assert after.rupture == before.rupture
    finally:
        reducer.close()


class _CapturingObserverRouter:
    def __init__(self):
        self.calls = []
        self.called = threading.Event()

    def observe_completed_turn(self, **kwargs):
        self.calls.append(kwargs)
        self.called.set()
        return _observation(kwargs["turn_seq"], user_act="compliment", relationship_meaning="closeness_bid")


def test_post_turn_observer_reads_current_public_reply_and_only_submits_event():
    reducer = StateReducer()
    router = _CapturingObserverRouter()
    observer = PostTurnObserver(router, reducer, workers=1)
    user_meta = {}
    assistant_meta = {}
    try:
        observer.submit(
            turn_id="turn-3",
            turn_seq=3,
            user_text="giọng em hay quá",
            assistant_text="Khen đúng chỗ làm tôi khó giữ vẻ bình thản đấy.",
            recent_history=(),
            state_summary={},
            user_meta=user_meta,
            assistant_meta=assistant_meta,
        )
        assert router.called.wait(1.0)
        assert reducer.wait_idle(1.0)
        assert router.calls[0]["assistant_text"].startswith("Khen đúng chỗ")
        assert reducer.snapshot().last_applied_turn_seq == 3
        assert user_meta["cognitive_observation_pending"] is False
    finally:
        observer.shutdown()
        reducer.close()


class _FakeClient:
    model_name = "openai/gpt-oss-20b"

    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "text": "Tôi nghe đây.",
                "should_speak": True,
                "performance_hint": "soft_warm",
            },
            ensure_ascii=False,
        )
        return {"choices": [{"message": {"content": content}}]}


class _Budget:
    def __init__(self):
        self.calls = []

    def run_queued(self, tier, func, *args, reason="", priority=0, **kwargs):
        self.calls.append((tier, reason, priority))
        return func(*args, **kwargs)


def test_main_model_contract_is_small_and_stage_fields_are_runtime_defaults():
    client = _FakeClient()
    budget = _Budget()
    service = SimpleNamespace(client=client, fallback_client=None, style_client=None)
    router = AIRuntimeModelRouter(service, budget_policy=budget)

    payload = router.generate_public_reply(
        chat_history=[],
        user_text="xin chào",
        relationship_context="Độ quen thuộc đang ở mức vừa",
    )

    required = set(client.calls[0]["response_format"]["json_schema"]["schema"]["required"])
    assert required == {"text", "should_speak", "performance_hint"}
    assert required == set(PUBLIC_REPLY_SCHEMA["required"])
    assert payload["text"] == "Tôi nghe đây."
    assert payload["animation"] == "stand"
    assert payload["stage_motion"] == ""
    assert payload["system_action"] == ""
    assert budget.calls == [("main_cognition", "architecture_c_public_reply", 100)]


def test_parser_preserves_performance_hint_and_stage_planner_expands_it():
    parser = DecisionParser(Decision(text="", animation="stand", should_speak=False))
    raw = json.dumps(
        {
            "text": "Hm. Bạn khá biết chọn lời đấy.",
            "should_speak": True,
            "system_action": "",
            "action_input": "",
            "performance_hint": "dry_tease",
            "animation": "stand",
            "next_animation": "",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "delivery_hint": "",
            "nonverbal_cue": "",
            "stage_motion": "",
        },
        ensure_ascii=False,
    )
    decision = parser.parse(raw)
    assert decision.performance_hint == "dry_tease"

    StagePlanner().apply(decision, decision.performance_hint)
    assert decision.delivery_hint == "dry_tease"
    assert decision.nonverbal_cue == "scoff_soft"
    assert decision.stage_motion == "blink_slow"


def test_cognitive_views_are_read_only_projections_of_one_state():
    reducer = StateReducer()
    try:
        assert reducer.apply_now(StateEvent.from_observation(_observation(4))) is True
        state = reducer.snapshot()
        views = build_cognitive_views(state)
        assert views["ni"]["continuity"] == "continues_current_task"
        assert views["fe"]["relationship_meaning"] == "technical_correction"
        assert views["ti"]["competence_trust"] == state.relationship.competence_trust
        assert views["authority"]["text_mutation_authority"] is False
        assert views["authority"]["state_write_authority"] == "StateReducer"
    finally:
        reducer.close()


def test_ai_panel_payload_comes_from_reducer_state_not_legacy_cortex():
    reducer = StateReducer()
    try:
        assert reducer.apply_now(StateEvent.from_observation(_observation(7))) is True
        payload = build_ai_panel_payload(reducer.snapshot())
        assert payload["emotion_debug"]["architecture"] == "ai_orchestrated.v1"
        assert payload["depth_v2"]["turn_seq"] == 7
        assert payload["cognitive_views"]["ti"]["factual_reliability"] < 0.50
        assert payload["private_mind_digest"]["architecture"] == "ai_orchestrated.v1"
    finally:
        reducer.close()


def test_architecture_c_routes_chat_autonomous_and_force_speak_before_legacy_cortex():
    from runtime.autonomous_cycle import AutonomousCycleMixin
    from runtime.chat_cycle import ChatCycleMixin
    from runtime.force_speak_cycle import ForceSpeakCycleMixin

    calls = []

    class _ChatOrchestrator:
        def run(self, user_text, **kwargs):
            calls.append(("chat", user_text, kwargs["cycle_start"]))

    class _AutoOrchestrator:
        def run_iteration(self):
            calls.append(("autonomous",))
            return True

        def run_force_speak(self):
            calls.append(("force_speak",))

    host = SimpleNamespace(
        ai_runtime_enabled=True,
        ai_chat_orchestrator=_ChatOrchestrator(),
        ai_autonomous_orchestrator=_AutoOrchestrator(),
    )

    ChatCycleMixin._run_chat_cycle_inner(host, "xin chào", cycle_start=1.25)
    assert AutonomousCycleMixin._run_loop_iteration(host) is True
    ForceSpeakCycleMixin._handle_force_speak_request(host)
    assert calls == [
        ("chat", "xin chào", 1.25),
        ("autonomous",),
        ("force_speak",),
    ]


class _PlannerAndSpeakerClient:
    model_name = "openai/gpt-oss-20b"

    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["response_format"]["json_schema"]["name"]
        if name == "eris_chat_intention":
            content = {
                "plan_id": "plan-chat-1",
                "speak": True,
                "motive": "execute_user_request",
                "topic": "Acknowledge and perform the requested volume change.",
                "importance": 0.8,
                "intrusion_risk": 0.0,
                "confidence": 0.88,
                "performance_hint": "focused",
                "tool_intent": "set_volume",
                "tool_input": "35",
                "evidence_refs": ["explicit user request"],
                "notes": "",
            }
        else:
            content = {
                "text": "Tôi chỉnh xuống 35 nhé.",
                "should_speak": True,
                "performance_hint": "focused",
            }
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def test_chat_planner_owns_tool_intent_while_speaker_only_writes_text():
    client = _PlannerAndSpeakerClient()
    service = SimpleNamespace(
        client=client,
        social_parser_client=client,
        social_critic_client=None,
        social_fallback_client=None,
        fallback_client=None,
        style_client=None,
    )
    router = AIRuntimeModelRouter(service)
    plan = router.plan_chat({"user_text": "giảm âm lượng còn 35"})
    payload = router.generate_public_reply(
        chat_history=[],
        user_text="giảm âm lượng còn 35",
        planned_intention=plan,
    )

    assert plan.tool_intent == "set_volume"
    assert plan.tool_input == "35"
    assert payload["system_action"] == "set_volume"
    assert payload["action_input"] == "35"
    public_required = client.calls[-1]["response_format"]["json_schema"]["schema"]["required"]
    assert "system_action" not in public_required
    assert "action_input" not in public_required


def test_autonomous_observation_updates_inner_appraisal_without_inventing_relationship_change():
    reducer = StateReducer()
    try:
        before = reducer.snapshot()
        obs = _observation(
            20,
            event_kind="autonomous",
            relationship_meaning="self_expression",
            relational_delta=1.0,
            closeness_delta=1.0,
            familiarity_delta=1.0,
            rupture_delta=1.0,
            repair_needed=True,
            appraisal={
                "pleasantness": 0.7,
                "curiosity": 0.8,
                "tenderness": 0.2,
                "embarrassment": 0.0,
                "irritation": 0.0,
                "pressure": 0.1,
                "novelty": 0.6,
            },
        )
        assert reducer.apply_now(StateEvent.from_observation(obs)) is True
        after = reducer.snapshot()
        assert after.relationship.relational_trust == before.relationship.relational_trust
        assert after.relationship.closeness == before.relationship.closeness
        assert after.relationship.familiarity == before.relationship.familiarity
        assert after.relationship.rupture == before.relationship.rupture
        assert after.appraisal.curiosity == 0.8
        assert after.last_applied_turn_seq == 20
    finally:
        reducer.close()


def test_post_turn_observer_forwards_event_kind_to_model_router():
    reducer = StateReducer()
    router = _CapturingObserverRouter()
    observer = PostTurnObserver(router, reducer, workers=1)
    try:
        observer.submit(
            turn_id="autonomous:21",
            turn_seq=21,
            user_text="",
            assistant_text="Tôi vừa nhớ ra một điều đáng hỏi.",
            event_kind="autonomous",
        )
        assert router.called.wait(1.0)
        assert reducer.wait_idle(1.0)
        assert router.calls[0]["event_kind"] == "autonomous"
    finally:
        observer.shutdown()
        reducer.close()
