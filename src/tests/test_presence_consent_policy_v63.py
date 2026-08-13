from dataclasses import dataclass

import presence_consent_policy as policy


@dataclass(frozen=True)
class Candidate:
    action_kind: str
    arguments: dict


@dataclass(frozen=True)
class Frame:
    coalitions: tuple
    observation: object = None


@dataclass(frozen=True)
class Choice:
    motive_validity: float
    novelty: float
    continuity_fit: float
    epistemic_support: float
    reversibility: float


@dataclass(frozen=True)
class Appraisal:
    choices: tuple
    boundary_pressure: float
    interruption_cost: float
    confidence: float
    reason: str


@dataclass(frozen=True)
class Selection:
    winner_index: int
    scores: tuple
    probabilities: tuple
    margin: float
    entropy: float
    requires_deliberation: bool
    parallel_review_recommended: bool
    reason: str


def _fixture():
    frame = Frame((Candidate("speak", {"candidate_kind": "reaction"}), Candidate("silence", {})))
    appraisal = Appraisal(
        (
            Choice(0.25, 0.70, 0.15, 0.10, 0.30),
            Choice(0.70, 0.05, 0.85, 0.05, 0.95),
        ),
        0.0,
        0.64,
        0.76,
        "no user text, low familiarity, social cooldown",
    )
    baseline = Selection(0, (0.80, 0.58), (0.93, 0.07), 0.22, 0.30, False, True, "fast")
    merged = Selection(1, (0.47, 0.62), (0.53, 0.47), 0.05, 0.80, False, False, "semantic")
    return frame, appraisal, baseline, merged


def test_quiet_is_not_boundary_and_internal_speech_is_preserved():
    frame, appraisal, baseline, merged = _fixture()
    normalized = policy._normalize_appraisal(frame, appraisal)
    assert normalized.interruption_cost == 0.0
    assert normalized.choices[0].motive_validity >= 0.62
    assert normalized.choices[0].continuity_fit >= 0.58
    assert normalized.choices[0].epistemic_support >= 0.55
    final = policy._preserve_valid_speech(frame, baseline, merged, normalized)
    assert final.winner_index == 0
    assert final.reason == "presence_consent_preserve_fast_speech"


def test_real_boundary_still_wins():
    frame, appraisal, baseline, merged = _fixture()
    boundary = Appraisal(appraisal.choices, 0.90, 0.64, 0.90, "user asked for quiet")
    normalized = policy._normalize_appraisal(frame, boundary)
    assert normalized.interruption_cost == 0.64
    final = policy._preserve_valid_speech(frame, baseline, merged, normalized)
    assert final.winner_index == 1


def test_grounding_requirement_keeps_epistemic_brake():
    _, appraisal, _, _ = _fixture()
    frame = Frame((Candidate("speak", {"requires_grounding": True}), Candidate("silence", {})))
    normalized = policy._normalize_appraisal(frame, appraisal)
    assert normalized.choices[0].epistemic_support == 0.10


def test_force_speak_is_real_one_shot_authority():
    frame, appraisal, _, merged = _fixture()
    normalized = policy._normalize_appraisal(frame, appraisal)
    baseline_silence = Selection(1, (0.77, 0.84), (0.45, 0.55), 0.07, 0.80, False, False, "fast")
    policy._mark_force_speak()
    final = policy._preserve_valid_speech(frame, baseline_silence, merged, normalized)
    assert final.winner_index == 0
    assert final.reason == "force_speak_authority"
    assert not policy._force_speak_active()
