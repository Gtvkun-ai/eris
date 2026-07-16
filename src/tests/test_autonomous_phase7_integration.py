# -*- coding: utf-8 -*-
"""Integration tests cho Phase 7 Autonomous VTuber.

Các test tập trung vào bốn lỗi thực chiến: plan bị observer ghi đè, opportunity
chết trong post-chat grace, nhiều gate cùng tranh quyền, và prompt dùng nhầm plan
cũ. Không gọi LLM/TTS mạng. Con người đã tạo đủ biến số ngoài mạng rồi.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.autonomous_cycle_context import AutonomousCycleContext
from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_orchestrator import AutonomousPerformerOrchestrator, AutonomousPlan
from runtime.autonomous_policy_resolver import AutonomousPolicyResolver
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_speak_gate import SpeakPermit
from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
from runtime.coordinator import RuntimeCoordinator


def _opportunity(*, now_ms: int = 100_000, kind: str = "scene_transition") -> AutonomousOpportunity:
    return AutonomousOpportunity(
        opportunity_id=f"opp_{kind}",
        kind=kind,
        scene_mode="private_active",
        strength=0.82,
        urgency=0.35,
        novelty=0.74,
        evidence_refs=("scene_transition",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 15_000,
        suggested_intent="react",
        reason="coding_partner->private_active",
    )


def _plan(cycle_id: str, *, text_reason: str = "scene_transition_short_act") -> AutonomousPlan:
    opportunity = _opportunity()
    return AutonomousPlan(
        scene=SceneRuntimeState(name="private_active"),
        opportunities=(opportunity,),
        selected_opportunity=opportunity,
        permit=SpeakPermit(True, "short_reply", 10, 1_800, text_reason, 24_000, 0.82, final_authority=True),
        evaluated_at_ms=100_000,
        cycle_id=cycle_id,
    )


def test_cycle_context_freezes_plan_only_once() -> None:
    cycle = AutonomousCycleContext.create(now_ms=100_000)
    first = _plan(cycle.cycle_id, text_reason="first")
    second = _plan(cycle.cycle_id, text_reason="second_should_not_replace")

    assert cycle.freeze(first, now_ms=100_010) is first
    cycle.note_observer_refresh(now_ms=100_020)
    assert cycle.freeze(second, now_ms=100_030) is first
    assert cycle.plan.permit.reason == "first"
    assert cycle.observer_refresh_count == 1


def test_post_chat_opportunity_is_pending_then_eligible() -> None:
    orchestrator = AutonomousPerformerOrchestrator()
    scene = SceneRuntimeState(name="private_active")
    opportunity = _opportunity(now_ms=100_000)

    pending = orchestrator._merge_pending_opportunities(
        (opportunity,),
        scene=scene,
        now_ms=100_000,
        runtime_policy={"presence_blocked_until_ms": 145_000},
    )
    assert len(pending) == 1
    assert pending[0].status == "pending"
    assert pending[0].eligible_after_ms == 145_000
    assert pending[0].expires_at_ms == 160_000

    eligible = orchestrator._merge_pending_opportunities(
        (),
        scene=scene,
        now_ms=145_001,
        runtime_policy={"presence_blocked_until_ms": 145_000},
    )
    assert len(eligible) == 1
    assert eligible[0].status == "eligible"
    assert eligible[0].expires_at_ms > 145_001


def test_policy_resolver_owns_post_chat_block_and_final_authority() -> None:
    resolver = AutonomousPolicyResolver()
    base = SpeakPermit(True, "short_reply", 14, 2_400, "scene_transition_short_act", 24_000, 0.8)

    blocked = resolver.resolve(
        base_permit=base,
        opportunity=_opportunity(),
        runtime_policy={"presence_blocked_until_ms": 145_000},
        now_ms=120_000,
    )
    assert blocked.permit.allowed is False
    assert blocked.permit.reason == "post_chat_grace_pending"
    assert blocked.permit.defer_until_ms == 145_000
    assert blocked.permit.final_authority is True
    assert [step.policy for step in blocked.steps][-1] == "final_authority"

    released = resolver.resolve(
        base_permit=base,
        opportunity=_opportunity(),
        runtime_policy={"presence_blocked_until_ms": 145_000},
        now_ms=145_001,
    )
    assert released.permit.allowed is True
    assert released.permit.final_authority is True


def test_prompt_uses_active_frozen_cycle_not_stale_global_plan() -> None:
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    active_cycle = AutonomousCycleContext.create(now_ms=100_000)
    active_plan = _plan(active_cycle.cycle_id, text_reason="active")
    active_cycle.freeze(active_plan)
    coordinator.active_autonomous_cycle = active_cycle
    coordinator.last_autonomous_plan = _plan("stale_cycle", text_reason="stale")

    block = coordinator._autonomous_stage_prompt_block()
    payload = json.loads(block.split("\n", 1)[1])

    assert payload["contract"] == AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
    assert payload["cycle_id"] == active_cycle.cycle_id
    assert payload["permit"]["mode"] == "short_reply"
