# -*- coding: utf-8 -*-
"""Test Phase 6: đóng kiến trúc autonomous VTuber.

Không chờ thật 60 phút. Timestamp được đẩy nhân tạo để kiểm tra đúng các bệnh
chỉ lộ trong phiên dài, vì bắt pytest ngồi ngắm đồng hồ một tiếng là một cách
khá sáng tạo để biến CI thành đồ nội thất.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.autonomous_audience_feedback import (
    AudienceFeedbackDirective,
    AutonomousAudienceFeedbackLoop,
)
from runtime.autonomous_debug_snapshot import AutonomousDebugSnapshotStore
from runtime.autonomous_long_run_audit import (
    AutonomousAuditConfig,
    AutonomousLongRunAudit,
)
from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_orchestrator import AutonomousPlan
from runtime.autonomous_policy_resolver import AutonomousPolicyResolver
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_session_director import (
    AutonomousSessionDirector,
    SessionDirective,
)
from runtime.autonomous_speak_gate import SpeakPermit
from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
from runtime.coordinator import RuntimeCoordinator


def _opportunity(
    kind: str = "task_progress",
    *,
    opportunity_id: str = "opp_phase6",
    urgency: float = 0.4,
    strength: float = 0.8,
    now_ms: int = 100_000,
) -> AutonomousOpportunity:
    return AutonomousOpportunity(
        opportunity_id=opportunity_id,
        kind=kind,
        scene_mode="coding_partner",
        strength=strength,
        urgency=urgency,
        novelty=0.72,
        evidence_refs=("signal",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 300_000,
        suggested_intent="react",
        reason="phase6_test",
    )


def _session_directive(*, body_only_bias: float = 0.2, words: int = 12) -> SessionDirective:
    return SessionDirective(
        phase="settled",
        cadence="balanced",
        selected_opportunity_id="opp_phase6",
        selected_kind="task_progress",
        selected_score=0.8,
        audience_fatigue=0.2,
        speech_density=0.2,
        body_only_bias=body_only_bias,
        max_words_cap=words,
        cooldown_multiplier=1.4,
        opening_hold_bias_ms=0,
        preferred_intent="react",
        lines_last_hour=2,
        recent_kinds=("new_error",),
        reason="test",
    )


def _feedback(*, mode: str = "low_intrusion", intrusion: float = 0.45, words: int = 9):
    return AudienceFeedbackDirective(
        mode=mode,
        engagement_score=-0.1,
        intrusion_pressure=intrusion,
        body_only_bias=intrusion,
        cooldown_multiplier=1.8,
        max_words_cap=words,
        suppressed_kinds=(),
        recent_outcome="ignored",
        pending_act_id="",
        reason="test_feedback",
    )


class _PolicyThatIllegallyReopens:
    def apply_to_permit(self, permit, directive, *, opportunity):
        return SpeakPermit(True, "full_line", 99, 99_000, "illegal_reopen", 0, 1.0)


def _plan(
    opportunity: AutonomousOpportunity,
    *,
    allowed: bool = True,
    reason: str = "test",
    evaluated_at_ms: int = 100_000,
) -> SimpleNamespace:
    return SimpleNamespace(
        scene=SceneRuntimeState(name="coding_partner"),
        selected_opportunity=opportunity,
        permit=SpeakPermit(
            allowed,
            "short_reply" if allowed else "body_only",
            12 if allowed else 0,
            2_000 if allowed else 0,
            reason,
            20_000,
            0.8,
        ),
        evaluated_at_ms=evaluated_at_ms,
        session_directive=SimpleNamespace(phase="settled", cadence="balanced"),
        stage_preset=SimpleNamespace(preset_id="coding_partner.focused.v1"),
        audience_feedback=SimpleNamespace(mode="normal"),
        policy_decision=None,
    )


def test_policy_resolver_never_reopens_hard_gate() -> None:
    resolver = AutonomousPolicyResolver()
    base = SpeakPermit(False, "body_only", 0, 0, "user_is_typing", 0, 0.96)

    result = resolver.resolve(
        base_permit=base,
        opportunity=_opportunity("new_error", urgency=0.99),
        session_director=_PolicyThatIllegallyReopens(),
        session_directive=object(),
    )

    assert result.permit.allowed is False
    assert result.permit.reason == "user_is_typing"
    assert "session_director_attempted_to_reopen_denied_permit" in result.conflict_flags
    assert "user_is_typing" in result.blockers


def test_policy_resolver_has_one_trace_and_monotonic_budget() -> None:
    resolver = AutonomousPolicyResolver()
    base = SpeakPermit(True, "full_line", 18, 3_000, "base", 20_000, 0.8)
    feedback_loop = AutonomousAudienceFeedbackLoop()

    result = resolver.resolve(
        base_permit=base,
        opportunity=_opportunity("task_progress"),
        stage_preset=SimpleNamespace(max_words=14, max_duration_ms=2_600),
        session_director=AutonomousSessionDirector(),
        session_directive=_session_directive(words=12),
        audience_feedback_loop=feedback_loop,
        audience_directive=_feedback(words=9),
    )

    assert result.permit.allowed is True
    assert result.permit.max_words == 9
    assert result.permit.max_duration_ms <= 3_000
    assert result.permit.cooldown_after_ms >= 20_000
    assert [step.policy for step in result.steps] == [
        "speak_gate",
        "runtime_authority",
        "session_director",
        "audience_feedback",
        "final_budget_clamp",
        "final_authority",
    ]
    assert result.permit.final_authority is True
    assert result.conflict_flags == ()


def test_recovery_allows_urgent_error_but_caps_it() -> None:
    result = AutonomousPolicyResolver().resolve(
        base_permit=SpeakPermit(True, "full_line", 18, 3_000, "new_error", 20_000, 0.9),
        opportunity=_opportunity("new_error", urgency=0.95),
        stage_preset=SimpleNamespace(max_words=18, max_duration_ms=3_000),
        session_director=AutonomousSessionDirector(),
        session_directive=_session_directive(body_only_bias=0.2, words=18),
        audience_feedback_loop=AutonomousAudienceFeedbackLoop(),
        audience_directive=_feedback(mode="recovery", intrusion=0.92, words=7),
    )

    assert result.permit.allowed is True
    assert result.permit.max_words <= 7
    assert result.emergency_override is True


def test_long_run_audit_simulates_55_minutes_without_spam() -> None:
    audit = AutonomousLongRunAudit(
        AutonomousAuditConfig(max_lines_per_hour=12, max_same_kind_streak=3)
    )
    start = 1_000_000
    kinds = ("task_progress", "new_error", "return_after_idle")
    for index in range(12):
        now = start + index * 5 * 60_000
        opportunity = _opportunity(
            kinds[index % len(kinds)],
            opportunity_id=f"opp_{index}",
            now_ms=now,
        )
        plan = _plan(opportunity, evaluated_at_ms=now)
        audit.observe_plan(plan, now_ms=now)
        audit.record_commit(plan, at_ms=now + 500)

    snapshot = audit.snapshot(now_ms=start + 55 * 60_000)

    assert snapshot.status == "ok"
    assert snapshot.lines_last_hour == 12
    assert snapshot.orphaned_permits == 0
    assert snapshot.max_same_kind_streak == 1
    assert snapshot.commit_ratio == 1.0


def test_long_run_audit_detects_density_repetition_and_orphan_permit() -> None:
    audit = AutonomousLongRunAudit(
        AutonomousAuditConfig(
            pending_permit_timeout_ms=5_000,
            max_lines_per_hour=4,
            max_same_kind_streak=2,
            max_orphaned_permits=0,
        )
    )
    start = 2_000_000
    for index in range(5):
        now = start + index * 10_000
        opportunity = _opportunity("dead_air", opportunity_id=f"spam_{index}", now_ms=now)
        plan = _plan(opportunity, evaluated_at_ms=now)
        audit.observe_plan(plan, now_ms=now)
        audit.record_commit(plan, at_ms=now + 100)

    orphan = _plan(_opportunity("task_progress", opportunity_id="orphan", now_ms=start + 60_000), evaluated_at_ms=start + 60_000)
    audit.observe_plan(orphan, now_ms=start + 60_000)
    snapshot = audit.snapshot(now_ms=start + 70_000)

    assert snapshot.status == "violation"
    assert "speech_density_exceeded" in snapshot.violations
    assert "same_kind_streak_exceeded" in snapshot.violations
    assert "orphaned_permit_budget_exceeded" in snapshot.violations


def test_debug_snapshot_contains_policy_reason_but_not_public_text() -> None:
    store = AutonomousDebugSnapshotStore()
    opportunity = _opportunity("task_progress")
    plan = _plan(opportunity)
    plan.policy_decision = SimpleNamespace(blockers=(), conflict_flags=())
    store.record_plan(plan)
    store.record_commit(plan, intent="react", hook_id="bug_payoff", at_ms=101_000)

    payload = store.snapshot(now_ms=102_000)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["contract"] == AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
    assert payload["current"]["reason"] == "test"
    assert payload["recent_commits"][0]["hook_id"] == "bug_payoff"
    assert "public_text" not in serialized
    assert "user_text" not in serialized


def test_autonomous_plan_payload_is_stamped_current_version() -> None:
    opportunity = _opportunity()
    plan = AutonomousPlan(
        scene=SceneRuntimeState(name="coding_partner"),
        opportunities=(opportunity,),
        selected_opportunity=opportunity,
        permit=SpeakPermit(True, "short_reply", 10, 1_800, "test", 20_000, 0.8),
        evaluated_at_ms=100_000,
    )

    assert plan.to_payload()["architecture_version"] == AUTONOMOUS_STAGE_ARCHITECTURE_VERSION


def test_prompt_contract_surfaces_current_policy_trace() -> None:
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator.last_autonomous_plan = SimpleNamespace(
        enabled=True,
        architecture_version=AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
        scene=SceneRuntimeState(name="coding_partner"),
        selected_opportunity=_opportunity("task_progress"),
        permit=SpeakPermit(True, "short_reply", 9, 1_800, "test", 20_000, 0.8),
        session_directive=SimpleNamespace(
            phase="settled", cadence="balanced", audience_fatigue=0.1,
            body_only_bias=0.2, recent_kinds=("new_error",),
        ),
        show_arc_directive=SimpleNamespace(
            arc_id="arc_v6", arc_family="task_thread", arc_stage="payoff",
            continuity_mode="continue", line_shape="setup_payoff", callback_anchor="",
            avoid_openings=(), novelty_target=0.7, escalation_level=1,
        ),
        stage_preset=SimpleNamespace(
            preset_id="coding_partner.focused.v1", performance_lane="focus_preserving",
            body_first=True, default_intent="technical_help", delivery_style="cold_precision",
            stage_emotion="focused", stage_motion="tiny_nod", tts_style="clipped_clear",
            gesture_density="minimal", anti_spoiler=False, public_memory_allowed=True,
            poetic_drift_allowed=False, policy_tags=("focus_protection",), surface_rules=(),
        ),
        audience_feedback=SimpleNamespace(
            mode="normal", engagement_score=0.1, intrusion_pressure=0.0,
            recent_outcome="affirmed", suppressed_kinds=(),
        ),
        policy_decision=SimpleNamespace(
            version=AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
            blockers=(), conflict_flags=(), emergency_override=False,
        ),
    )

    block = coordinator._autonomous_stage_prompt_block()
    payload = json.loads(block.split("\n", 1)[1])

    assert payload["contract"] == AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
    assert payload["policy_decision"]["conflict_flags"] == []
    assert any("policy resolver" in rule.lower() for rule in payload["surface_rules"])


def test_observability_accepts_policy_and_long_run_audit(tmp_path) -> None:
    from runtime.observability import ErisObservability

    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "events.jsonl")
    store.write_jsonl = False
    opportunity = _opportunity("task_progress")
    plan = AutonomousPlan(
        scene=SceneRuntimeState(name="coding_partner"),
        opportunities=(opportunity,),
        selected_opportunity=opportunity,
        permit=SpeakPermit(True, "short_reply", 9, 1_800, "test", 20_000, 0.8),
        evaluated_at_ms=100_000,
        policy_decision=SimpleNamespace(
            blockers=(), conflict_flags=(), version=AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
        ),
    )
    audit = AutonomousLongRunAudit()
    audit.observe_plan(plan, now_ms=100_000)

    store.record_autonomous_plan(plan)
    store.record_autonomous_audit(audit.snapshot(now_ms=100_100))
    names = [event["name"] for event in store.recent_events(limit=100)]

    assert "autonomous_plan" in names
    assert "autonomous_audit" in names
