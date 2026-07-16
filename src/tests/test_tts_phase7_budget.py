# -*- coding: utf-8 -*-
"""Test budget TTS riêng, segment trước synthesize và health theo lane."""

from __future__ import annotations

import pytest

from runtime.stage_output import SentenceSegmenter
from runtime.tts_budget import TtsRequestBudget
from runtime.tts_engine import _build_tts_prompt
from runtime.tts_key_health import TtsKeyLaneHealth


class _ProviderError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def test_tts_budget_uses_hard_character_limits_not_llm_pressure() -> None:
    budget = TtsRequestBudget(max_transcript_chars=80, max_prompt_chars=500, max_style_chars=120)
    budget.validate(transcript="Một câu ngắn.", prompt="prompt gọn", style_text="dry_tease")
    with pytest.raises(RuntimeError, match="StageOutputPipeline"):
        budget.validate(transcript="x" * 81, prompt="prompt", style_text="")


def test_stage_segmenter_splits_long_vietnamese_before_provider() -> None:
    text = (
        "Được chứ. Tôi hiểu câu trước theo hướng nghiêm túc quá, trong khi bạn chỉ muốn biết một chút thôi; "
        "vậy nên mình sửa đúng ý rồi đi tiếp, không cần dựng thêm bí ẩn nào cả."
    )
    parts = SentenceSegmenter().split(text)
    assert len(parts) >= 2
    assert all(len(part) <= 88 for part in parts)
    assert " ".join(parts).replace("  ", " ")


def test_tts_prompt_is_compact_and_language_pinned() -> None:
    prompt = _build_tts_prompt(
        "Tôi nghe đây.", "[warmly]", "vi",
        prosody_notes="dry_tease; short close",
    )
    assert len(prompt) < 1800
    assert "Vietnamese only" in prompt
    assert "DIRECTOR'S NOTES" not in prompt
    assert "PERFORMANCE SCRIPT" in prompt


def test_403_disables_only_tts_lane_for_that_key() -> None:
    health = TtsKeyLaneHealth()
    kind = health.record_error(2, _ProviderError(403, "PERMISSION_DENIED: API disabled"))
    assert str(kind) == "project_permission"
    assert 2 in health.excluded_indices()
    assert health.snapshot()["2"]["state"] == "permission_denied"


def test_503_is_temporary_not_permanent() -> None:
    health = TtsKeyLaneHealth()
    kind = health.record_error(3, _ProviderError(503, "Service Unavailable"))
    assert str(kind) == "transient_server"
    snap = health.snapshot()["3"]
    assert snap["state"] == "temporarily_unavailable"
    assert snap["disabled_until"] != float("inf")
