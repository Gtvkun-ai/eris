# -*- coding: utf-8 -*-
"""Regression của lỗi chat phụ họa -> hủy Root và TTS breaker báo lỗi giả."""

from types import SimpleNamespace

from runtime.conversation import InterruptKind, classify_interrupt
from runtime.tts_circuit_breaker import BreakerState, TtsCircuitBreaker
from runtime.voice_manager import VoiceManager


def test_unicode_and_punctuation_backchannel_share_one_classifier():
    import unicodedata

    for text in ("ô", "Ồ!", "ừm...", "đúng rồi!", "hmm...", "oke!", "được"):
        nfc = unicodedata.normalize("NFC", text)
        assert classify_interrupt(nfc).kind == InterruptKind.BACKCHANNEL
        assert not classify_interrupt(nfc).cancel_generation
        assert not classify_interrupt(nfc).cancel_audio
        assert VoiceManager()._strategy_for_text(nfc) == "continue_short"


def test_short_meaningful_user_input_is_not_swallowed_as_backchannel():
    for text in ("ô, sao vậy?", "ai?", "không", "dừng!", "sửa đi"):
        d = classify_interrupt(text)
        assert d.kind != InterruptKind.BACKCHANNEL
        assert d.cancel_generation and d.cancel_audio


def test_preempt_does_not_cancel_generation_for_backchannel():
    from runtime.chat_cycle import ChatCycleMixin

    class Fake(ChatCycleMixin):
        logger = SimpleNamespace(debug=lambda *_: None)

        def __init__(self):
            self.llm_service = SimpleNamespace(cancel_pending_requests=lambda **kw: self.calls.append("llm"))
            self.ai_discovery_runtime = SimpleNamespace(preempt_for_chat=lambda **kw: self.calls.append("discovery"))
            self._supersede_tts_for_new_user_turn = lambda *_: self.calls.append("tts")
            self.calls = []

    host = Fake()
    decision = classify_interrupt("ô")
    host._preempt_for_classified_user_turn(
        cancel_audio=decision.cancel_audio,
        cancel_generation=decision.cancel_generation,
    )
    assert host.calls == []
    host._preempt_for_classified_user_turn(cancel_audio=True, cancel_generation=True)
    assert "llm" in host.calls and "discovery" in host.calls and "tts" in host.calls


def test_cancelled_probe_is_not_a_failure_or_a_success():
    breaker = TtsCircuitBreaker(failure_threshold=1, cooldown_s=1, successful_probes=2)
    key = ("gemini", "tts-model", "voice", "ja-JP")
    breaker.record_failure(key, kind="rate_limit", now=10)
    permit = breaker.allow(key, now=12)
    assert permit.allowed and permit.state == BreakerState.HALF_OPEN
    breaker.record_cancelled(key)
    breaker.record_cancelled(key)  # idempotent cleanup
    assert breaker.state(key) == BreakerState.HALF_OPEN
    assert breaker._entries[key].successful_probes == 0
    assert breaker._entries[key].failures == 1
    # Slot đã nhả; một thử mới có thể đi qua.
    assert breaker.allow(key, now=13).allowed
    breaker.record_success(key)
    assert breaker.state(key) == BreakerState.HALF_OPEN
    assert breaker._entries[key].successful_probes == 1


def test_elevenlabs_five_part_breaker_key_and_metric(monkeypatch):
    import sys
    from runtime import tts_circuit_breaker as mod
    calls = []
    monkeypatch.setitem(sys.modules, "runtime.hardening_metrics", SimpleNamespace(
        record_tts_breaker=lambda **kw: calls.append(kw)
    ))
    breaker = TtsCircuitBreaker(failure_threshold=1, cooldown_s=1)
    key = ("elevenlabs", "account_8", "v3", "voice_x", "ja-JP")
    breaker.record_failure(key, kind="quota", now=10)
    assert breaker.allow(key, now=10.5).allowed is False
    permit = breaker.allow(key, now=12)
    assert permit.state == BreakerState.HALF_OPEN
    breaker.record_cancelled(key)
    assert breaker.allow(key, now=13).allowed
    assert any(c["provider"] == "elevenlabs" and c["locale"] == "ja-JP" for c in calls)


def test_two_concurrent_half_open_slots_are_isolated():
    breaker = TtsCircuitBreaker(failure_threshold=1, cooldown_s=1, successful_probes=2,
                                max_half_open_probes=2)
    key = ("elevenlabs", "account_1", "v3", "voice", "ja-JP")
    breaker.record_failure(key, now=10)
    first = breaker.allow(key, now=12)
    second = breaker.allow(key, now=12)
    assert first.probe_id and second.probe_id and first.probe_id != second.probe_id
    assert not breaker.allow(key, now=12).allowed
    breaker.record_success(key, probe_id=first.probe_id)
    breaker.record_cancelled(key, probe_id=first.probe_id)  # callback muộn, không lấy slot của second
    assert breaker._entries[key].probes_in_flight == 1
    breaker.record_cancelled(key, probe_id=second.probe_id)
    assert breaker._entries[key].probes_in_flight == 0
    third = breaker.allow(key, now=13)
    assert third.allowed and third.probe_id
    breaker.record_failure(key, kind="api_error", probe_id=third.probe_id, now=13)
    assert breaker.state(key) == BreakerState.OPEN
    breaker.record_success(key, probe_id=third.probe_id)  # kết quả đến trễ
    assert breaker.state(key) == BreakerState.OPEN


def test_gemini_synthesis_cancel_does_not_mark_breaker_failed_or_healthy(monkeypatch):
    """Mock broker thật: user chen vào sau khi SDK trả dữ liệu, trước PCM."""
    import contextlib
    import sys
    import threading
    from runtime import tts_engine as engine
    from runtime import inference_broker as broker
    from runtime.tts_engine import TtsCancelledError

    cancel = threading.Event()
    breaker = TtsCircuitBreaker(failure_threshold=1, cooldown_s=1, successful_probes=2)
    key = ("gemini", "tts-model", "voice", "ja-JP")
    breaker.record_failure(key, now=10)
    assert breaker.allow(key, now=12).allowed
    # Giải phóng probe do test mở để lần synth tự xin slot.
    breaker.record_cancelled(key)
    monkeypatch.setattr(engine, "GLOBAL_TTS_BREAKER", breaker)
    monkeypatch.setattr(engine, "_tts_breaker_enabled", lambda: True)
    monkeypatch.setattr(engine, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(engine, "_tts_max_attempts", lambda: 1)
    monkeypatch.setattr(engine, "_try_local_tts_fallback", lambda *_args, **_kw: b"")
    monkeypatch.setattr(engine, "_tts_broker_timeout_seconds", lambda: 5.0)

    # Fake SDK không chạm mạng, broker vẫn chạy đúng cơ chế cấp request.
    class Models:
        def generate_content(self, **kwargs):
            return object()

    fake_genai = SimpleNamespace(Client=lambda **kwargs: SimpleNamespace(models=Models()))
    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kw: kw,
        SpeechConfig=lambda **kw: kw,
        VoiceConfig=lambda **kw: kw,
        PrebuiltVoiceConfig=lambda **kw: kw,
    )
    fake_genai.types = fake_types
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    monkeypatch.setattr(broker.GLOBAL_INFERENCE_BROKER, "request_from_context", lambda **kw: object())
    monkeypatch.setattr(broker.GLOBAL_INFERENCE_BROKER, "run", lambda _req, _call: (cancel.set(), object())[1])
    monkeypatch.setattr(broker, "inference_context", lambda *_a, **_k: contextlib.nullcontext())

    import pytest
    with pytest.raises(TtsCancelledError):
        engine._synthesize_wav("hi", "voice", "tts-model", fallback_text="hi",
                               language_hint="ja", cancel_event=cancel)
    assert breaker.state(key) == BreakerState.HALF_OPEN
    assert breaker._entries[key].failures == 1
    assert breaker._entries[key].probes_in_flight == 0
    assert breaker._entries[key].successful_probes == 0
