# -*- coding: utf-8 -*-
"""tests/test_meaning_hypothesis.py — property + delegation tests cho stage 4.

Bộ test cho ``MeaningHypothesisEngine`` (Phase 2, spec ``phase2-meaning-tom``),
phủ các task:

- 11.2 — Property 17: meaning hypotheses count & metric bounds (R5.1, R5.2).
- 11.3 — Property 18: near-tie hypotheses raise ambiguity (R5.3).
- 11.4 — Property 19: insufficient-evidence fallback (R5.4).
- 11.5 — Property 20: meaning hypotheses ordering (R5.5, R5.6).
- 11.6 — delegation spy: WRAP confirmation (R5.7).

``MeaningHypothesisEngine`` là một module **WRAP** — nó uỷ quyền việc chấm điểm
semantic cho ``SemanticHypothesisEngine`` và làm giàu meaning-slot qua
``MeaningLayer``. Để test xác định (deterministic) và không phụ thuộc encoder
thật, ta tiêm vào các **fake** engine:

- ``FakeSemanticEngine.compare(domain, text, *, anchors=(), labels=None)`` trả về
  một ``FakeReport`` có ``.hypotheses`` (tuple các ``FakeSemanticHypothesis`` với
  ``.label``/``.confidence``/``.margin_from_next``/``.is_fallback``), ``.ambiguity``
  và ``.confidence``.
- ``FakeMeaningLayer.evaluate(**kwargs)`` trả về một ``FakeMeaningSlot`` đơn giản.

``conftest.py`` đã chèn ``src`` và ``tests`` vào ``sys.path`` nên import
``cortex.*`` và ``phase2_strategies`` hoạt động trực tiếp.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from phase2_strategies import ids, unit_floats

from cortex.meaning.ambiguity import AmbiguityModule
from cortex.meaning.config import Phase2Config
from cortex.meaning.contracts import ContextAnnotation, MeaningHypothesis, Observation
from cortex.meaning.meaning_hypothesis import MeaningHypothesisEngine


# ---------------------------------------------------------------------------
# Fakes — semantic engine / meaning layer được tiêm vào engine
# ---------------------------------------------------------------------------
class FakeSemanticHypothesis:
    """Đại diện tối thiểu của một ``SemanticHypothesis`` mà adapter cần đọc."""

    def __init__(
        self,
        *,
        label: str = "statement",
        confidence: float = 0.0,
        margin_from_next: float = 0.0,
        is_fallback: bool = False,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.margin_from_next = margin_from_next
        self.is_fallback = is_fallback


class FakeReport:
    """Đại diện tối thiểu của một ``SemanticHypothesisReport``."""

    def __init__(
        self,
        hypotheses,
        *,
        ambiguity: float = 0.0,
        confidence: float = 0.0,
    ) -> None:
        self.hypotheses = tuple(hypotheses)
        self.ambiguity = ambiguity
        self.confidence = confidence


class FakeSemanticEngine:
    """Fake ``SemanticHypothesisEngine`` trả về một report cố định + đếm lời gọi."""

    def __init__(self, report: FakeReport) -> None:
        self.report = report
        self.compare_calls: list[tuple] = []

    def compare(self, domain, text, *, anchors=(), labels=None):
        self.compare_calls.append((domain, text, tuple(anchors), labels))
        return self.report


class FakeMeaningSlot:
    """Vật liệu meaning-slot đơn giản (chỉ để làm giàu summary, không chấm điểm)."""

    def __init__(self, *, semantic_family: str = "", scene_meaning: str = "") -> None:
        self.semantic_family = semantic_family
        self.scene_meaning = scene_meaning


class FakeMeaningLayer:
    """Fake ``MeaningLayer`` trả về một slot đơn giản + đếm lời gọi."""

    def __init__(self, slot: FakeMeaningSlot | None = None) -> None:
        self.slot = slot if slot is not None else FakeMeaningSlot()
        self.evaluate_calls: list[dict] = []

    def evaluate(self, **kwargs):
        self.evaluate_calls.append(kwargs)
        return self.slot


def make_engine(
    semantic_engine, meaning_layer, *, config: Phase2Config | None = None
) -> MeaningHypothesisEngine:
    """Dựng engine với deps tiêm vào (AmbiguityModule + Phase2Config mặc định)."""

    return MeaningHypothesisEngine(
        semantic_engine=semantic_engine,
        meaning_layer=meaning_layer,
        ambiguity_module=AmbiguityModule(),
        config=config or Phase2Config(),
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def _summaries() -> st.SearchStrategy[str]:
    """Summary chữ-cái không rỗng (để text feed semantic engine luôn non-empty)."""

    return st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)


@st.composite
def context_annotations(draw, *, min_size: int = 1, max_size: int = 3, with_evidence: bool = True):
    """Sinh list ``ContextAnnotation`` hợp lệ wrap ``Observation`` có evidence.

    ``with_evidence=False`` ép mọi observation có ``evidence_ids`` rỗng (dùng cho
    nhánh insufficient-evidence của Property 19).
    """

    n = draw(st.integers(min_value=min_size, max_value=max_size))
    annotations: list[ContextAnnotation] = []
    for _ in range(n):
        min_ev = 1 if with_evidence else 0
        evidence_ids = draw(
            st.lists(ids(), min_size=min_ev, max_size=3, unique=True)
        ) if with_evidence else []
        observation = Observation(
            observation_id=draw(ids()),
            summary=draw(_summaries()),
            evidence_ids=evidence_ids,
            confidence=draw(unit_floats()),
            source_element_id=draw(ids()),
        )
        annotations.append(
            ContextAnnotation(
                observation=observation,
                relationship="peer",
                register="casual",
                social_norm="neutral",
                unconfirmed_social=[],
                defaults_applied=[],
                confidence=draw(unit_floats()),
            )
        )
    return annotations


@st.composite
def fake_semantic_hypotheses(draw, *, min_size: int = 1, max_size: int = 6):
    """Sinh list ``FakeSemanticHypothesis`` với confidence ∈ [0,1]."""

    n = draw(st.integers(min_value=min_size, max_value=max_size))
    hyps = []
    for _ in range(n):
        hyps.append(
            FakeSemanticHypothesis(
                label=draw(st.sampled_from(("statement", "request", "joke", "probe", "x"))),
                confidence=draw(unit_floats()),
                margin_from_next=draw(unit_floats()),
                is_fallback=draw(st.booleans()),
            )
        )
    return hyps


@st.composite
def reports_with_hypotheses(draw, *, min_size: int = 1, max_size: int = 6):
    """Sinh một ``FakeReport`` có ≥1 hypothesis + ambiguity ∈ [0,1]."""

    hyps = draw(fake_semantic_hypotheses(min_size=min_size, max_size=max_size))
    return FakeReport(hyps, ambiguity=draw(unit_floats()), confidence=draw(unit_floats()))


@st.composite
def near_tie_reports(draw, *, margin: float = 0.08):
    """Sinh ``(report, report_ambiguity)`` với top-2 confidence sát nhau (≤ margin).

    ``report_ambiguity`` bị giới hạn ≤ 0.8 để việc "tăng ambiguity" (R5.3) luôn
    quan sát được mà không bị clamp ở biên 1.0.
    """

    top = draw(st.floats(min_value=margin, max_value=1.0, allow_nan=False, allow_infinity=False))
    # Draw delta strictly safely below the margin so the realized top-2 gap
    # (top - second) is guaranteed <= margin even after floating-point error.
    # Using margin * 0.5 leaves ample headroom against float rounding, so at
    # least one genuine near-tie pair always exists and ``raised_any`` becomes
    # True deterministically (no boundary flakiness).
    delta = draw(
        st.floats(min_value=0.0, max_value=margin * 0.5, allow_nan=False, allow_infinity=False)
    )
    second = max(0.0, top - delta)

    confidences = [top, second]
    extra = draw(
        st.lists(
            st.floats(min_value=0.0, max_value=second, allow_nan=False, allow_infinity=False),
            max_size=2,
        )
    )
    confidences.extend(extra)

    hyps = [
        FakeSemanticHypothesis(
            label="statement",
            confidence=c,
            margin_from_next=draw(unit_floats()),
            is_fallback=draw(st.booleans()),
        )
        for c in confidences
    ]
    report_ambiguity = draw(
        st.floats(min_value=0.0, max_value=0.8, allow_nan=False, allow_infinity=False)
    )
    return FakeReport(hyps, ambiguity=report_ambiguity), report_ambiguity


# ---------------------------------------------------------------------------
# Property 17 (task 11.2) — count and metric bounds
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 17: Meaning hypotheses count and metric
# bounds — for any context-annotated observation set, the engine produces between
# 1 and the configured maximum MeaningHypothesis instances, each with a non-empty
# evidence_ids set and Confidence/Ambiguity/Overread_Risk all in [0.0, 1.0].
@settings(max_examples=100)
@given(annotations=context_annotations(with_evidence=True), report=reports_with_hypotheses())
def test_property_17_count_and_metric_bounds(annotations, report):
    """Validates: Requirements 5.1, 5.2"""

    config = Phase2Config()
    engine = make_engine(FakeSemanticEngine(report), FakeMeaningLayer(), config=config)

    produced, _debug = engine.generate(annotations, frame_id="frame")

    # R5.1 — count between 1 and configured maximum (default 4).
    assert 1 <= len(produced) <= config.max_hypotheses

    for hyp in produced:
        assert isinstance(hyp, MeaningHypothesis)
        # R5.2 — non-empty evidence_ids.
        assert len(hyp.evidence_ids) >= 1
        # R5.2 — all three metrics in [0,1].
        assert 0.0 <= hyp.confidence <= 1.0
        assert 0.0 <= hyp.ambiguity <= 1.0
        assert 0.0 <= hyp.overread_risk <= 1.0


# ---------------------------------------------------------------------------
# Property 18 (task 11.3) — near-tie hypotheses raise ambiguity
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 18: Near-tie hypotheses raise ambiguity —
# any two produced MeaningHypothesis whose Confidence values differ by at most the
# configured margin (default 0.08) have their Ambiguity increased without exceeding
# 1.0.
@settings(max_examples=100)
@given(
    annotations=context_annotations(with_evidence=True),
    report_pair=near_tie_reports(),
)
def test_property_18_near_tie_raises_ambiguity(annotations, report_pair):
    """Validates: Requirements 5.3"""

    report, report_ambiguity = report_pair
    config = Phase2Config()
    engine = make_engine(FakeSemanticEngine(report), FakeMeaningLayer(), config=config)

    produced, _debug = engine.generate(annotations, frame_id="frame")

    margin = config.ambiguity_margin
    confidences = [h.confidence for h in produced]

    raised_any = False
    for i, hyp in enumerate(produced):
        near_tie = any(
            j != i and abs(confidences[i] - confidences[j]) <= margin
            for j in range(len(confidences))
        )
        if not near_tie:
            continue
        raised_any = True
        # Ambiguity increased above the report baseline (R5.3)...
        assert hyp.ambiguity > report_ambiguity
        # ...and never exceeds 1.0.
        assert hyp.ambiguity <= 1.0

    # The strategy guarantees the top-2 confidences are within margin, so at least
    # one near-tie hypothesis must have been produced and checked.
    assert raised_any


# ---------------------------------------------------------------------------
# Property 19 (task 11.4) — insufficient-evidence fallback
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 19: Insufficient-evidence fallback — when
# no hypothesis can be supported by available evidence (no annotations, no
# evidence, or empty semantic report), the engine produces exactly one hypothesis
# flagged is_insufficient_evidence with Confidence below the configured low-conf
# threshold (default 0.2).
@settings(max_examples=100)
@given(
    mode=st.sampled_from(("no_annotations", "no_evidence", "empty_report")),
    annotations_with_ev=context_annotations(with_evidence=True),
    annotations_no_ev=context_annotations(with_evidence=False),
)
def test_property_19_insufficient_evidence_fallback(mode, annotations_with_ev, annotations_no_ev):
    """Validates: Requirements 5.4"""

    config = Phase2Config()

    if mode == "no_annotations":
        annotations = []
        # Report would have hypotheses, but no annotations short-circuits first.
        report = FakeReport([FakeSemanticHypothesis(confidence=0.9)])
    elif mode == "no_evidence":
        annotations = annotations_no_ev
        report = FakeReport([FakeSemanticHypothesis(confidence=0.9)])
    else:  # empty_report
        annotations = annotations_with_ev
        report = FakeReport(())  # semantic report yields no hypotheses

    engine = make_engine(FakeSemanticEngine(report), FakeMeaningLayer(), config=config)

    produced, _debug = engine.generate(annotations, frame_id="frame")

    # Exactly one hypothesis, flagged insufficient evidence, with low confidence.
    assert len(produced) == 1
    fallback = produced[0]
    assert fallback.is_insufficient_evidence is True
    assert fallback.confidence < config.meaning_low_conf
    # Invariant R5.2 still holds: evidence_ids stays non-empty (sentinel).
    assert len(fallback.evidence_ids) >= 1


# ---------------------------------------------------------------------------
# Property 20 (task 11.5) — ordering
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 20: Meaning hypotheses ordering — the
# produced set is sorted by Confidence descending, with ties broken by Ambiguity
# ascending.
@settings(max_examples=100)
@given(annotations=context_annotations(with_evidence=True), report=reports_with_hypotheses())
def test_property_20_ordering(annotations, report):
    """Validates: Requirements 5.5, 5.6"""

    engine = make_engine(FakeSemanticEngine(report), FakeMeaningLayer())

    produced, _debug = engine.generate(annotations, frame_id="frame")

    for earlier, later in zip(produced, produced[1:]):
        # R5.5 — descending confidence.
        assert earlier.confidence >= later.confidence
        # R5.6 — equal confidence tie-broken by ascending ambiguity.
        if earlier.confidence == later.confidence:
            assert earlier.ambiguity <= later.ambiguity


# ---------------------------------------------------------------------------
# Delegation spy (task 11.6) — WRAP confirmation
# ---------------------------------------------------------------------------
def test_delegation_spy_wraps_semantic_engine():
    """Validates: Requirements 5.7

    Khẳng định ``MeaningHypothesisEngine`` **uỷ quyền** việc chấm điểm semantic
    cho ``SemanticHypothesisEngine.compare`` (và làm giàu qua
    ``MeaningLayer.evaluate``) thay vì tự tính điểm. Dùng spy (``MagicMock``) cho
    cả hai dependency và xác nhận chúng được gọi khi có annotation kèm evidence.
    """

    report = FakeReport(
        [
            FakeSemanticHypothesis(label="request", confidence=0.8, margin_from_next=0.3),
            FakeSemanticHypothesis(label="statement", confidence=0.6, margin_from_next=0.1),
        ],
        ambiguity=0.2,
    )

    semantic_engine = MagicMock()
    semantic_engine.compare.return_value = report
    meaning_layer = MagicMock()
    meaning_layer.evaluate.return_value = FakeMeaningSlot(semantic_family="dialogue")

    engine = make_engine(semantic_engine, meaning_layer)

    observation = Observation(
        observation_id="obs-1",
        summary="please help me with this",
        evidence_ids=["ev-1", "ev-2"],
        confidence=0.7,
        source_element_id="elem-1",
    )
    annotation = ContextAnnotation(
        observation=observation,
        relationship="peer",
        register="casual",
        social_norm="neutral",
        unconfirmed_social=[],
        defaults_applied=[],
        confidence=0.7,
    )

    produced, _debug = engine.generate([annotation], frame_id="frame")

    # Delegation happened: scoring was obtained from the injected semantic engine.
    assert semantic_engine.compare.called
    assert semantic_engine.compare.call_count == 1
    # Meaning-slot enrichment was also delegated.
    assert meaning_layer.evaluate.called
    # And the produced hypotheses carry the delegated confidences (not recomputed).
    produced_confidences = sorted(h.confidence for h in produced)
    assert produced_confidences == [0.6, 0.8]
