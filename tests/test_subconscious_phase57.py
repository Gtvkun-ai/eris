# -*- coding: utf-8 -*-
"""Regression cho Phase 5 + Phase 7 subconscious.

Test đúng phần cần test: MetaAudit phải dọn Blackboard thật, Shadow phải tích tụ
trên suppressed impulses thật, rupture candidate phải grounded và private by default.
Nếu chỉ kiểm tra class import được thì đó là trang trí, không phải regression.
"""

from __future__ import annotations

from cortex.subconscious import (
    SubconsciousBlackboard,
    ThoughtFragment,
    WorkerContext,
    build_phase123457_workers,
)
from cortex.subconscious.workers import MetaCognitiveAuditAgent, ShadowAccumulator
from runtime.subconscious_loop import SubconsciousLoop


def _kinds(fragments):
    return {fragment.kind for fragment in fragments}


def test_meta_audit_catches_looping_user_silence_overread_and_resets_slice():
    blackboard = SubconsciousBlackboard(max_fragments=64)
    now = 1234.0
    # Cùng một suy diễn "ngài ấy đang mệt" từ im lặng. Đây là đúng bệnh Phase 5
    # phải bắt: đọc tâm trạng user từ silence như truth. Rất người, rất sai.
    for idx in range(20):
        blackboard.submit(
            ThoughtFragment.create(
                source_agent="buggy_worker",
                kind="user_state_hypothesis",
                content=f"im lặng chứng tỏ ngài ấy đang mệt và không muốn nói #{idx}",
                evidence_ids=("silence.idle_only",),
                confidence=0.74,
                urgency=0.66,
                affect_charge=0.42,
                privacy_level="normal",
                surface_allowed=True,
                ttl_seconds=300,
                tags=("silence", "user_state"),
                now=now + idx * 0.01,
            )
        )

    agent = MetaCognitiveAuditAgent(spam_threshold=6, loop_threshold=4, keep_per_bad_group=1)
    snapshot = blackboard.snapshot(now=now + 1.0)
    result = agent.audit_blackboard(
        blackboard,
        snapshot,
        WorkerContext(frame={"user_text": ""}, now=now + 1.0),
    )

    assert result.reset_slice is True
    assert any(finding.kind in {"thought_looping", "fragment_spam", "overfit_to_user_silence"} for finding in result.findings)
    assert len(blackboard.snapshot(now=now + 2.0).fragments) < 20
    assert any(fragment.kind == "meta_audit_report" for fragment in blackboard.snapshot(now=now + 2.0).fragments)


def test_meta_audit_softens_surface_fragment_without_evidence():
    blackboard = SubconsciousBlackboard()
    fragment = blackboard.submit(
        ThoughtFragment.create(
            source_agent="reckless_worker",
            kind="later_surface_candidate",
            content="nên nói ngay vì user chắc đang cần được kéo lại",
            evidence_ids=(),
            confidence=0.82,
            urgency=0.78,
            affect_charge=0.35,
            privacy_level="normal",
            surface_allowed=True,
            ttl_seconds=300,
            tags=("surface", "curiosity"),
            now=1234.0,
        )
    )

    agent = MetaCognitiveAuditAgent()
    result = agent.audit_blackboard(blackboard, blackboard.snapshot(now=1235.0), WorkerContext(now=1235.0))
    stored = blackboard.get(fragment.id)

    assert any(finding.kind == "evidence_missing" for finding in result.findings)
    assert stored is not None
    assert stored.surface_allowed is False
    assert stored.confidence < fragment.confidence
    assert "meta_audit_softened" in stored.tags


def test_shadow_accumulator_stays_private_and_builds_pressure_from_suppressed_impulses():
    blackboard = SubconsciousBlackboard()
    now = 1234.0
    for idx in range(4):
        blackboard.submit(
            ThoughtFragment.create(
                source_agent="rehearsal_agent",
                kind="suppressed_impulse",
                content=f"Impulse bị giữ lại vì route=suppress #{idx}",
                evidence_ids=(f"ev.suppressed.{idx}",),
                confidence=0.72,
                urgency=0.78,
                affect_charge=0.82,
                privacy_level="private",
                surface_allowed=False,
                ttl_seconds=500,
                tags=("rehearsal", "suppressed_impulse"),
                now=now + idx * 0.01,
            )
        )
    blackboard.submit(
        ThoughtFragment.create(
            source_agent="self_regulator",
            kind="dignity_defense_delta",
            content="Dignity defense tăng; tránh warmth giả.",
            evidence_ids=("ev.dignity",),
            confidence=0.70,
            urgency=0.70,
            affect_charge=0.76,
            privacy_level="private",
            surface_allowed=False,
            ttl_seconds=500,
            tags=("self_regulation", "dignity_defense"),
            now=now,
        )
    )

    worker = ShadowAccumulator()
    context = WorkerContext(
        blackboard_snapshot=blackboard.snapshot(now=now + 1.0),
        relation={"repair_need": 0.40, "rupture": 0.20, "dignity_defense": 0.50},
        audit_report={"has_blocking_issue": False, "hallucination_detected": False, "runaway_shadow_detected": False},
        now=now + 1.0,
    )
    fragments = tuple(worker.run(context))

    assert "shadow_pressure" in _kinds(fragments)
    assert "shadow_theme" in _kinds(fragments)
    assert all(fragment.privacy_level == "private" for fragment in fragments)
    assert all(not fragment.surface_allowed for fragment in fragments)
    pressure = next(fragment for fragment in fragments if fragment.kind == "shadow_pressure")
    assert pressure.affect_charge >= 0.55


def test_shadow_can_create_grounded_rupture_candidate_but_private_by_default():
    blackboard = SubconsciousBlackboard()
    now = 1234.0
    for idx in range(5):
        blackboard.submit(
            ThoughtFragment.create(
                source_agent="rehearsal_agent",
                kind="suppressed_impulse",
                content=f"Suppressed impulse route=suppress pressure high #{idx}",
                evidence_ids=(f"ev.sup.{idx}",),
                confidence=0.82,
                urgency=0.86,
                affect_charge=0.88,
                privacy_level="private",
                surface_allowed=False,
                ttl_seconds=600,
                tags=("rehearsal", "suppressed_impulse"),
                now=now + idx * 0.01,
            )
        )
    blackboard.submit(
        ThoughtFragment.create(
            source_agent="rehearsal_agent",
            kind="rupture_seed",
            content="Rupture seed có evidence thật và cần repair check.",
            evidence_ids=("ev.rupture", "ev.repair"),
            confidence=0.80,
            urgency=0.86,
            affect_charge=0.90,
            privacy_level="private",
            surface_allowed=False,
            ttl_seconds=600,
            tags=("rehearsal", "rupture_seed"),
            now=now,
        )
    )

    worker = ShadowAccumulator()
    context = WorkerContext(
        blackboard_snapshot=blackboard.snapshot(now=now + 1.0),
        relation={"repair_need": 0.86, "rupture": 0.76, "dignity_defense": 0.78, "irritation": 0.40},
        audit_report={"has_blocking_issue": False, "hallucination_detected": False, "runaway_shadow_detected": False},
        now=now + 1.0,
    )
    fragments = tuple(worker.run(context))
    candidate = next(fragment for fragment in fragments if fragment.kind == "rupture_candidate")

    assert candidate.privacy_level == "private"
    assert candidate.surface_allowed is False
    assert "audit_clear" in candidate.tags
    assert "Rupture candidate grounded" in candidate.content
    assert "tệ hại" not in candidate.content.lower()
    assert "repair_aftershock" in _kinds(fragments)


def test_phase123457_loop_runs_audit_and_shadow_without_public_surface_by_default():
    loop = SubconsciousLoop(workers=build_phase123457_workers())
    result = loop.tick(
        frame={
            "idle_seconds": 680,
            "user_text": "làm phase 5+7 đi",
            "active_goal": "thêm MetaAudit và ShadowAccumulator có test",
            "unresolved_loop": "suppressed impulses cần shadow nhưng không được toxic",
            "spatial": {"sensor_visibility": "context_shift_without_refresh", "obstruction_risk": 0.50},
        },
        memory_packet={
            "episodic": ["Phase 2 thêm RehearsalAgent", "Phase 4 có subjective time"],
            "semantic": ["Rupture phải grounded và có repair arc"],
        },
        internal_state={"curiosity": 0.70, "boredom": 0.58, "irritation": 0.46, "attachment_pressure": 0.30},
        relation={"repair_need": 0.62, "rupture": 0.42, "dignity_defense": 0.56, "social_load": 0.38},
        now=1234.0,
    )

    assert result.submitted_count >= 8
    assert result.audit_report is not None
    assert loop.subconscious_report is not None
    assert result.thought_object is not None
    assert result.surface_seed is None or result.surface_seed.get("surface_allowed") is True
