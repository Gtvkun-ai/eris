# -*- coding: utf-8 -*-
"""
src/cortex/global_workspace.py
================================

Global Workspace / Broadcast Frame cho ERIS.

Mục tiêu của file này:
- Biến WorkingMemory + Salience + Evidence + Affect + Goal + Risk + Body state
  thành một object trung gian rõ ràng cho downstream đọc.
- Không cho module downstream đọc toàn bộ raw world tùy tiện.
- Không biến GlobalWorkspace thành "render prompt context". Prompt chỉ là một đầu ra phụ,
  còn WorkspaceFrame mới là contract chính.

Vị trí trong pipeline:
    Evidence
      -> AttentionSalience
      -> WorkingMemory
      -> GlobalWorkspace
      -> WorldScene / Meaning / ToM / Speech / Action

Nguyên tắc thiết kế:
1. Workspace chỉ broadcast phần đã được chọn, không broadcast toàn bộ frame.
2. Mọi thứ được đưa vào workspace phải có lý do, priority và confidence.
3. Memory, affect, relation, risk được xem là pressure / context, không phải chân lý tuyệt đối.
4. Downstream đọc WorkspaceFrame thay vì đọc raw_signals/evidence/memory tràn lan.
5. Prompt builder có thể dùng workspace, nhưng workspace không sinh ra chỉ để prompt builder sống.

File này cố tình ít phụ thuộc import nội bộ. Nếu repo chưa nối core/evidence.py hoặc
core/cognitive_frame.py, nó vẫn compile và chạy được bằng duck-typing.
Con người đã phát minh dependency hell, ta không cần tôn vinh nó thêm.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum
from time import time
from typing import Any, Dict, Iterable, Literal, Optional, Sequence
from uuid import uuid4
import json
import math


try:  # pragma: no cover - phụ thuộc vào layout repo khi Ngài nối thật.
    from core.evidence import ModuleReport  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.evidence import ModuleReport  # type: ignore
    except Exception:  # pragma: no cover
        @dataclass
        class ModuleReport:  # type: ignore[no-redef]
            """Fallback tối thiểu để file chạy độc lập khi chưa nối core.evidence."""

            module_name: str
            confidence: float
            pressure: float
            evidence_used: list[str]
            result: Any
            warnings: list[str] = field(default_factory=list)
            debug: dict[str, Any] = field(default_factory=dict)


PrivacyLevel = Literal["public", "normal", "private", "sensitive"]
WorkspaceItemKind = Literal[
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
]
BroadcastScope = Literal[
    "world_scene",
    "meaning",
    "theory_of_mind",
    "epistemic",
    "speech",
    "body",
    "memory",
    "debug",
]
WorkspaceBudgetMode = Literal["fast", "normal", "deep", "reflection"]


class WorkspaceSuppressionReason(str, Enum):
    """Các lý do một candidate không được broadcast."""

    LOW_PRIORITY = "low_priority"
    LOW_CONFIDENCE = "low_confidence"
    CONTEXT_FLOOD = "context_flood"
    PRIVACY_BLOCKED = "privacy_blocked"
    DUPLICATE = "duplicate"
    STALE = "stale"
    WEAK_MEMORY_ECHO = "weak_memory_echo"
    SYMBOLIC_DRIFT_RISK = "symbolic_drift_risk"
    TOO_MANY_OF_KIND = "too_many_of_kind"
    RAW_WORLD_LEAK = "raw_world_leak"


@dataclass(slots=True)
class WorkspaceItem:
    """
    Một đơn vị được broadcast trong Global Workspace.

    Đây là atom cho downstream đọc. Nó không nhất thiết là EvidenceItem gốc.
    Ví dụ:
    - current user request
    - dominant technical goal
    - relevant memory summary
    - affect pressure
    - body state summary
    - risk constraint

    Lưu ý: `content` có thể là object/dict/string. `summary` mới là dạng ngắn
    để debug hoặc prompt packet dùng. Đừng bắt mọi downstream parse string, đó là
    nghi thức triệu hồi bug khá cổ điển.
    """

    id: str
    kind: WorkspaceItemKind
    content: Any
    summary: str
    priority: float
    confidence: float
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    privacy_level: PrivacyLevel = "normal"
    tags: list[str] = field(default_factory=list)
    broadcast_scopes: list[BroadcastScope] = field(default_factory=list)
    decay_after_seconds: float = 120.0
    created_at: float = field(default_factory=time)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now_ts: Optional[float] = None) -> bool:
        """Kiểm tra item có hết hạn chưa."""

        now_ts = time() if now_ts is None else now_ts
        if self.decay_after_seconds <= 0:
            return False
        return (now_ts - self.created_at) > self.decay_after_seconds

    def is_surfaceable(self, include_private: bool = False) -> bool:
        """
        Kiểm tra item có được phép đưa vào bề mặt prompt/output không.

        Workspace có thể giữ private pressure nội bộ, nhưng prompt/speech không được
        tự ý dùng nếu privacy không cho phép. Hiểu được không có nghĩa được quyền nói.
        """

        if include_private:
            return self.privacy_level != "sensitive"
        return self.privacy_level in ("public", "normal")

    def to_safe_dict(self, include_content: bool = False) -> dict[str, Any]:
        """Xuất dict an toàn cho debug/log."""

        data = {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "priority": round_float(self.priority),
            "confidence": round_float(self.confidence),
            "source_ids": list(self.source_ids),
            "evidence_ids": list(self.evidence_ids),
            "privacy_level": self.privacy_level,
            "tags": list(self.tags),
            "broadcast_scopes": list(self.broadcast_scopes),
            "reason": self.reason,
            "metadata": safe_serialize(self.metadata),
        }
        if include_content:
            data["content"] = safe_serialize(self.content)
        return data


@dataclass(slots=True)
class SuppressedWorkspaceItem:
    """Candidate bị chặn trước khi broadcast."""

    id: str
    kind: WorkspaceItemKind
    summary: str
    reason: WorkspaceSuppressionReason
    priority: float
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "reason": self.reason.value,
            "priority": round_float(self.priority),
            "confidence": round_float(self.confidence),
            "evidence_ids": list(self.evidence_ids),
            "debug": safe_serialize(self.debug),
        }


@dataclass(slots=True)
class WorkspaceRisk:
    """
    Risk đã được chọn để downstream biết giới hạn hành động.

    Risk ở đây không phải lệnh rewrite. Nó chỉ là broadcast constraint.
    Permission/Grounding/SpeechCore mới quyết định xử lý thế nào.
    """

    label: str
    severity: float
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    recommended_constraint: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "severity": round_float(self.severity),
            "confidence": round_float(self.confidence),
            "evidence_ids": list(self.evidence_ids),
            "recommended_constraint": self.recommended_constraint,
            "reason": self.reason,
        }


@dataclass(slots=True)
class WorkspaceSocialHypothesis:
    """
    Giả thuyết xã hội được broadcast ở mức rất cẩn trọng.

    Đây KHÔNG phải Theory of Mind đầy đủ. Nó chỉ là seed cho WorldInterpreter / ToM.
    Ví dụ: "user is requesting implementation", "technical urgency", "correction context".
    Không nhét các phán đoán cảm xúc nặng vào đây nếu không có evidence mạnh.
    """

    label: str
    description: str
    confidence: float
    overread_risk: float
    evidence_ids: list[str] = field(default_factory=list)
    allowed_surface: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "confidence": round_float(self.confidence),
            "overread_risk": round_float(self.overread_risk),
            "evidence_ids": list(self.evidence_ids),
            "allowed_surface": self.allowed_surface,
        }


@dataclass(slots=True)
class WorkspacePromptPacket:
    """
    Packet phụ cho prompt builder.

    Cấm hiểu nhầm: đây chỉ là projection của WorkspaceFrame sang prompt, không phải
    bản chất của GlobalWorkspace. Nếu downstream cần hiểu scene/meaning/tom, hãy đọc
    WorkspaceFrame trực tiếp.
    """

    frame_id: str
    selected_context: list[str]
    memory_context: list[str]
    constraints: list[str]
    forbidden_assumptions: list[str]
    max_estimated_tokens: int
    debug_summary: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """Render packet thành text ngắn cho prompt builder."""

        parts: list[str] = []
        if self.selected_context:
            parts.append("[Workspace selected context]")
            parts.extend(f"- {line}" for line in self.selected_context)
        if self.memory_context:
            parts.append("[Selected memory]")
            parts.extend(f"- {line}" for line in self.memory_context)
        if self.constraints:
            parts.append("[Workspace constraints]")
            parts.extend(f"- {line}" for line in self.constraints)
        if self.forbidden_assumptions:
            parts.append("[Forbidden assumptions]")
            parts.extend(f"- {line}" for line in self.forbidden_assumptions)
        return "\n".join(parts).strip()


@dataclass(slots=True)
class WorkspaceFrame:
    """
    Global Workspace / Broadcast Frame.

    Đây là object trung gian downstream đọc.

    Fields đầu bám contract PDF:
    - selected_evidence
    - selected_memory
    - selected_affect
    - selected_goal
    - selected_risk
    - selected_social_hypothesis
    - selected_body_state
    - broadcast_reason

    Fields mở rộng để runtime thật dùng được:
    - broadcast_items: atom đã chọn kèm priority/confidence/reason
    - suppressed_items: atom bị chặn và lý do
    - forbidden_assumptions: điều downstream không được nói như fact
    - context_pressure: áp lực context/token
    - broadcast_priority: mức ưu tiên workspace tổng thể
    - downstream_contract: gợi ý module nào nên đọc gì
    """

    frame_id: str
    timestamp: float
    budget_mode: WorkspaceBudgetMode

    selected_evidence: list[Any] = field(default_factory=list)
    selected_memory: list[str] = field(default_factory=list)
    selected_affect: Optional[Any] = None
    selected_goal: Optional[str] = None
    selected_risk: Optional[str] = None
    selected_social_hypothesis: Optional[str] = None
    selected_body_state: Optional[Any] = None
    broadcast_reason: str = ""

    broadcast_items: list[WorkspaceItem] = field(default_factory=list)
    suppressed_items: list[SuppressedWorkspaceItem] = field(default_factory=list)
    risks: list[WorkspaceRisk] = field(default_factory=list)
    social_hypotheses: list[WorkspaceSocialHypothesis] = field(default_factory=list)
    forbidden_assumptions: list[str] = field(default_factory=list)
    active_threads: list[str] = field(default_factory=list)
    dominant_thread: Optional[str] = None
    context_pressure: float = 0.0
    broadcast_priority: float = 0.0
    confidence: float = 0.0
    uncertainty: float = 0.0
    downstream_contract: dict[str, list[str]] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)

    def evidence_ids(self) -> list[str]:
        """Lấy toàn bộ evidence id được workspace dùng."""

        ids: list[str] = []
        for item in self.broadcast_items:
            ids.extend(item.evidence_ids)
        for ev in self.selected_evidence:
            ev_id = get_attr(ev, "id", None)
            if ev_id:
                ids.append(str(ev_id))
        return unique_keep_order(ids)

    def items_by_kind(self, kind: WorkspaceItemKind) -> list[WorkspaceItem]:
        """Lấy các item theo kind."""

        return [item for item in self.broadcast_items if item.kind == kind]

    def surface_items(self, scope: Optional[BroadcastScope] = None) -> list[WorkspaceItem]:
        """Lấy item được phép surface, có thể lọc theo scope."""

        out: list[WorkspaceItem] = []
        for item in self.broadcast_items:
            if not item.is_surfaceable(include_private=False):
                continue
            if scope and scope not in item.broadcast_scopes:
                continue
            out.append(item)
        return out

    def build_prompt_packet(self, max_tokens: int = 850) -> WorkspacePromptPacket:
        """
        Projection phụ cho prompt builder.

        Không gọi hàm này từ module cognition nếu module đó cần object có cấu trúc.
        Dùng trực tiếp `broadcast_items`, `risks`, `social_hypotheses` sẽ sạch hơn.
        """

        selected_context: list[str] = []
        memory_context: list[str] = []
        constraints: list[str] = []

        token_used = 0
        for item in sorted(self.surface_items(), key=lambda x: x.priority, reverse=True):
            line = f"{item.kind}: {item.summary}"
            cost = estimate_tokens(line)
            if token_used + cost > max_tokens:
                break
            token_used += cost
            if item.kind == "memory":
                memory_context.append(item.summary)
            elif item.kind in ("risk", "constraint"):
                constraints.append(item.summary)
            else:
                selected_context.append(line)

        for risk in self.risks:
            if risk.recommended_constraint:
                line = f"{risk.label}: {risk.recommended_constraint}"
                if estimate_tokens(line) + token_used <= max_tokens:
                    constraints.append(line)
                    token_used += estimate_tokens(line)

        return WorkspacePromptPacket(
            frame_id=self.frame_id,
            selected_context=selected_context,
            memory_context=memory_context,
            constraints=unique_keep_order(constraints),
            forbidden_assumptions=unique_keep_order(self.forbidden_assumptions),
            max_estimated_tokens=max_tokens,
            debug_summary={
                "token_used_estimate": token_used,
                "context_pressure": round_float(self.context_pressure),
                "broadcast_priority": round_float(self.broadcast_priority),
                "dominant_thread": self.dominant_thread,
            },
        )

    def render_prompt_context(self, max_tokens: int = 850) -> str:
        """Tiện ích tương thích prompt builder cũ."""

        return self.build_prompt_packet(max_tokens=max_tokens).render()

    def to_dict(self, include_content: bool = False) -> dict[str, Any]:
        """Xuất WorkspaceFrame thành dict an toàn."""

        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "budget_mode": self.budget_mode,
            "selected_evidence": [safe_serialize(ev) for ev in self.selected_evidence],
            "selected_memory": list(self.selected_memory),
            "selected_affect": safe_serialize(self.selected_affect),
            "selected_goal": self.selected_goal,
            "selected_risk": self.selected_risk,
            "selected_social_hypothesis": self.selected_social_hypothesis,
            "selected_body_state": safe_serialize(self.selected_body_state),
            "broadcast_reason": self.broadcast_reason,
            "broadcast_items": [item.to_safe_dict(include_content=include_content) for item in self.broadcast_items],
            "suppressed_items": [item.to_dict() for item in self.suppressed_items],
            "risks": [risk.to_dict() for risk in self.risks],
            "social_hypotheses": [hyp.to_dict() for hyp in self.social_hypotheses],
            "forbidden_assumptions": list(self.forbidden_assumptions),
            "active_threads": list(self.active_threads),
            "dominant_thread": self.dominant_thread,
            "context_pressure": round_float(self.context_pressure),
            "broadcast_priority": round_float(self.broadcast_priority),
            "confidence": round_float(self.confidence),
            "uncertainty": round_float(self.uncertainty),
            "downstream_contract": safe_serialize(self.downstream_contract),
            "debug": safe_serialize(self.debug),
        }

    def to_json(self, include_content: bool = False, ensure_ascii: bool = False) -> str:
        """Xuất JSON cho debug/dev mode."""

        return json.dumps(self.to_dict(include_content=include_content), ensure_ascii=ensure_ascii, indent=2)


@dataclass(slots=True)
class GlobalWorkspaceConfig:
    """Cấu hình chọn broadcast."""

    min_priority: float = 0.18
    min_confidence: float = 0.20
    max_items_fast: int = 5
    max_items_normal: int = 9
    max_items_deep: int = 14
    max_items_reflection: int = 12
    max_selected_evidence_fast: int = 3
    max_selected_evidence_normal: int = 5
    max_selected_evidence_deep: int = 9
    max_selected_memory_fast: int = 1
    max_selected_memory_normal: int = 3
    max_selected_memory_deep: int = 5
    max_token_pressure_normalizer: int = 1200
    allow_private_internal: bool = True
    allow_sensitive_internal: bool = False
    decay_default_seconds: float = 150.0
    stale_after_seconds: float = 900.0
    duplicate_similarity_threshold: float = 0.82
    # Quota chống một loại context chiếm toàn bộ workspace.
    max_per_kind: dict[str, int] = field(default_factory=lambda: {
        "evidence": 5,
        "memory": 4,
        "affect": 2,
        "homeostasis": 1,
        "goal": 2,
        "risk": 3,
        "social_hypothesis": 2,
        "body_state": 1,
        "temporal": 1,
        "constraint": 3,
        "working_memory": 7,
        "salience": 2,
        "user_request": 2,
        "unknown": 2,
    })

    def max_items_for_budget(self, budget_mode: WorkspaceBudgetMode) -> int:
        if budget_mode == "fast":
            return self.max_items_fast
        if budget_mode == "deep":
            return self.max_items_deep
        if budget_mode == "reflection":
            return self.max_items_reflection
        return self.max_items_normal

    def max_evidence_for_budget(self, budget_mode: WorkspaceBudgetMode) -> int:
        if budget_mode == "fast":
            return self.max_selected_evidence_fast
        if budget_mode == "deep":
            return self.max_selected_evidence_deep
        return self.max_selected_evidence_normal

    def max_memory_for_budget(self, budget_mode: WorkspaceBudgetMode) -> int:
        if budget_mode == "fast":
            return self.max_selected_memory_fast
        if budget_mode == "deep":
            return self.max_selected_memory_deep
        return self.max_selected_memory_normal


class GlobalWorkspaceEngine:
    """
    Engine tạo WorkspaceFrame từ CognitiveFrame.

    Input chính:
    - frame.evidence
    - frame.salience
    - frame.working_memory
    - frame.affect / frame.homeostasis
    - frame.memory_packet
    - frame.spatial
    - frame.relation / frame.meaning / frame.tom nếu đã có trong vài path nối sau

    Output:
    - frame.workspace = WorkspaceFrame
    - frame.add_report(ModuleReport(...)) nếu frame hỗ trợ

    Đây là broadcast engine, không phải prompt renderer. Nếu sau này WorldSceneBuilder,
    MeaningHypothesis hoặc ToM còn đọc raw_signals trực tiếp trong path bình thường,
    xem như pipeline đã có mùi spaghetti telepathy cần phẫu thuật.
    """

    module_name = "global_workspace"

    def __init__(self, config: Optional[GlobalWorkspaceConfig] = None) -> None:
        self.config = config or GlobalWorkspaceConfig()

    def broadcast(self, frame: Any) -> WorkspaceFrame:
        """Tạo WorkspaceFrame từ frame hiện tại và gắn ngược vào frame nếu có thể."""

        timestamp = float(get_attr(frame, "timestamp", time()) or time())
        frame_id = str(get_attr(frame, "frame_id", f"frame_{uuid4().hex[:10]}"))
        budget_mode = normalize_budget(get_attr(frame, "budget_mode", "normal"))

        candidates = self._collect_candidates(frame=frame, timestamp=timestamp)
        selected, suppressed = self._select_items(candidates, budget_mode=budget_mode, now_ts=timestamp)

        selected_evidence = self._select_evidence(frame, selected, budget_mode)
        selected_memory = self._select_memory(frame, selected, budget_mode)
        selected_affect = self._select_affect(frame, selected)
        selected_goal = self._select_goal(frame, selected)
        risks = self._select_risks(frame, selected)
        social_hypotheses = self._select_social_hypotheses(frame, selected)
        selected_body_state = self._select_body_state(frame, selected)

        dominant_thread = self._derive_dominant_thread(frame, selected)
        active_threads = self._derive_active_threads(frame, selected, dominant_thread)
        forbidden_assumptions = self._derive_forbidden_assumptions(frame, selected, risks, social_hypotheses)
        context_pressure = self._calculate_context_pressure(selected, suppressed, budget_mode)
        broadcast_priority = self._calculate_broadcast_priority(selected, risks)
        confidence = self._calculate_confidence(selected)
        uncertainty = clamp(1.0 - confidence + context_pressure * 0.15, 0.0, 1.0)
        broadcast_reason = self._build_broadcast_reason(
            selected=selected,
            suppressed=suppressed,
            dominant_thread=dominant_thread,
            broadcast_priority=broadcast_priority,
            context_pressure=context_pressure,
        )

        workspace = WorkspaceFrame(
            frame_id=frame_id,
            timestamp=timestamp,
            budget_mode=budget_mode,
            selected_evidence=selected_evidence,
            selected_memory=selected_memory,
            selected_affect=selected_affect,
            selected_goal=selected_goal,
            selected_risk=risks[0].label if risks else None,
            selected_social_hypothesis=social_hypotheses[0].label if social_hypotheses else None,
            selected_body_state=selected_body_state,
            broadcast_reason=broadcast_reason,
            broadcast_items=selected,
            suppressed_items=suppressed,
            risks=risks,
            social_hypotheses=social_hypotheses,
            forbidden_assumptions=forbidden_assumptions,
            active_threads=active_threads,
            dominant_thread=dominant_thread,
            context_pressure=context_pressure,
            broadcast_priority=broadcast_priority,
            confidence=confidence,
            uncertainty=uncertainty,
            downstream_contract=self._build_downstream_contract(selected, risks, social_hypotheses),
            debug={
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "suppressed_count": len(suppressed),
                "budget_mode": budget_mode,
                "kind_counts": count_by_kind(selected),
                "suppressed_reasons": count_suppression(suppressed),
            },
        )

        self._attach_to_frame(frame, workspace)
        return workspace

    # ------------------------------------------------------------------
    # Candidate collection
    # ------------------------------------------------------------------

    def _collect_candidates(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        """Gom candidate từ các tầng đã có trong frame."""

        candidates: list[WorkspaceItem] = []
        candidates.extend(self._candidates_from_working_memory(frame, timestamp))
        candidates.extend(self._candidates_from_salience(frame, timestamp))
        candidates.extend(self._candidates_from_evidence(frame, timestamp))
        candidates.extend(self._candidates_from_memory_packet(frame, timestamp))
        candidates.extend(self._candidates_from_affect_and_homeostasis(frame, timestamp))
        candidates.extend(self._candidates_from_goal(frame, timestamp))
        candidates.extend(self._candidates_from_risk_like_fields(frame, timestamp))
        candidates.extend(self._candidates_from_social_like_fields(frame, timestamp))
        candidates.extend(self._candidates_from_body_state(frame, timestamp))
        candidates.extend(self._candidates_from_temporal_constraints(frame, timestamp))
        return candidates

    def _candidates_from_working_memory(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        wm = get_attr(frame, "working_memory", None)
        if wm is None:
            return []

        candidates: list[WorkspaceItem] = []
        active_slots = as_list(get_attr(wm, "active_slots", []))
        dominant_thread = get_attr(wm, "dominant_thread", None)
        context_pressure = get_attr(wm, "context_pressure", 0.0)

        for index, slot in enumerate(active_slots):
            name = str(get_attr(slot, "name", f"slot_{index}"))
            content = get_attr(slot, "content", slot)
            priority = clamp(float_or(get_attr(slot, "priority", 0.5), 0.5), 0.0, 1.0)
            source_ids = [str(x) for x in as_list(get_attr(slot, "source_ids", []))]
            summary = compact_text(f"{name}: {stringify_content(content)}", 260)
            kind = self._classify_slot_kind(name, content)
            scopes = self._scopes_for_kind(kind)
            tags = unique_keep_order(["working_memory", name, kind])
            candidates.append(WorkspaceItem(
                id=f"ws_wm_{stable_suffix(name, index)}",
                kind=kind if kind != "unknown" else "working_memory",
                content=content,
                summary=summary,
                priority=clamp(priority + 0.08, 0.0, 1.0),
                confidence=clamp(float_or(get_attr(slot, "confidence", priority), priority), 0.0, 1.0),
                source_ids=source_ids,
                evidence_ids=[sid for sid in source_ids if sid.startswith("ev") or sid.startswith("evidence")],
                privacy_level=normalize_privacy(get_attr(slot, "privacy_level", "normal")),
                tags=tags,
                broadcast_scopes=scopes,
                decay_after_seconds=float_or(get_attr(slot, "decay_after_seconds", self.config.decay_default_seconds), self.config.decay_default_seconds),
                created_at=timestamp,
                reason="selected by working memory bottleneck",
                metadata={
                    "slot_name": name,
                    "dominant_thread_match": bool(dominant_thread and name in str(dominant_thread)),
                    "working_memory_context_pressure": round_float(float_or(context_pressure, 0.0)),
                },
            ))
        return candidates

    def _candidates_from_salience(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        salience = get_attr(frame, "salience", None)
        if salience is None:
            return []

        candidates: list[WorkspaceItem] = []
        dominant_focus = get_attr(salience, "dominant_focus", None)
        broadcast_priority = float_or(get_attr(salience, "broadcast_priority", 0.0), 0.0)
        reason = str(get_attr(salience, "reason", "selected by salience"))

        if dominant_focus:
            candidates.append(WorkspaceItem(
                id="ws_salience_dominant_focus",
                kind="salience",
                content=dominant_focus,
                summary=compact_text(f"dominant focus: {dominant_focus}", 220),
                priority=clamp(0.55 + broadcast_priority * 0.35, 0.0, 1.0),
                confidence=clamp(0.55 + broadcast_priority * 0.25, 0.0, 1.0),
                tags=["salience", "dominant_focus"],
                broadcast_scopes=["world_scene", "meaning", "speech", "debug"],
                decay_after_seconds=90.0,
                created_at=timestamp,
                reason=reason,
                metadata={"broadcast_priority": round_float(broadcast_priority)},
            ))

        selected_candidates = as_list(get_attr(salience, "selected_candidates", []))
        for index, candidate in enumerate(selected_candidates[:12]):
            claim = stringify_content(get_attr(candidate, "claim", get_attr(candidate, "summary", candidate)))
            confidence = clamp(float_or(get_attr(candidate, "confidence", 0.55), 0.55), 0.0, 1.0)
            priority = clamp(float_or(get_attr(candidate, "score", get_attr(candidate, "priority", confidence)), confidence), 0.0, 1.0)
            evidence_id = str(get_attr(candidate, "evidence_id", get_attr(candidate, "id", "")) or "")
            tags = [str(x) for x in as_list(get_attr(candidate, "tags", []))]
            kind = self._kind_from_tags_or_text(tags, claim, fallback="evidence")
            candidates.append(WorkspaceItem(
                id=f"ws_sal_{stable_suffix(evidence_id or claim, index)}",
                kind=kind,
                content=candidate,
                summary=compact_text(claim, 260),
                priority=priority,
                confidence=confidence,
                source_ids=[str(get_attr(candidate, "source_signal_id", ""))] if get_attr(candidate, "source_signal_id", None) else [],
                evidence_ids=[evidence_id] if evidence_id else [],
                privacy_level=normalize_privacy(get_attr(candidate, "privacy_level", "normal")),
                tags=unique_keep_order(["salience_candidate", *tags]),
                broadcast_scopes=self._scopes_for_kind(kind),
                decay_after_seconds=120.0,
                created_at=timestamp,
                reason="selected candidate from SalienceFrame",
                metadata={"salience_rank": index},
            ))
        return candidates

    def _candidates_from_evidence(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        evidence_list = as_list(get_attr(frame, "evidence", []))
        if not evidence_list:
            return []

        candidates: list[WorkspaceItem] = []
        for index, ev in enumerate(evidence_list[:80]):
            claim = str(get_attr(ev, "claim", stringify_content(ev)))
            ev_id = str(get_attr(ev, "id", f"ev_{index}"))
            confidence = clamp(float_or(get_attr(ev, "confidence", 0.45), 0.45), 0.0, 1.0)
            reliability = clamp(float_or(get_attr(ev, "reliability", 0.70), 0.70), 0.0, 1.0)
            tags = [str(t) for t in as_list(get_attr(ev, "tags", []))]
            source = str(get_attr(ev, "source", "unknown"))
            raw_or_inferred = str(get_attr(ev, "raw_or_inferred", "inferred"))
            kind = self._kind_from_tags_or_text(tags + [source], claim, fallback="evidence")
            source_ts = float_or(get_attr(ev, "timestamp", timestamp), timestamp)
            age = max(0.0, timestamp - source_ts)
            priority = self._score_evidence_priority(
                claim=claim,
                tags=tags,
                source=source,
                confidence=confidence,
                reliability=reliability,
                raw_or_inferred=raw_or_inferred,
                age_seconds=age,
            )
            candidates.append(WorkspaceItem(
                id=f"ws_ev_{stable_suffix(ev_id, index)}",
                kind=kind,
                content=ev,
                summary=compact_text(claim, 260),
                priority=priority,
                confidence=clamp(confidence * 0.72 + reliability * 0.28, 0.0, 1.0),
                source_ids=[str(get_attr(ev, "source_signal_id", ""))] if get_attr(ev, "source_signal_id", None) else [],
                evidence_ids=[ev_id],
                privacy_level=normalize_privacy(get_attr(ev, "privacy_level", "normal")),
                tags=unique_keep_order(["evidence", source, raw_or_inferred, *tags]),
                broadcast_scopes=self._scopes_for_kind(kind),
                decay_after_seconds=self.config.decay_default_seconds,
                created_at=source_ts,
                reason="candidate from normalized evidence",
                metadata={
                    "source": source,
                    "raw_or_inferred": raw_or_inferred,
                    "age_seconds": round_float(age),
                    "reliability": round_float(reliability),
                },
            ))
        return candidates

    def _candidates_from_memory_packet(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        packet = get_attr(frame, "memory_packet", None)
        if packet is None:
            return []

        candidates: list[WorkspaceItem] = []
        # Hỗ trợ cả MemoryPacket dạng object và dict.
        memory_fields = [
            ("episodic", 0.50),
            ("semantic", 0.46),
            ("relational", 0.54),
            ("affective_residue", 0.42),
            ("procedural", 0.48),
            ("temporal", 0.38),
            ("spatial", 0.34),
            ("worldview", 0.36),
        ]
        for field_name, base_priority in memory_fields:
            values = as_list(get_from_obj_or_dict(packet, field_name, []))
            for index, value in enumerate(values[:6]):
                text = compact_text(stringify_content(value), 260)
                if not text:
                    continue
                priority = base_priority
                lowered = text.lower()
                if any(key in lowered for key in ("current", "active", "recent", "repair", "correction", "goal")):
                    priority += 0.10
                if field_name == "affective_residue":
                    # Affect residue là pressure, không được cho thống trị workspace nếu không có current evidence.
                    priority -= 0.08
                candidates.append(WorkspaceItem(
                    id=f"ws_mem_{field_name}_{index}_{stable_suffix(text, index)}",
                    kind="memory",
                    content=value,
                    summary=f"{field_name}: {text}",
                    priority=clamp(priority, 0.0, 1.0),
                    confidence=clamp(float_or(get_attr(value, "confidence", 0.45), 0.45), 0.0, 1.0),
                    source_ids=[str(get_attr(value, "id", ""))] if get_attr(value, "id", None) else [],
                    evidence_ids=[],
                    privacy_level=normalize_privacy(get_attr(value, "privacy_level", "normal")),
                    tags=["memory", field_name],
                    broadcast_scopes=["meaning", "theory_of_mind", "speech", "memory"],
                    decay_after_seconds=180.0,
                    created_at=timestamp,
                    reason=f"selected memory packet field: {field_name}",
                    metadata={"memory_field": field_name},
                ))
        return candidates

    def _candidates_from_affect_and_homeostasis(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        candidates: list[WorkspaceItem] = []
        affect = get_attr(frame, "affect", None)
        homeostasis = get_attr(frame, "homeostasis", None)

        if affect is not None:
            summary, priority, confidence = self._summarize_pressure_object(
                affect,
                preferred_fields=(
                    "tension",
                    "curiosity",
                    "restraint",
                    "attachment_pressure",
                    "irritation",
                    "tenderness",
                    "continuity_anxiety",
                    "fatigue",
                    "arousal",
                ),
            )
            candidates.append(WorkspaceItem(
                id="ws_affect_selected",
                kind="affect",
                content=affect,
                summary=summary or "affect pressure available",
                priority=priority,
                confidence=confidence,
                tags=["affect", "pressure"],
                broadcast_scopes=["meaning", "theory_of_mind", "speech", "body"],
                decay_after_seconds=80.0,
                created_at=timestamp,
                reason="current affective pressure selected for regulation",
                metadata={"not_public_emotion_claim": True},
            ))

        if homeostasis is not None:
            summary, priority, confidence = self._summarize_pressure_object(
                homeostasis,
                preferred_fields=(
                    "energy_budget",
                    "cognitive_load",
                    "social_load",
                    "exposure_load",
                    "speech_cost",
                    "silence_recovery_need",
                    "action_readiness",
                    "regulation_policy",
                ),
            )
            candidates.append(WorkspaceItem(
                id="ws_homeostasis_selected",
                kind="homeostasis",
                content=homeostasis,
                summary=summary or "homeostatic regulation available",
                priority=priority,
                confidence=confidence,
                tags=["homeostasis", "regulation"],
                broadcast_scopes=["speech", "body", "meaning"],
                decay_after_seconds=80.0,
                created_at=timestamp,
                reason="current regulation state selected",
                metadata={"not_public_emotion_claim": True},
            ))
        return candidates

    def _candidates_from_goal(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        candidates: list[WorkspaceItem] = []
        goal_sources = [
            get_attr(frame, "goal", None),
            get_attr(frame, "goal_state", None),
            get_attr(frame, "agency", None),
            get_attr(frame, "epistemic", None),
        ]
        # Một số repo để goal trong active_state hoặc internal_state.
        active_state = get_attr(frame, "active_state", None)
        if active_state is not None:
            goal_sources.append(get_attr(active_state, "goal", None))
            goal_sources.append(get_attr(active_state, "active_goal", None))

        for index, goal in enumerate(goal_sources):
            if goal is None:
                continue
            summary = self._goal_summary(goal)
            if not summary:
                continue
            confidence = clamp(float_or(get_attr(goal, "confidence", get_attr(goal, "commitment_strength", 0.55)), 0.55), 0.0, 1.0)
            strength = clamp(float_or(get_attr(goal, "strength", get_attr(goal, "commitment_strength", confidence)), confidence), 0.0, 1.0)
            priority = clamp(0.36 + strength * 0.38 + confidence * 0.16, 0.0, 1.0)
            if bool(get_attr(goal, "can_intervene", False)):
                priority += 0.08
            candidates.append(WorkspaceItem(
                id=f"ws_goal_{index}_{stable_suffix(summary, index)}",
                kind="goal",
                content=goal,
                summary=compact_text(summary, 240),
                priority=clamp(priority, 0.0, 1.0),
                confidence=confidence,
                tags=["goal"],
                broadcast_scopes=["meaning", "epistemic", "speech", "memory"],
                decay_after_seconds=240.0,
                created_at=timestamp,
                reason="active goal/agency pressure selected",
                metadata={
                    "strength": round_float(strength),
                    "can_intervene": bool(get_attr(goal, "can_intervene", False)),
                    "actionability": round_float(float_or(get_attr(goal, "actionability", 0.0), 0.0)),
                },
            ))
        return candidates

    def _candidates_from_risk_like_fields(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        candidates: list[WorkspaceItem] = []
        risk_sources = [
            get_attr(frame, "permission", None),
            get_attr(frame, "grounding", None),
            get_attr(frame, "value_resolution", None),
            get_attr(frame, "tom", None),
        ]
        for index, source in enumerate(risk_sources):
            if source is None:
                continue
            risk_label, severity, confidence, constraint = self._extract_risk(source)
            if not risk_label:
                continue
            candidates.append(WorkspaceItem(
                id=f"ws_risk_{index}_{stable_suffix(risk_label, index)}",
                kind="risk",
                content=source,
                summary=compact_text(f"{risk_label}: {constraint or 'risk constraint active'}", 260),
                priority=clamp(0.40 + severity * 0.42 + confidence * 0.12, 0.0, 1.0),
                confidence=confidence,
                tags=["risk", risk_label],
                broadcast_scopes=["meaning", "theory_of_mind", "speech", "body", "debug"],
                decay_after_seconds=120.0,
                created_at=timestamp,
                reason="risk-like report selected as workspace constraint",
                metadata={
                    "risk_label": risk_label,
                    "severity": round_float(severity),
                    "recommended_constraint": constraint,
                },
            ))
        return candidates

    def _candidates_from_social_like_fields(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        candidates: list[WorkspaceItem] = []
        social_sources = [
            get_attr(frame, "relation", None),
            get_attr(frame, "sociocultural", None),
            get_attr(frame, "meaning", None),
            get_attr(frame, "tom", None),
        ]
        for index, source in enumerate(social_sources):
            if source is None:
                continue
            label, description, confidence, overread = self._extract_social_hypothesis(source)
            if not label:
                continue
            candidates.append(WorkspaceItem(
                id=f"ws_social_{index}_{stable_suffix(label, index)}",
                kind="social_hypothesis",
                content=source,
                summary=compact_text(f"{label}: {description}", 260),
                priority=clamp(0.30 + confidence * 0.38 - overread * 0.20, 0.0, 1.0),
                confidence=confidence,
                tags=["social_hypothesis", label],
                broadcast_scopes=["meaning", "theory_of_mind", "speech"],
                decay_after_seconds=110.0,
                created_at=timestamp,
                reason="social/cultural hypothesis selected carefully",
                metadata={"overread_risk": round_float(overread)},
            ))
        return candidates

    def _candidates_from_body_state(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        spatial = get_attr(frame, "spatial", None)
        body_plan = get_attr(frame, "body_plan", None)
        modality = get_attr(frame, "modality", None)
        source = spatial or body_plan or modality
        if source is None:
            return []

        summary = self._body_summary(source)
        if not summary:
            return []
        priority = 0.38
        contradiction = float_or(get_attr(source, "contradiction_risk", get_attr(modality, "contradiction_risk", 0.0)), 0.0)
        if contradiction > 0.35:
            priority += 0.18
        return [WorkspaceItem(
            id="ws_body_state_selected",
            kind="body_state",
            content=source,
            summary=summary,
            priority=clamp(priority, 0.0, 1.0),
            confidence=clamp(0.56 + max(0.0, 1.0 - contradiction) * 0.12, 0.0, 1.0),
            tags=["body_state", "spatial"],
            broadcast_scopes=["world_scene", "body", "speech"],
            decay_after_seconds=70.0,
            created_at=timestamp,
            reason="body/spatial state selected for modality consistency",
            metadata={"contradiction_risk": round_float(contradiction)},
        )]

    def _candidates_from_temporal_constraints(self, frame: Any, timestamp: float) -> list[WorkspaceItem]:
        temporal = get_attr(frame, "temporal", None)
        if temporal is None:
            return []
        summary = self._temporal_summary(temporal)
        if not summary:
            return []
        pressure = max(
            float_or(get_attr(temporal, "waiting_pressure", 0.0), 0.0),
            float_or(get_attr(temporal, "meaning_debt", 0.0), 0.0),
            float_or(get_attr(temporal, "repetition_fatigue", 0.0), 0.0),
            float_or(get_attr(temporal, "unfinished_time_pressure", 0.0), 0.0),
        )
        return [WorkspaceItem(
            id="ws_temporal_selected",
            kind="temporal",
            content=temporal,
            summary=summary,
            priority=clamp(0.28 + pressure * 0.42, 0.0, 1.0),
            confidence=0.58,
            tags=["temporal", "rhythm"],
            broadcast_scopes=["meaning", "speech", "memory"],
            decay_after_seconds=120.0,
            created_at=timestamp,
            reason="temporal rhythm selected",
            metadata={"pressure": round_float(pressure)},
        )]

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _select_items(
        self,
        candidates: list[WorkspaceItem],
        budget_mode: WorkspaceBudgetMode,
        now_ts: float,
    ) -> tuple[list[WorkspaceItem], list[SuppressedWorkspaceItem]]:
        """Chọn items theo score, quota, privacy, duplicate và context pressure."""

        selected: list[WorkspaceItem] = []
        suppressed: list[SuppressedWorkspaceItem] = []
        max_items = self.config.max_items_for_budget(budget_mode)
        kind_counts: dict[str, int] = {}
        seen_summaries: list[str] = []

        ranked = sorted(candidates, key=lambda item: (item.priority, item.confidence), reverse=True)
        for item in ranked:
            reason = self._suppression_reason(item, selected, seen_summaries, kind_counts, now_ts)
            if reason is not None:
                suppressed.append(self._suppress(item, reason))
                continue

            if len(selected) >= max_items:
                suppressed.append(self._suppress(item, WorkspaceSuppressionReason.CONTEXT_FLOOD))
                continue

            max_for_kind = self.config.max_per_kind.get(item.kind, self.config.max_per_kind.get("unknown", 2))
            if kind_counts.get(item.kind, 0) >= max_for_kind:
                suppressed.append(self._suppress(item, WorkspaceSuppressionReason.TOO_MANY_OF_KIND))
                continue

            selected.append(item)
            kind_counts[item.kind] = kind_counts.get(item.kind, 0) + 1
            seen_summaries.append(normalize_text_for_similarity(item.summary))

        return selected, suppressed

    def _suppression_reason(
        self,
        item: WorkspaceItem,
        selected: list[WorkspaceItem],
        seen_summaries: list[str],
        kind_counts: dict[str, int],
        now_ts: float,
    ) -> Optional[WorkspaceSuppressionReason]:
        if item.priority < self.config.min_priority:
            return WorkspaceSuppressionReason.LOW_PRIORITY
        if item.confidence < self.config.min_confidence:
            return WorkspaceSuppressionReason.LOW_CONFIDENCE
        if item.is_expired(now_ts) and item.kind not in ("goal", "memory"):
            return WorkspaceSuppressionReason.STALE
        if item.privacy_level == "sensitive" and not self.config.allow_sensitive_internal:
            return WorkspaceSuppressionReason.PRIVACY_BLOCKED
        if item.privacy_level == "private" and not self.config.allow_private_internal:
            return WorkspaceSuppressionReason.PRIVACY_BLOCKED
        if item.kind == "memory" and item.confidence < 0.36 and item.priority < 0.48:
            return WorkspaceSuppressionReason.WEAK_MEMORY_ECHO
        if item.kind in ("social_hypothesis", "affect") and item.confidence < 0.42 and not item.evidence_ids:
            return WorkspaceSuppressionReason.SYMBOLIC_DRIFT_RISK
        norm = normalize_text_for_similarity(item.summary)
        for existing in seen_summaries:
            if jaccard_similarity(norm, existing) >= self.config.duplicate_similarity_threshold:
                return WorkspaceSuppressionReason.DUPLICATE
        return None

    def _suppress(self, item: WorkspaceItem, reason: WorkspaceSuppressionReason) -> SuppressedWorkspaceItem:
        return SuppressedWorkspaceItem(
            id=item.id,
            kind=item.kind,
            summary=item.summary,
            reason=reason,
            priority=item.priority,
            confidence=item.confidence,
            evidence_ids=list(item.evidence_ids),
            debug={"tags": list(item.tags), "privacy_level": item.privacy_level},
        )

    # ------------------------------------------------------------------
    # Derivations
    # ------------------------------------------------------------------

    def _select_evidence(self, frame: Any, selected: list[WorkspaceItem], budget_mode: WorkspaceBudgetMode) -> list[Any]:
        evidence_by_id: dict[str, Any] = {}
        for ev in as_list(get_attr(frame, "evidence", [])):
            ev_id = str(get_attr(ev, "id", ""))
            if ev_id:
                evidence_by_id[ev_id] = ev

        picked: list[Any] = []
        for item in selected:
            for ev_id in item.evidence_ids:
                ev = evidence_by_id.get(ev_id)
                if ev is not None and ev not in picked:
                    picked.append(ev)
                if len(picked) >= self.config.max_evidence_for_budget(budget_mode):
                    return picked

        # Nếu item không map được id, lấy evidence content trực tiếp.
        for item in selected:
            if item.kind == "evidence" and item.content not in picked:
                picked.append(item.content)
            if len(picked) >= self.config.max_evidence_for_budget(budget_mode):
                break
        return picked

    def _select_memory(self, frame: Any, selected: list[WorkspaceItem], budget_mode: WorkspaceBudgetMode) -> list[str]:
        max_memory = self.config.max_memory_for_budget(budget_mode)
        memory_items = [item for item in selected if item.kind == "memory" and item.is_surfaceable(False)]
        memory_items.sort(key=lambda item: item.priority, reverse=True)
        return [item.summary for item in memory_items[:max_memory]]

    def _select_affect(self, frame: Any, selected: list[WorkspaceItem]) -> Optional[Any]:
        for item in selected:
            if item.kind == "affect":
                return item.content
        return get_attr(frame, "affect", None)

    def _select_goal(self, frame: Any, selected: list[WorkspaceItem]) -> Optional[str]:
        goals = [item for item in selected if item.kind == "goal"]
        if goals:
            goals.sort(key=lambda item: item.priority, reverse=True)
            return goals[0].summary
        return None

    def _select_risks(self, frame: Any, selected: list[WorkspaceItem]) -> list[WorkspaceRisk]:
        risks: list[WorkspaceRisk] = []
        for item in selected:
            if item.kind != "risk":
                continue
            label = str(item.metadata.get("risk_label") or first_tag_after(item.tags, "risk") or "risk")
            severity = clamp(float_or(item.metadata.get("severity"), item.priority), 0.0, 1.0)
            constraint = str(item.metadata.get("recommended_constraint") or "lower certainty / preserve grounding")
            risks.append(WorkspaceRisk(
                label=label,
                severity=severity,
                confidence=item.confidence,
                evidence_ids=list(item.evidence_ids),
                recommended_constraint=constraint,
                reason=item.reason,
            ))
        risks.sort(key=lambda risk: (risk.severity, risk.confidence), reverse=True)
        return risks[:4]

    def _select_social_hypotheses(self, frame: Any, selected: list[WorkspaceItem]) -> list[WorkspaceSocialHypothesis]:
        hypotheses: list[WorkspaceSocialHypothesis] = []
        for item in selected:
            if item.kind != "social_hypothesis":
                continue
            label = str(first_tag_after(item.tags, "social_hypothesis") or "social_context")
            overread = clamp(float_or(item.metadata.get("overread_risk"), 0.35), 0.0, 1.0)
            hypotheses.append(WorkspaceSocialHypothesis(
                label=label,
                description=item.summary,
                confidence=item.confidence,
                overread_risk=overread,
                evidence_ids=list(item.evidence_ids),
                allowed_surface=(item.confidence >= 0.65 and overread < 0.35),
            ))
        hypotheses.sort(key=lambda hyp: (hyp.confidence - hyp.overread_risk), reverse=True)
        return hypotheses[:3]

    def _select_body_state(self, frame: Any, selected: list[WorkspaceItem]) -> Optional[Any]:
        for item in selected:
            if item.kind == "body_state":
                return item.content
        return get_attr(frame, "spatial", None)

    def _derive_dominant_thread(self, frame: Any, selected: list[WorkspaceItem]) -> Optional[str]:
        wm = get_attr(frame, "working_memory", None)
        dominant = get_attr(wm, "dominant_thread", None) if wm is not None else None
        if dominant:
            return str(dominant)
        if selected:
            best = max(selected, key=lambda item: (item.priority, item.confidence))
            return best.summary
        return None

    def _derive_active_threads(self, frame: Any, selected: list[WorkspaceItem], dominant_thread: Optional[str]) -> list[str]:
        threads: list[str] = []
        if dominant_thread:
            threads.append(dominant_thread)
        for item in selected:
            if item.kind in ("goal", "user_request", "working_memory", "salience"):
                threads.append(item.summary)
        return unique_keep_order([compact_text(t, 180) for t in threads if t])[:6]

    def _derive_forbidden_assumptions(
        self,
        frame: Any,
        selected: list[WorkspaceItem],
        risks: list[WorkspaceRisk],
        social_hypotheses: list[WorkspaceSocialHypothesis],
    ) -> list[str]:
        forbidden: list[str] = []
        for hyp in social_hypotheses:
            if hyp.overread_risk > 0.45 or hyp.confidence < 0.55:
                forbidden.append(f"Do not state social hypothesis as fact: {hyp.label}")
        for item in selected:
            if item.kind == "affect":
                forbidden.append("Do not express internal affect pressure as a literal human emotion claim.")
            if item.kind == "memory" and item.confidence < 0.50:
                forbidden.append("Do not present weak memory echo as current fact.")
            if item.privacy_level in ("private", "sensitive"):
                forbidden.append(f"Do not surface private/sensitive workspace item: {item.id}")
        for risk in risks:
            if "overread" in risk.label or "unsupported" in risk.label:
                forbidden.append("Do not add unsupported psychological interpretation.")
            if "permission" in risk.label:
                forbidden.append("Do not expand action beyond permission limits.")
        # Hàng rào chung cho các path chưa có Permission/Grounding.
        forbidden.extend([
            "Do not read raw world outside WorkspaceFrame unless this module explicitly requires perception-level audit.",
            "Do not turn broadcast pressure into final truth without downstream arbitration.",
        ])
        return unique_keep_order(forbidden)

    def _calculate_context_pressure(
        self,
        selected: list[WorkspaceItem],
        suppressed: list[SuppressedWorkspaceItem],
        budget_mode: WorkspaceBudgetMode,
    ) -> float:
        token_estimate = sum(estimate_tokens(item.summary) for item in selected)
        max_items = self.config.max_items_for_budget(budget_mode)
        item_pressure = len(selected) / max(1, max_items)
        suppression_pressure = min(1.0, len(suppressed) / max(1, len(selected) + len(suppressed)))
        token_pressure = min(1.0, token_estimate / max(1, self.config.max_token_pressure_normalizer))
        return clamp(item_pressure * 0.38 + suppression_pressure * 0.22 + token_pressure * 0.40, 0.0, 1.0)

    def _calculate_broadcast_priority(self, selected: list[WorkspaceItem], risks: list[WorkspaceRisk]) -> float:
        if not selected:
            return 0.0
        top = sorted(selected, key=lambda item: item.priority, reverse=True)[:5]
        base = sum(item.priority for item in top) / len(top)
        risk_bonus = max([risk.severity for risk in risks], default=0.0) * 0.12
        return clamp(base + risk_bonus, 0.0, 1.0)

    def _calculate_confidence(self, selected: list[WorkspaceItem]) -> float:
        if not selected:
            return 0.0
        weights = [max(0.05, item.priority) for item in selected]
        total = sum(weights)
        return clamp(sum(item.confidence * weight for item, weight in zip(selected, weights)) / total, 0.0, 1.0)

    def _build_broadcast_reason(
        self,
        selected: list[WorkspaceItem],
        suppressed: list[SuppressedWorkspaceItem],
        dominant_thread: Optional[str],
        broadcast_priority: float,
        context_pressure: float,
    ) -> str:
        if not selected:
            return "No workspace broadcast: no candidate survived selection."
        kind_counts = count_by_kind(selected)
        top_kinds = ", ".join(f"{k}={v}" for k, v in sorted(kind_counts.items(), key=lambda kv: kv[1], reverse=True)[:4])
        base = f"Broadcast selected {len(selected)} items ({top_kinds})"
        if dominant_thread:
            base += f" around dominant thread: {compact_text(dominant_thread, 120)}"
        base += f"; priority={broadcast_priority:.2f}; context_pressure={context_pressure:.2f}"
        if suppressed:
            base += f"; suppressed={len(suppressed)}"
        return base

    def _build_downstream_contract(
        self,
        selected: list[WorkspaceItem],
        risks: list[WorkspaceRisk],
        social_hypotheses: list[WorkspaceSocialHypothesis],
    ) -> dict[str, list[str]]:
        """Gợi ý module downstream nên đọc phần nào. Đây là tài liệu runtime, không phải luật cứng."""

        contract: dict[str, list[str]] = {
            "WorldSceneBuilder": [
                "selected_evidence",
                "selected_body_state",
                "dominant_thread",
            ],
            "WorldInterpreter": ["broadcast_items", "risks", "active_threads"],
            "SocioculturalContext": [
                "social_hypotheses",
                "selected_evidence",
                "forbidden_assumptions",
            ],
            # Tên phải khớp đúng module name mà FrameReadView dùng. Bản cũ dùng
            # "MeaningHypothesis" / "TheoryOfMind" trong khi facade gọi
            # "MeaningHypothesisEngine" / "TheoryOfMindCore", nên contract guard
            # chặn chính pipeline hợp lệ của mình. Con người gọi đây là bảo mật;
            # máy tính gọi đây là tự khóa cửa rồi ném chìa ra ngoài.
            "MeaningHypothesisEngine": [
                "selected_evidence",
                "selected_memory",
                "selected_goal",
                "social_hypotheses",
            ],
            "TheoryOfMindCore": [
                "social_hypotheses",
                "selected_evidence",
                "selected_memory",
                "forbidden_assumptions",
            ],
            "EpistemicDrive": ["selected_goal", "selected_evidence", "risks"],
            "SpeechCore": ["broadcast_items", "selected_risk", "forbidden_assumptions", "context_pressure"],
            "ActionPlanner": ["selected_goal", "selected_body_state", "risks", "broadcast_priority"],
            "PromptBuilder": ["WorkspacePromptPacket only", "do not read raw frame"],
        }
        if risks:
            contract["PermissionEngine"] = ["risks", "forbidden_assumptions", "selected_risk"]
        return contract

    # ------------------------------------------------------------------
    # Extractors / classifiers
    # ------------------------------------------------------------------

    def _classify_slot_kind(self, name: str, content: Any) -> WorkspaceItemKind:
        text = f"{name} {stringify_content(content)}".lower()
        if any(k in text for k in ("user request", "current request", "user_text", "chat", "ngài yêu cầu", "request")):
            return "user_request"
        if any(k in text for k in ("goal", "mục tiêu", "task", "active technical")):
            return "goal"
        if any(k in text for k in ("memory", "recall", "episodic", "semantic")):
            return "memory"
        if any(k in text for k in ("affect", "homeostasis", "pressure", "restraint", "fatigue")):
            return "affect"
        if any(k in text for k in ("risk", "constraint", "forbidden", "permission")):
            return "risk"
        if any(k in text for k in ("relation", "social", "tom", "hypothesis")):
            return "social_hypothesis"
        if any(k in text for k in ("body", "spatial", "gaze", "posture")):
            return "body_state"
        return "working_memory"

    def _kind_from_tags_or_text(self, tags: Sequence[str], text: str, fallback: WorkspaceItemKind) -> WorkspaceItemKind:
        joined = " ".join(tags).lower() + " " + text.lower()
        if any(k in joined for k in ("user_chat", "user_request", "current request", "directive")):
            return "user_request"
        if any(k in joined for k in ("memory", "recall", "episodic", "semantic", "relational")):
            return "memory"
        if any(k in joined for k in ("goal", "task", "objective", "mục tiêu")):
            return "goal"
        if any(k in joined for k in ("risk", "unsafe", "unsupported", "permission", "privacy", "overread")):
            return "risk"
        if any(k in joined for k in ("affect", "emotion", "irritation", "tension", "attachment")):
            return "affect"
        if any(k in joined for k in ("social", "relation", "culture", "joke", "profanity")):
            return "social_hypothesis"
        if any(k in joined for k in ("body", "spatial", "gaze", "posture", "movement")):
            return "body_state"
        if any(k in joined for k in ("time", "temporal", "rhythm", "recency")):
            return "temporal"
        return fallback

    def _scopes_for_kind(self, kind: WorkspaceItemKind) -> list[BroadcastScope]:
        mapping: dict[str, list[BroadcastScope]] = {
            "user_request": ["world_scene", "meaning", "speech", "debug"],
            "evidence": ["world_scene", "meaning", "theory_of_mind", "speech", "debug"],
            "memory": ["meaning", "theory_of_mind", "speech", "memory"],
            "affect": ["meaning", "speech", "body"],
            "homeostasis": ["speech", "body"],
            "goal": ["meaning", "epistemic", "speech", "memory"],
            "risk": ["meaning", "theory_of_mind", "speech", "body", "debug"],
            "social_hypothesis": ["meaning", "theory_of_mind", "speech"],
            "body_state": ["world_scene", "body", "speech"],
            "temporal": ["meaning", "speech", "memory"],
            "constraint": ["speech", "body", "debug"],
            "working_memory": ["meaning", "speech", "debug"],
            "salience": ["world_scene", "meaning", "speech", "debug"],
            "unknown": ["debug"],
        }
        return list(mapping.get(kind, ["debug"]))

    def _score_evidence_priority(
        self,
        claim: str,
        tags: Sequence[str],
        source: str,
        confidence: float,
        reliability: float,
        raw_or_inferred: str,
        age_seconds: float,
    ) -> float:
        text = f"{claim} {' '.join(tags)} {source}".lower()
        priority = 0.24 + confidence * 0.24 + reliability * 0.18
        if raw_or_inferred == "raw":
            priority += 0.06
        if source == "user_chat":
            priority += 0.22
        if any(k in text for k in ("request", "làm", "tạo", "fix", "error", "bug", "architecture", "code", "pdf")):
            priority += 0.14
        if any(k in text for k in ("risk", "permission", "private", "sensitive", "overread", "unsupported")):
            priority += 0.12
        if any(k in text for k in ("telemetry", "active_window", "browser")) and source != "user_chat":
            priority -= 0.07
        if age_seconds > self.config.stale_after_seconds:
            priority -= 0.18
        return clamp(priority, 0.0, 1.0)

    def _summarize_pressure_object(self, obj: Any, preferred_fields: Sequence[str]) -> tuple[str, float, float]:
        parts: list[str] = []
        strongest = 0.0
        numeric_seen = 0
        for field_name in preferred_fields:
            value = get_from_obj_or_dict(obj, field_name, None)
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                v = clamp(float(value), 0.0, 1.0)
                if v >= 0.18:
                    parts.append(f"{field_name}={v:.2f}")
                strongest = max(strongest, v)
                numeric_seen += 1
            else:
                text = compact_text(str(value), 80)
                if text:
                    parts.append(f"{field_name}={text}")
        if not parts:
            return "", 0.24, 0.36
        priority = clamp(0.28 + strongest * 0.44 + min(0.12, numeric_seen * 0.018), 0.0, 1.0)
        confidence = clamp(0.48 + strongest * 0.20, 0.0, 1.0)
        return "; ".join(parts[:6]), priority, confidence

    def _goal_summary(self, goal: Any) -> str:
        for field_name in ("summary", "goal_preserved", "active_goal", "claim", "intent", "reason"):
            value = get_from_obj_or_dict(goal, field_name, None)
            if value:
                return str(value)
        if isinstance(goal, str):
            return goal
        return compact_text(stringify_content(goal), 220)

    def _extract_risk(self, source: Any) -> tuple[str, float, float, str]:
        candidates = [
            ("permission_violation", get_from_obj_or_dict(source, "permission_violation", None), "reduce intensity or suppress segment"),
            ("factual_risk", get_from_obj_or_dict(source, "factual_risk", None), "soften certainty and require grounding"),
            ("overcertainty_risk", get_from_obj_or_dict(source, "overcertainty_risk", None), "lower certainty"),
            ("body_action_mismatch", get_from_obj_or_dict(source, "body_action_mismatch", None), "sync body with speech"),
            ("global_overread_risk", get_from_obj_or_dict(source, "global_overread_risk", None), "do not express mental-state interpretation directly"),
            ("max_allowed_intensity_limit", 1.0 - float_or(get_from_obj_or_dict(source, "max_allowed_intensity", 1.0), 1.0), "respect max intensity"),
        ]
        best_label = ""
        best_severity = 0.0
        best_constraint = ""
        for label, raw_value, constraint in candidates:
            if raw_value is None:
                continue
            value = clamp(float_or(raw_value, 0.0), 0.0, 1.0)
            if value > best_severity:
                best_label = label
                best_severity = value
                best_constraint = constraint
        if best_severity < 0.20:
            return "", 0.0, 0.0, ""
        confidence = clamp(float_or(get_from_obj_or_dict(source, "confidence", get_from_obj_or_dict(source, "global_confidence", 0.55)), 0.55), 0.0, 1.0)
        return best_label, best_severity, confidence, best_constraint

    def _extract_social_hypothesis(self, source: Any) -> tuple[str, str, float, float]:
        # Cố lấy meaning/tom/relation đã có, nếu không thì không tự bịa.
        label = ""
        description = ""
        confidence = 0.0
        overread = 0.35

        dominant_hyp = get_from_obj_or_dict(source, "dominant_hypothesis", None)
        if dominant_hyp is not None:
            label = str(get_from_obj_or_dict(dominant_hyp, "label", "meaning_hypothesis"))
            description = str(get_from_obj_or_dict(dominant_hyp, "description", label))
            confidence = clamp(float_or(get_from_obj_or_dict(dominant_hyp, "confidence", 0.55), 0.55), 0.0, 1.0)
            overread = clamp(float_or(get_from_obj_or_dict(source, "ambiguity", 0.30), 0.30), 0.0, 1.0)
            return label, description, confidence, overread

        # Relationship state.
        if any(get_from_obj_or_dict(source, f, None) is not None for f in ("trust", "familiarity", "rupture", "repair_need")):
            trust = float_or(get_from_obj_or_dict(source, "trust", 0.5), 0.5)
            rupture = float_or(get_from_obj_or_dict(source, "rupture", 0.0), 0.0)
            repair = float_or(get_from_obj_or_dict(source, "repair_need", 0.0), 0.0)
            if repair > 0.35 or rupture > 0.30:
                label = "repair_context"
                description = "relationship repair pressure is active"
                confidence = clamp(0.45 + max(repair, rupture) * 0.35, 0.0, 1.0)
                overread = 0.28
            elif trust > 0.55:
                label = "familiar_interaction"
                description = "user-specific familiarity may shape register"
                confidence = clamp(0.42 + trust * 0.20, 0.0, 1.0)
                overread = 0.34
            return label, description, confidence, overread

        # ToM report nếu có.
        global_confidence = get_from_obj_or_dict(source, "global_confidence", None)
        global_overread = get_from_obj_or_dict(source, "global_overread_risk", None)
        if global_confidence is not None:
            confidence = clamp(float_or(global_confidence, 0.5), 0.0, 1.0)
            overread = clamp(float_or(global_overread, 0.45), 0.0, 1.0)
            if confidence >= 0.35:
                label = "tom_seed"
                description = "theory-of-mind estimate available but must remain tentative"
            return label, description, confidence, overread

        # Sociocultural frame.
        register = get_from_obj_or_dict(source, "register", None)
        language = get_from_obj_or_dict(source, "language", None)
        if register or language:
            label = "sociocultural_register"
            description = f"language={language or 'unknown'}, register={register or 'unknown'}"
            confidence = 0.58
            overread = 0.18
            return label, description, confidence, overread

        return "", "", 0.0, 0.0

    def _body_summary(self, source: Any) -> str:
        fields = []
        for field_name in ("posture", "gaze_target", "shared_space_relation", "body_interaction_meaning", "action", "movement"):
            value = get_from_obj_or_dict(source, field_name, None)
            if value:
                fields.append(f"{field_name}={value}")
        pos = get_from_obj_or_dict(source, "body_position", None)
        if pos:
            fields.append(f"position={pos}")
        if not fields:
            return ""
        return "; ".join(fields[:6])

    def _temporal_summary(self, temporal: Any) -> str:
        fields = []
        for field_name in ("rhythm", "session_arc", "duration", "recency", "waiting_pressure", "meaning_debt", "repetition_fatigue"):
            value = get_from_obj_or_dict(temporal, field_name, None)
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if abs(float(value)) < 0.05:
                    continue
                fields.append(f"{field_name}={float(value):.2f}")
            else:
                fields.append(f"{field_name}={value}")
        return "; ".join(fields[:6])

    def _attach_to_frame(self, frame: Any, workspace: WorkspaceFrame) -> None:
        """Gắn workspace và ModuleReport vào frame nếu frame hỗ trợ."""

        try:
            if hasattr(frame, "set_slot"):
                frame.set_slot("workspace", workspace, module_name=self.module_name)  # type: ignore[misc]
            else:
                setattr(frame, "workspace", workspace)
        except Exception:
            # Không để attach fail làm chết engine. Frame cũ có thể là dataclass frozen hoặc object lạ.
            try:
                setattr(frame, "workspace", workspace)
            except Exception:
                pass

        report = ModuleReport(
            module_name=self.module_name,
            confidence=workspace.confidence,
            pressure=workspace.broadcast_priority,
            evidence_used=workspace.evidence_ids(),
            result=workspace,
            warnings=list(workspace.forbidden_assumptions),
            debug={
                "broadcast_reason": workspace.broadcast_reason,
                "context_pressure": round_float(workspace.context_pressure),
                "selected_count": len(workspace.broadcast_items),
                "suppressed_count": len(workspace.suppressed_items),
            },
        )
        try:
            if hasattr(frame, "add_report"):
                frame.add_report(report)  # type: ignore[misc]
            elif hasattr(frame, "module_reports"):
                reports = get_attr(frame, "module_reports", {})
                if isinstance(reports, dict):
                    reports[self.module_name] = report
                elif isinstance(reports, list):
                    reports.append(report)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Public convenience function
# ----------------------------------------------------------------------


def broadcast_workspace(frame: Any, config: Optional[GlobalWorkspaceConfig] = None) -> WorkspaceFrame:
    """Hàm tiện ích để dùng nhanh trong coordinator/runtime."""

    return GlobalWorkspaceEngine(config=config).broadcast(frame)


# ----------------------------------------------------------------------
# Utility helpers
# ----------------------------------------------------------------------


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        if math.isnan(value):
            return low
    except Exception:
        return low
    return max(low, min(high, float(value)))


def float_or(value: Any, default: float) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def round_float(value: Any, digits: int = 4) -> float:
    return round(float_or(value, 0.0), digits)


def get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def get_from_obj_or_dict(obj: Any, name: str, default: Any = None) -> Any:
    return get_attr(obj, name, default)


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


def unique_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def normalize_budget(value: Any) -> WorkspaceBudgetMode:
    text = str(value or "normal").lower()
    if text in ("fast", "normal", "deep", "reflection"):
        return text  # type: ignore[return-value]
    return "normal"


def normalize_privacy(value: Any) -> PrivacyLevel:
    text = str(value or "normal").lower()
    if text in ("public", "normal", "private", "sensitive"):
        return text  # type: ignore[return-value]
    return "normal"


def compact_text(text: Any, max_chars: int = 240) -> str:
    s = " ".join(str(text or "").strip().split())
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if is_dataclass(content):
        try:
            data = asdict(content)
            return compact_text(json.dumps(safe_serialize(data), ensure_ascii=False), 320)
        except Exception:
            return compact_text(repr(content), 320)
    if isinstance(content, dict):
        return compact_text(json.dumps(safe_serialize(content), ensure_ascii=False), 320)
    return compact_text(repr(content), 320)


def safe_serialize(value: Any) -> Any:
    """Serialize best-effort cho debug mà không nổ vì object lạ."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [safe_serialize(v) for v in list(value)]
    if isinstance(value, dict):
        return {str(k): safe_serialize(v) for k, v in value.items()}
    if is_dataclass(value):
        try:
            return safe_serialize(asdict(value))
        except Exception:
            pass
    # Object thường: lấy vài field an toàn nếu có.
    data: dict[str, Any] = {}
    for name in (
        "id",
        "claim",
        "label",
        "description",
        "confidence",
        "priority",
        "reason",
        "summary",
        "source",
        "tags",
    ):
        if hasattr(value, name):
            data[name] = safe_serialize(getattr(value, name))
    if data:
        return data
    return repr(value)


def stable_suffix(text: Any, index: int = 0) -> str:
    raw = str(text or f"item_{index}")
    h = 2166136261
    for ch in raw[:160]:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h:08x}_{index}"


def normalize_text_for_similarity(text: str) -> str:
    text = str(text or "").lower()
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch.isspace():
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def jaccard_similarity(a: str, b: str) -> float:
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def estimate_tokens(text: str) -> int:
    # Ước lượng thô, đủ cho context pressure. Không cần mang tokenizer vào đây.
    s = str(text or "")
    if not s:
        return 0
    return max(1, int(len(s) / 3.0) + s.count("\n") * 2)


def count_by_kind(items: Sequence[WorkspaceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def count_suppression(items: Sequence[SuppressedWorkspaceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.reason.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def first_tag_after(tags: Sequence[str], prefix: str) -> Optional[str]:
    found = False
    for tag in tags:
        if found:
            return tag
        if tag == prefix:
            found = True
    return None


__all__ = [
    "WorkspaceItem",
    "SuppressedWorkspaceItem",
    "WorkspaceRisk",
    "WorkspaceSocialHypothesis",
    "WorkspacePromptPacket",
    "WorkspaceFrame",
    "GlobalWorkspaceConfig",
    "GlobalWorkspaceEngine",
    "WorkspaceSuppressionReason",
    "broadcast_workspace",
]
