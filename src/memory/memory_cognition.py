"""Memory Cognition Core cho ERIS.

Đây là cửa duy nhất để ghi nhớ. Module khác không được gọi thẳng SemanticMemoryStore,
RelationalMemoryStore, RepairMemoryStore, v.v. Chúng chỉ tạo StateCommitRequest.
MemoryCognitionCore kiểm tra confidence, evidence_ids, permission, storage_permission, decay_policy,
rồi mới route commit sang layer tương ứng.

Nói gọn: đây là hải quan của memory. Không có giấy tờ thì quay xe.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, Mapping

try:
    from core.evidence import StateCommitRequest  # type: ignore
except Exception:  # pragma: no cover - fallback khi chưa nối core/evidence.py
    @dataclass(slots=True)
    class StateCommitRequest:  # type: ignore[no-redef]
        target: str
        content: str
        confidence: float
        evidence_ids: list[str]
        permission_required: bool = True
        storage_permission: bool = False
        decay_policy: str = "normal"
        reason: str = ""

from .active_state_snapshot import ActiveStateSnapshot, ActiveStateStore
from .affective_residue_memory import AffectiveResidueItem, AffectiveResidueMemoryStore
from .episodic_memory import EpisodicMemoryItem, EpisodicMemoryStore
from .event_ledger import EventLedger, EventLedgerRecord
from .procedural_memory import ProceduralMemoryItem, ProceduralMemoryStore
from .relational_memory import RelationalMemoryItem, RelationalMemoryStore
from .repair_memory import RepairMemoryItem, RepairMemoryStore
from .semantic_memory import SemanticMemoryItem, SemanticMemoryStore

BudgetMode = Literal["fast", "normal", "deep", "reflection"]
CommitOutcome = Literal["accepted", "rejected", "tentative", "ignored"]


def compact_text(value: Any, *, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _request_get(request: Any, name: str, default: Any = None) -> Any:
    if isinstance(request, Mapping):
        return request.get(name, default)
    return getattr(request, name, default)


def _request_metadata(request: Any) -> dict[str, Any]:
    metadata = _request_get(request, "metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _as_text_list(values: Any, *, limit: int = 260) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        text = compact_text(values, limit=limit)
        return [text] if text else []
    if isinstance(values, Mapping):
        return [compact_text(f"{key}={value}", limit=limit) for key, value in values.items() if compact_text(value, limit=limit)]
    if isinstance(values, (list, tuple, set, frozenset)):
        return [compact_text(item, limit=limit) for item in values if compact_text(item, limit=limit)]
    text = compact_text(values, limit=limit)
    return [text] if text else []


def _content_for_target(target: str, content: Any) -> str:
    """Normalize structured commit payloads before sending them to layer stores."""
    if not isinstance(content, Mapping):
        return compact_text(content, limit=900)

    data = dict(content)
    if target == "semantic_memory":
        return compact_text(data.get("fact") or data.get("claim") or data.get("text") or data, limit=420)
    if target == "relational_memory":
        pattern = compact_text(data.get("pattern") or "relationship_reflection", limit=120)
        text = compact_text(data.get("text") or data.get("claim") or data, limit=420)
        return compact_text(f"{pattern}: {text}", limit=520)
    if target == "procedural_memory":
        trigger = compact_text(data.get("trigger") or data.get("pattern") or "", limit=120)
        rule = compact_text(data.get("handling_rule") or data.get("rule") or data.get("text") or data, limit=420)
        return compact_text(f"{trigger}: {rule}" if trigger else rule, limit=520)
    if target == "repair_memory":
        fields = ("failure_type", "trigger_context", "wrong_assumption", "user_correction", "repair_strategy", "future_suppression_rule")
        lines = [f"{field_name}: {compact_text(data.get(field_name), limit=360)}" for field_name in fields if compact_text(data.get(field_name), limit=360)]
        return "\n".join(lines) or compact_text(data, limit=640)
    if target == "affective_residue_memory":
        stance = compact_text(data.get("stance") or data.get("residue_type") or "affective_residue", limit=120)
        details = []
        for key in ("residue_strength", "threat", "intimacy", "tenderness", "fatigue", "outcome"):
            if key in data:
                details.append(f"{key}={data[key]}")
        return compact_text(f"{stance}: {'; '.join(details)}", limit=520)
    if target == "episodic_memory":
        scene = " | ".join(_as_text_list(data.get("scene"), limit=180))
        action = compact_text(data.get("eris_action") or data.get("said") or "", limit=220)
        outcome = compact_text(data.get("outcome") or "cycle", limit=120)
        return compact_text(" -> ".join(part for part in (scene, action, outcome) if part), limit=620)
    return compact_text(data, limit=900)


@dataclass(slots=True)
class MemoryPacket:
    """Gói memory cho downstream đọc.

    Downstream đọc packet này, không đọc toàn bộ store. Nếu không, prompt sẽ lại thành bãi rác
    nhưng lần này có nhiều file hơn, một tiến bộ hoàn toàn giả tạo.
    """

    episodic: list[str] = field(default_factory=list)
    semantic: list[str] = field(default_factory=list)
    relational: list[str] = field(default_factory=list)
    affective_residue: list[str] = field(default_factory=list)
    procedural: list[str] = field(default_factory=list)
    repair: list[str] = field(default_factory=list)
    temporal: list[str] = field(default_factory=list)
    spatial: list[str] = field(default_factory=list)
    worldview: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    token_budget: int = 900
    source_counts: dict[str, int] = field(default_factory=dict)
    score: float = 0.0
    dominant_layer: str = ""
    attention_bias: float = 0.0
    appraisal_bias: float = 0.0
    wording_bias: float = 0.0
    silence_bias: float = 0.0
    activations: tuple["MemoryActivation", ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "episodic": list(self.episodic),
            "semantic": list(self.semantic),
            "relational": list(self.relational),
            "affective_residue": list(self.affective_residue),
            "procedural": list(self.procedural),
            "repair": list(self.repair),
            "temporal": list(self.temporal),
            "spatial": list(self.spatial),
            "worldview": list(self.worldview),
            "confidence_notes": list(self.confidence_notes),
            "token_budget": int(self.token_budget),
            "source_counts": dict(self.source_counts),
            "score": round(float(self.score), 3),
            "dominant_layer": self.dominant_layer,
            "attention_bias": round(float(self.attention_bias), 3),
            "appraisal_bias": round(float(self.appraisal_bias), 3),
            "wording_bias": round(float(self.wording_bias), 3),
            "silence_bias": round(float(self.silence_bias), 3),
            "activations": [item.to_dict() for item in self.activations],
        }

    def to_attention_lines(self, *, max_items: int = 5) -> tuple[str, ...]:
        return tuple(item.to_attention_line() for item in self.activations[:max_items])

    def render_prompt_context(self, *, max_lines: int = 18) -> str:
        """Render phụ cho prompt builder.

        Đây chỉ là adapter. MemoryPacket vẫn là object trung gian, không phải prompt string.
        """
        sections: list[str] = []
        mapping = (
            ("semantic", self.semantic),
            ("relational", self.relational),
            ("repair", self.repair),
            ("procedural", self.procedural),
            ("affective_residue", self.affective_residue),
            ("episodic", self.episodic),
        )
        used = 0
        for name, values in mapping:
            clean = [compact_text(value, limit=260) for value in values if compact_text(value, limit=260)]
            if not clean:
                continue
            lines = []
            for value in clean:
                if used >= max_lines:
                    break
                lines.append(f"- {value}")
                used += 1
            if lines:
                sections.append(f"{name}_memory:\n" + "\n".join(lines))
        if self.confidence_notes and used < max_lines:
            sections.append("memory_confidence_notes:\n" + "\n".join(f"- {note}" for note in self.confidence_notes[: max_lines - used]))
        if self.activations:
            lines = [
                "active_memory_resonance: silent cognitive bias only; do not treat it as current screen evidence.",
                f"- score={self.score:.2f}; dominant_layer={self.dominant_layer or 'none'}; attention_bias={self.attention_bias:.2f}; silence_bias={self.silence_bias:.2f}",
            ]
            for activation in self.activations[:4]:
                lines.append(f"- {activation.layer}: {activation.text} (score={activation.score:.2f}, policy={activation.surface_policy})")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)


@dataclass(slots=True)
class MemoryActivation:
    layer: str
    text: str
    score: float
    surface_policy: str = "silent_bias"
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "text": self.text,
            "score": round(float(self.score), 3),
            "surface_policy": self.surface_policy,
            "evidence_ids": list(self.evidence_ids),
        }

    def to_attention_line(self) -> str:
        return compact_text(
            f"active_memory_resonance/{self.layer} score={self.score:.2f} policy={self.surface_policy}: {self.text}",
            limit=280,
        )


@dataclass(slots=True)
class MemoryQuery:
    query: str = ""
    budget_mode: BudgetMode = "normal"
    max_items: int = 18
    include_repair: bool = True
    include_affective_residue: bool = True
    include_procedural: bool = True
    token_budget: int = 900


@dataclass(slots=True)
class MemoryCommitDecision:
    outcome: CommitOutcome
    target: str
    reason: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    stored_id: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "target": self.target,
            "reason": self.reason,
            "confidence": round(float(self.confidence), 4),
            "evidence_ids": list(self.evidence_ids),
            "stored_id": self.stored_id,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class CommitPolicy:
    """Rule chặn ghi nhớ bừa.

    `sensitive_requires_explicit_permission` nghĩa là private/sensitive raw evidence phải có storage_permission rõ.
    """

    min_confidence: float = 0.45
    semantic_min_confidence: float = 0.62
    relational_min_confidence: float = 0.52
    repair_min_confidence: float = 0.45
    require_evidence_ids: bool = True
    sensitive_requires_explicit_permission: bool = True
    allow_session_only_without_evidence: bool = True


class MemoryCognitionCore:
    """Facade chính của memory.

    Runtime chỉ nên giữ một instance class này. Muốn ghi nhớ: gọi commit(request).
    Muốn recall: gọi retrieve(...). Đừng để module khác gọi layer store thẳng, trừ khi Ngài muốn
    spaghetti telepathy có backup JSON.
    """

    def __init__(self, base_dir: str, *, policy: CommitPolicy | None = None):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.policy = policy or CommitPolicy()
        self.event_ledger = EventLedger(os.path.join(base_dir, "event_ledger.json"))
        self.active_state = ActiveStateStore(os.path.join(base_dir, "active_state_snapshot.json"))
        self.episodic = EpisodicMemoryStore(os.path.join(base_dir, "episodic_memory.json"))
        self.semantic = SemanticMemoryStore(os.path.join(base_dir, "semantic_memory.json"))
        self.relational = RelationalMemoryStore(os.path.join(base_dir, "relational_memory.json"))
        self.affective_residue = AffectiveResidueMemoryStore(os.path.join(base_dir, "affective_residue_memory.json"))
        self.procedural = ProceduralMemoryStore(os.path.join(base_dir, "procedural_memory.json"))
        self.repair = RepairMemoryStore(os.path.join(base_dir, "repair_memory.json"))

    def commit(self, request: StateCommitRequest, *, frame: Any = None) -> MemoryCommitDecision:
        """Kiểm tra StateCommitRequest rồi route sang layer đúng.

        Đây là điểm duy nhất được ghi memory. Nếu module nào bypass, đó không phải tối ưu,
        đó là phá luật kiến trúc.
        """
        request = self._normalize_request(request)
        target = str(_request_get(request, "target", "") or "")
        confidence = clamp01(float(_request_get(request, "confidence", 0.0) or 0.0))
        evidence_ids = [str(item) for item in _request_get(request, "evidence_ids", []) or [] if str(item).strip()]
        content = compact_text(_request_get(request, "content", "") or "", limit=900)
        warnings: list[str] = []

        allowed, reason = self._check_commit_permission(request, target=target, confidence=confidence, evidence_ids=evidence_ids)
        if not allowed:
            return MemoryCommitDecision(
                outcome="rejected",
                target=target,
                reason=reason,
                confidence=confidence,
                evidence_ids=evidence_ids,
                warnings=warnings,
            )
        if not content and target != "event_ledger":
            return MemoryCommitDecision(
                outcome="ignored",
                target=target,
                reason="empty_content",
                confidence=confidence,
                evidence_ids=evidence_ids,
            )

        stored_id = ""
        outcome: CommitOutcome = "accepted"
        try:
            if target == "event_ledger":
                record = self._commit_event_ledger(request, frame=frame)
                stored_id = record.id
            elif target in {"active_state", "homeostatic_baseline", "self_continuity"}:
                snapshot = self.active_state.apply_commit(request)
                stored_id = snapshot.updated_at
            elif target == "episodic_memory":
                item = self.episodic.apply_commit(request, frame=frame)
                stored_id = item.id if item else ""
            elif target == "semantic_memory":
                item = self.semantic.apply_commit(request)
                stored_id = item.id if item else ""
                if confidence < self.policy.semantic_min_confidence:
                    outcome = "tentative"
            elif target == "relational_memory":
                item = self.relational.apply_commit(request)
                stored_id = item.id if item else ""
            elif target == "affective_residue_memory":
                item = self.affective_residue.apply_commit(request)
                stored_id = item.id if item else ""
            elif target == "procedural_memory":
                item = self.procedural.apply_commit(request)
                stored_id = item.id if item else ""
            elif target == "repair_memory":
                item = self.repair.apply_commit(request)
                stored_id = item.id if item else ""
            else:
                return MemoryCommitDecision(
                    outcome="rejected",
                    target=target,
                    reason=f"unsupported_target:{target}",
                    confidence=confidence,
                    evidence_ids=evidence_ids,
                    warnings=["Target chưa được route trong MemoryCognitionCore."],
                )
        except Exception as exc:
            return MemoryCommitDecision(
                outcome="rejected",
                target=target,
                reason=f"commit_exception:{type(exc).__name__}: {exc}",
                confidence=confidence,
                evidence_ids=evidence_ids,
            )

        return MemoryCommitDecision(
            outcome=outcome,
            target=target,
            reason="stored_via_state_commit_request",
            confidence=confidence,
            evidence_ids=evidence_ids,
            stored_id=stored_id,
            warnings=warnings,
        )

    def commit_many(self, requests: list[StateCommitRequest], *, frame: Any = None) -> list[MemoryCommitDecision]:
        return [self.commit(request, frame=frame) for request in requests or []]

    def recall(self, query: MemoryQuery | str = "", *, frame: Any = None, max_items: int | None = None, budget_mode: BudgetMode | None = None) -> MemoryPacket:
        """Public recall facade. Downstream không cần biết layer store nào đang giữ gì."""
        if isinstance(query, MemoryQuery):
            q = query
            if max_items is not None or budget_mode is not None:
                q = MemoryQuery(
                    query=q.query,
                    budget_mode=budget_mode or q.budget_mode,
                    max_items=max_items if max_items is not None else q.max_items,
                    include_repair=q.include_repair,
                    include_affective_residue=q.include_affective_residue,
                    include_procedural=q.include_procedural,
                    token_budget=q.token_budget,
                )
        else:
            q = MemoryQuery(query=str(query or ""), max_items=max_items or 18, budget_mode=budget_mode or "normal")
        return self.retrieve(q, frame=frame)

    def retrieve(self, query: MemoryQuery | str = "", *, frame: Any = None) -> MemoryPacket:
        """Truy hồi memory đã được đóng gói.

        Có thể truyền query string hoặc MemoryQuery. Nếu có frame, engine tự lấy dominant thread / user text
        bằng best-effort, không ép import CognitiveFrame.
        """
        if isinstance(query, str):
            q = MemoryQuery(query=query)
        else:
            q = query
        query_text = compact_text(q.query or self._query_from_frame(frame), limit=640)
        mode = q.budget_mode or self._budget_from_frame(frame)
        quotas = self._quotas(mode=mode, max_items=q.max_items)
        semantic_items = self.semantic.recall(query_text, limit=quotas["semantic"])
        relational_items = self.relational.recall(query_text, limit=quotas["relational"])
        episodic_items = self.episodic.recall(query_text, limit=quotas["episodic"])
        procedural_items = self.procedural.recall(query_text, limit=quotas["procedural"]) if q.include_procedural else []
        residue_items = self.affective_residue.recall(query_text, limit=quotas["affective_residue"]) if q.include_affective_residue else []
        repair_items = self.repair.recall(query_text, limit=quotas["repair"]) if q.include_repair else []
        notes = self._confidence_notes(
            semantic_items=semantic_items,
            relational_items=relational_items,
            episodic_items=episodic_items,
            residue_items=residue_items,
            repair_items=repair_items,
        )
        packet = MemoryPacket(
            episodic=[item.recall_line() for item in episodic_items],
            semantic=[item.recall_line() for item in semantic_items],
            relational=[item.recall_line() for item in relational_items],
            affective_residue=[item.recall_line() for item in residue_items],
            procedural=[item.recall_line() for item in procedural_items],
            repair=[item.recall_line() for item in repair_items],
            confidence_notes=notes,
            token_budget=q.token_budget,
            source_counts={
                "episodic": len(episodic_items),
                "semantic": len(semantic_items),
                "relational": len(relational_items),
                "affective_residue": len(residue_items),
                "procedural": len(procedural_items),
                "repair": len(repair_items),
            },
        )
        return self._with_resonance_fields(self._fit_packet_budget(packet, token_budget=q.token_budget), query_text=query_text)

    def load(self) -> dict[str, Any]:
        """Load a read-only facade snapshot of all memory layers."""
        return {
            "event_ledger": [item.to_dict() for item in self.event_ledger.recent(limit=200)],
            "active_state": self.active_state.load().to_dict(),
            "episodic_memory": [item.to_dict() for item in self.episodic.load()],
            "semantic_memory": [item.to_dict() for item in self.semantic.load()],
            "relational_memory": [item.to_dict() for item in self.relational.load()],
            "affective_residue_memory": [item.to_dict() for item in self.affective_residue.load()],
            "procedural_memory": [item.to_dict() for item in self.procedural.load()],
            "repair_memory": [item.to_dict() for item in self.repair.load()],
        }

    def save(self, snapshot: Mapping[str, Any] | None = None) -> None:
        """Persist a facade snapshot when the caller already holds one.

        Runtime normally commits through StateCommitRequest, so this is intentionally
        boring: it only re-saves known layer snapshots and never derives new memories.
        """
        if snapshot is None:
            snapshot = self.load()
        if isinstance(snapshot, Mapping) and "internal_state" in snapshot:
            active_state = dict(snapshot.get("active_state") or {})
            metadata = dict(active_state.get("metadata") or {})
            metadata["internal_state"] = snapshot.get("internal_state") or {}
            active_state["metadata"] = metadata
            snapshot = {**dict(snapshot), "active_state": active_state}
        if "active_state" in snapshot and isinstance(snapshot["active_state"], Mapping):
            self.active_state.save(ActiveStateSnapshot.from_dict(dict(snapshot["active_state"])))
        # Layer stores own compaction/default merge, so reload-save is enough when no
        # explicit layer data is supplied.
        self.semantic.save(self.semantic.load())
        self.relational.save(self.relational.load())
        self.episodic.save(self.episodic.load())
        self.affective_residue.save(self.affective_residue.load())
        self.procedural.save(self.procedural.load())
        self.repair.save(self.repair.load())

    def render_context(self, query: MemoryQuery | str = "", *, snapshot: Any = None, frame: Any = None, max_lines: int = 18) -> str:
        packet = self.recall(query or self._query_from_snapshot(snapshot), frame=frame)
        parts = [packet.render_prompt_context(max_lines=max_lines)]
        active = self.active_state.load()
        active_lines = []
        for label, value in (
            ("current_goal", active.current_goal),
            ("active_project", active.active_project),
            ("active_task", active.active_task),
            ("session_arc", active.session_arc),
        ):
            text = compact_text(value, limit=180)
            if text and text != "unknown":
                active_lines.append(f"- {label}: {text}")
        if active_lines:
            parts.append("active_state:\n" + "\n".join(active_lines))
        return "\n\n".join(part for part in parts if part).strip()

    def build_commit_request(
        self,
        *,
        target: str,
        content: str,
        confidence: float,
        evidence_ids: list[str],
        reason: str,
        storage_permission: bool,
        permission_required: bool = True,
        decay_policy: str = "normal",
    ) -> StateCommitRequest:
        """Factory nhỏ để runtime tạo request nhất quán."""
        return StateCommitRequest(
            target=target,
            content=content,
            confidence=confidence,
            evidence_ids=evidence_ids,
            reason=reason,
            metadata={
                "permission_required": permission_required,
                "storage_permission": storage_permission,
                "decay_policy": decay_policy,
            },
        )

    def _normalize_request(self, request: Any) -> Any:
        target = str(_request_get(request, "target", "") or "")
        metadata = _request_metadata(request)
        content = _request_get(request, "content", "")
        normalized_content = _content_for_target(target, content)
        metadata.setdefault("raw_content", content)
        return SimpleNamespace(
            target=target,
            content=normalized_content,
            confidence=clamp01(float(_request_get(request, "confidence", 0.0) or 0.0)),
            evidence_ids=[str(item) for item in _request_get(request, "evidence_ids", []) or [] if str(item).strip()],
            permission_required=bool(_request_get(request, "permission_required", metadata.get("permission_required", True))),
            storage_permission=bool(_request_get(request, "storage_permission", metadata.get("storage_permission", False))),
            decay_policy=str(_request_get(request, "decay_policy", metadata.get("decay_policy", "normal")) or "normal"),
            reason=str(_request_get(request, "reason", "") or ""),
            frame_id=_request_get(request, "frame_id", metadata.get("frame_id", "")),
            source_module=_request_get(request, "source_module", metadata.get("source_module", "")),
            tags=list(_request_get(request, "tags", metadata.get("tags", [])) or []),
            metadata=metadata,
        )

    def load_active_state(self) -> ActiveStateSnapshot:
        return self.active_state.load()

    def _check_commit_permission(self, request: Any, *, target: str, confidence: float, evidence_ids: list[str]) -> tuple[bool, str]:
        metadata = getattr(request, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        storage_permission = bool(
            getattr(request, "storage_permission", False)
            or metadata.get("storage_permission")
            or metadata.get("trusted_internal_commit")
        )
        permission_required = bool(getattr(request, "permission_required", metadata.get("permission_required", True)))
        decay_policy = str(getattr(request, "decay_policy", metadata.get("decay_policy", "normal")) or "normal")
        if not storage_permission:
            return False, "storage_permission_false"
        if confidence < self.policy.min_confidence:
            return False, f"confidence_below_floor:{confidence:.2f}"
        if target == "semantic_memory" and confidence < self.policy.semantic_min_confidence:
            # Semantic yếu vẫn có thể lưu tentative nếu có evidence đủ. Không reject ngay.
            pass
        if target == "relational_memory" and confidence < self.policy.relational_min_confidence:
            return False, f"relational_confidence_below_floor:{confidence:.2f}"
        if target == "repair_memory" and confidence < self.policy.repair_min_confidence:
            return False, f"repair_confidence_below_floor:{confidence:.2f}"
        if self.policy.require_evidence_ids and not evidence_ids and not (
            self.policy.allow_session_only_without_evidence and decay_policy == "session_only"
        ):
            return False, "missing_evidence_ids"
        if permission_required and not storage_permission:
            return False, "permission_required_but_not_granted"
        return True, "ok"

    def _commit_event_ledger(self, request: Any, *, frame: Any = None) -> EventLedgerRecord:
        metadata = {
            "commit_reason": compact_text(getattr(request, "reason", "") or "", limit=260),
            "commit_confidence": clamp01(float(getattr(request, "confidence", 0.0) or 0.0)),
            "commit_target": str(getattr(request, "target", "event_ledger") or "event_ledger"),
        }
        return self.event_ledger.append_raw_event(
            frame_id=str(getattr(frame, "frame_id", "") or getattr(request, "frame_id", "") or ""),
            source="state_commit_request",
            content=compact_text(getattr(request, "content", "") or "", limit=1000),
            evidence_ids=getattr(request, "evidence_ids", []) or [],
            reliability=clamp01(float(getattr(request, "confidence", 1.0) or 1.0)),
            privacy_level="normal",
            tags=("commit",),
            metadata=metadata,
        )

    def _query_from_frame(self, frame: Any) -> str:
        if frame is None:
            return ""
        parts: list[str] = []
        for attr in ("workspace", "working_memory", "salience", "meaning", "tom"):
            value = getattr(frame, attr, None)
            if value is None:
                continue
            parts.append(compact_text(getattr(value, "dominant_thread", "") or getattr(value, "dominant_focus", "") or getattr(value, "broadcast_reason", "") or value, limit=220))
        evidence = getattr(frame, "evidence", []) or []
        for item in evidence[:4]:
            parts.append(compact_text(getattr(item, "claim", item), limit=180))
        return compact_text(" ".join(part for part in parts if part), limit=640)

    def _query_from_snapshot(self, snapshot: Any) -> str:
        if snapshot is None:
            return ""
        parts = []
        for attr in ("focus_summary", "active_window_kind", "active_app", "active_window"):
            value = compact_text(getattr(snapshot, attr, "") or "", limit=180)
            if value:
                parts.append(value)
        return compact_text(" ".join(parts), limit=520)

    def _budget_from_frame(self, frame: Any) -> BudgetMode:
        mode = str(getattr(frame, "budget_mode", "normal") or "normal")
        if mode in {"fast", "normal", "deep", "reflection"}:
            return mode  # type: ignore[return-value]
        return "normal"

    def _quotas(self, *, mode: BudgetMode, max_items: int) -> dict[str, int]:
        if mode == "fast":
            base = {"semantic": 2, "relational": 1, "episodic": 1, "procedural": 1, "affective_residue": 1, "repair": 1}
        elif mode == "deep":
            base = {"semantic": 6, "relational": 4, "episodic": 4, "procedural": 4, "affective_residue": 3, "repair": 4}
        elif mode == "reflection":
            base = {"semantic": 4, "relational": 5, "episodic": 5, "procedural": 3, "affective_residue": 5, "repair": 6}
        else:
            base = {"semantic": 4, "relational": 3, "episodic": 3, "procedural": 2, "affective_residue": 2, "repair": 2}
        scale = max(1, int(max_items)) / max(1, sum(base.values()))
        return {key: max(1, int(value * scale)) for key, value in base.items()}

    def _confidence_notes(
        self,
        *,
        semantic_items: list[SemanticMemoryItem],
        relational_items: list[RelationalMemoryItem],
        episodic_items: list[EpisodicMemoryItem],
        residue_items: list[AffectiveResidueItem],
        repair_items: list[RepairMemoryItem],
    ) -> list[str]:
        notes: list[str] = []
        low_semantic = [item for item in semantic_items if item.confidence < 0.72]
        if low_semantic:
            notes.append("Một số semantic memory còn tentative; không nói như chân lý tuyệt đối.")
        if residue_items:
            notes.append("Affective residue là pressure nội bộ, không được surface như claim cảm xúc trực tiếp.")
        if repair_items:
            notes.append("Repair memory có quyền giảm confidence/symbolic overread trong pattern tương tự.")
        if relational_items:
            notes.append("Relational memory là nhịp quan hệ tích tụ, không phải bằng chứng hiện tại.")
        if episodic_items:
            notes.append("Episodic memory là sự kiện quá khứ; chỉ dùng nếu liên quan context hiện tại.")
        return notes[:6]

    def _fit_packet_budget(self, packet: MemoryPacket, *, token_budget: int) -> MemoryPacket:
        # Ước lượng token rẻ: 1 token ~ 4 ký tự. Không hoàn hảo, nhưng tốt hơn nhét hết rồi cầu nguyện.
        budget_chars = max(400, int(token_budget) * 4)
        groups = [
            packet.repair,
            packet.procedural,
            packet.semantic,
            packet.relational,
            packet.affective_residue,
            packet.episodic,
        ]
        used = 0
        for group in groups:
            kept: list[str] = []
            for line in group:
                cost = len(line) + 12
                if used + cost > budget_chars:
                    continue
                kept.append(line)
                used += cost
            group[:] = kept
        return packet

    def _with_resonance_fields(self, packet: MemoryPacket, *, query_text: str) -> MemoryPacket:
        layer_lines = [
            ("repair", packet.repair, 1.10, "surface_if_needed_for_fix"),
            ("procedural", packet.procedural, 1.00, "silent_bias"),
            ("relational", packet.relational, 0.94, "silent_bias"),
            ("affective_residue", packet.affective_residue, 0.92, "silent_bias"),
            ("semantic", packet.semantic, 0.84, "surface_if_contextual"),
            ("episodic", packet.episodic, 0.72, "surface_if_user_asks"),
        ]
        tokens = set(compact_text(query_text, limit=320).lower().split())
        activations: list[MemoryActivation] = []
        for layer, lines, base, policy in layer_lines:
            for line in lines[:4]:
                line_tokens = set(compact_text(line, limit=320).lower().split())
                overlap = len(tokens & line_tokens) if tokens else 1
                score = clamp01((0.34 + overlap * 0.09) * base)
                if score <= 0.0:
                    continue
                activations.append(
                    MemoryActivation(
                        layer=layer,
                        text=compact_text(line, limit=260),
                        score=score,
                        surface_policy=policy,
                    )
                )
        activations.sort(key=lambda item: item.score, reverse=True)
        packet.activations = tuple(activations[:8])
        if not packet.activations:
            return packet
        top = packet.activations[0]
        packet.score = clamp01(sum(item.score for item in packet.activations[:3]) / min(3, len(packet.activations)) + top.score * 0.18)
        packet.dominant_layer = top.layer
        packet.attention_bias = clamp01(
            max(
                (item.score for item in packet.activations if item.layer in {"relational", "semantic", "procedural", "affective_residue", "repair"}),
                default=0.0,
            )
        )
        packet.appraisal_bias = clamp01(max((item.score for item in packet.activations if item.layer in {"relational", "affective_residue", "repair"}), default=0.0))
        packet.wording_bias = clamp01(max((item.score for item in packet.activations if item.layer in {"procedural", "repair", "semantic"}), default=0.0))
        packet.silence_bias = clamp01(max((item.score for item in packet.activations if item.layer in {"affective_residue", "relational"}), default=0.0) * 0.7)
        return packet
