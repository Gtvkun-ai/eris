# -*- coding: utf-8 -*-
"""test_sociocultural_context.py — Phase 2 stage 3 (SocioculturalContext) tests.

Covers tasks 9.2–9.5 của spec ``phase2-meaning-tom``:

- Property 14 (9.2) — Full sociocultural annotation when contexts present (R4.1, R4.5).
- Property 15 (9.3) — Social hypotheses remain unconfirmed (R4.2).
- Property 16 (9.4) — Neutral defaults applied and recorded (R4.3, R4.4).
- Unit (9.5) — empty observation set (R4.6).

Quy ước test: ``pytest`` + ``hypothesis``; ``tests/conftest.py`` đã chèn cả
``src`` (để import ``cortex.*``) lẫn ``tests`` (để import ``phase2_strategies``)
vào ``sys.path`` trước khi thu thập test. Mỗi property test dùng
``@settings(max_examples=100)`` và mang comment + docstring liên kết requirement.

Để có ``observations`` đưa vào ``SocioculturalContext.annotate(...)``, ta chạy các
stage phía trước trên một frame được sinh:
``FrameReadView(frame) -> WorldSceneBuilder().build(...) ->
WorldInterpreter().interpret(...) -> observations``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from cortex.global_workspace import WorkspaceFrame
from cortex.meaning.read_contract import FrameReadView
from cortex.meaning.world_scene_builder import WorldSceneBuilder
from cortex.meaning.world_interpreter import WorldInterpreter
from cortex.meaning.sociocultural_context import (
    SocioculturalContext,
    NEUTRAL_RELATIONSHIP,
    NEUTRAL_REGISTER,
    NEUTRAL_SOCIAL_NORM,
)

from phase2_strategies import frames, social_hypotheses


# ---------------------------------------------------------------------------
# Helpers — chạy pipeline thượng nguồn để lấy observations + annotations
# ---------------------------------------------------------------------------
def _observations_for(frame):
    """Chạy WorldSceneBuilder -> WorldInterpreter trên ``frame`` -> observations."""

    view = FrameReadView(frame)
    scene, _ = WorldSceneBuilder().build(view.for_module("WorldSceneBuilder"))
    observations, _ = WorldInterpreter().interpret(scene)
    return observations


def _annotate(frame):
    """Chạy đầy đủ tới SocioculturalContext.annotate(...) trên ``frame``."""

    view = FrameReadView(frame)
    observations = _observations_for(frame)
    annotations, debug = SocioculturalContext().annotate(
        observations, view.for_module("SocioculturalContext")
    )
    return annotations, debug


def _hypothesis_text(hyp) -> str:
    """Phản chiếu logic ``SocioculturalContext._hypothesis_text`` cho assertion."""

    label = getattr(hyp, "label", None)
    description = getattr(hyp, "description", None)
    if label is None:
        return str(hyp).strip()
    if description:
        return f"{label}: {description}"
    return str(label)


# ---------------------------------------------------------------------------
# Strategy dẫn xuất cục bộ
# ---------------------------------------------------------------------------
@st.composite
def frames_with_social(draw):
    """Frame có ≥1 broadcast item và ≥1 ``social_hypotheses`` (ba context khả dụng)."""

    frame = draw(frames(min_items=1, max_items=4))
    frame.social_hypotheses = draw(
        st.lists(social_hypotheses(), min_size=1, max_size=3)
    )
    return frame


@st.composite
def frames_without_contexts(draw):
    """Frame có ≥1 broadcast item nhưng KHÔNG có context nào khả dụng.

    ``social_hypotheses`` và ``forbidden_assumptions`` đều rỗng -> cả ba loại
    ngữ cảnh (relationship / register / social_norm) phải rơi về neutral default.
    """

    frame = draw(frames(min_items=1, max_items=4))
    frame.social_hypotheses = []
    frame.forbidden_assumptions = []
    return frame


# ---------------------------------------------------------------------------
# Property 14 (task 9.2)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 14: Full sociocultural annotation when
# contexts present — for any non-empty observation set where relationship,
# register, and social-norm contexts are all available, every produced
# annotation carries all three context types and a Confidence value in [0,1].
@settings(max_examples=100)
@given(frames(min_items=1, max_items=4))
def test_property_14_full_sociocultural_annotation(frame):
    """Validates: Requirements 4.1, 4.5

    Khi cả ba context khả dụng (frame có ``social_hypotheses`` không rỗng nên
    relationship/register/social_norm đều dẫn xuất là available), mỗi annotation
    mang đủ ba loại context ở dạng non-neutral. Nếu frame không đủ context, vẫn
    giữ bất biến yếu hơn: cả ba field được set (có thể neutral) và confidence ∈ [0,1].
    """

    annotations, _ = _annotate(frame)

    all_contexts_available = bool(frame.social_hypotheses)

    for ann in annotations:
        # Bất biến mạnh chung: cả ba field luôn được set (chuỗi không rỗng).
        assert isinstance(ann.relationship, str) and ann.relationship
        assert isinstance(ann.register, str) and ann.register
        assert isinstance(ann.social_norm, str) and ann.social_norm
        # Confidence luôn ∈ [0,1] (R4.5).
        assert 0.0 <= ann.confidence <= 1.0

        if all_contexts_available:
            # Đủ ba context -> non-neutral, không default nào được áp (R4.1).
            assert ann.relationship != NEUTRAL_RELATIONSHIP
            assert ann.register != NEUTRAL_REGISTER
            assert ann.social_norm != NEUTRAL_SOCIAL_NORM
            assert ann.defaults_applied == []


# ---------------------------------------------------------------------------
# Property 15 (task 9.3)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 15: Social hypotheses remain unconfirmed
# — for any WorkspaceFrame exposing social_hypotheses, all such hypotheses appear
# in the annotation's unconfirmed bucket and none are treated as confirmed fact.
@settings(max_examples=100)
@given(frames_with_social())
def test_property_15_social_hypotheses_remain_unconfirmed(frame):
    """Validates: Requirements 4.2

    Mọi ``social_hypotheses`` của frame xuất hiện trong ``unconfirmed_social`` của
    mỗi annotation, và không cái nào bị ghi vào relationship/register/social_norm
    như sự thật đã xác nhận.
    """

    annotations, _ = _annotate(frame)

    expected_texts = {_hypothesis_text(h) for h in frame.social_hypotheses}
    # Frame có ≥1 item -> chắc chắn có annotation để kiểm.
    assert annotations

    for ann in annotations:
        # Tất cả social hypotheses nằm trong bucket unconfirmed (R4.2).
        assert set(ann.unconfirmed_social) == expected_texts
        # Không hypothesis nào bị coi là fact đã xác nhận trong ba context field.
        for text in expected_texts:
            assert ann.relationship != text
            assert ann.register != text
            assert ann.social_norm != text


# ---------------------------------------------------------------------------
# Property 16 (task 9.4)
# ---------------------------------------------------------------------------
# Feature: phase2-meaning-tom, Property 16: Neutral defaults applied and recorded
# — for any observation set where one or more of the three context types is
# unavailable, each missing context type is set to its predefined neutral default
# and recorded in the per-type defaults-applied record.
@settings(max_examples=100)
@given(frames_without_contexts())
def test_property_16_neutral_defaults_applied_and_recorded(frame):
    """Validates: Requirements 4.3, 4.4

    Frame không có context nào khả dụng (``social_hypotheses`` rỗng và
    ``forbidden_assumptions`` rỗng) -> cả ba context field bằng neutral default và
    cả ba loại được ghi vào ``defaults_applied``.
    """

    annotations, _ = _annotate(frame)

    # Frame có ≥1 item -> chắc chắn có annotation để kiểm.
    assert annotations

    for ann in annotations:
        assert ann.relationship == NEUTRAL_RELATIONSHIP
        assert ann.register == NEUTRAL_REGISTER
        assert ann.social_norm == NEUTRAL_SOCIAL_NORM
        # Mỗi loại thiếu được ghi nhận theo từng loại (R4.4).
        assert set(ann.defaults_applied) == {
            "relationship",
            "register",
            "social_norm",
        }
        assert 0.0 <= ann.confidence <= 1.0


# ---------------------------------------------------------------------------
# Unit (task 9.5) — empty observation set (R4.6)
# ---------------------------------------------------------------------------
def test_empty_observation_set_yields_no_annotations():
    """Validates: Requirements 4.6

    ``annotate([], view)`` trả ``[]`` (không annotation) và không ném lỗi.
    """

    frame = WorkspaceFrame(
        frame_id="frame-empty-obs",
        timestamp=0.0,
        budget_mode="normal",
        downstream_contract={
            "SocioculturalContext": [
                "frame_id",
                "social_hypotheses",
                "forbidden_assumptions",
            ]
        },
    )
    view = FrameReadView(frame).for_module("SocioculturalContext")

    annotations, debug = SocioculturalContext().annotate([], view)

    assert annotations == []
    assert debug.stage == "SocioculturalContext"
