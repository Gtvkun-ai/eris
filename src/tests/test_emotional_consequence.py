# -*- coding: utf-8 -*-
"""Tests cho Nước 1 — van bước-cuối (emotional consequence).

Phủ:
  - helper xác định trong cortex.emotional_consequence;
  - appraisal.render_prompt_context đổi disclaimer khi cờ bật, giữ nguyên khi tắt;
  - personality.render_prompt_context gỡ blacklist cảm xúc khi bật, giữ khi tắt;
  - _apply_emotional_consequence_filter: nở câu phẳng, KHÔNG bao giờ câm/rút ngắn.
"""

from __future__ import annotations

import logging

import pytest

from cortex import emotional_consequence as ec


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("ERIS_EMOTIONAL_CONSEQUENCE", raising=False)
    yield


# ---------------------------------------------------------------------------
# Helpers xác định
# ---------------------------------------------------------------------------
def test_flag_default_off():
    assert ec.emotional_consequence_enabled() is False


def test_flag_on(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    assert ec.emotional_consequence_enabled() is True


def test_min_words_below_threshold_is_zero():
    assert ec.min_words_for_expression(0.0) == 0
    assert ec.min_words_for_expression(0.44) == 0


def test_min_words_grows_with_expression():
    low = ec.min_words_for_expression(0.45)
    high = ec.min_words_for_expression(1.0)
    assert 0 < low < high
    assert high >= 15


def test_surface_flattened_only_when_wanted_and_short():
    # muốn nói mạnh + câu cụt -> phẳng
    assert ec.surface_is_flattened("Ừ.", allowed_expression=0.9, want_to_say=0.9) is True
    # câu đủ dài -> không phẳng
    long_line = " ".join(["từ"] * 20)
    assert ec.surface_is_flattened(long_line, allowed_expression=0.9, want_to_say=0.9) is False
    # không muốn nói -> không ép dài
    assert ec.surface_is_flattened("Ừ.", allowed_expression=0.9, want_to_say=0.1) is False
    # biểu đạt thấp -> kìm nén hợp lệ, không phẳng
    assert ec.surface_is_flattened("Ừ.", allowed_expression=0.2, want_to_say=0.2) is False
    # im lặng không phải phẳng
    assert ec.surface_is_flattened("", allowed_expression=0.9, want_to_say=0.9) is False


# ---------------------------------------------------------------------------
# appraisal prompt-side
# ---------------------------------------------------------------------------
def _make_appraisal():
    from cortex.appraisal import AppraisalEngine
    from cortex.contracts import CognitiveAppraisal

    appraisal = CognitiveAppraisal(stance="tender_under_cold")
    return AppraisalEngine(), appraisal


def test_appraisal_keeps_disclaimer_when_off():
    engine, appraisal = _make_appraisal()
    ctx = engine.render_prompt_context(appraisal)
    assert "not an inner feeling claim" in ctx


def test_appraisal_swaps_disclaimer_when_on(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    engine, appraisal = _make_appraisal()
    ctx = engine.render_prompt_context(appraisal)
    assert "not an inner feeling claim" not in ctx
    assert "CẢM được thật" in ctx
    # vẫn giữ trục/stance
    assert "appraisal_stance:" in ctx
    assert "appraisal_axes:" in ctx


# ---------------------------------------------------------------------------
# personality prompt-side
# ---------------------------------------------------------------------------
def _make_lens_result():
    from cortex.personality import PersonalityLens
    from cortex.contracts import PersonalityLensResult

    result = PersonalityLensResult(
        profile="INFJ_5w4_594",
        interpretation="emotional_undertone",
        stance="tender_under_cold",
        emotional_coloring="warm_under_cool",
        social_distance="near_guarded",
        want_to_say=0.7,
        allowed_expression=0.55,
        suppression_pressure=0.4,
        restraint_mode="leak",
    )
    return PersonalityLens(), result


def test_personality_keeps_emotional_bans_when_off():
    lens, result = _make_lens_result()
    ctx = lens.render_prompt_context(result)
    # blacklist cảm xúc vẫn hiện diện khi tắt
    assert "toi co don" in ctx
    assert "residue, wound, void" in ctx


def test_personality_drops_emotional_bans_when_on(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    lens, result = _make_lens_result()
    ctx = lens.render_prompt_context(result)
    # các ban cảm xúc bị gỡ
    assert "toi co don" not in ctx
    assert "residue, wound, void" not in ctx
    # nhưng ban claim-sai (màn hình/quan sát) vẫn giữ
    assert "tôi thấy màn hình" in ctx


# ---------------------------------------------------------------------------
# Post-generation filter — van chỉ MỞ, không câm
# ---------------------------------------------------------------------------
class _FakeService:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def rewrite_for_felt_expression(self, **kwargs):
        self.calls += 1
        return self.reply


def _make_harness(service, gate):
    from runtime.post_generation_filters import PostGenerationFiltersMixin

    class _Harness(PostGenerationFiltersMixin):
        pass

    h = _Harness()
    h.llm_service = service
    h._last_expression_gate = gate
    h.logger = logging.getLogger("test_ec")
    return h


def _decision(text: str):
    from domain import Decision

    return Decision(text=text, animation="stand", should_speak=True, intent="chat", parse_mode="chat")


def _gate(allowed=0.9, want=0.9, stance="tender_under_cold"):
    return {
        "allowed_expression": allowed,
        "want_to_say": want,
        "suppression_pressure": 0.3,
        "stance": stance,
    }


def test_filter_noop_when_flag_off():
    svc = _FakeService("một câu dài hơn nhiều để nở ra rõ ràng đây")
    h = _make_harness(svc, _gate())
    dec = _decision("Ừ.")
    out = h._apply_emotional_consequence_filter(dec, channel="chat")
    assert out.text == "Ừ."
    assert svc.calls == 0


def test_filter_expands_flat_line_when_on(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    expanded = "Ừ, tôi nghe rồi — chỉ là chưa biết nói gì cho đúng lúc này thôi."
    svc = _FakeService(expanded)
    h = _make_harness(svc, _gate())
    dec = _decision("Ừ.")
    out = h._apply_emotional_consequence_filter(dec, channel="chat")
    assert out.text == expanded
    assert svc.calls == 1
    assert out.should_speak is True


def test_filter_keeps_original_when_reroll_shorter(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    svc = _FakeService("Ngắn.")  # ngắn hơn -> không nhận
    h = _make_harness(svc, _gate())
    dec = _decision("Ừ.")
    out = h._apply_emotional_consequence_filter(dec, channel="chat")
    assert out.text == "Ừ."  # giữ nguyên, không câm


def test_filter_never_runs_on_non_flat(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    svc = _FakeService("không nên gọi")
    h = _make_harness(svc, _gate())
    long_line = " ".join(["từ"] * 20)
    dec = _decision(long_line)
    out = h._apply_emotional_consequence_filter(dec, channel="chat")
    assert out.text == long_line
    assert svc.calls == 0


def test_filter_skips_autonomous_channel(monkeypatch):
    monkeypatch.setenv("ERIS_EMOTIONAL_CONSEQUENCE", "1")
    svc = _FakeService("một câu dài hơn nhiều để nở ra rõ ràng đây")
    h = _make_harness(svc, _gate())
    dec = _decision("Ừ.")
    out = h._apply_emotional_consequence_filter(dec, channel="autonomous")
    assert out.text == "Ừ."
    assert svc.calls == 0
