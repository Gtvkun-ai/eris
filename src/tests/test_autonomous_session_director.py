# -*- coding: utf-8 -*-
"""Test Phase 2: cadence phiên, commit hook và telemetry autonomous."""

from __future__ import annotations

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_orchestrator import AutonomousPlan
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_session_director import (
    AutonomousSessionConfig,
    AutonomousSessionDirector,
)
from runtime.autonomous_speak_gate import SpeakPermit
from runtime.content_engine import ContentEngine
from runtime.director_context import DirectorContext, MachineState, SceneMode
from runtime.observability import ErisObservability


def _opportunity(kind: str, *, now_ms: int, strength: float = 0.72, novelty: float = 0.70, urgency: float = 0.30):
    return AutonomousOpportunity(
        opportunity_id=f"opp_{kind}",
        kind=kind,
        scene_mode="private_idle",
        strength=strength,
        urgency=urgency,
        novelty=novelty,
        evidence_refs=("test",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 30_000,
        suggested_intent="micro_presence",
        reason="test",
    )


def test_session_director_penalizes_repeated_kind_and_picks_fresher_opportunity():
    now = 900_000
    director = AutonomousSessionDirector(
        AutonomousSessionConfig(
            opening_phase_ms=0,
            focus_phase_after_ms=60_000,
            fatigue_soft_lines_per_hour=7,
            fatigue_hard_lines_per_hour=12,
            repeated_kind_penalty=0.22,
            minimum_opportunity_score=0.20,
            history_size=8,
        ),
        started_at_ms=0,
    )
    for index in range(3):
        director.record_spoken(kind="dead_air", at_ms=now - 30_000 + index * 1_000)

    scene = SceneRuntimeState(name="private_idle", stable_for_ms=200_000)
    directive = director.direct(
        scene=scene,
        opportunities=(
            _opportunity("dead_air", now_ms=now, strength=0.78, novelty=0.62),
            _opportunity("task_progress", now_ms=now, strength=0.70, novelty=0.76),
        ),
        now_ms=now,
    )

    assert directive.selected_kind == "task_progress"
    assert directive.recent_kinds[-1] == "dead_air"
    assert "repeat_penalty" not in directive.reason or directive.selected_kind != "dead_air"


def test_session_director_turns_weak_dead_air_body_only_when_audience_is_fatigued():
    now = 2_000_000
    director = AutonomousSessionDirector(
        AutonomousSessionConfig(opening_phase_ms=0, fatigue_soft_lines_per_hour=3, fatigue_hard_lines_per_hour=5),
        started_at_ms=0,
    )
    for index in range(6):
        director.record_spoken(kind="dead_air", at_ms=now - 20_000 + index * 1_000)

    opportunity = _opportunity("dead_air", now_ms=now, strength=0.70)
    directive = director.direct(
        scene=SceneRuntimeState(name="private_idle", stable_for_ms=500_000),
        opportunities=(opportunity,),
        now_ms=now,
    )
    permit = director.apply_to_permit(
        SpeakPermit(True, "short_reply", 10, 1_800, "dead_air_micro_line", 40_000, 0.72),
        directive,
        opportunity=opportunity,
    )

    assert directive.audience_fatigue >= 0.95
    assert permit.allowed is False
    assert permit.mode == "body_only"
    assert permit.reason == "session_director_body_only_bias"


def _director_context() -> DirectorContext:
    return DirectorContext(
        session_id="session-test",
        trace_id="trace-test",
        audience_mode="private",
        relation_band="warm",
        scene_mode=SceneMode("coding_partner", 0.9),
        machine_state=MachineState(active_app="VS Code", focus_kind="code"),
    )


def test_autonomous_content_hook_only_enters_cooldown_after_public_commit():
    engine = ContentEngine(persist=False)
    hook = engine.select_hook(
        _director_context(),
        payload={"intent": "technical_help", "user_text": ""},
        channel="autonomous",
        commit_on_select=False,
    )

    before = engine.hook_usage_snapshot(hook.id)
    assert before["session_uses"] == 0
    assert before["last_used"] == 0.0

    assert engine.commit_hook_use(hook) is True
    after = engine.hook_usage_snapshot(hook.id)
    assert after["session_uses"] == 1
    assert after["last_used"] > 0.0


def test_observability_records_autonomous_plan_without_raw_text(tmp_path):
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "events.jsonl")
    store.write_jsonl = False
    opportunity = _opportunity("task_progress", now_ms=100_000)
    director = AutonomousSessionDirector(
        AutonomousSessionConfig(opening_phase_ms=0),
        started_at_ms=0,
    )
    scene = SceneRuntimeState(name="coding_partner", stable_for_ms=30_000)
    directive = director.direct(scene=scene, opportunities=(opportunity,), now_ms=100_000)
    plan = AutonomousPlan(
        scene=scene,
        opportunities=(opportunity,),
        selected_opportunity=opportunity,
        permit=SpeakPermit(True, "short_reply", 12, 2_000, "test", 20_000, 0.8),
        evaluated_at_ms=100_000,
        session_directive=directive,
    )

    store.record_autonomous_plan(plan)
    store.record_autonomous_commit(
        plan=plan,
        intent="react",
        hook_id="bug_autopsy",
        session_snapshot={"lines_last_hour": 1, "audience_fatigue": 0.1, "recent_kinds": ["task_progress"]},
    )
    names = [event["name"] for event in store.recent_events(limit=100)]

    assert "autonomous_plan" in names
    assert "autonomous_public_commit" in names
    assert all("Một bug" not in str(event) for event in store.recent_events(limit=100))


def test_autonomous_opportunity_intent_overrides_stale_inner_whim_in_performance_context():
    from runtime.performance_contract import PerformanceContextBuilder

    builder = PerformanceContextBuilder(content_engine=ContentEngine(persist=False))
    context = builder.build(
        _director_context(),
        payload={
            "intent": "inner_whim",
            "autonomous_plan": {
                "permit": {"allowed": True, "max_words": 14, "max_duration_ms": 2_400},
                "selected_opportunity": {"kind": "new_error", "suggested_intent": "technical_help"},
                "session_directive": {"phase": "deep_focus", "cadence": "restrained"},
            },
        },
        channel="autonomous",
    )

    assert context.performance_intent == "technical_help"
    assert any(reason == "session=deep_focus/restrained" for reason in context.reasons)
