# -*- coding: utf-8 -*-
"""Test AppetiteSystem: đói đi săn mồi; nội dung khác → phản ứng khác; yan cực đoan."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.appetite_system import (
    AppetiteSystem,
    build_evidence_buffet,
)


def _sys():
    return AppetiteSystem()


def test_buffet_tags_video_vs_shortform_vs_game():
    yt = build_evidence_buffet(content_kind="youtube_video", content_title="Rust Tier List")
    tt = build_evidence_buffet(content_kind="tiktok_video", content_title="foryou")
    gm = build_evidence_buffet(active_window="ELDEN RING")
    assert any("video" in i.tags for i in yt)
    assert any("shortform_scroll" in i.tags for i in tt)
    assert any("game" in i.tags for i in gm)


def test_curiosity_wins_on_fresh_video():
    s = _sys()
    states = s.new_states()
    states["curiosity"].pressure = 0.8
    ev = build_evidence_buffet(content_kind="youtube_video", content_title="Cách build nhà gỗ", novelty=0.9)
    states, reaction = s.update(states, now=1.0, signals={"curiosity": 0.8}, evidence=ev)
    assert reaction is not None
    assert reaction.appetite == "curiosity"
    assert "Cách build" in reaction.seed
    assert reaction.allow_pretext is False


def test_mischief_wins_on_doomscroll():
    s = _sys()
    states = s.new_states()
    states["mischief"].pressure = 0.85
    ev = build_evidence_buffet(content_kind="tiktok_video", content_title="foryou")
    states, reaction = s.update(states, now=1.0, signals={"mischief": 0.85}, evidence=ev)
    assert reaction is not None
    assert reaction.appetite == "mischief"


def test_loneliness_brings_own_pretext_on_blank_screen():
    s = _sys()
    states = s.new_states()
    states["loneliness"].pressure = 0.9
    ev = build_evidence_buffet(idle_seconds=600.0)  # màn hình trống → idle_blank
    states, reaction = s.update(states, now=1.0, signals={"loneliness": 0.9}, evidence=ev)
    assert reaction is not None
    assert reaction.appetite == "loneliness"
    # Có cớ tự mang khi không có món cụ thể.
    assert reaction.allow_pretext is True or reaction.seed == ""


def test_dignity_blocks_in_normal_mode_when_threat_high():
    s = _sys()
    states = s.new_states()
    states["loneliness"].pressure = 0.95
    ev = build_evidence_buffet(idle_seconds=600.0)
    states, reaction = s.update(states, now=1.0, signals={"loneliness": 0.95}, evidence=ev, threat=0.8)
    assert reaction is None  # cô độc nhưng phẩm giá thắng


def test_yan_overrides_dignity_and_amplifies():
    s = _sys()
    states = s.new_states()
    ev = build_evidence_buffet(idle_seconds=600.0)
    states, reaction = s.update(
        states, now=1.0, signals={"loneliness": 0.2}, evidence=ev, threat=0.95, yan_mode=True
    )
    assert reaction is not None
    assert reaction.mode == "yan"
    assert reaction.override_dignity is True
    assert reaction.intensity >= 0.8


def test_feeding_decays_winner_pressure():
    s = _sys()
    states = s.new_states()
    states["curiosity"].pressure = 0.9
    ev = build_evidence_buffet(content_kind="youtube_video", content_title="abc", novelty=0.9)
    new_states, reaction = s.update(states, now=5.0, signals={"curiosity": 0.0}, evidence=ev)
    assert reaction is not None and reaction.appetite == "curiosity"
    assert new_states["curiosity"].pressure < 0.9
    assert new_states["curiosity"].last_fed_at == 5.0


def test_different_content_yields_different_appetite_lens():
    s = _sys()
    base = s.new_states()
    for a in base.values():
        a.pressure = 0.7
    sig = {k: 0.7 for k in base}
    _, r_video = s.update(dict(base), now=1.0, signals=sig,
                          evidence=build_evidence_buffet(content_kind="youtube_video", content_title="doc phim", novelty=0.9))
    _, r_scroll = s.update(dict(base), now=1.0, signals=sig,
                           evidence=build_evidence_buffet(content_kind="tiktok_video", content_title="foryou", novelty=0.9))
    # Video kéo curiosity, doomscroll kéo mischief → lens khác nhau.
    assert r_video is not None and r_scroll is not None
    assert r_video.lens != r_scroll.lens
