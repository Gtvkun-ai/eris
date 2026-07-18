from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import runtime.tts_engine as tts
from runtime.stage_contracts import StageFrame
from runtime.tts_task_manager import TtsTaskManager


def _wait(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _frame(turn_id: str = "turn-old") -> StageFrame:
    return StageFrame(
        turn_id=turn_id,
        segment_id=0,
        display_text="Câu cũ.",
        tts_text="Câu cũ.",
        emotion="calm",
        motion="stand",
        interruptible=True,
        source="test",
    )


def test_worker_drops_remote_audio_that_finishes_after_turn_changed(monkeypatch):
    synth_started = threading.Event()
    release_synth = threading.Event()
    played: list[bytes] = []
    started: list[str] = []
    events = []
    authority = {"epoch": 1, "turn": "turn-old"}

    def fake_synth(*args, **kwargs):
        synth_started.set()
        assert release_synth.wait(2.0)
        return b"old-wav"

    monkeypatch.setattr(tts, "_invoke_synthesize_wav", fake_synth)
    monkeypatch.setattr(tts, "_play_wav_bytes", lambda wav, stop, **kwargs: played.append(wav))

    worker = tts._TtsWorker(
        "Aoede",
        "fake-model",
        "vi",
        epoch_validator=lambda epoch, turn: (
            epoch == authority["epoch"] and turn == authority["turn"]
        ),
    )
    try:
        worker.speak(
            tts._SpeakRequest(
                "Câu cũ.",
                turn_id="turn-old",
                speech_epoch=1,
                on_start_play=lambda: started.append("start"),
                on_event=events.append,
            )
        )
        assert synth_started.wait(1.0)
        authority.update(epoch=2, turn="turn-new")
        release_synth.set()
        assert _wait(lambda: any(e.type == "audio_cancelled" for e in events))
        assert played == []
        assert started == []
        assert any(e.reason == "stale_turn_before_playback" for e in events)
    finally:
        worker.shutdown()


def test_task_manager_does_not_play_or_reveal_stale_turn(monkeypatch):
    synth_started = threading.Event()
    release_synth = threading.Event()
    played: list[bytes] = []
    revealed: list[str] = []
    events = []
    authority = {"epoch": 4, "turn": "turn-old"}

    class Backend:
        def synthesize(self, text, **kwargs):
            synth_started.set()
            assert release_synth.wait(2.0)
            return b"old-wav"

        def play_audio(self, wav_bytes, stop_event, on_started=None):
            played.append(wav_bytes)
            if on_started:
                on_started()

        def is_speech_epoch_current(self, epoch, turn_id=""):
            return epoch == authority["epoch"] and turn_id == authority["turn"]

    monkeypatch.setenv("ERIS_TTS_PREFETCH_MODE", "prefetch")
    manager = TtsTaskManager(prefetch_workers=1, max_prefetch_segments=4)
    assert manager.dispatch_frames(
        [_frame()],
        backend=Backend(),
        valence=0.0,
        arousal=0.2,
        stance="test",
        speech_epoch=4,
        on_first_start=lambda: revealed.append("old-text"),
        on_event=lambda event, frame: events.append(event),
    )
    assert synth_started.wait(1.0)
    authority.update(epoch=5, turn="turn-new")
    release_synth.set()
    assert manager.wait_until_idle(timeout=2.0)
    assert played == []
    assert revealed == []
    assert any(e.reason == "stale_turn_before_playback" for e in events)


def test_engine_supersede_cancels_manager_and_legacy_worker():
    calls = []

    class QueueOwner:
        def __init__(self, name):
            self.name = name

        def cancel_current(self, **kwargs):
            calls.append((self.name, kwargs))
            return True

    engine = tts.TtsEngine.__new__(tts.TtsEngine)
    engine._speech_lock = threading.RLock()
    engine._speech_epoch = 7
    engine._speech_turn_id = "turn-old"
    engine.task_manager = QueueOwner("manager")
    engine._worker = QueueOwner("worker")

    assert engine.supersede_all(reason="user_chat") is True
    assert engine._speech_epoch == 8
    assert engine._speech_turn_id == ""
    assert {name for name, _ in calls} == {"manager", "worker"}
    assert all(kwargs["only_interruptible"] is False for _, kwargs in calls)


def test_begin_speech_turn_is_idempotent_for_dispatch_fallback():
    engine = tts.TtsEngine.__new__(tts.TtsEngine)
    engine._speech_lock = threading.RLock()
    engine._speech_epoch = 0
    engine._speech_turn_id = ""
    engine.task_manager = None
    engine._worker = None

    first = engine.begin_speech_turn("turn-a")
    second = engine.begin_speech_turn("turn-a")
    third = engine.begin_speech_turn("turn-b")

    assert first == second
    assert third == first + 1
    assert engine.is_speech_epoch_current(third, "turn-b")
    assert not engine.is_speech_epoch_current(first, "turn-a")


def test_provider_retry_stops_before_rotating_to_next_key_when_superseded(monkeypatch):
    """Một request cũ bị thu hồi không được tiếp tục đốt cả key pool."""
    import sys
    import types as pytypes

    cancel_event = threading.Event()
    acquired: list[int] = []

    class FakePool:
        size = 3

        def acquire(self, exclude_indices=None):
            index = len(acquired)
            acquired.append(index)
            return SimpleNamespace(index=index, key=f"key-{index}")

        def next_available_in(self):
            return 0.0

        def mark_success(self, **kwargs):
            return None

    class FakeModels:
        def generate_content(self, **kwargs):
            cancel_event.set()
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: kwargs,
        SpeechConfig=lambda **kwargs: kwargs,
        VoiceConfig=lambda **kwargs: kwargs,
        PrebuiltVoiceConfig=lambda **kwargs: kwargs,
    )
    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_genai.types = fake_types

    import google
    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr("llm.key_pool.get_key_pool", lambda provider="gemini": FakePool())
    monkeypatch.setattr(tts, "_tts_breaker_enabled", lambda: False)
    monkeypatch.setattr(tts, "_tts_max_attempts", lambda: 3)
    from runtime.tts_key_health import GLOBAL_TTS_KEY_LANE_HEALTH
    monkeypatch.setattr(GLOBAL_TTS_KEY_LANE_HEALTH, "excluded_indices", lambda: ())

    try:
        tts._synthesize_wav(
            "prompt",
            "Aoede",
            "fake-model",
            fallback_text="Câu cũ.",
            language_hint="vi",
            cancel_event=cancel_event,
        )
    except RuntimeError as exc:
        assert str(exc) == "tts_cancelled"
    else:  # pragma: no cover - test phải thấy request bị thu hồi
        raise AssertionError("TTS request cũ không bị hủy")

    assert acquired == [0]
