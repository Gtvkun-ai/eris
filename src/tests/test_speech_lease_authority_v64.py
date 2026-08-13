"""Regression nhỏ cho V64 Speech Lease Authority.

Các test này cố tình không import runtime .pyc để chạy được độc lập trên máy dev.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from speech_lease_authority import LeaseDecision, SpeechLeaseAuthority


@dataclass
class Observation:
    context: dict = field(default_factory=dict)


@dataclass
class Candidate:
    action_kind: str
    arguments: dict = field(default_factory=dict)


@dataclass
class Frame:
    frame_id: str
    coalitions: tuple[Candidate, ...]
    observation: Observation = field(default_factory=Observation)


def test_quiet_is_not_boundary_and_ready_urge_gets_speech_lease():
    frame = Frame(
        "f1",
        (
            Candidate("silence", {}),
            Candidate(
                "speak",
                {
                    "expression_urge_id": "urge:1",
                    "expression_readiness": 0.78,
                    "expression_pressure": 0.90,
                    "expression_freshness": 1.0,
                    "expression_satisfaction": 0.0,
                    "initiative_policy_cost": 0.20,
                    "initiative_policy_max_cost": 1.0,
                    "semantic_target": "Một ý nghĩ mới đáng chia sẻ.",
                },
            ),
        ),
        Observation({"no_user_text": True, "low_familiarity": True}),
    )
    result = SpeechLeaseAuthority().evaluate(frame)
    assert result.decision is LeaseDecision.SPEAK


def test_explicit_quiet_is_hard_boundary():
    frame = Frame(
        "f2",
        (Candidate("silence"), Candidate("speak", {"expression_readiness": 1.0})),
        Observation({"explicit_quiet_request": True}),
    )
    result = SpeechLeaseAuthority().evaluate(frame)
    assert result.decision is LeaseDecision.WAIT
    assert "hard_boundary" in result.reason


def test_pacing_cost_can_wait_without_calling_it_interruption():
    frame = Frame(
        "f3",
        (
            Candidate("silence"),
            Candidate(
                "speak",
                {
                    "expression_readiness": 0.30,
                    "expression_pressure": 0.35,
                    "expression_freshness": 0.40,
                    "initiative_policy_cost": 0.95,
                    "initiative_policy_max_cost": 1.0,
                },
            ),
        ),
    )
    result = SpeechLeaseAuthority().evaluate(frame)
    assert result.decision is LeaseDecision.WAIT
    assert result.reason.startswith("pacing_wait:")


def test_force_speak_claims_family_but_not_through_real_boundary():
    authority = SpeechLeaseAuthority()
    open_frame = Frame("f4", (Candidate("silence"), Candidate("speak", {})))
    blocked_frame = Frame(
        "f5",
        (Candidate("silence"), Candidate("speak", {})),
        Observation({"user_speaking": True}),
    )
    assert authority.evaluate(open_frame, force=True).decision is LeaseDecision.SPEAK
    assert authority.evaluate(blocked_frame, force=True).decision is LeaseDecision.WAIT


def test_legacy_frame_is_unclaimed_instead_of_guessed():
    frame = Frame("f6", (Candidate("silence"), Candidate("speak", {})))
    result = SpeechLeaseAuthority().evaluate(frame)
    assert result.decision is LeaseDecision.UNCLAIMED
