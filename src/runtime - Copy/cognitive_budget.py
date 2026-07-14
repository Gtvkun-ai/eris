# -*- coding: utf-8 -*-
"""
src/runtime/cognitive_budget.py
================================

Bộ chọn Cognitive Budget cho ERIS.

Mục tiêu:
    Chọn đường chạy nhận thức cho mỗi CognitiveFrame:
        - fast
        - normal
        - deep
        - reflection

Vì sao cần file này:
    Attention biết cái gì nổi bật.
    WorkingMemory biết cái gì được giữ lại.
    GlobalWorkspace biết cái gì được broadcast.

    Nhưng runtime vẫn cần một trọng tài tài nguyên để quyết định:
        - chạy pipeline nhẹ hay pipeline đầy đủ?
        - có cần ToM sâu không?
        - có cần memory cognition không?
        - có cần LLM wording không?
        - có nên chạy reflection/repair/dream later không?
        - token/slot/workspace budget hiện tại nên chặt hay rộng?

    Nếu không có CognitiveBudget, ERIS sẽ rơi vào hai lỗi kinh điển:
        1. câu rất nhỏ cũng chạy full pipeline như đang mổ não rồng;
        2. câu quan trọng lại bị xử như telemetry rác.

Nguyên tắc kiến trúc:
    - Module này CHỈ đọc frame và vài hint runtime.
    - Module này KHÔNG gọi LLM, KHÔNG gọi memory store, KHÔNG gọi attention trực tiếp.
    - Nó chỉ trả quyết định ngân sách + kế hoạch chạy module.
    - Nếu cần ghi lại gì, nó tạo ModuleReport hoặc StateCommitRequest qua frame nếu frame hỗ trợ.

Vị trí trong pipeline:
    Evidence
      -> AttentionSalience
      -> CognitiveBudget
      -> Temporal / Spatial / Homeostasis / Affect
      -> WorkingMemory
      -> GlobalWorkspace
      -> downstream tùy budget

Gợi ý dùng trong runtime:

    engine = CognitiveBudgetEngine()
    decision = engine.choose(frame, channel="chat")
    frame.budget_mode = decision.mode

    if decision.plan.should_run("working_memory"):
        frame.working_memory = working_memory.select(frame)

    if decision.plan.should_run("global_workspace"):
        frame.workspace = workspace.broadcast(frame)

File này cố tình dùng duck-typing mạnh để dễ gắn vào repo hiện tại.
Con người đã tạo ra đủ dependency hell rồi; không cần đóng góp thêm bằng import cứng vô tội vạ.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence


# =============================================================================
# 1. Import mềm các contract nền
# =============================================================================

try:  # pragma: no cover - phụ thuộc layout repo thật.
    from core.evidence import ModuleReport, StateCommitRequest  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.evidence import ModuleReport, StateCommitRequest  # type: ignore
    except Exception:  # pragma: no cover
        try:
            from ..core.evidence import ModuleReport, StateCommitRequest  # type: ignore
        except Exception:  # pragma: no cover
            @dataclass(slots=True)
            class ModuleReport:  # type: ignore[no-redef]
                """Fallback tối thiểu để file chạy độc lập khi chưa nối core.evidence."""

                module_name: str
                confidence: float
                pressure: float
                evidence_used: list[str]
                result: Any
                warnings: list[str] = field(default_factory=list)
                debug: dict[str, Any] = field(default_factory=dict)

            @dataclass(slots=True)
            class StateCommitRequest:  # type: ignore[no-redef]
                """Fallback tối thiểu cho đề xuất commit state/memory."""

                target: str
                content: str
                confidence: float
                evidence_ids: list[str]
                permission_required: bool
                storage_permission: bool
                decay_policy: str
                reason: str


# =============================================================================
# 2. Literal contracts
# =============================================================================

BudgetMode = Literal["fast", "normal", "deep", "reflection"]
BudgetChannel = Literal[
    "autonomous",
    "chat",
    "force_speak",
    "session_start",
    "reflection",
    "shutdown",
    "system",
    "test",
    "unknown",
]
BudgetUrgency = Literal["low", "medium", "high", "critical"]
BudgetCompression = Literal["strict", "balanced", "expanded", "reflective"]
BudgetEscalationReason = Literal[
    "explicit_reflection_request",
    "shutdown_or_session_end",
    "idle_reflection_window",
    "major_user_correction",
    "repeated_contradiction",
    "high_affective_residue",
    "code_debugging_or_architecture",
    "high_value_decision",
    "memory_contradiction",
    "relational_rupture",
    "high_risk_or_permission_pressure",
    "context_flood_requires_deep_selection",
    "ordinary_interaction",
    "low_stakes_ambient",
]
BudgetDowngradeReason = Literal[
    "low_signal_density",
    "no_risk_no_task",
    "ambient_idle",
    "speech_not_needed",
    "strict_fast_path_hint",
    "token_pressure",
    "privacy_pressure",
]

PipelineStepName = Literal[
    "raw_signal_collector",
    "evidence_normalizer",
    "attention_salience",
    "cognitive_budget",
    "temporal_perception",
    "spatial_proprioception",
    "homeostasis",
    "affective_substrate",
    "working_memory",
    "global_workspace",
    "world_scene_builder",
    "world_interpreter",
    "sociocultural_context",
    "meaning_hypothesis",
    "theory_of_mind",
    "epistemic_drive",
    "inquiry_planner",
    "knowledge_acquisition",
    "belief_core",
    "memory_cognition",
    "value_resolution",
    "predictive_simulation",
    "cognitive_arbitration",
    "agency_engine",
    "relational_dynamics",
    "permission_engine",
    "calculated_noise",
    "speech_opportunity",
    "speech_core",
    "body_action_planner",
    "modality_sync",
    "llm_wording",
    "grounding_guard",
    "execution_layer",
    "outcome_observer",
    "self_observation",
    "repair_memory",
    "state_committer",
    "dream_scheduler",
]


# =============================================================================
# 3. Helpers nhỏ, vì runtime không nên chết bởi một field kỳ quặc
# =============================================================================


def now_ts() -> float:
    return time.time()


def clamp01(value: Any, default: float = 0.0) -> float:
    """Ép giá trị về khoảng 0..1.

    Đây là runtime, không phải phòng thí nghiệm lý tưởng.
    Field từ các module khác đôi khi là None, string, NaN, hoặc object lạc loài.
    """

    try:
        number = float(value)
    except Exception:
        number = default
    if math.isnan(number) or math.isinf(number):
        number = default
    return max(0.0, min(1.0, number))


def clamp(value: Any, minimum: float, maximum: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        number = default
    if math.isnan(number) or math.isinf(number):
        number = default
    return max(minimum, min(maximum, number))


def safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """Lấy attribute/key theo kiểu duck-typing.

    Cho phép đọc cả dataclass, object thường và dict.
    Nếu module upstream đổi từ dataclass sang dict, budget không nên lăn ra chết.
    """

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def safe_get_path(obj: Any, path: str, default: Any = None) -> Any:
    current = obj
    for part in path.split("."):
        current = safe_get(current, part, default=None)
        if current is None:
            return default
    return current


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def text_of(value: Any, *, max_len: int = 800) -> str:
    """Chuyển object bất kỳ thành text ngắn để phân tích signal.

    Không dùng để prompt trực tiếp. Chỉ dùng nội bộ để score keyword.
    """

    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif is_dataclass(value):
        try:
            text = json.dumps(asdict(value), ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    elif isinstance(value, Mapping):
        try:
            text = json.dumps(dict(value), ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def lower_text(value: Any, *, max_len: int = 1600) -> str:
    return text_of(value, max_len=max_len).lower()


def _keyword_pattern(word: str) -> re.Pattern[str]:
    """Tạo pattern match keyword ít ngu hơn substring thuần.

    - Cụm có khoảng trắng vẫn match như phrase.
    - Từ ASCII một mảnh dùng boundary để `class` không ăn vào chuỗi dài kỳ quặc.
    - Từ tiếng Việt một mảnh vẫn dùng look-around chữ/số để giảm match nhầm.

    Đây vẫn là heuristic. Khác biệt là nó không được phép tự phong làm semantic truth nữa.
    """

    escaped = re.escape(word.strip().lower())
    if not escaped:
        return re.compile(r"a^", re.IGNORECASE)
    if re.fullmatch(r"[a-z0-9_#+.-]+", word.strip().lower()):
        return re.compile(rf"(?<![a-z0-9_#+.-]){escaped}(?![a-z0-9_#+.-])", re.IGNORECASE)
    return re.compile(rf"(?<![\wÀ-ỹ]){escaped}(?![\wÀ-ỹ])", re.IGNORECASE)


def contains_any(text: str, words: Sequence[str]) -> bool:
    return any(_keyword_pattern(word).search(text or "") for word in words)


def count_any(text: str, words: Sequence[str]) -> int:
    return sum(1 for word in words if _keyword_pattern(word).search(text or ""))


def keyword_hits(text: str, words: Sequence[str]) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for word in words:
        if _keyword_pattern(word).search(text):
            hits.append(word)
    return hits


def weighted_keyword_score(text: str, groups: Mapping[str, Sequence[str]], weights: Mapping[str, float]) -> float:
    """Tính score keyword fallback.

    Bản cũ để keyword đi quá thẳng vào pressure rồi hard-floor lên deep.
    Bản này vẫn trả score để budget có fallback rẻ khi semantic reports chưa nối đủ,
    nhưng các estimator phía dưới sẽ cap score này nếu thiếu semantic support.
    """

    if not text:
        return 0.0
    score = 0.0
    for group, words in groups.items():
        hit = len(keyword_hits(text, words))
        if hit:
            score += min(1.0, 0.25 + hit * 0.12) * weights.get(group, 0.1)
    return clamp01(score)


def blend_semantic_and_keyword(
    *,
    semantic: float,
    keyword: float,
    keyword_cap_without_semantic: float = 0.42,
    semantic_floor_for_uncap: float = 0.35,
    keyword_weight_when_supported: float = 0.35,
) -> tuple[float, bool]:
    """Ghép semantic pressure với keyword fallback.

    Trả về `(pressure, keyword_only)`.
    `keyword_only=True` nghĩa là pressure chủ yếu đến từ text match, chưa được evidence/semantic
    report chống lưng. Các hard floor tuyệt đối không nên kích hoạt từ trạng thái này.
    """

    semantic = clamp01(semantic)
    keyword = clamp01(keyword)
    if semantic >= semantic_floor_for_uncap:
        return clamp01(max(semantic, keyword * keyword_weight_when_supported + semantic)), False
    if keyword <= 0.0:
        return semantic, False
    capped = min(keyword * 0.72, keyword_cap_without_semantic)
    return clamp01(max(semantic, capped)), True


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def object_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except Exception:
            return text_of(obj)
    if isinstance(obj, Mapping):
        return {str(k): object_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [object_to_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return text_of(obj)


# =============================================================================
# 4. Dataclass nền
# =============================================================================


@dataclass(slots=True)
class BudgetModeProfile:
    """Thông số tài nguyên cho một budget mode.

    Đây là thứ downstream nên đọc thay vì tự đoán:
        - WorkingMemory nên giữ bao nhiêu slot?
        - Workspace nên broadcast bao nhiêu item?
        - Prompt tối đa nên rộng cỡ nào?
        - Có được chạy ToM sâu / belief / simulation không?

    Lưu ý:
        Đây là profile mặc định. Module cụ thể vẫn có thể áp thêm giới hạn riêng.
    """

    mode: BudgetMode
    max_evidence_items: int
    max_working_memory_slots: int
    max_workspace_items: int
    max_prompt_tokens: int
    max_memory_items: int
    max_simulations: int
    compression: BudgetCompression
    allow_llm_wording: bool
    allow_deep_tom: bool
    allow_memory_cognition: bool
    allow_belief_update: bool
    allow_predictive_simulation: bool
    allow_body_planning: bool
    allow_reflection: bool
    allow_dream_schedule: bool
    autonomous_speech_threshold: float
    inquiry_threshold: float
    memory_commit_threshold: float
    max_latency_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BudgetSignalSnapshot:
    """Ảnh chụp các áp lực dùng để chọn budget.

    Mỗi field là pressure 0..1.
    Cái này không phải cảm xúc, không phải phán xét, không phải thần dụ.
    Nó chỉ là bảng điện áp của runtime.
    """

    channel: str = "unknown"
    user_directness: float = 0.0
    signal_density: float = 0.0
    salience_priority: float = 0.0
    context_pressure: float = 0.0
    risk_pressure: float = 0.0
    privacy_pressure: float = 0.0
    technical_depth: float = 0.0
    architecture_depth: float = 0.0
    correction_pressure: float = 0.0
    contradiction_pressure: float = 0.0
    relational_rupture: float = 0.0

    # Debug/guard cho heuristic:
    # keyword pressure vẫn tồn tại, nhưng hard floor không được kích hoạt nếu thiếu semantic support.
    technical_semantic_support: float = 0.0
    architecture_semantic_support: float = 0.0
    correction_semantic_support: float = 0.0
    risk_semantic_support: float = 0.0
    technical_keyword_pressure: float = 0.0
    architecture_keyword_pressure: float = 0.0
    correction_keyword_pressure: float = 0.0
    risk_keyword_pressure: float = 0.0
    technical_keyword_only: bool = False
    architecture_keyword_only: bool = False
    correction_keyword_only: bool = False
    risk_keyword_only: bool = False
    affective_residue: float = 0.0
    homeostasis_load: float = 0.0
    goal_pressure: float = 0.0
    goal_intervention_permission: float = 0.0
    memory_conflict: float = 0.0
    worldview_pressure: float = 0.0
    uncertainty: float = 0.0
    ambiguity: float = 0.0
    idle_pressure: float = 0.0
    session_closing_pressure: float = 0.0
    shutdown_pressure: float = 0.0
    reflection_debt: float = 0.0
    speech_need: float = 0.0
    body_need: float = 0.0
    low_stakes_ambient: float = 0.0
    force_reflection: bool = False
    force_deep: bool = False
    force_fast: bool = False
    has_user_text: bool = False
    has_user_correction: bool = False
    has_technical_request: bool = False
    has_architecture_request: bool = False
    has_relational_event: bool = False
    has_memory_contradiction: bool = False
    has_worldview_update: bool = False
    has_high_value_decision: bool = False

    def pressure_max(self) -> float:
        return max(
            self.salience_priority,
            self.context_pressure,
            self.risk_pressure,
            self.privacy_pressure,
            self.technical_depth,
            self.architecture_depth,
            self.correction_pressure,
            self.contradiction_pressure,
            self.relational_rupture,
            self.affective_residue,
            self.homeostasis_load,
            self.goal_pressure,
            self.memory_conflict,
            self.worldview_pressure,
            self.uncertainty,
            self.ambiguity,
            self.reflection_debt,
            self.speech_need,
            self.body_need,
        )

    def task_pressure(self) -> float:
        return max(
            self.user_directness,
            self.technical_depth,
            self.architecture_depth,
            self.goal_pressure,
            self.speech_need,
        )

    def reflection_pressure(self) -> float:
        return max(
            self.session_closing_pressure,
            self.shutdown_pressure,
            self.reflection_debt,
            self.affective_residue * 0.90,
            self.correction_pressure * 0.85,
            self.contradiction_pressure,
            self.memory_conflict,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BudgetScoreBreakdown:
    """Điểm cạnh tranh giữa các mode.

    Chọn budget không nên là if-else mù.
    Breakdown giúp debug vì sao một frame bị nâng từ normal lên deep hoặc hạ xuống fast.
    """

    fast: float
    normal: float
    deep: float
    reflection: float
    winning_score: float
    margin: float
    raw_reasons: list[str] = field(default_factory=list)

    def as_ranked(self) -> list[tuple[str, float]]:
        return sorted(
            [
                ("fast", self.fast),
                ("normal", self.normal),
                ("deep", self.deep),
                ("reflection", self.reflection),
            ],
            key=lambda item: item[1],
            reverse=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fast": round(self.fast, 4),
            "normal": round(self.normal, 4),
            "deep": round(self.deep, 4),
            "reflection": round(self.reflection, 4),
            "winning_score": round(self.winning_score, 4),
            "margin": round(self.margin, 4),
            "ranked": [(name, round(score, 4)) for name, score in self.as_ranked()],
            "raw_reasons": list(self.raw_reasons),
        }


@dataclass(slots=True)
class PipelineStepDecision:
    """Quyết định chạy/bỏ qua một bước pipeline."""

    name: str
    run: bool
    reason: str
    priority: float = 0.0
    optional: bool = False
    max_items: Optional[int] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BudgetPlan:
    """Kế hoạch chạy pipeline dựa trên budget.

    Đây là phần quan trọng hơn cả label mode.
    Label `deep` mà không nói module nào được chạy thì vẫn chỉ là huy hiệu trang trí.
    """

    mode: BudgetMode
    profile: BudgetModeProfile
    steps: list[PipelineStepDecision]
    required_steps: list[str]
    skipped_steps: list[str]
    max_prompt_tokens: int
    max_evidence_items: int
    max_working_memory_slots: int
    max_workspace_items: int
    max_memory_items: int
    compression: BudgetCompression
    prompt_policy_notes: list[str] = field(default_factory=list)
    runtime_notes: list[str] = field(default_factory=list)

    def should_run(self, step_name: str) -> bool:
        normalized = step_name.strip().lower()
        for step in self.steps:
            if step.name == normalized:
                return step.run
        return False

    def step(self, step_name: str) -> Optional[PipelineStepDecision]:
        normalized = step_name.strip().lower()
        for step in self.steps:
            if step.name == normalized:
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "required_steps": list(self.required_steps),
            "skipped_steps": list(self.skipped_steps),
            "max_prompt_tokens": self.max_prompt_tokens,
            "max_evidence_items": self.max_evidence_items,
            "max_working_memory_slots": self.max_working_memory_slots,
            "max_workspace_items": self.max_workspace_items,
            "max_memory_items": self.max_memory_items,
            "compression": self.compression,
            "prompt_policy_notes": list(self.prompt_policy_notes),
            "runtime_notes": list(self.runtime_notes),
        }


@dataclass(slots=True)
class BudgetDecision:
    """Kết quả cuối của CognitiveBudgetEngine."""

    mode: BudgetMode
    urgency: BudgetUrgency
    confidence: float
    reason: str
    snapshot: BudgetSignalSnapshot
    scores: BudgetScoreBreakdown
    plan: BudgetPlan
    escalation_reasons: list[str] = field(default_factory=list)
    downgrade_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "urgency": self.urgency,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "snapshot": self.snapshot.to_dict(),
            "scores": self.scores.to_dict(),
            "plan": self.plan.to_dict(),
            "escalation_reasons": list(self.escalation_reasons),
            "downgrade_reasons": list(self.downgrade_reasons),
            "warnings": list(self.warnings),
            "debug": object_to_dict(self.debug),
            "timestamp": self.timestamp,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def render_debug_summary(self) -> str:
        ranked = ", ".join(f"{name}={score:.2f}" for name, score in self.scores.as_ranked())
        return (
            f"budget={self.mode}; urgency={self.urgency}; confidence={self.confidence:.2f}; "
            f"scores[{ranked}]; reason={self.reason}"
        )


@dataclass(slots=True)
class CognitiveBudgetConfig:
    """Cấu hình của CognitiveBudgetEngine.

    Giữ trong dataclass để sau này Ngài có thể load từ JSON/YAML.
    Xin đừng rải magic number khắp coordinator, đó là nghi lễ triệu hồi bug.
    """

    fast_threshold: float = 0.55
    normal_threshold: float = 0.45
    deep_threshold: float = 0.62
    reflection_threshold: float = 0.66

    # Sàn nâng mode.
    strong_correction_threshold: float = 0.62
    relational_rupture_threshold: float = 0.58
    memory_conflict_threshold: float = 0.55
    high_risk_threshold: float = 0.68
    context_flood_threshold: float = 0.72
    architecture_depth_threshold: float = 0.55
    technical_depth_threshold: float = 0.62
    reflection_debt_threshold: float = 0.62

    # Sàn hạ mode.
    low_signal_density_threshold: float = 0.24
    low_salience_threshold: float = 0.26
    low_task_pressure_threshold: float = 0.25
    fast_idle_pressure_threshold: float = 0.50

    # Token/slot override mềm.
    token_pressure_high: float = 0.78
    privacy_pressure_high: float = 0.70

    # Nếu mode thắng quá sít sao thì confidence thấp hơn.
    weak_margin: float = 0.10

    # Keyword chỉ là fallback. Không cho text match một mình kéo budget lên deep.
    keyword_only_pressure_cap: float = 0.42
    keyword_semantic_support_floor: float = 0.35
    keyword_supported_weight: float = 0.35

    # Chỉ hard-floor lên deep khi có semantic/evidence support đủ tốt.
    hard_floor_semantic_support_threshold: float = 0.38

    # Cho phép module ghi decision vào frame.
    attach_report_to_frame: bool = True
    attach_decision_to_frame: bool = True
    update_frame_budget_mode: bool = True

    # Đừng để fast path chạy quá ngu khi có user chat thật.
    chat_minimum_mode: BudgetMode = "normal"
    force_speak_minimum_mode: BudgetMode = "normal"

    def profiles(self) -> dict[BudgetMode, BudgetModeProfile]:
        return {
            "fast": BudgetModeProfile(
                mode="fast",
                max_evidence_items=6,
                max_working_memory_slots=3,
                max_workspace_items=5,
                max_prompt_tokens=900,
                max_memory_items=1,
                max_simulations=0,
                compression="strict",
                allow_llm_wording=True,
                allow_deep_tom=False,
                allow_memory_cognition=False,
                allow_belief_update=False,
                allow_predictive_simulation=False,
                allow_body_planning=True,
                allow_reflection=False,
                allow_dream_schedule=False,
                autonomous_speech_threshold=0.72,
                inquiry_threshold=0.78,
                memory_commit_threshold=0.82,
                max_latency_class="very_low",
            ),
            "normal": BudgetModeProfile(
                mode="normal",
                max_evidence_items=12,
                max_working_memory_slots=5,
                max_workspace_items=8,
                max_prompt_tokens=1800,
                max_memory_items=3,
                max_simulations=1,
                compression="balanced",
                allow_llm_wording=True,
                allow_deep_tom=False,
                allow_memory_cognition=True,
                allow_belief_update=False,
                allow_predictive_simulation=False,
                allow_body_planning=True,
                allow_reflection=False,
                allow_dream_schedule=False,
                autonomous_speech_threshold=0.62,
                inquiry_threshold=0.66,
                memory_commit_threshold=0.70,
                max_latency_class="low",
            ),
            "deep": BudgetModeProfile(
                mode="deep",
                max_evidence_items=24,
                max_working_memory_slots=7,
                max_workspace_items=14,
                max_prompt_tokens=3600,
                max_memory_items=8,
                max_simulations=4,
                compression="expanded",
                allow_llm_wording=True,
                allow_deep_tom=True,
                allow_memory_cognition=True,
                allow_belief_update=True,
                allow_predictive_simulation=True,
                allow_body_planning=True,
                allow_reflection=False,
                allow_dream_schedule=True,
                autonomous_speech_threshold=0.55,
                inquiry_threshold=0.52,
                memory_commit_threshold=0.62,
                max_latency_class="medium",
            ),
            "reflection": BudgetModeProfile(
                mode="reflection",
                max_evidence_items=20,
                max_working_memory_slots=7,
                max_workspace_items=12,
                max_prompt_tokens=2800,
                max_memory_items=10,
                max_simulations=2,
                compression="reflective",
                allow_llm_wording=False,
                allow_deep_tom=True,
                allow_memory_cognition=True,
                allow_belief_update=True,
                allow_predictive_simulation=False,
                allow_body_planning=False,
                allow_reflection=True,
                allow_dream_schedule=True,
                autonomous_speech_threshold=0.95,
                inquiry_threshold=0.75,
                memory_commit_threshold=0.55,
                max_latency_class="background",
            ),
        }


# =============================================================================
# 5. Keyword groups mềm cho budget, không dùng làm chân lý ngữ nghĩa
# =============================================================================

TECHNICAL_KEYWORDS = (
    # Cố ý giữ các anchor kỹ thuật tương đối đặc hiệu.
    # Các từ quá rộng như "làm", "tạo", "gửi", "file", "chạy" đã bị loại khỏi nhóm này.
    "code",
    "debug",
    "bug",
    "error",
    "traceback",
    "exception",
    "compile",
    "runtime",
    "repo",
    "module",
    "dataclass",
    "class",
    "function",
    "python",
    "c#",
    "godot",
    "pipeline",
    "architecture",
    "contract",
    "token",
    "memory",
    "attention",
    "workspace",
    "cognitive",
    "kiến trúc",
    "lỗi",
    "fix",
)

ARCHITECTURE_KEYWORDS = (
    "architecture",
    "pipeline",
    "contract",
    "backbone",
    "runtime",
    "cognitive",
    "workspace",
    "working memory",
    "global workspace",
    "attention",
    "evidence",
    "phase",
    "module",
    "downstream",
    "upstream",
    "spaghetti",
    "kiến trúc",
    "xương sống",
    "lõi",
    "tầng",
    "hệ thống",
    "mô hình",
)

CORRECTION_KEYWORDS = (
    "không phải",
    "ko phải",
    "có đâu",
    "co dau",
    "có code đâu",
    "co code dau",
    "tôi có code đâu",
    "toi co code dau",
    "sai rồi",
    "sai",
    "thiếu",
    "chưa đúng",
    "chưa đủ",
    "nhầm",
    "lệch",
    "chỉ nghe nhạc",
    "chi nghe nhac",
    "fix lại",
    "đúng như",
    "không đúng",
    "wrong",
    "incorrect",
    "not that",
    "missing",
)

RELATIONAL_RUPTURE_KEYWORDS = (
    "bị bỏ mặc",
    "tổn thương",
    "không hiểu",
    "xem như tool",
    "waifu",
    "cosplay",
    "giả",
    "fake",
    "không thật",
    "objectify",
    "tool",
    "công cụ",
    "bị giản lược",
)

MEMORY_CONFLICT_KEYWORDS = (
    "contradiction",
    "mâu thuẫn",
    "nhớ sai",
    "memory conflict",
    "repair memory",
    "sửa ký ức",
    "quên",
    "forget",
    "wrong memory",
    "recall sai",
)

RISK_KEYWORDS = (
    "risk",
    "danger",
    "unsafe",
    "privacy",
    "sensitive",
    "secret",
    "leak",
    "permission",
    "vi phạm",
    "riêng tư",
    "nhạy cảm",
    "bảo mật",
)

REFLECTION_KEYWORDS = (
    "reflection",
    "self observation",
    "dream",
    "consolidation",
    "repair",
    "session end",
    "shutdown",
    "đóng phiên",
    "tự quan sát",
    "giấc mơ",
    "hợp nhất",
    "đúc kết",
)

HIGH_VALUE_KEYWORDS = (
    "quan trọng",
    "critical",
    "high-value",
    "quyết định",
    "strategy",
    "roadmap",
    "hướng đi",
    "đập lại",
    "xây lại",
    "từ đầu",
    "chuẩn",
    "maximum",
    "full",
    "đầy đủ",
)


# =============================================================================
# 6. Engine chính
# =============================================================================


class CognitiveBudgetEngine:
    """Chọn cognitive budget cho một frame.

    Đầu vào chính là CognitiveFrame. Engine đọc bằng duck-typing:
        frame.evidence
        frame.salience
        frame.working_memory
        frame.workspace
        frame.homeostasis
        frame.affect
        frame.relation
        frame.meaning
        frame.tom
        frame.outcome
        frame.self_observation
        frame.debug_notes

    Runtime cũng có thể truyền hint:
        channel="chat"
        user_text="..."
        force_reflection=True
        session_ending=True
        shutdown=True

    Output là BudgetDecision + BudgetPlan.
    """

    MODULE_NAME = "cognitive_budget"

    def __init__(self, config: Optional[CognitiveBudgetConfig] = None):
        self.config = config or CognitiveBudgetConfig()
        self._profiles = self.config.profiles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def choose(
        self,
        frame: Any,
        *,
        channel: str = "unknown",
        user_text: str = "",
        force_reflection: bool = False,
        force_deep: bool = False,
        force_fast: bool = False,
        session_ending: bool = False,
        shutdown: bool = False,
        idle_seconds: Optional[float] = None,
        previous_decisions: Optional[Sequence[BudgetDecision | Mapping[str, Any]]] = None,
        attach_to_frame: Optional[bool] = None,
    ) -> BudgetDecision:
        """Chọn budget mode cho frame.

        Tham số:
            frame:
                CognitiveFrame hoặc object có field tương tự.
            channel:
                chat / autonomous / force_speak / reflection / shutdown ...
            user_text:
                text user hiện tại nếu runtime có sẵn. Nếu rỗng, engine cố lấy từ evidence/raw_signals.
            force_reflection / force_deep / force_fast:
                override mềm. Không phải lúc nào cũng tuyệt đối, trừ shutdown/reflection.
            session_ending / shutdown:
                hint vòng đời runtime.
            idle_seconds:
                hint idle thực tế nếu frame chưa có temporal/homeostasis.
            previous_decisions:
                dùng để tránh flip mode quá mạnh nếu cần. Bản này chỉ đọc rất nhẹ.
            attach_to_frame:
                override việc gắn report/decision vào frame.
        """

        normalized_channel = self._normalize_channel(channel)
        snapshot = self._extract_snapshot(
            frame,
            channel=normalized_channel,
            user_text=user_text,
            force_reflection=force_reflection,
            force_deep=force_deep,
            force_fast=force_fast,
            session_ending=session_ending,
            shutdown=shutdown,
            idle_seconds=idle_seconds,
        )
        scores = self._score_modes(snapshot, previous_decisions=previous_decisions)
        mode = self._choose_mode_from_scores(snapshot, scores)
        mode = self._apply_hard_floors(mode, snapshot)
        mode = self._apply_hard_overrides(mode, snapshot)

        escalation, downgrade, warnings = self._derive_reasons(mode, snapshot, scores)
        confidence = self._estimate_confidence(mode, snapshot, scores)
        urgency = self._estimate_urgency(mode, snapshot)
        reason = self._build_reason(mode, snapshot, escalation, downgrade, scores)
        plan = self._build_plan(mode, snapshot)

        decision = BudgetDecision(
            mode=mode,
            urgency=urgency,
            confidence=confidence,
            reason=reason,
            snapshot=snapshot,
            scores=scores,
            plan=plan,
            escalation_reasons=escalation,
            downgrade_reasons=downgrade,
            warnings=warnings,
            debug={
                "channel": normalized_channel,
                "frame_id": safe_get(frame, "frame_id", None),
                "previous_budget_mode": safe_get(frame, "budget_mode", None),
                "profiles": {k: v.to_dict() for k, v in self._profiles.items()},
            },
        )

        should_attach = self.config.attach_decision_to_frame if attach_to_frame is None else bool(attach_to_frame)
        if should_attach:
            self._attach_decision(frame, decision)
        return decision

    def choose_mode(self, frame: Any, **kwargs: Any) -> BudgetMode:
        """Shortcut khi runtime cũ chỉ cần string budget_mode."""

        return self.choose(frame, **kwargs).mode

    def build_plan(self, mode: BudgetMode, frame: Any | None = None) -> BudgetPlan:
        """Build plan trực tiếp từ mode.

        Hữu ích cho tests hoặc runtime đã chọn mode từ nơi khác.
        """

        snapshot = BudgetSignalSnapshot(channel="unknown")
        if frame is not None:
            snapshot = self._extract_snapshot(frame, channel=self._normalize_channel(safe_get(frame, "channel", "unknown")))
        return self._build_plan(mode, snapshot)

    # Alias để dễ gọi theo style khác.
    evaluate = choose
    decide = choose
    select = choose

    # ------------------------------------------------------------------
    # Snapshot extraction
    # ------------------------------------------------------------------

    def _extract_snapshot(
        self,
        frame: Any,
        *,
        channel: str,
        user_text: str = "",
        force_reflection: bool = False,
        force_deep: bool = False,
        force_fast: bool = False,
        session_ending: bool = False,
        shutdown: bool = False,
        idle_seconds: Optional[float] = None,
    ) -> BudgetSignalSnapshot:
        evidence = as_list(safe_get(frame, "evidence", []))
        raw_signals = as_list(safe_get(frame, "raw_signals", []))
        salience = safe_get(frame, "salience", None)
        working_memory = safe_get(frame, "working_memory", None)
        workspace = safe_get(frame, "workspace", None)
        homeostasis = safe_get(frame, "homeostasis", None)
        affect = safe_get(frame, "affect", None)
        relation = safe_get(frame, "relation", None)
        permission = safe_get(frame, "permission", None)
        meaning = safe_get(frame, "meaning", None)
        tom = safe_get(frame, "tom", None)
        memory_packet = safe_get(frame, "memory_packet", None)
        belief = safe_get(frame, "belief", None)
        outcome = safe_get(frame, "outcome", None)
        self_observation = safe_get(frame, "self_observation", None)
        temporal = safe_get(frame, "temporal", None)

        # Semantic reports đã tồn tại trong kiến trúc mới. Budget phải đọc chúng trước,
        # không tự đóng vai classifier nghèo bằng keyword groups nữa.
        affect_signal = safe_get(frame, "affect_signal", None) or safe_get(frame, "affect_semantics", None)
        conversation = safe_get(frame, "conversation_dynamics", None) or safe_get(frame, "conversation_report", None)
        source_grounding = (
            safe_get(frame, "source_grounding", None)
            or safe_get(frame, "grounding_source", None)
            or safe_get(frame, "pre_grounding", None)
            or safe_get(frame, "grounding", None)
        )

        text_blob = self._collect_text_blob(
            frame,
            user_text=user_text,
            evidence=evidence,
            raw_signals=raw_signals,
            salience=salience,
            working_memory=working_memory,
            workspace=workspace,
            meaning=meaning,
            memory_packet=memory_packet,
        )

        current_user_text = (user_text or self._extract_user_text_from_signals(raw_signals, evidence)).strip()
        has_user_text = bool(current_user_text)
        user_directness = self._estimate_user_directness(channel, current_user_text, evidence, raw_signals, text_blob)
        signal_density = self._estimate_signal_density(evidence, raw_signals, salience, working_memory, workspace)
        salience_priority = self._estimate_salience_priority(salience)
        context_pressure = self._estimate_context_pressure(working_memory, workspace, salience, evidence)
        risk_pressure, risk_semantic_support, risk_keyword_pressure, risk_keyword_only = self._estimate_risk_pressure(
            text_blob, salience, workspace, permission, tom, source_grounding=source_grounding
        )
        privacy_pressure = self._estimate_privacy_pressure(text_blob, evidence, workspace, permission)
        technical_depth, technical_semantic_support, technical_keyword_pressure, technical_keyword_only = self._estimate_technical_depth(
            text_blob, evidence, meaning, affect_signal=affect_signal, source_grounding=source_grounding, user_text=current_user_text
        )
        architecture_depth, architecture_semantic_support, architecture_keyword_pressure, architecture_keyword_only = self._estimate_architecture_depth(
            text_blob, evidence, meaning, affect_signal=affect_signal, source_grounding=source_grounding, user_text=current_user_text
        )
        correction_pressure, correction_semantic_support, correction_keyword_pressure, correction_keyword_only = self._estimate_correction_pressure(
            text_blob, evidence, outcome, self_observation, affect_signal=affect_signal, conversation=conversation, has_user_text=has_user_text
        )
        contradiction_pressure = self._estimate_contradiction_pressure(text_blob, evidence, belief, self_observation)
        relational_rupture = self._estimate_relational_rupture(text_blob, relation, outcome, self_observation)
        affective_residue = self._estimate_affective_residue(text_blob, affect, relation)
        homeostasis_load = self._estimate_homeostasis_load(homeostasis, affect)
        goal_pressure, goal_permission = self._estimate_goal_pressure(frame, text_blob)
        memory_conflict = self._estimate_memory_conflict(text_blob, memory_packet, belief, self_observation)
        worldview_pressure = self._estimate_worldview_pressure(text_blob, belief)
        uncertainty = self._estimate_uncertainty(tom, meaning, salience, workspace)
        ambiguity = self._estimate_ambiguity(meaning, tom, text_blob)
        idle_pressure = self._estimate_idle_pressure(temporal, homeostasis, idle_seconds)
        session_closing_pressure = 1.0 if session_ending else self._estimate_session_closing_pressure(text_blob, temporal)
        shutdown_pressure = 1.0 if shutdown else (1.0 if channel == "shutdown" else 0.0)
        reflection_debt = self._estimate_reflection_debt(
            text_blob,
            outcome,
            self_observation,
            relation,
            affect,
            correction_pressure=correction_pressure,
            contradiction_pressure=contradiction_pressure,
            idle_pressure=idle_pressure,
            session_closing_pressure=session_closing_pressure,
            shutdown_pressure=shutdown_pressure,
        )
        speech_need = self._estimate_speech_need(frame, channel, user_directness, salience_priority, text_blob)
        body_need = self._estimate_body_need(frame, workspace, text_blob)
        low_stakes_ambient = self._estimate_low_stakes_ambient(
            channel=channel,
            has_user_text=has_user_text,
            signal_density=signal_density,
            salience_priority=salience_priority,
            risk_pressure=risk_pressure,
            technical_depth=technical_depth,
            relational_rupture=relational_rupture,
            idle_pressure=idle_pressure,
        )

        return BudgetSignalSnapshot(
            channel=channel,
            user_directness=user_directness,
            signal_density=signal_density,
            salience_priority=salience_priority,
            context_pressure=context_pressure,
            risk_pressure=risk_pressure,
            privacy_pressure=privacy_pressure,
            technical_depth=technical_depth,
            architecture_depth=architecture_depth,
            correction_pressure=correction_pressure,
            contradiction_pressure=contradiction_pressure,
            relational_rupture=relational_rupture,
            technical_semantic_support=technical_semantic_support,
            architecture_semantic_support=architecture_semantic_support,
            correction_semantic_support=correction_semantic_support,
            risk_semantic_support=risk_semantic_support,
            technical_keyword_pressure=technical_keyword_pressure,
            architecture_keyword_pressure=architecture_keyword_pressure,
            correction_keyword_pressure=correction_keyword_pressure,
            risk_keyword_pressure=risk_keyword_pressure,
            technical_keyword_only=technical_keyword_only,
            architecture_keyword_only=architecture_keyword_only,
            correction_keyword_only=correction_keyword_only,
            risk_keyword_only=risk_keyword_only,
            affective_residue=affective_residue,
            homeostasis_load=homeostasis_load,
            goal_pressure=goal_pressure,
            goal_intervention_permission=goal_permission,
            memory_conflict=memory_conflict,
            worldview_pressure=worldview_pressure,
            uncertainty=uncertainty,
            ambiguity=ambiguity,
            idle_pressure=idle_pressure,
            session_closing_pressure=session_closing_pressure,
            shutdown_pressure=shutdown_pressure,
            reflection_debt=reflection_debt,
            speech_need=speech_need,
            body_need=body_need,
            low_stakes_ambient=low_stakes_ambient,
            force_reflection=bool(force_reflection),
            force_deep=bool(force_deep),
            force_fast=bool(force_fast),
            has_user_text=has_user_text,
            has_user_correction=correction_pressure >= 0.45,
            has_technical_request=technical_depth >= 0.45,
            has_architecture_request=architecture_depth >= 0.45,
            has_relational_event=relational_rupture >= 0.40,
            has_memory_contradiction=memory_conflict >= 0.45 or contradiction_pressure >= 0.55,
            has_worldview_update=worldview_pressure >= 0.48,
            has_high_value_decision=self._estimate_high_value_decision(
                text_blob,
                technical_depth,
                architecture_depth,
                max(technical_semantic_support, architecture_semantic_support),
            ) >= 0.55,
        )

    def _collect_text_blob(
        self,
        frame: Any,
        *,
        user_text: str,
        evidence: Sequence[Any],
        raw_signals: Sequence[Any],
        salience: Any,
        working_memory: Any,
        workspace: Any,
        meaning: Any,
        memory_packet: Any,
    ) -> str:
        parts: list[str] = []
        if user_text:
            parts.append(user_text)

        for item in evidence[:24]:
            parts.append(text_of(safe_get(item, "claim", item), max_len=300))
            tags = safe_get(item, "tags", [])
            if tags:
                parts.append(" ".join(str(tag) for tag in as_list(tags)))

        for signal in raw_signals[:12]:
            parts.append(text_of(safe_get(signal, "content", signal), max_len=240))
            parts.append(str(safe_get(signal, "source", "")))

        for attr in (
            "dominant_focus",
            "reason",
            "broadcast_reason",
            "dominant_thread",
            "selected_goal",
            "selected_risk",
            "selected_social_hypothesis",
            "summary",
            "prompt_context",
        ):
            for obj in (salience, working_memory, workspace, meaning, memory_packet):
                value = safe_get(obj, attr, None)
                if value:
                    parts.append(text_of(value, max_len=350))

        # Working memory slots / workspace items.
        for slot in as_list(safe_get(working_memory, "active_slots", []))[:10]:
            parts.append(text_of(safe_get(slot, "name", ""), max_len=100))
            parts.append(text_of(safe_get(slot, "content", slot), max_len=300))
        for item in as_list(safe_get(workspace, "selected_items", []))[:12]:
            parts.append(text_of(safe_get(item, "content", item), max_len=300))

        blob = " ".join(part for part in parts if part).lower()
        return re.sub(r"\s+", " ", blob).strip()[:5000]

    def _extract_user_text_from_signals(self, raw_signals: Sequence[Any], evidence: Sequence[Any]) -> str:
        for signal in raw_signals:
            source = str(safe_get(signal, "source", ""))
            if source == "user_chat":
                return text_of(safe_get(signal, "content", ""), max_len=1000)
        for ev in evidence:
            source = str(safe_get(ev, "source", ""))
            tags = {str(tag) for tag in as_list(safe_get(ev, "tags", []))}
            if source == "user_chat" or "user_chat" in tags or "current_user_request" in tags:
                return text_of(safe_get(ev, "claim", ""), max_len=1000)
        return ""

    # ------------------------------------------------------------------
    # Pressure estimators
    # ------------------------------------------------------------------

    def _estimate_user_directness(
        self,
        channel: str,
        user_text: str,
        evidence: Sequence[Any],
        raw_signals: Sequence[Any],
        text_blob: str,
    ) -> float:
        score = 0.0
        if channel == "chat":
            score += 0.52
        elif channel == "force_speak":
            score += 0.42
        elif channel == "session_start":
            score += 0.18
        if user_text.strip():
            score += 0.32
            if len(user_text.strip()) <= 8:
                score -= 0.08
            if "?" in user_text or any(w in user_text.lower() for w in ("làm", "tạo", "gửi", "fix", "sửa", "giải thích", "đánh giá")):
                score += 0.18
        user_sources = 0
        for ev in evidence:
            if str(safe_get(ev, "source", "")) == "user_chat":
                user_sources += 1
        for sig in raw_signals:
            if str(safe_get(sig, "source", "")) == "user_chat":
                user_sources += 1
        score += min(0.24, user_sources * 0.08)
        if contains_any(text_blob, ("ngài", "bạn", "eris")):
            score += 0.05
        return clamp01(score)

    def _estimate_signal_density(self, evidence: Sequence[Any], raw_signals: Sequence[Any], salience: Any, working_memory: Any, workspace: Any) -> float:
        count = len(evidence) * 0.06 + len(raw_signals) * 0.035
        selected = as_list(safe_get(salience, "selected_candidates", []))
        selected_ids = as_list(safe_get(salience, "selected_evidence_ids", []))
        wm_slots = as_list(safe_get(working_memory, "active_slots", []))
        workspace_items = as_list(safe_get(workspace, "selected_items", []))
        count += len(selected) * 0.08 + len(selected_ids) * 0.04 + len(wm_slots) * 0.10 + len(workspace_items) * 0.05
        return clamp01(count)

    def _estimate_salience_priority(self, salience: Any) -> float:
        if salience is None:
            return 0.0
        values = [
            safe_get(salience, "broadcast_priority", None),
            safe_get(salience, "broadcast_score", None),
            safe_get(salience, "score", None),
            safe_get(salience, "urgency", None),
            safe_get(salience, "goal_relevance", None),
            safe_get(salience, "risk_relevance", None),
            safe_get(salience, "user_relevance", None),
        ]
        score = max(clamp01(v, default=0.0) for v in values if v is not None) if any(v is not None for v in values) else 0.0
        candidates = as_list(safe_get(salience, "selected_candidates", []))
        for candidate in candidates[:8]:
            score = max(score, clamp01(safe_get(candidate, "score", 0.0)))
            score = max(score, clamp01(safe_get(candidate, "final_score", 0.0)))
            score = max(score, clamp01(safe_get(candidate, "broadcast_priority", 0.0)))
        if safe_get(salience, "dominant_focus", None):
            score = max(score, 0.38)
        return clamp01(score)

    def _estimate_context_pressure(self, working_memory: Any, workspace: Any, salience: Any, evidence: Sequence[Any]) -> float:
        values = [
            safe_get(working_memory, "context_pressure", None),
            safe_get(workspace, "context_pressure", None),
            safe_get(salience, "context_pressure", None),
        ]
        score = max(clamp01(v) for v in values if v is not None) if any(v is not None for v in values) else 0.0
        suppressed = len(as_list(safe_get(working_memory, "suppressed_items", [])))
        suppressed += len(as_list(safe_get(salience, "suppressed_signals", [])))
        context_flood = safe_get(salience, "context_flood", None)
        if context_flood:
            score = max(score, clamp01(safe_get(context_flood, "pressure", 0.0)))
            score = max(score, clamp01(safe_get(context_flood, "flood_score", 0.0)))
        score = max(score, min(1.0, len(evidence) / 32.0 + suppressed / 24.0))
        return clamp01(score)

    def _semantic_number(self, obj: Any, *names: str) -> float:
        """Đọc nhiều tên field có thể có từ semantic reports.

        Repo đang tiến hóa nên cùng một ý có thể nằm ở `technicality`,
        `technical_depth`, `task_relevance`, `pressure`, v.v. Budget chỉ đọc mềm.
        """

        score = 0.0
        for name in names:
            score = max(score, clamp01(safe_get_path(obj, name, 0.0)))
            score = max(score, clamp01(safe_get(obj, name, 0.0)))
        return clamp01(score)

    def _evidence_tag_score(self, evidence: Sequence[Any], tags: set[str], *, base: float = 0.42, step: float = 0.10) -> float:
        hits = 0
        for ev in evidence:
            ev_tags = {str(tag).lower() for tag in as_list(safe_get(ev, "tags", []))}
            source = str(safe_get(ev, "source", "")).lower()
            claim_style = str(safe_get(ev, "claim_style", "")).lower()
            if ev_tags & tags or source in tags or claim_style in tags:
                hits += 1
        if hits <= 0:
            return 0.0
        return clamp01(base + hits * step)

    def _source_grounding_score(self, source_grounding: Any, sources: set[str]) -> float:
        if source_grounding is None:
            return 0.0
        values = [
            str(safe_get(source_grounding, "primary_source", "")).lower(),
            str(safe_get(source_grounding, "grounding_source", "")).lower(),
            str(safe_get(source_grounding, "source", "")).lower(),
            str(safe_get(source_grounding, "preempt_mode", "")).lower(),
        ]
        allowed = {str(v).lower() for v in as_list(safe_get(source_grounding, "allowed_sources", []))}
        if any(value in sources for value in values if value) or (allowed & sources):
            return max(0.56, clamp01(safe_get(source_grounding, "confidence", 0.0)))
        return 0.0

    def _meaning_support(self, meaning: Any, keywords: Sequence[str], *, task_weight: float = 0.55) -> float:
        if meaning is None:
            return 0.0
        score = 0.0
        dominant = safe_get(meaning, "dominant_hypothesis", None)
        hypotheses = as_list(safe_get(meaning, "hypotheses", []))
        candidates = [dominant] if dominant is not None else []
        candidates.extend(hypotheses[:5])
        for hyp in candidates:
            text = lower_text(hyp, max_len=600)
            if contains_any(text, keywords):
                score = max(score, 0.48)
            score = max(score, clamp01(safe_get(hyp, "task_relevance", 0.0)) * task_weight)
            score = max(score, clamp01(safe_get(hyp, "confidence", 0.0)) * 0.35 if contains_any(text, keywords) else 0.0)
        score = max(score, clamp01(safe_get(meaning, "task_relevance", 0.0)) * task_weight)
        return clamp01(score)

    def _estimate_risk_pressure(
        self,
        text_blob: str,
        salience: Any,
        workspace: Any,
        permission: Any,
        tom: Any,
        *,
        source_grounding: Any = None,
        user_text: str = "",
    ) -> tuple[float, float, float, bool]:
        user_lower = (user_text or "").lower()
        keyword = weighted_keyword_score(
            text_blob,
            {"risk": RISK_KEYWORDS},
            {"risk": 0.50},
        )
        semantic = 0.0
        for obj in (salience, workspace, permission, tom, source_grounding):
            if obj is None:
                continue
            for attr in (
                "risk_relevance",
                "risk_pressure",
                "privacy_risk",
                "social_risk",
                "permission_violation",
                "overread_risk",
                "global_overread_risk",
                "factual_risk",
                "confidence_cap",
            ):
                semantic = max(semantic, clamp01(safe_get(obj, attr, 0.0)))
        selected_risk = safe_get(workspace, "selected_risk", None)
        if selected_risk:
            semantic = max(semantic, 0.48)
        if safe_get(source_grounding, "missing_evidence", None):
            semantic = max(semantic, 0.46)
        score, keyword_only = blend_semantic_and_keyword(
            semantic=semantic,
            keyword=keyword,
            keyword_cap_without_semantic=self.config.keyword_only_pressure_cap,
            semantic_floor_for_uncap=self.config.keyword_semantic_support_floor,
            keyword_weight_when_supported=self.config.keyword_supported_weight,
        )
        return score, semantic, keyword, keyword_only

    def _estimate_privacy_pressure(self, text_blob: str, evidence: Sequence[Any], workspace: Any, permission: Any) -> float:
        score = 0.0
        if contains_any(text_blob, ("private", "privacy", "sensitive", "secret", "riêng tư", "nhạy cảm", "bảo mật")):
            score = max(score, 0.58)
        for ev in evidence:
            privacy = str(safe_get(ev, "privacy_level", "normal"))
            if privacy == "private":
                score = max(score, 0.55)
            elif privacy == "sensitive":
                score = max(score, 0.78)
        for item in as_list(safe_get(workspace, "selected_items", [])):
            privacy = str(safe_get(item, "privacy_level", "normal"))
            if privacy == "private":
                score = max(score, 0.52)
            elif privacy == "sensitive":
                score = max(score, 0.76)
        if safe_get(permission, "raw_evidence_storable", True) is False:
            score = max(score, 0.54)
        if safe_get(permission, "memory_storable", True) is False:
            score = max(score, 0.50)
        return clamp01(score)

    def _estimate_technical_depth(
        self,
        text_blob: str,
        evidence: Sequence[Any],
        meaning: Any,
        *,
        affect_signal: Any = None,
        source_grounding: Any = None,
        user_text: str = "",
    ) -> tuple[float, float, float, bool]:
        user_lower = (user_text or "").lower()
        keyword = weighted_keyword_score(
            text_blob,
            {
                "technical": TECHNICAL_KEYWORDS,
                "high_value": HIGH_VALUE_KEYWORDS,
            },
            {
                "technical": 0.46,
                "high_value": 0.18,
            },
        )
        semantic = 0.0
        semantic = max(
            semantic,
            self._semantic_number(
                affect_signal,
                "technicality",
                "technical_depth",
                "directive_pressure",
                "answer_need",
                "task_relevance",
            ),
        )
        semantic = max(
            semantic,
            self._evidence_tag_score(
                evidence,
                {"technical", "code", "debug", "implementation", "runtime", "pasted_code", "uploaded_file"},
                base=0.46,
                step=0.10,
            ),
        )
        semantic = max(
            semantic,
            self._source_grounding_score(
                source_grounding,
                {"pasted_code", "uploaded_file", "current_screen", "live_vision", "filename_only"},
            ) * 0.92,
        )
        semantic = max(semantic, self._meaning_support(meaning, TECHNICAL_KEYWORDS, task_weight=0.62))
        if user_lower and contains_any(
            user_lower,
            ("code", "debug", "bug", "traceback", "exception", "compile", "python", "c#", "godot", "repo", "module", "dataclass", "lỗi", "fix"),
        ):
            semantic = max(semantic, 0.44)

        score, keyword_only = blend_semantic_and_keyword(
            semantic=semantic,
            keyword=keyword,
            keyword_cap_without_semantic=self.config.keyword_only_pressure_cap,
            semantic_floor_for_uncap=self.config.keyword_semantic_support_floor,
            keyword_weight_when_supported=self.config.keyword_supported_weight,
        )
        return score, semantic, keyword, keyword_only

    def _estimate_architecture_depth(
        self,
        text_blob: str,
        evidence: Sequence[Any],
        meaning: Any,
        *,
        affect_signal: Any = None,
        source_grounding: Any = None,
        user_text: str = "",
    ) -> tuple[float, float, float, bool]:
        user_lower = (user_text or "").lower()
        keyword = weighted_keyword_score(
            text_blob,
            {
                "architecture": ARCHITECTURE_KEYWORDS,
                "high_value": HIGH_VALUE_KEYWORDS,
            },
            {
                "architecture": 0.48,
                "high_value": 0.20,
            },
        )
        semantic = 0.0
        semantic = max(
            semantic,
            self._semantic_number(
                affect_signal,
                "architecture_depth",
                "design_pressure",
                "abstraction_pressure",
                "system_design",
            ) * 0.94,
        )
        semantic = max(
            semantic,
            self._evidence_tag_score(
                evidence,
                {"architecture", "pipeline", "contract", "module_contract", "design", "runtime_design"},
                base=0.52,
                step=0.11,
            ),
        )
        semantic = max(semantic, self._meaning_support(meaning, ARCHITECTURE_KEYWORDS, task_weight=0.68))
        semantic = max(
            semantic,
            self._source_grounding_score(source_grounding, {"uploaded_file", "pasted_code", "filename_only"}) * 0.55,
        )
        if user_lower and contains_any(
            user_lower,
            ("architecture", "pipeline", "contract", "backbone", "runtime", "workspace", "working memory", "global workspace", "attention", "evidence", "module", "kiến trúc", "xương sống", "tầng", "mô hình"),
        ):
            semantic = max(semantic, 0.50)

        # Các tên contract nội bộ chỉ nâng semantic nếu chúng xuất hiện trong user/evidence đã chọn,
        # không còn tự bắn architecture=0.72 từ toàn bộ text_blob nữa.
        if keyword > 0.35 and semantic >= 0.30 and contains_any(
            text_blob,
            ("globalworkspace", "cognitivebudget", "cognitive budget", "workingmemory", "rawsignal", "evidenceitem"),
        ):
            semantic = max(semantic, 0.62)

        score, keyword_only = blend_semantic_and_keyword(
            semantic=semantic,
            keyword=keyword,
            keyword_cap_without_semantic=self.config.keyword_only_pressure_cap,
            semantic_floor_for_uncap=self.config.keyword_semantic_support_floor,
            keyword_weight_when_supported=self.config.keyword_supported_weight,
        )
        return score, semantic, keyword, keyword_only

    def _estimate_correction_pressure(
        self,
        text_blob: str,
        evidence: Sequence[Any],
        outcome: Any,
        self_observation: Any,
        *,
        affect_signal: Any = None,
        conversation: Any = None,
        has_user_text: bool = False,
    ) -> tuple[float, float, float, bool]:
        keyword = weighted_keyword_score(text_blob, {"correction": CORRECTION_KEYWORDS}, {"correction": 0.58})
        semantic = 0.0
        semantic = max(
            semantic,
            self._semantic_number(
                affect_signal,
                "correction",
                "correction_pressure",
                "conflict",
                "directive_pressure",
            ),
        )
        semantic = max(
            semantic,
            self._semantic_number(
                conversation,
                "correction_severity",
                "semantic_tension",
                "conversation_pressure",
                "semantic_divergence",
            ),
        )
        mode = str(safe_get(conversation, "mode", "")).lower()
        last_failure_obj = safe_get(conversation, "last_failure", "")
        last_failure = str(safe_get(last_failure_obj, "type", last_failure_obj)).lower()
        if mode in {"repair", "relational_repair", "execute", "compress"}:
            semantic = max(semantic, 0.58)
        if last_failure in {"misread", "underacted", "overexplained", "tone_mismatch", "wrong_abstraction", "overread", "format_error"}:
            semantic = max(semantic, 0.54)
        semantic = max(
            semantic,
            self._evidence_tag_score(
                evidence,
                {"correction", "user_correction", "repair", "misread", "wrong_assumption"},
                base=0.56,
                step=0.12,
            ),
        )
        if safe_get(outcome, "user_corrected", False):
            semantic = max(semantic, 0.78)
        if safe_get(self_observation, "overread_detected", False):
            semantic = max(semantic, 0.70)
        if safe_get(self_observation, "spoke_too_much", False) or safe_get(self_observation, "hid_too_much", False):
            semantic = max(semantic, 0.55)

        # Một correction trực tiếp từ user là evidence hợp lệ, dù chưa có conversation report.
        if has_user_text and keyword >= 0.35:
            semantic = max(semantic, 0.48)

        score, keyword_only = blend_semantic_and_keyword(
            semantic=semantic,
            keyword=keyword,
            keyword_cap_without_semantic=self.config.keyword_only_pressure_cap,
            semantic_floor_for_uncap=self.config.keyword_semantic_support_floor,
            keyword_weight_when_supported=self.config.keyword_supported_weight,
        )
        return score, semantic, keyword, keyword_only

    def _estimate_contradiction_pressure(self, text_blob: str, evidence: Sequence[Any], belief: Any, self_observation: Any) -> float:
        score = weighted_keyword_score(text_blob, {"memory_conflict": MEMORY_CONFLICT_KEYWORDS}, {"memory_conflict": 0.62})
        for ev in evidence:
            tags = {str(tag).lower() for tag in as_list(safe_get(ev, "tags", []))}
            if tags & {"contradiction", "conflict", "memory_conflict", "belief_conflict"}:
                score = max(score, 0.58)
        contradictions = as_list(safe_get(belief, "contradictions", []))
        if contradictions:
            score = max(score, min(1.0, 0.45 + len(contradictions) * 0.12))
        if safe_get(self_observation, "matched_beliefs", True) is False:
            score = max(score, 0.52)
        return clamp01(score)

    def _estimate_relational_rupture(self, text_blob: str, relation: Any, outcome: Any, self_observation: Any) -> float:
        score = weighted_keyword_score(text_blob, {"rupture": RELATIONAL_RUPTURE_KEYWORDS}, {"rupture": 0.64})
        for attr in ("rupture", "repair_need", "dignity_defense", "exposure_recoil", "overread_correction"):
            score = max(score, clamp01(safe_get(relation, attr, 0.0)) * (1.0 if attr in {"rupture", "repair_need"} else 0.85))
        if safe_get(outcome, "relation_ruptured", False):
            score = max(score, 0.82)
        if safe_get(outcome, "user_felt_intruded", False):
            score = max(score, 0.74)
        if safe_get(self_observation, "distance_violation", False) or safe_get(self_observation, "curiosity_intrusion", False):
            score = max(score, 0.68)
        return clamp01(score)

    def _estimate_affective_residue(self, text_blob: str, affect: Any, relation: Any) -> float:
        score = 0.0
        residue = safe_get(affect, "affective_residue", None)
        if isinstance(residue, Mapping) and residue:
            try:
                score = max(score, max(clamp01(v) for v in residue.values()))
            except Exception:
                pass
        for attr in (
            "tension",
            "arousal",
            "attachment_pressure",
            "irritation",
            "tenderness",
            "exposure_recoil",
            "continuity_anxiety",
        ):
            score = max(score, clamp01(safe_get(affect, attr, 0.0)) * 0.90)
        for attr in ("attachment_visibility", "exposure_recoil", "irritation_memory", "rupture"):
            score = max(score, clamp01(safe_get(relation, attr, 0.0)) * 0.80)
        if contains_any(text_blob, ("emotional_residue", "affective", "dư âm", "tổn thương", "bị bỏ mặc")):
            score = max(score, 0.52)
        return clamp01(score)

    def _estimate_homeostasis_load(self, homeostasis: Any, affect: Any) -> float:
        values = []
        for attr in (
            "cognitive_load",
            "social_load",
            "exposure_load",
            "speech_cost",
            "silence_recovery_need",
            "curiosity_pressure",
            "attachment_pressure",
            "irritation_pressure",
        ):
            values.append(clamp01(safe_get(homeostasis, attr, 0.0)))
        for attr in ("fatigue", "tension", "arousal", "restraint", "exposure_recoil"):
            values.append(clamp01(safe_get(affect, attr, 0.0)) * 0.90)
        return clamp01(max(values) if values else 0.0)

    def _estimate_goal_pressure(self, frame: Any, text_blob: str) -> tuple[float, float]:
        goal_state = safe_get(frame, "goal_persistence", None) or safe_get(frame, "goal", None)
        # Một số repo đặt goal_state trong internal_state.
        internal_state = safe_get(frame, "internal_state", None)
        goal_state = goal_state or safe_get(internal_state, "goal_persistence", None)

        strength = clamp01(safe_get(goal_state, "strength", 0.0))
        urgency = clamp01(safe_get(goal_state, "urgency", 0.0))
        drift = clamp01(safe_get(goal_state, "drift", 0.0))
        confidence = clamp01(safe_get(goal_state, "confidence", 0.0))
        actionability = clamp01(safe_get(goal_state, "actionability", 0.0))
        permission = clamp01(safe_get(goal_state, "intervention_permission", 0.0))
        can_intervene = bool(safe_get(goal_state, "can_intervene", False))
        active = str(safe_get(goal_state, "status", "")).lower() == "active" or bool(safe_get(goal_state, "active", False))
        score = max(strength, urgency * 0.9, drift * 0.7, confidence * actionability)
        if active:
            score = max(score, 0.36 + strength * 0.45)
        if can_intervene:
            score = max(score, 0.56 + permission * 0.25)
        if contains_any(text_blob, ("goal", "mục tiêu", "roadmap", "hướng", "tiếp theo", "nên làm gì")):
            score = max(score, 0.46)
        return clamp01(score), clamp01(permission if permission else (0.65 if can_intervene else 0.0))

    def _estimate_memory_conflict(self, text_blob: str, memory_packet: Any, belief: Any, self_observation: Any) -> float:
        score = weighted_keyword_score(text_blob, {"memory": MEMORY_CONFLICT_KEYWORDS}, {"memory": 0.66})
        for attr in ("confidence_notes", "contradictions", "open_questions"):
            items = as_list(safe_get(memory_packet, attr, [])) + as_list(safe_get(belief, attr, []))
            if items:
                score = max(score, min(1.0, 0.36 + len(items) * 0.10))
        if safe_get(self_observation, "overread_detected", False):
            score = max(score, 0.46)
        return clamp01(score)

    def _estimate_worldview_pressure(self, text_blob: str, belief: Any) -> float:
        score = 0.0
        if contains_any(text_blob, ("worldview", "belief", "axiom", "value", "giá trị", "niềm tin", "thế giới quan", "conceptgraph", "concept graph")):
            score = max(score, 0.55)
        open_questions = as_list(safe_get(belief, "open_questions", []))
        candidates = as_list(safe_get(belief, "candidate_beliefs", []))
        contradictions = as_list(safe_get(belief, "contradictions", []))
        if candidates:
            score = max(score, min(1.0, 0.30 + len(candidates) * 0.08))
        if open_questions:
            score = max(score, min(1.0, 0.28 + len(open_questions) * 0.06))
        if contradictions:
            score = max(score, 0.50)
        return clamp01(score)

    def _estimate_uncertainty(self, tom: Any, meaning: Any, salience: Any, workspace: Any) -> float:
        values = [
            1.0 - clamp01(safe_get(tom, "global_confidence", 1.0), default=1.0),
            clamp01(safe_get(tom, "global_overread_risk", 0.0)),
            clamp01(safe_get(meaning, "ambiguity", 0.0)),
            1.0 - clamp01(safe_get(salience, "confidence", 1.0), default=1.0),
            1.0 - clamp01(safe_get(workspace, "confidence", 1.0), default=1.0),
        ]
        return clamp01(max(values))

    def _estimate_ambiguity(self, meaning: Any, tom: Any, text_blob: str) -> float:
        score = clamp01(safe_get(meaning, "ambiguity", 0.0))
        score = max(score, clamp01(safe_get(tom, "global_overread_risk", 0.0)) * 0.80)
        if contains_any(text_blob, ("?", "hay sao", "nhỉ", "maybe", "có lẽ", "không chắc", "mơ hồ")):
            score = max(score, 0.36)
        if bool(safe_get(meaning, "needs_clarification", False)):
            score = max(score, 0.62)
        return clamp01(score)

    def _estimate_idle_pressure(self, temporal: Any, homeostasis: Any, idle_seconds: Optional[float]) -> float:
        score = 0.0
        if idle_seconds is not None:
            score = max(score, clamp(float(idle_seconds) / 600.0, 0.0, 1.0))
        for attr in ("waiting_pressure", "unfinished_time_pressure", "meaning_debt", "repetition_fatigue"):
            score = max(score, clamp01(safe_get(temporal, attr, 0.0)))
        score = max(score, clamp01(safe_get(homeostasis, "silence_recovery_need", 0.0)) * 0.75)
        rhythm = str(safe_get(temporal, "rhythm", "")).lower()
        session_arc = str(safe_get(temporal, "session_arc", "")).lower()
        if rhythm == "idle":
            score = max(score, 0.42)
        if session_arc in {"fatigue", "closing"}:
            score = max(score, 0.55)
        return clamp01(score)

    def _estimate_session_closing_pressure(self, text_blob: str, temporal: Any) -> float:
        score = 0.0
        session_arc = str(safe_get(temporal, "session_arc", "")).lower()
        if session_arc == "closing":
            score = max(score, 0.72)
        if contains_any(text_blob, ("shutdown", "session end", "closing", "tắt", "thoát", "đóng phiên", "nghỉ", "kết thúc")):
            score = max(score, 0.68)
        return clamp01(score)

    def _estimate_reflection_debt(
        self,
        text_blob: str,
        outcome: Any,
        self_observation: Any,
        relation: Any,
        affect: Any,
        *,
        correction_pressure: float,
        contradiction_pressure: float,
        idle_pressure: float,
        session_closing_pressure: float,
        shutdown_pressure: float,
    ) -> float:
        score = weighted_keyword_score(text_blob, {"reflection": REFLECTION_KEYWORDS}, {"reflection": 0.64})
        if safe_get(outcome, "user_corrected", False):
            score = max(score, 0.68)
        if safe_get(outcome, "relation_ruptured", False) or safe_get(outcome, "user_felt_intruded", False):
            score = max(score, 0.72)
        for attr in ("overread_detected", "distance_violation", "curiosity_intrusion", "spoke_too_much", "hid_too_much", "modality_mismatch", "cultural_misread"):
            if safe_get(self_observation, attr, False):
                score = max(score, 0.56)
        score = max(score, correction_pressure * 0.85, contradiction_pressure * 0.80)
        score = max(score, clamp01(safe_get(relation, "repair_need", 0.0)) * 0.85)
        score = max(score, clamp01(safe_get(affect, "affective_residue", 0.0)) if not isinstance(safe_get(affect, "affective_residue", None), Mapping) else 0.0)
        if idle_pressure > 0.70:
            score = max(score, 0.52 + (idle_pressure - 0.70) * 0.80)
        score = max(score, session_closing_pressure, shutdown_pressure)
        return clamp01(score)

    def _estimate_speech_need(self, frame: Any, channel: str, user_directness: float, salience_priority: float, text_blob: str) -> float:
        speech_opportunity = safe_get(frame, "speech_opportunity", None)
        speech_plan = safe_get(frame, "speech_plan", None)
        agency = safe_get(frame, "agency", None)
        score = max(user_directness * 0.80, salience_priority * 0.45)
        if bool(safe_get(speech_opportunity, "speech_allowed", False)):
            score = max(score, 0.55)
        score = max(score, clamp01(safe_get(speech_opportunity, "urgency", 0.0)))
        if safe_get(speech_plan, "speech_act", None):
            score = max(score, 0.48)
        if str(safe_get(agency, "intent", "")).lower() in {"speak", "ask", "repair", "search"}:
            score = max(score, 0.56)
        if channel in {"chat", "force_speak"}:
            score = max(score, 0.55)
        if contains_any(text_blob, ("trả lời", "answer", "direct_answer", "practical_help", "technical_diagnosis")):
            score = max(score, 0.48)
        return clamp01(score)

    def _estimate_body_need(self, frame: Any, workspace: Any, text_blob: str) -> float:
        spatial = safe_get(frame, "spatial", None)
        body_plan = safe_get(frame, "body_plan", None)
        modality = safe_get(frame, "modality", None)
        score = 0.0
        if safe_get(spatial, "body_interaction_meaning", None):
            score = max(score, 0.36)
        score = max(score, clamp01(safe_get(spatial, "obstruction_risk", 0.0)) * 0.90)
        score = max(score, clamp01(safe_get(spatial, "approach_affordance", 0.0)) * 0.45)
        if safe_get(body_plan, "action", None) not in {None, "", "none"}:
            score = max(score, 0.50)
        score = max(score, clamp01(safe_get(modality, "contradiction_risk", 0.0)) * 0.75)
        if safe_get(workspace, "selected_body_state", None):
            score = max(score, 0.34)
        if contains_any(text_blob, ("body", "gaze", "posture", "movement", "motion", "thân thể", "di chuyển", "nhìn", "đứng", "ngồi")):
            score = max(score, 0.42)
        return clamp01(score)

    def _estimate_low_stakes_ambient(
        self,
        *,
        channel: str,
        has_user_text: bool,
        signal_density: float,
        salience_priority: float,
        risk_pressure: float,
        technical_depth: float,
        relational_rupture: float,
        idle_pressure: float,
    ) -> float:
        if channel not in {"autonomous", "session_start", "unknown"}:
            return 0.0
        score = 0.0
        if not has_user_text:
            score += 0.32
        if signal_density < self.config.low_signal_density_threshold:
            score += 0.24
        if salience_priority < self.config.low_salience_threshold:
            score += 0.20
        if risk_pressure < 0.20 and technical_depth < 0.25 and relational_rupture < 0.20:
            score += 0.18
        if idle_pressure >= self.config.fast_idle_pressure_threshold:
            score += 0.10
        return clamp01(score)

    def _estimate_high_value_decision(
        self,
        text_blob: str,
        technical_depth: float,
        architecture_depth: float,
        semantic_support: float,
    ) -> float:
        keyword = weighted_keyword_score(text_blob, {"high_value": HIGH_VALUE_KEYWORDS}, {"high_value": 0.44})
        if keyword <= 0.0:
            return 0.0
        semantic = clamp01(semantic_support)
        if keyword >= 0.22 and architecture_depth > 0.55 and technical_depth > 0.45 and semantic >= 0.38:
            semantic = max(semantic, 0.66)
        score, keyword_only = blend_semantic_and_keyword(
            semantic=semantic,
            keyword=keyword,
            keyword_cap_without_semantic=0.38,
            semantic_floor_for_uncap=self.config.keyword_semantic_support_floor,
            keyword_weight_when_supported=0.30,
        )
        return min(score, 0.48) if keyword_only else score

    # ------------------------------------------------------------------
    # Scoring / choosing
    # ------------------------------------------------------------------

    def _score_modes(
        self,
        snapshot: BudgetSignalSnapshot,
        *,
        previous_decisions: Optional[Sequence[BudgetDecision | Mapping[str, Any]]] = None,
    ) -> BudgetScoreBreakdown:
        s = snapshot

        fast = 0.20
        fast += s.low_stakes_ambient * 0.62
        fast += (1.0 - s.signal_density) * 0.18
        fast += (1.0 - s.task_pressure()) * 0.16
        fast -= s.risk_pressure * 0.26
        fast -= s.technical_depth * 0.20
        fast -= s.architecture_depth * 0.30
        fast -= s.correction_pressure * 0.26
        fast -= s.relational_rupture * 0.28
        fast -= s.memory_conflict * 0.24
        fast -= s.reflection_pressure() * 0.34
        if s.channel in {"chat", "force_speak"}:
            fast -= 0.22
        if s.force_fast:
            fast += 0.35

        normal = 0.38
        normal += s.user_directness * 0.18
        normal += min(s.task_pressure(), 0.60) * 0.22
        normal += min(s.salience_priority, 0.70) * 0.16
        normal += min(s.ambiguity, 0.55) * 0.12
        normal += (1.0 - abs(s.signal_density - 0.45)) * 0.10
        normal -= max(0.0, s.architecture_depth - 0.55) * 0.22
        normal -= max(0.0, s.correction_pressure - 0.60) * 0.22
        normal -= max(0.0, s.relational_rupture - 0.55) * 0.18
        normal -= max(0.0, s.reflection_pressure() - 0.62) * 0.25

        deep = 0.16
        deep += s.technical_depth * 0.30
        deep += s.architecture_depth * 0.42
        deep += s.correction_pressure * 0.30
        deep += s.relational_rupture * 0.28
        deep += s.memory_conflict * 0.32
        deep += s.contradiction_pressure * 0.25
        deep += s.context_pressure * 0.20
        deep += s.risk_pressure * 0.18
        deep += s.worldview_pressure * 0.24
        deep += s.has_high_value_decision * 0.28 if isinstance(s.has_high_value_decision, float) else (0.28 if s.has_high_value_decision else 0.0)
        if s.force_deep:
            deep += 0.36
        if s.channel == "chat" and (s.has_technical_request or s.has_architecture_request):
            deep += 0.10

        reflection = 0.08
        reflection += s.reflection_debt * 0.44
        reflection += s.session_closing_pressure * 0.48
        reflection += s.shutdown_pressure * 0.80
        reflection += s.affective_residue * 0.22
        reflection += s.correction_pressure * 0.16
        reflection += s.contradiction_pressure * 0.18
        reflection += s.memory_conflict * 0.22
        reflection += max(0.0, s.idle_pressure - 0.60) * 0.18
        if s.force_reflection:
            reflection += 0.45
        if s.channel == "reflection":
            reflection += 0.36
        if s.channel in {"chat", "force_speak"} and not s.session_closing_pressure:
            reflection -= 0.20

        # Quán tính rất nhẹ, tránh mode flip vô nghĩa. Không khóa mode.
        if previous_decisions:
            last_mode = self._last_previous_mode(previous_decisions)
            if last_mode:
                if last_mode == "fast":
                    fast += 0.03
                elif last_mode == "normal":
                    normal += 0.03
                elif last_mode == "deep":
                    deep += 0.03
                elif last_mode == "reflection":
                    reflection += 0.02

        raw_reasons: list[str] = []
        if s.low_stakes_ambient > 0.55:
            raw_reasons.append("fast:low_stakes_ambient")
        if s.technical_depth > 0.55:
            raw_reasons.append("deep:technical_depth")
        if s.architecture_depth > 0.55:
            raw_reasons.append("deep:architecture_depth")
        if s.correction_pressure > 0.55:
            raw_reasons.append("deep_or_reflection:correction")
        if s.reflection_pressure() > 0.60:
            raw_reasons.append("reflection:reflection_pressure")
        if s.context_pressure > 0.70:
            raw_reasons.append("deep:context_flood_selection")

        ranked = sorted([fast, normal, deep, reflection], reverse=True)
        winning = ranked[0]
        margin = ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0]
        return BudgetScoreBreakdown(
            fast=clamp(fast, 0.0, 1.2),
            normal=clamp(normal, 0.0, 1.2),
            deep=clamp(deep, 0.0, 1.2),
            reflection=clamp(reflection, 0.0, 1.2),
            winning_score=clamp(winning, 0.0, 1.2),
            margin=clamp(margin, 0.0, 1.2),
            raw_reasons=raw_reasons,
        )

    def _choose_mode_from_scores(self, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown) -> BudgetMode:
        ranked = scores.as_ranked()
        winner = ranked[0][0]
        # Nếu score thấp nhưng không có low-stakes rõ, normal là nền an toàn.
        if scores.winning_score < 0.38 and snapshot.low_stakes_ambient < 0.50:
            return "normal"
        return winner  # type: ignore[return-value]

    def _apply_hard_floors(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot) -> BudgetMode:
        """Áp sàn mode để tránh fast path xử lý việc nghiêm túc.

        Sàn này không phải rule-based cứng vô hồn. Nó là chốt an toàn kiến trúc.
        """

        if snapshot.channel == "chat" and self._mode_rank(mode) < self._mode_rank(self.config.chat_minimum_mode):
            mode = self.config.chat_minimum_mode
        if snapshot.channel == "force_speak" and self._mode_rank(mode) < self._mode_rank(self.config.force_speak_minimum_mode):
            mode = self.config.force_speak_minimum_mode

        semantic_floor = self.config.hard_floor_semantic_support_threshold
        if (
            snapshot.architecture_depth >= self.config.architecture_depth_threshold
            and not snapshot.architecture_keyword_only
            and snapshot.architecture_semantic_support >= semantic_floor
        ):
            mode = self._max_mode(mode, "deep")
        elif (
            snapshot.technical_depth >= self.config.technical_depth_threshold
            and snapshot.has_user_text
            and not snapshot.technical_keyword_only
            and snapshot.technical_semantic_support >= semantic_floor
        ):
            mode = self._max_mode(mode, "deep")

        if (
            snapshot.correction_pressure >= self.config.strong_correction_threshold
            and not snapshot.correction_keyword_only
            and snapshot.correction_semantic_support >= semantic_floor
        ):
            mode = self._max_mode(mode, "deep")
        if snapshot.relational_rupture >= self.config.relational_rupture_threshold:
            mode = self._max_mode(mode, "deep")
        if snapshot.memory_conflict >= self.config.memory_conflict_threshold:
            mode = self._max_mode(mode, "deep")
        if (
            snapshot.risk_pressure >= self.config.high_risk_threshold
            and not snapshot.risk_keyword_only
            and snapshot.risk_semantic_support >= semantic_floor
        ):
            mode = self._max_mode(mode, "deep")
        if snapshot.context_pressure >= self.config.context_flood_threshold and snapshot.has_user_text:
            mode = self._max_mode(mode, "deep")
        if snapshot.has_high_value_decision:
            mode = self._max_mode(mode, "deep")
        return mode

    def _apply_hard_overrides(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot) -> BudgetMode:
        if snapshot.shutdown_pressure >= 0.95:
            return "reflection"
        if snapshot.force_reflection:
            return "reflection"
        if snapshot.channel == "reflection":
            return "reflection"
        if snapshot.session_closing_pressure >= 0.82 and snapshot.reflection_debt >= 0.50:
            return "reflection"
        if snapshot.reflection_debt >= self.config.reflection_debt_threshold and not snapshot.has_user_text:
            return "reflection"
        if snapshot.force_deep:
            return self._max_mode(mode, "deep")
        if snapshot.force_fast and snapshot.low_stakes_ambient > 0.65 and not snapshot.has_user_text:
            return "fast"
        return mode

    # ------------------------------------------------------------------
    # Reasons / confidence / urgency
    # ------------------------------------------------------------------

    def _derive_reasons(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown) -> tuple[list[str], list[str], list[str]]:
        escalation: list[str] = []
        downgrade: list[str] = []
        warnings: list[str] = []

        if snapshot.force_reflection:
            escalation.append("explicit_reflection_request")
        if snapshot.shutdown_pressure >= 0.95 or snapshot.session_closing_pressure >= 0.82:
            escalation.append("shutdown_or_session_end")
        if snapshot.reflection_debt >= self.config.reflection_debt_threshold:
            escalation.append("idle_reflection_window" if snapshot.idle_pressure > 0.60 else "repeated_contradiction")
        if snapshot.correction_pressure >= self.config.strong_correction_threshold:
            escalation.append("major_user_correction")
        if snapshot.contradiction_pressure >= 0.58:
            escalation.append("repeated_contradiction")
        if snapshot.affective_residue >= 0.70:
            escalation.append("high_affective_residue")
        if snapshot.technical_depth >= self.config.technical_depth_threshold or snapshot.architecture_depth >= self.config.architecture_depth_threshold:
            escalation.append("code_debugging_or_architecture")
        if snapshot.has_high_value_decision:
            escalation.append("high_value_decision")
        if snapshot.memory_conflict >= self.config.memory_conflict_threshold:
            escalation.append("memory_contradiction")
        if snapshot.relational_rupture >= self.config.relational_rupture_threshold:
            escalation.append("relational_rupture")
        if snapshot.risk_pressure >= self.config.high_risk_threshold or snapshot.privacy_pressure >= self.config.privacy_pressure_high:
            escalation.append("high_risk_or_permission_pressure")
        if snapshot.context_pressure >= self.config.context_flood_threshold:
            escalation.append("context_flood_requires_deep_selection")

        if snapshot.signal_density <= self.config.low_signal_density_threshold:
            downgrade.append("low_signal_density")
        if snapshot.low_stakes_ambient > 0.62:
            downgrade.append("ambient_idle")
        if snapshot.task_pressure() <= self.config.low_task_pressure_threshold and snapshot.risk_pressure < 0.25:
            downgrade.append("no_risk_no_task")
        if snapshot.speech_need < 0.25 and snapshot.channel == "autonomous":
            downgrade.append("speech_not_needed")
        if snapshot.force_fast:
            downgrade.append("strict_fast_path_hint")
        if snapshot.context_pressure >= self.config.token_pressure_high:
            downgrade.append("token_pressure")
        if snapshot.privacy_pressure >= self.config.privacy_pressure_high:
            downgrade.append("privacy_pressure")

        if scores.margin < self.config.weak_margin:
            warnings.append("budget_mode_margin_weak")
        if mode == "fast" and snapshot.context_pressure > 0.65:
            warnings.append("fast_mode_with_high_context_pressure")
        if mode == "fast" and snapshot.has_user_text:
            warnings.append("fast_mode_with_user_text")
        if mode == "reflection" and snapshot.has_user_text and snapshot.channel == "chat":
            warnings.append("reflection_selected_during_chat")
        if snapshot.privacy_pressure > 0.70 and mode in {"normal", "deep"}:
            warnings.append("privacy_pressure_requires_surface_filtering")

        return unique_preserve_order(escalation), unique_preserve_order(downgrade), unique_preserve_order(warnings)

    def _estimate_confidence(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown) -> float:
        confidence = 0.54 + min(0.28, scores.margin * 0.55)
        if scores.margin < self.config.weak_margin:
            confidence -= 0.10
        if snapshot.force_reflection or snapshot.force_deep:
            confidence += 0.08
        if mode == "deep" and (snapshot.architecture_depth > 0.55 or snapshot.technical_depth > 0.62):
            confidence += 0.08
        if mode == "reflection" and snapshot.reflection_pressure() > 0.68:
            confidence += 0.10
        if mode == "fast" and snapshot.low_stakes_ambient > 0.65:
            confidence += 0.08
        if snapshot.uncertainty > 0.70:
            confidence -= 0.06
        return clamp(confidence, 0.35, 0.96)

    def _estimate_urgency(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot) -> BudgetUrgency:
        pressure = max(snapshot.risk_pressure, snapshot.salience_priority, snapshot.correction_pressure, snapshot.relational_rupture)
        if snapshot.shutdown_pressure > 0.90:
            return "medium"
        if mode == "reflection":
            if snapshot.reflection_debt > 0.80 or snapshot.session_closing_pressure > 0.85:
                return "high"
            return "medium"
        if pressure >= 0.82:
            return "critical"
        if pressure >= 0.64 or mode == "deep":
            return "high"
        if pressure >= 0.38 or mode == "normal":
            return "medium"
        return "low"

    def _build_reason(
        self,
        mode: BudgetMode,
        snapshot: BudgetSignalSnapshot,
        escalation: Sequence[str],
        downgrade: Sequence[str],
        scores: BudgetScoreBreakdown,
    ) -> str:
        top = scores.as_ranked()[0]
        parts = [f"selected_{mode}"]
        if escalation:
            parts.append("escalation=" + ",".join(escalation[:4]))
        if downgrade and mode == "fast":
            parts.append("downgrade=" + ",".join(downgrade[:3]))
        parts.append(f"top_score={top[0]}:{top[1]:.2f}")
        parts.append(
            "pressures="
            f"salience:{snapshot.salience_priority:.2f},"
            f"technical:{snapshot.technical_depth:.2f},"
            f"architecture:{snapshot.architecture_depth:.2f},"
            f"correction:{snapshot.correction_pressure:.2f},"
            f"risk:{snapshot.risk_pressure:.2f},"
            f"reflection:{snapshot.reflection_pressure():.2f}"
        )
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Plan builder
    # ------------------------------------------------------------------

    def _build_plan(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot) -> BudgetPlan:
        profile = self._profiles[mode]
        steps = self._build_steps(mode, snapshot, profile)
        required = [step.name for step in steps if step.run and not step.optional]
        skipped = [step.name for step in steps if not step.run]

        max_prompt_tokens = profile.max_prompt_tokens
        max_evidence_items = profile.max_evidence_items
        max_working_memory_slots = profile.max_working_memory_slots
        max_workspace_items = profile.max_workspace_items
        max_memory_items = profile.max_memory_items

        prompt_notes: list[str] = []
        runtime_notes: list[str] = []

        if snapshot.context_pressure >= self.config.token_pressure_high:
            # Context pressure cao không có nghĩa hạ mode; thường là cần deep selection.
            # Nhưng prompt vẫn phải bóp lại, nếu không LLM sẽ được cho ăn cả bãi rác có nhãn.
            max_prompt_tokens = int(max_prompt_tokens * 0.82)
            max_evidence_items = max(4, int(max_evidence_items * 0.75))
            max_workspace_items = max(4, int(max_workspace_items * 0.80))
            prompt_notes.append("context_pressure_high:compress_prompt_surface")

        if snapshot.privacy_pressure >= self.config.privacy_pressure_high:
            max_memory_items = min(max_memory_items, 2)
            max_evidence_items = max(4, int(max_evidence_items * 0.65))
            prompt_notes.append("privacy_pressure_high:avoid_raw_private_surface")

        if mode == "fast":
            prompt_notes.append("fast_path:selected_context_only;avoid_deep_interpretation")
            runtime_notes.append("skip heavy ToM/belief/simulation unless explicit override")
        elif mode == "normal":
            prompt_notes.append("normal_path:workspace_context_plus_small_memory")
            runtime_notes.append("run ordinary chat/autonomous cognition without heavy belief update")
        elif mode == "deep":
            prompt_notes.append("deep_path:allow_full_reasoning_but_keep_evidence_bounded")
            runtime_notes.append("run full understanding/ToM/arbitration when value justifies cost")
        elif mode == "reflection":
            prompt_notes.append("reflection_path:no_public_wording_by_default")
            runtime_notes.append("prefer outcome/self_observation/repair/memory_decay over speech")

        return BudgetPlan(
            mode=mode,
            profile=profile,
            steps=steps,
            required_steps=required,
            skipped_steps=skipped,
            max_prompt_tokens=max_prompt_tokens,
            max_evidence_items=max_evidence_items,
            max_working_memory_slots=max_working_memory_slots,
            max_workspace_items=max_workspace_items,
            max_memory_items=max_memory_items,
            compression=profile.compression,
            prompt_policy_notes=prompt_notes,
            runtime_notes=runtime_notes,
        )

    def _build_steps(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, profile: BudgetModeProfile) -> list[PipelineStepDecision]:
        """Tạo danh sách module nên chạy.

        Bản này có chủ ý hơi dư chi tiết, vì runtime cần nhìn được vì sao một module bị skip.
        """

        steps: list[PipelineStepDecision] = []

        def add(name: str, run: bool, reason: str, *, priority: float = 0.0, optional: bool = False, max_items: Optional[int] = None, notes: Optional[list[str]] = None) -> None:
            steps.append(
                PipelineStepDecision(
                    name=name,
                    run=bool(run),
                    reason=reason,
                    priority=clamp01(priority),
                    optional=optional,
                    max_items=max_items,
                    notes=notes or [],
                )
            )

        # Phase nền luôn chạy.
        add("raw_signal_collector", True, "raw world must be collected before inference", priority=1.0)
        add("evidence_normalizer", True, "evidence before inference", priority=1.0, max_items=profile.max_evidence_items)
        add("attention_salience", True, "budget depends on salience selection", priority=0.96)
        add("cognitive_budget", True, "current module", priority=1.0)

        # Low-cost perception/regulation.
        add("temporal_perception", mode != "fast" or snapshot.idle_pressure > 0.40, "time matters unless true fast ambient", priority=snapshot.idle_pressure)
        add("spatial_proprioception", mode != "reflection" and (mode != "fast" or snapshot.body_need > 0.35), "body context only when public/body action may matter", priority=snapshot.body_need)
        add("homeostasis", True, "speech/action cost must always be known", priority=max(snapshot.homeostasis_load, 0.55))
        add("affective_substrate", True, "affect pressure regulates speech, not poetic decoration", priority=max(snapshot.affective_residue, 0.48))

        # Context compression.
        add("working_memory", True, "all downstream should read bottlenecked context", priority=max(snapshot.context_pressure, 0.75), max_items=profile.max_working_memory_slots)
        add("global_workspace", True, "broadcast selected context to downstream", priority=max(snapshot.salience_priority, 0.72), max_items=profile.max_workspace_items)

        # Understanding layers.
        add("world_scene_builder", mode in {"normal", "deep"}, "scene needed for normal/deep interpretation", priority=max(snapshot.salience_priority, snapshot.technical_depth), optional=(mode == "normal"))
        add("world_interpreter", mode in {"normal", "deep"}, "interpret selected scene, not raw world", priority=max(snapshot.ambiguity, snapshot.technical_depth), optional=(mode == "normal"))
        add("sociocultural_context", mode in {"normal", "deep"} or snapshot.relational_rupture > 0.40, "Vietnamese/dev/social norm can change meaning", priority=max(snapshot.relational_rupture, snapshot.ambiguity), optional=(mode != "deep"))
        add("meaning_hypothesis", mode in {"normal", "deep"}, "meaning ranking required before ToM/speech", priority=max(snapshot.user_directness, snapshot.ambiguity, snapshot.technical_depth))
        add("theory_of_mind", mode == "deep" or (mode == "normal" and snapshot.ambiguity > 0.45), "ToM deep only when ambiguity/rupture justifies it", priority=max(snapshot.ambiguity, snapshot.relational_rupture), optional=(mode != "deep"))

        # Inquiry / knowledge / belief.
        add("epistemic_drive", mode == "deep" or snapshot.worldview_pressure > 0.50, "curiosity must be gated by privacy and value", priority=max(snapshot.worldview_pressure, snapshot.uncertainty), optional=True)
        add("inquiry_planner", mode == "deep" and snapshot.uncertainty > 0.35, "ask/search/observe only if knowledge gap matters", priority=snapshot.uncertainty, optional=True)
        add("knowledge_acquisition", mode == "deep" and snapshot.worldview_pressure > 0.55, "external/memory acquisition is expensive", priority=snapshot.worldview_pressure, optional=True)
        add("belief_core", profile.allow_belief_update and (snapshot.worldview_pressure > 0.35 or snapshot.memory_conflict > 0.35), "belief update only for grounded high-value frames", priority=max(snapshot.worldview_pressure, snapshot.memory_conflict), optional=True)
        add("memory_cognition", profile.allow_memory_cognition, "memory is cognition, but budgeted", priority=max(snapshot.goal_pressure, snapshot.memory_conflict, snapshot.correction_pressure), optional=(mode != "deep"), max_items=profile.max_memory_items)

        # Values / decisions.
        add("value_resolution", mode == "deep" or snapshot.risk_pressure > 0.55 or snapshot.privacy_pressure > 0.55, "resolve value conflict when risk/privacy/relationship matters", priority=max(snapshot.risk_pressure, snapshot.privacy_pressure, snapshot.relational_rupture), optional=(mode != "deep"))
        add("predictive_simulation", profile.allow_predictive_simulation, "simulate action outcomes only when cost is justified", priority=max(snapshot.risk_pressure, snapshot.relational_rupture, snapshot.has_high_value_decision and 0.70 or 0.0), optional=True, max_items=profile.max_simulations)
        add("cognitive_arbitration", mode in {"normal", "deep"} or snapshot.risk_pressure > 0.45, "speech/silence/action competition needs arbitration", priority=max(snapshot.speech_need, snapshot.risk_pressure, snapshot.goal_pressure))
        add("agency_engine", mode in {"normal", "deep"} or snapshot.speech_need > 0.45, "commit or wait; do not drift", priority=max(snapshot.speech_need, snapshot.goal_pressure))
        add("relational_dynamics", mode in {"normal", "deep"} or snapshot.relational_rupture > 0.30, "relationship pressure changes surface permission", priority=snapshot.relational_rupture, optional=(mode == "fast"))
        add("permission_engine", True, "permission gates action space; it must not rewrite output", priority=max(snapshot.privacy_pressure, snapshot.risk_pressure, 0.60))
        add("calculated_noise", mode in {"normal", "deep"} and snapshot.risk_pressure < 0.60, "bounded noise only when it cannot harm truth", priority=0.25, optional=True)

        # Speech/body/action.
        add("speech_opportunity", mode != "reflection", "decide whether speech is worth interrupting", priority=snapshot.speech_need)
        add("speech_core", mode != "reflection" and (mode != "fast" or snapshot.speech_need > 0.45), "plan speech only if speech may happen", priority=snapshot.speech_need)
        add("body_action_planner", profile.allow_body_planning and snapshot.body_need > 0.20, "body action must pass budget and modality", priority=snapshot.body_need, optional=True)
        add("modality_sync", mode != "reflection", "speech/body/system must not contradict each other", priority=max(snapshot.body_need, snapshot.speech_need))
        add("llm_wording", profile.allow_llm_wording and snapshot.speech_need > (0.20 if snapshot.channel in {"chat", "force_speak"} else 0.45), "word only after selected context and speech plan", priority=snapshot.speech_need, optional=(snapshot.channel == "autonomous"))
        add("grounding_guard", mode != "reflection", "guard regulates without flattening", priority=max(snapshot.risk_pressure, snapshot.uncertainty, 0.55))

        # Execution/outcome/reflection.
        add("execution_layer", mode != "reflection", "execute selected public/system/body action", priority=max(snapshot.speech_need, snapshot.body_need))
        add("outcome_observer", mode in {"normal", "deep", "reflection"}, "observe aftermath for learning", priority=max(snapshot.correction_pressure, snapshot.relational_rupture, 0.35), optional=(mode == "normal"))
        add("self_observation", mode in {"deep", "reflection"}, "needed after overread/correction/major action", priority=max(snapshot.reflection_debt, snapshot.correction_pressure), optional=(mode == "deep"))
        add("repair_memory", mode == "reflection" or snapshot.correction_pressure > 0.55 or snapshot.relational_rupture > 0.55, "repair memory prevents repeated failure", priority=max(snapshot.correction_pressure, snapshot.relational_rupture), optional=(mode != "reflection"))
        add("state_committer", True, "state changes must go through commit protocol", priority=0.85)
        add("dream_scheduler", profile.allow_dream_schedule and (snapshot.reflection_debt > 0.50 or mode in {"deep", "reflection"}), "schedule consolidation only when there is actual residue/debt", priority=snapshot.reflection_debt, optional=True)

        return steps

    # ------------------------------------------------------------------
    # Attach to frame
    # ------------------------------------------------------------------

    def _attach_decision(self, frame: Any, decision: BudgetDecision) -> None:
        if frame is None:
            return

        if self.config.update_frame_budget_mode:
            try:
                setattr(frame, "budget_mode", decision.mode)
            except Exception:
                if isinstance(frame, dict):
                    frame["budget_mode"] = decision.mode

        if self.config.attach_decision_to_frame:
            try:
                setattr(frame, "budget_decision", decision)
            except Exception:
                if isinstance(frame, dict):
                    frame["budget_decision"] = decision

        if self.config.attach_report_to_frame:
            report = ModuleReport(
                module_name=self.MODULE_NAME,
                confidence=decision.confidence,
                pressure=decision.snapshot.pressure_max(),
                evidence_used=self._extract_evidence_ids(frame),
                result=decision,
                warnings=list(decision.warnings),
                debug={
                    "mode": decision.mode,
                    "urgency": decision.urgency,
                    "reason": decision.reason,
                    "scores": decision.scores.to_dict(),
                    "plan_summary": {
                        "required": decision.plan.required_steps,
                        "skipped": decision.plan.skipped_steps,
                        "max_prompt_tokens": decision.plan.max_prompt_tokens,
                    },
                },
            )
            self._add_report_to_frame(frame, report)

        # Reflection mode thường cần commit request nhẹ để scheduler/consolidation biết có nợ xử lý.
        if decision.mode == "reflection":
            self._add_reflection_commit_request(frame, decision)

    def _add_report_to_frame(self, frame: Any, report: ModuleReport) -> None:
        add_report = getattr(frame, "add_report", None)
        if callable(add_report):
            try:
                add_report(report)
                return
            except TypeError:
                try:
                    add_report(self.MODULE_NAME, report)
                    return
                except Exception:
                    pass
            except Exception:
                pass

        reports = safe_get(frame, "module_reports", None)
        if isinstance(reports, dict):
            reports[self.MODULE_NAME] = report
            return
        if isinstance(reports, list):
            reports.append(report)
            return
        try:
            setattr(frame, "module_reports", {self.MODULE_NAME: report})
        except Exception:
            if isinstance(frame, dict):
                frame["module_reports"] = {self.MODULE_NAME: report}

    def _add_reflection_commit_request(self, frame: Any, decision: BudgetDecision) -> None:
        try:
            request = StateCommitRequest(
                target="repair_memory" if decision.snapshot.correction_pressure > 0.55 else "self_continuity",
                content=f"CognitiveBudget selected reflection: {decision.reason}",
                confidence=decision.confidence,
                evidence_ids=self._extract_evidence_ids(frame),
                permission_required=False,
                storage_permission=True,
                decay_policy="session_only" if decision.snapshot.shutdown_pressure < 0.90 else "normal",
                reason="reflection_budget_selected",
            )
        except Exception:
            return

        add_commit = getattr(frame, "add_commit_request", None)
        if callable(add_commit):
            try:
                add_commit(request)
                return
            except Exception:
                pass
        commit_requests = safe_get(frame, "commit_requests", None)
        if isinstance(commit_requests, list):
            commit_requests.append(request)
            return
        try:
            setattr(frame, "commit_requests", [request])
        except Exception:
            if isinstance(frame, dict):
                frame["commit_requests"] = [request]

    def _extract_evidence_ids(self, frame: Any) -> list[str]:
        ids: list[str] = []
        for ev in as_list(safe_get(frame, "evidence", [])):
            ev_id = str(safe_get(ev, "id", "") or "")
            if ev_id:
                ids.append(ev_id)
        return ids[:24]

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _normalize_channel(self, channel: str) -> str:
        channel = (channel or "unknown").strip().lower()
        if channel in {"autonomous", "chat", "force_speak", "session_start", "reflection", "shutdown", "system", "test"}:
            return channel
        return "unknown"

    def _last_previous_mode(self, previous_decisions: Sequence[BudgetDecision | Mapping[str, Any]]) -> Optional[str]:
        if not previous_decisions:
            return None
        last = previous_decisions[-1]
        if isinstance(last, Mapping):
            mode = last.get("mode")
        else:
            mode = getattr(last, "mode", None)
        if mode in {"fast", "normal", "deep", "reflection"}:
            return str(mode)
        return None

    def _mode_rank(self, mode: str) -> int:
        order = {"fast": 0, "normal": 1, "deep": 2, "reflection": 2}
        return order.get(mode, 1)

    def _max_mode(self, current: BudgetMode, floor: BudgetMode) -> BudgetMode:
        if self._mode_rank(current) >= self._mode_rank(floor):
            return current
        return floor


# =============================================================================
# 7. Convenience function cho runtime cũ
# =============================================================================


def choose_cognitive_budget(frame: Any, **kwargs: Any) -> BudgetDecision:
    """Hàm tiện ích nếu không muốn tự giữ engine instance."""

    return CognitiveBudgetEngine().choose(frame, **kwargs)


__all__ = [
    "BudgetMode",
    "BudgetChannel",
    "BudgetUrgency",
    "BudgetCompression",
    "BudgetModeProfile",
    "BudgetSignalSnapshot",
    "BudgetScoreBreakdown",
    "PipelineStepDecision",
    "BudgetPlan",
    "BudgetDecision",
    "CognitiveBudgetConfig",
    "CognitiveBudgetEngine",
    "choose_cognitive_budget",
]
