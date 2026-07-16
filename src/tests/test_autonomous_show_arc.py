# -*- coding: utf-8 -*-
"""Test Phase 3: show arc, callback/payoff và chống lặp khuôn mở câu."""

from __future__ import annotations

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_performance import AutonomousPerformancePlanner
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_show_arc import AutonomousShowArcDirector, ShowArcConfig


def _opportunity(kind: str, *, now_ms: int, intent: str = "react") -> AutonomousOpportunity:
    return AutonomousOpportunity(
        opportunity_id=f"opp_{kind}_{now_ms}",
        kind=kind,
        scene_mode="coding_partner",
        strength=0.84 if kind == "new_error" else 0.72,
        urgency=0.74 if kind == "new_error" else 0.30,
        novelty=0.70,
        evidence_refs=("test",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 30_000,
        suggested_intent=intent,
        reason="test",
    )


def test_problem_arc_advances_from_setup_to_escalation_then_payoff():
    director = AutonomousShowArcDirector(
        ShowArcConfig(callback_window_ms=120_000, arc_timeout_ms=300_000, resolved_grace_ms=30_000)
    )
    scene = SceneRuntimeState(name="coding_partner", stable_for_ms=120_000)

    first_opp = _opportunity("new_error", now_ms=100_000, intent="technical_help")
    first = director.direct(scene=scene, opportunity=first_opp, now_ms=100_000)
    assert first.arc_family == "problem_thread"
    assert first.arc_stage == "setup"
    assert first.line_shape == "technical_two_step"

    director.record_spoken(
        text="Parser sai tầng. Kiểm tra network trước.",
        opportunity=first_opp,
        directive=first,
        hook_id="bug_summoning",
        at_ms=101_000,
    )
    second_opp = _opportunity("new_error", now_ms=110_000, intent="technical_help")
    second = director.direct(scene=scene, opportunity=second_opp, now_ms=110_000)
    assert second.arc_id == first.arc_id
    assert second.arc_stage == "escalation"
    assert second.callback_anchor == "bug_summoning"

    director.record_spoken(
        text="Nó đổi mặt nạ thôi. Network vẫn là đầu mối.",
        opportunity=second_opp,
        directive=second,
        hook_id="bug_summoning",
        at_ms=111_000,
    )
    progress = _opportunity("task_progress", now_ms=120_000)
    payoff = director.direct(scene=scene, opportunity=progress, now_ms=120_000)
    assert payoff.arc_id == first.arc_id
    assert payoff.arc_stage == "payoff"
    assert payoff.line_shape == "setup_payoff"
    assert payoff.closing_mode == "clean_release"


def test_recorded_opening_is_sent_to_next_directive_as_avoid_rule():
    director = AutonomousShowArcDirector()
    scene = SceneRuntimeState(name="private_idle", stable_for_ms=60_000)
    opp = _opportunity("dead_air", now_ms=200_000, intent="micro_presence")
    first = director.direct(scene=scene, opportunity=opp, now_ms=200_000)
    director.record_spoken(
        text="Im lâu thế. Cái ghế sắp thắng rồi.",
        opportunity=opp,
        directive=first,
        at_ms=201_000,
    )

    next_opp = _opportunity("scene_transition", now_ms=260_000)
    second = director.direct(scene=scene, opportunity=next_opp, now_ms=260_000)
    assert "im lâu thế" in second.avoid_openings
    assert second.novelty_target >= 0.62


def test_performance_act_carries_show_arc_and_maps_payoff_gesture():
    planner = AutonomousPerformancePlanner()
    act = planner.plan(
        "Một bug ngã xuống. Lần này nó nằm yên.",
        autonomous_plan={
            "scene": {"name": "coding_partner"},
            "selected_opportunity": {
                "opportunity_id": "opp_progress",
                "kind": "task_progress",
                "suggested_intent": "react",
            },
            "permit": {
                "allowed": True,
                "mode": "short_reply",
                "max_words": 14,
                "max_duration_ms": 2400,
                "cooldown_after_ms": 24000,
            },
            "session_directive": {"phase": "settled", "cadence": "balanced"},
            "show_arc_directive": {
                "arc_id": "arc_problem",
                "arc_family": "problem_thread",
                "arc_stage": "payoff",
                "line_shape": "setup_payoff",
                "opening_mode": "release_hold",
                "closing_mode": "clean_release",
            },
        },
        performance_context={
            "performance_intent": "react",
            "delivery_style": "dry_payoff",
            "stage_emotion": "satisfied_soft",
            "stage_motion": "tiny_nod",
            "tts_style": "clear_low",
        },
    )

    assert act is not None
    assert act.show_arc_id == "arc_problem"
    assert act.show_arc_stage == "payoff"
    assert act.line_shape == "setup_payoff"
    assert act.speech_beats[0].gesture_intent == "small_release"
    assert act.beats[-1].gesture_intent == "small_release"
    assert act.closing_hold_ms >= 460


def test_resolved_arc_does_not_payoff_twice():
    director = AutonomousShowArcDirector(ShowArcConfig(resolved_grace_ms=120_000))
    scene = SceneRuntimeState(name="coding_partner")
    error = _opportunity("new_error", now_ms=10_000, intent="technical_help")
    setup = director.direct(scene=scene, opportunity=error, now_ms=10_000)
    director.record_spoken(text="Sai tầng.", opportunity=error, directive=setup, at_ms=11_000)

    progress = _opportunity("task_progress", now_ms=20_000)
    payoff = director.direct(scene=scene, opportunity=progress, now_ms=20_000)
    director.record_spoken(text="Xong một mạng.", opportunity=progress, directive=payoff, at_ms=21_000)

    another_progress = _opportunity("task_progress", now_ms=30_000)
    next_directive = director.direct(scene=scene, opportunity=another_progress, now_ms=30_000)
    assert next_directive.arc_id != payoff.arc_id
    assert next_directive.arc_stage == "setup"


def test_coding_progress_uses_payoff_performance_not_technical_help():
    from runtime.content_engine import ContentEngine
    from runtime.director_context import DirectorContext, MachineState, SceneMode
    from runtime.performance_contract import PerformanceContextBuilder

    director_context = DirectorContext(
        session_id="session_test",
        trace_id="trace_test",
        audience_mode="private",
        relation_band="close_restrained",
        scene_mode=SceneMode(name="coding_partner", confidence=0.95),
        machine_state=MachineState(active_app="VS Code", focus_kind="coding"),
        speak_budget_words=18,
        speak_budget_ms=3000,
    )
    performance = PerformanceContextBuilder(content_engine=ContentEngine(persist=False)).build(
        director_context,
        payload={
            "intent": "react",
            "autonomous_plan": {
                "permit": {"allowed": True, "max_words": 14, "max_duration_ms": 2400},
                "selected_opportunity": {"kind": "task_progress", "suggested_intent": "react"},
                "session_directive": {"phase": "settled", "cadence": "balanced"},
                "show_arc_directive": {"arc_stage": "payoff", "line_shape": "setup_payoff"},
            },
        },
        channel="autonomous",
    )

    assert performance.performance_intent == "react"
    assert performance.delivery_style == "dry_payoff"
    assert performance.stage_motion == "tiny_nod"


def test_planning_without_public_commit_does_not_create_phantom_arc():
    director = AutonomousShowArcDirector()
    scene = SceneRuntimeState(name="coding_partner")
    opportunity = _opportunity("new_error", now_ms=400_000, intent="technical_help")

    proposal = director.direct(scene=scene, opportunity=opportunity, now_ms=400_000)
    assert proposal.arc_id
    assert director.snapshot(now_ms=400_100)["active_arc"]["arc_id"] == ""
