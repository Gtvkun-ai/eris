# -*- coding: utf-8 -*-
"""Hồi quy cho stance trực tiếp và catalog greeting đời thường."""

from types import SimpleNamespace

from cortex.greeting_presets import GREETING_PRESETS, greeting_preset_speech_text
from runtime.greeting_preset_runtime import decision_from_session_ritual
from runtime.stage_contracts import StageFrameBuilder
from runtime.social_stance_policy import (
    build_direct_stance_text,
    guard_subjective_stance_payload,
    needs_direct_stance_rewrite,
)


def _axis(value: float) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _snapshot(*, playful: float = 0.0, affection: float = 0.0, irritation: float = 0.0, engagement: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        playful=_axis(playful),
        affection=_axis(affection),
        irritation=_axis(irritation),
        engagement=_axis(engagement),
        thresholds=SimpleNamespace(playful_repair=0.58, irritation_high=0.62),
    )


def test_stance_policy_refuses_directly_before_adding_warmth() -> None:
    text = build_direct_stance_text(_snapshot(affection=0.55, engagement=0.70), contrast="không phải")

    assert text.startswith("Không. Tôi vẫn nghĩ vậy.")
    assert "không định ép" in text
    assert "ấn tượng ban đầu" not in text
    assert "cách đọc" not in text


def test_stance_policy_keeps_playful_refusal_short() -> None:
    text = build_direct_stance_text(_snapshot(playful=0.80))

    assert text == "Không đâu. Tôi vẫn nghĩ mình đọc đúng."


def test_stance_guard_rewrites_ai_mediation_language_without_touching_frame() -> None:
    frame = {
        "version": "semantic_frame.v1",
        "user_act": "disagreement",
        "discourse_relation": "contest_assistant_impression",
    }
    payload = {
        "semantic_frame": frame,
        "text": "Tôi hiểu bạn không nhìn nó như vậy. Nhưng tôi vẫn giữ ấn tượng ban đầu.",
        "performance_hint": "repair",
    }

    guarded = guard_subjective_stance_payload(payload)

    assert guarded["semantic_frame"] == frame
    assert guarded["text"] == "Không. Tôi vẫn nghĩ vậy."
    assert guarded["performance_hint"] == "soft_warm"


def test_stance_guard_detects_both_capitulation_and_policy_speak() -> None:
    assert needs_direct_stance_rewrite("Xin lỗi, tôi hiểu sai rồi.") is True
    assert needs_direct_stance_rewrite("Tôi vẫn giữ ấn tượng ban đầu, chỉ không coi nó là sự thật về bạn.") is True
    assert needs_direct_stance_rewrite("Không. Tôi vẫn nghĩ vậy.") is False
    assert needs_direct_stance_rewrite("Bạn không thấy thế, nhưng tôi vẫn nghĩ vậy.") is True


def test_greeting_catalog_has_32_natural_lines_and_forces_live_tts() -> None:
    assert len(GREETING_PRESETS) == 32
    banned = ("Eris online", "runtime", "dữ kiện", "ghi nhận", "sai nhịp", "lệch nhịp")

    for preset in GREETING_PRESETS:
        assert preset.text.strip()
        assert greeting_preset_speech_text(preset.id, language="ja").strip()
        assert not any(marker.casefold() in preset.text.casefold() for marker in banned)
        # Chữ đã đổi nên WAV cũ không được phép đọc lệch subtitle.
        assert preset.audio_asset == ""


def test_startup_greeting_preset_commits_japanese_speech_surface(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_TTS_LANGUAGE", "ja")
    preset = next(item for item in GREETING_PRESETS if item.id == "greet_quiet_02")
    report = SimpleNamespace(
        greeting_preset_id=preset.id,
        greeting_preset_text=preset.text,
        greeting_preset_prosody=preset.prosody_style,
        greeting_preset_motion=preset.motion,
        greeting_preset_emotion=preset.emotion,
        greeting_audio_asset="",
        tone="quiet_background",
        greeting_frame=None,
    )

    decision = decision_from_session_ritual(report)
    assert decision is not None
    assert decision.display_language == "vi"
    assert decision.speech_language == "ja"
    assert decision.speech_text == "来たね。聞いているよ。"

    frame = StageFrameBuilder(language_hint="ja").build(
        decision,
        payload=decision.to_payload(),
        channel="session_ritual",
    )

    assert frame.display_text == decision.text
    assert frame.tts_text == decision.speech_text
    assert frame.speech_contract["language"] == "ja"
    assert frame.speech_contract["prelocalized"] is True
