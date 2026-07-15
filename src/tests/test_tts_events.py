from __future__ import annotations

import time

import runtime.tts_engine as tts


def test_tts_worker_emits_queued_start_done_events():
    events = []
    old_synth = tts._synthesize_wav
    old_play = tts._play_wav_bytes
    tts._synthesize_wav = lambda prompt, voice, model: b"fake-wav"
    tts._play_wav_bytes = lambda wav_bytes, stop_event: None
    worker = tts._TtsWorker("Aoede", "fake-model", "auto")
    try:
        worker.speak(
            tts._SpeakRequest(
                "bạn lại phá gì rồi?",
                turn_id="turn-x",
                segment_id=2,
                prosody_style="dry_tease",
                on_event=events.append,
            )
        )

        deadline = time.time() + 2.0
        while time.time() < deadline and "audio_done" not in [event.type for event in events]:
            time.sleep(0.02)

        event_types = [event.type for event in events]
        assert event_types[:3] == ["audio_queued", "audio_start", "audio_done"]
        assert events[-1].turn_id == "turn-x"
        assert events[-1].segment_id == 2
    finally:
        worker.shutdown()
        tts._synthesize_wav = old_synth
        tts._play_wav_bytes = old_play
