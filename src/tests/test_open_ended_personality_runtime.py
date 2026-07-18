from __future__ import annotations

import json
import time
from types import SimpleNamespace

from runtime.ai_orchestrated.contracts import CognitiveObservation, RuntimeMindState, StateEvent
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter, COGNITIVE_OBSERVATION_SCHEMA
from runtime.ai_orchestrated.panel_adapter import build_ai_panel_payload
from runtime.ai_orchestrated.personality import PersonalityProfile, decay_profile
from runtime.ai_orchestrated.state_reducer import StateReducer
from llm.contracts import CHAT_RULES_PROMPT, RUNTIME_RULES_PROMPT, STYLE_FALLBACK_PROMPT


def _observation(turn_seq: int, *, signals=None, event_kind="chat", interpretation=None, consequence=None):
    payload = {
        "event_kind": event_kind,
        "user_act": "test_event",
        "relationship_meaning": "neutral",
        "continuity": "continues_current_theme",
        "repair_needed": False,
        "assistant_fault_probability": 0.0,
        "memory_worthy": False,
        "confidence": 0.92,
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
            "tenderness": 0.3,
            "embarrassment": 0.0,
            "irritation": 0.0,
            "pressure": 0.0,
            "novelty": 0.2,
        },
        "self_interpretation": interpretation
        or {
            "summary": "Eris coi đây là một trải nghiệm có ý nghĩa cho cách mình hành động.",
            "frame": "self_reflection",
            "confidence": 0.90,
            "self_authored": True,
            "evidence": ["public outcome"],
        },
        "consequence": consequence
        or {
            "strategy": "direct_response",
            "outcome": "interaction continued",
            "reinforcement": 0.6,
            "confidence": 0.88,
            "evidence": ["user continued the exchange"],
        },
        "trait_signals": signals or [],
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


def _signal(trait: str, delta: float, *, category="temperament", source="user_interaction"):
    return {
        "category": category,
        "trait": trait,
        "delta": delta,
        "confidence": 0.95,
        "importance": 1.0,
        "source": source,
        "evidence": ["repeated observable outcome"],
        "strategy": "direct_response",
    }


def test_default_profile_is_erislive_seed_without_type_label_in_prompt():
    profile = PersonalityProfile()
    summary = profile.prompt_summary().lower()
    assert profile.core["meaning_drive"] == 0.89
    assert profile.temperament["dry_humor"] == 0.47
    assert profile.temperament["possessiveness"] == 0.08
    assert "infj" not in summary
    assert "5w4" not in summary
    assert "594" not in summary
    assert "yandere" not in summary
    assert "hóm hỉnh khô" in summary


def test_temperament_can_move_both_directions_without_maturity_target():
    reducer = StateReducer()
    try:
        before = reducer.snapshot().personality.temperament["resentment"]
        assert reducer.apply_now(
            StateEvent.from_observation(_observation(1, signals=[_signal("resentment", 1.0)]))
        )
        raised = reducer.snapshot().personality.temperament["resentment"]
        assert raised > before

        assert reducer.apply_now(
            StateEvent.from_observation(_observation(2, signals=[_signal("resentment", -1.0)]))
        )
        lowered = reducer.snapshot().personality.temperament["resentment"]
        assert lowered < raised
        assert reducer.snapshot().personality.trajectory
    finally:
        reducer.close()


def test_core_requires_repeated_corroboration_before_it_moves():
    reducer = StateReducer()
    try:
        start = reducer.snapshot().personality.core["self_authorship"]
        for seq in (1, 2):
            assert reducer.apply_now(
                StateEvent.from_observation(
                    _observation(seq, signals=[_signal("self_authorship", 1.0, category="core")])
                )
            )
            assert reducer.snapshot().personality.core["self_authorship"] == start

        assert reducer.apply_now(
            StateEvent.from_observation(
                _observation(3, signals=[_signal("self_authorship", 1.0, category="core")])
            )
        )
        assert reducer.snapshot().personality.core["self_authorship"] > start
    finally:
        reducer.close()


def test_autonomous_stable_growth_requires_self_choice_and_real_consequence():
    reducer = StateReducer()
    try:
        start = reducer.snapshot().personality.temperament["initiative"]
        weak = _observation(
            1,
            event_kind="autonomous",
            signals=[_signal("initiative", 1.0, source="self_choice")],
            consequence={
                "strategy": "self_started_repair",
                "outcome": "unknown",
                "reinforcement": 0.0,
                "confidence": 0.4,
                "evidence": [],
            },
        )
        assert reducer.apply_now(StateEvent.from_observation(weak))
        assert reducer.snapshot().personality.temperament["initiative"] == start

        strong = _observation(
            2,
            event_kind="autonomous",
            signals=[_signal("initiative", 1.0, source="self_choice")],
            consequence={
                "strategy": "self_started_repair",
                "outcome": "task completed",
                "reinforcement": 0.9,
                "confidence": 0.92,
                "evidence": ["runtime confirmed completion"],
            },
        )
        assert reducer.apply_now(StateEvent.from_observation(strong))
        assert reducer.snapshot().personality.temperament["initiative"] > start
    finally:
        reducer.close()


def test_mood_decays_to_its_own_baseline_not_to_a_moral_target():
    now = time.time()
    profile = PersonalityProfile.from_mapping(
        {
            "mood": {"irritation": 1.0},
            "last_decay_at": now - 3 * 3600,
        }
    )
    decayed = decay_profile(profile, now=now)
    # Irritation half-life is 3h: it should be halfway from 1.0 to baseline 0.08.
    assert 0.52 <= decayed.mood["irritation"] <= 0.56


def test_emergent_yandere_is_a_debug_view_not_a_prompt_label():
    profile = PersonalityProfile.from_mapping(
        {
            "temperament": {
                "attachment_intensity": 0.88,
                "abandonment_sensitivity": 0.82,
                "possessiveness": 0.84,
                "control_seeking": 0.76,
                "rumination": 0.86,
                "reality_anchoring": 0.22,
            }
        }
    )
    forms = profile.derived_forms()
    assert forms["yandere_tendency"] >= 0.75
    assert "yandere" not in profile.prompt_summary().lower()
    assert "yandere_tendency" in profile.panel_view()["emergent_forms"]


def test_observer_schema_carries_interpretation_consequence_and_trait_signals():
    required = set(COGNITIVE_OBSERVATION_SCHEMA["required"])
    assert {"self_interpretation", "consequence", "trait_signals"} <= required
    signal_schema = COGNITIVE_OBSERVATION_SCHEMA["properties"]["trait_signals"]
    assert signal_schema["maxItems"] == 10


class _CaptureClient:
    model_name = "openai/gpt-oss-20b"

    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "text": "Tôi nghe đây.",
                                "should_speak": True,
                                "performance_hint": "neutral",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def test_main_model_receives_current_personality_as_inertia_not_type_label():
    client = _CaptureClient()
    router = AIRuntimeModelRouter(SimpleNamespace(client=client, fallback_client=None, style_client=None))
    profile = PersonalityProfile()
    router.generate_public_reply(
        chat_history=[],
        user_text="xin chào",
        personality_context=profile.prompt_summary(),
    )
    system = client.calls[0]["messages"][0]["content"].lower()
    assert "current eris personality" in system
    assert "không cố diễn một nhãn" in system
    assert "infj 5w4" not in system


def test_panel_exposes_trajectory_and_emergent_forms_from_single_state():
    state = RuntimeMindState()
    payload = build_ai_panel_payload(state)
    personality = payload["depth_v2"]["personality"]
    assert personality["schema"] == "eris.personality.open_ended.v1"
    assert "emergent_forms" in personality
    assert payload["cognitive_views"]["authority"]["personality_write_authority"] == "StateReducer"
    assert payload["cognitive_views"]["development"]["no_maturity_target"] is True

class _TwoLaneClient:
    model_name = "openai/gpt-oss-20b"

    def __init__(self):
        self.names = []

    def create_chat_completion(self, **kwargs):
        name = kwargs["response_format"]["json_schema"]["name"]
        self.names.append(name)
        if name == "eris_cognitive_observation":
            content = {
                "event_kind": "chat",
                "user_act": "compliment",
                "relationship_meaning": "closeness_bid",
                "continuity": "continues_current_theme",
                "repair_needed": False,
                "assistant_fault_probability": 0.0,
                "memory_worthy": False,
                "confidence": 0.91,
                "ambiguity": 0.08,
                "relational_delta": 0.2,
                "competence_delta": 0.0,
                "factual_delta": 0.0,
                "boundary_delta": 0.0,
                "familiarity_delta": 0.1,
                "closeness_delta": 0.2,
                "playful_safety_delta": 0.1,
                "rupture_delta": 0.0,
                "appraisal": {
                    "pleasantness": 0.8,
                    "curiosity": 0.3,
                    "tenderness": 0.7,
                    "embarrassment": 0.4,
                    "irritation": 0.0,
                    "pressure": 0.1,
                    "novelty": 0.2,
                },
                "consequence": {
                    "strategy": "accept_warmth",
                    "outcome": "closeness continued",
                    "reinforcement": 0.7,
                    "confidence": 0.88,
                    "evidence": ["user continued warmly"],
                },
                "open_loop": "",
                "memory_candidate": "",
                "evidence": ["user complimented ERIS"],
                "notes": "",
            }
        else:
            content = {
                "self_interpretation": {
                    "summary": "Sự ấm áp này có vẻ an toàn để đáp lại.",
                    "frame": "safe_reciprocity",
                    "confidence": 0.86,
                    "self_authored": True,
                    "evidence": ["ERIS accepted the compliment"],
                },
                "trait_signals": [
                    {
                        "category": "temperament",
                        "trait": "warmth_expression",
                        "delta": 0.6,
                        "confidence": 0.84,
                        "importance": 0.7,
                        "source": "consequence",
                        "evidence": ["warm response preserved closeness"],
                        "strategy": "accept_warmth",
                    }
                ],
                "notes": "",
            }
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def test_observer_and_self_reflection_are_separate_model_lanes():
    client = _TwoLaneClient()
    router = AIRuntimeModelRouter(
        SimpleNamespace(
            social_parser_client=client,
            social_critic_client=None,
            social_fallback_client=None,
        )
    )
    observation = router.observe_completed_turn(
        turn_id="turn-1",
        turn_seq=1,
        user_text="Giọng em nghe dễ chịu ghê.",
        assistant_text="Nghe vậy làm tôi hơi ngượng, nhưng tôi thích.",
        state_summary=RuntimeMindState().to_dict(),
    )
    assert client.names == ["eris_cognitive_observation", "eris_personality_reflection"]
    assert observation.self_interpretation.frame == "safe_reciprocity"
    assert observation.trait_signals[0].trait == "warmth_expression"
    assert "+self_reflection" in observation.source


def test_active_voice_contract_has_no_fixed_personality_or_toxic_permission_gate():
    prompt = " ".join((STYLE_FALLBACK_PROMPT, RUNTIME_RULES_PROMPT, CHAT_RULES_PROMPT)).lower()
    assert "infj" not in prompt
    assert "5w4" not in prompt
    assert "594" not in prompt
    assert "toxic_requires_permission" not in prompt
    assert "permission ladder" not in prompt
    assert "development_direction=open" in prompt
    assert "live_profile_authority=true" in prompt
