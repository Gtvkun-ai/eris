from __future__ import annotations

from runtime.tts_sync_policy import (
    sync_text_with_tts_enabled,
    tts_event_releases_deferred_text,
)


def test_text_sync_with_tts_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("ERIS_TTS_SYNC_TEXT", raising=False)
    assert sync_text_with_tts_enabled() is True


def test_text_sync_can_be_disabled_for_legacy_ui(monkeypatch):
    monkeypatch.setenv("ERIS_TTS_SYNC_TEXT", "0")
    assert sync_text_with_tts_enabled() is False


def test_failed_synthesis_releases_deferred_text():
    assert tts_event_releases_deferred_text("audio_failed") is True
    assert tts_event_releases_deferred_text("audio_queued") is False
    assert tts_event_releases_deferred_text("audio_cancelled") is False
