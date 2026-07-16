# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from runtime.autonomous_show_formats import AutonomousShowFormatDirector
from runtime.autonomous_surface_anchor import AutonomousSurfaceAnchorGuard
from runtime.stage_contracts import StageFrame, StageFrameBuilder
from runtime.stage_event_bus import StageEventBus
from runtime.stage_protocol import STAGE_PROTOCOL_VERSION, StageProtocolEvent
from runtime.stage_protocol_adapter import show_plan_event
from runtime.stage_session_runtime import StageSessionRuntime
from runtime.stage_show_runtime import StageShowRuntime


@dataclass
class Decision:
    text: str
    animation: str = "stand"
    intent: str = "react"
    should_speak: bool = True

    def resolve_motion_intent(self) -> str:
        return "tilt_head"


class Transport:
    def __init__(self):
        self.payloads = []

    def send_json(self, payload):
        self.payloads.append(dict(payload))


def _plan(kind="new_error", evidence=("error_event",)):
    return {
        "scene": {"name": "coding_partner"},
        "selected_opportunity": {
            "opportunity_id": "opp_1",
            "kind": kind,
            "scene_mode": "coding_partner",
            "suggested_intent": "react",
            "evidence_refs": list(evidence),
        },
        "permit": {"allowed": True, "mode": "short_reply", "cooldown_after_ms": 1000},
        "show_format": {
            "format_id": "technical_sting",
            "family": "technical",
            "variant": 1,
            "max_beats": 2,
            "stage_energy": 0.56,
            "opening_mode": "quick_focus",
            "closing_mode": "focused_hold",
            "anchor_policy": "require_surface_anchor",
            "required_evidence_refs": list(evidence),
        },
    }


def test_phase8_show_runtime_compiles_open_speech_pause_close():
    frame = StageFrame(
        turn_id="turn1",
        tts_text="Một bug ngã xuống.",
        emotion="mischief",
        motion="tilt_head",
        stage_act={
            "act_id": "act1",
            "opportunity_kind": "new_error",
            "show_format_id": "technical_sting",
            "beats": [
                {"kind": "opening_hold", "duration_ms": 100, "motion_intent": "tilt_head"},
                {"kind": "speech", "text": "Một bug ngã xuống.", "duration_ms": 700, "pause_after_ms": 180},
                {"kind": "closing_settle", "duration_ms": 300},
            ],
        },
    )
    plan = StageShowRuntime().compile(frame)
    kinds = [cue.kind for cue in plan.cues]
    assert kinds == ["act_open", "opening_hold", "speech_prepare", "speech_window", "rhetorical_pause", "closing_settle", "act_close"]
    assert plan.total_duration_ms == 1280
    assert plan.cues[2].segment_index == 0


def test_phase8_stage_builder_attaches_avatar_neutral_show_plan():
    decision = Decision("Một bug ngã xuống. Ba bug khác đứng dậy.")
    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "autonomous_plan": _plan(),
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
    assert frame.show_plan["version"] == "eris.show.v1"
    assert frame.show_plan["turn_id"] == "turn-auto"
    assert any(cue["kind"] == "speech_window" for cue in frame.show_plan["cues"])
    assert "live2d" not in str(frame.show_plan).lower()


def test_phase9_format_director_selects_anchor_safe_formats():
    director = AutonomousShowFormatDirector()
    opportunity = SimpleNamespace(kind="new_error", evidence_refs=("error_event",))
    directive = director.select(
        scene=SimpleNamespace(name="coding_partner"),
        opportunity=opportunity,
        show_arc=SimpleNamespace(arc_stage="setup"),
        audience_feedback=SimpleNamespace(mode="normal"),
    )
    assert directive.format_id == "technical_sting"
    assert directive.anchor_policy == "require_surface_anchor"
    assert directive.max_beats == 2


def test_phase9_anchor_guard_rewrites_hollow_task_claim():
    verdict = AutonomousSurfaceAnchorGuard().validate(
        "Giao tôi phần khó nhất đi.",
        {
            "scene": {"name": "private_idle"},
            "selected_opportunity": {"kind": "dead_air", "evidence_refs": ["idle_ms"]},
            "show_format": {"anchor_policy": "require_surface_anchor"},
        },
    )
    assert verdict.rewritten is True
    assert verdict.text == "Yên lặng cũng được. Tôi chưa cần chen."
    assert "hollow_task_premise" in verdict.unsupported


def test_phase10_stage_session_envelope_ack_and_replay():
    runtime = StageSessionRuntime(max_replay=20)
    first = runtime.prepare(StageProtocolEvent(type="show_plan", turn_id="t1"))
    second = runtime.prepare(StageProtocolEvent(type="stage_segment", turn_id="t1", seq=0))
    runtime.record_sent(first.to_payload(), success=True)
    runtime.record_sent(second.to_payload(), success=True)
    assert first.event_seq == 1
    assert second.event_seq == 2
    assert len(runtime.replay_after(1)) == 1
    runtime.observe_inbound({"type": "stage_ack", "event_seq": 2})
    assert runtime.snapshot()["ack_backlog"] == 0


def test_phase10_event_bus_emits_protocol_v2_monotonic_event_seq():
    transport = Transport()
    bus = StageEventBus(transport=transport)
    assert bus.emit(StageProtocolEvent(type="stage_state", turn_id="t1")) is True
    assert bus.emit(StageProtocolEvent(type="stage_segment", turn_id="t1", seq=0)) is True
    assert STAGE_PROTOCOL_VERSION == 2
    assert [p["event_seq"] for p in transport.payloads] == [1, 2]
    assert transport.payloads[0]["session_id"] == transport.payloads[1]["session_id"]


def test_show_plan_protocol_event_keeps_timeline_out_of_text():
    frame = StageFrame(
        turn_id="t2",
        display_text="Ổn.",
        show_plan={"show_id": "show1", "version": "eris.show.v1", "cues": [{"kind": "act_open"}]},
    )
    payload = show_plan_event(frame).to_payload()
    assert payload["type"] == "show_plan"
    assert payload["data"]["show_plan"]["show_id"] == "show1"
    assert payload["display_text"] == "Ổn."
