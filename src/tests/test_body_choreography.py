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


def test_segmenter_does_not_replay_same_body_timeline_on_every_segment():
    from runtime.stage_output import StageOutputPipeline

    builder = StageFrameBuilder()
    frame = builder.build(
        DummyDecision(),
        payload={
            "text": "Hah. Tôi đang cười đây. Nhưng đừng biến nó thành ba lần nhảy liên tiếp.",
            "user_text": "cười đi",
        },
        turn_id="turn-segmented-laugh",
    )
    frames = StageOutputPipeline(profile=SimpleNamespace(
        logical_segment_tts=True, min_split_chars=24, max_tts_segments=8
    )).frames_for_tts(frame)
    assert frames[0].body_timeline
    assert all(not item.body_timeline for item in frames[1:])


def test_small_smile_is_subtle_and_does_not_turn_into_a_hop():
    planner = BodyChoreographyPlanner()

    timeline = planner.plan(
        turn_id="t-soft",
        text="Khá gian, với một cây nấm.",
        motion="small_smile",
        actions=(),
        delivery={},
    )

    assert timeline is not None
    names = [event["name"] for event in timeline.to_payload()["events"]]
    assert "hop" not in names
    assert names[0] == "stand"


def test_reaction_arc_maps_to_recognition_then_assimilation_poses():
    planner = BodyChoreographyPlanner()

    recognized = planner.plan(
        turn_id="t-recognize",
        text="À...",
        motion="recognition",
        actions=(),
        delivery={},
    )
    assimilated = planner.plan(
        turn_id="t-assimilate",
        text="Ở một số loài, ánh sáng có thể thu hút côn trùng.",
        motion="assimilate",
        actions=(),
        delivery={},
    )

    assert recognized is not None
    assert assimilated is not None
    assert recognized.to_payload()["events"][0]["name"] == "stand"
    assert assimilated.to_payload()["events"][0]["name"] == "read"


def test_belief_update_looks_away_instead_of_hopping():
    planner = BodyChoreographyPlanner()
    timeline = planner.plan(turn_id="turn-belief", text="Tôi cứ tưởng khác.", motion="belief_update")
    assert timeline is not None
    names = [event.name for event in timeline.events]
    assert "hop" not in names
    assert names[:2] == ["stand", "read"]
    assert timeline.events[0].facing == -1
