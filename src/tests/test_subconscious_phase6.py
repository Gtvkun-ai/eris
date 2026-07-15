# -*- coding: utf-8 -*-
"""Regression cho Phase 6 Core Belief Mutation.

Phase 6 không được test bằng kiểu "class import được" rồi tự hào như vừa hạ boss.
Nó phải chứng minh ba thứ: proposal không tự commit, commit rule đủ chặt, và rollback
record tồn tại thật.
"""

from __future__ import annotations

from cortex.subconscious import (
    SubconsciousBlackboard,
    ThoughtFragment,
    WorkerContext,
    build_phase1234567_workers,
)
from cortex.subconscious.workers import (
    BeliefMutationEngine,
    BeliefMutationProposal,
    HabitDeltaProposal,
    MutationCommitter,
    PreferenceDeltaProposal,
)
from runtime.subconscious_loop import SubconsciousLoop


def _kinds(fragments):
    return {fragment.kind for fragment in fragments}


def _seed_mutation_blackboard(now: float = 1_000_000.0) -> SubconsciousBlackboard:
    blackboard = SubconsciousBlackboard(max_fragments=96)
    # Trải fragment qua nhiều ngày để engine có thể suy ra observation window nếu
    # integration không truyền explicit window. Đây là "nhiều ngày" giả trong test,
    # còn runtime thật phải dựa memory/outcome history.
    day = 86_400.0
    for idx in range(6):
        blackboard.submit(
            ThoughtFragment.create(
                source_agent="rehearsal_agent",
                kind="suppressed_impulse",
                content=f"Impulse bị giữ lại vì proactive speech có timing rủi ro #{idx}",
                evidence_ids=(f"ev.sup.{idx}",),
                confidence=0.78,
                urgency=0.82,
                affect_charge=0.74,
                privacy_level="private",
                surface_allowed=False,
                ttl_seconds=day * 20,
                tags=("rehearsal", "suppressed_impulse"),
                now=now + idx * day,
            )
        )
    for idx in range(3):
        blackboard.submit(
            ThoughtFragment.create(
                source_agent="curiosity_gap_agent",
                kind="curiosity_seed",
                content=f"Curiosity seed nên chờ thêm evidence trước khi hỏi #{idx}",
                evidence_ids=(f"ev.curiosity.{idx}",),
                confidence=0.70,
                urgency=0.62,
                affect_charge=0.36,
                privacy_level="private",
                surface_allowed=False,
                ttl_seconds=day * 20,
                tags=("curiosity", "wait_for_evidence"),
                now=now + idx * day,
            )
        )
    blackboard.submit(
        ThoughtFragment.create(
            source_agent="self_regulator",
            kind="over_attention_warning",
            content="Over attention warning: presence ping dễ thành chen ngang.",
            evidence_ids=("ev.over_attention",),
            confidence=0.76,
            urgency=0.72,
            affect_charge=0.48,
            privacy_level="private",
            surface_allowed=False,
            ttl_seconds=day * 20,
            tags=("restraint", "over_attention"),
            now=now,
        )
    )
    return blackboard


def test_phase6_proposals_are_pending_by_default_and_private():
    blackboard = _seed_mutation_blackboard()
    worker = BeliefMutationEngine(enable_commit=False)
    context = WorkerContext(
        blackboard_snapshot=blackboard.snapshot(now=1_000_000.0 + 10 * 86_400.0),
        frame={"observation_window_days": 10, "user_text": "phase 6 mutation nhưng đừng sửa thẳng agent_mind"},
        relation={"repair_need": 0.82, "rupture": 0.55, "social_load": 0.64, "trust": 0.58},
        audit_report={"has_blocking_issue": False, "contradiction_severity": 0.0},
        now=1_000_000.0 + 10 * 86_400.0,
    )

    fragments = tuple(worker.run(context))
    kinds = _kinds(fragments)

    assert "belief_mutation_proposal" in kinds
    assert "preference_delta_proposal" in kinds
    assert "habit_delta_proposal" in kinds
    assert "mutation_commit_record" not in kinds
    assert all(fragment.privacy_level == "private" for fragment in fragments)
    assert all(not fragment.surface_allowed for fragment in fragments)
    assert all("pending" in fragment.tags for fragment in fragments)
    assert len(worker.last_proposals) >= 3


def test_mutation_committer_rejects_short_window_even_with_good_confidence():
    proposal = BeliefMutationProposal(
        target="belief.speech_requires_grounded_timing",
        delta=0.20,  # phải bị clamp còn 0.08
        reason="test proposal đủ evidence nhưng thiếu observation window",
        evidence_ids=tuple(f"ev.{idx}" for idx in range(5)),
        confidence=0.90,
        observation_window_days=2,
        reversibility=0.90,
        severity="low",
    )
    committer = MutationCommitter()
    decision = committer.evaluate(proposal, contradiction_severity=0.0, now=1234.0)

    assert proposal.delta == 0.08
    assert decision.status == "rejected"
    assert "window<7d" in decision.reason
    assert committer.commit_records == []


def test_mutation_committer_commits_with_rollback_record_when_rules_pass():
    proposal = PreferenceDeltaProposal(
        target="preference.defer_intrusive_curiosity",
        delta=0.06,
        reason="nhiều evidence nhiều ngày cho thấy nên hỏi muộn hơn",
        evidence_ids=tuple(f"ev.{idx}" for idx in range(6)),
        confidence=0.84,
        observation_window_days=9,
        reversibility=0.88,
        severity="low",
    )
    store = {"belief": {}, "preference": {"preference.defer_intrusive_curiosity": 0.40}, "habit": {}}
    committer = MutationCommitter(store=store)
    decision = committer.evaluate(proposal, contradiction_severity=0.0, now=1234.0)

    assert decision.status == "committed"
    assert decision.record is not None
    assert store["preference"]["preference.defer_intrusive_curiosity"] == 0.46
    assert decision.record.rollback_token in committer.rollback_records
    assert committer.rollback(decision.record.rollback_token) is True
    assert store["preference"]["preference.defer_intrusive_curiosity"] == 0.40


def test_belief_mutation_engine_can_commit_when_explicitly_enabled_and_rules_pass():
    blackboard = _seed_mutation_blackboard()
    store = {"belief": {"belief.speech_requires_grounded_timing": 0.50}, "preference": {}, "habit": {}}
    committer = MutationCommitter(store=store)
    worker = BeliefMutationEngine(enable_commit=True, committer=committer)
    context = WorkerContext(
        blackboard_snapshot=blackboard.snapshot(now=1_000_000.0 + 10 * 86_400.0),
        frame={"observation_window_days": 10, "contradiction_severity": 0.0},
        relation={"repair_need": 0.86, "rupture": 0.62, "social_load": 0.68, "trust": 0.55},
        audit_report={"has_blocking_issue": False, "contradiction_severity": 0.0},
        now=1_000_000.0 + 10 * 86_400.0,
    )

    fragments = tuple(worker.run(context))

    assert "mutation_commit_record" in _kinds(fragments)
    assert any(decision.status == "committed" for decision in worker.last_decisions)
    assert committer.commit_records
    assert all(abs(record.delta) <= 0.08 for record in committer.commit_records)
    assert store["belief"]["belief.speech_requires_grounded_timing"] > 0.50


def test_phase1234567_loop_runs_mutation_without_auto_commit_by_default():
    loop = SubconsciousLoop(workers=build_phase1234567_workers())
    result = loop.tick(
        frame={
            "idle_seconds": 720,
            "user_text": "làm phase 6 đi",
            "active_goal": "thêm belief mutation proposal trước commit",
            "unresolved_loop": "presence không được thành timer và shadow cần repair path",
            "observation_window_days": 10,
            "spatial": {"sensor_visibility": "context_shift_without_refresh", "obstruction_risk": 0.42},
        },
        memory_packet={
            "episodic": ["Phase 2 sinh suppressed_impulse", "Phase 5 audit bắt loop"],
            "semantic": ["Core belief mutation phải có rollback và evidence"],
            "repair": ["repair evidence A", "repair evidence B", "repair evidence C"],
        },
        internal_state={"curiosity": 0.72, "boredom": 0.58, "irritation": 0.46, "restraint": 0.62},
        relation={"repair_need": 0.78, "rupture": 0.52, "dignity_defense": 0.55, "social_load": 0.64, "trust": 0.58},
        now=1234.0,
    )
    snapshot = loop.blackboard.snapshot(now=1235.0)
    kinds = _kinds(snapshot.fragments)

    assert result.submitted_count >= 9
    assert "belief_mutation_proposal" in kinds or "preference_delta_proposal" in kinds or "habit_delta_proposal" in kinds
    assert "mutation_commit_record" not in kinds
    assert result.audit_report is not None
    assert result.thought_object is not None
