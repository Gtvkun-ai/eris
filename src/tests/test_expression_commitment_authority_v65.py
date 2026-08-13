"""Regression thuần cho V65 Expression Commitment.

Không import runtime .pyc để chạy được trên máy dev hiện tại. Các test tập trung
vào invariant: expression self-owned, pacing chỉ defer, boundary phải explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import expression_commitment_authority as eca


@dataclass
class Observation:
    context: dict = field(default_factory=dict)


@dataclass
class Candidate:
    action_kind: str
    arguments: dict = field(default_factory=dict)


@dataclass
class Frame:
    coalitions: tuple[Candidate, ...]
    observation: Observation = field(default_factory=Observation)
    mode: str = "autonomous"


@dataclass
class Selection:
    winner_index: int
    scores: tuple[float, ...]
    requires_deliberation: bool = True
    parallel_review_recommended: bool = True
    reason: str = "legacy"


@dataclass
class FakeDecision:
    action: str
    reason: str
    intention_id: str
    motive_kind: str
    pressure: float
    commitment: float
    contentful: bool


def reset_state() -> None:
    eca._ACTIVE_COMMITMENT = None
    eca._SELF_HOLD_UNTIL.clear()
    eca._FORCE_PENDING_UNTIL = 0.0
    eca._RHYTHM = eca.ExpressionRhythm()


def test_quiet_low_familiarity_is_not_boundary():
    reset_state()
    frame = Frame(
        (
            Candidate("silence"),
            Candidate("speak", {"semantic_target": "Em vừa nghĩ ra một chuyện."}),
        ),
        Observation({"no_user_text": True, "low_familiarity": True}),
    )
    assert eca._hard_boundary(frame) == (False, "")
    assert eca._candidate_has_expression_object(frame.coalitions[1]) is True


def test_explicit_quiet_and_active_user_turn_are_boundaries():
    reset_state()
    quiet = Frame((Candidate("speak", {"semantic_target": "x"}),), Observation({"explicit_quiet_request": True}))
    busy = Frame((Candidate("speak", {"semantic_target": "x"}),), Observation({"active_user_turn": True}))
    assert eca._hard_boundary(quiet)[0] is True
    assert eca._hard_boundary(busy)[0] is True


def test_no_readiness_threshold_for_expression_object():
    reset_state()
    candidate = Candidate(
        "speak",
        {
            "semantic_target": "Một ý nhỏ nhưng là ý của Eris.",
            "expression_pressure": 0.05,
            "expression_readiness": 0.02,
        },
    )
    assert eca._candidate_has_expression_object(candidate) is True
    assert eca._candidate_expression_drive(candidate) < 0.1
    commitment = eca._ensure_commitment_from_candidate(candidate)
    assert commitment.active is True
    assert commitment.semantic_target.startswith("Một ý nhỏ")


def test_expression_rhythm_is_self_density_not_user_response():
    now = [100.0]
    rhythm = eca.ExpressionRhythm(
        capacity=2.0,
        refill_seconds_per_token=20.0,
        min_gap_seconds=5.0,
        clock=lambda: now[0],
    )
    assert rhythm.decide().allow is True
    rhythm.note_realized()
    now[0] += 1.0
    decision = rhythm.decide()
    assert decision.allow is False
    assert decision.reason == "self_gap"
    now[0] += 5.0
    assert rhythm.decide().allow is True
    rhythm.note_realized()
    now[0] += 6.0
    decision = rhythm.decide()
    assert decision.allow is False
    assert decision.reason == "self_density"
    now[0] += 20.0
    assert rhythm.decide().allow is True


def test_legacy_social_wait_tokens_are_identified_but_self_restraint_is_kept():
    assert eca._is_legacy_user_centric_reason("startup_social_cooldown") is True
    assert eca._is_legacy_user_centric_reason("initiative_not_worth_interrupting_yet") is True
    assert eca._is_hard_wait_reason("abandonment_requires_restraint") is True
    assert eca._is_hard_wait_reason("stale_low_value_intention") is True


def test_best_speech_uses_rank_not_permission_threshold():
    reset_state()
    frame = Frame(
        (
            Candidate("silence"),
            Candidate("speak", {"semantic_target": "A", "expression_pressure": 0.10}),
            Candidate("speak", {"semantic_target": "B", "expression_pressure": 0.90}),
        )
    )
    selection = Selection(0, (0.95, 0.50, 0.60))
    idx = eca._best_speech_index(frame, selection)
    assert idx == 2


def test_duplicate_failure_creates_self_hold_not_user_rejection():
    reset_state()
    candidate = Candidate("speak", {"material_id": "urge:abc", "semantic_target": "A"})
    commitment = eca._ensure_commitment_from_candidate(candidate)
    eca._hold_commitment(commitment)
    assert eca._held(candidate) is True


def test_chat_frame_is_not_claimed_by_autonomous_authority():
    frame = Frame((Candidate("speak", {"semantic_target": "x"}),), mode="chat")
    assert eca._is_autonomous_frame(frame) is False


if __name__ == "__main__":
    tests = [
        test_quiet_low_familiarity_is_not_boundary,
        test_explicit_quiet_and_active_user_turn_are_boundaries,
        test_no_readiness_threshold_for_expression_object,
        test_expression_rhythm_is_self_density_not_user_response,
        test_legacy_social_wait_tokens_are_identified_but_self_restraint_is_kept,
        test_best_speech_uses_rank_not_permission_threshold,
        test_duplicate_failure_creates_self_hold_not_user_rejection,
        test_chat_frame_is_not_claimed_by_autonomous_authority,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)}/{len(tests)} passed")
