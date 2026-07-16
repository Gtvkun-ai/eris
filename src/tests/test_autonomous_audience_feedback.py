from __future__ import annotations

from runtime.autonomous_audience_feedback import (
    AudienceFeedbackConfig,
    AutonomousAudienceFeedbackLoop,
)
from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_speak_gate import SpeakPermit


def _opp(kind: str = "dead_air", *, urgency: float = 0.2, strength: float = 0.72) -> AutonomousOpportunity:
    return AutonomousOpportunity(
        opportunity_id=f"opp_{kind}",
        kind=kind,
        scene_mode="private_idle",
        strength=strength,
        urgency=urgency,
        novelty=0.72,
        evidence_refs=("idle_ms",),
        created_at_ms=1_000,
        expires_at_ms=999_999,
        suggested_intent="micro_presence",
        reason="test",
    )


def _permit(words: int = 12) -> SpeakPermit:
    return SpeakPermit(
        allowed=True,
        mode="short_reply",
        max_words=words,
        max_duration_ms=2_200,
        reason="base",
        cooldown_after_ms=20_000,
        confidence=0.8,
    )


def test_affirmed_reply_increases_engagement_without_auto_permit() -> None:
    loop = AutonomousAudienceFeedbackLoop()
    loop.record_act(
        opportunity=_opp("task_progress"),
        scene_mode="coding_partner",
        text="Một bug ngã xuống. Tạm thời.",
        at_ms=10_000,
    )

    outcome = loop.observe(channel="chat", user_text="haha chuẩn", now_ms=12_000)
    directive = loop.directive(now_ms=12_001)

    assert outcome is not None
    assert outcome.kind == "affirmed"
    assert directive.engagement_score > 0.3
    assert directive.intrusion_pressure < 0.2
    assert directive.mode == "engaged"


def test_explicit_rejection_suppresses_same_opportunity_kind() -> None:
    loop = AutonomousAudienceFeedbackLoop()
    opportunity = _opp("dead_air")
    loop.record_act(
        opportunity=opportunity,
        scene_mode="private_idle",
        text="Im lâu thế.",
        at_ms=10_000,
    )

    outcome = loop.observe(channel="chat", user_text="đừng chen lúc tôi đang làm", now_ms=11_000)
    directive = loop.directive(opportunity=opportunity, now_ms=11_001)
    permit = loop.apply_to_permit(_permit(), directive, opportunity=opportunity)

    assert outcome is not None
    assert outcome.kind == "rejected"
    assert directive.mode == "recovery"
    assert "dead_air" in directive.suppressed_kinds
    assert permit.allowed is False
    assert permit.mode == "body_only"
    assert permit.reason == "audience_feedback_prefers_silence"


def test_correction_is_negative_but_not_a_psychological_claim() -> None:
    loop = AutonomousAudienceFeedbackLoop()
    opportunity = _opp("new_error", urgency=0.7)
    loop.record_act(
        opportunity=opportunity,
        scene_mode="coding_partner",
        text="Parser trước.",
        at_ms=10_000,
    )

    outcome = loop.observe(channel="chat", user_text="không phải, network trước", now_ms=11_500)
    snapshot = loop.snapshot(now_ms=11_501)

    assert outcome is not None
    assert outcome.kind == "corrected"
    assert outcome.reason == "user_corrected_autonomous_line"
    assert snapshot["directive"]["intrusion_pressure"] >= 0.6
    assert "emotion" not in outcome.to_payload()


def test_ignored_dead_air_reduces_repeated_dead_air_strength() -> None:
    loop = AutonomousAudienceFeedbackLoop(
        AudienceFeedbackConfig(reply_window_ms=2_000, ignored_window_ms=4_000)
    )
    opportunity = _opp("dead_air", strength=0.72)
    loop.record_act(
        opportunity=opportunity,
        scene_mode="private_idle",
        text="Cái ghế sắp thắng rồi.",
        at_ms=10_000,
    )

    outcome = loop.observe(
        channel="autonomous",
        scene=SceneRuntimeState(name="private_idle", user_typing=False),
        now_ms=15_500,
    )
    adjusted = loop.adjust_opportunities((opportunity,), now_ms=15_501)

    assert outcome is not None
    assert outcome.kind == "ignored"
    assert adjusted[0].strength < opportunity.strength


def test_urgent_error_can_still_surface_in_recovery_but_is_shorter() -> None:
    loop = AutonomousAudienceFeedbackLoop()
    dead_air = _opp("dead_air")
    loop.record_act(
        opportunity=dead_air,
        scene_mode="private_idle",
        text="Một câu chen.",
        at_ms=10_000,
    )
    loop.observe(channel="chat", user_text="đừng nói nữa", now_ms=11_000)

    urgent = _opp("new_error", urgency=0.95, strength=0.95)
    directive = loop.directive(opportunity=urgent, now_ms=11_001)
    permit = loop.apply_to_permit(_permit(words=18), directive, opportunity=urgent)

    assert directive.mode == "recovery"
    assert permit.allowed is True
    assert permit.max_words <= 10
    assert permit.cooldown_after_ms > 20_000
    assert "audience:recovery" in permit.reason


def test_continued_focus_is_neutral_not_rejection() -> None:
    loop = AutonomousAudienceFeedbackLoop(
        AudienceFeedbackConfig(reply_window_ms=2_000, ignored_window_ms=4_000)
    )
    opportunity = _opp("task_progress")
    loop.record_act(
        opportunity=opportunity,
        scene_mode="coding_partner",
        text="Build qua rồi.",
        at_ms=10_000,
    )

    outcome = loop.observe(
        channel="autonomous",
        scene=SceneRuntimeState(name="coding_partner", user_typing=True),
        now_ms=15_100,
    )

    assert outcome is not None
    assert outcome.kind == "continued_focus"
    assert outcome.valence > -0.2
