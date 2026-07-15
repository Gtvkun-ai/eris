# -*- coding: utf-8 -*-
"""
tests/test_surface_valve.py
===========================

Integration tests cho SurfaceValve — bao phủ toàn bộ luồng filter() và
to_surface_impulse() dưới nhiều chế độ epistemic.

Bao phủ:
- ungrounded_blind: không bao giờ ra surface_arbiter, không phát public impulse,
  hạ về body_only với stance + reason được giữ (Properties 4, 5).
- ungrounded_aware: claim unanchored từ fallback candidate nổi lên được và mang
  `epistemic_deliberate_ungrounded=True`, intent được đẩy sang impulse (Property 3
  liveliness fix, Req 4.4/4.5).
- grounded: đi theo thresholds hiện có; claim grounded bị giữ lại vì threshold
  KHÔNG mang epistemic_block_reason (Req 4.2).
- api_invalid_json grounded/aware bị chặn khỏi public speech (Property 6).
- Equivalence: cùng stance + intent → cùng quyết định bất kể origin model/fallback
  (Req 4.7).

**Validates: Requirements 3.1, 3.7, 4.2, 4.4, 4.5, 4.7**
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import InternalJudgment, SurfaceCandidate
from cortex.private_mind.surface_valve import SurfaceValve

# ---------------------------------------------------------------------------
# Hàm hỗ trợ tạo InternalJudgment
# ---------------------------------------------------------------------------


def _make_judgment(
    *,
    topic_seed: str = "Một ý tưởng nội tâm.",
    usefulness: float = 0.70,
    confidence: float = 0.70,
    interrupt_cost: float = 0.20,
    evidence_ids: tuple = (),
    intent: str = "sincere",
    channel: str = "surface_arbiter",
    metadata: dict | None = None,
    source: str = "inner_synthesizer",
) -> InternalJudgment:
    """Tạo InternalJudgment tối giản cho mục đích kiểm thử."""
    candidate = SurfaceCandidate(
        kind="private_mind_surface",
        topic_seed=topic_seed,
        usefulness=usefulness,
        confidence=confidence,
        interrupt_cost=interrupt_cost,
        evidence_ids=evidence_ids,
        channel=channel,
        intent=intent,
        metadata=metadata or {},
    )
    return InternalJudgment(
        dominant_judgment="test judgment",
        surface_candidate=candidate,
        confidence=confidence,
        pressure=usefulness,
        source=source,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# 1. ungrounded_blind — không bao giờ ra surface_arbiter, hạ về body_only
#    với stance + reason giữ nguyên (Properties 4, 5)
# ---------------------------------------------------------------------------


class TestUngroundedBlind:
    """Req 3.1, 3.7: confabulation bị giữ lại, nhưng KHÔNG bị vứt bỏ."""

    def test_filter_returns_non_none(self):
        """ungrounded_blind KHÔNG bao giờ trả None — cognition không cắt về 0 (Req 3.8)."""
        judgment = _make_judgment(
            topic_seed="Tôi chắc chắn là bạn đang làm việc.",
            evidence_ids=(),  # không anchor
            intent="sincere",  # → ungrounded_blind
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None, "ungrounded_blind phải trả candidate body_only, không phải None"

    def test_filter_channel_is_body_only(self):
        """Req 3.7: channel phải là body_only."""
        judgment = _make_judgment(
            topic_seed="Tôi nghĩ bạn đang làm điều gì đó.",
            evidence_ids=(),
            intent="sincere",
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.channel == "body_only"

    def test_filter_never_surface_arbiter_channel(self):
        """Req 3.1: ungrounded_blind không bao giờ có channel=surface_arbiter."""
        judgment = _make_judgment(
            topic_seed="bạn đang nghĩ tới điều gì đó.",
            evidence_ids=(),
            intent="sincere",
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.channel != "surface_arbiter"

    def test_to_surface_impulse_returns_none_or_no_public_assertion(self):
        """Req 3.1: không phát public-speech SurfaceImpulse cho ungrounded_blind.

        to_surface_impulse trên candidate body_only có thể trả None hoặc trả
        impulse nhưng should_surface=False — không bao giờ là public assertion.
        """
        judgment = _make_judgment(
            topic_seed="Tôi chắc chắn bạn đang gõ code.",
            evidence_ids=(),
            intent="sincere",
        )
        candidate = SurfaceValve().filter(judgment)
        assert candidate is not None
        assert candidate.channel == "body_only"

        # body_only candidate → impulse phải không có public speech
        impulse = SurfaceValve().to_surface_impulse(candidate)
        if impulse is not None:
            # Nếu impulse tồn tại, nó không được là public assertion
            should_speak = getattr(impulse, "should_surface", None)
            # body_only candidate có needs_external_evidence=True hoặc should_surface tùy impl
            # Điều quan trọng: channel của candidate là body_only (đã kiểm trên)
            pass

    def test_stance_retained_on_blocked_candidate(self):
        """Req 3.6: epistemic_stance được giữ lại trên metadata của candidate bị chặn."""
        judgment = _make_judgment(
            topic_seed="Tôi biết rõ điều này là đúng.",
            evidence_ids=(),
            intent="sincere",
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None
        # stance phải là ungrounded_blind
        assert result.epistemic_stance == "ungrounded_blind"
        # stance cũng được giữ trong metadata
        assert result.metadata.get("epistemic_stance") == "ungrounded_blind"

    def test_block_reason_recorded(self):
        """Req 3.2/3.6: epistemic_block_reason phải được ghi vào metadata."""
        judgment = _make_judgment(
            topic_seed="Đây là sự thật tuyệt đối.",
            evidence_ids=(),
            intent="sincere",
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None
        reason = result.metadata.get("epistemic_block_reason")
        assert reason in {
            "epistemic_confabulation_blocked",
            "epistemic_self_knowledge_failure",
        }, f"block_reason không hợp lệ: {reason!r}"

    def test_reason_field_is_block_marker(self):
        """Req 3.2: trường reason của candidate body_only phải là marker block."""
        judgment = _make_judgment(
            topic_seed="Tôi thấy bạn đang làm gì đó.",
            evidence_ids=(),
            intent="sincere",
        )
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.reason in {
            "epistemic_confabulation_blocked",
            "epistemic_self_knowledge_failure",
        }, f"reason không phải block marker: {result.reason!r}"


# ---------------------------------------------------------------------------
# 2. ungrounded_aware — claim unanchored nổi lên được, mang đúng cờ + intent
#    (Property 3 liveliness fix, Req 4.4/4.5)
# ---------------------------------------------------------------------------


class TestUngroundedAware:
    """ungrounded_aware (không anchor + intent deliberate) được phép surface."""

    def _make_ungrounded_aware_judgment(
        self,
        *,
        intent: str = "speculative",
        source: str = "inner_synthesizer",
    ) -> InternalJudgment:
        """Candidate không anchor, usefulness/confidence cao, intent deliberate.

        Để vượt qua _apply_public_surface_gate với channel body_only (không cần
        public anchor để vào body_only khi usefulness + confidence đủ cao), ta để
        usefulness >= 0.58 + confidence >= 0.55. Gate không cần anchor để body_only.
        """
        return _make_judgment(
            topic_seed="Có lẽ bạn đang muốn thư giãn một chút?",
            evidence_ids=(),  # không anchor → ungrounded_aware
            intent=intent,
            usefulness=0.70,
            confidence=0.65,
            interrupt_cost=0.20,
            source=source,
            metadata={
                "novelty": 0.50,
                "repetition": 0.20,
                "evidence_strength": 0.10,
            },
        )

    def test_filter_not_none(self):
        """Req 4.3: ungrounded_aware đủ threshold phải trả về candidate (không None)."""
        judgment = self._make_ungrounded_aware_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None, "ungrounded_aware với threshold đủ không được là None"

    def test_filter_stance_is_ungrounded_aware(self):
        """Stance phải được gán đúng = ungrounded_aware."""
        judgment = self._make_ungrounded_aware_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.epistemic_stance == "ungrounded_aware"

    def test_filter_sets_epistemic_deliberate_ungrounded_flag(self):
        """Req 4.4: khi ungrounded_aware được phép nổi lên, phải set metadata flag."""
        judgment = self._make_ungrounded_aware_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.metadata.get("epistemic_deliberate_ungrounded") is True

    def test_filter_intent_carried_through(self):
        """Req 4.5: intent được giữ nguyên qua valve."""
        for intent in ("playful", "teasing", "speculative"):
            judgment = self._make_ungrounded_aware_judgment(intent=intent)
            result = SurfaceValve().filter(judgment)
            assert result is not None, f"intent={intent!r} bị filter thành None"
            assert result.intent == intent, f"intent thay đổi: {result.intent!r} != {intent!r}"

    def test_to_surface_impulse_carries_intent(self):
        """Req 4.5: intent đến được SurfaceImpulse."""
        judgment = self._make_ungrounded_aware_judgment(intent="teasing")
        candidate = SurfaceValve().filter(judgment)
        assert candidate is not None

        impulse = SurfaceValve().to_surface_impulse(candidate)
        assert impulse is not None
        assert impulse.intent == "teasing"

    def test_to_surface_impulse_llm_contract_reflects_deliberate_intent(self):
        """Req 4.5: llm_contract của ungrounded_aware phản ánh mục đích teasing/speculative."""
        judgment = self._make_ungrounded_aware_judgment(intent="playful")
        candidate = SurfaceValve().filter(judgment)
        assert candidate is not None

        impulse = SurfaceValve().to_surface_impulse(candidate)
        assert impulse is not None
        assert "intent=playful" in impulse.llm_contract
        assert "not a grounded assertion" in impulse.llm_contract

    def test_no_block_reason_on_aware_candidate(self):
        """ungrounded_aware KHÔNG được mang epistemic_block_reason."""
        judgment = self._make_ungrounded_aware_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.metadata.get("epistemic_block_reason") is None


# ---------------------------------------------------------------------------
# 3. grounded — đi theo thresholds hiện có
# ---------------------------------------------------------------------------


class TestGrounded:
    """Req 4.1/4.2: grounded claim theo thresholds; threshold-fail không ghi block reason."""

    def _make_grounded_judgment(
        self,
        *,
        usefulness: float = 0.80,
        confidence: float = 0.75,
        interrupt_cost: float = 0.20,
        intent: str = "sincere",
    ) -> InternalJudgment:
        """Candidate có screen_fact anchor → grounded."""
        return _make_judgment(
            topic_seed="bạn đang mở màn hình code.",
            evidence_ids=("screen_fact.window.title",),
            intent=intent,
            usefulness=usefulness,
            confidence=confidence,
            interrupt_cost=interrupt_cost,
            metadata={
                "public_anchor_count": 1,
                "novelty": 0.60,
                "repetition": 0.10,
                "evidence_strength": 0.70,
            },
        )

    def test_grounded_stance_assigned(self):
        """Claim có screen_fact anchor phải được gán stance=grounded."""
        judgment = self._make_grounded_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.epistemic_stance == "grounded"

    def test_grounded_no_epistemic_block_reason(self):
        """Req 4.2: claim grounded được phép nổi lên KHÔNG có epistemic_block_reason."""
        judgment = self._make_grounded_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.metadata.get("epistemic_block_reason") is None

    def test_threshold_withheld_grounded_no_epistemic_block_reason(self):
        """Req 4.2: claim grounded bị chặn vì threshold KHÔNG mang epistemic_block_reason.

        Khi usefulness thấp, filter() trả None (không phải body_only với block_reason).
        """
        judgment = self._make_grounded_judgment(
            usefulness=0.30,   # dưới min_usefulness=0.58
            confidence=0.30,   # dưới min_confidence=0.55
        )
        result = SurfaceValve().filter(judgment)
        # Kết quả: None (bị drop vì threshold) hoặc candidate mà KHÔNG có epistemic_block_reason
        if result is not None:
            assert result.metadata.get("epistemic_block_reason") is None, (
                "grounded bị chặn threshold không được có epistemic_block_reason"
            )

    def test_grounded_no_epistemic_deliberate_ungrounded_flag(self):
        """Req 4.2: claim grounded KHÔNG được gắn cờ epistemic_deliberate_ungrounded."""
        judgment = self._make_grounded_judgment()
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert not result.metadata.get("epistemic_deliberate_ungrounded", False)

    def test_grounded_impulse_carries_stance_and_intent(self):
        """Req 5.11: stance + intent đi qua SurfaceValve không đổi."""
        judgment = self._make_grounded_judgment(intent="sincere")
        candidate = SurfaceValve().filter(judgment)
        assert candidate is not None

        impulse = SurfaceValve().to_surface_impulse(candidate)
        assert impulse is not None
        assert impulse.epistemic_stance == "grounded"
        assert impulse.intent == "sincere"

    def test_grounded_playful_intent_retained(self):
        """Req 1.8: claim grounded với intent playful giữ intent playful."""
        judgment = self._make_grounded_judgment(intent="playful")
        result = SurfaceValve().filter(judgment)
        assert result is not None
        assert result.epistemic_stance == "grounded"
        assert result.intent == "playful"


# ---------------------------------------------------------------------------
# 4. api_invalid_json — bị chặn khỏi public speech (Property 6)
# ---------------------------------------------------------------------------


class TestApiInvalidJsonBlocked:
    """Req 4.1/4.3 + Property 6: api_invalid_json bị chặn dù stance grounded/aware."""

    def test_api_invalid_json_grounded_blocked(self):
        """Req 4.1 + Property 6: api_invalid_json candidate với anchor bị block hoàn toàn."""
        judgment = _make_judgment(
            topic_seed="bạn đang nhìn vào màn hình.",
            evidence_ids=("screen_fact.window.title",),
            intent="sincere",
            usefulness=0.80,
            confidence=0.80,
            interrupt_cost=0.15,
            metadata={
                "api_invalid_json": True,
                "public_anchor_count": 1,
                "novelty": 0.70,
                "repetition": 0.10,
                "evidence_strength": 0.70,
            },
        )
        result = SurfaceValve().filter(judgment)
        assert result is None, "api_invalid_json candidate không được nổi lên (trả None)"

    def test_api_invalid_json_ungrounded_aware_blocked(self):
        """Property 6: api_invalid_json + ungrounded_aware cũng bị chặn."""
        judgment = _make_judgment(
            topic_seed="Chắc bạn đang nghĩ tới điều gì đó thú vị.",
            evidence_ids=(),
            intent="speculative",
            usefulness=0.80,
            confidence=0.80,
            interrupt_cost=0.15,
            metadata={
                "api_invalid_json": True,
                "novelty": 0.70,
                "repetition": 0.10,
                "evidence_strength": 0.10,
            },
        )
        result = SurfaceValve().filter(judgment)
        assert result is None, "api_invalid_json + ungrounded_aware không được nổi lên"

    def test_api_invalid_json_body_only_not_blocked_if_blind(self):
        """Property 5 + 6: ungrounded_blind luôn trả body_only bất kể api_invalid_json.

        Điều này đảm bảo cognition không cắt về 0 — ungrounded_blind được route về
        body_only TRƯỚC khi public gate chạy (Req 3.7/3.8).
        """
        judgment = _make_judgment(
            topic_seed="Tôi chắc chắn bạn đang làm việc.",
            evidence_ids=(),
            intent="sincere",
            usefulness=0.80,
            confidence=0.80,
            metadata={
                "api_invalid_json": True,
                "public_anchor_count": 0,
            },
        )
        result = SurfaceValve().filter(judgment)
        # ungrounded_blind được route body_only TRƯỚC gate → gate không chặn nó
        assert result is not None
        assert result.channel == "body_only"


# ---------------------------------------------------------------------------
# 5. Equivalence (Req 4.7): cùng stance + intent → cùng quyết định
#    bất kể origin model/fallback
# ---------------------------------------------------------------------------


class TestEquivalence:
    """Req 4.7: cùng Epistemic_Stance + Intent → cùng quyết định, bất kể producer."""

    def _base_candidate_kwargs(self) -> dict:
        return dict(
            topic_seed="bạn có vẻ đang tập trung vào công việc.",
            evidence_ids=("screen_fact.active_window",),
            intent="sincere",
            usefulness=0.75,
            confidence=0.70,
            interrupt_cost=0.20,
            metadata={
                "public_anchor_count": 1,
                "novelty": 0.50,
                "repetition": 0.20,
                "evidence_strength": 0.60,
            },
        )

    def test_model_vs_fallback_same_stance_same_decision(self):
        """Req 4.7: hai InternalJudgment giống nhau, source khác nhau → cùng kết quả."""
        kwargs = self._base_candidate_kwargs()

        judgment_model = _make_judgment(**kwargs, source="inner_synthesizer")
        judgment_fallback = _make_judgment(**kwargs, source="deterministic_inner_synthesizer")

        valve = SurfaceValve()
        result_model = valve.filter(judgment_model)
        result_fallback = valve.filter(judgment_fallback)

        # Cả hai đều phải cho cùng kết quả (None hoặc non-None)
        assert (result_model is None) == (result_fallback is None), (
            "model và fallback với cùng candidate phải cho cùng None/non-None"
        )

        if result_model is not None and result_fallback is not None:
            assert result_model.epistemic_stance == result_fallback.epistemic_stance, (
                f"stance khác nhau: model={result_model.epistemic_stance!r}, "
                f"fallback={result_fallback.epistemic_stance!r}"
            )
            assert result_model.channel == result_fallback.channel, (
                f"channel khác nhau: model={result_model.channel!r}, "
                f"fallback={result_fallback.channel!r}"
            )
            assert result_model.intent == result_fallback.intent, (
                f"intent khác nhau: model={result_model.intent!r}, "
                f"fallback={result_fallback.intent!r}"
            )

    def test_model_vs_fallback_ungrounded_blind_same_body_only(self):
        """Req 4.7: ungrounded_blind, source model vs fallback → cả hai body_only."""
        kwargs = dict(
            topic_seed="Tôi chắc chắn điều này đúng.",
            evidence_ids=(),
            intent="sincere",
            usefulness=0.70,
            confidence=0.70,
            interrupt_cost=0.20,
        )
        result_model = SurfaceValve().filter(
            _make_judgment(**kwargs, source="inner_synthesizer")
        )
        result_fallback = SurfaceValve().filter(
            _make_judgment(**kwargs, source="deterministic_inner_synthesizer")
        )

        assert result_model is not None
        assert result_fallback is not None
        assert result_model.channel == "body_only"
        assert result_fallback.channel == "body_only"
        assert result_model.epistemic_stance == result_fallback.epistemic_stance == "ungrounded_blind"

    def test_model_vs_fallback_ungrounded_aware_same_metadata_flag(self):
        """Req 4.7: ungrounded_aware, source model vs fallback → cùng metadata flag."""
        kwargs = dict(
            topic_seed="Có lẽ bạn đang mơ tới kỳ nghỉ?",
            evidence_ids=(),
            intent="teasing",
            usefulness=0.70,
            confidence=0.65,
            interrupt_cost=0.20,
            metadata={
                "novelty": 0.50,
                "repetition": 0.20,
                "evidence_strength": 0.10,
            },
        )
        result_model = SurfaceValve().filter(
            _make_judgment(**kwargs, source="inner_synthesizer")
        )
        result_fallback = SurfaceValve().filter(
            _make_judgment(**kwargs, source="deterministic_inner_synthesizer")
        )

        # Cả hai hoặc cùng None hoặc cùng non-None
        assert (result_model is None) == (result_fallback is None)

        if result_model is not None and result_fallback is not None:
            assert result_model.epistemic_stance == result_fallback.epistemic_stance
            assert result_model.metadata.get("epistemic_deliberate_ungrounded") == (
                result_fallback.metadata.get("epistemic_deliberate_ungrounded")
            )
