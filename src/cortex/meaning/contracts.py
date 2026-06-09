# -*- coding: utf-8 -*-
"""contracts.py — Shared Phase 2 data models, ``clamp01`` helper và errors.

Đây là **nguồn sự thật dùng chung** cho tầng meaning (Phase 2):

- ``clamp01``: helper DUY NHẤT kẹp ``confidence``/``ambiguity``/``overread_risk``
  về [0.0, 1.0] tại điểm khởi tạo (áp ở ``__post_init__`` của mọi dataclass mang
  ba chỉ số này). Module ``cortex.tom.contracts`` import lại helper này thay vì
  tự định nghĩa, giữ một nguồn duy nhất.
- Các ``@dataclass(slots=True)`` mô tả artifact của pipeline meaning, đồng bộ với
  quy ước của ``cortex.global_workspace`` / ``cortex.contracts``.
- Các exception contract của Phase 2 (trừ ``ToMOrderingViolation`` thuộc
  ``cortex.tom.contracts`` để giữ ràng buộc ToM-after-Meaning ở đúng package).

Phụ thuộc một chiều: ``cortex.tom.contracts`` → ``cortex.meaning.contracts``.
Module này KHÔNG import bất kỳ symbol nào của ``cortex.tom`` ở runtime; alias
``Conclusion`` dùng forward-reference nên không tạo vòng import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover - chỉ phục vụ type-checker
    from ..tom.contracts import MentalStateInference


__all__ = [
    "clamp01",
    "RawWorldAccessError",
    "InvalidWorkspaceFrameError",
    "WorldSceneValidationError",
    "ConfigurationError",
    "WorldSceneElement",
    "WorldScene",
    "Observation",
    "ContextAnnotation",
    "MeaningHypothesis",
    "PragmaticIntent",
    "EvaluatedConclusion",
    "SurfaceDecision",
    "Phase2Result",
    "StageDebug",
    "Conclusion",
]


# ---------------------------------------------------------------------------
# clamp01 — nguồn DUY NHẤT
# ---------------------------------------------------------------------------
def clamp01(value: float) -> float:
    """Kẹp một chỉ số (confidence/ambiguity/overread_risk) về [0.0, 1.0].

    Giá trị không parse được hoặc ``NaN`` được quy về ``0.0`` để bất biến
    "mọi chỉ số luôn nằm trong [0,1]" không bao giờ bị phá.
    """

    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result:  # NaN
        return 0.0
    if result < 0.0:
        return 0.0
    if result > 1.0:
        return 1.0
    return result


# ---------------------------------------------------------------------------
# Errors & exceptions (kiểu dữ liệu) — design "Lỗi & ngoại lệ"
# ---------------------------------------------------------------------------
class RawWorldAccessError(RuntimeError):
    """R1.2 — Một stage Phase 2 cố đọc field ngoài hợp đồng / kênh Raw_World.

    Mang theo ``module_name`` (stage vi phạm) và ``field_name`` (field bị chặn)
    để debug chỉ đích danh module gây lỗi.
    """

    def __init__(self, module_name: str, field_name: str) -> None:
        self.module_name = module_name
        self.field_name = field_name
        super().__init__(
            f"module '{module_name}' attempted to read field '{field_name}' "
            "outside its WorkspaceFrame contract"
        )


class InvalidWorkspaceFrameError(ValueError):
    """R2.6 — WorkspaceFrame malformed / không parse được; không sinh scene."""


class WorldSceneValidationError(ValueError):
    """R3.5 — WorldScene rỗng/None/sai cấu trúc khi WorldInterpreter chạy."""


class ConfigurationError(ValueError):
    """R11.3, R11.4 — Taxonomy cấu hình sai (trùng id hoặc id không hợp lệ).

    Mang theo ``category_id`` và ``set_name`` để chỉ rõ vi phạm.
    """

    def __init__(self, category_id: str, set_name: str) -> None:
        self.category_id = category_id
        self.set_name = set_name
        super().__init__(
            f"invalid taxonomy configuration: category '{category_id}' "
            f"in set '{set_name}'"
        )


# ---------------------------------------------------------------------------
# WorldScene
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class WorldSceneElement:
    element_id: str
    kind: str                       # entity | salient_signal | thread
    summary: str
    evidence_ids: list[str]         # bảo toàn nguyên vẹn từ frame (R2.5)
    confidence: float               # [0,1] (R2.2)
    is_dominant_focus: bool = False
    source_item_id: str | None = None

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)


@dataclass(slots=True)
class WorldScene:
    frame_id: str | None            # R1.5
    entities: list[WorldSceneElement]
    salient_signals: list[WorldSceneElement]
    active_threads: list[WorldSceneElement]
    confidence: float               # cap 0.5 nếu thiếu field (R1.6); 0.0 nếu rỗng (R1.4)
    is_empty: bool = False
    reason: str = ""                # lý do rỗng (R1.4, R2.4)

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Observation:
    observation_id: str
    summary: str
    evidence_ids: list[str]         # >=1 (R3.1, R3.6)
    confidence: float
    source_element_id: str          # R3.4
    low_confidence: bool = False    # R3.3

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)


# ---------------------------------------------------------------------------
# Sociocultural
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ContextAnnotation:
    observation: Observation
    relationship: str               # neutral default nếu thiếu (R4.3)
    register: str
    social_norm: str
    unconfirmed_social: list[str]   # social_hypotheses dạng chưa xác nhận (R4.2)
    defaults_applied: list[str]     # loại nào dùng default (R4.4)
    confidence: float               # R4.5

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)


# ---------------------------------------------------------------------------
# Meaning
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class MeaningHypothesis:
    hypothesis_id: str
    category: str                   # Taxonomy.MEANING (qua require())
    summary: str
    evidence_ids: list[str]         # non-empty (R5.2)
    confidence: float
    ambiguity: float
    overread_risk: float
    is_insufficient_evidence: bool = False    # R5.4
    source_semantic_label: str | None = None  # truy vết về SemanticHypothesis được wrap

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)
        self.ambiguity = clamp01(self.ambiguity)
        self.overread_risk = clamp01(self.overread_risk)


# ---------------------------------------------------------------------------
# Pragmatic intent
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class PragmaticIntent:
    intent_id: str
    category: str                   # Taxonomy.INTENT
    confidence: float
    supporting_meaning_ids: list[str]   # >=1, giữ cả khi confidence==0 (R6.3)
    overread_risk: float = 0.0

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)
        self.overread_risk = clamp01(self.overread_risk)


# ---------------------------------------------------------------------------
# OverreadBrake / Surface
# ---------------------------------------------------------------------------
# Conclusion: alias dùng cho OverreadBrake / SurfaceMeaningPolicy. Dùng
# forward-reference (chuỗi) để KHÔNG import runtime ``cortex.tom`` -> tránh vòng.
Conclusion = Union["MeaningHypothesis", "PragmaticIntent", "MentalStateInference"]


@dataclass(slots=True)
class EvaluatedConclusion:
    conclusion: Conclusion
    kind: str                       # "meaning" | "intent" | "mental_state"
    confidence: float               # có thể đã bị giảm (R8.1)
    original_confidence: float      # giữ giá trị gốc cho debug (R8.5)
    overread_suppressed: bool = False
    brake_reason: str = ""
    metric_name: str = ""
    metric_value: float = 0.0

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)
        self.original_confidence = clamp01(self.original_confidence)


@dataclass(slots=True)
class SurfaceDecision:
    conclusion_id: str
    status: str                     # "surfaced_asserted" | "surfaced_tentative" | "withheld"
    reason: str = ""


@dataclass(slots=True)
class Phase2Result:
    frame_id: str | None            # R1.5, R12.4
    surfaced: list[EvaluatedConclusion]
    withheld: list[EvaluatedConclusion]
    decisions: list[SurfaceDecision]    # R10.5
    debug: dict                         # contract_violations, missing_fields, stage debugs


# ---------------------------------------------------------------------------
# Hỗ trợ guard
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class StageDebug:
    stage: str
    confidence: float | None = None
    ambiguity: float | None = None
    overread_risk: float | None = None
    missing_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.confidence is not None:
            self.confidence = clamp01(self.confidence)
        if self.ambiguity is not None:
            self.ambiguity = clamp01(self.ambiguity)
        if self.overread_risk is not None:
            self.overread_risk = clamp01(self.overread_risk)
