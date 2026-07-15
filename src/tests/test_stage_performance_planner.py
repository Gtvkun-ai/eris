from __future__ import annotations

from domain.decision import Decision
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_performance_planner import PerformanceRequestPlanner
from runtime.stage_transformers import StageTransformerChain


def test_performance_request_detector_recognizes_laugh_request():
    act = PerformanceRequestPlanner().detect("cười cho tôi nghe coi")

    assert act is not None
    assert act.kind == "playful_laugh"
    assert act.audible_prefix == "Hah... haha."
    assert act.delivery_hint == "dry_tease"


def test_stage_frame_adds_audible_laugh_without_polluting_memory():
    decision = Decision(text="Được.", animation="", intent="chat")

    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "user_text": "cười đi",
        },
        channel="chat",
    )

    assert frame.display_text.startswith("Hah... haha.")
    assert frame.tts_text.startswith("Hah... haha.")
    assert "trò hề" in frame.display_text
    assert "Hah" not in frame.memory_text
    assert frame.delivery["performance_act"]["kind"] == "playful_laugh"
    assert frame.prosody_style == "dry_tease"
    assert "audible_laugh_soft" in frame.actions
    assert frame.motion == "look_away"


def test_stage_frame_keeps_good_model_line_but_adds_laugh_prefix():
    decision = Decision(
        text="bạn định cho tôi làm trò hề gì vậy?",
        animation="",
        intent="chat",
    )

    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "user_text": "cười cho tôi nghe",
        },
        channel="chat",
    )

    assert frame.tts_text == "Hah... haha. bạn định cho tôi làm trò hề gì vậy?"
    assert frame.memory_text == "bạn định cho tôi làm trò hề gì vậy?"


def test_stage_frame_renders_fake_anger_as_deadpan_act():
    decision = Decision(text="Được.", animation="", intent="chat")

    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "user_text": "nổi giận coi",
        },
        channel="chat",
    )

    assert frame.tts_text.startswith("...")
    assert "ra lệnh cho tôi nổi giận" in frame.tts_text
    assert frame.delivery["performance_act"]["kind"] == "fake_annoyed_deadpan"
    assert frame.prosody_style == "deadpan"
    assert "scoff_soft" in frame.actions
    assert frame.motion == "blink_slow"


def test_stage_transformer_still_removes_parenthesized_stage_tags():
    surfaces = StageTransformerChain().transform("(cười khẽ) bạn lại phá gì rồi?")

    assert surfaces.display_text == "bạn lại phá gì rồi?"
    assert surfaces.tts_text == "bạn lại phá gì rồi?"
    assert surfaces.memory_text == "bạn lại phá gì rồi?"
    assert "laugh_soft" in surfaces.marks.actions
