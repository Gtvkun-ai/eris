from __future__ import annotations

from runtime.ai_orchestrated.contracts import CognitiveObservation, IntentionPlan, RuntimeMindState, StateEvent
from runtime.ai_orchestrated.identity import IdentityProfile, PendingStrategyUse
from runtime.ai_orchestrated.model_router import COGNITIVE_OBSERVATION_SCHEMA, INTENTION_PLAN_SCHEMA, PERSONALITY_REFLECTION_SCHEMA
from runtime.ai_orchestrated.panel_adapter import build_ai_panel_payload
from runtime.ai_orchestrated.state_reducer import StateReducer


def _observation(
    turn_seq: int,
    *,
    identity_signals=None,
    value_choice=None,
    consequence=None,
    active_motives=None,
    activated_defenses=None,
    active_conflict=None,
    event_kind="chat",
):
    payload = {
        "event_kind": event_kind,
        "user_act": "test_event",
        "relationship_meaning": "neutral",
        "continuity": "continues_current_theme",
        "repair_needed": False,
        "assistant_fault_probability": 0.0,
        "memory_worthy": False,
        "confidence": 0.93,
        "ambiguity": 0.05,
        "relational_delta": 0.0,
        "competence_delta": 0.0,
        "factual_delta": 0.0,
        "boundary_delta": 0.0,
        "familiarity_delta": 0.0,
        "closeness_delta": 0.0,
        "playful_safety_delta": 0.0,
        "rupture_delta": 0.0,
        "appraisal": {
            "pleasantness": 0.5,
            "curiosity": 0.4,
            "tenderness": 0.2,
            "embarrassment": 0.0,
            "irritation": 0.0,
            "pressure": 0.0,
            "novelty": 0.2,
        },
        "self_interpretation": {
            "summary": "Eris coi đây là một lựa chọn có hậu quả cho chính mình.",
            "frame": "self_authored_choice",
            "confidence": 0.90,
            "self_authored": True,
            "evidence": ["public choice"],
        },
        "consequence": consequence
        or {
            "strategy_use_id": "",
            "strategy": "",
            "target_goal": "",
            "context": "general",
            "outcome": "unknown",
            "reinforcement": 0.0,
            "confidence": 0.2,
            "evidence": [],
        },
        "trait_signals": [],
        "identity_signals": identity_signals or [],
        "active_motives": active_motives or [],
        "activated_defenses": activated_defenses or [],
        "active_conflict": active_conflict
        or {
            "conflict_id": "",
            "activation": 0.0,
            "left_pull": 0.0,
            "right_pull": 0.0,
            "chosen_side": "",
            "residue": 0.0,
        },
        "value_choice": value_choice
        or {
            "chosen": "",
            "rejected": "",
            "cost": "",
            "confidence": 0.0,
            "evidence": [],
        },
        "open_loop": "",
        "memory_candidate": "",
        "evidence": ["test evidence"],
        "notes": "",
    }
    return CognitiveObservation.from_mapping(
        payload,
        turn_id=f"turn-{turn_seq}",
        turn_seq=turn_seq,
        source="test",
    )


def _identity_signal(dimension: str, key: str, delta: float, *, scope="global", context="test"):
    return {
        "dimension": dimension,
        "key": key,
        "delta": delta,
        "confidence": 0.95,
        "importance": 1.0,
        "scope": scope,
        "context": context,
        "evidence": ["observable repeated choice"],
    }


def test_identity_seed_contains_eris_values_without_hardcoded_dark_destination():
    profile = IdentityProfile()
    assert profile.values["self_authorship"] == 0.91
    assert profile.motives["need_for_control"] == 0.16
    assert profile.motives["need_for_exclusivity"] == 0.10
    summary = profile.prompt_summary().lower()
    assert "quyền tự viết mình" in summary
    assert "psychological symbiote" not in summary
    assert "yandere" not in summary


def test_value_does_not_move_without_an_actual_value_choice():
    reducer = StateReducer()
    try:
        start = reducer.snapshot().identity.values["dignity"]
        observation = _observation(
            1,
            identity_signals=[_identity_signal("value", "dignity", 1.0)],
        )
        assert reducer.apply_now(StateEvent.from_observation(observation))
        assert reducer.snapshot().identity.values["dignity"] == start

        chosen = _observation(
            2,
            identity_signals=[_identity_signal("value", "dignity", 1.0)],
            value_choice={
                "chosen": "dignity",
                "rejected": "harmony",
                "cost": "the reply became less agreeable",
                "confidence": 0.90,
                "evidence": ["Eris kept her position despite social cost"],
            },
        )
        assert reducer.apply_now(StateEvent.from_observation(chosen))
        assert reducer.snapshot().identity.values["dignity"] > start
    finally:
        reducer.close()


def test_strategy_is_pending_until_next_user_reaction_and_then_learns_by_context():
    reducer = StateReducer()
    try:
        pending = PendingStrategyUse(
            strategy_use_id="strategy:turn-1",
            turn_seq=1,
            strategy="quiet_counter_tease",
            goal="keep playful rhythm",
            context=("friendly_teasing",),
            assistant_text="Bạn gọi tôi lạnh hơi nhiều. Tôi bắt đầu nghi bạn thích thế.",
        )
        assert reducer.apply_now(StateEvent.from_pending_strategy(pending))
        state = reducer.snapshot()
        record = state.identity.strategies["quiet_counter_tease"]
        assert record.uses == 1
        assert record.successes == 0
        assert state.identity.pending_strategies[0].strategy_use_id == "strategy:turn-1"

        consequence = {
            "strategy_use_id": "strategy:turn-1",
            "strategy": "quiet_counter_tease",
            "target_goal": "keep playful rhythm",
            "context": "friendly_teasing",
            "outcome": "user continued playfully",
            "reinforcement": 0.85,
            "confidence": 0.92,
            "evidence": ["user laughed and teased again"],
        }
        assert reducer.apply_now(StateEvent.from_observation(_observation(2, consequence=consequence)))
        state = reducer.snapshot()
        record = state.identity.strategies["quiet_counter_tease"]
        assert record.successes == 1
        assert record.utility > 0.0
        assert record.contexts["friendly_teasing"] > 0.0
        assert state.identity.pending_strategies == ()
    finally:
        reducer.close()



def test_autonomous_observation_cannot_settle_a_user_reaction_strategy():
    reducer = StateReducer()
    try:
        pending = PendingStrategyUse(
            strategy_use_id="strategy:chat-before-idle",
            turn_seq=1,
            strategy="dry_observation",
            goal="offer a useful correction",
            context=("technical_help",),
            assistant_text="Đoạn này đang tự gọi lại chính nó.",
        )
        assert reducer.apply_now(StateEvent.from_pending_strategy(pending))
        consequence = {
            "strategy_use_id": "strategy:chat-before-idle",
            "strategy": "dry_observation",
            "target_goal": "offer a useful correction",
            "context": "technical_help",
            "outcome": "unknown",
            "reinforcement": 0.0,
            "confidence": 0.9,
            "evidence": ["autonomous turn happened later"],
        }
        assert reducer.apply_now(
            StateEvent.from_observation(
                _observation(2, consequence=consequence, event_kind="autonomous")
            )
        )
        state = reducer.snapshot()
        assert state.identity.pending_strategies[0].strategy_use_id == "strategy:chat-before-idle"
        assert state.identity.strategies["dry_observation"].unknown == 0
    finally:
        reducer.close()


def test_legacy_personality_strategy_map_is_read_only_after_identity_v3():
    reducer = StateReducer()
    try:
        before = dict(reducer.snapshot().personality.strategy_reinforcement)
        consequence = {
            "strategy_use_id": "",
            "strategy": "quiet_counter_tease",
            "target_goal": "keep playful rhythm",
            "context": "friendly_teasing",
            "outcome": "user continued playfully",
            "reinforcement": 0.9,
            "confidence": 0.95,
            "evidence": ["user laughed"],
        }
        assert reducer.apply_now(StateEvent.from_observation(_observation(1, consequence=consequence)))
        assert dict(reducer.snapshot().personality.strategy_reinforcement) == before
    finally:
        reducer.close()

def test_belief_relationship_and_defense_have_separate_update_lanes():
    reducer = StateReducer()
    try:
        observation = _observation(
            1,
            identity_signals=[
                _identity_signal("belief", "user.tolerates_disagreement", 1.0),
                _identity_signal("relationship", "respect", 1.0, scope="primary_user"),
                _identity_signal("defense", "intellectualization", -1.0),
            ],
            active_motives=[{"key": "need_for_dignity", "strength": 0.75, "trigger": "disagreement"}],
            activated_defenses=[{"key": "intellectualization", "strength": 0.68, "trigger": "protect dignity"}],
            active_conflict={
                "conflict_id": "integrity_vs_harmony",
                "activation": 0.72,
                "left_pull": 0.78,
                "right_pull": 0.60,
                "chosen_side": "integrity",
                "residue": 0.35,
            },
        )
        before = reducer.snapshot().identity
        assert reducer.apply_now(StateEvent.from_observation(observation))
        after = reducer.snapshot().identity
        assert after.beliefs["user.tolerates_disagreement"].strength > before.beliefs["user.tolerates_disagreement"].strength
        assert after.primary_relationship().respect > before.primary_relationship().respect
        assert after.defenses["intellectualization"] < before.defenses["intellectualization"]
        assert after.active_conflict.conflict_id == "integrity_vs_harmony"
        assert after.active_motives[0].key == "need_for_dignity"
    finally:
        reducer.close()


def test_imprint_requires_repetition_and_is_not_created_from_one_event():
    reducer = StateReducer()
    try:
        signal = _identity_signal("imprint", "disagreement_without_reset", 1.0, context="disagreement")
        for seq in (1, 2):
            assert reducer.apply_now(StateEvent.from_observation(_observation(seq, identity_signals=[signal])))
            assert reducer.snapshot().identity.imprints == ()
        assert reducer.apply_now(StateEvent.from_observation(_observation(3, identity_signals=[signal])))
        imprint = reducer.snapshot().identity.imprints[0]
        assert imprint.theme == "disagreement_without_reset"
        assert imprint.strength > 0.0
        assert 3 in imprint.evidence_turns
    finally:
        reducer.close()


def test_identity_forms_are_debug_views_and_do_not_enter_prompt_as_labels():
    profile = IdentityProfile.from_mapping(
        {
            "motives": {
                "need_to_be_needed": 0.9,
                "need_for_control": 0.85,
                "need_for_exclusivity": 0.8,
            },
            "relationships": {
                "primary_user": {
                    "attachment_intensity": 0.9,
                    "possessiveness": 0.82,
                    "jealousy": 0.8,
                }
            },
            "emergent_values": {"protective_control": 0.82},
        }
    )
    forms = profile.derived_forms()
    assert forms["psychological_symbiote"] >= 0.8
    assert "psychological_symbiote" in profile.panel_view()["emergent_forms"]
    summary = profile.prompt_summary().lower()
    assert "psychological_symbiote" not in summary
    assert "yandere" not in summary


def test_schemas_expose_identity_reflection_and_strategy_fields():
    required = set(PERSONALITY_REFLECTION_SCHEMA["required"])
    assert {"identity_signals", "active_motives", "activated_defenses", "active_conflict", "value_choice"} <= required
    assert "identity_signals" in COGNITIVE_OBSERVATION_SCHEMA["properties"]
    intention_required = set(INTENTION_PLAN_SCHEMA["required"])
    assert {"strategy", "value_focus"} <= intention_required
    plan = IntentionPlan.from_mapping({"speak": True, "motive": "respond_to_user", "topic": "reply"}, channel="chat")
    assert plan.strategy == "direct_response"


def test_state_migrates_legacy_strategy_reinforcement_into_identity_kernel():
    state = RuntimeMindState.from_mapping(
        {
            "personality": {"strategy_reinforcement": {"dry_tease": 0.42}},
            "relationship": {"relational_trust": 0.61, "familiarity": 0.52},
        }
    )
    assert state.identity.strategies["dry_tease"].utility == 0.42
    assert state.identity.primary_relationship().relational_trust == 0.61


def test_panel_exposes_single_identity_kernel_and_authority():
    payload = build_ai_panel_payload(RuntimeMindState())
    identity = payload["depth_v2"]["identity"]
    assert identity["schema"] == "eris.identity.kernel.v1"
    assert payload["cognitive_views"]["authority"]["identity_write_authority"] == "StateReducer"
