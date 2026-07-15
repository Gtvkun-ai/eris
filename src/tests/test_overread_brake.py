# -*- coding: utf-8 -*-
"""test_overread_brake.py — property + unit tests cho ``OverreadBrake`` (stage 8).

Bao phủ Properties 27–30 (tasks 15.2–15.5) của spec ``phase2-meaning-tom``:

- Property 27 (R8.1) — confidence reduction band.
- Property 28 (R8.2, R8.3, R8.6, R13.6) — suppression conditions.
- Property 29 (R13.7) — non-suppression below threshold.
- Property 30 (R8.4, R8.5) — brake records & preserves originals.

Quy ước: ``pytest`` + ``hypothesis``; ``tests/conftest.py`` đã chèn ``src`` và
``tests`` vào ``sys.path`` nên import ``cortex.*`` và ``phase2_strategies`` chạy
mà không cần cài package. Mỗi property-based test cấu hình
``@settings(max_examples=100)`` và gắn comment ``# Feature: ...`` + docstring
``Validates:`` theo đúng quy ước.

Các band test chính xác dựng ``MeaningHypothesis`` trực tiếp với
``overread_risk``/``evidence_ids`` được kiểm soát; mặc định cấp
``>= min_evidence_count`` evidence để evidence-suppression không nhiễu band test
(trừ khi đang test riêng R8.3).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cortex.meaning.config import Phase2Config
from cortex.meaning.contracts import EvaluatedConclusion, MeaningHypothesis
from cortex.meaning.overread_brake import OverreadBrake

from phase2_strategies import conclusions_across_brake_bands, ids


# ---------------------------------------------------------------------------
# Hằng số mặc định (đồng bộ Phase2Config — nguồn duy nhất)
# ---------------------------------------------------------------------------
_CFG = Phase2Config()
REDUCTION_THRESHOLD = _CFG.overread_reduction_threshold      # 0.70
SUPPRESSION_THRESHOLD = _CFG.overread_suppression_threshold  # 0.90
REDUCED_CONF_CAP = _CFG.reduced_conf_cap                     # 0.50
MIN_EVIDENCE_COUNT = _CFG.min_evidence_count                 # 2


def _brake() -> OverreadBrake:
    """OverreadBrake với cấu hình mặc định Phase2Config."""

    return OverreadBrake(config=Phase2Config())


def _make_hypothesis(
    *,
    confidence: float,
    overread_risk: float,
    evidence_count: int,
    summary: str = "neutral summary",
) -> MeaningHypothesis:
    """Dựng một ``MeaningHypothesis`` hợp lệ với các trường được kiểm soát."""

    evidence_ids = [f"ev-{i}" for i in range(evidence_count)]
    return MeaningHypothesis(
        hypothesis_id="h-test",
        category="literal",  # bất kỳ chuỗi nào; brake không kiểm category
        summary=summary,
        evidence_ids=evidence_ids,
        confidence=confidence,
        ambiguity=0.0,
        overread_risk=overread_risk,
    )


# ---------------------------------------------------------------------------
# Property 27 (task 15.2) — confidence reduction band (R8.1)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 27: Overread confidence reduction band
@settings(max_examples=100)
@given(
    overread_risk=st.floats(
        min_value=REDUCTION_THRESHOLD,
        max_value=math.nextafter(SUPPRESSION_THRESHOLD, 0.0),
        allow_nan=False,
        allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    evidence_count=st.integers(min_value=MIN_EVIDENCE_COUNT, max_value=6),
)
def test_property_27_confidence_reduction_band(overread_risk, confidence, evidence_count):
    """Validates: Requirements 8.1.

    Với mọi conclusion có ``reduction_threshold <= overread_risk <
    suppression_threshold`` AND ``evidence_count >= min_evidence_count`` AND
    không khớp forbidden, ``evaluate()`` giảm confidence xuống
    ``<= reduced_conf_cap`` (0.50), ghi reason + ``metric_name="overread_risk"``
    + ``metric_value``, và giữ nguyên ``original_confidence``.
    """

    hypothesis = _make_hypothesis(
        confidence=confidence,
        overread_risk=overread_risk,
        evidence_count=evidence_count,
    )

    evaluated, _debug = _brake().evaluate([hypothesis], forbidden_assumptions=[])

    assert len(evaluated) == 1
    ec = evaluated[0]

    # Không bị suppress (đây là reduction band, evidence đủ, không forbidden).
    assert ec.overread_suppressed is False
    # Confidence bị giảm xuống <= cap.
    assert ec.confidence <= REDUCED_CONF_CAP + 1e-9
    # Cụ thể là min(original, cap).
    assert ec.confidence == pytest.approx(min(hypothesis.confidence, REDUCED_CONF_CAP))
    # Ghi nhận reason + metric.
    assert ec.brake_reason != ""
    assert ec.metric_name == "overread_risk"
    assert ec.metric_value == pytest.approx(hypothesis.overread_risk)
    # original_confidence giữ giá trị gốc.
    assert ec.original_confidence == pytest.approx(hypothesis.confidence)


# ---------------------------------------------------------------------------
# Property 28 (task 15.3) — suppression conditions (R8.2, R8.3, R8.6, R13.6)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 28: Overread suppression conditions
@settings(max_examples=100)
@given(
    overread_risk=st.floats(
        min_value=SUPPRESSION_THRESHOLD,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    evidence_count=st.integers(min_value=MIN_EVIDENCE_COUNT, max_value=6),
)
def test_property_28a_suppress_high_overread_risk(overread_risk, confidence, evidence_count):
    """Validates: Requirements 8.2, 13.6.

    ``overread_risk >= suppression_threshold`` (0.90) → ``overread_suppressed``
    True, bất kể evidence đủ và không forbidden.
    """

    hypothesis = _make_hypothesis(
        confidence=confidence,
        overread_risk=overread_risk,
        evidence_count=evidence_count,
    )

    evaluated, _debug = _brake().evaluate([hypothesis], forbidden_assumptions=[])

    assert len(evaluated) == 1
    assert evaluated[0].overread_suppressed is True


# Feature: phase2-meaning-tom, Property 28: Overread suppression conditions
@settings(max_examples=100)
@given(
    overread_risk=st.floats(
        min_value=0.0,
        max_value=math.nextafter(SUPPRESSION_THRESHOLD, 0.0),
        allow_nan=False,
        allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    evidence_count=st.integers(min_value=0, max_value=MIN_EVIDENCE_COUNT - 1),
)
def test_property_28b_suppress_insufficient_evidence(overread_risk, confidence, evidence_count):
    """Validates: Requirements 8.3, 13.6.

    ``evidence_count < min_evidence_count`` (2) → ``overread_suppressed`` True,
    ngay cả khi ``overread_risk`` dưới ngưỡng suppression.
    """

    hypothesis = _make_hypothesis(
        confidence=confidence,
        overread_risk=overread_risk,
        evidence_count=evidence_count,
    )

    evaluated, _debug = _brake().evaluate([hypothesis], forbidden_assumptions=[])

    assert len(evaluated) == 1
    assert evaluated[0].overread_suppressed is True


# Feature: phase2-meaning-tom, Property 28: Overread suppression conditions
@settings(max_examples=100)
@given(
    overread_risk=st.floats(
        min_value=0.0,
        max_value=math.nextafter(SUPPRESSION_THRESHOLD, 0.0),
        allow_nan=False,
        allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    evidence_count=st.integers(min_value=MIN_EVIDENCE_COUNT, max_value=6),
    forbidden=st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        min_size=3,
        max_size=12,
    ).filter(lambda s: s.strip() != ""),
)
def test_property_28c_suppress_forbidden_assumption(
    overread_risk, confidence, evidence_count, forbidden
):
    """Validates: Requirements 8.6, 13.6.

    Conclusion khẳng định một ``forbidden_assumption`` (xuất hiện trong summary)
    → ``overread_suppressed`` True, dù evidence đủ và overread_risk dưới ngưỡng.
    """

    # Nhúng forbidden như substring của summary để brake khớp (case-insensitive).
    summary = f"the user definitely {forbidden} right now"
    hypothesis = _make_hypothesis(
        confidence=confidence,
        overread_risk=overread_risk,
        evidence_count=evidence_count,
        summary=summary,
    )

    evaluated, _debug = _brake().evaluate(
        [hypothesis], forbidden_assumptions=[forbidden]
    )

    assert len(evaluated) == 1
    assert evaluated[0].overread_suppressed is True


# ---------------------------------------------------------------------------
# Property 29 (task 15.4) — non-suppression below threshold (R13.7)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 29: Non-suppression below threshold
@settings(max_examples=100)
@given(
    overread_risk=st.floats(
        min_value=0.0,
        max_value=math.nextafter(SUPPRESSION_THRESHOLD, 0.0),
        allow_nan=False,
        allow_infinity=False,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    evidence_count=st.integers(min_value=MIN_EVIDENCE_COUNT, max_value=6),
)
def test_property_29_non_suppression_below_threshold(overread_risk, confidence, evidence_count):
    """Validates: Requirements 13.7.

    Với mọi conclusion có ``overread_risk <= suppression_threshold`` AND
    ``evidence_count >= min_evidence_count`` AND không khớp forbidden,
    ``evaluate()`` KHÔNG đánh suppressed trên cơ sở overread_risk.

    Strategy sinh ``overread_risk`` strictly dưới ngưỡng (band below + reduction),
    nên không chạm điều kiện suppression nào.
    """

    hypothesis = _make_hypothesis(
        confidence=confidence,
        overread_risk=overread_risk,
        evidence_count=evidence_count,
        summary="neutral non-asserting summary",
    )

    evaluated, _debug = _brake().evaluate([hypothesis], forbidden_assumptions=[])

    assert len(evaluated) == 1
    assert evaluated[0].overread_suppressed is False


# ---------------------------------------------------------------------------
# Property 30 (task 15.5) — brake records & preserves originals (R8.4, R8.5)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 30: Brake records and preserves originals
@settings(max_examples=100)
@given(conclusion=conclusions_across_brake_bands())
def test_property_30_records_and_preserves_originals(conclusion):
    """Validates: Requirements 8.4, 8.5.

    Với mọi conclusion bị reduce hoặc suppress, ``EvaluatedConclusion`` ghi
    ``brake_reason``/``metric_name``/``metric_value`` và giữ nguyên
    ``original_confidence``; mọi conclusion vẫn nằm trong output list
    (đúng một ``EvaluatedConclusion`` mỗi input).
    """

    original_confidence = conclusion.confidence

    evaluated, _debug = _brake().evaluate([conclusion], forbidden_assumptions=[])

    # Đúng một EvaluatedConclusion cho mỗi input (không drop — R8.5).
    assert len(evaluated) == 1
    ec = evaluated[0]
    assert isinstance(ec, EvaluatedConclusion)
    assert ec.conclusion is conclusion

    # original_confidence luôn được bảo toàn.
    assert ec.original_confidence == pytest.approx(original_confidence)

    was_reduced = (not ec.overread_suppressed) and ec.brake_reason == "overread_risk_reduced"
    was_suppressed = ec.overread_suppressed

    if was_reduced or was_suppressed:
        # Mọi lần reduce/suppress: ghi reason + metric (R8.4).
        assert ec.brake_reason != ""
        assert ec.metric_name != ""
    if was_suppressed:
        # Bị chặn: confidence giữ nguyên original (không bịa giá trị mới — R8.5).
        assert ec.confidence == pytest.approx(original_confidence)


# Feature: phase2-meaning-tom, Property 30: Brake records and preserves originals
@settings(max_examples=100)
@given(conclusions=st.lists(conclusions_across_brake_bands(), min_size=0, max_size=6))
def test_property_30_output_one_per_input(conclusions):
    """Validates: Requirements 8.4, 8.5.

    ``evaluate()`` trả về đúng một ``EvaluatedConclusion`` cho MỖI input
    (kể cả input bị chặn) và bảo toàn ``original_confidence`` cho từng cái.
    """

    originals = [c.confidence for c in conclusions]

    evaluated, _debug = _brake().evaluate(list(conclusions), forbidden_assumptions=[])

    assert len(evaluated) == len(conclusions)
    for ec, original, src in zip(evaluated, originals, conclusions):
        assert ec.conclusion is src
        assert ec.original_confidence == pytest.approx(original)


# ---------------------------------------------------------------------------
# Unit tests — band biên chính xác (bổ trợ property tests)
# ---------------------------------------------------------------------------
def test_unit_reduction_lower_boundary_reduces():
    """Tại đúng ``reduction_threshold`` → reduce (R8.1)."""

    h = _make_hypothesis(confidence=0.95, overread_risk=REDUCTION_THRESHOLD, evidence_count=2)
    evaluated, _ = _brake().evaluate([h], forbidden_assumptions=[])
    ec = evaluated[0]
    assert ec.overread_suppressed is False
    assert ec.brake_reason == "overread_risk_reduced"
    assert ec.confidence == pytest.approx(REDUCED_CONF_CAP)


def test_unit_suppression_lower_boundary_suppresses():
    """Tại đúng ``suppression_threshold`` → suppress (R8.2)."""

    h = _make_hypothesis(confidence=0.95, overread_risk=SUPPRESSION_THRESHOLD, evidence_count=4)
    evaluated, _ = _brake().evaluate([h], forbidden_assumptions=[])
    ec = evaluated[0]
    assert ec.overread_suppressed is True
    assert ec.metric_name == "overread_risk"


def test_unit_below_reduction_untouched():
    """``overread_risk`` dưới reduction, evidence đủ → giữ nguyên, không reason."""

    h = _make_hypothesis(confidence=0.8, overread_risk=0.10, evidence_count=3)
    evaluated, _ = _brake().evaluate([h], forbidden_assumptions=[])
    ec = evaluated[0]
    assert ec.overread_suppressed is False
    assert ec.brake_reason == ""
    assert ec.confidence == pytest.approx(0.8)


def test_unit_insufficient_evidence_metric():
    """Evidence thiếu → suppress với ``metric_name="evidence_count"`` (R8.3)."""

    h = _make_hypothesis(confidence=0.9, overread_risk=0.1, evidence_count=1)
    evaluated, _ = _brake().evaluate([h], forbidden_assumptions=[])
    ec = evaluated[0]
    assert ec.overread_suppressed is True
    assert ec.metric_name == "evidence_count"
    assert ec.metric_value == pytest.approx(1.0)


def test_unit_empty_input_returns_empty():
    """Input rỗng → không EvaluatedConclusion."""

    evaluated, _debug = _brake().evaluate([], forbidden_assumptions=[])
    assert evaluated == []
