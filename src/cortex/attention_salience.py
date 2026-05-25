# -*- coding: utf-8 -*-
"""
cortex/attention_salience.py
============================

Selection backbone / anti-context-flood backbone cho ERIS Cognitive Pipeline.

Đây KHÔNG phải "attention hiện tại" kiểu gom vài keyword rồi chấm điểm cho vui.
File này là tầng [03] Attention & Salience Allocation trong PDF Grand Architecture:

    Evidence -> Attention/Salience -> Temporal/Homeostasis/WorkingMemory/Workspace

Vai trò chính:
- Nhận EvidenceItem từ CognitiveFrame.
- Biến mỗi evidence thành AttentionCandidate có điểm salience đa trục.
- Chọn dominant_focus và secondary_focuses.
- Đè bớt telemetry rác, event lặp, evidence mỏng, claim quá generic.
- Tạo danh sách selected_evidence để WorkingMemory/GlobalWorkspace dùng tiếp.
- Không gọi memory.py, không gọi meaning.py, không gọi LLM.

Luật kiến trúc:
- Attention không sở hữu chân lý.
- Attention chỉ nói: "cái này đáng được đưa lên workspace hơn cái kia".
- Attention không kết luận user buồn, không kết luận user né việc, không tự ghi memory.
- Mọi suy diễn sau đó phải đi qua MeaningHypothesis / ToM / Arbitration.

Cách gắn tối thiểu:

    engine = AttentionSalienceEngine()
    salience = engine.evaluate(frame)
    frame.salience = salience

Nếu CognitiveFrame có add_report(), engine sẽ tự ghi ModuleReport vào frame.
Nếu chưa có, nó vẫn trả SalienceFrame bình thường. Một chút tôn trọng với repo đang được phẫu thuật,
chuyện khá hiếm trong thế giới phần mềm.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence, cast


# =============================================================================
# 0. Import mềm
# =============================================================================
# File này cố ý ít phụ thuộc. Trong giai đoạn Ngài đang xây lại core, layout repo có thể là:
# - src/core/evidence.py
# - src/cortex/evidence.py
# - src/core/cognitive_frame.py
# - src/cortex/cognitive_frame.py
# Nếu import cứng, file sẽ chết vì khác layout. Đúng là Python thích biến tổ chức thư mục thành
# một môn tâm linh ứng dụng, nên ta import mềm.

try:  # cùng package cortex
    from .evidence import EvidenceItem, ModuleReport  # type: ignore
except Exception:  # pragma: no cover
    try:  # layout core
        from core.evidence import EvidenceItem, ModuleReport  # type: ignore
    except Exception:  # pragma: no cover
        EvidenceItem = Any  # type: ignore

        @dataclass(slots=True)
        class ModuleReport:  # type: ignore[no-redef]
            """Fallback tối thiểu khi repo chưa có ModuleReport thật."""

            module_name: str
            confidence: float
            pressure: float
            evidence_used: list[str]
            result: Any
            warnings: list[str] = field(default_factory=list)
            debug: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 1. Literal contracts
# =============================================================================

SignalSource = Literal[
    "user_chat",
    "active_window",
    "browser",
    "telemetry",
    "vision",
    "ocr",
    "body",
    "system_log",
    "memory",
    "time",
    "unknown",
]

SuppressionReason = Literal[
    "low_score",
    "low_confidence",
    "low_reliability",
    "generic_telemetry",
    "repeated_habituation",
    "false_alarm_likely",
    "privacy_filtered",
    "prompt_budget_overflow",
    "duplicate_semantic_family",
    "stale_signal",
    "weak_memory_echo",
    "selected_elsewhere",
]

AttentionFamily = Literal[
    "user_request",
    "technical_issue",
    "runtime_risk",
    "system_state",
    "body_state",
    "vision_observation",
    "memory_recall",
    "relational_signal",
    "identity_signal",
    "goal_signal",
    "affective_signal",
    "temporal_signal",
    "ambient_context",
    "unknown",
]

FocusKind = Literal[
    "chat",
    "code",
    "debug",
    "architecture",
    "runtime",
    "body",
    "memory",
    "relationship",
    "identity",
    "risk",
    "ambient",
    "unknown",
]


# =============================================================================
# 2. Helper nhỏ, xấu vừa đủ để hữu dụng
# =============================================================================

_WORD_RE = re.compile(r"[\wÀ-ỹ]+", flags=re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def now_ts() -> float:
    """Trả Unix timestamp hiện tại."""

    return time.time()


def clamp01(value: Any, default: float = 0.0) -> float:
    """Ép một giá trị số vào [0, 1].

    Tất cả score trong attention dùng cùng thang này để dễ debug.
    Nếu input bậy, trả default. Không nổ tung chỉ vì một module upstream trả None.
    Upstream đã lười thì downstream phải cẩn thận hơn, một thực tế đáng buồn.
    """

    try:
        number = float(value)
    except Exception:
        number = float(default)
    if not math.isfinite(number):
        number = float(default)
    return max(0.0, min(1.0, number))


def safe_float(value: Any, default: float = 0.0) -> float:
    """Chuyển value sang float an toàn."""

    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


def safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """Lấy attribute hoặc key dict mà không gây tai nạn."""

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def normalize_text(text: Any, *, max_len: int = 800) -> str:
    """Chuẩn hóa text cho scoring.

    Không bỏ dấu tiếng Việt vì dấu giúp phân biệt vài ngữ cảnh.
    Chỉ hạ chữ, gom whitespace, cắt dài.
    """

    raw = str(text or "")
    raw = raw.replace("\x00", " ")
    raw = _MULTI_SPACE_RE.sub(" ", raw).strip()
    if len(raw) > max_len:
        raw = raw[: max_len - 1] + "…"
    return raw


def tokenize(text: Any) -> set[str]:
    """Tách token đơn giản để tính overlap.

    Đây không phải semantic embedding. Nó chỉ đủ làm backbone nhẹ, không chặn việc
    sau này gắn embedding/reranker. Đừng biến attention phase 0 thành research paper,
    repo không cần thêm một con quái vật nữa.
    """

    normalized = normalize_text(text, max_len=1500).lower()
    return {m.group(0) for m in _WORD_RE.finditer(normalized) if len(m.group(0)) >= 2}


def stable_fingerprint(text: Any, *, prefix: str = "att") -> str:
    """Tạo fingerprint ổn định để nhận diện lặp.

    Không dùng hash() built-in vì Python randomizes hash giữa process.
    """

    normalized = normalize_text(text, max_len=1200).lower()
    digest = hashlib.blake2b(normalized.encode("utf-8", errors="ignore"), digest_size=8).hexdigest()
    return f"{prefix}.{digest}"


def to_plain(value: Any) -> Any:
    """Chuyển dataclass/object thành dạng JSON-friendly."""

    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def join_reason(parts: Iterable[str]) -> str:
    """Gom reason, bỏ phần rỗng."""

    clean = [str(p).strip() for p in parts if str(p or "").strip()]
    return "; ".join(clean) if clean else "no salient evidence"


def estimate_token_count(text: Any) -> int:
    """Ước lượng token rất thô bằng độ dài ký tự.

    Mục tiêu không phải đếm token chính xác, mà là chống context flood.
    Tokenizer thật có thể gắn sau. Còn bây giờ dùng xấp xỉ, vì xây hệ thống
    không nhất thiết phải tự bắn vào chân bằng dependency.
    """

    raw = str(text or "")
    return max(1, math.ceil(len(raw) / 4))


# =============================================================================
# 3. Cấu hình
# =============================================================================

@dataclass(slots=True)
class SalienceWeights:
    """Trọng số salience theo PDF.

    Công thức gốc trong PDF:
        novelty + urgency + goal_relevance + user_relevance + identity_relevance
        + relational_relevance + affective_charge + risk_relevance
        + unresolved_tension + recurrence_weight
        - habituation - false_alarm_likelihood

    Ở đây giữ đúng các trục đó, nhưng cho trọng số mềm để tune runtime.
    """

    novelty: float = 1.00
    urgency: float = 1.10
    goal_relevance: float = 1.05
    user_relevance: float = 1.20
    identity_relevance: float = 0.80
    relational_relevance: float = 0.85
    affective_charge: float = 0.75
    risk_relevance: float = 1.15
    unresolved_tension: float = 0.95
    recurrence_weight: float = 0.55
    reliability: float = 0.55
    confidence: float = 0.75
    habituation: float = 0.95
    false_alarm_likelihood: float = 1.05
    generic_penalty: float = 0.70


@dataclass(slots=True)
class AttentionSalienceConfig:
    """Cấu hình của AttentionSalienceEngine.

    Các giới hạn ở đây dùng để chống context flood:
    - không đưa quá nhiều evidence vào prompt
    - không cho telemetry rác chiếm workspace
    - không cho event lặp liên tục tạo cảm giác mới giả
    """

    max_candidates: int = 96
    max_selected_evidence: int = 12
    max_secondary_focuses: int = 6
    max_prompt_chars: int = 2200
    max_prompt_tokens: int = 550
    min_select_score: float = 0.32
    min_dominant_score: float = 0.38
    min_confidence: float = 0.10
    min_reliability: float = 0.10
    privacy_filter_sensitive: bool = True
    collapse_same_family: bool = True
    novelty_recent_window: int = 64
    stale_after_seconds: float = 15 * 60
    repeat_habituation_start: int = 2
    repeat_habituation_cap: int = 12
    generic_telemetry_score_cap: float = 0.30
    memory_echo_score_cap: float = 0.42
    dominant_focus_max_len: int = 120
    reason_max_len: int = 420
    weights: SalienceWeights = field(default_factory=SalienceWeights)

    def normalized(self) -> "AttentionSalienceConfig":
        """Trả bản config đã clamp vài field nguy hiểm."""

        clone = AttentionSalienceConfig(
            max_candidates=max(1, int(self.max_candidates)),
            max_selected_evidence=max(1, int(self.max_selected_evidence)),
            max_secondary_focuses=max(0, int(self.max_secondary_focuses)),
            max_prompt_chars=max(120, int(self.max_prompt_chars)),
            max_prompt_tokens=max(32, int(self.max_prompt_tokens)),
            min_select_score=clamp01(self.min_select_score),
            min_dominant_score=clamp01(self.min_dominant_score),
            min_confidence=clamp01(self.min_confidence),
            min_reliability=clamp01(self.min_reliability),
            privacy_filter_sensitive=bool(self.privacy_filter_sensitive),
            collapse_same_family=bool(self.collapse_same_family),
            novelty_recent_window=max(4, int(self.novelty_recent_window)),
            stale_after_seconds=max(10.0, safe_float(self.stale_after_seconds, 900.0)),
            repeat_habituation_start=max(1, int(self.repeat_habituation_start)),
            repeat_habituation_cap=max(2, int(self.repeat_habituation_cap)),
            generic_telemetry_score_cap=clamp01(self.generic_telemetry_score_cap),
            memory_echo_score_cap=clamp01(self.memory_echo_score_cap),
            dominant_focus_max_len=max(32, int(self.dominant_focus_max_len)),
            reason_max_len=max(80, int(self.reason_max_len)),
            weights=self.weights,
        )
        return clone


# =============================================================================
# 4. Data contracts
# =============================================================================

@dataclass(slots=True)
class SalienceFactorBreakdown:
    """Các trục điểm của một candidate.

    Đây là thứ giúp debug: vì sao evidence A được chọn còn evidence B bị chôn.
    Nếu không có breakdown, attention chỉ là một cái hộp đen chấm điểm bằng niềm tin.
    Nhân loại đã thử mô hình đó trong quản lý dự án và kết quả không đẹp.
    """

    novelty: float = 0.0
    urgency: float = 0.0
    goal_relevance: float = 0.0
    user_relevance: float = 0.0
    identity_relevance: float = 0.0
    relational_relevance: float = 0.0
    affective_charge: float = 0.0
    risk_relevance: float = 0.0
    unresolved_tension: float = 0.0
    recurrence_weight: float = 0.0
    reliability: float = 0.0
    confidence: float = 0.0
    habituation: float = 0.0
    false_alarm_likelihood: float = 0.0
    generic_penalty: float = 0.0
    final_score: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return cast(dict[str, float], asdict(self))


@dataclass(slots=True)
class AttentionCandidate:
    """Một evidence đã được attention chuẩn hóa để tranh suất lên workspace."""

    candidate_id: str
    evidence_id: str
    source_signal_id: str
    source: SignalSource
    claim: str
    timestamp: float
    confidence: float
    reliability: float
    privacy_level: str
    raw_or_inferred: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    family: AttentionFamily = "unknown"
    focus_kind: FocusKind = "unknown"
    fingerprint: str = ""
    text_tokens: tuple[str, ...] = field(default_factory=tuple)
    score: float = 0.0
    score_breakdown: SalienceFactorBreakdown = field(default_factory=SalienceFactorBreakdown)
    suppression_reason: Optional[SuppressionReason] = None
    selected: bool = False
    prompt_sayable: bool = True
    debug_notes: tuple[str, ...] = field(default_factory=tuple)

    def short_claim(self, max_len: int = 160) -> str:
        text = normalize_text(self.claim, max_len=max_len)
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "evidence_id": self.evidence_id,
            "source_signal_id": self.source_signal_id,
            "source": self.source,
            "claim": self.claim,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "reliability": self.reliability,
            "privacy_level": self.privacy_level,
            "raw_or_inferred": self.raw_or_inferred,
            "tags": list(self.tags),
            "family": self.family,
            "focus_kind": self.focus_kind,
            "fingerprint": self.fingerprint,
            "score": self.score,
            "score_breakdown": self.score_breakdown.to_dict(),
            "suppression_reason": self.suppression_reason,
            "selected": self.selected,
            "prompt_sayable": self.prompt_sayable,
            "debug_notes": list(self.debug_notes),
        }


@dataclass(slots=True)
class SuppressedSignal:
    """Evidence bị attention chặn hoặc không chọn."""

    evidence_id: str
    source: str
    claim: str
    score: float
    reason: SuppressionReason
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "claim": self.claim,
            "score": self.score,
            "reason": self.reason,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class PromptEvidenceItem:
    """Evidence được phép đưa vào prompt/context packet.

    Không phải candidate nào được chọn cũng nên đưa nguyên văn vào prompt.
    Sensitive/private evidence có thể dùng để điều tiết nội bộ nhưng không public-sayable.
    """

    evidence_id: str
    claim: str
    score: float
    source: str
    family: str
    confidence: float
    reliability: float
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_prompt_line(self) -> str:
        tags = f" tags={','.join(self.tags[:4])}" if self.tags else ""
        return (
            f"- [{self.evidence_id}] {self.claim} "
            f"(source={self.source}, score={self.score:.2f}, confidence={self.confidence:.2f}, reliability={self.reliability:.2f}{tags})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "claim": self.claim,
            "score": self.score,
            "source": self.source,
            "family": self.family,
            "confidence": self.confidence,
            "reliability": self.reliability,
            "tags": list(self.tags),
        }


@dataclass(slots=True)
class ContextFloodReport:
    """Báo cáo chống ngập context."""

    total_candidates: int = 0
    selected_count: int = 0
    suppressed_count: int = 0
    prompt_items_count: int = 0
    prompt_chars: int = 0
    prompt_tokens_estimate: int = 0
    generic_telemetry_suppressed: int = 0
    repeated_suppressed: int = 0
    privacy_suppressed: int = 0
    overflow_suppressed: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pressure(self) -> float:
        """Áp lực context flood trên [0,1]."""

        if self.total_candidates <= 0:
            return 0.0
        ratio = self.suppressed_count / max(1, self.total_candidates)
        budget_pressure = min(1.0, self.prompt_tokens_estimate / 550.0)
        return clamp01(0.55 * ratio + 0.45 * budget_pressure)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "selected_count": self.selected_count,
            "suppressed_count": self.suppressed_count,
            "prompt_items_count": self.prompt_items_count,
            "prompt_chars": self.prompt_chars,
            "prompt_tokens_estimate": self.prompt_tokens_estimate,
            "generic_telemetry_suppressed": self.generic_telemetry_suppressed,
            "repeated_suppressed": self.repeated_suppressed,
            "privacy_suppressed": self.privacy_suppressed,
            "overflow_suppressed": self.overflow_suppressed,
            "pressure": self.pressure,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class SalienceFrame:
    """Kết quả Attention & Salience Allocation.

    Các field đầu bám PDF. Các field sau mở rộng để nối WorkingMemory/Workspace.
    """

    dominant_focus: Optional[str] = None
    secondary_focuses: list[str] = field(default_factory=list)
    suppressed_signals: list[str] = field(default_factory=list)
    novelty: float = 0.0
    urgency: float = 0.0
    goal_relevance: float = 0.0
    user_relevance: float = 0.0
    identity_relevance: float = 0.0
    relational_relevance: float = 0.0
    affective_charge: float = 0.0
    risk_relevance: float = 0.0
    unresolved_tension: float = 0.0
    recurrence_weight: float = 0.0
    habituation: float = 0.0
    false_alarm_likelihood: float = 0.0
    broadcast_priority: float = 0.0
    reason: str = ""

    # Mở rộng thực dụng.
    selected_evidence_ids: list[str] = field(default_factory=list)
    selected_candidate_ids: list[str] = field(default_factory=list)
    dominant_evidence_id: Optional[str] = None
    dominant_family: AttentionFamily = "unknown"
    dominant_focus_kind: FocusKind = "unknown"
    candidates: list[AttentionCandidate] = field(default_factory=list)
    selected_candidates: list[AttentionCandidate] = field(default_factory=list)
    suppressed: list[SuppressedSignal] = field(default_factory=list)
    prompt_evidence: list[PromptEvidenceItem] = field(default_factory=list)
    context_flood: ContextFloodReport = field(default_factory=ContextFloodReport)
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def has_focus(self) -> bool:
        return bool(self.dominant_focus and self.broadcast_priority > 0.0)

    @property
    def workspace_ready(self) -> bool:
        """True nếu frame đủ tốt để WorkingMemory/Workspace xử lý tiếp."""

        return bool(self.selected_evidence_ids or self.dominant_focus)

    def prompt_context(self, *, max_lines: int = 8) -> str:
        """Render context ngắn cho prompt builder nếu cần.

        Prompt builder vẫn nên đọc `prompt_evidence`, không đọc toàn bộ candidates.
        """

        lines = [
            "AttentionSalience: selected evidence only; do not treat salience as truth.",
            f"dominant_focus={self.dominant_focus or 'none'}; priority={self.broadcast_priority:.2f}; family={self.dominant_family}; kind={self.dominant_focus_kind}.",
        ]
        for item in self.prompt_evidence[:max_lines]:
            lines.append(item.to_prompt_line())
        if self.context_flood.pressure >= 0.45:
            lines.append(
                f"context_flood_pressure={self.context_flood.pressure:.2f}; many low-value signals were suppressed."
            )
        return "\n".join(lines)

    def to_dict(self, *, include_candidates: bool = False) -> dict[str, Any]:
        data = {
            "dominant_focus": self.dominant_focus,
            "secondary_focuses": list(self.secondary_focuses),
            "suppressed_signals": list(self.suppressed_signals),
            "novelty": self.novelty,
            "urgency": self.urgency,
            "goal_relevance": self.goal_relevance,
            "user_relevance": self.user_relevance,
            "identity_relevance": self.identity_relevance,
            "relational_relevance": self.relational_relevance,
            "affective_charge": self.affective_charge,
            "risk_relevance": self.risk_relevance,
            "unresolved_tension": self.unresolved_tension,
            "recurrence_weight": self.recurrence_weight,
            "habituation": self.habituation,
            "false_alarm_likelihood": self.false_alarm_likelihood,
            "broadcast_priority": self.broadcast_priority,
            "reason": self.reason,
            "selected_evidence_ids": list(self.selected_evidence_ids),
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "dominant_evidence_id": self.dominant_evidence_id,
            "dominant_family": self.dominant_family,
            "dominant_focus_kind": self.dominant_focus_kind,
            "selected_candidates": [c.to_dict() for c in self.selected_candidates],
            "suppressed": [s.to_dict() for s in self.suppressed],
            "prompt_evidence": [p.to_dict() for p in self.prompt_evidence],
            "context_flood": self.context_flood.to_dict(),
            "warnings": list(self.warnings),
            "debug": to_plain(self.debug),
        }
        if include_candidates:
            data["candidates"] = [c.to_dict() for c in self.candidates]
        return data


@dataclass(slots=True)
class AttentionSalienceMemory:
    """Bộ nhớ nhẹ của AttentionSalienceEngine.

    Đây không phải long-term memory. Đây chỉ là rolling memory để biết signal nào đang lặp.
    Không ghi fact vào đây. Không suy diễn người dùng từ đây. Chỉ dùng chống "mỗi tick telemetry là
    một sự kiện trọng đại", căn bệnh kinh điển của agent non.
    """

    recent_fingerprints: list[str] = field(default_factory=list)
    fingerprint_counts: dict[str, int] = field(default_factory=dict)
    family_counts: dict[str, int] = field(default_factory=dict)
    last_seen_ts: dict[str, float] = field(default_factory=dict)
    last_dominant_focus: Optional[str] = None
    last_dominant_family: Optional[str] = None
    cycle_count: int = 0

    def mark_seen(self, candidates: Sequence[AttentionCandidate], *, max_recent: int = 64) -> None:
        self.cycle_count += 1
        for candidate in candidates:
            fp = candidate.fingerprint
            if not fp:
                continue
            self.recent_fingerprints.append(fp)
            self.fingerprint_counts[fp] = self.fingerprint_counts.get(fp, 0) + 1
            self.family_counts[candidate.family] = self.family_counts.get(candidate.family, 0) + 1
            self.last_seen_ts[fp] = candidate.timestamp
        if len(self.recent_fingerprints) > max_recent:
            self.recent_fingerprints = self.recent_fingerprints[-max_recent:]

    def repeat_count(self, fingerprint: str) -> int:
        return int(self.fingerprint_counts.get(fingerprint, 0))

    def family_repeat_count(self, family: str) -> int:
        return int(self.family_counts.get(family, 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_fingerprints": list(self.recent_fingerprints[-16:]),
            "fingerprint_counts_size": len(self.fingerprint_counts),
            "family_counts": dict(self.family_counts),
            "last_dominant_focus": self.last_dominant_focus,
            "last_dominant_family": self.last_dominant_family,
            "cycle_count": self.cycle_count,
        }


# =============================================================================
# 5. Classifier nhẹ cho family/kind
# =============================================================================

class SalienceClassifier:
    """Classifier nhẹ cho attention family và focus kind.

    Đây không phải MeaningHypothesis. Nó không được kết luận sâu.
    Nó chỉ gắn nhãn kỹ thuật để score và group evidence.
    """

    TECHNICAL_TOKENS = {
        "code",
        "python",
        "c#",
        "csharp",
        "godot",
        "runtime",
        "module",
        "class",
        "dataclass",
        "function",
        "bug",
        "error",
        "exception",
        "traceback",
        "compile",
        "json",
        "api",
        "llm",
        "pipeline",
        "architecture",
        "kiến",
        "trúc",
        "lỗi",
        "file",
        "repo",
        "debug",
        "fix",
    }
    RISK_TOKENS = {
        "error",
        "exception",
        "traceback",
        "failed",
        "crash",
        "panic",
        "warning",
        "security",
        "secret",
        "api key",
        "private",
        "sensitive",
        "mật khẩu",
        "token",
        "key",
    }
    RELATIONAL_TOKENS = {
        "sai",
        "không phải",
        "khong phai",
        "ngu",
        "dcm",
        "vl",
        "cảm ơn",
        "cam on",
        "đúng rồi",
        "dung roi",
        "ổn",
        "on",
        "ngon",
        "nịnh",
        "giận",
        "tức",
        "bực",
    }
    IDENTITY_TOKENS = {
        "eris",
        "ai",
        "chatbot",
        "waifu",
        "tool",
        "prompt",
        "persona",
        "roleplay",
        "cosplay",
        "thực thể",
        "runtime presence",
    }
    GOAL_TOKENS = {
        "mục tiêu",
        "goal",
        "đồ án",
        "project",
        "phase",
        "roadmap",
        "làm tiếp",
        "xây",
        "gắn",
        "nối",
        "core",
    }
    AFFECTIVE_TOKENS = {
        "bực",
        "cay",
        "stress",
        "mệt",
        "tức",
        "điên",
        "ngu quá",
        "khó chịu",
        "frustrated",
        "angry",
        "sad",
        "buồn",
    }
    BODY_TOKENS = {
        "body",
        "sprite",
        "godot",
        "animation",
        "motion",
        "gaze",
        "posture",
        "đứng",
        "đi",
        "ngồi",
        "leo",
    }
    MEMORY_TOKENS = {
        "memory",
        "ký ức",
        "ky uc",
        "remember",
        "recall",
        "episodic",
        "semantic",
        "long_term",
    }

    GENERIC_TELEMETRY_PATTERNS = (
        "active window is",
        "focus kind is",
        "there has been no input",
        "cpu",
        "ram",
        "window active",
        "mouse_move",
        "key_press",
        "scroll",
    )

    @classmethod
    def classify_family(cls, *, source: str, claim: str, tags: Sequence[str]) -> AttentionFamily:
        lower = claim.lower()
        tagset = {str(t).lower() for t in tags}
        if source == "user_chat":
            return "user_request"
        if source in {"vision", "ocr"}:
            return "vision_observation"
        if source == "body":
            return "body_state"
        if source == "memory":
            return "memory_recall"
        if source == "time":
            return "temporal_signal"
        if source == "system_log" or any(token in lower for token in cls.RISK_TOKENS) or "risk" in tagset:
            return "runtime_risk"
        if any(token in lower for token in cls.IDENTITY_TOKENS) or "identity" in tagset:
            return "identity_signal"
        if any(token in lower for token in cls.RELATIONAL_TOKENS) or "relationship" in tagset or "correction" in tagset:
            return "relational_signal"
        if any(token in lower for token in cls.GOAL_TOKENS) or "goal" in tagset:
            return "goal_signal"
        if any(token in lower for token in cls.AFFECTIVE_TOKENS) or "affect" in tagset:
            return "affective_signal"
        if any(token in lower for token in cls.TECHNICAL_TOKENS) or "technical" in tagset or "code" in tagset:
            return "technical_issue"
        if source in {"telemetry", "active_window", "browser"}:
            return "ambient_context"
        return "unknown"

    @classmethod
    def classify_focus_kind(cls, *, source: str, claim: str, tags: Sequence[str]) -> FocusKind:
        lower = claim.lower()
        tagset = {str(t).lower() for t in tags}
        if source == "user_chat":
            if any(token in lower for token in ("code", "file", "class", "dataclass", "python", "c#", "godot", "fix")):
                return "code"
            if any(token in lower for token in ("pipeline", "architecture", "kiến trúc", "module", "core")):
                return "architecture"
            return "chat"
        if any(token in lower for token in ("error", "exception", "traceback", "failed", "lỗi")):
            return "debug"
        if any(token in lower for token in cls.BODY_TOKENS) or "body" in tagset:
            return "body"
        if any(token in lower for token in cls.MEMORY_TOKENS) or source == "memory":
            return "memory"
        if any(token in lower for token in cls.IDENTITY_TOKENS):
            return "identity"
        if any(token in lower for token in cls.RELATIONAL_TOKENS):
            return "relationship"
        if source == "system_log" or any(token in lower for token in cls.RISK_TOKENS):
            return "risk"
        if source in {"active_window", "browser", "telemetry", "vision", "ocr"}:
            return "ambient"
        return "unknown"

    @classmethod
    def is_generic_telemetry(cls, *, source: str, claim: str, tags: Sequence[str]) -> bool:
        lower = claim.lower()
        tagset = {str(t).lower() for t in tags}
        if "generic" in tagset or "low_value" in tagset:
            return True
        if source not in {"telemetry", "active_window", "browser", "time"}:
            return False
        return any(pattern in lower for pattern in cls.GENERIC_TELEMETRY_PATTERNS)


# =============================================================================
# 6. Engine chính
# =============================================================================

class AttentionSalienceEngine:
    """Attention & Salience Allocation Engine.

    Đọc evidence từ frame, trả SalienceFrame.
    Không đọc raw_signals trừ khi cần debug fallback.
    Không gọi module khác.
    """

    module_name = "attention_salience"

    def __init__(
        self,
        config: Optional[AttentionSalienceConfig] = None,
        memory: Optional[AttentionSalienceMemory] = None,
        classifier: Optional[SalienceClassifier] = None,
    ) -> None:
        self.config = (config or AttentionSalienceConfig()).normalized()
        self.memory = memory or AttentionSalienceMemory()
        self.classifier = classifier or SalienceClassifier()

    # ------------------------------------------------------------------
    # API công khai
    # ------------------------------------------------------------------

    def evaluate(
        self,
        frame: Any = None,
        *,
        evidence: Optional[Sequence[Any]] = None,
        channel: Optional[str] = None,
        active_goal: Any = None,
        unresolved_focuses: Optional[Sequence[str]] = None,
        now: Optional[float] = None,
        write_to_frame: bool = True,
    ) -> SalienceFrame:
        """Chạy attention trên một frame hoặc danh sách evidence.

        Parameters
        ----------
        frame:
            CognitiveFrame hoặc object có field `.evidence`.
        evidence:
            Dùng khi muốn test engine độc lập không cần frame.
        channel:
            chat/autonomous/force_speak/... Nếu None sẽ lấy từ frame.channel.
        active_goal:
            Goal hiện tại nếu caller muốn attention tính goal relevance tốt hơn.
        unresolved_focuses:
            Các thread chưa đóng, dùng tăng unresolved_tension.
        now:
            Timestamp test. None thì dùng time.time().
        write_to_frame:
            Nếu True, engine cố gắn salience + ModuleReport vào frame.
        """

        timestamp = now_ts() if now is None else float(now)
        frame_evidence = list(evidence if evidence is not None else safe_get(frame, "evidence", []) or [])
        frame_channel = str(channel or safe_get(frame, "channel", "") or safe_get(frame, "frame_channel", "") or "unknown")
        active_goal_text = self._extract_goal_text(active_goal if active_goal is not None else safe_get(frame, "active_goal", None))
        unresolved = tuple(str(x) for x in (unresolved_focuses or safe_get(frame, "unresolved_focuses", []) or ()))

        candidates = self._build_candidates(
            frame_evidence,
            now=timestamp,
            channel=frame_channel,
            active_goal_text=active_goal_text,
            unresolved_focuses=unresolved,
        )
        candidates = candidates[: self.config.max_candidates]

        for candidate in candidates:
            self._score_candidate(
                candidate,
                now=timestamp,
                channel=frame_channel,
                active_goal_text=active_goal_text,
                unresolved_focuses=unresolved,
            )

        selected, suppressed = self._select_candidates(candidates)
        prompt_items, overflow_suppressed = self._build_prompt_evidence(selected)
        if overflow_suppressed:
            suppressed.extend(overflow_suppressed)

        salience = self._build_salience_frame(
            candidates=candidates,
            selected=selected,
            suppressed=suppressed,
            prompt_items=prompt_items,
            channel=frame_channel,
            active_goal_text=active_goal_text,
        )

        self.memory.mark_seen(candidates, max_recent=self.config.novelty_recent_window)
        if salience.dominant_focus:
            self.memory.last_dominant_focus = salience.dominant_focus
            self.memory.last_dominant_family = salience.dominant_family

        if write_to_frame and frame is not None:
            self._write_to_frame(frame, salience)

        return salience

    def reset_memory(self) -> None:
        """Xóa rolling memory của attention.

        Dùng khi reset session/test. Không đụng long-term memory.
        """

        self.memory = AttentionSalienceMemory()

    # ------------------------------------------------------------------
    # Build candidate
    # ------------------------------------------------------------------

    def _build_candidates(
        self,
        evidence_items: Sequence[Any],
        *,
        now: float,
        channel: str,
        active_goal_text: str,
        unresolved_focuses: Sequence[str],
    ) -> list[AttentionCandidate]:
        candidates: list[AttentionCandidate] = []
        for index, item in enumerate(evidence_items):
            candidate = self._candidate_from_evidence(item, index=index, now=now)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _candidate_from_evidence(self, item: Any, *, index: int, now: float) -> Optional[AttentionCandidate]:
        evidence_id = str(safe_get(item, "id", "") or safe_get(item, "evidence_id", "") or f"ev_missing_{index}")
        claim = normalize_text(safe_get(item, "claim", "") or safe_get(item, "content", ""), max_len=900)
        if not claim:
            return None

        source_signal_id = str(safe_get(item, "source_signal_id", "") or safe_get(item, "signal_id", "") or "")
        source_raw = str(safe_get(item, "source", "unknown") or "unknown").strip().lower()
        source = self._normalize_source(source_raw)
        timestamp = safe_float(safe_get(item, "timestamp", now), now)
        confidence = clamp01(safe_get(item, "confidence", 1.0), default=0.5)
        reliability = clamp01(safe_get(item, "reliability", 1.0), default=0.5)
        privacy_level = str(safe_get(item, "privacy_level", "normal") or "normal").strip().lower()
        raw_or_inferred = str(safe_get(item, "raw_or_inferred", "raw") or "raw").strip().lower()
        tags_raw = safe_get(item, "tags", ()) or ()
        if isinstance(tags_raw, str):
            tags = (tags_raw,)
        else:
            try:
                tags = tuple(str(t) for t in tags_raw)
            except Exception:
                tags = ()

        family = self.classifier.classify_family(source=source, claim=claim, tags=tags)
        focus_kind = self.classifier.classify_focus_kind(source=source, claim=claim, tags=tags)
        fingerprint = stable_fingerprint(f"{source}|{family}|{claim}", prefix="att")
        tokens = tuple(sorted(tokenize(claim))[:128])
        prompt_sayable = privacy_level not in {"private", "sensitive"}

        return AttentionCandidate(
            candidate_id=f"att_{index:03d}_{fingerprint.split('.')[-1]}",
            evidence_id=evidence_id,
            source_signal_id=source_signal_id,
            source=source,
            claim=claim,
            timestamp=timestamp,
            confidence=confidence,
            reliability=reliability,
            privacy_level=privacy_level,
            raw_or_inferred=raw_or_inferred,
            tags=tags,
            family=family,
            focus_kind=focus_kind,
            fingerprint=fingerprint,
            text_tokens=tokens,
            prompt_sayable=prompt_sayable,
        )

    def _normalize_source(self, source: str) -> SignalSource:
        aliases = {
            "chat": "user_chat",
            "user": "user_chat",
            "window": "active_window",
            "active_app": "active_window",
            "log": "system_log",
            "runtime": "system_log",
            "screen": "vision",
            "vision_fact": "vision",
            "long_term_memory": "memory",
            "clock": "time",
        }
        normalized = aliases.get(source, source)
        allowed = {
            "user_chat",
            "active_window",
            "browser",
            "telemetry",
            "vision",
            "ocr",
            "body",
            "system_log",
            "memory",
            "time",
        }
        if normalized not in allowed:
            return "unknown"
        return cast(SignalSource, normalized)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_candidate(
        self,
        candidate: AttentionCandidate,
        *,
        now: float,
        channel: str,
        active_goal_text: str,
        unresolved_focuses: Sequence[str],
    ) -> None:
        breakdown = SalienceFactorBreakdown()
        repeat_count = self.memory.repeat_count(candidate.fingerprint)
        family_repeat = self.memory.family_repeat_count(candidate.family)
        age_seconds = max(0.0, now - candidate.timestamp)
        tags = {t.lower() for t in candidate.tags}
        lower_claim = candidate.claim.lower()
        tokens = set(candidate.text_tokens)

        breakdown.confidence = candidate.confidence
        breakdown.reliability = candidate.reliability
        breakdown.novelty = self._novelty_score(candidate, repeat_count=repeat_count, age_seconds=age_seconds)
        breakdown.urgency = self._urgency_score(candidate, lower_claim=lower_claim, tags=tags, channel=channel)
        breakdown.goal_relevance = self._goal_relevance_score(candidate, active_goal_text=active_goal_text)
        breakdown.user_relevance = self._user_relevance_score(candidate, lower_claim=lower_claim, channel=channel)
        breakdown.identity_relevance = self._identity_relevance_score(candidate, lower_claim=lower_claim, tags=tags)
        breakdown.relational_relevance = self._relational_relevance_score(candidate, lower_claim=lower_claim, tags=tags)
        breakdown.affective_charge = self._affective_charge_score(candidate, lower_claim=lower_claim, tags=tags)
        breakdown.risk_relevance = self._risk_relevance_score(candidate, lower_claim=lower_claim, tags=tags)
        breakdown.unresolved_tension = self._unresolved_tension_score(
            candidate,
            unresolved_focuses=unresolved_focuses,
            active_goal_text=active_goal_text,
        )
        breakdown.recurrence_weight = self._recurrence_weight_score(repeat_count=repeat_count, family_repeat=family_repeat)
        breakdown.habituation = self._habituation_score(candidate, repeat_count=repeat_count, family_repeat=family_repeat)
        breakdown.false_alarm_likelihood = self._false_alarm_likelihood_score(
            candidate,
            age_seconds=age_seconds,
            lower_claim=lower_claim,
            tags=tags,
        )
        breakdown.generic_penalty = self._generic_penalty_score(candidate)

        weighted = self._weighted_score(breakdown)
        capped = self._apply_score_caps(candidate, weighted, breakdown)
        candidate.score = clamp01(capped)
        breakdown.final_score = candidate.score
        candidate.score_breakdown = breakdown

        notes: list[str] = []
        if repeat_count >= self.config.repeat_habituation_start:
            notes.append(f"repeat_count={repeat_count}")
        if family_repeat >= self.config.repeat_habituation_start:
            notes.append(f"family_repeat={family_repeat}")
        if self.classifier.is_generic_telemetry(source=candidate.source, claim=candidate.claim, tags=candidate.tags):
            notes.append("generic_telemetry")
        if age_seconds >= self.config.stale_after_seconds:
            notes.append(f"stale_age={int(age_seconds)}s")
        if candidate.privacy_level in {"private", "sensitive"}:
            notes.append(f"privacy={candidate.privacy_level}")
        candidate.debug_notes = tuple(notes)

    def _weighted_score(self, b: SalienceFactorBreakdown) -> float:
        w = self.config.weights
        positive = (
            b.novelty * w.novelty
            + b.urgency * w.urgency
            + b.goal_relevance * w.goal_relevance
            + b.user_relevance * w.user_relevance
            + b.identity_relevance * w.identity_relevance
            + b.relational_relevance * w.relational_relevance
            + b.affective_charge * w.affective_charge
            + b.risk_relevance * w.risk_relevance
            + b.unresolved_tension * w.unresolved_tension
            + b.recurrence_weight * w.recurrence_weight
            + b.reliability * w.reliability
            + b.confidence * w.confidence
        )
        negative = (
            b.habituation * w.habituation
            + b.false_alarm_likelihood * w.false_alarm_likelihood
            + b.generic_penalty * w.generic_penalty
        )
        max_positive = (
            w.novelty
            + w.urgency
            + w.goal_relevance
            + w.user_relevance
            + w.identity_relevance
            + w.relational_relevance
            + w.affective_charge
            + w.risk_relevance
            + w.unresolved_tension
            + w.recurrence_weight
            + w.reliability
            + w.confidence
        )
        raw = (positive - negative) / max(0.001, max_positive)
        return clamp01(raw)

    def _novelty_score(self, candidate: AttentionCandidate, *, repeat_count: int, age_seconds: float) -> float:
        if age_seconds >= self.config.stale_after_seconds:
            return 0.08
        if repeat_count <= 0:
            return 0.85
        if repeat_count == 1:
            return 0.55
        if repeat_count == 2:
            return 0.32
        return 0.14

    def _urgency_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str], channel: str) -> float:
        score = 0.0
        if channel == "chat" and candidate.source == "user_chat":
            score += 0.55
        if channel == "force_speak":
            score += 0.25
        if candidate.family == "runtime_risk":
            score += 0.55
        if any(token in lower_claim for token in ("error", "exception", "traceback", "failed", "crash", "lỗi", "không chạy")):
            score += 0.45
        if any(token in lower_claim for token in ("urgent", "ngay", "gấp", "critical", "fatal")):
            score += 0.35
        if "urgent" in tags or "risk" in tags:
            score += 0.30
        return clamp01(score)

    def _goal_relevance_score(self, candidate: AttentionCandidate, *, active_goal_text: str) -> float:
        if not active_goal_text:
            if candidate.family == "goal_signal":
                return 0.50
            return 0.0
        goal_tokens = tokenize(active_goal_text)
        if not goal_tokens:
            return 0.0
        overlap = len(goal_tokens.intersection(set(candidate.text_tokens))) / max(1, min(len(goal_tokens), len(candidate.text_tokens)))
        base = clamp01(overlap)
        if candidate.family in {"goal_signal", "technical_issue", "user_request"}:
            base += 0.15
        return clamp01(base)

    def _user_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, channel: str) -> float:
        score = 0.0
        if candidate.source == "user_chat":
            score += 0.75
        if channel == "chat":
            score += 0.15
        if any(token in lower_claim for token in ("tôi", "toi", "ngài", "ngai", "mình", "minh", "bạn", "ban")):
            score += 0.18
        if "?" in candidate.claim:
            score += 0.15
        return clamp01(score)

    def _identity_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str]) -> float:
        if candidate.family == "identity_signal":
            return 0.72
        if "identity" in tags:
            return 0.65
        if any(token in lower_claim for token in SalienceClassifier.IDENTITY_TOKENS):
            return 0.55
        return 0.0

    def _relational_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str]) -> float:
        score = 0.0
        if candidate.family == "relational_signal":
            score += 0.55
        if "correction" in tags or "repair" in tags:
            score += 0.35
        if any(token in lower_claim for token in ("sai", "không phải", "khong phai", "đúng rồi", "dung roi")):
            score += 0.30
        if any(token in lower_claim for token in ("ngu", "dcm", "vl", "cay", "bực", "tức")):
            score += 0.20
        return clamp01(score)

    def _affective_charge_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str]) -> float:
        score = 0.0
        if candidate.family == "affective_signal":
            score += 0.50
        if "affect" in tags or "emotion" in tags:
            score += 0.35
        if any(token in lower_claim for token in SalienceClassifier.AFFECTIVE_TOKENS):
            score += 0.30
        if candidate.source == "user_chat" and any(p in lower_claim for p in ("!!!", "???")):
            score += 0.15
        return clamp01(score)

    def _risk_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str]) -> float:
        score = 0.0
        if candidate.family == "runtime_risk":
            score += 0.62
        if "risk" in tags or "security" in tags or "privacy" in tags:
            score += 0.35
        if candidate.privacy_level == "sensitive":
            score += 0.30
        if any(token in lower_claim for token in SalienceClassifier.RISK_TOKENS):
            score += 0.30
        return clamp01(score)

    def _unresolved_tension_score(
        self,
        candidate: AttentionCandidate,
        *,
        unresolved_focuses: Sequence[str],
        active_goal_text: str,
    ) -> float:
        if not unresolved_focuses and not active_goal_text:
            return 0.0
        candidate_tokens = set(candidate.text_tokens)
        best = 0.0
        for focus in unresolved_focuses:
            focus_tokens = tokenize(focus)
            if not focus_tokens:
                continue
            overlap = len(candidate_tokens.intersection(focus_tokens)) / max(1, min(len(candidate_tokens), len(focus_tokens)))
            best = max(best, overlap)
        if active_goal_text:
            best = max(best, self._goal_relevance_score(candidate, active_goal_text=active_goal_text) * 0.75)
        if candidate.family in {"technical_issue", "goal_signal", "runtime_risk"}:
            best += 0.10
        return clamp01(best)

    def _recurrence_weight_score(self, *, repeat_count: int, family_repeat: int) -> float:
        # Recurrence có hai mặt:
        # - lặp nhẹ có nghĩa là pattern đang hình thành
        # - lặp quá nhiều là habituation rác
        if repeat_count <= 0 and family_repeat <= 0:
            return 0.0
        peak = min(max(repeat_count, family_repeat), self.config.repeat_habituation_cap)
        if peak <= 1:
            return 0.18
        if peak <= 3:
            return 0.38
        if peak <= 6:
            return 0.30
        return 0.16

    def _habituation_score(self, candidate: AttentionCandidate, *, repeat_count: int, family_repeat: int) -> float:
        generic = self.classifier.is_generic_telemetry(source=candidate.source, claim=candidate.claim, tags=candidate.tags)
        start = self.config.repeat_habituation_start
        score = 0.0
        if repeat_count >= start:
            score += min(0.55, (repeat_count - start + 1) / max(1, self.config.repeat_habituation_cap))
        if family_repeat >= start + 1:
            score += min(0.25, (family_repeat - start) / max(1, self.config.repeat_habituation_cap))
        if generic:
            score += 0.25
        return clamp01(score)

    def _false_alarm_likelihood_score(
        self,
        candidate: AttentionCandidate,
        *,
        age_seconds: float,
        lower_claim: str,
        tags: set[str],
    ) -> float:
        score = 0.0
        if candidate.confidence < 0.35:
            score += 0.30
        if candidate.reliability < 0.35:
            score += 0.30
        if candidate.raw_or_inferred == "inferred" and candidate.confidence < 0.60:
            score += 0.18
        if "weak" in tags or "hint" in tags or "impression" in tags:
            score += 0.20
        if age_seconds >= self.config.stale_after_seconds:
            score += 0.35
        if candidate.source == "memory" and candidate.confidence < 0.55:
            score += 0.20
        if "maybe" in lower_claim or "possibly" in lower_claim or "có thể" in lower_claim:
            score += 0.12
        return clamp01(score)

    def _generic_penalty_score(self, candidate: AttentionCandidate) -> float:
        if self.classifier.is_generic_telemetry(source=candidate.source, claim=candidate.claim, tags=candidate.tags):
            return 0.42
        if candidate.family == "ambient_context" and candidate.confidence < 0.50:
            return 0.22
        return 0.0

    def _apply_score_caps(
        self,
        candidate: AttentionCandidate,
        score: float,
        breakdown: SalienceFactorBreakdown,
    ) -> float:
        capped = score
        if candidate.confidence < self.config.min_confidence:
            capped = min(capped, 0.18)
        if candidate.reliability < self.config.min_reliability:
            capped = min(capped, 0.18)
        if self.classifier.is_generic_telemetry(source=candidate.source, claim=candidate.claim, tags=candidate.tags):
            capped = min(capped, self.config.generic_telemetry_score_cap)
        if candidate.source == "memory" and candidate.raw_or_inferred == "inferred" and candidate.confidence < 0.70:
            capped = min(capped, self.config.memory_echo_score_cap)
        if candidate.privacy_level == "sensitive" and self.config.privacy_filter_sensitive:
            # Sensitive vẫn có thể tăng risk nội bộ, nhưng không được chiếm prompt bừa.
            capped = min(capped, max(0.28, capped * 0.72))
        return clamp01(capped)

    # ------------------------------------------------------------------
    # Selection / suppression
    # ------------------------------------------------------------------

    def _select_candidates(
        self,
        candidates: Sequence[AttentionCandidate],
    ) -> tuple[list[AttentionCandidate], list[SuppressedSignal]]:
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
        selected: list[AttentionCandidate] = []
        suppressed: list[SuppressedSignal] = []
        selected_families: set[str] = set()

        for candidate in sorted_candidates:
            reason = self._suppression_reason(candidate, selected_families=selected_families)
            if reason is not None:
                candidate.selected = False
                candidate.suppression_reason = reason
                suppressed.append(self._to_suppressed(candidate, reason))
                continue

            if len(selected) >= self.config.max_selected_evidence:
                candidate.selected = False
                candidate.suppression_reason = "selected_elsewhere"
                suppressed.append(self._to_suppressed(candidate, "selected_elsewhere"))
                continue

            candidate.selected = True
            candidate.suppression_reason = None
            selected.append(candidate)
            selected_families.add(candidate.family)

        return selected, suppressed

    def _suppression_reason(
        self,
        candidate: AttentionCandidate,
        *,
        selected_families: set[str],
    ) -> Optional[SuppressionReason]:
        if candidate.confidence < self.config.min_confidence:
            return "low_confidence"
        if candidate.reliability < self.config.min_reliability:
            return "low_reliability"
        if candidate.privacy_level == "sensitive" and self.config.privacy_filter_sensitive and candidate.score < 0.55:
            return "privacy_filtered"
        if candidate.score < self.config.min_select_score:
            if self.classifier.is_generic_telemetry(source=candidate.source, claim=candidate.claim, tags=candidate.tags):
                return "generic_telemetry"
            if candidate.score_breakdown.false_alarm_likelihood >= 0.45:
                return "false_alarm_likely"
            return "low_score"
        if self.config.collapse_same_family and candidate.family in selected_families:
            # Không collapse user_request/risk quá mạnh, vì nhiều user evidence có thể cùng quan trọng.
            if candidate.family not in {"user_request", "runtime_risk"}:
                return "duplicate_semantic_family"
        if candidate.score_breakdown.habituation >= 0.72 and candidate.score < 0.60:
            return "repeated_habituation"
        return None

    def _to_suppressed(self, candidate: AttentionCandidate, reason: SuppressionReason) -> SuppressedSignal:
        return SuppressedSignal(
            evidence_id=candidate.evidence_id,
            source=candidate.source,
            claim=candidate.short_claim(140),
            score=candidate.score,
            reason=reason,
            notes=candidate.debug_notes,
        )

    def _build_prompt_evidence(
        self,
        selected: Sequence[AttentionCandidate],
    ) -> tuple[list[PromptEvidenceItem], list[SuppressedSignal]]:
        prompt_items: list[PromptEvidenceItem] = []
        overflow: list[SuppressedSignal] = []
        char_budget = self.config.max_prompt_chars
        token_budget = self.config.max_prompt_tokens
        used_chars = 0
        used_tokens = 0

        for candidate in selected:
            if not candidate.prompt_sayable:
                overflow.append(self._to_suppressed(candidate, "privacy_filtered"))
                continue
            item = PromptEvidenceItem(
                evidence_id=candidate.evidence_id,
                claim=candidate.short_claim(240),
                score=candidate.score,
                source=candidate.source,
                family=candidate.family,
                confidence=candidate.confidence,
                reliability=candidate.reliability,
                tags=candidate.tags,
            )
            line = item.to_prompt_line()
            line_chars = len(line)
            line_tokens = estimate_token_count(line)
            if used_chars + line_chars > char_budget or used_tokens + line_tokens > token_budget:
                overflow.append(self._to_suppressed(candidate, "prompt_budget_overflow"))
                continue
            prompt_items.append(item)
            used_chars += line_chars
            used_tokens += line_tokens

        return prompt_items, overflow

    # ------------------------------------------------------------------
    # Build SalienceFrame
    # ------------------------------------------------------------------

    def _build_salience_frame(
        self,
        *,
        candidates: Sequence[AttentionCandidate],
        selected: Sequence[AttentionCandidate],
        suppressed: Sequence[SuppressedSignal],
        prompt_items: Sequence[PromptEvidenceItem],
        channel: str,
        active_goal_text: str,
    ) -> SalienceFrame:
        dominant = selected[0] if selected else None
        secondary = list(selected[1 : 1 + self.config.max_secondary_focuses])

        aggregate = self._aggregate_breakdown(selected if selected else candidates[:1])
        dominant_focus = self._dominant_focus_text(dominant)
        secondary_focuses = [self._dominant_focus_text(c) or c.short_claim(100) for c in secondary]
        selected_ids = [c.evidence_id for c in selected]
        selected_candidate_ids = [c.candidate_id for c in selected]
        prompt_chars = sum(len(p.to_prompt_line()) for p in prompt_items)
        prompt_tokens = sum(estimate_token_count(p.to_prompt_line()) for p in prompt_items)
        flood = self._context_flood_report(
            total=len(candidates),
            selected=selected,
            suppressed=suppressed,
            prompt_items=prompt_items,
            prompt_chars=prompt_chars,
            prompt_tokens=prompt_tokens,
        )

        warnings: list[str] = []
        if len(candidates) > self.config.max_selected_evidence * 3:
            warnings.append("many_candidates_context_flood_risk")
        if not dominant:
            warnings.append("no_dominant_focus_selected")
        if flood.pressure >= 0.65:
            warnings.append("high_context_flood_pressure")

        reason = self._build_reason(dominant=dominant, selected=selected, flood=flood, channel=channel)
        if len(reason) > self.config.reason_max_len:
            reason = reason[: self.config.reason_max_len - 1] + "…"

        return SalienceFrame(
            dominant_focus=dominant_focus,
            secondary_focuses=secondary_focuses,
            suppressed_signals=[s.evidence_id for s in suppressed],
            novelty=aggregate.novelty,
            urgency=aggregate.urgency,
            goal_relevance=aggregate.goal_relevance,
            user_relevance=aggregate.user_relevance,
            identity_relevance=aggregate.identity_relevance,
            relational_relevance=aggregate.relational_relevance,
            affective_charge=aggregate.affective_charge,
            risk_relevance=aggregate.risk_relevance,
            unresolved_tension=aggregate.unresolved_tension,
            recurrence_weight=aggregate.recurrence_weight,
            habituation=aggregate.habituation,
            false_alarm_likelihood=aggregate.false_alarm_likelihood,
            broadcast_priority=dominant.score if dominant else 0.0,
            reason=reason,
            selected_evidence_ids=selected_ids,
            selected_candidate_ids=selected_candidate_ids,
            dominant_evidence_id=dominant.evidence_id if dominant else None,
            dominant_family=dominant.family if dominant else "unknown",
            dominant_focus_kind=dominant.focus_kind if dominant else "unknown",
            candidates=list(candidates),
            selected_candidates=list(selected),
            suppressed=list(suppressed),
            prompt_evidence=list(prompt_items),
            context_flood=flood,
            warnings=warnings,
            debug={
                "channel": channel,
                "active_goal_text": active_goal_text[:160] if active_goal_text else "",
                "memory": self.memory.to_dict(),
                "score_threshold": self.config.min_select_score,
                "dominant_threshold": self.config.min_dominant_score,
            },
        )

    def _aggregate_breakdown(self, candidates: Sequence[AttentionCandidate]) -> SalienceFactorBreakdown:
        if not candidates:
            return SalienceFactorBreakdown()
        # Dùng max thay vì average, vì frame salience nên phản ánh tín hiệu mạnh nhất.
        return SalienceFactorBreakdown(
            novelty=max(c.score_breakdown.novelty for c in candidates),
            urgency=max(c.score_breakdown.urgency for c in candidates),
            goal_relevance=max(c.score_breakdown.goal_relevance for c in candidates),
            user_relevance=max(c.score_breakdown.user_relevance for c in candidates),
            identity_relevance=max(c.score_breakdown.identity_relevance for c in candidates),
            relational_relevance=max(c.score_breakdown.relational_relevance for c in candidates),
            affective_charge=max(c.score_breakdown.affective_charge for c in candidates),
            risk_relevance=max(c.score_breakdown.risk_relevance for c in candidates),
            unresolved_tension=max(c.score_breakdown.unresolved_tension for c in candidates),
            recurrence_weight=max(c.score_breakdown.recurrence_weight for c in candidates),
            reliability=max(c.score_breakdown.reliability for c in candidates),
            confidence=max(c.score_breakdown.confidence for c in candidates),
            habituation=max(c.score_breakdown.habituation for c in candidates),
            false_alarm_likelihood=max(c.score_breakdown.false_alarm_likelihood for c in candidates),
            generic_penalty=max(c.score_breakdown.generic_penalty for c in candidates),
            final_score=max(c.score for c in candidates),
        )

    def _dominant_focus_text(self, candidate: Optional[AttentionCandidate]) -> Optional[str]:
        if candidate is None:
            return None
        text = candidate.short_claim(self.config.dominant_focus_max_len)
        if not text:
            return None
        return text

    def _context_flood_report(
        self,
        *,
        total: int,
        selected: Sequence[AttentionCandidate],
        suppressed: Sequence[SuppressedSignal],
        prompt_items: Sequence[PromptEvidenceItem],
        prompt_chars: int,
        prompt_tokens: int,
    ) -> ContextFloodReport:
        generic_count = sum(1 for s in suppressed if s.reason == "generic_telemetry")
        repeated_count = sum(1 for s in suppressed if s.reason in {"repeated_habituation", "duplicate_semantic_family"})
        privacy_count = sum(1 for s in suppressed if s.reason == "privacy_filtered")
        overflow_count = sum(1 for s in suppressed if s.reason == "prompt_budget_overflow")
        notes: list[str] = []
        if generic_count:
            notes.append(f"generic_telemetry_suppressed={generic_count}")
        if repeated_count:
            notes.append(f"repeated_or_duplicate_suppressed={repeated_count}")
        if overflow_count:
            notes.append(f"prompt_overflow_suppressed={overflow_count}")
        return ContextFloodReport(
            total_candidates=total,
            selected_count=len(selected),
            suppressed_count=len(suppressed),
            prompt_items_count=len(prompt_items),
            prompt_chars=prompt_chars,
            prompt_tokens_estimate=prompt_tokens,
            generic_telemetry_suppressed=generic_count,
            repeated_suppressed=repeated_count,
            privacy_suppressed=privacy_count,
            overflow_suppressed=overflow_count,
            notes=tuple(notes),
        )

    def _build_reason(
        self,
        *,
        dominant: Optional[AttentionCandidate],
        selected: Sequence[AttentionCandidate],
        flood: ContextFloodReport,
        channel: str,
    ) -> str:
        if dominant is None:
            return join_reason(
                (
                    f"channel={channel}",
                    "no evidence passed salience threshold",
                    f"context_flood_pressure={flood.pressure:.2f}",
                )
            )
        b = dominant.score_breakdown
        reasons = [
            f"dominant={dominant.evidence_id}",
            f"family={dominant.family}",
            f"kind={dominant.focus_kind}",
            f"score={dominant.score:.2f}",
        ]
        top_factors = self._top_factors(b)
        if top_factors:
            reasons.append("top_factors=" + ",".join(top_factors))
        if flood.pressure >= 0.35:
            reasons.append(f"context_flood_pressure={flood.pressure:.2f}")
        if len(selected) > 1:
            reasons.append(f"secondary={len(selected) - 1}")
        return join_reason(reasons)

    def _top_factors(self, breakdown: SalienceFactorBreakdown, *, limit: int = 4) -> list[str]:
        values = {
            "novelty": breakdown.novelty,
            "urgency": breakdown.urgency,
            "goal": breakdown.goal_relevance,
            "user": breakdown.user_relevance,
            "identity": breakdown.identity_relevance,
            "relation": breakdown.relational_relevance,
            "affect": breakdown.affective_charge,
            "risk": breakdown.risk_relevance,
            "unresolved": breakdown.unresolved_tension,
            "recurrence": breakdown.recurrence_weight,
        }
        ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)
        return [f"{name}:{value:.2f}" for name, value in ranked[:limit] if value >= 0.18]

    # ------------------------------------------------------------------
    # Frame integration
    # ------------------------------------------------------------------

    def _write_to_frame(self, frame: Any, salience: SalienceFrame) -> None:
        """Gắn salience và ModuleReport vào frame nếu có thể."""

        try:
            if hasattr(frame, "set_slot"):
                frame.set_slot("salience", salience, writer=self.module_name)  # type: ignore[misc]
            else:
                setattr(frame, "salience", salience)
        except Exception:
            # Không để integration làm chết engine. Lỗi sẽ nằm trong report/debug nếu caller giữ salience.
            pass

        report = self._build_module_report(salience)
        try:
            if hasattr(frame, "add_report"):
                frame.add_report(report)  # type: ignore[misc]
            elif hasattr(frame, "reports"):
                reports = safe_get(frame, "reports", None)
                if isinstance(reports, dict):
                    reports[self.module_name] = report
        except Exception:
            pass

    def _build_module_report(self, salience: SalienceFrame) -> ModuleReport:
        pressure = clamp01(max(salience.broadcast_priority, salience.context_flood.pressure))
        confidence = clamp01(
            max(
                salience.user_relevance,
                salience.goal_relevance,
                salience.risk_relevance,
                salience.broadcast_priority,
            )
        )
        return ModuleReport(
            module_name=self.module_name,
            confidence=confidence,
            pressure=pressure,
            evidence_used=list(salience.selected_evidence_ids),
            result=salience,
            warnings=list(salience.warnings),
            debug={
                "dominant_evidence_id": salience.dominant_evidence_id,
                "dominant_family": salience.dominant_family,
                "context_flood": salience.context_flood.to_dict(),
                "suppressed_count": len(salience.suppressed),
            },
        )

    # ------------------------------------------------------------------
    # Extract goal/context
    # ------------------------------------------------------------------

    def _extract_goal_text(self, active_goal: Any) -> str:
        if active_goal is None:
            return ""
        if isinstance(active_goal, str):
            return normalize_text(active_goal, max_len=600)
        for key in ("summary", "goal", "description", "text", "title"):
            value = safe_get(active_goal, key, None)
            if value:
                return normalize_text(value, max_len=600)
        return normalize_text(active_goal, max_len=600)


# =============================================================================
# 7. Convenience functions
# =============================================================================

def allocate_salience(
    frame: Any = None,
    *,
    evidence: Optional[Sequence[Any]] = None,
    config: Optional[AttentionSalienceConfig] = None,
    memory: Optional[AttentionSalienceMemory] = None,
    channel: Optional[str] = None,
    active_goal: Any = None,
    unresolved_focuses: Optional[Sequence[str]] = None,
    write_to_frame: bool = True,
) -> SalienceFrame:
    """Hàm tiện dụng cho caller không muốn tự giữ engine.

    Nếu cần chống lặp giữa nhiều frame, nên giữ một instance AttentionSalienceEngine
    thay vì gọi hàm này mỗi lần, vì memory rolling sẽ bị reset.
    """

    engine = AttentionSalienceEngine(config=config, memory=memory)
    return engine.evaluate(
        frame,
        evidence=evidence,
        channel=channel,
        active_goal=active_goal,
        unresolved_focuses=unresolved_focuses,
        write_to_frame=write_to_frame,
    )


__all__ = [
    "AttentionCandidate",
    "AttentionFamily",
    "AttentionSalienceConfig",
    "AttentionSalienceEngine",
    "AttentionSalienceMemory",
    "ContextFloodReport",
    "FocusKind",
    "PromptEvidenceItem",
    "SalienceClassifier",
    "SalienceFactorBreakdown",
    "SalienceFrame",
    "SalienceWeights",
    "SuppressedSignal",
    "allocate_salience",
]
