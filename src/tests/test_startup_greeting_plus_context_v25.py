from __future__ import annotations

from types import SimpleNamespace

from runtime.ai_orchestrated.startup_grounding import (
    ensure_startup_greeting_payload,
    ensure_startup_greeting_text,
    startup_text_has_greeting,
)


def test_contextual_startup_gets_greeting_without_losing_question() -> None:
    text, inserted = ensure_startup_greeting_text(
        "Hôm nay anh xem Facebook khá tập trung nhỉ? Có gì đáng chú ý không?",
        language="vi",
        user_vocative="anh",
        frame=SimpleNamespace(situation="plain_return"),
    )

    assert inserted is True
    assert text == "Chào anh. Hôm nay anh xem Facebook khá tập trung nhỉ? Có gì đáng chú ý không?"


def test_natural_arrival_acknowledgement_is_not_duplicated() -> None:
    text, inserted = ensure_startup_greeting_text(
        "Anh vào rồi à. Hôm nay xem gì thế?",
        language="vi",
        user_vocative="anh",
        frame=SimpleNamespace(situation="plain_return"),
    )

    assert inserted is False
    assert text == "Anh vào rồi à. Hôm nay xem gì thế?"
    assert startup_text_has_greeting(text, language="vi") is True


def test_payload_preserves_social_plan_and_greets_both_surfaces() -> None:
    social_plan = {
        "afterbeat": {"decision": "none"},
        "exposure": {"decision": "none"},
        "agenda_update": {"decision": "none"},
        "conversation_arc": {
            "decision": "schedule",
            "goal": "Return once to the Facebook question if the user stays silent.",
            "beats": [],
            "confidence": 0.8,
        },
    }
    payload = {
        "text": "Hôm nay anh xem Facebook khá tập trung nhỉ? Có gì đáng chú ý không?",
        "display_language": "vi",
        "speech_text": "今日はフェイスブックをかなり集中して見てるね。何か気になることでもある？",
        "speech_language": "ja",
        "utterance": {
            "display": {
                "language": "vi",
                "text": "Hôm nay anh xem Facebook khá tập trung nhỉ? Có gì đáng chú ý không?",
            },
            "speech": {
                "language": "ja",
                "text": "今日はフェイスブックをかなり集中して見てるね。何か気になることでもある？",
            },
        },
        "social_plan": social_plan,
    }

    result = ensure_startup_greeting_payload(
        payload,
        frame=SimpleNamespace(situation="plain_return"),
        display_language="vi",
        speech_language="ja",
        user_vocative="anh",
    )

    assert result["text"].startswith("Chào anh. ")
    assert result["speech_text"].startswith("こんにちは。")
    assert result["social_plan"] is social_plan
    assert result["startup_greeting_nonbinding"] is True
    assert result["startup_context_may_expect_reply"] is True


def test_existing_bilingual_greetings_are_not_duplicated() -> None:
    payload = {
        "text": "Chào anh. Hôm nay xem gì thế?",
        "display_language": "vi",
        "speech_text": "こんにちは。今日は何を見てるの？",
        "speech_language": "ja",
    }

    result = ensure_startup_greeting_payload(
        payload,
        frame=SimpleNamespace(situation="plain_return"),
        display_language="vi",
        speech_language="ja",
        user_vocative="anh",
    )

    assert result["text"] == payload["text"]
    assert result["speech_text"] == payload["speech_text"]
    assert result["startup_greeting_inserted"] is False
