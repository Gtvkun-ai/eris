# -*- coding: utf-8 -*-
"""Hồi quy lời mở đầu: có cá tính nhưng không dựng tiền đề ảo."""

from __future__ import annotations

from cortex.greeting_cognition import GreetingCognitionEngine
from cortex.greeting_presets import GREETING_PRESETS, GreetingPresetResolver
from cortex.greeting_quality import GreetingQualityScorer
from cortex.startup_anchor_gate import StartupAnchorGate


def _frame(**kwargs):
    return GreetingCognitionEngine().build(**kwargs)


def test_low_evidence_rejects_hollow_hardest_part_opening() -> None:
    verdict = StartupAnchorGate().validate(
        "Vào việc thôi bạn, giao tôi phần khó nhất đi.",
        _frame(),
    )
    assert verdict.accepted is False
    assert "task_without_anchor" in verdict.unsupported_presuppositions
    assert "difficulty_without_anchor" in verdict.unsupported_presuppositions


def test_low_evidence_rejects_fake_mischief_premise() -> None:
    verdict = StartupAnchorGate().validate(
        "Eris đã online. Phần còn lại tùy bạn gây chuyện.",
        _frame(),
    )
    assert verdict.accepted is False
    assert "user_behaviour_without_event" in verdict.unsupported_presuppositions


def test_low_evidence_accepts_personality_from_self_attitude() -> None:
    frame = _frame()
    lines = (
        "Tôi lên rồi. Chưa biết hôm nay có gì, nên tôi chưa phán.",
        "Eris online. Tôi chưa hứa sẽ ngoan.",
        "Tôi lên rồi. Phần khó thì chưa thấy, thái độ thì có sẵn.",
    )
    for line in lines:
        verdict = StartupAnchorGate().validate(line, frame)
        assert verdict.accepted, (line, verdict.unsupported_presuppositions)
        assert verdict.challenge_answer


def test_task_anchor_allows_concrete_resume_but_not_unranked_hardest_part() -> None:
    frame = _frame(
        active_goal="sửa TTS parser",
        continuity_restored=True,
    )
    assert StartupAnchorGate().validate("Vào việc thôi. TTS parser còn dang dở.", frame).accepted

    vague_rank = StartupAnchorGate().validate("Giao tôi phần khó nhất đi.", frame)
    assert vague_rank.accepted is False
    assert "difficulty_without_anchor" in vague_rank.unsupported_presuppositions


def test_explicit_difficulty_anchor_can_support_hard_part_reference() -> None:
    frame = _frame(
        active_goal="blocker khó nhất: Gemini TTS không trả audio parts",
        continuity_restored=True,
    )
    verdict = StartupAnchorGate().validate("Phần khó nhất vẫn là TTS không trả audio.", frame)
    assert verdict.accepted
    assert "difficulty_anchor" in verdict.anchor_ids


def test_quality_scorer_heavily_penalizes_unsupported_presupposition() -> None:
    frame = _frame()
    scorer = GreetingQualityScorer()
    bad = scorer.score("Đúng giờ đấy. Giao tôi phần khó nhất đi.", frame)
    good = scorer.score("Eris online. Tôi chưa hứa sẽ ngoan.", frame)
    assert bad.accepted is False
    assert bad.unsupported_presupposition == 1.0
    assert "unsupported_presupposition" in bad.reasons
    assert good.accepted is True
    assert good.score > bad.score


def test_all_catalog_presets_are_anchorable_in_their_intended_context() -> None:
    gate = StartupAnchorGate()
    for preset in GREETING_PRESETS:
        if "quick_reopen" in preset.tags:
            frame = _frame(presence_restored=True, seconds_since_last_session=60)
        elif "long_absence" in preset.tags:
            frame = _frame(presence_restored=True, seconds_since_last_session=8 * 3600)
        elif "restart" in preset.tags:
            frame = _frame(presence_restored=True, restart_detected=True)
        elif "overloaded" in preset.tags:
            frame = _frame(tone="overloaded")
        elif "low_evidence_start" in preset.situations:
            frame = _frame()
        else:
            frame = _frame(presence_restored=True)
        verdict = gate.validate(preset.text, frame)
        assert verdict.accepted, (preset.id, preset.text, verdict.unsupported_presuppositions)


def test_resolver_never_returns_unanchored_custom_preset() -> None:
    # Dùng catalog thật để xác nhận resolver và gate cùng chạy; lặp nhiều lần vì
    # resolver dùng weighted random.
    resolver = GreetingPresetResolver()
    frame = _frame()
    gate = StartupAnchorGate()
    for _ in range(40):
        preset = resolver.resolve_or_default(frame, tone="quiet_background", force=True)
        assert preset is not None
        assert gate.validate(preset.text, frame).accepted
