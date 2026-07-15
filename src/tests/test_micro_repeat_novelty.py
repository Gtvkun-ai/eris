# -*- coding: utf-8 -*-
"""Tests for the continuous novelty score (penalty, not veto)."""

from cortex.micro_repeat_guard import SemanticRepeatGuard


def test_fresh_line_scores_high():
    guard = SemanticRepeatGuard()
    score = guard.novelty_score(
        "Ngài vừa đổi sang file khác à.",
        recent_lines=("Tôi nhớ hôm qua Ngài bỏ dở cái hàm parser.",),
    )
    assert score > 0.5


def test_exact_repeat_of_recent_scores_low():
    guard = SemanticRepeatGuard()
    line = "Tôi vẫn đang quan sát thôi."
    score = guard.novelty_score(line, recent_lines=(line,))
    assert score < 0.1


def test_banned_filler_variant_is_penalized():
    # "Tôi ở đây." nằm trong BANNED_FILLER_LINES; câu gần y hệt phải bị phạt
    # qua lexical fallback dù không khớp chuỗi chính xác.
    guard = SemanticRepeatGuard()
    fresh = guard.novelty_score("Cái biểu đồ này lệch trục rồi.")
    stale = guard.novelty_score("Tôi ở đây.")
    assert stale < fresh


def test_empty_text_is_max_novelty():
    guard = SemanticRepeatGuard()
    assert guard.novelty_score("") == 1.0
    assert guard.novelty_score("   ") == 1.0


def test_no_references_means_novel():
    guard = SemanticRepeatGuard()
    score = guard.novelty_score("Một câu hoàn toàn mới mẻ.", include_banned_seed=False)
    assert score == 1.0


def test_score_is_bounded():
    guard = SemanticRepeatGuard()
    for text in ("a", "Tôi ở đây.", "Ngài quay lại rồi.", "x y z foo bar"):
        score = guard.novelty_score(text)
        assert 0.0 <= score <= 1.0
