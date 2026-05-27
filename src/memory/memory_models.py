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

    def to_state_commit_request(self) -> Any:
        """
        Chuyển sang StateCommitRequest của project nếu import được.

        Nếu shape trong project khác, sửa đúng một hàm này, đừng để policy bị dính
        trực tiếp vào memory store. Đó là cách người văn minh tránh tạo thêm bãi rác.
        """
        payload = {
            "target": self.target.value,
            "kind": self.kind.value,
            "claim": self.claim,
            "surface": self.surface,
            "confidence": self.confidence,
            "importance": self.importance,
            "source": self.source,
            "permission": self.permission,
            "surface_mode": self.surface_mode.value,
            "decay": self.decay.value,
            "evidence": list(self.evidence),
            "metadata": dict(self.metadata),
        }

        try:
            from src.core.evidence import StateCommitRequest  # type: ignore

            try:
                return StateCommitRequest(
                    target=self.target.value,
                    payload=payload,
                    confidence=self.confidence,
                    reason=f"memory_commit_policy:{self.kind.value}",
                    evidence_ids=list(self.evidence),
                )
            except TypeError:
                return StateCommitRequest(
                    target=self.target.value,
                    data=payload,
                    confidence=self.confidence,
                    reason=f"memory_commit_policy:{self.kind.value}",
                )
        except Exception:
            return payload


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
