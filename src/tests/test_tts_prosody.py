from __future__ import annotations

from runtime.prosody_director import ProsodyDirector
from runtime.tts_engine import _build_tts_prompt
from runtime.tts_markup import render_tts_markup


def test_prosody_director_detects_dry_tease():
    plan = ProsodyDirector().plan("bạn lại phá gì rồi?", valence=0.0, arousal=0.35)

    assert plan.style == "dry_tease"
    assert "teasing" in plan.opening_tag
    assert plan.emphasis_mode == "last_phrase"


def test_tts_markup_adds_tag_and_light_pause_for_tease():
    plan = ProsodyDirector().plan("bạn lại phá gì rồi?", valence=0.0, arousal=0.35)
    marked = render_tts_markup("bạn lại phá gì rồi?", plan)

    assert marked.startswith("[dryly, teasing")
    assert "…" in marked
    assert "bạn" in marked


def test_tts_prompt_prelocalized_japanese_does_not_translate_again():
    prompt = _build_tts_prompt(
        "[dryly, teasing, slightly slow] また……何を壊したんですか。",
        "",
        "ja",
        prosody_notes="Dry teasing. Emphasize the last phrase lightly.",
        prelocalized=True,
    )

    assert "already in Japanese" in prompt
    assert "Translate the transcript" not in prompt
    assert "Line performance:" in prompt
