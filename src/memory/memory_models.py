from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MemoryTarget(str, Enum):
    """Loại kho nhớ mà một fact nên đi vào."""

    SEMANTIC = "semantic_memory"
    EPISODIC = "episodic_memory"
    PROCEDURAL = "procedural_memory"
    EVENT_LEDGER = "event_ledger"
    REPAIR = "repair_memory"


class SurfaceMode(str, Enum):
    """Cách ký ức được phép hiện ra ngoài khi recall."""

    EXACT = "exact"
    GIST = "gist"
    SEMANTIC = "semantic"
    UNCERTAIN = "uncertain"
    REFUSE = "refuse"


class DecayPolicy(str, Enum):
    """Độ bền của ký ức."""

    STABLE = "stable"
    SESSION = "session"
    SHORT = "short"
    DECAYING = "decaying"


class MemoryKind(str, Enum):
    """Nhãn nghĩa cấp cao, tránh để các tầng sau phải đoán từ text thô."""

    USER_NAME = "user_identity.name"
    USER_BIRTH_MONTH = "user_identity.birth_month"
    USER_RESPONSE_STYLE = "user_preference.response_style"
    SESSION_MEMORY_TEST = "session.memory_test"
    USER_GENERAL_TOPIC = "user.general_topic"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MemoryCommitDecision:
    """
    Quyết định commit một mảnh thông tin.

    Đây không phải bản ghi memory cuối cùng. Nó là request có policy rõ:
    lưu vào đâu, mặt ngoài hiện thế nào, decay thế nào, vì sao được lưu.
    """

    target: MemoryTarget
    kind: MemoryKind
    claim: str
    surface: str
    confidence: float
    importance: float
    source: str = "user_text"
    permission: str = "user_provided"
    surface_mode: SurfaceMode = SurfaceMode.GIST
    decay: DecayPolicy = DecayPolicy.DECAYING
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_state_commit_request(
        self,
        *,
        storage_permission: bool = True,
        permission_required: bool = False,
    ) -> Any:
        """
        Chuyển sang StateCommitRequest của project nếu import được.

        Nếu shape trong project khác, sửa đúng một hàm này, đừng để policy bị dính
        trực tiếp vào memory store. Đó là cách người văn minh tránh tạo thêm bãi rác.
        """
        metadata = dict(self.metadata)
        metadata.setdefault("memory_kind", self.kind.value)
        metadata.setdefault("surface_mode", self.surface_mode.value)
        metadata.setdefault("importance", self.importance)
        metadata.setdefault("source", "MemoryCommitPolicy")
        metadata.setdefault("permission", self.permission)
        if self.target == MemoryTarget.SEMANTIC:
            metadata.setdefault("semantic_source", "explicit_user_statement")
            metadata.setdefault("source_grounded", True)

        return {
            "target": self.target.value,
            "content": _commit_content_from_decision(self, metadata),
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence),
            "permission_required": bool(permission_required),
            "storage_permission": bool(storage_permission),
            "decay_policy": _state_decay_from_memory_decay(self.decay),
            "reason": f"memory_commit_policy:{self.kind.value}",
            "source_module": "MemoryCommitPolicy",
            "tags": [self.kind.value, self.target.value],
            "metadata": metadata,
        }


def _state_decay_from_memory_decay(decay: DecayPolicy) -> str:
    if decay == DecayPolicy.STABLE:
        return "slow"
    if decay == DecayPolicy.SHORT:
        return "fast"
    if decay == DecayPolicy.SESSION:
        return "session_only"
    return "normal"


def _commit_content_from_decision(
    decision: MemoryCommitDecision,
    metadata: dict[str, Any],
) -> Any:
    if decision.target == MemoryTarget.SEMANTIC:
        return {
            "fact": decision.claim,
            "source": str(metadata.get("semantic_source") or "explicit_user_statement"),
            "kind": decision.kind.value,
            "surface": decision.surface,
            "value": metadata.get("value"),
        }
    return decision.claim


@dataclass(frozen=True)
class RecallRequest:
    """Yêu cầu recall đã được phân loại trước khi đụng tới memory thật."""

    mode: SurfaceMode
    kind: MemoryKind = MemoryKind.UNKNOWN
    ordinal: Optional[int] = None
    target_role: str = "user"
    asks_count: bool = False
    asks_longest: bool = False
    asks_question_only: bool = False
    raw_text: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class RecallAnswer:
    """Câu trả lời recall đã qua policy, có confidence và trace để debug."""

    text: str
    confidence: float
    source: str
    surface_mode: SurfaceMode
    debug_trace: str
    metadata: dict[str, Any] = field(default_factory=dict)
