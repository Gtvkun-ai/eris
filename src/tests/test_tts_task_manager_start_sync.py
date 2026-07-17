from __future__ import annotations

import threading

from runtime.stage_audio_bus import StageAudioBus
from runtime.stage_contracts import StageFrame
from runtime.tts_task_manager import TtsTaskManager


def _frame() -> StageFrame:
    return StageFrame(
        turn_id="take-sync",
        segment_id=0,
        display_text="Xin chào.",
        tts_text="Xin chào.",
        emotion="calm",
        motion="stand",
        interruptible=True,
        source="test",
    )


def test_audio_start_is_emitted_after_backend_reports_device_started(monkeypatch):
    order: list[str] = []

    class Backend:
        def synthesize(self, text, **kwargs):
            return b"wav"

        def play_audio(self, wav_bytes, stop_event, on_started=None):
            order.append("device_started")
            assert callable(on_started)
            on_started()
            order.append("audio_flowing")

    manager = TtsTaskManager(
        audio_bus=StageAudioBus(),
        prefetch_workers=1,
        max_prefetch_segments=4,
    )
    monkeypatch.setenv("ERIS_TTS_PREFETCH_MODE", "prefetch")

    assert manager.dispatch_frames(
        [_frame()],
        backend=Backend(),
        valence=0.0,
        arousal=0.2,
        stance="test",
        on_event=lambda event, frame: order.append(event.type),
    ) is True
    assert manager.wait_until_idle(timeout=2.0) is True

    assert order.index("device_started") < order.index("audio_start") < order.index("audio_flowing")
    assert order.count("audio_start") == 1


def test_legacy_two_argument_playback_backend_still_works(monkeypatch):
    events: list[str] = []

    class LegacyBackend:
        def synthesize(self, text, **kwargs):
            return b"wav"

        def play_audio(self, wav_bytes, stop_event: threading.Event):
            events.append("legacy_play")

    manager = TtsTaskManager(prefetch_workers=1, max_prefetch_segments=4)
    monkeypatch.setenv("ERIS_TTS_PREFETCH_MODE", "prefetch")
    assert manager.dispatch_frames(
        [_frame()],
        backend=LegacyBackend(),
        valence=0.0,
        arousal=0.2,
        stance="test",
        on_event=lambda event, frame: events.append(event.type),
    ) is True
    assert manager.wait_until_idle(timeout=2.0) is True
    assert events.index("audio_start") < events.index("legacy_play")
