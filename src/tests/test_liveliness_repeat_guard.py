from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.micro_repeat_guard import SemanticRepeatGuard


def test_default_exact_window_covers_max_idle_interval() -> None:
    guard = SemanticRepeatGuard()
    # Idle cycles are up to 120s apart; the exact-repeat window must cover that.
    assert guard.exact_repeat_seconds >= 120.0
    assert guard.window_seconds >= guard.exact_repeat_seconds


def test_identical_line_rejected_across_100s_gap() -> None:
    guard = SemanticRepeatGuard()
    guard.remember("Khoảng yên này vẫn giữ chỗ.", timestamp=1000.0)
    result = guard.check("Khoảng yên này vẫn giữ chỗ.", now=1100.0)
    assert result.rejected is True
    assert result.reason == "exact_micro_line_repeat"
    assert result.fingerprint


def test_explicit_args_still_override_config() -> None:
    guard = SemanticRepeatGuard(window_seconds=300.0, exact_repeat_seconds=200.0, semantic_threshold=0.6)
    assert guard.window_seconds == 300.0
    assert guard.exact_repeat_seconds == 200.0
    assert guard.semantic_threshold == 0.6


def test_repeat_window_floor_applies_from_bad_config(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_LIVELINESS_REPEAT_WINDOW_SEC", "10")  # below max idle
    guard = SemanticRepeatGuard()
    # config clamps to >= 120, so exact window still covers the idle interval.
    assert guard.exact_repeat_seconds >= 120.0
