# -*- coding: utf-8 -*-
"""tests/test_pragmatic_intent.py — PragmaticIntentEngine (stage 5) tests.

Bao phủ các task 12.2–12.5 của spec ``phase2-meaning-tom``:

- Property 21 (12.2) — count and valid categories (R6.1, R11.2).
- Property 22 (12.3) — intents retain supporting refs and confidence bounds (R6.3).
- Property 23 (12.4) — high ambiguity lowers intent confidence (R6.4).
- Unit (12.5) — empty input → 0 intent + chỉ báo "no pragmatic intent" (R6.5).

Quy ước: ``pytest`` + ``hypothesis``; ``tests/conftest.py`` chèn ``src`` vào
``sys.path`` nên import ``cortex.*`` hoạt động. Mỗi property-based test cấu hình
``@settings(max_examples=100)`` và gắn comment
``# Feature: phase2-meaning-tom, Property {n}: {text}``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from cortex.meaning.pragmatic_intent import PragmaticIntentEngine
from cortex.meaning.contracts import MeaningHypothesis, PragmaticIntent
from cortex.meaning.taxonomy import Taxonomy


# Category meaning hợp lệ (sample id thật từ Taxonomy.MEANING).
_MEANING_CATEGORIES: tuple[str, ...] = tuple(sorted(Taxonomy.MEANING))

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _ids(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[str]:
    """Chuỗi id không rỗng cho ``hypothesis_id``/``evidence_id``."""

    return st.text(alphabet=_ID_ALPHABET, min_size=min_size, max_size=max_size)


def _unit_floats() -> st.SearchStrategy[float]:
    """Float trong [0.0, 1.0] (không NaN/inf)."""

    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def _safe_text(max_size: int = 30) -> st.SearchStrategy[str]:
    """Text ngắn, loại ký tự điều khiển/surrogate cho ``summary``."""

    return st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        max_size=max_size,
    )


@st.composite
def meaning_hypotheses(
    draw,
    *,
    confidence: float | None = None,
    ambiguity: float | None = None,
    overread_risk: float | None = None,
    category: str | None = None,
    summary: str | None = None,
) -> MeaningHypothesis:
    """Sinh một ``MeaningHypothesis`` hợp lệ.

    - ``category`` thuộc ``Taxonomy.MEANING`` (sample id thật).
    - ``evidence_ids`` không rỗng (đúng contract R5.2 của input).
    - ``confidence``/``ambiguity``/``overread_risk`` ∈ [0,1], có thể ghim để các
      test dẫn xuất kiểm soát phân bố.
    """

    return MeaningHypothesis(
        hypothesis_id=draw(_ids()),
        category=category if category is not None else draw(st.sampled_from(_MEANING_CATEGORIES)),
        summary=summary if summary is not None else draw(_safe_text()),
        evidence_ids=draw(st.lists(_ids(), min_size=1, max_size=4, unique=True)),
        confidence=draw(_unit_floats()) if confidence is None else confidence,
        ambiguity=draw(_unit_floats()) if ambiguity is None else ambiguity,
        overread_risk=draw(_unit_floats()) if overread_risk is None else overread_risk,
    )


def _nonempty_hypothesis_lists() -> st.SearchStrategy[list[MeaningHypothesis]]:
    """Danh sách KHÔNG rỗng các ``MeaningHypothesis`` hợp lệ."""

    return st.lists(meaning_hypotheses(), min_size=1, max_size=12)


# ---------------------------------------------------------------------------
# Property 21 (task 12.2) — count and valid categories
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 21: Pragmatic intent count and valid categories
@settings(max_examples=100)
@given(hypotheses=_nonempty_hypothesis_lists())
def test_property_21_count_and_valid_categories(hypotheses: list[MeaningHypothesis]) -> None:
    """Validates: Requirements 6.1, 11.2.

    Với BẤT KỲ danh sách ``MeaningHypothesis`` không rỗng, ``derive`` sinh giữa 1
    và 8 ``PragmaticIntent``, và mỗi ``intent.category`` thuộc ``Taxonomy.INTENT``.
    """

    intents, _debug = PragmaticIntentEngine().derive(hypotheses, frame_id="f")

    assert 1 <= len(intents) <= 8
    for intent in intents:
        assert isinstance(intent, PragmaticIntent)
        assert intent.category in Taxonomy.INTENT


# ---------------------------------------------------------------------------
# Property 22 (task 12.3) — intents retain supporting refs and confidence bounds
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 22: Intents retain supporting references and confidence bounds
@settings(max_examples=100)
@given(hypotheses=_nonempty_hypothesis_lists())
def test_property_22_retain_support_and_confidence_bounds(
    hypotheses: list[MeaningHypothesis],
) -> None:
    """Validates: Requirements 6.3.

    Mọi intent sinh ra có ``confidence ∈ [0,1]`` và ≥1 ``supporting_meaning_ids``.
    """

    intents, _debug = PragmaticIntentEngine().derive(hypotheses, frame_id="f")

    for intent in intents:
        assert 0.0 <= intent.confidence <= 1.0
        assert len(intent.supporting_meaning_ids) >= 1


# Feature: phase2-meaning-tom, Property 22: Intents retain supporting references and confidence bounds
@settings(max_examples=100)
@given(
    categories=st.lists(st.sampled_from(_MEANING_CATEGORIES), min_size=1, max_size=6),
)
def test_property_22_support_retained_when_confidence_zero(categories: list[str]) -> None:
    """Validates: Requirements 6.3.

    Trường hợp ``confidence == 0.0``: với tập supporter mà toàn bộ confidence = 0
    (⇒ confidence intent = 0), ``supporting_meaning_ids`` vẫn KHÔNG rỗng.
    """

    hypotheses = [
        MeaningHypothesis(
            hypothesis_id=f"h{i}",
            category=cat,
            summary="",
            evidence_ids=[f"e{i}"],
            confidence=0.0,
            ambiguity=0.0,
            overread_risk=0.0,
        )
        for i, cat in enumerate(categories)
    ]

    intents, _debug = PragmaticIntentEngine().derive(hypotheses, frame_id="f")

    assert len(intents) >= 1
    for intent in intents:
        assert intent.confidence == 0.0
        assert len(intent.supporting_meaning_ids) >= 1


# ---------------------------------------------------------------------------
# Property 23 (task 12.4) — high ambiguity lowers intent confidence
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 23: High ambiguity lowers intent confidence
@settings(max_examples=100)
@given(
    category=st.sampled_from(_MEANING_CATEGORIES),
    confidences=st.lists(_unit_floats(), min_size=1, max_size=5),
    low_ambiguities=st.lists(
        st.floats(min_value=0.0, max_value=0.7, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=5,
    ),
    high_ambiguity=st.floats(
        min_value=0.70001, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_23_high_ambiguity_lowers_confidence(
    category: str,
    confidences: list[float],
    low_ambiguities: list[float],
    high_ambiguity: float,
) -> None:
    """Validates: Requirements 6.4.

    Với CÙNG tập supporter ánh xạ về một intent (cùng ``category``, cùng
    ``confidence``), so confidence khi mọi supporter có ``ambiguity ≤ 0.7`` với
    khi ÍT NHẤT một supporter có ``ambiguity > 0.7`` (chỉ khác đúng một supporter).
    Khi ``base confidence > 0`` thì case ambiguity-cao cho confidence
    NGHIÊM NGẶT thấp hơn.
    """

    # Đồng bộ độ dài hai danh sách để mỗi supporter có (confidence, ambiguity).
    n = min(len(confidences), len(low_ambiguities))
    confidences = confidences[:n]
    low_ambiguities = low_ambiguities[:n]

    # --- Tập low-ambiguity: mọi supporter ambiguity ≤ 0.7 -------------------
    low_set = [
        MeaningHypothesis(
            hypothesis_id=f"h{i}",
            category=category,
            summary="",
            evidence_ids=[f"e{i}"],
            confidence=conf,
            ambiguity=amb,
            overread_risk=0.0,
        )
        for i, (conf, amb) in enumerate(zip(confidences, low_ambiguities))
    ]

    # --- Tập high-ambiguity: y hệt, chỉ nâng ambiguity của supporter[0] > 0.7 -
    high_set = [
        MeaningHypothesis(
            hypothesis_id=f"h{i}",
            category=category,
            summary="",
            evidence_ids=[f"e{i}"],
            confidence=conf,
            ambiguity=(high_ambiguity if i == 0 else amb),
            overread_risk=0.0,
        )
        for i, (conf, amb) in enumerate(zip(confidences, low_ambiguities))
    ]

    engine = PragmaticIntentEngine()
    low_intents, _ = engine.derive(low_set, frame_id="f")
    high_intents, _ = engine.derive(high_set, frame_id="f")

    # Cùng category ⇒ đúng một intent mỗi bên.
    assert len(low_intents) == 1
    assert len(high_intents) == 1

    low_conf = low_intents[0].confidence
    high_conf = high_intents[0].confidence

    base = max(confidences)
    if base > 0.0:
        assert high_conf < low_conf
    else:
        # base == 0 ⇒ cả hai về 0; supporting refs vẫn được giữ (R6.3).
        assert high_conf == low_conf == 0.0
        assert len(high_intents[0].supporting_meaning_ids) >= 1


# ---------------------------------------------------------------------------
# Unit (task 12.5) — empty input
# ---------------------------------------------------------------------------
def test_empty_input_yields_no_intent_with_indicator() -> None:
    """Validates: Requirements 6.5.

    ``derive([], frame_id="f")`` → ``[]`` và ``StageDebug.notes`` có chỉ báo
    "no pragmatic intent".
    """

    intents, debug = PragmaticIntentEngine().derive([], frame_id="f")

    assert intents == []
    joined = " ".join(debug.notes).lower()
    assert "no pragmatic intent" in joined
