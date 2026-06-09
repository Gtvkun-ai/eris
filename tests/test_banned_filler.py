from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.banned_filler import (
    BANNED_FILLER_LINES,
    HOLLOW_PRESENCE_LINES,
    STALE_MICRO_TEMPLATES,
    is_banned_filler,
    normalize_banned,
    quoted_fragment,
)


def test_canonical_lines_are_all_banned() -> None:
    for line in BANNED_FILLER_LINES:
        assert is_banned_filler(line), line


def test_match_is_case_and_whitespace_insensitive() -> None:
    assert is_banned_filler("khoảng yên này vẫn giữ chỗ.")
    assert is_banned_filler("  Khoảng   yên này vẫn giữ chỗ  ")
    assert is_banned_filler("KHOẢNG YÊN NÀY VẪN GIỮ CHỖ")


def test_match_ignores_trailing_punctuation() -> None:
    # Prompt lists "Tôi ở đây" without a period; output may add one.
    assert is_banned_filler("Tôi ở đây")
    assert is_banned_filler("Tôi ở đây.")
    assert is_banned_filler("Tôi ở đây…")


def test_non_banned_line_passes() -> None:
    assert not is_banned_filler("Cái panel Execution Changes kia vẫn mở năm file.")
    assert not is_banned_filler("")
    assert not is_banned_filler("   ")


def test_normalize_banned_collapses_and_casefolds() -> None:
    assert normalize_banned("  Tôi   Ở Đây.  ") == normalize_banned("tôi ở đây")


def test_quoted_fragment_renders_without_trailing_periods() -> None:
    fragment = quoted_fragment(HOLLOW_PRESENCE_LINES)
    assert "'Tôi ở đây'" in fragment
    assert "'Tôi ở đây.'" not in fragment
    assert fragment.count("'") == len(HOLLOW_PRESENCE_LINES) * 2


def test_banned_set_is_union_of_groups() -> None:
    assert set(BANNED_FILLER_LINES) == set(HOLLOW_PRESENCE_LINES) | set(STALE_MICRO_TEMPLATES)


def test_single_source_of_truth_reflected_in_prompt_and_filter() -> None:
    # Any line the prompt is told to avoid must also be enforced by the filter.
    for line in (*HOLLOW_PRESENCE_LINES, *STALE_MICRO_TEMPLATES):
        assert is_banned_filler(line)
        bare = line.rstrip(". ")
        assert f"'{bare}'" in quoted_fragment((line,))
