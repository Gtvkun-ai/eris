# -*- coding: utf-8 -*-
"""Test contract autonomous performer.

Các test này cố ý không đụng mic, VAD, ASR hay Live2D. Mục tiêu là chứng minh
Eris chỉ nói khi có opportunity, rồi biến câu đã được cấp quyền thành một act có
opening/speech/closing đủ trung tính để body 3D sau này map lại.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_orchestrator import AutonomousPerformerOrchestrator
from runtime.autonomous_performance import AutonomousPerformancePlanner, BeatScheduler
from runtime.autonomous_scene_runtime import AutonomousSceneRuntime, SceneRuntimeConfig, SceneRuntimeState
from runtime.autonomous_speak_gate import AutonomousSpeakPermissionGate, SpeakGateConfig
from runtime.autonomous_wake_governor import WakeDecision
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_output import StageOutputPipeline


def _snapshot(*, app: str = "Desktop", title: str = "", idle: float = 0.0, events=(), metadata=None):
    return SimpleNamespace(
        active_app=app,
        active_window_title=title,
        url_or_path_hint="",
        focus_kind_hint="unknown",
        idle_seconds=idle,
        recent_events=tuple(events),
        metadata=dict(metadata or {}),
    )


def _wake(level: str = "sleep") -> WakeDecision:
    return WakeDecision(
        level=level,
        should_speak=False,
        should_call_vision=False,
        should_wake_main=False,
        should_run_daydream=False,
        reason="test",
        confidence=0.5,
        speech_value=0.2,
        interrupt_cost=0.1,
    )


def _opportunity(*, now_ms: int = 100_000, kind: str = "dead_air") -> AutonomousOpportunity:
    return AutonomousOpportunity(
        opportunity_id="opp_test",
        kind=kind,
        scene_mode="private_idle",
        strength=0.74,
        urgency=0.3,
        novelty=0.7,
        evidence_refs=("idle_ms",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 20_000,
        suggested_intent="micro_presence",
        reason="test_opportunity",
    )


def test_scene_runtime_requires_stable_candidate_before_transition():
    runtime = AutonomousSceneRuntime(
        SceneRuntimeConfig(transition_hold_ms=2_000, immediate_confidence=0.99, idle_scene_after_seconds=18.0)
    )
    initial = runtime.update(signal_snapshot=_snapshot(app="Desktop"), now_ms=1_000)
    assert initial.name == "private_active"

    pending = runtime.update(
        signal_snapshot=_snapshot(app="Notion", title="Tài liệu"),
        observer_frame=SimpleNamespace(focus_kind="docs", activity_intent="reading"),
        now_ms=2_000,
    )
    assert pending.name == "private_active"
    assert pending.candidate_name == "study_session"

    stable = runtime.update(
        signal_snapshot=_snapshot(app="Notion", title="Tài liệu"),
        observer_frame=SimpleNamespace(focus_kind="docs", activity_intent="reading"),
        now_ms=4_100,
    )
    assert stable.name == "study_session"
    assert stable.previous_name == "private_active"
    assert stable.transition_seq == 1


def test_speak_gate_denies_when_user_is_typing():
    gate = AutonomousSpeakPermissionGate(
        SpeakGateConfig(startup_quiet_ms=0, min_gap_ms=3_000, max_lines_per_hour=12, max_same_kind_streak=2),
        started_at_ms=0,
    )
    scene = SceneRuntimeState(name="coding_partner", user_typing=True)
    permit = gate.evaluate(_opportunity(kind="new_error"), scene=scene, now_ms=100_100)

    assert permit.allowed is False
    assert permit.mode == "body_only"
    assert permit.reason == "user_is_typing"


def test_orchestrator_promotes_return_after_idle_to_one_main_generation():
    orchestrator = AutonomousPerformerOrchestrator()
    orchestrator.speak_gate.started_at_ms = 0

    # Tick đầu ghi nhận idle dài nhưng không phát greeting lúc vừa khởi động scene.
    orchestrator.evaluate(
        signal_snapshot=_snapshot(idle=120.0),
        observer_frame=SimpleNamespace(focus_kind="unknown", activity_intent="idle", possible_error=0.0, novelty=0.0, salience=0.0),
        wake_decision=_wake(),
        now_ms=100_000,
    )
    plan = orchestrator.evaluate(
        signal_snapshot=_snapshot(idle=0.0),
        observer_frame=SimpleNamespace(focus_kind="unknown", activity_intent="active", possible_error=0.0, novelty=0.2, salience=0.2),
        wake_decision=_wake(),
        now_ms=102_000,
    )

    assert plan.selected_opportunity is not None
    assert plan.selected_opportunity.kind == "return_after_idle"
    assert plan.permit.allowed is True
    refined = orchestrator.refine_wake_decision(_wake(), plan)
    assert refined.level == "wake_main_cognition"
    assert refined.should_speak is True
    assert refined.should_wake_main is True


def test_performance_planner_makes_one_opening_hold_not_two():
    planner = AutonomousPerformancePlanner()
    act = planner.plan(
        "Một bug ngã xuống. Ba bug khác đứng dậy.",
        autonomous_plan={
            "scene": {"name": "coding_partner"},
            "selected_opportunity": {
                "opportunity_id": "opp_bug",
                "kind": "new_error",
                "suggested_intent": "technical_help",
            },
            "permit": {
                "allowed": True,
                "mode": "full_line",
                "max_words": 18,
                "max_duration_ms": 3_000,
                "cooldown_after_ms": 22_000,
            },
        },
        performance_context={
            "performance_intent": "tease",
            "delivery_style": "dry_tease",
            "stage_emotion": "mischief",
            "stage_motion": "tilt_head",
            "tts_style": "amused_low",
        },
    )

    assert act is not None
    assert [beat.kind for beat in act.beats] == ["opening_hold", "speech", "speech", "closing_settle"]
    assert act.speech_beats[0].start_after_ms == 0
    timeline = BeatScheduler().schedule(act, started_at_ms=1_000)
    assert timeline[0].at_ms == 1_000
    assert timeline[1].at_ms == 1_000 + act.opening_hold_ms
    assert act.total_budget_ms == sum(beat.duration_ms + beat.pause_after_ms for beat in act.beats)


@dataclass
class _Decision:
    text: str
    animation: str = "stand"
    intent: str = "react"
    should_speak: bool = True

    def resolve_motion_intent(self) -> str:
        return "tilt_head"


def test_stage_frame_carries_avatar_neutral_autonomous_act():
    decision = _Decision("Một bug ngã xuống. Ba bug khác đứng dậy.")
    plan = {
        "enabled": True,
        "scene": {"name": "coding_partner"},
        "selected_opportunity": {
            "opportunity_id": "opp_bug",
            "kind": "new_error",
            "scene_mode": "coding_partner",
            "suggested_intent": "technical_help",
        },
        "permit": {
            "allowed": True,
            "mode": "full_line",
            "max_words": 18,
            "max_duration_ms": 3_000,
            "cooldown_after_ms": 22_000,
        },
    }
    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "autonomous_plan": plan,
            "performance_context": {
                "performance_intent": "tease",
                "delivery_style": "dry_tease",
                "stage_emotion": "mischief",
                "stage_motion": "tilt_head",
                "tts_style": "amused_low",
            },
        },
        channel="autonomous",
        turn_id="turn-auto",
    )

    assert frame.stage_act["opportunity_kind"] == "new_error"
    assert frame.stage_act["scene_mode"] == "coding_partner"
    assert "hotkey" not in str(frame.stage_act).lower()
    assert "live2d" not in str(frame.stage_act).lower()
    speech_frames = StageOutputPipeline().frames_for_tts(frame)
    assert [item.tts_text for item in speech_frames] == ["Một bug ngã xuống.", "Ba bug khác đứng dậy."]
    assert speech_frames[0].delivery["active_beat"]["head_intent"] == "tilt_small"
