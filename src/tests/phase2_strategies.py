# -*- coding: utf-8 -*-
"""phase2_strategies.py — shared hypothesis strategies cho property test Phase 2.

Module helper dùng chung cho toàn bộ bộ property-based test của Phase 2
(`test_world_scene_builder.py`, `test_meaning_hypothesis.py`,
`test_overread_brake.py`, `test_phase2_integration.py`, ...). Các test import
trực tiếp::

    from phase2_strategies import (
        frames, empty_frames, frames_missing_field,
        near_tie_hypotheses, evidenceless_candidates,
        conclusions_across_brake_bands,
    )

``tests/conftest.py`` chèn cả thư mục ``src`` (để import ``cortex.*``) lẫn thư
mục ``tests`` (để import được module này) vào ``sys.path`` trước khi pytest thu
thập test, nên các import trên hoạt động mà không cần cài đặt package.

Mọi strategy sinh ra **object hợp lệ** theo đúng chữ ký constructor trong
``cortex.global_workspace`` và ``cortex.meaning.contracts``:

- ``frames`` — ``WorkspaceFrame`` hợp lệ tổng quát (R13.8).
- ``empty_frames`` — frame không có ``broadcast_items`` (Property 9 / R2.4).
- ``frames_missing_field`` — frame thiếu một field bắt buộc (Property 6 / R1.6).
- ``near_tie_hypotheses`` — tập ``MeaningHypothesis`` có top-2 confidence sát nhau
  (Property 18 / R5.3 và Property 31 / R9.3).
- ``evidenceless_candidates`` — ``MeaningHypothesis`` không có evidence
  (Property 1 / R10.8 và Property 11 / R3.6).
- ``conclusions_across_brake_bands`` — conclusion trải các band ngưỡng
  ``OverreadBrake`` (Properties 27–29 / R8.1–R8.3).
"""

from __future__ import annotations

import math
import string

from hypothesis import strategies as st

from cortex.global_workspace import (
    WorkspaceFrame,
    WorkspaceItem,
    WorkspaceRisk,
    WorkspaceSocialHypothesis,
)
from cortex.meaning.contracts import MeaningHypothesis
from cortex.meaning.taxonomy import Taxonomy


__all__ = [
    "ids",
    "unit_floats",
    "workspace_items",
    "social_hypotheses",
    "workspace_risks",
    "frames",
    "empty_frames",
    "frames_missing_field",
    "near_tie_hypotheses",
    "evidenceless_candidates",
    "conclusions_across_brake_bands",
    "REQUIRED_FRAME_FIELDS",
]


# ---------------------------------------------------------------------------
# Hằng số literal-set lấy thẳng từ contract của WorkspaceFrame / WorkspaceItem
# ---------------------------------------------------------------------------
# Khớp ``WorkspaceItemKind`` trong cortex/global_workspace.py.
_ITEM_KINDS: tuple[str, ...] = (
    "user_request",
    "evidence",
    "memory",
    "affect",
    "homeostasis",
    "goal",
    "risk",
    "social_hypothesis",
    "body_state",
    "temporal",
    "constraint",
    "working_memory",
    "salience",
    "unknown",
)

# Khớp ``WorkspaceBudgetMode`` trong cortex/global_workspace.py.
_BUDGET_MODES: tuple[str, ...] = ("fast", "normal", "deep", "reflection")

# Category meaning hợp lệ (đi qua Taxonomy để strategy không sinh id ngoài họ).
_MEANING_CATEGORIES: tuple[str, ...] = tuple(sorted(Taxonomy.MEANING))

# Hợp đồng downstream mặc định: ánh xạ mỗi stage Phase 2 -> field được phép đọc.
# Liệt kê đúng các field thuộc WorkspaceFrame mà từng stage cần (design R1.3).
_DEFAULT_DOWNSTREAM_CONTRACT: dict[str, list[str]] = {
    "WorldSceneBuilder": [
        "frame_id",
        "broadcast_items",
        "active_threads",
        "dominant_thread",
        "broadcast_reason",
    ],
    "WorldInterpreter": ["frame_id"],
    "SocioculturalContext": [
        "frame_id",
        "social_hypotheses",
        "forbidden_assumptions",
    ],
    "MeaningHypothesisEngine": [
        "frame_id",
        "broadcast_items",
        "forbidden_assumptions",
    ],
    "PragmaticIntentEngine": ["frame_id"],
    "TheoryOfMindCore": ["frame_id", "forbidden_assumptions"],
}

# Field "bắt buộc" theo nghĩa của builder (R1.6): có thể bị thiếu/None mà vẫn
# dựng được WorkspaceFrame (frame_id/timestamp/budget_mode là bắt buộc khi khởi
# tạo nên không nằm trong danh sách này).
REQUIRED_FRAME_FIELDS: tuple[str, ...] = (
    "broadcast_items",
    "active_threads",
    "downstream_contract",
    "broadcast_reason",
    "selected_evidence",
)

_ID_ALPHABET = string.ascii_letters + string.digits + "_-"


# ---------------------------------------------------------------------------
# Strategy nền tảng
# ---------------------------------------------------------------------------
def ids(min_size: int = 1, max_size: int = 16) -> st.SearchStrategy[str]:
    """Chuỗi id không rỗng dùng cho ``frame_id``/``evidence_id``/thread id."""

    return st.text(alphabet=_ID_ALPHABET, min_size=min_size, max_size=max_size)


def unit_floats() -> st.SearchStrategy[float]:
    """Float trong [0.0, 1.0] (không NaN/inf) cho ``priority``/``confidence``..."""

    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def _safe_text(max_size: int = 40) -> st.SearchStrategy[str]:
    """Text ngắn, loại ký tự điều khiển/surrogate để summary luôn hiển thị được."""

    return st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        max_size=max_size,
    )


@st.composite
def workspace_items(draw, *, with_evidence: bool = True) -> WorkspaceItem:
    """Sinh một ``WorkspaceItem`` hợp lệ.

    - ``priority``/``confidence`` ∈ [0,1].
    - ``kind`` thuộc literal set ``WorkspaceItemKind``.
    - ``evidence_ids`` không rỗng khi ``with_evidence=True`` (mặc định).
    """

    min_ev = 1 if with_evidence else 0
    summary = draw(_safe_text())
    return WorkspaceItem(
        id=draw(ids()),
        kind=draw(st.sampled_from(_ITEM_KINDS)),
        content=summary,
        summary=summary,
        priority=draw(unit_floats()),
        confidence=draw(unit_floats()),
        evidence_ids=draw(st.lists(ids(), min_size=min_ev, max_size=4, unique=True)),
    )


@st.composite
def social_hypotheses(draw) -> WorkspaceSocialHypothesis:
    """Sinh một ``WorkspaceSocialHypothesis`` hợp lệ (confidence/overread ∈ [0,1])."""

    return WorkspaceSocialHypothesis(
        label=draw(ids()),
        description=draw(_safe_text()),
        confidence=draw(unit_floats()),
        overread_risk=draw(unit_floats()),
        evidence_ids=draw(st.lists(ids(), max_size=3, unique=True)),
        allowed_surface=draw(st.booleans()),
    )


@st.composite
def workspace_risks(draw) -> WorkspaceRisk:
    """Sinh một ``WorkspaceRisk`` hợp lệ (severity/confidence ∈ [0,1])."""

    return WorkspaceRisk(
        label=draw(ids()),
        severity=draw(unit_floats()),
        confidence=draw(unit_floats()),
        evidence_ids=draw(st.lists(ids(), max_size=3, unique=True)),
    )


# ---------------------------------------------------------------------------
# frames() — strategy WorkspaceFrame chính (R13.8)
# ---------------------------------------------------------------------------
@st.composite
def frames(
    draw,
    *,
    min_items: int = 0,
    max_items: int = 4,
    require_item_evidence: bool = True,
) -> WorkspaceFrame:
    """Sinh một ``WorkspaceFrame`` hợp lệ dùng chung cho property test.

    - ``frame_id`` không rỗng, ``timestamp`` float hữu hạn, ``budget_mode`` hợp lệ.
    - 0..N ``broadcast_items`` (mỗi item có ``evidence_ids`` không rỗng theo mặc
      định, ``priority``/``confidence`` ∈ [0,1], ``kind`` thuộc literal set).
    - ``dominant_thread`` (nếu có) luôn được rút ra từ ``active_threads``.
    - ``social_hypotheses``, ``forbidden_assumptions`` tùy chọn.
    - ``downstream_contract`` ánh xạ mỗi stage Phase 2 -> danh sách field cho phép.
    """

    items = draw(
        st.lists(
            workspace_items(with_evidence=require_item_evidence),
            min_size=min_items,
            max_size=max_items,
        )
    )

    active_threads = draw(st.lists(ids(), max_size=3, unique=True))
    dominant_thread = None
    if active_threads:
        dominant_thread = draw(st.one_of(st.none(), st.sampled_from(active_threads)))

    return WorkspaceFrame(
        frame_id=draw(ids()),
        timestamp=draw(
            st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False)
        ),
        budget_mode=draw(st.sampled_from(_BUDGET_MODES)),
        broadcast_items=items,
        social_hypotheses=draw(st.lists(social_hypotheses(), max_size=3)),
        risks=draw(st.lists(workspace_risks(), max_size=3)),
        forbidden_assumptions=draw(
            st.lists(_safe_text(max_size=20).filter(lambda s: s != ""), max_size=3, unique=True)
        ),
        active_threads=active_threads,
        dominant_thread=dominant_thread,
        context_pressure=draw(unit_floats()),
        broadcast_priority=draw(unit_floats()),
        confidence=draw(unit_floats()),
        uncertainty=draw(unit_floats()),
        downstream_contract={k: list(v) for k, v in _DEFAULT_DOWNSTREAM_CONTRACT.items()},
    )


# ---------------------------------------------------------------------------
# Strategy dẫn xuất
# ---------------------------------------------------------------------------
def empty_frames() -> st.SearchStrategy[WorkspaceFrame]:
    """Property 9 (R2.4) — frame không có ``broadcast_items`` nào."""

    return frames(min_items=0, max_items=0)


@st.composite
def frames_missing_field(draw) -> WorkspaceFrame:
    """Property 6 (R1.6) — frame hợp lệ nhưng thiếu một field bắt buộc.

    Frame được dựng đầy đủ (có ≥1 ``broadcast_item`` để phân biệt với
    ``empty_frames``), sau đó một field trong ``REQUIRED_FRAME_FIELDS`` bị đặt về
    ``None`` để mô phỏng "thiếu field bắt buộc". Tên field bị bỏ được ghi vào
    ``debug["_omitted_required_field"]`` để test có thể đối chiếu builder đã ghi
    nhận đúng field thiếu.
    """

    frame = draw(frames(min_items=1, max_items=4))
    field_name = draw(st.sampled_from(REQUIRED_FRAME_FIELDS))
    setattr(frame, field_name, None)
    frame.debug["_omitted_required_field"] = field_name
    return frame


@st.composite
def _meaning_hypothesis(
    draw,
    *,
    confidence: float | None = None,
    overread_risk: float | None = None,
    ambiguity: float | None = None,
    evidenceless: bool = False,
) -> MeaningHypothesis:
    """Helper nội bộ: dựng một ``MeaningHypothesis`` hợp lệ.

    ``confidence``/``overread_risk``/``ambiguity`` có thể được ghim để các strategy
    dẫn xuất kiểm soát phân bố; ``evidenceless=True`` ép ``evidence_ids`` rỗng.
    """

    evidence_ids = (
        []
        if evidenceless
        else draw(st.lists(ids(), min_size=1, max_size=4, unique=True))
    )
    return MeaningHypothesis(
        hypothesis_id=draw(ids()),
        category=draw(st.sampled_from(_MEANING_CATEGORIES)),
        summary=draw(_safe_text()),
        evidence_ids=evidence_ids,
        confidence=draw(unit_floats()) if confidence is None else confidence,
        ambiguity=draw(unit_floats()) if ambiguity is None else ambiguity,
        overread_risk=draw(unit_floats()) if overread_risk is None else overread_risk,
    )


@st.composite
def near_tie_hypotheses(
    draw,
    *,
    margin: float = 0.05,
    max_size: int = 4,
) -> list[MeaningHypothesis]:
    """Properties 18 (R5.3) & 31 (R9.3) — tập hypothesis có top-2 confidence sát nhau.

    Hai hypothesis xếp đầu có ``|Δconfidence| ≤ margin`` (mặc định 0.05 để thỏa cả
    biên 0.05 của AmbiguityModule lẫn biên 0.08 của MeaningHypothesisEngine). Các
    hypothesis còn lại có ``confidence`` không vượt phần tử thứ hai.
    """

    top = draw(
        st.floats(min_value=margin, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    delta = draw(
        st.floats(min_value=0.0, max_value=margin, allow_nan=False, allow_infinity=False)
    )
    second = max(0.0, top - delta)

    confidences = [top, second]
    extra = draw(
        st.lists(
            st.floats(min_value=0.0, max_value=second, allow_nan=False, allow_infinity=False),
            max_size=max(0, max_size - 2),
        )
    )
    confidences.extend(extra)

    return [draw(_meaning_hypothesis(confidence=c)) for c in confidences]


@st.composite
def evidenceless_candidates(
    draw,
    *,
    min_size: int = 1,
    max_size: int = 4,
) -> list[MeaningHypothesis]:
    """Properties 1 (R10.8) & 11 (R3.6) — candidate không gắn được evidence nào.

    Mọi ``MeaningHypothesis`` trả về có ``evidence_ids == []`` để kiểm bất biến
    no-overread (không bao giờ surfaced) và việc loại candidate không evidence.
    """

    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(_meaning_hypothesis(evidenceless=True)) for _ in range(n)]


@st.composite
def conclusions_across_brake_bands(
    draw,
    *,
    reduction_threshold: float = 0.70,
    suppression_threshold: float = 0.90,
    min_evidence_count: int = 2,
) -> MeaningHypothesis:
    """Properties 27–29 (R8.1–R8.3) — conclusion trải các band ngưỡng OverreadBrake.

    ``overread_risk`` được chọn theo từng band:

    - ``below``       — ``overread_risk < reduction_threshold``.
    - ``reduction``   — ``reduction_threshold ≤ overread_risk < suppression_threshold``.
    - ``suppression`` — ``overread_risk ≥ suppression_threshold``.

    ``evidence_ids`` được sinh với số lượng 0..3 để trải qua biên
    ``min_evidence_count`` (mặc định 2). Trả về ``MeaningHypothesis`` vì đây là
    ``Conclusion`` duy nhất mang sẵn ``evidence_ids`` để OverreadBrake kiểm.
    """

    band = draw(st.sampled_from(("below", "reduction", "suppression")))
    if band == "below":
        overread = draw(
            st.floats(
                min_value=0.0,
                max_value=math.nextafter(reduction_threshold, 0.0),
                allow_nan=False,
                allow_infinity=False,
            )
        )
    elif band == "reduction":
        overread = draw(
            st.floats(
                min_value=reduction_threshold,
                max_value=math.nextafter(suppression_threshold, 0.0),
                allow_nan=False,
                allow_infinity=False,
            )
        )
    else:  # suppression
        overread = draw(
            st.floats(
                min_value=suppression_threshold,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )

    evidence_count = draw(st.integers(min_value=0, max_value=max(3, min_evidence_count + 1)))
    evidence_ids = draw(
        st.lists(ids(), min_size=evidence_count, max_size=evidence_count, unique=True)
    )

    return MeaningHypothesis(
        hypothesis_id=draw(ids()),
        category=draw(st.sampled_from(_MEANING_CATEGORIES)),
        summary=draw(_safe_text()),
        evidence_ids=evidence_ids,
        confidence=draw(unit_floats()),
        ambiguity=draw(unit_floats()),
        overread_risk=overread,
    )
