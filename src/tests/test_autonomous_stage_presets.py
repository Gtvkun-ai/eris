# -*- coding: utf-8 -*-
"""Test Phase 4: scene playbook/preset cho autonomous VTuber."""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_performance import AutonomousPerformancePlanner
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_speak_gate import AutonomousSpeakPermissionGate, SpeakGateConfig
from runtime.autonomous_stage_presets import AutonomousStagePresetResolver
from runtime.content_engine import ContentEngine
from runtime.coordinator import RuntimeCoordinator
from runtime.director_context import DirectorContext, MachineState, SceneMode
from runtime.performance_contract import PerformanceContextBuilder


def _opportunity(kind: str, *, strength: float = 0.80, urgency: float = 0.40, now_ms: int = 100_000):
    return AutonomousOpportunity(
        opportunity_id=f"opp_{kind}",
        kind=kind,
        scene_mode="game_companion",
        strength=strength,
        urgency=urgency,
        novelty=0.72,
        evidence_refs=("signal",),
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 30_000,
        suggested_intent="react",
        reason="test",
    )


def test_coding_preset_filters_dead_air_but_keeps_real_error():
    resolver = AutonomousStagePresetResolver()
    preset = resolver.resolve(scene=SceneRuntimeState(name="coding_partner"))
    eligible = resolver.selectable_opportunities(
        (_opportunity("dead_air"), _opportunity("new_error", strength=0.84, urgency=0.78)),
        preset,
    )

    assert preset.preset_id == "coding_partner.focused.v1"
    assert preset.poetic_drift_allowed is False
    assert [item.kind for item in eligible] == ["new_error"]


def test_game_preset_allows_high_salience_burst_and_caps_budget():
    resolver = AutonomousStagePresetResolver()
    preset = resolver.resolve(scene=SceneRuntimeState(name="game_companion"))
    gate = AutonomousSpeakPermissionGate(
        SpeakGateConfig(startup_quiet_ms=0, min_gap_ms=3_000, max_lines_per_hour=20, max_same_kind_streak=3),
        started_at_ms=0,
    )
    permit = gate.evaluate(
        _opportunity("high_salience", strength=0.82),
        scene=SceneRuntimeState(name="game_companion"),
        stage_preset=preset,
        now_ms=100_100,
    )

    assert permit.allowed is True
    assert permit.max_words == 10
    assert permit.max_duration_ms <= 1_650
    assert permit.cooldown_after_ms >= preset.min_gap_ms
    assert "game_companion.reactor.v1" in permit.reason


def test_media_preset_has_anti_spoiler_and_sparse_public_surface():
    preset = AutonomousStagePresetResolver().resolve(scene=SceneRuntimeState(name="media_companion"))
    payload = preset.to_payload()

    assert payload["anti_spoiler"] is True
    assert payload["max_words"] == 12
    assert any("spoil" in rule.lower() for rule in payload["surface_rules"])
    assert "high_salience" in payload["allowed_opportunity_kinds"]


def test_stream_preset_disables_private_memory():
    preset = AutonomousStagePresetResolver().resolve(scene=SceneRuntimeState(name="stream_host"))

    assert preset.audience_mode == "stream"
    assert preset.public_memory_allowed is False
    assert preset.body_first is False
    assert "private_memory_off" in preset.policy_tags


def test_performance_context_uses_scene_preset_lane_instead_of_generic_scene_branch():
    preset = AutonomousStagePresetResolver().resolve(scene=SceneRuntimeState(name="game_companion"))
    director = DirectorContext(
        session_id="session_preset",
        trace_id="trace_preset",
        audience_mode="private",
        relation_band="close_restrained",
        scene_mode=SceneMode(name="game_companion", confidence=0.95),
        machine_state=MachineState(active_app="Game"),
        speak_budget_words=18,
        speak_budget_ms=3_000,
    )
    performance = PerformanceContextBuilder(content_engine=ContentEngine(persist=False)).build(
        director,
        payload={
            "intent": "inner_whim",
            "autonomous_plan": {
                "permit": {"allowed": True, "max_words": 10, "max_duration_ms": 1_650},
                "selected_opportunity": {"kind": "high_salience", "suggested_intent": "react"},
                "session_directive": {"phase": "settled", "cadence": "balanced"},
                "show_arc_directive": {"arc_stage": "setup", "line_shape": "single_strike"},
                "stage_preset": preset.to_payload(),
            },
        },
        channel="autonomous",
    )

    assert performance.performance_intent == "react"
    assert performance.delivery_style == "energetic_short"
    assert performance.stage_emotion == "bright_react"
    assert performance.max_words == 10
    assert "performance_lane=reaction_burst" in performance.reasons


def test_performance_act_carries_preset_and_respects_minimal_gesture_density():
    preset = AutonomousStagePresetResolver().resolve(scene=SceneRuntimeState(name="coding_partner"))
    act = AutonomousPerformancePlanner().plan(
        "Network trước. Parser sau.",
        autonomous_plan={
            "scene": {"name": "coding_partner"},
            "selected_opportunity": {
                "opportunity_id": "opp_error",
                "kind": "new_error",
                "suggested_intent": "technical_help",
            },
            "permit": {
                "allowed": True,
                "mode": "full_line",
                "max_words": 18,
                "max_duration_ms": 3_000,
                "cooldown_after_ms": 24_000,
            },
            "session_directive": {"phase": "deep_focus", "cadence": "restrained"},
            "show_arc_directive": {
                "arc_id": "arc_error",
                "arc_family": "problem_thread",
                "arc_stage": "setup",
                "line_shape": "technical_two_step",
                "opening_mode": "quick_focus",
                "closing_mode": "focused_hold",
            },
            "stage_preset": preset.to_payload(),
        },
        performance_context={
            "performance_intent": "technical_help",
            "delivery_style": "cold_precision",
            "stage_emotion": "focused",
            "stage_motion": "scene_focus",
            "tts_style": "clipped_clear",
        },
    )

    assert act is not None
    assert act.stage_preset_id == "coding_partner.focused.v1"
    assert act.performance_lane == "focus_preserving"
    assert act.gesture_density == "minimal"
    assert act.speech_beats[0].gesture_intent == "none"
    assert act.closing_hold_ms >= preset.closing_hold_min_ms


def test_autonomous_prompt_v5_includes_resolved_preset_policy():
    preset = AutonomousStagePresetResolver().resolve(scene=SceneRuntimeState(name="media_companion"))
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator.last_autonomous_plan = SimpleNamespace(
        enabled=True,
        scene=SceneRuntimeState(name="media_companion"),
        selected_opportunity=_opportunity("high_salience"),
        permit=SimpleNamespace(allowed=True, mode="short_reply", max_words=12, max_duration_ms=2_100),
        session_directive=SimpleNamespace(
            phase="settled", cadence="sparse", audience_fatigue=0.1,
            body_only_bias=0.4, recent_kinds=("high_salience",),
        ),
        show_arc_directive=SimpleNamespace(
            arc_id="arc_media", arc_family="reaction_thread", arc_stage="setup",
            continuity_mode="new_arc", line_shape="single_strike", callback_anchor="",
            avoid_openings=(), novelty_target=0.72, escalation_level=0,
        ),
        stage_preset=preset,
        audience_feedback=SimpleNamespace(
            mode="low_intrusion", engagement_score=-0.1, intrusion_pressure=0.5,
            recent_outcome="ignored", suppressed_kinds=("high_salience",),
        ),
    )

    block = coordinator._autonomous_stage_prompt_block()
    payload = json.loads(block.split("\n", 1)[1])

    assert payload["contract"] == "autonomous_stage.v5"
    assert payload["stage_preset"]["preset_id"] == "media_companion.side_commentary.v1"
    assert payload["stage_preset"]["anti_spoiler"] is True
    assert payload["audience_feedback"]["mode"] == "low_intrusion"
    assert payload["audience_feedback"]["recent_outcome"] == "ignored"
    assert any("spoil" in rule.lower() for rule in payload["surface_rules"])
    assert any("không mở chủ đề mới" in rule.lower() for rule in payload["surface_rules"])
