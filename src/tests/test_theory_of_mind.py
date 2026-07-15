# -*- coding: utf-8 -*-
"""tests/test_theory_of_mind.py — TheoryOfMindCore + cộng sự (stage 6) tests.

Bao phủ các task của spec ``phase2-meaning-tom``:

- Unit (3.2) — ``StageLedger.record``/``has`` per ``(stage, frame_id)`` (R7.2).
- Property 24 (14.5) — mental-state inferences bounded and supported
  (R7.6, R7.7, R11.2).
- Property 25 (14.6) — ``MentalStateRanker.rank`` ordering (R7.3).
- Property 26 (14.7) — ``CounterfactualCorrector.correct`` reduction (R7.4).
- Unit (14.8) — ordering violation + history-absent + positive ordering
  (R7.2, R7.8, R13.3, R13.4).

Quy ước: ``pytest`` + ``hypothesis``; ``tests/conftest.py`` chèn ``src`` vào
``sys.path`` nên import ``cortex.*`` hoạt động. Mỗi property-based test cấu hình
``@settings(max_examples=100)`` và gắn comment
``# Feature: phase2-meaning-tom, Property {n}: {text}``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from cortex.tom import (
    Counterfactual,
    CounterfactualCorrector,
    MentalStateInference,
    MentalStateRanker,
    TheoryOfMindCore,
    ToMHistory,
)
from cortex.meaning.config import StageLedger
from cortex.meaning.contracts import MeaningHypothesis, PragmaticIntent
from cortex.meaning.taxonomy import Taxonomy


# ---------------------------------------------------------------------------
# Hằng số / strategies dùng chung
# ---------------------------------------------------------------------------
_MEANING_CATEGORIES: tuple[str, ...] = tuple(sorted(Taxonomy.MEANING))
_INTENT_CATEGORIES: tuple[str, ...] = tuple(sorted(Taxonomy.INTENT))
_MENTAL_STATE_CATEGORIES: tuple[str, ...] = tuple(sorted(Taxonomy.MENTAL_STATE))

_MEANING_STAGE = "MeaningHypothesisEngine"
_PRAGMATIC_STAGE = "PragmaticIntentEngine"


def _unit_floats() -> st.SearchStrategy[float]:
    """Float trong [0.0, 1.0] (không NaN/inf)."""

    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def _ledger_with_both(frame_id: str) -> StageLedger:
    """Một ``StageLedger`` đã ghi nhận CẢ HAI stage tiền đề cho ``frame_id``."""

    ledger = StageLedger()
    ledger.record(_MEANING_STAGE, frame_id)
    ledger.record(_PRAGMATIC_STAGE, frame_id)
    return ledger


@st.composite
def meaning_and_intents(draw) -> tuple[list[MeaningHypothesis], list[PragmaticIntent]]:
    """Sinh ``(meaning, intents)`` hợp lệ để feed ``TheoryOfMindCore.infer``.

    - ``meaning`` có id xác định ``h0..h{n-1}`` để intent tham chiếu được.
    - Mỗi intent ở một trong hai chế độ:
      * ``existing`` — ``supporting_meaning_ids`` là tập con id meaning đang có
        (⇒ inference dẫn xuất phải ``unsupported=False``).
      * ``missing``  — toàn bộ id KHÔNG khớp meaning nào (prefix ``MISSING_``)
        (⇒ inference dẫn xuất phải ``unsupported=True``) — exercise R7.7.
    """

    n = draw(st.integers(min_value=1, max_value=5))
    meaning = [
        MeaningHypothesis(
            hypothesis_id=f"h{i}",
            category=draw(st.sampled_from(_MEANING_CATEGORIES)),
            summary="",
            evidence_ids=[f"e{i}"],
            confidence=draw(_unit_floats()),
            ambiguity=draw(_unit_floats()),
            overread_risk=draw(_unit_floats()),
        )
        for i in range(n)
    ]
    meaning_ids = [h.hypothesis_id for h in meaning]

    num_intents = draw(st.integers(min_value=1, max_value=5))
    intents: list[PragmaticIntent] = []
    for j in range(num_intents):
        mode = draw(st.sampled_from(["existing", "missing"]))
        if mode == "existing":
            support = draw(
                st.lists(st.sampled_from(meaning_ids), min_size=1, max_size=n, unique=True)
            )
        else:
            support = draw(
                st.lists(
                    st.integers(min_value=0, max_value=50).map(lambda k: f"MISSING_{k}"),
                    min_size=1,
                    max_size=3,
                    unique=True,
                )
            )
        intents.append(
            PragmaticIntent(
                intent_id=f"i{j}",
                category=draw(st.sampled_from(_INTENT_CATEGORIES)),
                confidence=draw(_unit_floats()),
                supporting_meaning_ids=support,
                overread_risk=draw(_unit_floats()),
            )
        )

    return meaning, intents


# ===========================================================================
# Unit (task 3.2) — StageLedger
# ===========================================================================
def test_stage_ledger_record_and_has_per_stage_and_frame() -> None:
    """Validates: Requirements 7.2.

    ``record``/``has`` hoạt động theo từng cặp ``(stage, frame_id)``; ``has``
    trả False cho frame khác hoặc stage chưa ghi; ghi lại cùng cặp idempotent.
    """

    ledger = StageLedger()

    # Chưa ghi gì → has() luôn False.
    assert ledger.has(_MEANING_STAGE, "frameA") is False

    ledger.record(_MEANING_STAGE, "frameA")
    assert ledger.has(_MEANING_STAGE, "frameA") is True

    # frame_id khác → False (ledger phân biệt theo frame).
    assert ledger.has(_MEANING_STAGE, "frameB") is False

    # stage khác cho cùng frame → False (chưa ghi).
    assert ledger.has(_PRAGMATIC_STAGE, "frameA") is False

    ledger.record(_PRAGMATIC_STAGE, "frameA")
    assert ledger.has(_PRAGMATIC_STAGE, "frameA") is True

    # Idempotent: ghi lại cùng cặp không thay đổi kết quả, không lỗi.
    ledger.record(_MEANING_STAGE, "frameA")
    ledger.record(_MEANING_STAGE, "frameA")
    assert ledger.has(_MEANING_STAGE, "frameA") is True


# ===========================================================================
# Property 24 (task 14.5) — mental-state inferences bounded and supported
# ===========================================================================
# Feature: phase2-meaning-tom, Property 24: Mental-state inferences are bounded, categorized, and support-flagged
@settings(max_examples=100)
@given(payload=meaning_and_intents())
def test_property_24_inferences_bounded_and_support_flagged(
    payload: tuple[list[MeaningHypothesis], list[PragmaticIntent]],
) -> None:
    """Validates: Requirements 7.6, 7.7, 11.2.

    Với ledger đã ghi cả hai stage tiền đề cho ``frame_id``, cho BẤT KỲ
    meaning+intents: mọi inference có ``confidence ∈ [0,1]``, ``category`` ∈
    ``Taxonomy.MENTAL_STATE``; inference gắn được supporter có ``unsupported=False``
    và ids ⊆ meaning ids; inference không gắn được supporter nào vẫn được sinh
    nhưng ``unsupported=True`` với ``supporting_meaning_ids`` rỗng.
    """

    meaning, intents = payload
    frame_id = "frame-24"
    ledger = _ledger_with_both(frame_id)
    meaning_ids = {h.hypothesis_id for h in meaning}

    inferences, _debug = TheoryOfMindCore().infer(
        meaning=meaning,
        intents=intents,
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=[], available=True),
    )

    # Một inference cho mỗi intent (không bị nuốt).
    assert len(inferences) == len(intents)

    for inf in inferences:
        assert 0.0 <= inf.confidence <= 1.0
        assert inf.category in Taxonomy.MENTAL_STATE
        if inf.supporting_meaning_ids:
            assert inf.unsupported is False
            assert set(inf.supporting_meaning_ids) <= meaning_ids
        else:
            assert inf.unsupported is True


# Feature: phase2-meaning-tom, Property 24: Mental-state inferences are bounded, categorized, and support-flagged
@settings(max_examples=100)
@given(
    category=st.sampled_from(_INTENT_CATEGORIES),
    confidence=_unit_floats(),
    overread_risk=_unit_floats(),
    missing_ids=st.lists(
        st.integers(min_value=0, max_value=50).map(lambda k: f"NOPE_{k}"),
        min_size=1,
        max_size=3,
        unique=True,
    ),
)
def test_property_24_unsupported_intent_still_produces_flagged_inference(
    category: str,
    confidence: float,
    overread_risk: float,
    missing_ids: list[str],
) -> None:
    """Validates: Requirements 7.7.

    Một intent mà ``supporting_meaning_ids`` không khớp meaning nào vẫn sinh
    đúng một inference, được đánh ``unsupported=True``.
    """

    frame_id = "frame-24b"
    ledger = _ledger_with_both(frame_id)
    meaning = [
        MeaningHypothesis(
            hypothesis_id="h0",
            category=_MEANING_CATEGORIES[0],
            summary="",
            evidence_ids=["e0"],
            confidence=0.5,
            ambiguity=0.0,
            overread_risk=0.0,
        )
    ]
    intent = PragmaticIntent(
        intent_id="i0",
        category=category,
        confidence=confidence,
        supporting_meaning_ids=missing_ids,
        overread_risk=overread_risk,
    )

    inferences, _debug = TheoryOfMindCore().infer(
        meaning=meaning,
        intents=[intent],
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=[], available=True),
    )

    assert len(inferences) == 1
    assert inferences[0].unsupported is True
    assert inferences[0].supporting_meaning_ids == []
    assert inferences[0].category in Taxonomy.MENTAL_STATE


# ===========================================================================
# Property 25 (task 14.6) — ranking order
# ===========================================================================
@st.composite
def _mental_state_inferences(draw) -> list[MentalStateInference]:
    """Danh sách ``MentalStateInference`` với confidence/overread_risk đa dạng."""

    size = draw(st.integers(min_value=0, max_value=8))
    return [
        MentalStateInference(
            inference_id=f"m{i}",
            category=draw(st.sampled_from(_MENTAL_STATE_CATEGORIES)),
            summary="",
            confidence=draw(_unit_floats()),
            overread_risk=draw(_unit_floats()),
            supporting_meaning_ids=[f"h{i}"],
        )
        for i in range(size)
    ]


# Feature: phase2-meaning-tom, Property 25: Ranking orders by confidence desc then overread_risk asc
@settings(max_examples=100)
@given(inferences=_mental_state_inferences())
def test_property_25_ranking_order(inferences: list[MentalStateInference]) -> None:
    """Validates: Requirements 7.3.

    ``MentalStateRanker.rank`` xếp giảm dần theo ``confidence``; bằng confidence
    → ``overread_risk`` tăng dần. Khóa ``(-confidence, overread_risk)`` của các
    phần tử liên tiếp phải không giảm theo thứ tự từ điển.
    """

    ranked = MentalStateRanker().rank(inferences)

    # rank() không làm mất/đổi tập phần tử (cùng đa tập).
    assert len(ranked) == len(inferences)

    for a, b in zip(ranked, ranked[1:]):
        key_a = (-a.confidence, a.overread_risk)
        key_b = (-b.confidence, b.overread_risk)
        assert key_a <= key_b


def test_property_25_ranking_explicit_tie_break() -> None:
    """Validates: Requirements 7.3.

    Ví dụ tường minh: confidence cao xếp trước; khi confidence bằng nhau,
    overread_risk thấp hơn xếp trên.
    """

    def mk(iid: str, conf: float, risk: float) -> MentalStateInference:
        return MentalStateInference(
            inference_id=iid,
            category=_MENTAL_STATE_CATEGORIES[0],
            summary="",
            confidence=conf,
            overread_risk=risk,
            supporting_meaning_ids=["h0"],
        )

    low = mk("low", 0.2, 0.1)
    tie_high_risk = mk("tie_high_risk", 0.8, 0.9)
    tie_low_risk = mk("tie_low_risk", 0.8, 0.1)

    ranked = MentalStateRanker().rank([low, tie_high_risk, tie_low_risk])

    assert [inf.inference_id for inf in ranked] == ["tie_low_risk", "tie_high_risk", "low"]


# ===========================================================================
# Property 26 (task 14.7) — counterfactual reduction stays in range and recorded
# ===========================================================================
def _make_inference(confidence: float, overread_risk: float = 0.0) -> MentalStateInference:
    return MentalStateInference(
        inference_id="m0",
        category=_MENTAL_STATE_CATEGORIES[0],
        summary="",
        confidence=confidence,
        overread_risk=overread_risk,
        supporting_meaning_ids=["h0"],
    )


# Feature: phase2-meaning-tom, Property 26: Qualifying counterfactual reduces confidence and records reason
@settings(max_examples=100)
@given(
    inf_conf=_unit_floats(),
    threshold=_unit_floats(),
    cf_conf=_unit_floats(),
    explanation=st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        min_size=1,
        max_size=30,
    ),
)
def test_property_26_counterfactual_correction(
    inf_conf: float,
    threshold: float,
    cf_conf: float,
    explanation: str,
) -> None:
    """Validates: Requirements 7.4.

    Với counterfactual ``confidence ≥ threshold``: ``correct`` hạ confidence về
    giá trị ∈ [0.0, original] và ghi ``counterfactual_reason``. Với
    ``confidence < threshold``: inference giữ nguyên (confidence + reason rỗng).
    """

    inference = _make_inference(inf_conf)
    counterfactual = Counterfactual(explanation=explanation, confidence=cf_conf)

    result = CounterfactualCorrector().correct(
        inference, [counterfactual], threshold=threshold
    )

    if counterfactual.confidence >= threshold:
        assert 0.0 <= result.confidence <= inference.confidence
        assert result.counterfactual_reason == explanation
    else:
        assert result.confidence == inference.confidence
        assert result.counterfactual_reason == ""


def test_property_26_below_threshold_leaves_unchanged_explicit() -> None:
    """Validates: Requirements 7.4.

    Ví dụ tường minh: counterfactual yếu (dưới threshold) không đổi inference.
    """

    inference = _make_inference(0.8)
    weak = Counterfactual(explanation="weak alt", confidence=0.3)

    result = CounterfactualCorrector().correct(inference, [weak], threshold=0.5)

    assert result.confidence == 0.8
    assert result.counterfactual_reason == ""


# ===========================================================================
# Unit (task 14.8) — ordering violation + history-absent + positive ordering
# ===========================================================================
def _sample_meaning() -> list[MeaningHypothesis]:
    return [
        MeaningHypothesis(
            hypothesis_id="h0",
            category=_MEANING_CATEGORIES[0],
            summary="",
            evidence_ids=["e0"],
            confidence=0.6,
            ambiguity=0.1,
            overread_risk=0.0,
        )
    ]


def _sample_intents() -> list[PragmaticIntent]:
    return [
        PragmaticIntent(
            intent_id="i0",
            category=_INTENT_CATEGORIES[0],
            confidence=0.6,
            supporting_meaning_ids=["h0"],
            overread_risk=0.0,
        )
    ]


def test_ordering_violation_when_meaning_stage_missing() -> None:
    """Validates: Requirements 7.2, 13.3.

    Ledger chưa ghi ``MeaningHypothesisEngine`` cho frame → ``infer`` trả ``[]``
    và ghi vi phạm thứ tự (missing_fields + notes).
    """

    frame_id = "frame-violation-meaning"
    ledger = StageLedger()  # không ghi gì

    inferences, debug = TheoryOfMindCore().infer(
        meaning=_sample_meaning(),
        intents=_sample_intents(),
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=[], available=True),
    )

    assert inferences == []
    assert _MEANING_STAGE in debug.missing_fields
    joined = " ".join(debug.notes).lower()
    assert "cannot run" in joined
    assert _MEANING_STAGE.lower() in joined


def test_ordering_violation_when_pragmatic_stage_missing() -> None:
    """Validates: Requirements 7.2, 13.3.

    Ledger ghi Meaning nhưng thiếu ``PragmaticIntentEngine`` → ``infer`` trả
    ``[]`` và ghi vi phạm với stage còn thiếu là Pragmatic.
    """

    frame_id = "frame-violation-pragmatic"
    ledger = StageLedger()
    ledger.record(_MEANING_STAGE, frame_id)  # chỉ ghi Meaning

    inferences, debug = TheoryOfMindCore().infer(
        meaning=_sample_meaning(),
        intents=_sample_intents(),
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=[], available=True),
    )

    assert inferences == []
    assert _PRAGMATIC_STAGE in debug.missing_fields
    joined = " ".join(debug.notes).lower()
    assert _PRAGMATIC_STAGE.lower() in joined


def test_history_unavailable_records_note_and_still_runs() -> None:
    """Validates: Requirements 7.8.

    Ledger thỏa mãn nhưng ``history.available is False`` → ``infer`` vẫn chạy và
    ghi "history unavailable" vào debug notes.
    """

    frame_id = "frame-history-absent"
    ledger = _ledger_with_both(frame_id)

    inferences, debug = TheoryOfMindCore().infer(
        meaning=_sample_meaning(),
        intents=_sample_intents(),
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=[], available=False),
    )

    # Vẫn chạy tiếp: sinh inference từ intent.
    assert len(inferences) == 1
    joined = " ".join(debug.notes).lower()
    assert "history unavailable" in joined


def test_positive_ordering_produces_output_without_violation() -> None:
    """Validates: Requirements 13.4.

    Ledger có cả hai stage cho frame → ``infer`` sinh output, không có vi phạm
    thứ tự (không missing_fields, không thông điệp "cannot run").
    """

    frame_id = "frame-positive"
    ledger = _ledger_with_both(frame_id)

    inferences, debug = TheoryOfMindCore().infer(
        meaning=_sample_meaning(),
        intents=_sample_intents(),
        ledger=ledger,
        frame_id=frame_id,
        history=ToMHistory(items=["prior"], available=True),
    )

    assert len(inferences) == 1
    assert debug.missing_fields == []
    joined = " ".join(debug.notes).lower()
    assert "cannot run" not in joined
