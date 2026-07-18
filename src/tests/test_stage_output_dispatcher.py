from __future__ import annotations

import os
from dataclasses import replace

from runtime.stage_contracts import StageFrame
from runtime.stage_dispatcher import StageDispatcher
from runtime.stage_output import StageOutputPipeline


def _frame(text: str) -> StageFrame:
    return StageFrame(
        turn_id="turn-1",
        segment_id=0,
        display_text=text,
        tts_text=text,
        emotion="focused",
        motion="none",
        prosody_style="focused",
        prosody_notes="read clearly",
        interruptible=True,
        source="test",
    )


def test_stage_output_pipeline_splits_long_tts_into_segments():
    frame = _frame(
        "Khoan. Cái này không chết ở TTS. Nó chết ở stage layer trước đó. "
        "Sửa đúng là tách câu ra rồi mới phát."
    )

    frames = StageOutputPipeline().frames_for_tts(frame)

    assert len(frames) >= 3
    assert [item.segment_id for item in frames] == list(range(len(frames)))
    assert {item.turn_id for item in frames} == {"turn-1"}
    assert frames[0].tts_text == "Khoan."


def test_autonomous_beat_pause_is_only_kept_on_its_last_subsegment():
    frame = _frame("Một beat dài có nhiều câu.")
    frame = replace(
        frame,
        stage_act={
            "beats": [{
                "kind": "speech",
                "text": "Câu thứ nhất đủ dài để tách. Câu thứ hai cũng thuộc cùng một beat.",
                "pause_after_ms": 1400,
                "pause_jitter_ms": 0,
            }]
        },
    )

    frames = StageOutputPipeline().frames_for_tts(frame)

    assert len(frames) >= 2
    pauses = [item.delivery["active_beat"]["pause_after_ms"] for item in frames]
    assert pauses[:-1] == [0] * (len(pauses) - 1)
    assert pauses[-1] == 1400


def test_stage_dispatcher_inlines_segments_by_default_to_avoid_remote_tts_gaps():
    calls = []

    class FakeTts:
        _ok = True

        def speak(self, text, **kwargs):
            calls.append((text, kwargs))
            if kwargs.get("on_event"):
                kwargs["on_event"](type("Event", (), {"type": "audio_queued"})())

    frames = (
        _frame("Một."),
        _frame("Hai."),
        _frame("Ba."),
    )
    frames = tuple(
        StageFrame(
            turn_id=item.turn_id,
            segment_id=index,
            display_text=item.display_text,
            tts_text=item.tts_text,
            emotion=item.emotion,
            motion=item.motion,
            prosody_style=item.prosody_style,
            prosody_notes=item.prosody_notes,
            interruptible=item.interruptible,
            source=item.source,
        )
        for index, item in enumerate(frames)
    )

    ok = StageDispatcher().dispatch_tts(
        frames,
        tts_engine=FakeTts(),
        valence=0.0,
        arousal=0.3,
        stance="",
    )

    assert ok is True
    assert len(calls) == 1
    assert calls[0][0] == "Một. Hai. Ba."
    assert calls[0][1]["replace"] is True
    assert calls[0][1]["segment_id"] == 0
    assert "do not insert long silence" in calls[0][1]["prosody_notes"]


def test_stage_dispatcher_can_queue_segments_when_explicitly_enabled():
    calls = []

    class FakeTts:
        _ok = True

        def speak(self, text, **kwargs):
            calls.append((text, kwargs))

    frames = tuple(
        StageFrame(
            turn_id="turn-1",
            segment_id=index,
            display_text=text,
            tts_text=text,
            emotion="focused",
            motion="none",
            prosody_style="focused",
            prosody_notes="read clearly",
            interruptible=True,
            source="test",
        )
        for index, text in enumerate(("Một.", "Hai.", "Ba."))
    )

    old = os.environ.get("ERIS_TTS_SEGMENT_DISPATCH")
    os.environ["ERIS_TTS_SEGMENT_DISPATCH"] = "queued"
    try:
        ok = StageDispatcher().dispatch_tts(
            frames,
            tts_engine=FakeTts(),
            valence=0.0,
            arousal=0.3,
            stance="",
        )
    finally:
        if old is None:
            os.environ.pop("ERIS_TTS_SEGMENT_DISPATCH", None)
        else:
            os.environ["ERIS_TTS_SEGMENT_DISPATCH"] = old

    assert ok is True
    assert [call[0] for call in calls] == ["Một.", "Hai.", "Ba."]
    assert [call[1]["replace"] for call in calls] == [True, False, False]
    assert [call[1]["segment_id"] for call in calls] == [0, 1, 2]
