from types import SimpleNamespace
import threading
import time

from runtime.stage_continuation import StageContinuationRuntime
from runtime.stage_protocol_adapter import playback_event
from runtime.stage_audio_bus import StageAudioEvent


def _frame(pause_ms: int):
    return SimpleNamespace(
        turn_id="turn-1", segment_id=0, tts_text="Một câu.", display_text="Một câu.",
        emotion="curious", motion="look_aside", interruptible=True, source="test",
        delivery={"active_beat": {"pause_after_ms": pause_ms, "pause_jitter_ms": 0}},
    )


def test_long_pause_becomes_thinking_wait():
    runtime = StageContinuationRuntime(short_pause_max_ms=600)
    wait = runtime.wait_contract(_frame(1200))
    assert wait.kind == "thinking_pause"
    assert wait.delay_ms == 1200


def test_wait_is_interruptible():
    runtime = StageContinuationRuntime(short_pause_max_ms=100)
    generation, cancel_event = runtime.begin_generation()
    events = []

    thread = threading.Thread(
        target=runtime.wait_after_frame,
        args=(_frame(1000),),
        kwargs={"generation": generation, "cancel_event": cancel_event, "emit": lambda t, r: events.append(t)},
    )
    thread.start()
    time.sleep(0.05)
    runtime.cancel("user_input")
    thread.join(timeout=0.5)
    assert not thread.is_alive()
    assert "thinking_started" in events
    assert "continuation_cancelled" in events


def test_protocol_exposes_thinking_state():
    event = StageAudioEvent(type="thinking_started", turn_id="t", segment_id=1, reason="deliberate_thought")
    protocol = playback_event(event, stage_frame=_frame(900))
    assert protocol.type == "thinking_started"
    assert protocol.reason == "deliberate_thought"


def test_thinking_protocol_carries_body_pose_and_return_to_stand():
    started = playback_event(
        StageAudioEvent(type="thinking_started", turn_id="t", segment_id=1, reason="pause"),
        stage_frame=_frame(900),
    ).to_payload()
    assert started["motion"] == "read"
    assert started["data"]["body_timeline"]["events"][0]["name"] == "read"

    finished = playback_event(
        StageAudioEvent(type="thinking_finished", turn_id="t", segment_id=1, reason="done"),
        stage_frame=_frame(900),
    ).to_payload()
    assert finished["motion"] == "stand"
    assert finished["data"]["body_timeline"]["events"][0]["name"] == "stand"
