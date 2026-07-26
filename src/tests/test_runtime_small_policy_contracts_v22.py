from __future__ import annotations

from types import SimpleNamespace

from runtime.acceptance_types import AcceptanceResult, GateVerdict
from runtime.ambient_silence_policy import (
    ambient_silence_cooldown_seconds,
    muse_directive_active,
    should_hold_ambient_silence,
)
from runtime.cognition.normalization import (
    compact,
    contains_phrase,
    normalize_vi,
    starts_with_phrase,
    token_overlap,
    tokens,
)
from runtime.conversation_lane import classify_conversation_lane
from runtime.settings_protocol import normalize_settings_message


def ns(**kwargs):
    return SimpleNamespace(**kwargs)


def test_acceptance_result_only_accepts_pass() -> None:
    assert AcceptanceResult(GateVerdict.PASS).accepted is True
    for verdict in (GateVerdict.CONSTRAINED_RERUN, GateVerdict.DOMAIN_FALLBACK, GateVerdict.BLOCK):
        assert AcceptanceResult(verdict, reasons=("reason",)).accepted is False


def test_ambient_policy_modes_and_focus() -> None:
    assert muse_directive_active(ns(mode="pattern_muse")) is True
    assert muse_directive_active(ns(mode=None)) is False
    snapshot = ns(active_window_kind="coding")
    assert ambient_silence_cooldown_seconds(snapshot, ns(mode="resource_guard")) == 0
    assert ambient_silence_cooldown_seconds(snapshot, ns(mode="pattern_muse")) == 60
    assert ambient_silence_cooldown_seconds(snapshot, ns(mode="ordinary")) == 60
    assert ambient_silence_cooldown_seconds(ns(active_window_kind="documentation"), ns(mode="ordinary")) == 60
    assert ambient_silence_cooldown_seconds(ns(active_window_kind="communication"), ns(mode="ordinary")) == 40
    assert ambient_silence_cooldown_seconds(ns(active_window_kind="entertainment"), ns(mode="ordinary")) == 50
    assert ambient_silence_cooldown_seconds(ns(active_window_kind="other"), ns(mode="system_watch")) == 50
    assert ambient_silence_cooldown_seconds(ns(active_window_kind="other"), ns(mode="ordinary")) == 40


def test_ambient_hold_exemptions_and_cooldown() -> None:
    snapshot = ns(active_window_kind="other")
    ordinary = ns(mode="ordinary")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ordinary, last_text="x", last_autonomous_spoken_at=90,
        speech_intent="user_requested", now=100,
    ) == (False, "")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ordinary, last_text="", last_autonomous_spoken_at=90, now=100,
    ) == (False, "")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ns(mode="pattern_muse"), last_text="x",
        last_autonomous_spoken_at=90, now=100,
    ) == (False, "muse_exempt")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ns(mode="resource_guard"), last_text="x",
        last_autonomous_spoken_at=90, now=100,
    ) == (False, "")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ordinary, last_text="x", last_autonomous_spoken_at=90, now=100,
    ) == (True, "cooldown=40s")
    assert should_hold_ambient_silence(
        snapshot=snapshot, ti_report=ordinary, last_text="x", last_autonomous_spoken_at=10, now=100,
    ) == (False, "")


def test_conversation_lane_full_and_fast_paths() -> None:
    assert classify_conversation_lane("hãy sửa repo này").reason == "external_or_tool_task"
    assert classify_conversation_lane("chào", ns(response_move="natural_reply", evidence_domain="project")).reason == "evidence_domain:project"
    social = classify_conversation_lane("cảm ơn em", ns(response_move="restrained_warmth", evidence_domain="conversation"))
    assert social.fast is True and social.reason == "social_move:restrained_warmth"
    greeting = classify_conversation_lane("Xin chào")
    assert greeting.fast is True and greeting.reason == "simple_greeting"
    default = classify_conversation_lane("hãy phân tích chuyện này thật kỹ")
    assert default.to_dict() == {"name": "full", "fast": False, "reason": "default_full_reasoning"}


def test_normalization_helpers_cover_boundaries() -> None:
    assert compact(" a   b ") == "a b"
    assert compact("abcdef", 5) == "ab..."
    assert compact("abcdef", 2) == "..."
    assert normalize_vi("ĐỪNG! C# + Python_3.13") == "dung c# + python_3.13"
    assert tokens("C# Python-3.13") == ("c#", "python-3.13")
    assert token_overlap("cờ vua", "Tôi đang chơi cờ") == 0.5
    assert token_overlap("a", "a b") == 0.0
    normalized = normalize_vi("Eris hỗ trợ cờ vua")
    assert contains_phrase(normalized, "cờ vua", "") is True
    assert contains_phrase(normalized, "đánh đàn") is False
    assert starts_with_phrase(normalized, "eris hỗ trợ") is True
    assert starts_with_phrase(normalized, "hỗ trợ") is False


def test_settings_protocol_allows_observability_and_normalizes_payloads() -> None:
    runtime = normalize_settings_message({
        "scope": "runtime",
        "settings": {"observability": {"minimum_ready_ratio": 0.9}, "unknown": 1},
    })
    assert runtime.patch == {"observability": {"minimum_ready_ratio": 0.9}}
    assert runtime.rejected_fields == ("unknown",)

    advanced = normalize_settings_message({
        "scope": "advanced",
        "settings": {"observability": {"maximum_degraded_seconds": 10}},
    })
    assert "observability" in advanced.patch

    personality = normalize_settings_message({
        "scope": "personality", "settings": {"personality": {"warmth": 0.7}, "health": {}},
    })
    assert personality.patch == {"personality": {"warmth": 0.7}}
    assert personality.rejected_fields == ("health",)

    tts = normalize_settings_message({
        "scope": "tts", "tts_enabled": "off", "tts_language": "ja-jp", "tts_voice": "  Aoede  ",
        "tts_quality": " HIGH ", "tts_volume": "bad", "tts_speed": "1.2",
    })
    assert tts.patch["tts"] == {
        "enabled": False, "language": "ja", "voice": "Aoede", "quality": "high", "volume": 1.0, "speed": 1.2,
    }
    assert not tts.restart_required_paths


def test_settings_protocol_legacy_and_missing_payload() -> None:
    legacy = normalize_settings_message({
        "scope": "advanced",
        "advanced_env": {
            "ERIS_NO_FALLBACK_MODE": "1",
            "ERIS_SELF_CRITIQUE_ENABLED": "true",
            "ERIS_CHAT_DIRECTOR_SECOND_PASS": "true",
            "ERIS_LLM_MAX_CONCURRENCY": "3.0",
            "ERIS_AI_STATE_PERSIST_INTERVAL_SEC": "0.75",
            "ERIS_TUTOR_ENABLED": "yes",
            "ERIS_REASONING_EFFORT": "high",
            "ERIS_UNKNOWN": "x",
        },
    })
    assert legacy.legacy_payload is True
    assert legacy.patch["chat"]["auto_fallback"] is False
    assert legacy.patch["chat"]["critique_mode"] == "advisory"
    assert legacy.patch["chat"]["director_second_pass"] == "off"
    assert legacy.patch["chat"]["max_concurrency"] == 3
    assert legacy.patch["ai_runtime"]["state_persistence_interval_seconds"] == 0.75
    assert legacy.patch["tutor"]["enabled"] is True
    assert legacy.patch["chat"]["reasoning_effort"] == "high"
    assert legacy.rejected_fields == ("ERIS_UNKNOWN",)

    malformed_number = normalize_settings_message({
        "scope": "advanced",
        "advanced_env": {"ERIS_LLM_MAX_CONCURRENCY": "many", "ERIS_AI_STATE_PERSIST_INTERVAL_SEC": "later"},
    })
    assert malformed_number.patch["chat"]["max_concurrency"] == "many"
    assert malformed_number.patch["ai_runtime"]["state_persistence_interval_seconds"] == "later"

    missing = normalize_settings_message({"scope": "runtime"})
    assert missing.patch == {}
    assert missing.rejected_fields == ("missing_settings_payload",)
