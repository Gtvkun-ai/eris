from __future__ import annotations

"""
working_memory.py - cổ chai nhận thức / bộ chọn context sống cho ERIS
====================================================================

Mục tiêu của file này:
    Biến đống evidence, salience, memory recall, affect, relation và action constraint
    thành một WorkingMemoryFrame nhỏ, đủ dùng, có kiểm soát.

Tại sao cần tầng này:
    ERIS không được nhét mọi thứ vào prompt.
    ERIS không được kéo memory chỉ vì nó nghe có vẻ sâu.
    ERIS không được biến một tín hiệu nhỏ thành continuity / symbolism / emotional residue
    nếu không có evidence thật.

Working Memory đúng nghĩa là "cổ chai":
    - chỉ giữ 3-7 slot đang cần trong frame hiện tại.
    - đẩy phần còn lại vào suppressed_items.
    - ghi rõ recall_competition để debug vì sao memory X không được lên prompt.
    - giữ dominant_thread để GlobalWorkspace biết thread chính.
    - tính context_pressure để các tầng sau biết prompt đang nặng hay nhẹ.

Nguyên tắc kiến trúc:
    Module này CHỈ đọc CognitiveFrame.
    Module này KHÔNG gọi trực tiếp memory store, attention engine, LLM, hoặc module khác.
    Nếu cần dữ liệu, nó phải nằm sẵn trong frame: frame.evidence, frame.salience,
    frame.memory_packet, frame.relation, frame.affect, frame.homeostasis, v.v.

Nếu module khác tự gọi memory.py rồi tự chọn context:
    xin chúc mừng, Ngài vừa phát minh lại spaghetti telepathy với kiểu dữ liệu mới.
"""

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

try:
    # Dùng khi file được đặt trong package cortex/core có cognitive_frame.py.
    from .cognitive_frame import ModuleReport  # type: ignore
except Exception:  # pragma: no cover - fallback để file chạy độc lập khi test rời.
    @dataclass(slots=True)
    class ModuleReport:  # type: ignore[no-redef]
        """Fallback tối thiểu để không ép repo phải nối hết ngay lập tức."""

        module_name: str
        confidence: float
        pressure: float
        evidence_used: list[str]
        result: Any
        warnings: list[str] = field(default_factory=list)
        debug: dict[str, Any] = field(default_factory=dict)


WorkingMemorySlotKind = Literal[
    "current_user_request",
    "active_technical_goal",
    "immediate_evidence",
    "relevant_memory",
    "relational_state",
    "affect_homeostasis",
    "action_constraint",
    "risk_or_repair",
    "temporal_context",
    "spatial_context",
    "body_state",
    "open_question",
    "misc",
]

SuppressionReason = Literal[
    "duplicate",
    "low_priority",
    "low_confidence",
    "expired",
    "privacy_blocked",
    "token_budget",
    "slot_budget",
    "memory_quota",
    "symbolic_drift_risk",
    "overassociation_risk",
    "poetic_overflow_risk",
    "weak_memory_echo",
    "irrelevant_recall",
    "replaced_by_stronger_slot",
    "unsupported_inference",
]

BudgetMode = Literal["fast", "normal", "deep", "reflection"]


# ---------------------------------------------------------------------------
# Helper nền: nhỏ thôi, vì lôi thư viện to vào file lõi là một nghi thức gọi bug.
# ---------------------------------------------------------------------------


def clamp01(value: Any, default: float = 0.0) -> float:
    """Ép một giá trị về khoảng 0..1.

    Các module khác thường sẽ trả float hơi bẩn: None, chuỗi số, NaN,
    hoặc object lạ. Working memory không được chết vì một field xấu.
    """

    try:
        number = float(value)
    except Exception:
        number = default
    if math.isnan(number) or math.isinf(number):
        number = default
    return max(0.0, min(1.0, number))


def now_ts() -> float:
    return time.time()


def stable_id(prefix: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """Đọc field từ dataclass/object/dict một cách khoan dung.

    File này được thiết kế để gắn sau, nên không ép mọi object trong repo
    phải cùng một class ngay lập tức.
    """

    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def safe_iter(value: Any) -> list[Any]:
    """Biến tuple/list/set/None/object đơn thành list."""

    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def normalize_text(text: Any) -> str:
    """Chuẩn hóa text nhẹ để so trùng / phát hiện echo.

    Không bỏ dấu tiếng Việt, vì mất dấu có thể làm câu technical và câu đùa
    dính vào nhau như hai module thiếu boundary.
    """

    raw = str(text or "").strip().lower()
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"[`*_#>\[\](){}]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def estimate_tokens(text: Any) -> int:
    """Ước lượng token thô.

    Không cần tokenizer thật ở tầng này. Working memory chỉ cần budget tương đối
    để không biến prompt thành kho rác văn học.
    """

    s = str(text or "")
    if not s:
        return 0
    words = re.findall(r"\w+|[^\w\s]", s, flags=re.UNICODE)
    return max(1, int(len(words) * 1.20))


def truncate_text(text: Any, max_chars: int) -> str:
    s = str(text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def unique_preserve_order(items: Iterable[Any], limit: Optional[int] = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if limit is not None and len(out) >= limit:
            break
    return out


SYMBOLIC_DRIFT_TERMS = {
    "continuity",
    "dư âm",
    "residue",
    "vết nứt",
    "cô độc",
    "bản ngã",
    "ý nghĩa sâu",
    "symbolic",
    "ẩn ý",
    "không tan rã",
    "tồn tại",
    "attachment",
}

TECHNICAL_TERMS = {
    "code",
    "debug",
    "bug",
    "error",
    "exception",
    "traceback",
    "module",
    "class",
    "dataclass",
    "pipeline",
    "runtime",
    "architecture",
    "file",
    "python",
    "c#",
    "godot",
    "api",
}

AFFECT_TERMS = {
    "sad",
    "angry",
    "buồn",
    "giận",
    "stress",
    "tổn thương",
    "cô đơn",
    "frustrated",
    "xúc động",
    "lo lắng",
}


# ---------------------------------------------------------------------------
# Data contract theo PDF, có mở rộng để dùng thật trong repo.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkingMemorySlot:
    """Một slot đang hoạt động trong cổ chai nhận thức.

    Field lõi theo PDF:
        name:
            Tên slot. Ví dụ: current_user_request, immediate_evidence.
        content:
            Nội dung đã nén. Không đưa nguyên object dài vào đây.
        priority:
            Mức ưu tiên sau scoring, 0..1.
        source_ids:
            ID evidence/signal/report đã tạo ra slot.
        decay_after_seconds:
            Sau khoảng này slot nên bị xem là cũ nếu frame sau còn giữ lại.

    Field mở rộng:
        kind:
            Nhóm slot chuẩn để downstream biết đây là request, evidence, memory, affect...
        confidence:
            Slot đáng tin đến mức nào.
        token_cost:
            Chi phí prompt ước lượng.
        permission_to_surface:
            Có được phép đưa vào prompt public/surface không.
        symbolic_drift_risk:
            Nguy cơ slot kéo ERIS sang fake depth / poetic overflow.
    """

    name: str
    content: str
    priority: float
    source_ids: list[str]
    decay_after_seconds: float

    kind: WorkingMemorySlotKind = "misc"
    confidence: float = 1.0
    created_at: float = field(default_factory=now_ts)
    token_cost: int = 0
    privacy_level: str = "normal"
    permission_to_surface: bool = True
    symbolic_drift_risk: float = 0.0
    overassociation_risk: float = 0.0
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.priority = clamp01(self.priority)
        self.confidence = clamp01(self.confidence, 1.0)
        self.symbolic_drift_risk = clamp01(self.symbolic_drift_risk)
        self.overassociation_risk = clamp01(self.overassociation_risk)
        self.source_ids = unique_preserve_order(self.source_ids, limit=16)
        self.tags = unique_preserve_order(self.tags, limit=16)
        self.content = truncate_text(self.content, 900)
        if self.token_cost <= 0:
            self.token_cost = estimate_tokens(self.content)

    @property
    def is_memory(self) -> bool:
        return self.kind == "relevant_memory"

    @property
    def is_symbolic_heavy(self) -> bool:
        text = normalize_text(self.content)
        return any(term in text for term in SYMBOLIC_DRIFT_TERMS)

    def expired(self, timestamp: Optional[float] = None) -> bool:
        ts = now_ts() if timestamp is None else timestamp
        return (ts - self.created_at) > self.decay_after_seconds

    def to_prompt_line(self) -> str:
        """Dòng ngắn để prompt builder có thể dùng.

        Không nhét metadata vào prompt. Metadata dành cho debug. Prompt không phải
        bãi rác có định dạng JSON.
        """

        return f"- [{self.kind}] {self.content}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "content": self.content,
            "priority": round(self.priority, 4),
            "confidence": round(self.confidence, 4),
            "source_ids": list(self.source_ids),
            "decay_after_seconds": self.decay_after_seconds,
            "created_at": self.created_at,
            "token_cost": self.token_cost,
            "privacy_level": self.privacy_level,
            "permission_to_surface": self.permission_to_surface,
            "symbolic_drift_risk": round(self.symbolic_drift_risk, 4),
            "overassociation_risk": round(self.overassociation_risk, 4),
            "reason": self.reason,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SuppressedMemoryItem:
    """Một candidate bị loại khỏi working memory.

    Đây là thứ giúp debug câu hỏi: "vì sao memory này không được kéo lên?"
    Không có nó, Ngài sẽ nhìn output ngu rồi lục log như khảo cổ một nền văn minh lỗi.
    """

    item_id: str
    kind: str
    content: str
    reason: SuppressionReason
    score: float
    confidence: float
    source_ids: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_debug_line(self) -> str:
        return f"{self.kind}:{self.reason}:{self.score:.2f}:{truncate_text(self.content, 120)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "content": self.content,
            "reason": self.reason,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "source_ids": list(self.source_ids),
            "debug": dict(self.debug),
        }


@dataclass(slots=True)
class WorkingMemoryFrame:
    """Kết quả chính của module Working Memory.

    Field lõi theo PDF:
        active_slots:
            3-7 slot đang hoạt động.
        suppressed_items:
            Những item bị loại để chống context flood.
        dominant_thread:
            Thread chính mà GlobalWorkspace nên giữ.
        context_pressure:
            Áp lực context/prompt, 0..1.
        recall_competition:
            Các memory/context đã cạnh tranh nhưng không thắng.

    Field mở rộng:
        workspace_candidates:
            Slot đã đủ sạch để GlobalWorkspace chọn tiếp.
        prompt_context:
            Prompt context nén, có thể dùng trực tiếp nếu cần.
        anti_drift_notes:
            Ghi chú chống symbolic drift / fake depth.
    """

    active_slots: list[WorkingMemorySlot]
    suppressed_items: list[str]
    dominant_thread: Optional[str]
    context_pressure: float
    recall_competition: list[str]

    workspace_candidates: list[WorkingMemorySlot] = field(default_factory=list)
    token_budget: int = 900
    used_tokens: int = 0
    slot_budget: int = 7
    overflow: bool = False
    anti_drift_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.context_pressure = clamp01(self.context_pressure)
        self.suppressed_items = unique_preserve_order(self.suppressed_items, limit=80)
        self.recall_competition = unique_preserve_order(self.recall_competition, limit=40)
        self.anti_drift_notes = unique_preserve_order(self.anti_drift_notes, limit=32)
        self.warnings = unique_preserve_order(self.warnings, limit=32)
        if not self.workspace_candidates:
            self.workspace_candidates = list(self.active_slots)
        if self.used_tokens <= 0:
            self.used_tokens = sum(slot.token_cost for slot in self.active_slots)

    def get_slot(self, kind_or_name: str) -> Optional[WorkingMemorySlot]:
        for slot in self.active_slots:
            if slot.kind == kind_or_name or slot.name == kind_or_name:
                return slot
        return None

    def evidence_ids(self) -> list[str]:
        ids: list[str] = []
        for slot in self.active_slots:
            ids.extend(slot.source_ids)
        return unique_preserve_order(ids, limit=64)

    def render_prompt_context(self, *, max_lines: int = 7) -> str:
        """Render prompt context cực gọn.

        Prompt builder sau này có thể tự format đẹp hơn. Hàm này chỉ cung cấp
        bản tối thiểu để test end-to-end.
        """

        lines: list[str] = []
        if self.dominant_thread:
            lines.append(f"WorkingMemory dominant_thread: {self.dominant_thread}")
        for slot in self.active_slots[:max_lines]:
            if not slot.permission_to_surface:
                continue
            lines.append(slot.to_prompt_line())
        if self.context_pressure >= 0.78:
            lines.append("WorkingMemory note: context_pressure high; answer should stay focused and avoid extra associations.")
        if self.anti_drift_notes:
            lines.append("WorkingMemory anti_drift: " + "; ".join(self.anti_drift_notes[:3]))
        return "\n".join(lines).strip()

    @property
    def prompt_context(self) -> str:
        return self.render_prompt_context()

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_slots": [slot.to_dict() for slot in self.active_slots],
            "suppressed_items": list(self.suppressed_items),
            "dominant_thread": self.dominant_thread,
            "context_pressure": round(self.context_pressure, 4),
            "recall_competition": list(self.recall_competition),
            "workspace_candidates": [slot.to_dict() for slot in self.workspace_candidates],
            "token_budget": self.token_budget,
            "used_tokens": self.used_tokens,
            "slot_budget": self.slot_budget,
            "overflow": self.overflow,
            "anti_drift_notes": list(self.anti_drift_notes),
            "warnings": list(self.warnings),
            "debug": dict(self.debug),
        }


@dataclass(slots=True)
class WorkingMemoryCandidate:
    """Candidate nội bộ trước khi được chọn thành slot.

    Candidate có thể đến từ:
        - EvidenceItem
        - SalienceFrame / prompt evidence
        - MemoryPacket
        - Relation / affect / homeostasis / permission
        - Extra candidates do coordinator truyền vào
    """

    kind: WorkingMemorySlotKind
    content: str
    source_ids: list[str]
    confidence: float = 1.0
    base_priority: float = 0.5
    relevance: float = 0.5
    recency: float = 0.5
    risk: float = 0.0
    affective_weight: float = 0.0
    relational_weight: float = 0.0
    goal_weight: float = 0.0
    novelty: float = 0.0
    privacy_level: str = "normal"
    permission_to_surface: bool = True
    created_at: float = field(default_factory=now_ts)
    decay_after_seconds: float = 180.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Các field được engine tính sau.
    score: float = 0.0
    token_cost: int = 0
    symbolic_drift_risk: float = 0.0
    overassociation_risk: float = 0.0
    suppression_reason: Optional[SuppressionReason] = None

    def __post_init__(self) -> None:
        self.content = truncate_text(self.content, 1200)
        self.source_ids = unique_preserve_order(self.source_ids, limit=16)
        self.tags = unique_preserve_order(self.tags, limit=16)
        self.confidence = clamp01(self.confidence, 1.0)
        self.base_priority = clamp01(self.base_priority)
        self.relevance = clamp01(self.relevance)
        self.recency = clamp01(self.recency)
        self.risk = clamp01(self.risk)
        self.affective_weight = clamp01(self.affective_weight)
        self.relational_weight = clamp01(self.relational_weight)
        self.goal_weight = clamp01(self.goal_weight)
        self.novelty = clamp01(self.novelty)
        if self.token_cost <= 0:
            self.token_cost = estimate_tokens(self.content)

    @property
    def id(self) -> str:
        return stable_id("wmc", f"{self.kind}:{self.content}:{','.join(self.source_ids)}")

    @property
    def normalized_content(self) -> str:
        return normalize_text(self.content)

    def to_slot(self, *, name: Optional[str] = None, max_chars: int = 700) -> WorkingMemorySlot:
        return WorkingMemorySlot(
            name=name or self.kind,
            content=truncate_text(self.content, max_chars),
            priority=self.score,
            source_ids=list(self.source_ids),
            decay_after_seconds=self.decay_after_seconds,
            kind=self.kind,
            confidence=self.confidence,
            created_at=self.created_at,
            token_cost=min(self.token_cost, estimate_tokens(truncate_text(self.content, max_chars))),
            privacy_level=self.privacy_level,
            permission_to_surface=self.permission_to_surface,
            symbolic_drift_risk=self.symbolic_drift_risk,
            overassociation_risk=self.overassociation_risk,
            reason=str(self.metadata.get("reason", "")),
            tags=list(self.tags),
            metadata=dict(self.metadata),
        )


@dataclass(slots=True)
class WorkingMemoryConfig:
    """Cấu hình cổ chai.

    Slot budget mặc định:
        fast: 3
        normal: 5
        deep: 7
        reflection: 6

    Ngài có thể tăng token budget, nhưng đừng tưởng tăng context là tăng trí tuệ.
    Đa số trường hợp chỉ tăng diện tích cho hallucinated continuity mọc nấm.
    """

    max_slots_fast: int = 3
    max_slots_normal: int = 5
    max_slots_deep: int = 7
    max_slots_reflection: int = 6

    token_budget_fast: int = 280
    token_budget_normal: int = 620
    token_budget_deep: int = 1050
    token_budget_reflection: int = 850

    min_candidate_score: float = 0.22
    min_memory_confidence: float = 0.50
    min_memory_relevance: float = 0.42
    max_memory_slots: int = 2
    max_affect_slots: int = 1
    max_relation_slots: int = 1
    max_action_constraint_slots: int = 1

    duplicate_similarity_threshold: float = 0.86
    symbolic_drift_block_threshold: float = 0.62
    overassociation_block_threshold: float = 0.66
    poetic_overflow_block_threshold: float = 0.70

    current_request_decay_seconds: float = 300.0
    evidence_decay_seconds: float = 180.0
    goal_decay_seconds: float = 900.0
    memory_decay_seconds: float = 420.0
    relation_decay_seconds: float = 600.0
    affect_decay_seconds: float = 120.0
    action_decay_seconds: float = 180.0

    max_slot_chars: int = 700

    attach_to_frame: bool = True
    report_module_name: str = "working_memory"

    def slot_budget_for(self, budget_mode: Any) -> int:
        mode = str(budget_mode or "normal")
        if mode == "fast":
            return max(1, self.max_slots_fast)
        if mode == "deep":
            return max(1, self.max_slots_deep)
        if mode == "reflection":
            return max(1, self.max_slots_reflection)
        return max(1, self.max_slots_normal)

    def token_budget_for(self, budget_mode: Any) -> int:
        mode = str(budget_mode or "normal")
        if mode == "fast":
            return max(120, self.token_budget_fast)
        if mode == "deep":
            return max(240, self.token_budget_deep)
        if mode == "reflection":
            return max(240, self.token_budget_reflection)
        return max(160, self.token_budget_normal)


# ---------------------------------------------------------------------------
# Engine chính.
# ---------------------------------------------------------------------------


class WorkingMemoryEngine:
    """Bộ chọn WorkingMemoryFrame.

    Cách dùng:
        engine = WorkingMemoryEngine()
        wm = engine.select(frame)

    Contract:
        - đọc frame.
        - tạo candidates.
        - score candidates.
        - chọn 3-7 slot theo budget.
        - gắn frame.working_memory nếu frame cho phép.
        - ghi ModuleReport nếu frame có add_report.

    Không có LLM. Không gọi memory store. Không tự search web. Không làm trò ngoại cảm.
    """

    def __init__(self, config: Optional[WorkingMemoryConfig] = None) -> None:
        self.config = config or WorkingMemoryConfig()

    def select(
        self,
        frame: Any,
        *,
        extra_candidates: Optional[Iterable[WorkingMemoryCandidate | dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> WorkingMemoryFrame:
        timestamp = float(now if now is not None else safe_get(frame, "timestamp", now_ts()))
        budget_mode = safe_get(frame, "budget_mode", "normal")
        slot_budget = self.config.slot_budget_for(budget_mode)
        token_budget = self.config.token_budget_for(budget_mode)

        candidates = self._collect_candidates(frame, timestamp=timestamp)
        for item in safe_iter(extra_candidates):
            candidate = self._coerce_candidate(item, timestamp=timestamp)
            if candidate is not None:
                candidates.append(candidate)

        scored, suppressed = self._score_and_filter(candidates, frame=frame, timestamp=timestamp)
        active_slots, suppressed_late = self._select_slots(
            scored,
            slot_budget=slot_budget,
            token_budget=token_budget,
            timestamp=timestamp,
        )
        suppressed.extend(suppressed_late)

        used_tokens = sum(slot.token_cost for slot in active_slots)
        dominant_thread = self._choose_dominant_thread(active_slots, frame)
        context_pressure = self._context_pressure(
            used_tokens=used_tokens,
            token_budget=token_budget,
            active_slots=active_slots,
            suppressed=suppressed,
        )
        anti_drift_notes = self._anti_drift_notes(active_slots, suppressed)
        recall_competition = [item.to_debug_line() for item in suppressed if item.kind == "relevant_memory"][:24]
        suppressed_items = [item.to_debug_line() for item in suppressed][:60]
        warnings = self._warnings(active_slots, context_pressure, suppressed)

        wm_frame = WorkingMemoryFrame(
            active_slots=active_slots,
            suppressed_items=suppressed_items,
            dominant_thread=dominant_thread,
            context_pressure=context_pressure,
            recall_competition=recall_competition,
            workspace_candidates=list(active_slots),
            token_budget=token_budget,
            used_tokens=used_tokens,
            slot_budget=slot_budget,
            overflow=used_tokens > token_budget or len(scored) > len(active_slots),
            anti_drift_notes=anti_drift_notes,
            warnings=warnings,
            debug={
                "candidate_count": len(candidates),
                "scored_count": len(scored),
                "suppressed_count": len(suppressed),
                "budget_mode": str(budget_mode),
                "slot_budget": slot_budget,
                "token_budget": token_budget,
                "selected_kinds": [slot.kind for slot in active_slots],
                "selected_scores": {slot.kind: round(slot.priority, 4) for slot in active_slots},
            },
        )

        if self.config.attach_to_frame:
            self._attach_to_frame(frame, wm_frame)

        return wm_frame

    # ------------------------------------------------------------------
    # Candidate collection
    # ------------------------------------------------------------------

    def _collect_candidates(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        candidates: list[WorkingMemoryCandidate] = []
        candidates.extend(self._candidates_from_evidence(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_attention_candidates(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_percepts(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_salience(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_memory_packet(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_goal(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_relation(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_affect_homeostasis(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_constraints(frame, timestamp=timestamp))
        candidates.extend(self._candidates_from_temporal_spatial(frame, timestamp=timestamp))
        return candidates

    def _candidates_from_evidence(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        for ev in safe_iter(safe_get(frame, "evidence", [])):
            claim = str(safe_get(ev, "claim", "") or "").strip()
            if not claim:
                continue
            source = str(safe_get(ev, "source", "") or "")
            ev_id = str(safe_get(ev, "id", safe_get(ev, "source_signal_id", stable_id("ev", claim))))
            confidence = clamp01(safe_get(ev, "confidence", 0.65), 0.65)
            reliability = clamp01(safe_get(ev, "reliability", confidence), confidence)
            privacy = str(safe_get(ev, "privacy_level", "normal") or "normal")
            tags = [str(t) for t in safe_iter(safe_get(ev, "tags", []))]
            raw_or_inferred = str(safe_get(ev, "raw_or_inferred", "raw") or "raw")

            kind = self._evidence_kind(source=source, claim=claim, tags=tags, raw_or_inferred=raw_or_inferred)
            base = 0.42
            if kind == "current_user_request":
                base = 0.92
            elif kind == "immediate_evidence":
                base = 0.70
            elif kind == "risk_or_repair":
                base = 0.78
            elif kind == "relevant_memory":
                base = 0.46

            out.append(
                WorkingMemoryCandidate(
                    kind=kind,
                    content=claim,
                    source_ids=[ev_id],
                    confidence=min(confidence, reliability),
                    base_priority=base,
                    relevance=self._claim_relevance(claim, tags),
                    recency=self._recency_score(safe_get(ev, "timestamp", timestamp), timestamp),
                    risk=self._risk_score(claim, tags),
                    affective_weight=self._affective_score(claim, tags),
                    relational_weight=0.18 if any(t in {"relationship", "relational", "user"} for t in tags) else 0.0,
                    goal_weight=self._goal_score(claim, tags),
                    novelty=0.20 if raw_or_inferred == "raw" else 0.10,
                    privacy_level=privacy,
                    permission_to_surface=privacy not in {"private", "sensitive"},
                    created_at=float(safe_get(ev, "timestamp", timestamp) or timestamp),
                    decay_after_seconds=self._decay_for_kind(kind),
                    tags=tags + [source, raw_or_inferred],
                    metadata={
                        "reason": f"evidence:{source}:{raw_or_inferred}",
                        "source": source,
                        "raw_or_inferred": raw_or_inferred,
                    },
                )
            )
        return out

    def _candidates_from_attention_candidates(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        """Đọc Runtime AttentionCandidate cũ từ frame.attention_candidates.

        Coordinator hiện tại giữ attention ở `attention_candidates` + `broadcast`,
        không nhất thiết gắn `frame.salience`. Nếu WorkingMemory chỉ đọc evidence
        và salience mới, nó sẽ bỏ sót tín hiệu đã được attention chọn. Một cổ chai
        mà không đọc đầu vào chính thì hơi giống cửa kiểm soát không có cửa.
        """

        out: list[WorkingMemoryCandidate] = []
        for item in safe_iter(safe_get(frame, "attention_candidates", []))[:12]:
            content = str(safe_get(item, "content", safe_get(item, "claim", "")) or "").strip()
            if not content:
                continue
            label = str(safe_get(item, "label", "") or "").strip()
            source = str(safe_get(item, "source", "") or "").strip()
            score = clamp01(safe_get(item, "score", 0.45), 0.45)
            privacy = str(safe_get(item, "privacy_level", "normal") or "normal")
            evidence_ids = [str(x) for x in safe_iter(safe_get(item, "evidence", []))]
            if not evidence_ids:
                evidence_ids = [stable_id("att", content)]

            kind = self._attention_kind(label=label, source=source, content=content)
            out.append(
                WorkingMemoryCandidate(
                    kind=kind,
                    content=content,
                    source_ids=evidence_ids,
                    confidence=max(0.42, min(0.86, score)),
                    base_priority=max(0.42, score),
                    relevance=max(0.40, score),
                    recency=0.78,
                    risk=self._risk_score(content, [label, source]),
                    affective_weight=self._affective_score(content, [label, source]),
                    relational_weight=0.18 if label in {"relational_signal", "social_presence_event"} else 0.0,
                    goal_weight=self._goal_score(content, [label, source]),
                    novelty=0.16,
                    privacy_level=privacy,
                    permission_to_surface=privacy not in {"private", "sensitive"},
                    created_at=timestamp,
                    decay_after_seconds=self.config.evidence_decay_seconds,
                    tags=["attention_candidate", label, source],
                    metadata={"reason": "runtime attention candidate", "label": label, "source": source},
                )
            )
        return out

    def _candidates_from_percepts(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        """Fallback đọc percepts khi frame.evidence rỗng.

        `PerceptEvent` là contract runtime hiện tại. Ta chỉ lấy các percept đủ cụ thể
        để WorkingMemory không bị mù trong bản coordinator cũ.
        """

        out: list[WorkingMemoryCandidate] = []
        for item in safe_iter(safe_get(frame, "percepts", []))[:18]:
            kind_label = str(safe_get(item, "kind", "") or "").strip()
            content = str(safe_get(item, "content", "") or "").strip()
            if not content or kind_label in {"cycle_channel"}:
                continue
            source = str(safe_get(item, "source", "") or "runtime")
            confidence = clamp01(safe_get(item, "confidence", 0.55), 0.55)
            privacy = str(safe_get(item, "privacy_level", "normal") or "normal")
            evidence_ids = [f"percept:{kind_label}:{stable_id('p', content)[-12:]}"]
            wm_kind = self._attention_kind(label=kind_label, source=source, content=content)
            base = 0.44
            if kind_label in {"user_message", "user_force_speak"}:
                base = 0.88
            elif kind_label in {"background_observer", "vision_fact"}:
                base = 0.54
            out.append(
                WorkingMemoryCandidate(
                    kind=wm_kind,
                    content=content,
                    source_ids=evidence_ids,
                    confidence=confidence,
                    base_priority=base,
                    relevance=self._claim_relevance(content, [kind_label, source]),
                    recency=0.72,
                    risk=self._risk_score(content, [kind_label, source]),
                    affective_weight=self._affective_score(content, [kind_label, source]),
                    novelty=0.10,
                    privacy_level=privacy,
                    permission_to_surface=privacy not in {"private", "sensitive"},
                    created_at=timestamp,
                    decay_after_seconds=self._decay_for_kind(wm_kind),
                    tags=["percept", kind_label, source],
                    metadata={"reason": "runtime percept fallback", "kind": kind_label, "source": source},
                )
            )
        return out

    def _attention_kind(self, *, label: str, source: str, content: str) -> WorkingMemorySlotKind:
        label_l = str(label or "").lower()
        source_l = str(source or "").lower()
        text = normalize_text(content)
        if label_l in {"user_message", "user_force_speak"} or source_l in {"chat", "user_chat"}:
            return "current_user_request"
        if label_l in {"resource_pressure", "risk_or_repair"} or self._risk_score(text, [label_l, source_l]) >= 0.55:
            return "risk_or_repair"
        if label_l in {"persistent_goal"} or self._goal_score(text, [label_l, source_l]) >= 0.45:
            return "active_technical_goal" if self._looks_technical(text) else "open_question"
        if label_l in {"background_observer", "vision_fact", "active_window", "focus_context", "recent_event", "evidence"}:
            return "immediate_evidence"
        if label_l in {"social_presence_event"}:
            return "relational_state"
        if "body" in label_l or "body" in source_l:
            return "body_state"
        return "misc"

    def _candidates_from_salience(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        salience = safe_get(frame, "salience", None)
        if salience is None:
            return out

        dominant = safe_get(salience, "dominant_focus", None)
        reason = safe_get(salience, "reason", "")
        broadcast_priority = clamp01(safe_get(salience, "broadcast_priority", 0.0))
        salience_score = max(
            broadcast_priority,
            clamp01(safe_get(salience, "urgency", 0.0)) * 0.8,
            clamp01(safe_get(salience, "risk_relevance", 0.0)) * 0.9,
        )

        if dominant:
            content = str(dominant)
            if reason:
                content = f"{content} | reason: {truncate_text(reason, 180)}"
            out.append(
                WorkingMemoryCandidate(
                    kind="immediate_evidence",
                    content=content,
                    source_ids=["salience.dominant_focus"],
                    confidence=max(0.45, salience_score),
                    base_priority=max(0.62, salience_score),
                    relevance=max(0.58, clamp01(safe_get(salience, "user_relevance", 0.0))),
                    recency=0.86,
                    risk=clamp01(safe_get(salience, "risk_relevance", 0.0)),
                    affective_weight=clamp01(safe_get(salience, "affective_charge", 0.0)),
                    relational_weight=clamp01(safe_get(salience, "relational_relevance", 0.0)),
                    goal_weight=clamp01(safe_get(salience, "goal_relevance", 0.0)),
                    novelty=clamp01(safe_get(salience, "novelty", 0.0)),
                    decay_after_seconds=self.config.evidence_decay_seconds,
                    tags=["salience", "dominant_focus"],
                    metadata={"reason": "salience dominant focus"},
                )
            )

        # Nếu attention_salience.py có prompt_evidence/workspace hints, đọc mềm.
        prompt_items = safe_get(salience, "prompt_evidence", []) or safe_get(salience, "selected_evidence", [])
        for item in safe_iter(prompt_items)[:10]:
            text = str(safe_get(item, "content", safe_get(item, "claim", item)) or "").strip()
            if not text:
                continue
            out.append(
                WorkingMemoryCandidate(
                    kind="immediate_evidence",
                    content=text,
                    source_ids=[str(safe_get(item, "id", stable_id("sal", text)))],
                    confidence=clamp01(safe_get(item, "confidence", 0.62), 0.62),
                    base_priority=clamp01(safe_get(item, "score", 0.58), 0.58),
                    relevance=clamp01(safe_get(item, "relevance", 0.56), 0.56),
                    recency=0.75,
                    risk=clamp01(safe_get(item, "risk", 0.0)),
                    novelty=clamp01(safe_get(item, "novelty", 0.1)),
                    decay_after_seconds=self.config.evidence_decay_seconds,
                    tags=["salience", "prompt_evidence"],
                    metadata={"reason": "salience prompt evidence"},
                )
            )

        return out

    def _candidates_from_memory_packet(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        packet = safe_get(frame, "memory_packet", None)
        if packet is None:
            return out

        # Các layer memory có thể là list[str], list[dict], hoặc dataclass.
        layer_specs: list[tuple[str, float, float]] = [
            ("episodic", 0.45, 0.45),
            ("semantic", 0.42, 0.42),
            ("relational", 0.48, 0.50),
            ("affective_residue", 0.35, 0.34),
            ("procedural", 0.48, 0.55),
            ("temporal", 0.38, 0.40),
            ("spatial", 0.36, 0.38),
            ("worldview", 0.28, 0.30),
        ]
        for layer_name, base, relevance in layer_specs:
            items = safe_iter(safe_get(packet, layer_name, []))
            for idx, item in enumerate(items[:8]):
                text = self._memory_item_text(item)
                if not text:
                    continue
                confidence = clamp01(safe_get(item, "confidence", safe_get(item, "score", 0.58)), 0.58)
                relation = clamp01(
                    safe_get(item, "relation_to_current_context", safe_get(item, "relevance", relevance)),
                    relevance,
                )
                permission = bool(safe_get(item, "permission_to_surface", safe_get(item, "surface_allowed", True)))
                source_id = str(safe_get(item, "id", stable_id(f"mem_{layer_name}", text)))
                privacy = str(safe_get(item, "privacy_level", "normal") or "normal")
                tags = ["memory", layer_name] + [str(t) for t in safe_iter(safe_get(item, "tags", []))]
                out.append(
                    WorkingMemoryCandidate(
                        kind="relevant_memory",
                        content=f"{layer_name}: {text}",
                        source_ids=[source_id],
                        confidence=confidence,
                        base_priority=base,
                        relevance=relation,
                        recency=clamp01(safe_get(item, "recency", 0.35), 0.35),
                        risk=clamp01(safe_get(item, "risk", 0.0)),
                        affective_weight=0.35 if layer_name == "affective_residue" else 0.12,
                        relational_weight=0.42 if layer_name == "relational" else 0.08,
                        goal_weight=0.24 if layer_name in {"procedural", "semantic"} else 0.08,
                        novelty=0.05,
                        privacy_level=privacy,
                        permission_to_surface=permission and privacy not in {"private", "sensitive"},
                        created_at=timestamp,
                        decay_after_seconds=self.config.memory_decay_seconds,
                        tags=tags,
                        metadata={
                            "reason": f"memory_packet:{layer_name}",
                            "layer": layer_name,
                            "index": idx,
                            "relation_to_current_context": relation,
                        },
                    )
                )
        return out

    def _candidates_from_goal(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        goal_state = safe_get(frame, "goal_persistence", None)
        if goal_state is None:
            internal = safe_get(frame, "internal_state", None)
            goal_state = safe_get(internal, "goal_persistence", None)
        if goal_state is None:
            reports = safe_get(frame, "reports", {})
            goal_report = reports.get("goal_persistence") if isinstance(reports, dict) else None
            goal_state = safe_get(goal_report, "result", None)
        if goal_state is None:
            return out

        summary = str(safe_get(goal_state, "summary", "") or safe_get(goal_state, "active_goal", "") or "").strip()
        if not summary:
            return out
        active = bool(safe_get(goal_state, "active", True))
        status = str(safe_get(goal_state, "status", "active") or "active")
        if not active or status in {"closed", "stale", "rejected"}:
            return out
        strength = clamp01(safe_get(goal_state, "strength", 0.50), 0.50)
        confidence = clamp01(safe_get(goal_state, "confidence", 0.56), 0.56)
        actionability = clamp01(safe_get(goal_state, "actionability", 0.4), 0.4)
        can_intervene = bool(safe_get(goal_state, "can_intervene", False))
        anchors = [str(x) for x in safe_iter(safe_get(goal_state, "anchors", []))]
        content = summary
        next_hint = str(safe_get(goal_state, "next_hint", "") or "").strip()
        if next_hint:
            content += f" | next: {truncate_text(next_hint, 160)}"
        out.append(
            WorkingMemoryCandidate(
                kind="active_technical_goal" if self._looks_technical(summary) else "open_question",
                content=content,
                source_ids=[str(safe_get(goal_state, "id", stable_id("goal", summary)))],
                confidence=confidence,
                base_priority=0.62 + strength * 0.22,
                relevance=max(0.45, strength),
                recency=0.58,
                goal_weight=max(strength, actionability),
                novelty=0.04,
                permission_to_surface=can_intervene,
                decay_after_seconds=self.config.goal_decay_seconds,
                tags=["goal", "active"] + anchors[:6],
                metadata={
                    "reason": "active goal persistence",
                    "strength": strength,
                    "actionability": actionability,
                    "can_intervene": can_intervene,
                    "anchors": anchors,
                },
            )
        )
        return out

    def _candidates_from_relation(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        relation = safe_get(frame, "relation", None) or safe_get(frame, "relationship", None)
        if relation is None:
            internal = safe_get(frame, "internal_state", None)
            relation = safe_get(internal, "relationship_dynamics", None)
        if relation is None:
            return []

        trust = clamp01(safe_get(relation, "trust", 0.0))
        rupture = clamp01(safe_get(relation, "rupture", 0.0))
        repair_need = clamp01(safe_get(relation, "repair_need", 0.0))
        distance = clamp01(safe_get(relation, "preferred_distance", 0.5), 0.5)
        dignity = clamp01(safe_get(relation, "dignity_defense", 0.0))
        overread = clamp01(safe_get(relation, "overread_correction", 0.0))
        technical_respect = clamp01(safe_get(relation, "technical_respect", 0.0))
        if max(rupture, repair_need, dignity, overread, technical_respect) < 0.18 and trust < 0.2:
            return []

        parts = [
            f"trust={trust:.2f}",
            f"rupture={rupture:.2f}",
            f"repair_need={repair_need:.2f}",
            f"preferred_distance={distance:.2f}",
            f"dignity_defense={dignity:.2f}",
            f"overread_correction={overread:.2f}",
            f"technical_respect={technical_respect:.2f}",
        ]
        return [
            WorkingMemoryCandidate(
                kind="relational_state",
                content="relational pressure: " + "; ".join(parts),
                source_ids=["frame.relation"],
                confidence=0.62,
                base_priority=0.48 + max(rupture, repair_need, dignity, overread) * 0.25,
                relevance=0.52 + max(repair_need, dignity, technical_respect) * 0.25,
                recency=0.55,
                relational_weight=max(rupture, repair_need, dignity, overread, technical_respect),
                decay_after_seconds=self.config.relation_decay_seconds,
                permission_to_surface=False,  # Đây là pressure nội bộ, không phải câu để nói thẳng.
                tags=["relation", "internal_pressure"],
                metadata={"reason": "relationship dynamics pressure"},
            )
        ]

    def _candidates_from_affect_homeostasis(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        affect = safe_get(frame, "affect", None)
        homeostasis = safe_get(frame, "homeostasis", None)

        if affect is not None:
            tension = clamp01(safe_get(affect, "tension", 0.0))
            restraint = clamp01(safe_get(affect, "restraint", 0.0))
            curiosity = clamp01(safe_get(affect, "curiosity", 0.0))
            fatigue = clamp01(safe_get(affect, "fatigue", 0.0))
            exposure = clamp01(safe_get(affect, "exposure_recoil", 0.0))
            continuity = clamp01(safe_get(affect, "continuity_anxiety", 0.0))
            peak = max(tension, restraint, curiosity, fatigue, exposure, continuity)
            if peak >= 0.18:
                out.append(
                    WorkingMemoryCandidate(
                        kind="affect_homeostasis",
                        content=(
                            "affective pressure: "
                            f"tension={tension:.2f}; restraint={restraint:.2f}; curiosity={curiosity:.2f}; "
                            f"fatigue={fatigue:.2f}; exposure_recoil={exposure:.2f}; continuity={continuity:.2f}"
                        ),
                        source_ids=["frame.affect"],
                        confidence=0.58,
                        base_priority=0.34 + peak * 0.26,
                        relevance=0.42 + peak * 0.20,
                        affective_weight=peak,
                        recency=0.60,
                        decay_after_seconds=self.config.affect_decay_seconds,
                        permission_to_surface=False,
                        tags=["affect", "internal_pressure"],
                        metadata={"reason": "affect is pressure, not dialogue"},
                    )
                )

        if homeostasis is not None:
            cognitive_load = clamp01(safe_get(homeostasis, "cognitive_load", 0.0))
            social_load = clamp01(safe_get(homeostasis, "social_load", 0.0))
            speech_cost = clamp01(safe_get(homeostasis, "speech_cost", 0.0))
            regulation = str(safe_get(homeostasis, "regulation_policy", "normal") or "normal")
            peak = max(cognitive_load, social_load, speech_cost)
            if peak >= 0.18 or regulation != "normal":
                out.append(
                    WorkingMemoryCandidate(
                        kind="affect_homeostasis",
                        content=(
                            "homeostasis: "
                            f"cognitive_load={cognitive_load:.2f}; social_load={social_load:.2f}; "
                            f"speech_cost={speech_cost:.2f}; policy={regulation}"
                        ),
                        source_ids=["frame.homeostasis"],
                        confidence=0.62,
                        base_priority=0.38 + peak * 0.22,
                        relevance=0.44 + peak * 0.20,
                        affective_weight=peak,
                        recency=0.60,
                        decay_after_seconds=self.config.affect_decay_seconds,
                        permission_to_surface=False,
                        tags=["homeostasis", "internal_pressure", regulation],
                        metadata={"reason": "homeostatic regulation pressure"},
                    )
                )
        return out

    def _candidates_from_constraints(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        permission = safe_get(frame, "permission", None)
        grounding = safe_get(frame, "grounding", None)
        agency = safe_get(frame, "agency", None)
        speech_plan = safe_get(frame, "speech_plan", None)

        if permission is not None:
            max_intensity = clamp01(safe_get(permission, "max_intensity", 1.0), 1.0)
            allowed = safe_get(permission, "allowed_reaction", [])
            reason = str(safe_get(permission, "reason", "") or "")
            allowed_text = ", ".join(unique_preserve_order(allowed, limit=6))
            content = f"permission: max_intensity={max_intensity:.2f}; allowed={allowed_text or 'unknown'}"
            if reason:
                content += f"; reason={truncate_text(reason, 160)}"
            if max_intensity < 0.95 or allowed_text or reason:
                out.append(
                    WorkingMemoryCandidate(
                        kind="action_constraint",
                        content=content,
                        source_ids=["frame.permission"],
                        confidence=0.70,
                        base_priority=0.56 + (1.0 - max_intensity) * 0.20,
                        relevance=0.65,
                        risk=1.0 - max_intensity,
                        recency=0.70,
                        permission_to_surface=False,
                        decay_after_seconds=self.config.action_decay_seconds,
                        tags=["permission", "constraint"],
                        metadata={"reason": "permission constraint"},
                    )
                )

        if grounding is not None:
            factual_risk = clamp01(safe_get(grounding, "factual_risk", 0.0))
            unsupported = safe_iter(safe_get(grounding, "unsupported_claims", []))
            if factual_risk >= 0.18 or unsupported:
                out.append(
                    WorkingMemoryCandidate(
                        kind="risk_or_repair",
                        content=(
                            f"grounding risk: factual_risk={factual_risk:.2f}; "
                            f"unsupported={', '.join(unique_preserve_order(unsupported, limit=4))}"
                        ),
                        source_ids=["frame.grounding"],
                        confidence=0.74,
                        base_priority=0.70,
                        relevance=0.72,
                        risk=max(factual_risk, 0.45 if unsupported else 0.0),
                        recency=0.75,
                        permission_to_surface=False,
                        decay_after_seconds=self.config.action_decay_seconds,
                        tags=["grounding", "risk"],
                        metadata={"reason": "grounding guard warning"},
                    )
                )

        if agency is not None:
            intent = str(safe_get(agency, "intent", "") or "")
            reason = str(safe_get(agency, "reason", "") or "")
            strength = clamp01(safe_get(agency, "commitment_strength", 0.0))
            if intent:
                content = f"agency: intent={intent}; strength={strength:.2f}"
                if reason:
                    content += f"; reason={truncate_text(reason, 160)}"
                out.append(
                    WorkingMemoryCandidate(
                        kind="action_constraint",
                        content=content,
                        source_ids=["frame.agency"],
                        confidence=0.62,
                        base_priority=0.42 + strength * 0.25,
                        relevance=0.50 + strength * 0.20,
                        recency=0.62,
                        permission_to_surface=False,
                        decay_after_seconds=self.config.action_decay_seconds,
                        tags=["agency", intent],
                        metadata={"reason": "agency commitment"},
                    )
                )

        if speech_plan is not None:
            act = str(safe_get(speech_plan, "speech_act", "") or "")
            avoid = unique_preserve_order(safe_get(speech_plan, "must_avoid", []), limit=6)
            include = unique_preserve_order(safe_get(speech_plan, "must_include", []), limit=6)
            if act or avoid or include:
                out.append(
                    WorkingMemoryCandidate(
                        kind="action_constraint",
                        content=f"speech_plan: act={act or 'unknown'}; include={include}; avoid={avoid}",
                        source_ids=["frame.speech_plan"],
                        confidence=0.66,
                        base_priority=0.50,
                        relevance=0.62,
                        recency=0.65,
                        permission_to_surface=False,
                        decay_after_seconds=self.config.action_decay_seconds,
                        tags=["speech_plan", "constraint"],
                        metadata={"reason": "speech plan constraint"},
                    )
                )
        return out

    def _candidates_from_temporal_spatial(self, frame: Any, *, timestamp: float) -> list[WorkingMemoryCandidate]:
        out: list[WorkingMemoryCandidate] = []
        temporal = safe_get(frame, "temporal", None)
        spatial = safe_get(frame, "spatial", None)

        if temporal is not None:
            rhythm = str(safe_get(temporal, "rhythm", "") or "")
            pressure = max(
                clamp01(safe_get(temporal, "unfinished_time_pressure", 0.0)),
                clamp01(safe_get(temporal, "meaning_debt", 0.0)),
                clamp01(safe_get(temporal, "waiting_pressure", 0.0)),
                clamp01(safe_get(temporal, "repetition_fatigue", 0.0)),
            )
            if rhythm or pressure >= 0.18:
                out.append(
                    WorkingMemoryCandidate(
                        kind="temporal_context",
                        content=f"temporal: rhythm={rhythm or 'unknown'}; pressure={pressure:.2f}",
                        source_ids=["frame.temporal"],
                        confidence=0.56,
                        base_priority=0.34 + pressure * 0.20,
                        relevance=0.40 + pressure * 0.18,
                        recency=0.56,
                        novelty=0.04,
                        decay_after_seconds=180,
                        permission_to_surface=False,
                        tags=["temporal", rhythm],
                        metadata={"reason": "temporal bottleneck context"},
                    )
                )

        if spatial is not None:
            relation = str(safe_get(spatial, "shared_space_relation", "") or "")
            obstruction = clamp01(safe_get(spatial, "obstruction_risk", 0.0))
            body_meaning = str(safe_get(spatial, "body_interaction_meaning", "") or "")
            if relation or obstruction >= 0.18 or body_meaning:
                out.append(
                    WorkingMemoryCandidate(
                        kind="spatial_context",
                        content=(
                            f"spatial: relation={relation or 'unknown'}; "
                            f"obstruction_risk={obstruction:.2f}; body_meaning={body_meaning or 'none'}"
                        ),
                        source_ids=["frame.spatial"],
                        confidence=0.56,
                        base_priority=0.32 + obstruction * 0.22,
                        relevance=0.40 + obstruction * 0.20,
                        risk=obstruction,
                        recency=0.56,
                        decay_after_seconds=180,
                        permission_to_surface=False,
                        tags=["spatial", relation],
                        metadata={"reason": "spatial/body context"},
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Scoring / suppression
    # ------------------------------------------------------------------

    def _score_and_filter(
        self,
        candidates: list[WorkingMemoryCandidate],
        *,
        frame: Any,
        timestamp: float,
    ) -> tuple[list[WorkingMemoryCandidate], list[SuppressedMemoryItem]]:
        scored: list[WorkingMemoryCandidate] = []
        suppressed: list[SuppressedMemoryItem] = []
        seen_texts: list[str] = []
        technical_context = self._frame_is_technical(frame)

        for cand in candidates:
            cand.symbolic_drift_risk = self._symbolic_drift_risk(cand, technical_context=technical_context)
            cand.overassociation_risk = self._overassociation_risk(cand, frame=frame)
            cand.score = self._candidate_score(cand, technical_context=technical_context)

            reason = self._early_suppression_reason(cand, timestamp=timestamp, technical_context=technical_context)
            if reason is None:
                duplicate_of = self._find_duplicate(cand.normalized_content, seen_texts)
                if duplicate_of is not None:
                    reason = "duplicate"
                    cand.metadata["duplicate_of"] = duplicate_of

            if reason is not None:
                suppressed.append(self._suppressed(cand, reason))
                continue

            seen_texts.append(cand.normalized_content)
            scored.append(cand)

        scored.sort(key=lambda c: (c.score, c.confidence, -c.token_cost), reverse=True)
        return scored, suppressed

    def _candidate_score(self, cand: WorkingMemoryCandidate, *, technical_context: bool) -> float:
        """Tính điểm candidate.

        Công thức cố tình thiên về current request / immediate evidence / risk thật.
        Memory và affect chỉ được vào nếu liên quan rõ.
        """

        score = (
            cand.base_priority * 0.26
            + cand.confidence * 0.17
            + cand.relevance * 0.18
            + cand.recency * 0.10
            + cand.risk * 0.10
            + cand.goal_weight * 0.08
            + cand.relational_weight * 0.04
            + cand.affective_weight * 0.04
            + cand.novelty * 0.03
        )

        if cand.kind == "current_user_request":
            score += 0.20
        elif cand.kind == "immediate_evidence":
            score += 0.10
        elif cand.kind == "risk_or_repair":
            score += 0.12
        elif cand.kind == "relevant_memory":
            score -= 0.05
        elif cand.kind == "affect_homeostasis":
            score -= 0.04

        # Technical context ưu tiên task/evidence hơn poetic/affective association.
        if technical_context:
            if cand.kind in {"current_user_request", "active_technical_goal", "immediate_evidence", "action_constraint"}:
                score += 0.05
            if cand.kind == "relevant_memory" and cand.affective_weight > 0.28:
                score -= 0.08
            if cand.symbolic_drift_risk > 0.35:
                score -= cand.symbolic_drift_risk * 0.18

        # Chi phí token lớn phải trả giá. Prompt không phải kho lạnh.
        if cand.token_cost > 160:
            score -= min(0.12, (cand.token_cost - 160) / 1200)

        # Nguy cơ over-association trừ trực tiếp.
        score -= cand.overassociation_risk * 0.16
        return clamp01(score)

    def _early_suppression_reason(
        self,
        cand: WorkingMemoryCandidate,
        *,
        timestamp: float,
        technical_context: bool,
    ) -> Optional[SuppressionReason]:
        if not cand.content.strip():
            return "low_priority"
        if (timestamp - cand.created_at) > cand.decay_after_seconds:
            return "expired"
        if cand.privacy_level in {"private", "sensitive"} or not cand.permission_to_surface:
            # Internal pressure được giữ nhưng không nên surface. Tuy vậy các slot internal
            # như relation/affect/constraint vẫn có ích cho workspace, nên không block toàn bộ.
            if cand.kind not in {"relational_state", "affect_homeostasis", "action_constraint", "risk_or_repair", "temporal_context", "spatial_context"}:
                return "privacy_blocked"
        if cand.confidence < 0.28:
            return "low_confidence"
        if cand.kind == "relevant_memory":
            if cand.confidence < self.config.min_memory_confidence:
                return "low_confidence"
            if cand.relevance < self.config.min_memory_relevance:
                return "irrelevant_recall"
            if cand.score < 0.38:
                return "weak_memory_echo"
        if cand.symbolic_drift_risk >= self.config.symbolic_drift_block_threshold:
            return "symbolic_drift_risk"
        if cand.overassociation_risk >= self.config.overassociation_block_threshold:
            return "overassociation_risk"
        if technical_context and cand.kind == "relevant_memory" and cand.affective_weight > self.config.poetic_overflow_block_threshold:
            return "poetic_overflow_risk"
        if cand.score < self.config.min_candidate_score:
            return "low_priority"
        return None

    def _select_slots(
        self,
        candidates: list[WorkingMemoryCandidate],
        *,
        slot_budget: int,
        token_budget: int,
        timestamp: float,
    ) -> tuple[list[WorkingMemorySlot], list[SuppressedMemoryItem]]:
        selected: list[WorkingMemorySlot] = []
        suppressed: list[SuppressedMemoryItem] = []
        used_tokens = 0
        kind_counts: dict[str, int] = {}

        # Quota mềm để working memory không biến thành MemoryPacket phiên bản xấu hơn.
        quotas = {
            "relevant_memory": self.config.max_memory_slots,
            "affect_homeostasis": self.config.max_affect_slots,
            "relational_state": self.config.max_relation_slots,
            "action_constraint": self.config.max_action_constraint_slots,
        }

        # Chọn theo rank, nhưng luôn giữ request hiện tại nếu có.
        ordered = sorted(
            candidates,
            key=lambda c: (
                1 if c.kind == "current_user_request" else 0,
                1 if c.kind == "risk_or_repair" else 0,
                c.score,
                c.confidence,
            ),
            reverse=True,
        )

        for cand in ordered:
            if len(selected) >= slot_budget:
                suppressed.append(self._suppressed(cand, "slot_budget"))
                continue
            if used_tokens + cand.token_cost > token_budget:
                # Nếu candidate rất quan trọng, thử cắt ngắn thay vì loại.
                if cand.score >= 0.70 and cand.token_cost > 60:
                    shortened = cand.to_slot(max_chars=max(180, self.config.max_slot_chars // 2))
                    if used_tokens + shortened.token_cost <= token_budget:
                        selected.append(shortened)
                        used_tokens += shortened.token_cost
                        kind_counts[cand.kind] = kind_counts.get(cand.kind, 0) + 1
                        continue
                suppressed.append(self._suppressed(cand, "token_budget"))
                continue

            quota = quotas.get(cand.kind)
            if quota is not None and kind_counts.get(cand.kind, 0) >= quota:
                suppressed.append(self._suppressed(cand, "memory_quota" if cand.kind == "relevant_memory" else "replaced_by_stronger_slot"))
                continue

            slot = cand.to_slot(max_chars=self.config.max_slot_chars)
            selected.append(slot)
            used_tokens += slot.token_cost
            kind_counts[cand.kind] = kind_counts.get(cand.kind, 0) + 1

        # Nếu không có gì được chọn, tạo một slot an toàn từ request/evidence yếu nhất nếu có.
        if not selected and candidates:
            best = max(candidates, key=lambda c: c.score)
            selected.append(best.to_slot(max_chars=360))

        return selected, suppressed

    # ------------------------------------------------------------------
    # Risk / relevance helpers
    # ------------------------------------------------------------------

    def _evidence_kind(self, *, source: str, claim: str, tags: list[str], raw_or_inferred: str) -> WorkingMemorySlotKind:
        tag_set = {t.lower() for t in tags}
        text = normalize_text(claim)
        if source == "user_chat":
            return "current_user_request"
        if source == "memory":
            return "relevant_memory"
        if "repair" in tag_set or "correction" in tag_set or "risk" in tag_set:
            return "risk_or_repair"
        if "goal" in tag_set or "task" in tag_set or self._looks_technical(text):
            return "immediate_evidence"
        if raw_or_inferred == "inferred" and any(term in text for term in AFFECT_TERMS):
            return "risk_or_repair"
        return "immediate_evidence"

    def _claim_relevance(self, claim: str, tags: list[str]) -> float:
        text = normalize_text(claim)
        tag_set = {t.lower() for t in tags}
        score = 0.34
        if self._looks_technical(text) or tag_set & {"technical", "code", "debug", "architecture", "runtime"}:
            score += 0.28
        if tag_set & {"user", "request", "question", "directive"}:
            score += 0.25
        if tag_set & {"risk", "error", "exception", "correction", "repair"}:
            score += 0.24
        if len(text) > 30:
            score += 0.08
        return clamp01(score)

    def _risk_score(self, claim: str, tags: list[str]) -> float:
        text = normalize_text(claim)
        tag_set = {t.lower() for t in tags}
        score = 0.0
        if tag_set & {"risk", "error", "exception", "traceback", "privacy", "sensitive", "repair", "correction"}:
            score += 0.45
        if any(term in text for term in ["error", "exception", "traceback", "failed", "sai", "lỗi", "không đúng", "privacy"]):
            score += 0.32
        return clamp01(score)

    def _affective_score(self, claim: str, tags: list[str]) -> float:
        text = normalize_text(claim)
        tag_set = {t.lower() for t in tags}
        score = 0.0
        if tag_set & {"affect", "emotion", "emotional_residue", "distress"}:
            score += 0.38
        if any(term in text for term in AFFECT_TERMS):
            score += 0.28
        return clamp01(score)

    def _goal_score(self, claim: str, tags: list[str]) -> float:
        text = normalize_text(claim)
        tag_set = {t.lower() for t in tags}
        score = 0.0
        if tag_set & {"goal", "task", "architecture", "debug", "todo", "project"}:
            score += 0.36
        if self._looks_technical(text):
            score += 0.24
        if any(x in text for x in ["làm", "tạo", "fix", "gửi", "file", "module", "pipeline"]):
            score += 0.24
        return clamp01(score)

    def _recency_score(self, item_timestamp: Any, frame_timestamp: float) -> float:
        try:
            ts = float(item_timestamp)
        except Exception:
            return 0.50
        age = max(0.0, frame_timestamp - ts)
        if age <= 5:
            return 1.0
        if age <= 60:
            return 0.85
        if age <= 300:
            return 0.62
        if age <= 900:
            return 0.42
        return 0.20

    def _symbolic_drift_risk(self, cand: WorkingMemoryCandidate, *, technical_context: bool) -> float:
        text = cand.normalized_content
        symbolic_hits = sum(1 for term in SYMBOLIC_DRIFT_TERMS if term in text)
        if symbolic_hits <= 0:
            return 0.0
        risk = min(0.70, symbolic_hits * 0.18)
        if cand.kind == "relevant_memory":
            risk += 0.12
        if cand.confidence < 0.65:
            risk += 0.15
        if not cand.source_ids:
            risk += 0.20
        if technical_context:
            risk += 0.12
        if cand.kind in {"current_user_request", "immediate_evidence"}:
            risk -= 0.10
        return clamp01(risk)

    def _overassociation_risk(self, cand: WorkingMemoryCandidate, *, frame: Any) -> float:
        # Memory cũ, affective residue, worldview thường dễ kéo ERIS qua "liên tưởng sâu".
        risk = 0.0
        if cand.kind == "relevant_memory":
            layer = str(cand.metadata.get("layer", ""))
            if layer in {"affective_residue", "worldview", "relational"}:
                risk += 0.22
            if cand.relevance < 0.55:
                risk += 0.18
            if cand.confidence < 0.62:
                risk += 0.15
        if cand.affective_weight > 0.55 and cand.risk < 0.20:
            risk += 0.15
        if cand.goal_weight < 0.20 and cand.relational_weight > 0.45:
            risk += 0.12

        # Nếu salience rất thấp mà candidate lại symbolic, càng nguy hiểm.
        salience = safe_get(frame, "salience", None)
        broadcast = clamp01(safe_get(salience, "broadcast_priority", 0.0)) if salience else 0.0
        if broadcast < 0.35 and cand.symbolic_drift_risk > 0.20:
            risk += 0.15
        return clamp01(risk)

    def _find_duplicate(self, text: str, seen_texts: list[str]) -> Optional[str]:
        if not text:
            return None
        for seen in seen_texts:
            if not seen:
                continue
            if text == seen:
                return seen
            sim = self._jaccard_similarity(text, seen)
            if sim >= self.config.duplicate_similarity_threshold:
                return seen
        return None

    def _jaccard_similarity(self, a: str, b: str) -> float:
        ta = set(re.findall(r"\w+", a, flags=re.UNICODE))
        tb = set(re.findall(r"\w+", b, flags=re.UNICODE))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(1, len(ta | tb))

    def _suppressed(self, cand: WorkingMemoryCandidate, reason: SuppressionReason) -> SuppressedMemoryItem:
        return SuppressedMemoryItem(
            item_id=cand.id,
            kind=cand.kind,
            content=truncate_text(cand.content, 260),
            reason=reason,
            score=cand.score,
            confidence=cand.confidence,
            source_ids=list(cand.source_ids),
            debug={
                "token_cost": cand.token_cost,
                "relevance": round(cand.relevance, 4),
                "recency": round(cand.recency, 4),
                "risk": round(cand.risk, 4),
                "symbolic_drift_risk": round(cand.symbolic_drift_risk, 4),
                "overassociation_risk": round(cand.overassociation_risk, 4),
                "metadata": dict(cand.metadata),
            },
        )

    # ------------------------------------------------------------------
    # Frame-level summary
    # ------------------------------------------------------------------

    def _choose_dominant_thread(self, slots: list[WorkingMemorySlot], frame: Any) -> Optional[str]:
        if not slots:
            return None

        # Ưu tiên explicit dominant_focus nếu nó đã vào working memory.
        salience = safe_get(frame, "salience", None)
        salience_focus = str(safe_get(salience, "dominant_focus", "") or "").strip() if salience else ""
        if salience_focus:
            return truncate_text(salience_focus, 180)

        for kind in ("current_user_request", "active_technical_goal", "risk_or_repair", "immediate_evidence"):
            slot = next((s for s in slots if s.kind == kind), None)
            if slot is not None:
                return truncate_text(slot.content, 180)
        return truncate_text(max(slots, key=lambda s: s.priority).content, 180)

    def _context_pressure(
        self,
        *,
        used_tokens: int,
        token_budget: int,
        active_slots: list[WorkingMemorySlot],
        suppressed: list[SuppressedMemoryItem],
    ) -> float:
        budget_pressure = used_tokens / max(1, token_budget)
        slot_pressure = len(active_slots) / max(1, max(1, len(active_slots) + len(suppressed)))
        suppressed_pressure = min(1.0, len(suppressed) / 16)
        symbolic_pressure = max([slot.symbolic_drift_risk for slot in active_slots] or [0.0])
        return clamp01(budget_pressure * 0.55 + slot_pressure * 0.12 + suppressed_pressure * 0.18 + symbolic_pressure * 0.15)

    def _anti_drift_notes(self, slots: list[WorkingMemorySlot], suppressed: list[SuppressedMemoryItem]) -> list[str]:
        notes: list[str] = []
        if any(item.reason == "symbolic_drift_risk" for item in suppressed):
            notes.append("symbolic drift candidate suppressed; keep response grounded in selected evidence")
        if any(item.reason == "overassociation_risk" for item in suppressed):
            notes.append("over-association candidate suppressed; do not infer continuity beyond active slots")
        if any(item.reason == "weak_memory_echo" for item in suppressed):
            notes.append("weak memory echo suppressed; avoid hallucinated continuity")
        if any(slot.kind == "affect_homeostasis" for slot in slots):
            notes.append("affect/homeostasis is pressure only; do not verbalize as emotion claim")
        if any(slot.kind == "relational_state" for slot in slots):
            notes.append("relation state is internal style pressure; do not expose labels")
        return unique_preserve_order(notes, limit=8)

    def _warnings(
        self,
        slots: list[WorkingMemorySlot],
        context_pressure: float,
        suppressed: list[SuppressedMemoryItem],
    ) -> list[str]:
        warnings: list[str] = []
        if context_pressure >= 0.78:
            warnings.append("context_pressure_high")
        if not any(slot.kind == "current_user_request" for slot in slots):
            warnings.append("no_current_user_request_slot")
        if sum(1 for slot in slots if slot.kind == "relevant_memory") >= self.config.max_memory_slots:
            warnings.append("memory_quota_filled")
        if any(item.reason == "token_budget" for item in suppressed):
            warnings.append("token_budget_suppressed_candidates")
        if any(item.reason == "poetic_overflow_risk" for item in suppressed):
            warnings.append("poetic_overflow_suppressed")
        return unique_preserve_order(warnings, limit=10)

    # ------------------------------------------------------------------
    # Coercion / attachment
    # ------------------------------------------------------------------

    def _coerce_candidate(self, item: WorkingMemoryCandidate | dict[str, Any], *, timestamp: float) -> Optional[WorkingMemoryCandidate]:
        if isinstance(item, WorkingMemoryCandidate):
            return item
        if not isinstance(item, dict):
            return None
        content = str(item.get("content", item.get("claim", "")) or "").strip()
        if not content:
            return None
        return WorkingMemoryCandidate(
            kind=item.get("kind", "misc"),
            content=content,
            source_ids=[str(x) for x in safe_iter(item.get("source_ids", item.get("evidence_ids", [])))],
            confidence=clamp01(item.get("confidence", 0.60), 0.60),
            base_priority=clamp01(item.get("base_priority", item.get("priority", 0.50)), 0.50),
            relevance=clamp01(item.get("relevance", 0.50), 0.50),
            recency=clamp01(item.get("recency", 0.50), 0.50),
            risk=clamp01(item.get("risk", 0.0)),
            affective_weight=clamp01(item.get("affective_weight", 0.0)),
            relational_weight=clamp01(item.get("relational_weight", 0.0)),
            goal_weight=clamp01(item.get("goal_weight", 0.0)),
            novelty=clamp01(item.get("novelty", 0.0)),
            privacy_level=str(item.get("privacy_level", "normal") or "normal"),
            permission_to_surface=bool(item.get("permission_to_surface", True)),
            created_at=float(item.get("created_at", timestamp) or timestamp),
            decay_after_seconds=float(item.get("decay_after_seconds", 180.0) or 180.0),
            tags=[str(x) for x in safe_iter(item.get("tags", []))],
            metadata=dict(item.get("metadata", {})),
        )

    def _attach_to_frame(self, frame: Any, wm_frame: WorkingMemoryFrame) -> None:
        try:
            if hasattr(frame, "set_slot"):
                frame.set_slot("working_memory", wm_frame, module_name=self.config.report_module_name)
            else:
                setattr(frame, "working_memory", wm_frame)
        except Exception:
            # Không để lỗi attach làm mất kết quả. Giai đoạn gắn repo mà chết ở setter
            # là kiểu chết rất kém sang.
            pass

        evidence_used = wm_frame.evidence_ids()
        report = ModuleReport(
            module_name=self.config.report_module_name,
            confidence=self._report_confidence(wm_frame),
            pressure=wm_frame.context_pressure,
            evidence_used=evidence_used,
            result=wm_frame,
            warnings=list(wm_frame.warnings),
            debug=dict(wm_frame.debug),
        )
        try:
            if hasattr(frame, "add_report"):
                frame.add_report(report)
            else:
                reports = safe_get(frame, "reports", None)
                if isinstance(reports, dict):
                    reports[self.config.report_module_name] = report
        except Exception:
            pass

    def _report_confidence(self, wm_frame: WorkingMemoryFrame) -> float:
        if not wm_frame.active_slots:
            return 0.0
        avg = sum(slot.confidence for slot in wm_frame.active_slots) / len(wm_frame.active_slots)
        pressure_penalty = max(0.0, wm_frame.context_pressure - 0.72) * 0.22
        warning_penalty = min(0.16, len(wm_frame.warnings) * 0.03)
        return clamp01(avg - pressure_penalty - warning_penalty)

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _memory_item_text(self, item: Any) -> str:
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ("content", "summary", "claim", "text", "description"):
                if item.get(key):
                    return str(item[key]).strip()
            return str(item).strip()
        for key in ("content", "summary", "claim", "text", "description"):
            value = safe_get(item, key, None)
            if value:
                return str(value).strip()
        return str(item or "").strip()

    def _looks_technical(self, text: str) -> bool:
        normalized = normalize_text(text)
        return any(term in normalized for term in TECHNICAL_TERMS)

    def _frame_is_technical(self, frame: Any) -> bool:
        # Coi frame technical nếu user request/evidence/salience có dấu hiệu code/architecture.
        texts: list[str] = []
        salience = safe_get(frame, "salience", None)
        texts.append(str(safe_get(salience, "dominant_focus", "") or ""))
        for ev in safe_iter(safe_get(frame, "evidence", []))[:12]:
            texts.append(str(safe_get(ev, "claim", "") or ""))
            texts.extend(str(t) for t in safe_iter(safe_get(ev, "tags", [])))
        joined = normalize_text(" ".join(texts))
        return self._looks_technical(joined)

    def _decay_for_kind(self, kind: WorkingMemorySlotKind) -> float:
        if kind == "current_user_request":
            return self.config.current_request_decay_seconds
        if kind == "active_technical_goal":
            return self.config.goal_decay_seconds
        if kind == "relevant_memory":
            return self.config.memory_decay_seconds
        if kind == "relational_state":
            return self.config.relation_decay_seconds
        if kind == "affect_homeostasis":
            return self.config.affect_decay_seconds
        if kind in {"action_constraint", "risk_or_repair"}:
            return self.config.action_decay_seconds
        return self.config.evidence_decay_seconds


# ---------------------------------------------------------------------------
# API tiện dụng cho coordinator.
# ---------------------------------------------------------------------------


def select_working_memory(
    frame: Any,
    *,
    config: Optional[WorkingMemoryConfig] = None,
    extra_candidates: Optional[Iterable[WorkingMemoryCandidate | dict[str, Any]]] = None,
) -> WorkingMemoryFrame:
    """Hàm tiện dụng để không cần tự khởi tạo engine trong code thử nghiệm."""

    return WorkingMemoryEngine(config=config).select(frame, extra_candidates=extra_candidates)


__all__ = [
    "WorkingMemorySlot",
    "SuppressedMemoryItem",
    "WorkingMemoryFrame",
    "WorkingMemoryCandidate",
    "WorkingMemoryConfig",
    "WorkingMemoryEngine",
    "select_working_memory",
]
