# -*- coding: utf-8 -*-

from types import SimpleNamespace

from runtime.body_choreography import BodyChoreographyPlanner
from runtime.stage_contracts import StageFrameBuilder


class DummyDecision:
    text = "Được rồi."
    intent = "chat"
    animation = "stand"
    should_speak = True


def test_body_choreography_maps_laugh_to_hop_timeline():
    planner = BodyChoreographyPlanner()

    timeline = planner.plan(
        turn_id="t1",
        text="Hah... haha. bạn định cho tôi làm trò hề gì vậy?",
        motion="look_away",
        actions=("audible_laugh_soft",),
        delivery={"performance_act": {"kind": "playful_laugh"}},
    )

    assert timeline is not None
    payload = timeline.to_payload()
    assert payload["source"] == "performance_act:playful_laugh"
    assert payload["events"][0]["name"] == "hop"
    assert payload["events"][1]["intent"] == "face"


def test_stage_frame_includes_body_timeline_for_performance_request():
    builder = StageFrameBuilder()
    frame = builder.build(
        DummyDecision(),
        payload={"text": "Được rồi.", "user_text": "cười đi"},
        turn_id="turn-laugh",
    )

    patch = frame.to_payload_patch()
    timeline = patch["stage"]["body_timeline"]
    assert timeline["turn_id"] == "turn-laugh"
    assert timeline["events"][0]["name"] == "hop"
    assert frame.memory_text


def test_stage_frame_does_not_force_body_timeline_for_plain_reply():
    builder = StageFrameBuilder()
    frame = builder.build(
        DummyDecision(),
        payload={"text": "Tôi nghe đây.", "user_text": "hôm nay ổn không"},
        frame=SimpleNamespace(appraisal=None),
        turn_id="turn-normal",
    )

    assert "body_timeline" not in frame.to_payload_patch()["stage"]
