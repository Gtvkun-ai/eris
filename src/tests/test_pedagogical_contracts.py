from dataclasses import FrozenInstanceError

import pytest

from runtime.pedagogical_contracts import (
    ComprehensionState,
    TeachingConcept,
    TeachingDirective,
    TeachingEpisode,
    normalize_episode,
    validate_directive,
)


def test_episode_round_trips_with_bounded_fields():
    episode = TeachingEpisode.new(
        episode_id="teach:1",
        topic_key="core7_vs_core8",
        global_goal="distinguish motivation from behavior",
        concepts=(TeachingConcept("motivation", "Separate motive from behavior"),),
        now=100.0,
        expires_at=700.0,
    )
    restored = TeachingEpisode.from_mapping(episode.to_dict())
    assert restored == episode
    assert len(restored.global_goal) <= 420
    assert restored.status == "planning"
    assert restored.plan_revision == 1
    assert restored.pending_chunk is None


def test_invalid_status_and_out_of_range_values_fail_closed():
    assert normalize_episode({"status": "invented", "comprehension": {}}) is None
    state = ComprehensionState.from_mapping({"estimated_mastery": 4, "confidence": -2})
    assert state.estimated_mastery == 1.0
    assert state.confidence == 0.0


def test_directive_cannot_exceed_hard_chunk_limits():
    directive = TeachingDirective(
        episode_id="teach:1", plan_revision=1, chunk_id="chunk:1",
        global_goal="goal", current_objective="obj", claim="claim",
        contrast="contrast", example_policy="allowed", max_ideas=99,
        max_sentences=99, allow_question=True, stop_after_chunk=True,
        allow_autonomous_resume=True,
    )
    valid, reason = validate_directive(directive)
    assert not valid
    assert reason == "directive_budget_exceeded"


def test_contracts_are_frozen_and_serialization_bounds_text():
    episode = TeachingEpisode.new(
        episode_id="e" * 1000,
        topic_key="topic",
        global_goal="g" * 1000,
        concepts=(TeachingConcept("c", "d" * 1000),),
        now=1.0,
        expires_at=2.0,
    )
    payload = episode.to_dict()
    assert len(payload["episode_id"]) <= 120
    assert len(payload["global_goal"]) <= 420
    assert len(payload["concepts"][0]["description"]) <= 420
    with pytest.raises(FrozenInstanceError):
        episode.status = "ready"
