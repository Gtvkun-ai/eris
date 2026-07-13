# -*- coding: utf-8 -*-
"""
core/cognitive_frame.py

Khung nhận thức trung tâm cho ERIS Cognitive Pipeline.

File này là "xương sống runtime" của Phase 0:
- Mọi dữ liệu đi vào runtime phải được đóng gói thành RawSignal.
- Mọi claim dùng để suy luận phải đi qua EvidenceItem.
- Mọi module chỉ đọc CognitiveFrame và ghi ModuleReport vào CognitiveFrame.
- Không module nào được gọi chéo sang module khác để lấy "sự thật" riêng.

Nói ngắn gọn: CognitiveFrame là cái bàn mổ chung.
Attention, Meaning, ToM, Memory, Speech, Body... đều nhìn vào frame.
Không ai được chui cửa sau sang memory.py, telemetry.py hay attention.py để tự bói.
Đó là cách repo biến thành spaghetti telepathy, một thảm họa có cú pháp Python.

Gợi ý vị trí:
    src/core/cognitive_frame.py
hoặc:
    src/cortex/cognitive_frame.py

File này cố ý ít phụ thuộc:
- Nếu dự án đã có evidence.py thì nó sẽ import RawSignal/EvidenceItem/ModuleReport.
- Nếu chưa có, nó vẫn chạy được nhờ type fallback Any.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable, Iterable, Literal, Optional


# =============================================================================
# 1. Import mềm từ evidence.py
# =============================================================================
#
# Khi nối thật vào repo, nên thống nhất:
#     from core.evidence import RawSignal, EvidenceItem, ModuleReport, ...
#
try:  # package cùng thư mục: core/cognitive_frame.py + core/evidence.py
    from .evidence import (  # type: ignore
        DebugTrace,
        EvidenceItem,
        ModuleReport,
        RawSignal,
        StateCommitRequest,
    )
except Exception:  # pragma: no cover - fallback cho giai đoạn ráp file
    RawSignal = Any  # type: ignore
    EvidenceItem = Any  # type: ignore
    ModuleReport = Any  # type: ignore
    StateCommitRequest = Any  # type: ignore
    DebugTrace = Any  # type: ignore


# =============================================================================
# 2. Literal contracts
# =============================================================================

FrameBudgetMode = Literal["fast", "normal", "deep", "reflection"]

FrameStatus = Literal[
    "created",        # frame vừa được tạo
    "normalizing",    # đang chuyển RawSignal -> EvidenceItem
    "selecting",      # attention / working memory / workspace đang chọn tín hiệu
    "interpreting",   # scene / culture / meaning / ToM đang diễn giải
    "planning",       # value / arbitration / agency / speech / body đang chọn hành động
    "wording",        # LLM wording đang chạy
    "guarding",       # grounding / parser / Ti guard đang kiểm tra
    "executing",      # speech/body/system/memory commit đang chạy
    "observing",      # outcome/self-observation đang ghi nhận
    "closed",         # frame hoàn tất
    "failed",         # frame lỗi, nhưng vẫn giữ debug để mổ xác
]

FrameChannel = Literal[
    "autonomous",
    "chat",
    "force_speak",
    "session_start",
    "reflection",
    "system",
    "test",
    "unknown",
]

# Các slot chính trong CognitiveFrame, bám theo PDF Grand Architecture.
# Value của mỗi slot để Any vì module phía sau sẽ định nghĩa dataclass riêng:
# SalienceFrame, TemporalFrame, SpatialFrame, MeaningReport, ...
FrameSlotName = Literal[
    "salience",
    "temporal",
    "spatial",
    "homeostasis",
    "affect",
    "working_memory",
    "workspace",
    "world_scene",
    "interpretation",
    "sociocultural",
    "meaning",
    "tom",
    "epistemic",
    "inquiry",
    "belief",
    "memory_packet",
    "value_resolution",
    "simulations",
    "arbitration",
    "agency",
    "relation",
    "permission",
    "noise",
    "speech_opportunity",
    "speech_plan",
    "body_plan",
    "modality",
    "wording",
    "grounding",
    "execution",
    "outcome",
    "self_observation",
]


# Thứ tự pipeline dùng để kiểm tra module có ghi quá sớm/quá muộn không.
# Đây không phải luật tuyệt đối, nhưng đủ để bắt lỗi kiến trúc ngu ngốc kiểu:
# speech_core chạy trước evidence_normalizer.
PIPELINE_ORDER: tuple[str, ...] = (
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
)


# =============================================================================
# 3. Helper functions
# =============================================================================

def now_ts() -> float:
    """Trả timestamp hiện tại.

    Tách ra thành hàm để test có thể monkeypatch nếu cần.
    """
    return time.time()


def new_frame_id(prefix: str = "frame") -> str:
    """Sinh id cho frame.

    Dùng uuid ngắn để log dễ đọc hơn.
    """
    return f"{prefix}_{int(now_ts() * 1000)}_{uuid.uuid4().hex[:8]}"


def _safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Lấy attribute hoặc key dict một cách an toàn."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _object_id(obj: Any) -> Optional[str]:
    """Lấy id từ dataclass/dict/object.

    EvidenceItem, RawSignal, ModuleReport đều nên có field id/evidence id riêng.
    Nhưng trong giai đoạn ráp hệ thống, có thể object vẫn là dict.
    """
    return _safe_get_attr(obj, "id", None)


def _to_plain(value: Any) -> Any:
    """Chuyển object thành dạng JSON-friendly.

    Không dùng jsonpickle hay thư viện ngoài. Phase 0 nên nhẹ, sạch, không kéo
    dependency chỉ để serialize vài dict. Nhân loại đã đủ đau khổ vì dependency.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if is_dataclass(value):
        return _to_plain(asdict(value))

    # Với object lạ, chỉ xuất repr để debug, không cố serialize sâu.
    return repr(value)


def _shorten(text: Any, max_len: int = 240) -> str:
    """Rút gọn text để debug không biến log thành tiểu thuyết."""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _clamp01(value: float) -> float:
    """Ép số về [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


def _module_order_index(module_name: str) -> int:
    """Trả index pipeline của module. Module chưa biết được đẩy xuống cuối."""
    try:
        return PIPELINE_ORDER.index(module_name)
    except ValueError:
        return len(PIPELINE_ORDER)


# =============================================================================
# 4. Frame mutation / audit records
# =============================================================================

@dataclass(slots=True)
class FrameMutation:
    """Một lần thay đổi frame.

    CognitiveFrame không nên bị chỉnh âm thầm.
    Mỗi lần module ghi slot/report/warning/commit request, ta để lại một vết.
    Debug sau này sẽ bớt giống khảo cổ học trong bãi rác.
    """

    timestamp: float
    actor: str
    action: str
    target: str
    summary: str
    evidence_used: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FrameValidationIssue:
    """Một vấn đề phát hiện khi validate frame."""

    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    target: Optional[str] = None


@dataclass(slots=True)
class FramePromptPacket:
    """Gói context an toàn để đưa vào prompt.

    Không bao giờ nhét nguyên CognitiveFrame vào prompt.
    PDF đã nói rõ: LLM chỉ nên nhận selected workspace context, memory trong budget,
    speech plan, forbidden assumptions, permission limits, style pressure và format.
    Nhét toàn bộ frame vào prompt là biến câu trả lời thành đám tang token.
    """

    frame_id: str
    channel: FrameChannel
    budget_mode: FrameBudgetMode
    selected_evidence: list[dict[str, Any]]
    selected_memory: list[Any]
    selected_goal: Optional[Any]
    selected_risk: Optional[Any]
    speech_plan: Optional[Any]
    permission: Optional[Any]
    modality: Optional[Any]
    constraints: list[str]
    debug_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


# =============================================================================
# 5. CognitiveFrame
# =============================================================================

@dataclass
class CognitiveFrame:
    """Khung nhận thức đầy đủ cho một chu kỳ runtime.

    Vai trò:
    - Chứa raw_signals và evidence.
    - Chứa slot kết quả của từng tầng pipeline.
    - Chứa ModuleReport của từng module.
    - Chứa commit request để state/memory ghi sau, không cho module ghi trực tiếp.
    - Chứa debug/audit trail để biết vì sao ERIS nói/im/hỏi/nhớ/quên.

    Quy tắc kiến trúc:
    1. Module đọc CognitiveFrame.
    2. Module không tự gọi module khác để lấy context.
    3. Module trả ModuleReport.
    4. Runtime gắn ModuleReport vào frame.
    5. StateCommitter đọc commit_requests sau cùng rồi mới ghi memory/state.
    """

    # -------------------------------------------------------------------------
    # Metadata nền
    # -------------------------------------------------------------------------
    frame_id: str
    timestamp: float
    budget_mode: FrameBudgetMode = "normal"
    channel: FrameChannel = "unknown"
    status: FrameStatus = "created"

    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    parent_frame_id: Optional[str] = None
    cycle_index: int = 0

    # Dùng cho chat/debug nhanh. Không phải source of truth.
    # Source of truth vẫn là RawSignal/EvidenceItem.
    user_text: Optional[str] = None

    # -------------------------------------------------------------------------
    # Phase 0: raw input và evidence
    # -------------------------------------------------------------------------
    raw_signals: list[RawSignal] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)

    # -------------------------------------------------------------------------
    # Các slot pipeline chính theo PDF
    # -------------------------------------------------------------------------
    salience: Optional[Any] = None
    temporal: Optional[Any] = None
    spatial: Optional[Any] = None
    homeostasis: Optional[Any] = None
    affect: Optional[Any] = None
    working_memory: Optional[Any] = None
    workspace: Optional[Any] = None
    world_scene: Optional[Any] = None
    interpretation: Optional[Any] = None
    sociocultural: Optional[Any] = None
    meaning: Optional[Any] = None
    tom: Optional[Any] = None
    epistemic: Optional[Any] = None
    inquiry: Optional[Any] = None
    belief: Optional[Any] = None
    memory_packet: Optional[Any] = None
    value_resolution: Optional[Any] = None
    simulations: list[Any] = field(default_factory=list)
    arbitration: Optional[Any] = None
    agency: Optional[Any] = None
    relation: Optional[Any] = None
    permission: Optional[Any] = None
    noise: Optional[Any] = None
    speech_opportunity: Optional[Any] = None
    speech_plan: Optional[Any] = None
    body_plan: Optional[Any] = None
    modality: Optional[Any] = None
    wording: Optional[Any] = None
    grounding: Optional[Any] = None
    execution: Optional[Any] = None
    outcome: Optional[Any] = None
    self_observation: Optional[Any] = None

    # -------------------------------------------------------------------------
    # Reports / commit / debug
    # -------------------------------------------------------------------------
    module_reports: dict[str, ModuleReport] = field(default_factory=dict)
    commit_requests: list[StateCommitRequest] = field(default_factory=list)
    debug_trace: Optional[DebugTrace] = None

    debug_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mutations: list[FrameMutation] = field(default_factory=list)

    # Bag phụ cho runtime. Không dùng nó để lén truyền truth giữa module.
    metadata: dict[str, Any] = field(default_factory=dict)

    # -------------------------------------------------------------------------
    # Constructors
    # -------------------------------------------------------------------------
    @classmethod
    def start(
        cls,
        raw_signals: Optional[list[RawSignal]] = None,
        *,
        budget_mode: FrameBudgetMode = "normal",
        channel: FrameChannel = "unknown",
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        parent_frame_id: Optional[str] = None,
        cycle_index: int = 0,
        user_text: Optional[str] = None,
        timestamp: Optional[float] = None,
        frame_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "CognitiveFrame":
        """Tạo frame mới.

        Dùng method này thay vì gọi constructor trực tiếp để:
        - tự sinh frame_id
        - tự timestamp
        - ghi mutation đầu tiên
        """
        frame = cls(
            frame_id=frame_id or new_frame_id(),
            timestamp=timestamp if timestamp is not None else now_ts(),
            budget_mode=budget_mode,
            channel=channel,
            session_id=session_id,
            turn_id=turn_id,
            parent_frame_id=parent_frame_id,
            cycle_index=cycle_index,
            user_text=user_text,
            raw_signals=list(raw_signals or []),
            metadata=dict(metadata or {}),
        )
        frame._record_mutation(
            actor="cognitive_frame",
            action="start",
            target="frame",
            summary=f"Created frame channel={channel}, budget={budget_mode}",
        )
        return frame

    # -------------------------------------------------------------------------
    # Basic status/lifecycle
    # -------------------------------------------------------------------------
    def set_status(self, status: FrameStatus, *, actor: str = "runtime") -> None:
        """Đổi trạng thái frame và ghi audit."""
        old = self.status
        self.status = status
        self._record_mutation(
            actor=actor,
            action="set_status",
            target="status",
            summary=f"{old} -> {status}",
        )

    def close(self, *, actor: str = "runtime") -> None:
        """Đóng frame khi cycle hoàn tất."""
        self.set_status("closed", actor=actor)

    def fail(self, reason: str, *, actor: str = "runtime") -> None:
        """Đánh dấu frame lỗi nhưng vẫn giữ state để debug."""
        self.status = "failed"
        self.add_warning(f"Frame failed: {reason}", actor=actor)
        self._record_mutation(
            actor=actor,
            action="fail",
            target="frame",
            summary=reason,
        )

    # -------------------------------------------------------------------------
    # RawSignal / Evidence
    # -------------------------------------------------------------------------
    def add_raw_signal(self, signal: RawSignal, *, actor: str = "raw_signal_collector") -> None:
        """Thêm một RawSignal vào frame."""
        self.raw_signals.append(signal)
        self._record_mutation(
            actor=actor,
            action="add_raw_signal",
            target=str(_object_id(signal) or "raw_signal"),
            summary=_shorten(_safe_get_attr(signal, "source", "unknown")),
        )

    def add_raw_signals(
        self,
        signals: Iterable[RawSignal],
        *,
        actor: str = "raw_signal_collector",
    ) -> None:
        """Thêm nhiều RawSignal."""
        for signal in signals:
            self.add_raw_signal(signal, actor=actor)

    def add_evidence(
        self,
        item: EvidenceItem,
        *,
        actor: str = "evidence_normalizer",
    ) -> None:
        """Thêm EvidenceItem vào frame.

        Đây là điểm chuyển từ "dữ liệu thô" sang "claim có confidence".
        Module phía sau phải dùng evidence, không dùng raw_signals trừ khi nó là
        module normalize/evidence audit.
        """
        self.evidence.append(item)
        self._record_mutation(
            actor=actor,
            action="add_evidence",
            target=str(_object_id(item) or "evidence"),
            summary=_shorten(_safe_get_attr(item, "claim", item)),
            confidence=_safe_get_attr(item, "confidence", None),
        )

    def add_evidence_items(
        self,
        items: Iterable[EvidenceItem],
        *,
        actor: str = "evidence_normalizer",
    ) -> None:
        """Thêm nhiều EvidenceItem."""
        for item in items:
            self.add_evidence(item, actor=actor)

    def evidence_ids(self) -> set[str]:
        """Tập id evidence hiện có."""
        return {str(eid) for eid in (_object_id(ev) for ev in self.evidence) if eid}

    def raw_signal_ids(self) -> set[str]:
        """Tập id raw signal hiện có."""
        return {str(sid) for sid in (_object_id(sig) for sig in self.raw_signals) if sid}

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceItem]:
        """Lấy evidence theo id."""
        for item in self.evidence:
            if _object_id(item) == evidence_id:
                return item
        return None

    def get_evidence_many(self, evidence_ids: Iterable[str]) -> list[EvidenceItem]:
        """Lấy nhiều evidence theo id, bỏ qua id không tồn tại."""
        ids = set(evidence_ids)
        return [ev for ev in self.evidence if _object_id(ev) in ids]

    def find_evidence(
        self,
        predicate: Callable[[EvidenceItem], bool],
        *,
        limit: Optional[int] = None,
    ) -> list[EvidenceItem]:
        """Tìm evidence theo predicate.

        Ví dụ:
            frame.find_evidence(lambda ev: ev.raw_or_inferred == "inferred")
        """
        out: list[EvidenceItem] = []
        for item in self.evidence:
            if predicate(item):
                out.append(item)
                if limit is not None and len(out) >= limit:
                    break
        return out

    def evidence_by_tag(self, tag: str) -> list[EvidenceItem]:
        """Lấy evidence có tag."""
        result: list[EvidenceItem] = []
        for item in self.evidence:
            tags = _safe_get_attr(item, "tags", []) or []
            if tag in tags:
                result.append(item)
        return result

    def strongest_evidence(
        self,
        *,
        limit: int = 5,
        min_confidence: float = 0.0,
    ) -> list[EvidenceItem]:
        """Lấy evidence mạnh nhất theo confidence * reliability."""
        def score(item: EvidenceItem) -> float:
            confidence = float(_safe_get_attr(item, "confidence", 0.0) or 0.0)
            reliability = float(_safe_get_attr(item, "reliability", 1.0) or 1.0)
            return confidence * reliability

        candidates = [
            ev for ev in self.evidence
            if float(_safe_get_attr(ev, "confidence", 0.0) or 0.0) >= min_confidence
        ]
        return sorted(candidates, key=score, reverse=True)[:limit]

    # -------------------------------------------------------------------------
    # Slot handling
    # -------------------------------------------------------------------------
    def set_slot(
        self,
        slot_name: FrameSlotName,
        value: Any,
        *,
        actor: str,
        evidence_used: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        overwrite: bool = True,
    ) -> None:
        """Ghi kết quả vào một slot pipeline.

        Chỉ runtime/module wrapper nên gọi hàm này.
        Module thuần nên trả ModuleReport, sau đó coordinator gắn vào frame.
        """
        if not hasattr(self, slot_name):
            raise AttributeError(f"CognitiveFrame không có slot: {slot_name}")

        if getattr(self, slot_name) is not None and not overwrite:
            self.add_warning(
                f"Slot '{slot_name}' already has value; write skipped.",
                actor=actor,
            )
            return

        setattr(self, slot_name, value)
        self._record_mutation(
            actor=actor,
            action="set_slot",
            target=slot_name,
            summary=_shorten(value),
            evidence_used=list(evidence_used or []),
            confidence=confidence,
        )

    def append_slot_list(
        self,
        slot_name: FrameSlotName,
        value: Any,
        *,
        actor: str,
        evidence_used: Optional[list[str]] = None,
        confidence: Optional[float] = None,
    ) -> None:
        """Append vào slot dạng list.

        Hiện dùng chủ yếu cho `simulations`.
        """
        if not hasattr(self, slot_name):
            raise AttributeError(f"CognitiveFrame không có slot: {slot_name}")

        current = getattr(self, slot_name)
        if current is None:
            current = []
            setattr(self, slot_name, current)

        if not isinstance(current, list):
            raise TypeError(f"Slot '{slot_name}' không phải list.")

        current.append(value)
        self._record_mutation(
            actor=actor,
            action="append_slot_list",
            target=slot_name,
            summary=_shorten(value),
            evidence_used=list(evidence_used or []),
            confidence=confidence,
        )

    def get_slot(self, slot_name: FrameSlotName) -> Any:
        """Đọc slot theo tên."""
        if not hasattr(self, slot_name):
            raise AttributeError(f"CognitiveFrame không có slot: {slot_name}")
        return getattr(self, slot_name)

    def slot_is_ready(self, slot_name: FrameSlotName) -> bool:
        """Kiểm tra slot đã có dữ liệu chưa."""
        return self.get_slot(slot_name) is not None

    # -------------------------------------------------------------------------
    # ModuleReport handling
    # -------------------------------------------------------------------------
    def add_report(
        self,
        report: ModuleReport,
        *,
        slot_name: Optional[FrameSlotName] = None,
        actor: Optional[str] = None,
        overwrite: bool = True,
    ) -> None:
        """Gắn ModuleReport vào frame.

        Nếu slot_name được truyền:
        - lấy report.result gắn vào slot tương ứng.
        - report vẫn được lưu trong module_reports.

        Đây là entrypoint chính để module ghi kết quả.
        """
        module_name = str(_safe_get_attr(report, "module_name", actor or "unknown_module"))

        if module_name in self.module_reports and not overwrite:
            self.add_warning(
                f"ModuleReport '{module_name}' already exists; report skipped.",
                actor=actor or module_name,
            )
            return

        self.module_reports[module_name] = report

        evidence_used = list(_safe_get_attr(report, "evidence_used", []) or [])
        confidence = _safe_get_attr(report, "confidence", None)
        warnings = list(_safe_get_attr(report, "warnings", []) or [])

        for warning in warnings:
            self.add_warning(f"{module_name}: {warning}", actor=module_name)

        self._record_mutation(
            actor=actor or module_name,
            action="add_report",
            target=module_name,
            summary=_shorten(_safe_get_attr(report, "result", report)),
            evidence_used=evidence_used,
            confidence=confidence,
            warnings=warnings,
        )

        if slot_name is not None:
            result = _safe_get_attr(report, "result", None)
            self.set_slot(
                slot_name,
                result,
                actor=module_name,
                evidence_used=evidence_used,
                confidence=confidence,
                overwrite=overwrite,
            )

    def get_report(self, module_name: str) -> Optional[ModuleReport]:
        """Lấy report của module."""
        return self.module_reports.get(module_name)

    def require_report(self, module_name: str) -> ModuleReport:
        """Lấy report bắt buộc, thiếu thì raise.

        Dùng trong coordinator/test để bắt pipeline thiếu module.
        """
        report = self.get_report(module_name)
        if report is None:
            raise KeyError(f"Missing ModuleReport: {module_name}")
        return report

    def report_order(self) -> list[str]:
        """Danh sách module đã report theo thứ tự pipeline tương đối."""
        return sorted(self.module_reports.keys(), key=_module_order_index)

    # -------------------------------------------------------------------------
    # Commit requests
    # -------------------------------------------------------------------------
    def add_commit_request(
        self,
        request: StateCommitRequest,
        *,
        actor: str = "runtime",
    ) -> None:
        """Thêm yêu cầu ghi state/memory.

        Module không được ghi thẳng vào memory.
        Module chỉ được đề xuất StateCommitRequest.
        StateCommitter đọc request sau cùng và quyết định ghi hay bỏ.
        """
        self.commit_requests.append(request)
        evidence_used = list(_safe_get_attr(request, "evidence_ids", []) or [])
        confidence = _safe_get_attr(request, "confidence", None)
        target = _safe_get_attr(request, "target", "unknown_target")
        content = _safe_get_attr(request, "content", request)

        self._record_mutation(
            actor=actor,
            action="add_commit_request",
            target=str(target),
            summary=_shorten(content),
            evidence_used=evidence_used,
            confidence=confidence,
        )

    def commit_requests_for(self, target: str) -> list[StateCommitRequest]:
        """Lấy commit request theo target."""
        return [
            req for req in self.commit_requests
            if _safe_get_attr(req, "target", None) == target
        ]

    # -------------------------------------------------------------------------
    # Debug / warnings
    # -------------------------------------------------------------------------
    def add_debug_note(self, note: str, *, actor: str = "runtime") -> None:
        """Thêm ghi chú debug."""
        self.debug_notes.append(note)
        self._record_mutation(
            actor=actor,
            action="add_debug_note",
            target="debug_notes",
            summary=note,
        )

    def add_warning(self, warning: str, *, actor: str = "runtime") -> None:
        """Thêm warning."""
        self.warnings.append(warning)
        self._record_mutation(
            actor=actor,
            action="add_warning",
            target="warnings",
            summary=warning,
            warnings=[warning],
        )

    def _record_mutation(
        self,
        *,
        actor: str,
        action: str,
        target: str,
        summary: str,
        evidence_used: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        warnings: Optional[list[str]] = None,
    ) -> None:
        """Ghi audit record cho thay đổi frame."""
        conf = None if confidence is None else _clamp01(float(confidence))
        self.mutations.append(
            FrameMutation(
                timestamp=now_ts(),
                actor=actor,
                action=action,
                target=target,
                summary=_shorten(summary),
                evidence_used=list(evidence_used or []),
                confidence=conf,
                warnings=list(warnings or []),
            )
        )

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------
    def validate(self, *, strict: bool = False) -> list[FrameValidationIssue]:
        """Kiểm tra tính nhất quán của frame.

        strict=False:
            chỉ cảnh báo lỗi thường gặp.

        strict=True:
            lỗi thiếu evidence/report sẽ bị đánh severity error mạnh hơn.

        Hàm này không sửa frame. Nó chỉ báo bệnh.
        Đừng để validator vừa chẩn đoán vừa phẫu thuật. Đó là y học của bug.
        """
        issues: list[FrameValidationIssue] = []

        if not self.frame_id:
            issues.append(FrameValidationIssue("error", "missing_frame_id", "Frame thiếu frame_id."))

        if self.timestamp <= 0:
            issues.append(FrameValidationIssue("error", "invalid_timestamp", "Frame timestamp không hợp lệ."))

        if self.budget_mode not in ("fast", "normal", "deep", "reflection"):
            issues.append(FrameValidationIssue("error", "invalid_budget", f"budget_mode lạ: {self.budget_mode}"))

        if self.channel not in (
            "autonomous",
            "chat",
            "force_speak",
            "session_start",
            "reflection",
            "system",
            "test",
            "unknown",
        ):
            issues.append(FrameValidationIssue("error", "invalid_channel", f"channel lạ: {self.channel}"))

        raw_ids = self.raw_signal_ids()
        evidence_ids = self.evidence_ids()

        if not self.raw_signals:
            issues.append(
                FrameValidationIssue(
                    "warning" if not strict else "error",
                    "no_raw_signals",
                    "Frame không có raw_signals. Có thể hợp lệ trong test, nhưng runtime thật thì đáng nghi.",
                )
            )

        if not self.evidence:
            issues.append(
                FrameValidationIssue(
                    "warning" if not strict else "error",
                    "no_evidence",
                    "Frame không có evidence. Module phía sau không nên suy luận từ không khí.",
                )
            )

        # Evidence trỏ về RawSignal không tồn tại.
        for item in self.evidence:
            ev_id = _object_id(item) or "unknown_evidence"
            source_signal_id = _safe_get_attr(item, "source_signal_id", None)
            if source_signal_id and raw_ids and source_signal_id not in raw_ids:
                issues.append(
                    FrameValidationIssue(
                        "warning",
                        "evidence_source_missing",
                        f"Evidence '{ev_id}' trỏ tới raw signal không có trong frame: {source_signal_id}",
                        target=str(ev_id),
                    )
                )

            confidence = _safe_get_attr(item, "confidence", None)
            if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
                issues.append(
                    FrameValidationIssue(
                        "error",
                        "evidence_confidence_out_of_range",
                        f"Evidence '{ev_id}' có confidence ngoài [0,1]: {confidence}",
                        target=str(ev_id),
                    )
                )

        # ModuleReport dùng evidence id không tồn tại.
        for module_name, report in self.module_reports.items():
            evidence_used = list(_safe_get_attr(report, "evidence_used", []) or [])
            for evidence_id in evidence_used:
                if evidence_ids and evidence_id not in evidence_ids:
                    issues.append(
                        FrameValidationIssue(
                            "warning" if not strict else "error",
                            "report_uses_missing_evidence",
                            f"Report '{module_name}' dùng evidence không tồn tại: {evidence_id}",
                            target=module_name,
                        )
                    )

            confidence = _safe_get_attr(report, "confidence", None)
            if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
                issues.append(
                    FrameValidationIssue(
                        "error",
                        "report_confidence_out_of_range",
                        f"Report '{module_name}' có confidence ngoài [0,1]: {confidence}",
                        target=module_name,
                    )
                )

        # CommitRequest dùng evidence id không tồn tại.
        for req in self.commit_requests:
            target = _safe_get_attr(req, "target", "unknown")
            for evidence_id in list(_safe_get_attr(req, "evidence_ids", []) or []):
                if evidence_ids and evidence_id not in evidence_ids:
                    issues.append(
                        FrameValidationIssue(
                            "warning" if not strict else "error",
                            "commit_uses_missing_evidence",
                            f"CommitRequest '{target}' dùng evidence không tồn tại: {evidence_id}",
                            target=str(target),
                        )
                    )

        # Check pipeline order mềm: nếu module sớm xuất hiện sau module muộn thì warning.
        ordered_names = self.report_order()
        actual_names = list(self.module_reports.keys())
        if ordered_names != actual_names:
            issues.append(
                FrameValidationIssue(
                    "info",
                    "report_order_noncanonical",
                    "ModuleReport không theo thứ tự canonical. Có thể hợp lệ, nhưng nên kiểm tra coordinator.",
                )
            )

        return issues

    def raise_if_invalid(self, *, strict: bool = True) -> None:
        """Raise ValueError nếu validate có error."""
        issues = self.validate(strict=strict)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            message = "; ".join(f"{e.code}: {e.message}" for e in errors)
            raise ValueError(message)

    # -------------------------------------------------------------------------
    # Prompt packet / selected context
    # -------------------------------------------------------------------------
    def build_prompt_packet(
        self,
        *,
        max_evidence: int = 8,
        min_evidence_confidence: float = 0.35,
        include_debug: bool = False,
    ) -> FramePromptPacket:
        """Tạo gói context an toàn để đưa vào LLM.

        Không đưa raw_signals toàn bộ vào prompt.
        Không đưa module_reports toàn bộ vào prompt.
        Không đưa hidden state lung tung vào prompt.

        Chỉ đưa phần đã được chọn hoặc evidence mạnh.
        """
        selected_evidence = [
            self._evidence_to_prompt_dict(ev)
            for ev in self.strongest_evidence(
                limit=max_evidence,
                min_confidence=min_evidence_confidence,
            )
        ]

        selected_memory = []
        if self.memory_packet is not None:
            selected_memory = self._extract_memory_for_prompt(self.memory_packet)

        selected_goal = self._extract_selected_goal()

        selected_risk = None
        if self.grounding is not None:
            selected_risk = self.grounding
        elif self.permission is not None:
            selected_risk = self.permission

        constraints = self._collect_prompt_constraints()

        debug_summary = self.debug_summary() if include_debug else {}

        return FramePromptPacket(
            frame_id=self.frame_id,
            channel=self.channel,
            budget_mode=self.budget_mode,
            selected_evidence=selected_evidence,
            selected_memory=selected_memory,
            selected_goal=selected_goal,
            selected_risk=selected_risk,
            speech_plan=self.speech_plan,
            permission=self.permission,
            modality=self.modality,
            constraints=constraints,
            debug_summary=debug_summary,
        )

    def _evidence_to_prompt_dict(self, item: EvidenceItem) -> dict[str, Any]:
        """Rút EvidenceItem thành dict nhỏ cho prompt."""
        return {
            "id": _object_id(item),
            "source": _safe_get_attr(item, "source", None),
            "claim": _safe_get_attr(item, "claim", None),
            "confidence": _safe_get_attr(item, "confidence", None),
            "reliability": _safe_get_attr(item, "reliability", None),
            "raw_or_inferred": _safe_get_attr(item, "raw_or_inferred", None),
            "privacy_level": _safe_get_attr(item, "privacy_level", None),
            "tags": list(_safe_get_attr(item, "tags", []) or []),
        }

    def _extract_memory_for_prompt(self, memory_packet: Any) -> list[Any]:
        """Rút memory packet cho prompt.

        Chỉ lấy các field thường dùng. Nếu MemoryPacket sau này có method riêng,
        thay logic ở đây.
        """
        out: list[Any] = []
        for field_name in (
            "episodic",
            "semantic",
            "relational",
            "affective_residue",
            "procedural",
            "temporal",
            "spatial",
            "worldview",
        ):
            value = _safe_get_attr(memory_packet, field_name, None)
            if value:
                if isinstance(value, list):
                    out.extend(value[:4])
                else:
                    out.append(value)
        return out[:12]

    def _extract_selected_goal(self) -> Optional[Any]:
        """Lấy goal đang được chọn nếu có."""
        if self.workspace is not None:
            selected_goal = _safe_get_attr(self.workspace, "selected_goal", None)
            if selected_goal is not None:
                return selected_goal

        if self.memory_packet is not None:
            selected_goal = _safe_get_attr(self.memory_packet, "selected_goal", None)
            if selected_goal is not None:
                return selected_goal

        return None

    def _collect_prompt_constraints(self) -> list[str]:
        """Gom constraint ngắn cho prompt."""
        constraints: list[str] = []

        if self.permission is not None:
            max_intensity = _safe_get_attr(self.permission, "max_intensity", None)
            if max_intensity is not None:
                constraints.append(f"max_intensity={max_intensity}")

            if _safe_get_attr(self.permission, "allowed_search", None) is False:
                constraints.append("do_not_search")

            if _safe_get_attr(self.permission, "allowed_proactivity", None) is False:
                constraints.append("avoid_proactive_interruption")

        if self.grounding is not None:
            unsupported = _safe_get_attr(self.grounding, "unsupported_claims", None)
            if unsupported:
                constraints.append("avoid_unsupported_claims")

        if self.speech_plan is not None:
            must_avoid = _safe_get_attr(self.speech_plan, "must_avoid", None)
            if must_avoid:
                constraints.extend([f"avoid:{x}" for x in list(must_avoid)[:8]])

        return constraints[:16]

    # -------------------------------------------------------------------------
    # Debug summary / serialization
    # -------------------------------------------------------------------------
    def debug_summary(self) -> dict[str, Any]:
        """Tạo summary nhỏ để log/debug."""
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "budget_mode": self.budget_mode,
            "channel": self.channel,
            "raw_signal_count": len(self.raw_signals),
            "evidence_count": len(self.evidence),
            "reports": list(self.module_reports.keys()),
            "commit_request_count": len(self.commit_requests),
            "warnings": list(self.warnings[-8:]),
            "debug_notes": list(self.debug_notes[-8:]),
            "filled_slots": self.filled_slots(),
            "dominant_focus": self._debug_dominant_focus(),
            "last_mutations": [_to_plain(m) for m in self.mutations[-8:]],
        }

    def filled_slots(self) -> list[str]:
        """Danh sách slot pipeline đã có dữ liệu."""
        slots: list[str] = []
        for slot in FrameSlotName.__args__:  # type: ignore[attr-defined]
            value = getattr(self, slot)
            if value is not None and value != []:
                slots.append(slot)
        return slots

    def _debug_dominant_focus(self) -> Optional[Any]:
        """Lấy dominant focus từ salience/workspace nếu có."""
        if self.salience is not None:
            focus = _safe_get_attr(self.salience, "dominant_focus", None)
            if focus is not None:
                return focus

        if self.workspace is not None:
            thread = _safe_get_attr(self.workspace, "dominant_thread", None)
            if thread is not None:
                return thread

        if self.user_text:
            return _shorten(self.user_text, 80)

        return None

    def to_dict(self, *, include_mutations: bool = True) -> dict[str, Any]:
        """Serialize frame thành dict JSON-friendly.

        Cảnh báo: đây là debug serialization, không phải prompt packet.
        Đưa output này vào LLM là hành vi thiếu tự trọng kiến trúc.
        """
        data = {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "budget_mode": self.budget_mode,
            "channel": self.channel,
            "status": self.status,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "parent_frame_id": self.parent_frame_id,
            "cycle_index": self.cycle_index,
            "user_text": self.user_text,
            "raw_signals": _to_plain(self.raw_signals),
            "evidence": _to_plain(self.evidence),
            "slots": {
                "salience": _to_plain(self.salience),
                "temporal": _to_plain(self.temporal),
                "spatial": _to_plain(self.spatial),
                "homeostasis": _to_plain(self.homeostasis),
                "affect": _to_plain(self.affect),
                "working_memory": _to_plain(self.working_memory),
                "workspace": _to_plain(self.workspace),
                "world_scene": _to_plain(self.world_scene),
                "interpretation": _to_plain(self.interpretation),
                "sociocultural": _to_plain(self.sociocultural),
                "meaning": _to_plain(self.meaning),
                "tom": _to_plain(self.tom),
                "epistemic": _to_plain(self.epistemic),
                "inquiry": _to_plain(self.inquiry),
                "belief": _to_plain(self.belief),
                "memory_packet": _to_plain(self.memory_packet),
                "value_resolution": _to_plain(self.value_resolution),
                "simulations": _to_plain(self.simulations),
                "arbitration": _to_plain(self.arbitration),
                "agency": _to_plain(self.agency),
                "relation": _to_plain(self.relation),
                "permission": _to_plain(self.permission),
                "noise": _to_plain(self.noise),
                "speech_opportunity": _to_plain(self.speech_opportunity),
                "speech_plan": _to_plain(self.speech_plan),
                "body_plan": _to_plain(self.body_plan),
                "modality": _to_plain(self.modality),
                "wording": _to_plain(self.wording),
                "grounding": _to_plain(self.grounding),
                "execution": _to_plain(self.execution),
                "outcome": _to_plain(self.outcome),
                "self_observation": _to_plain(self.self_observation),
            },
            "module_reports": _to_plain(self.module_reports),
            "commit_requests": _to_plain(self.commit_requests),
            "debug_trace": _to_plain(self.debug_trace),
            "debug_notes": list(self.debug_notes),
            "warnings": list(self.warnings),
            "metadata": _to_plain(self.metadata),
        }

        if include_mutations:
            data["mutations"] = _to_plain(self.mutations)

        return data

    def to_json(self, *, indent: Optional[int] = 2, include_mutations: bool = True) -> str:
        """Serialize frame thành JSON string."""
        return json.dumps(
            self.to_dict(include_mutations=include_mutations),
            ensure_ascii=False,
            indent=indent,
        )

    def clone_shallow(self, *, new_id: bool = False) -> "CognitiveFrame":
        """Clone nông.

        Dùng cho test hoặc branch simulation nhẹ.
        Không nên dùng để chạy pipeline song song phức tạp.
        """
        cloned = copy.copy(self)
        if new_id:
            cloned.frame_id = new_frame_id()
            cloned.parent_frame_id = self.frame_id
            cloned.mutations = list(self.mutations)
            cloned._record_mutation(
                actor="cognitive_frame",
                action="clone_shallow",
                target="frame",
                summary=f"Cloned from {self.frame_id}",
            )
        return cloned

    def clone_deep(self, *, new_id: bool = True) -> "CognitiveFrame":
        """Clone sâu.

        Dùng khi muốn thử predictive simulation hoặc rollback branch.
        """
        cloned = copy.deepcopy(self)
        if new_id:
            cloned.parent_frame_id = self.frame_id
            cloned.frame_id = new_frame_id()
            cloned._record_mutation(
                actor="cognitive_frame",
                action="clone_deep",
                target="frame",
                summary=f"Deep cloned from {self.frame_id}",
            )
        return cloned

    # -------------------------------------------------------------------------
    # Budget helpers
    # -------------------------------------------------------------------------
    @property
    def is_fast(self) -> bool:
        return self.budget_mode == "fast"

    @property
    def is_normal(self) -> bool:
        return self.budget_mode == "normal"

    @property
    def is_deep(self) -> bool:
        return self.budget_mode == "deep"

    @property
    def is_reflection(self) -> bool:
        return self.budget_mode == "reflection"

    @property
    def has_user_chat(self) -> bool:
        """Frame có phải chứa chat user không."""
        if self.channel == "chat":
            return True
        for signal in self.raw_signals:
            if _safe_get_attr(signal, "source", None) == "user_chat":
                return True
        return False

    @property
    def has_body_context(self) -> bool:
        """Frame có signal/slot body hoặc spatial không."""
        if self.spatial is not None or self.body_plan is not None:
            return True
        for signal in self.raw_signals:
            if _safe_get_attr(signal, "source", None) == "body":
                return True
        return False

    @property
    def has_memory_context(self) -> bool:
        """Frame có signal/slot memory không."""
        if self.memory_packet is not None:
            return True
        for signal in self.raw_signals:
            if _safe_get_attr(signal, "source", None) == "memory":
                return True
        return False


# =============================================================================
# 6. FrameBuilder tiện dụng
# =============================================================================

@dataclass
class CognitiveFrameBuilder:
    """Builder nhỏ để tạo frame sạch hơn trong coordinator/test.

    Không bắt buộc dùng. Nhưng nó giúp coordinator bớt dài, một mục tiêu đáng
    kính trong một thế giới nơi file 5000 dòng vẫn được ai đó gọi là "tạm ổn".
    """

    default_budget: FrameBudgetMode = "normal"
    default_channel: FrameChannel = "unknown"
    session_id: Optional[str] = None

    def create(
        self,
        *,
        raw_signals: Optional[list[RawSignal]] = None,
        budget_mode: Optional[FrameBudgetMode] = None,
        channel: Optional[FrameChannel] = None,
        turn_id: Optional[str] = None,
        parent_frame_id: Optional[str] = None,
        cycle_index: int = 0,
        user_text: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CognitiveFrame:
        return CognitiveFrame.start(
            raw_signals=raw_signals,
            budget_mode=budget_mode or self.default_budget,
            channel=channel or self.default_channel,
            session_id=self.session_id,
            turn_id=turn_id,
            parent_frame_id=parent_frame_id,
            cycle_index=cycle_index,
            user_text=user_text,
            metadata=metadata,
        )


# =============================================================================
# 7. Utility functions cho coordinator
# =============================================================================

def attach_report_to_frame(
    frame: CognitiveFrame,
    report: ModuleReport,
    *,
    slot_name: Optional[FrameSlotName] = None,
    overwrite: bool = True,
) -> CognitiveFrame:
    """Gắn report vào frame rồi trả lại frame.

    Dạng functional-ish để coordinator có thể viết:
        frame = attach_report_to_frame(frame, report, slot_name="salience")
    """
    frame.add_report(report, slot_name=slot_name, overwrite=overwrite)
    return frame


def close_frame_with_validation(
    frame: CognitiveFrame,
    *,
    strict: bool = False,
    actor: str = "runtime",
) -> list[FrameValidationIssue]:
    """Validate rồi close frame.

    Trả issues để coordinator log hoặc test assert.
    """
    issues = frame.validate(strict=strict)
    for issue in issues:
        if issue.severity in ("warning", "error"):
            frame.add_warning(f"{issue.code}: {issue.message}", actor=actor)

    if any(issue.severity == "error" for issue in issues):
        frame.fail("validation error", actor=actor)
    else:
        frame.close(actor=actor)

    return issues


__all__ = [
    "CognitiveFrame",
    "CognitiveFrameBuilder",
    "FrameBudgetMode",
    "FrameChannel",
    "FrameMutation",
    "FramePromptPacket",
    "FrameSlotName",
    "FrameStatus",
    "FrameValidationIssue",
    "PIPELINE_ORDER",
    "attach_report_to_frame",
    "close_frame_with_validation",
    "new_frame_id",
    "now_ts",
]
