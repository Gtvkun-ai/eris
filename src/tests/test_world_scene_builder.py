# -*- coding: utf-8 -*-
"""test_world_scene_builder.py — Phase 2 stage 1 & 2 tests (WorldSceneBuilder +
WorldInterpreter) and the WorkspaceFrame-only read boundary (FrameReadView).

Covers spec tasks 4.2, 6.2–6.8, 7.4, 7.5 of ``phase2-meaning-tom``.

Conventions:
- pytest + hypothesis.
- ``tests/conftest.py`` puts ``src/`` and ``tests/`` on ``sys.path`` so the
  ``cortex.*`` and ``phase2_strategies`` imports below resolve without install.
- Every property-based test uses ``@settings(max_examples=100)`` (minimum) and a
  leading ``# Feature: phase2-meaning-tom, Property N: ...`` comment, plus a
  docstring noting the requirements it validates.
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from phase2_strategies import (
    REQUIRED_FRAME_FIELDS,
    empty_frames,
    frames,
    frames_missing_field,
)

from cortex.global_workspace import WorkspaceFrame, WorkspaceItem
from cortex.meaning.contracts import (
    InvalidWorkspaceFrameError,
    RawWorldAccessError,
    WorldScene,
    WorldSceneValidationError,
)
from cortex.meaning.read_contract import FrameReadView
from cortex.meaning.world_interpreter import WorldInterpreter
from cortex.meaning.world_scene_builder import WorldSceneBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# downstream_contract dùng cho các unit test dựng frame trực tiếp — đồng bộ với
# hợp đồng mặc định mà strategy ``frames()`` gắn cho WorldSceneBuilder (R1.3).
_BUILDER_CONTRACT: dict[str, list[str]] = {
    "WorldSceneBuilder": [
        "frame_id",
        "broadcast_items",
        "active_threads",
        "dominant_thread",
        "broadcast_reason",
    ],
}

# Tập field mà builder thực sự đọc qua hợp đồng và nằm trong REQUIRED_FRAME_FIELDS.
# Khi một field trong tập này bị bỏ, builder PHẢI ghi nhận missing + cap confidence.
_BUILDER_READ_REQUIRED: frozenset[str] = frozenset(
    {"broadcast_items", "active_threads", "broadcast_reason"}
)


def _view(frame: WorkspaceFrame) -> FrameReadView:
    """Bọc ``frame`` trong view đã scope cho WorldSceneBuilder."""

    return FrameReadView(frame).for_module("WorldSceneBuilder")


def _all_elements(scene: WorldScene):
    """Mọi element của scene (entities + salient_signals + active_threads)."""

    return list(scene.entities) + list(scene.salient_signals) + list(scene.active_threads)


@st.composite
def _frames_with_dominant(draw) -> WorkspaceFrame:
    """Frame có ``dominant_thread`` luôn khác ``None`` (Property 8)."""

    frame = draw(frames(min_items=1, max_items=4))
    if not frame.active_threads:
        frame.active_threads = ["thread_alpha"]
    if frame.dominant_thread is None:
        frame.dominant_thread = frame.active_threads[0]
    return frame


def _make_frame(**overrides) -> WorkspaceFrame:
    """Dựng một ``WorkspaceFrame`` tối thiểu hợp lệ cho unit test."""

    kwargs = dict(
        frame_id="frame-unit",
        timestamp=0.0,
        budget_mode="normal",
        broadcast_items=[],
        active_threads=[],
        dominant_thread=None,
        broadcast_reason="unit",
        downstream_contract={k: list(v) for k, v in _BUILDER_CONTRACT.items()},
    )
    kwargs.update(overrides)
    return WorkspaceFrame(**kwargs)


# ===========================================================================
# Property 7 (task 6.2) — WorldScene structure & confidence bounds
# ===========================================================================
# Feature: phase2-meaning-tom, Property 7: WorldScene structure and confidence bounds
@settings(max_examples=100)
@given(frame=frames(min_items=1, max_items=4))
def test_world_scene_structure_and_confidence_bounds(frame):
    """For any frame with >=1 broadcast item, build() yields exactly one
    WorldScene exposing entities/salient_signals/active_threads, and every
    element confidence is in [0,1].

    Validates: Requirements 2.1, 2.2
    """

    scene, _debug = WorldSceneBuilder().build(_view(frame))

    assert isinstance(scene, WorldScene)
    assert isinstance(scene.entities, list)
    assert isinstance(scene.salient_signals, list)
    assert isinstance(scene.active_threads, list)
    # >=1 broadcast item -> a non-empty scene (exactly one scene object).
    assert scene.is_empty is False
    assert 0.0 <= scene.confidence <= 1.0
    for element in _all_elements(scene):
        assert 0.0 <= element.confidence <= 1.0


# ===========================================================================
# Property 8 (task 6.3) — Exactly one dominant focus when dominant_thread present
# ===========================================================================
# Feature: phase2-meaning-tom, Property 8: Exactly one dominant focus when dominant_thread present
@settings(max_examples=100)
@given(frame=_frames_with_dominant())
def test_exactly_one_dominant_focus(frame):
    """For any frame exposing a dominant_thread, exactly one WorldScene element
    is marked is_dominant_focus.

    Validates: Requirements 2.3
    """

    assume(frame.dominant_thread is not None)

    scene, _debug = WorldSceneBuilder().build(_view(frame))

    dominant = [e for e in _all_elements(scene) if e.is_dominant_focus]
    assert len(dominant) == 1


# ===========================================================================
# Property 9 (task 6.4) — Empty-frame yields exactly one empty scene
# ===========================================================================
# Feature: phase2-meaning-tom, Property 9: Empty-frame yields exactly one empty scene
@settings(max_examples=100)
@given(frame=empty_frames())
def test_empty_frame_yields_one_empty_scene(frame):
    """For any frame with no broadcast items, build() returns one WorldScene
    with is_empty True and a non-empty reason.

    Validates: Requirements 2.4
    """

    scene, _debug = WorldSceneBuilder().build(_view(frame))

    assert isinstance(scene, WorldScene)
    assert scene.is_empty is True
    assert scene.entities == []
    assert scene.salient_signals == []
    assert isinstance(scene.reason, str) and scene.reason != ""


# ===========================================================================
# Property 10 (task 6.5) — Evidence_id preservation
# ===========================================================================
# Feature: phase2-meaning-tom, Property 10: Evidence_id preservation
@settings(max_examples=100)
@given(frame=frames(min_items=1, max_items=4))
def test_evidence_id_preservation(frame):
    """For any frame, every evidence_id carried by a scene element is preserved
    unmodified from the originating WorkspaceItem.evidence_ids.

    Validates: Requirements 2.5
    """

    scene, _debug = WorldSceneBuilder().build(_view(frame))

    # Map item id -> các danh sách evidence (xử lý id trùng nhau an toàn).
    id_to_ev_lists: dict[str, list[list[str]]] = defaultdict(list)
    for item in frame.broadcast_items:
        id_to_ev_lists[str(item.id)].append(list(item.evidence_ids))

    # entities + salient_signals đều dẫn xuất từ broadcast_items.
    for element in list(scene.entities) + list(scene.salient_signals):
        candidate_lists = id_to_ev_lists.get(element.source_item_id, [])
        assert element.evidence_ids in candidate_lists


# ===========================================================================
# Property 5 (task 6.6) — Frame_id traceability
# ===========================================================================
# Feature: phase2-meaning-tom, Property 5: Frame_id traceability
@settings(max_examples=100)
@given(frame=frames(min_items=0, max_items=4))
def test_frame_id_traceability(frame):
    """For any frame, the produced WorldScene.frame_id == frame.frame_id.

    Validates: Requirements 1.5, 12.4
    """

    scene, _debug = WorldSceneBuilder().build(_view(frame))
    assert scene.frame_id == frame.frame_id


# ===========================================================================
# Property 6 (task 6.7) — Missing-field confidence cap
# ===========================================================================
# Feature: phase2-meaning-tom, Property 6: Missing-field confidence cap
@settings(max_examples=100)
@given(frame=frames_missing_field())
def test_missing_field_confidence_cap(frame):
    """For any frame missing a required field, the produced scene has
    confidence <= 0.5; when the omitted field is one the builder reads, its name
    appears in StageDebug.missing_fields. Fields outside the builder's contract
    (selected_evidence / downstream_contract) must still produce a valid scene
    without crashing.

    Validates: Requirements 1.6
    """

    omitted = frame.debug["_omitted_required_field"]
    assert omitted in REQUIRED_FRAME_FIELDS

    scene, debug = WorldSceneBuilder().build(_view(frame))

    # Luôn trả về một scene hợp lệ, confidence hợp lệ.
    assert isinstance(scene, WorldScene)
    assert 0.0 <= scene.confidence <= 1.0

    if omitted in _BUILDER_READ_REQUIRED:
        # Field nằm trong hợp đồng builder đọc -> cap confidence + ghi tên field.
        assert scene.confidence <= 0.5
        assert omitted in debug.missing_fields
    else:
        # Field ngoài contract của builder (selected_evidence / downstream_contract):
        # builder KHÔNG đọc field này nên không thể (và không nên) report nó là
        # thiếu — confidence không bị cap. Ta chỉ ràng buộc "no crash + valid scene"
        # (đã assert ở trên). Builder không được ghi sai một field ngoài hợp đồng.
        assert omitted not in debug.missing_fields


# ===========================================================================
# Unit edge cases (task 6.8) — build(None) + malformed broadcast_items
# ===========================================================================
def test_build_none_returns_empty_scene():
    """build(None) -> empty scene, confidence 0.0, is_empty True (no frame read).

    Validates: Requirements 1.4
    """

    scene, debug = WorldSceneBuilder().build(None)

    assert isinstance(scene, WorldScene)
    assert scene.is_empty is True
    assert scene.confidence == 0.0
    assert scene.frame_id is None
    assert debug.confidence == 0.0


def test_malformed_broadcast_items_raises():
    """A frame whose broadcast_items is not a list -> InvalidWorkspaceFrameError.

    Validates: Requirements 2.6
    """

    frame = _make_frame()
    # Cố tình làm hỏng cấu trúc: broadcast_items không phải list.
    frame.broadcast_items = 123  # type: ignore[assignment]

    with pytest.raises(InvalidWorkspaceFrameError):
        WorldSceneBuilder().build(_view(frame))


# ===========================================================================
# Property 13 (task 7.4) — Low-confidence propagation (WorldInterpreter)
# ===========================================================================
# Feature: phase2-meaning-tom, Property 13: Low-confidence propagation
@settings(max_examples=100)
@given(
    frame=frames(min_items=1, max_items=4),
    threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_low_confidence_propagation(frame, threshold):
    """For any scene, every observation derived from an element whose confidence
    is below the threshold is marked low_confidence.

    Validates: Requirements 3.3
    """

    scene, _debug = WorldSceneBuilder().build(_view(frame))
    observations, _odbg = WorldInterpreter().interpret(scene, low_conf_threshold=threshold)

    for obs in observations:
        if obs.confidence < threshold:
            assert obs.low_confidence is True
        else:
            assert obs.low_confidence is False


# ===========================================================================
# Unit (task 7.5) — WorldInterpreter scene-invalid handling
# ===========================================================================
def test_interpret_none_raises():
    """interpret(None) raises WorldSceneValidationError.

    Validates: Requirements 3.5
    """

    with pytest.raises(WorldSceneValidationError):
        WorldInterpreter().interpret(None)  # type: ignore[arg-type]


def test_interpret_non_scene_raises():
    """interpret(a non-WorldScene) raises WorldSceneValidationError.

    Validates: Requirements 3.5
    """

    with pytest.raises(WorldSceneValidationError):
        WorldInterpreter().interpret("not a scene")  # type: ignore[arg-type]


def test_interpret_valid_empty_scene_returns_empty():
    """A validly-empty scene (is_empty True) returns [] without raising.

    Validates: Requirements 3.5
    """

    empty_scene = WorldScene(
        frame_id="frame-unit",
        entities=[],
        salient_signals=[],
        active_threads=[],
        confidence=0.0,
        is_empty=True,
        reason="no broadcast items",
    )

    observations, _debug = WorldInterpreter().interpret(empty_scene)
    assert observations == []


# ===========================================================================
# Task 4.2 — RawWorldAccessError on out-of-contract read (FrameReadView)
# ===========================================================================
def test_raw_world_access_error_on_out_of_contract_read():
    """Reading a field outside the builder's downstream_contract via
    FrameReadView raises RawWorldAccessError naming module+field, does not
    mutate frame data, and appends the violation to debug['contract_violations'].

    Validates: Requirements 1.2
    """

    frame = _make_frame()
    frame.selected_affect = "intact-affect"  # field hợp lệ nhưng NGOÀI hợp đồng
    view = FrameReadView(frame).for_module("WorldSceneBuilder")

    with pytest.raises(RawWorldAccessError) as excinfo:
        view.read("selected_affect")

    err = excinfo.value
    assert err.module_name == "WorldSceneBuilder"
    assert err.field_name == "selected_affect"

    # Lần đọc bị từ chối KHÔNG mutate dữ liệu của frame.
    assert frame.selected_affect == "intact-affect"

    # Vi phạm được ghi vào debug.contract_violations (R1.2).
    violations = frame.debug.get("contract_violations", [])
    assert any(
        v.get("module") == "WorldSceneBuilder" and v.get("field") == "selected_affect"
        for v in violations
    )
