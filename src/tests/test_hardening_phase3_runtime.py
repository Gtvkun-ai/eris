# -*- coding: utf-8 -*-
"""Hồi quy cho hardening phase 3 theo báo cáo kiến trúc."""

from __future__ import annotations

from types import SimpleNamespace

from llm.token_pressure import TokenPressureGovernor, lane_budget_for
from runtime.public_surface_commit import PublicSurfaceCommitter
from runtime.semantic_equivalence_gate import SemanticEquivalenceGate
from runtime.semantic_similarity_backend import MultilingualSemanticSimilarity
from runtime.stage_output import SentenceSegmenter


def test_semantic_backend_uses_deterministic_local_fallback_without_network():
    backend = MultilingualSemanticSimilarity(mode="fallback")
    close = backend.score(
        "Tôi chưa có bằng chứng hiện tại để khẳng định điều đó.",
        "Hiện tôi chưa đủ bằng chứng để khẳng định điều đó.",
    )
    far = backend.score(
        "Tôi chưa có bằng chứng hiện tại để khẳng định điều đó.",
        "Hôm nay trời có vẻ rất đẹp.",
    )
    assert close.backend == "char_ngram_fallback"
    assert close.degraded is True
    assert close.score > far.score
    assert close.score > 0.70


def test_semantic_gate_surfaces_backend_quality_in_result():
    gate = SemanticEquivalenceGate(
        semantic_backend=MultilingualSemanticSimilarity(mode="fallback")
    )
    result = gate.evaluate(
        "Tôi chưa có bằng chứng hiện tại để khẳng định điều đó.",
        "Hiện tôi chưa đủ bằng chứng để khẳng định điều đó.",
        intent="factual",
    )
    assert result.accepted is True
    assert result.backend == "char_ngram_fallback"
    assert result.degraded is True


def test_semantic_gate_prefers_real_backend_score_when_available():
    class _Backend:
        def score(self, _left: str, _right: str):
            return SimpleNamespace(score=0.95, backend="fake_multilingual", degraded=False)

    gate = SemanticEquivalenceGate(semantic_backend=_Backend())
    result = gate.evaluate(
        "Không đủ bằng chứng để kết luận.",
        "Dữ kiện hiện có vẫn chưa cho phép kết luận chắc chắn.",
        intent="factual",
    )
    assert result.accepted is True
    assert result.backend == "fake_multilingual"
    assert result.degraded is False


def test_lane_budget_caps_optional_director_pass_before_request():
    governor = TokenPressureGovernor(window_seconds=60, budgets={"gemini": 100_000})
    plan = governor.plan_request(
        "gemini",
        lane="director_candidates",
        prompt_tokens=5000,
        requested_output_tokens=1000,
        optional_pass=True,
        min_prompt_tokens=128,
        min_output_tokens=64,
        now=0,
    )
    policy = lane_budget_for("director_candidates")
    assert plan.allowed is True
    assert plan.prompt_limit == policy.prompt_tokens
    assert plan.output_tokens == policy.output_tokens
    assert plan.reason.startswith("lane_budget:")


def test_optional_lane_is_shed_under_provider_pressure_from_single_policy_source():
    governor = TokenPressureGovernor(window_seconds=60, budgets={"gemini": 1000})
    governor.record_request(
        "gemini", lane="chat", prompt_tokens=900, output_tokens=100, now=0
    )
    plan = governor.plan_request(
        "gemini",
        lane="self_critique",
        prompt_tokens=500,
        requested_output_tokens=96,
        optional_pass=None,
        now=1,
    )
    assert lane_budget_for("self_critique").optional is True
    assert plan.allowed is False
    assert plan.reason.startswith("shed_optional:")


def test_public_commit_surface_keeps_stage_side_channel_out_of_history_and_log():
    committer = PublicSurfaceCommitter()
    raw = (
        "(nháy mắt) Tôi đã kiểm tra key=AIza1234567890abcdefghijklmnop "
        "ở http://127.0.0.1:4242/debug"
    )
    result = committer.build(raw)
    assert "nháy mắt" not in result.display_text.lower()
    assert "nháy mắt" not in result.memory_text.lower()
    assert "AIza" not in result.display_text
    assert "AIza" not in result.memory_text
    assert "127.0.0.1" not in result.display_text
    assert "127.0.0.1" not in result.memory_text
    assert {"stage_direction", "secret", "private_url"}.issubset(
        set(result.blocked_kinds)
    )


def test_extracted_fact_is_sanitized_before_persistence():
    committer = PublicSurfaceCommitter()
    fact = committer.clean_fact(
        "(nháy mắt) API key=sk-1234567890abcdefghijklmnop đang ở C:\\secret\\keys.txt"
    )
    assert "nháy mắt" not in fact.lower()
    assert "sk-" not in fact
    assert "C:\\secret" not in fact


def test_sentence_segmenter_hard_splits_long_text_without_losing_content():
    text = " ".join([f"mục{i} dữ liệu cần giữ nguyên" for i in range(120)])
    segments = SentenceSegmenter().split(text)
    assert 2 <= len(segments) <= 16
    assert " ".join(segments) == " ".join(text.split())
    # Không còn kiểu dồn toàn bộ phần dư vào segment cuối như trước.
    assert max(len(item) for item in segments) < len(text) * 0.35
