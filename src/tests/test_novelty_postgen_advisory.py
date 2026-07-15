# -*- coding: utf-8 -*-
"""Đề xuất 2: novelty post-generation advisory (mặc định chỉ-log)."""

import os

import pytest

from domain import Decision
from runtime.post_generation_filters import PostGenerationFiltersMixin
from cortex.micro_repeat_guard import SemanticRepeatGuard


class _Host(PostGenerationFiltersMixin):
    def __init__(self, recent):
        self._recent = tuple(recent)
        self._guard = SemanticRepeatGuard()

    def _get_novelty_guard(self):
        return self._guard

    def _recent_spoken_texts(self, *, limit: int = 6):
        return self._recent[:limit]


def _decision(text: str) -> Decision:
    return Decision(text=text, animation="stand", should_speak=True, confidence=0.7)


@pytest.fixture(autouse=True)
def _clear_env():
    for key in ("ERIS_NOVELTY_POSTGEN_MODE", "ERIS_NOVELTY_POSTGEN_THRESHOLD"):
        os.environ.pop(key, None)
    yield
    for key in ("ERIS_NOVELTY_POSTGEN_MODE", "ERIS_NOVELTY_POSTGEN_THRESHOLD"):
        os.environ.pop(key, None)


def test_log_mode_default_never_changes_decision():
    host = _Host(recent=("Tôi vẫn ở đây.",))
    d = _decision("Tôi ở đây.")  # gần như lặp
    out = host._apply_novelty_advisory(d, channel="autonomous")
    # Mặc định = log: text/should_speak không đổi, chỉ thêm trace.
    assert out.text == "Tôi ở đây."
    assert out.should_speak is True
    assert "novelty_postgen=" in out.debug_trace


def test_off_mode_no_trace():
    os.environ["ERIS_NOVELTY_POSTGEN_MODE"] = "off"
    host = _Host(recent=("Tôi ở đây.",))
    out = host._apply_novelty_advisory(_decision("Tôi ở đây."), channel="autonomous")
    assert "novelty_postgen=" not in (out.debug_trace or "")


def test_enforce_penalizes_stale_line_confidence():
    os.environ["ERIS_NOVELTY_POSTGEN_MODE"] = "enforce"
    host = _Host(recent=("Tôi vẫn ở đây.",))
    out = host._apply_novelty_advisory(_decision("Tôi ở đây."), channel="chat")
    # Lặp → hạ confidence; nhưng chat KHÔNG bao giờ bị mute.
    assert out.confidence <= 0.40
    assert out.should_speak is True
    assert "stale_penalty" in out.debug_trace


def test_enforce_keeps_fresh_line_untouched():
    os.environ["ERIS_NOVELTY_POSTGEN_MODE"] = "enforce"
    host = _Host(recent=("Tôi ở đây.",))
    fresh = _decision("Cái build Godot vừa fail ở bước biên dịch shader đó.")
    out = host._apply_novelty_advisory(fresh, channel="chat")
    assert out.confidence == pytest.approx(0.7)
    assert out.should_speak is True


def test_enforce_non_chat_near_identical_degrades_to_body_only():
    os.environ["ERIS_NOVELTY_POSTGEN_MODE"] = "enforce"
    line = "Tôi vẫn đang quan sát thôi."
    host = _Host(recent=(line,))
    out = host._apply_novelty_advisory(_decision(line), channel="autonomous")
    # Gần như lặp y hệt + không phải chat → im.
    assert out.should_speak is False
    assert out.text == ""
    assert out.parse_mode == "novelty_body_only"


def test_empty_or_silent_decision_untouched():
    host = _Host(recent=("x",))
    silent = Decision(text="", animation="stand", should_speak=False)
    out = host._apply_novelty_advisory(silent, channel="autonomous")
    assert out is silent
