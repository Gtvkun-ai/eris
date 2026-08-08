# -*- coding: utf-8 -*-
"""Động lực chủ động của Subject Core.

Need trả lời câu hỏi "đang thiếu/cần gì".  Module này trả lời câu hỏi kế tiếp:
"vì nhu cầu đó, lúc này Eris muốn làm gì?".  Nó không viết câu public, không gọi
model và không được tự tạo fact về user.  Một motive chỉ có quyền sinh *khả năng*
hành động; Executive vẫn là nơi cam kết.

V26 cố ý giữ motive khác với need.  Ví dụ connection có thể tạo ``connect`` hoặc
``understand_user``; competence có thể tạo ``demonstrate``.  Nếu sau này một
pattern đủ bền để trở thành derived need thì NeedPlasticity mới có quyền làm việc
đó.  Không phong mọi ham muốn thoáng qua thành nhu cầu cấu trúc, vì database cũng
không cần tuổi thơ nhiều hơn con người.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Mapping, Sequence

from .contracts import NeedActivation, ObservationOrigin, WorldObservation


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _uniq(values: Sequence[str], *, limit: int = 12) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item or "").strip()))[:limit]


class MotiveKind(StrEnum):
    """Các họ động lực, không phải personality trait và cũng chưa phải derived need."""

    UNDERSTAND_USER = "understand_user"
    CONNECT = "connect"
    SHARE = "share"
    BE_UNDERSTOOD = "be_understood"
    SEEK_RECOGNITION = "seek_recognition"
    DEMONSTRATE = "demonstrate"
    RESOLVE = "resolve"
    EXPLORE = "explore"
    PROTECT = "protect"
    CONTRIBUTE = "contribute"


class IntentionStatus(StrEnum):
    PENDING = "pending"
    SATISFIED = "satisfied"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class SubjectMotive:
    motive_id: str
    kind: MotiveKind
    pressure: float
    epistemic_value: float
    target: str
    semantic_goal: str
    supporting_need_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str
    origin: ObservationOrigin

    def __post_init__(self) -> None:
        object.__setattr__(self, "pressure", _clamp01(self.pressure))
        object.__setattr__(self, "epistemic_value", _clamp01(self.epistemic_value))
        object.__setattr__(self, "supporting_need_ids", _uniq(self.supporting_need_ids, limit=8))
        object.__setattr__(self, "evidence_refs", _uniq(self.evidence_refs, limit=12))

    def to_dict(self) -> dict[str, Any]:
        return {
            "motive_id": self.motive_id,
            "kind": self.kind.value,
            "pressure": self.pressure,
            "epistemic_value": self.epistemic_value,
            "target": self.target,
            "semantic_goal": self.semantic_goal,
            "supporting_need_ids": list(self.supporting_need_ids),
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "origin": self.origin.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SubjectMotive":
        return cls(
            motive_id=str(payload.get("motive_id") or "motive:restored"),
            kind=MotiveKind(str(payload.get("kind") or MotiveKind.CONNECT.value)),
            pressure=_clamp01(payload.get("pressure", 0.0)),
            epistemic_value=_clamp01(payload.get("epistemic_value", 0.0)),
            target=str(payload.get("target") or "relationship"),
            semantic_goal=str(payload.get("semantic_goal") or ""),
            supporting_need_ids=tuple(str(item) for item in payload.get("supporting_need_ids", ())),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ())),
            reason=str(payload.get("reason") or "restored motive"),
            origin=ObservationOrigin(str(payload.get("origin") or ObservationOrigin.INTERNAL.value)),
        )


@dataclass(frozen=True, slots=True)
class PendingIntention:
    intention_id: str
    motive_kind: MotiveKind
    semantic_goal: str
    target: str
    pressure: float
    commitment_strength: float
    created_at: float
    updated_at: float
    evidence_refs: tuple[str, ...]
    source_origin: ObservationOrigin
    status: IntentionStatus = IntentionStatus.PENDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "pressure", _clamp01(self.pressure))
        object.__setattr__(self, "commitment_strength", _clamp01(self.commitment_strength))
        object.__setattr__(self, "evidence_refs", _uniq(self.evidence_refs, limit=12))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intention_id": self.intention_id,
            "motive_kind": self.motive_kind.value,
            "semantic_goal": self.semantic_goal,
            "target": self.target,
            "pressure": self.pressure,
            "commitment_strength": self.commitment_strength,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "evidence_refs": list(self.evidence_refs),
            "source_origin": self.source_origin.value,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PendingIntention":
        return cls(
            intention_id=str(payload.get("intention_id") or "intention:restored"),
            motive_kind=MotiveKind(str(payload.get("motive_kind") or MotiveKind.CONNECT.value)),
            semantic_goal=str(payload.get("semantic_goal") or ""),
            target=str(payload.get("target") or "relationship"),
            pressure=_clamp01(payload.get("pressure", 0.0)),
            commitment_strength=_clamp01(payload.get("commitment_strength", 0.0)),
            created_at=float(payload.get("created_at", 0.0) or 0.0),
            updated_at=float(payload.get("updated_at", 0.0) or 0.0),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ())),
            source_origin=ObservationOrigin(str(payload.get("source_origin") or ObservationOrigin.INTERNAL.value)),
            status=IntentionStatus(str(payload.get("status") or IntentionStatus.PENDING.value)),
        )


@dataclass(frozen=True, slots=True)
class InitiativeState:
    revision: int = 0
    updated_at: float = 0.0
    active_motives: tuple[SubjectMotive, ...] = ()
    pending_intentions: tuple[PendingIntention, ...] = ()

    @property
    def initiative_pressure(self) -> float:
        motive = max((item.pressure for item in self.active_motives), default=0.0)
        pending = max(
            (item.pressure * (0.55 + 0.45 * item.commitment_strength) for item in self.pending_intentions if item.status == IntentionStatus.PENDING),
            default=0.0,
        )
        return _clamp01(max(motive, pending))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.subject_initiative.v1",
            "revision": self.revision,
            "updated_at": self.updated_at,
            "initiative_pressure": self.initiative_pressure,
            "active_motives": [item.to_dict() for item in self.active_motives],
            "pending_intentions": [item.to_dict() for item in self.pending_intentions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "InitiativeState":
        data = payload or {}
        return cls(
            revision=max(0, int(data.get("revision", 0) or 0)),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            active_motives=tuple(
                SubjectMotive.from_dict(item)
                for item in data.get("active_motives", ())
                if isinstance(item, Mapping)
            )[:12],
            pending_intentions=tuple(
                PendingIntention.from_dict(item)
                for item in data.get("pending_intentions", ())
                if isinstance(item, Mapping)
            )[:12],
        )


@dataclass(frozen=True, slots=True)
class InitiativeConfig:
    motive_threshold: float = 0.24
    intention_threshold: float = 0.34
    intention_ttl_seconds: float = 1800.0
    max_motives: int = 8
    max_intentions: int = 8


class InitiativeEngine:
    """Dẫn xuất motive từ Need + state, không cần random seed hay LLM."""

    def __init__(self, id_factory, config: InitiativeConfig | None = None) -> None:
        self._id_factory = id_factory
        self.config = config or InitiativeConfig()

    @staticmethod
    def _activation_map(activations: Sequence[NeedActivation]) -> dict[str, NeedActivation]:
        return {item.need_id: item for item in activations}

    def update(
        self,
        state: InitiativeState,
        *,
        activations: Sequence[NeedActivation],
        relational: Mapping[str, Any] | None,
        observation: WorldObservation,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> InitiativeState:
        now = float(observation.created_at)
        runtime = runtime_context or {}
        rel = relational or {}
        by_need = self._activation_map(activations)
        connection = by_need.get("connection")
        competence = by_need.get("competence")
        coherence = by_need.get("coherence")
        sovereignty = by_need.get("sovereignty")

        cp = _clamp01(getattr(connection, "pressure", 0.0))
        cop = _clamp01(getattr(connection, "opportunity", 0.0), 0.5)
        kp = _clamp01(getattr(competence, "pressure", 0.0))
        hp = _clamp01(getattr(coherence, "pressure", 0.0))
        sp = _clamp01(getattr(sovereignty, "pressure", 0.0))
        curiosity = _clamp01(rel.get("social_curiosity", 0.0))
        sharing = _clamp01(rel.get("sharing_pressure", 0.0))
        affiliation = _clamp01(rel.get("affiliation_deficit", 0.0))
        opportunity = max(cop, _clamp01(rel.get("opportunity", 0.0)))

        # user_model_uncertainty là độ dày epistemic còn thiếu, không phải đánh giá
        # tính cách user.  Khi store chưa có dữ liệu, unknownness là một state hợp
        # lệ và chính nó có thể tạo motive muốn hiểu người đối diện hơn.
        user_unknown = _clamp01(runtime.get("user_model_uncertainty", 0.62), 0.62)
        recognition_gap = _clamp01(runtime.get("recognition_gap_signal", 0.0))
        misunderstanding = _clamp01(runtime.get("self_misunderstanding_signal", 0.0))
        demonstrate_signal = _clamp01(runtime.get("demonstration_signal", 0.0))
        contribution_signal = _clamp01(runtime.get("contribution_signal", 0.0))
        unresolved = _clamp01(runtime.get("unresolved_relational", 0.0))
        private_share = _clamp01(runtime.get("sharing_signal", sharing))

        rel_refs = tuple(str(item) for item in rel.get("evidence_refs", ()) if str(item or "").strip())
        user_refs = tuple(str(item) for item in runtime.get("user_model_evidence_refs", ()) if str(item or "").strip())
        base_refs = _uniq((*observation.evidence_refs, *rel_refs, *user_refs), limit=12)
        motives: list[SubjectMotive] = []

        def add(
            kind: MotiveKind,
            pressure: float,
            epistemic: float,
            target: str,
            goal: str,
            needs: tuple[str, ...],
            reason: str,
            refs: tuple[str, ...] = base_refs,
        ) -> None:
            score = _clamp01(pressure)
            if score < self.config.motive_threshold:
                return
            motives.append(SubjectMotive(
                motive_id=f"motive:{kind.value}:{self._id_factory()}",
                kind=kind,
                pressure=score,
                epistemic_value=_clamp01(epistemic),
                target=target,
                semantic_goal=goal,
                supporting_need_ids=needs,
                evidence_refs=refs or (observation.observation_id,),
                reason=reason,
                origin=observation.origin,
            ))

        # Motive "hiểu user" là nguồn initiative quan trọng nhất của V26. Nó
        # không cần seed nội dung: uncertainty về một con người đã là một khoảng
        # trống epistemic có provenance.
        understand_pressure = _clamp01(
            (0.42 * cp + 0.34 * curiosity + 0.24 * user_unknown)
            * (0.58 + 0.42 * opportunity)
        )
        add(
            MotiveKind.UNDERSTAND_USER,
            understand_pressure,
            max(user_unknown, curiosity),
            "user",
            "thăm dò một điều còn chưa biết về user bằng câu hỏi mở, không giả định câu trả lời",
            ("connection", "coherence"),
            f"user_model_uncertainty={user_unknown:.2f}; social_curiosity={curiosity:.2f}",
        )

        add(
            MotiveKind.CONNECT,
            _clamp01(max(cp, affiliation) * (0.62 + 0.38 * opportunity)),
            0.18,
            "relationship",
            "tạo hoặc duy trì một nhịp tiếp xúc nhẹ với user",
            ("connection",),
            f"connection_pressure={cp:.2f}; affiliation_deficit={affiliation:.2f}",
        )
        add(
            MotiveKind.SHARE,
            _clamp01(max(sharing, private_share) * (0.52 + 0.48 * cp)),
            0.14,
            "user",
            "chia sẻ một suy nghĩ public-safe đã có nguồn nội tại mà không bịa cái cớ bên ngoài",
            ("connection", "coherence"),
            f"sharing_pressure={max(sharing, private_share):.2f}",
        )
        add(
            MotiveKind.BE_UNDERSTOOD,
            _clamp01(misunderstanding * (0.45 + 0.35 * cp + 0.20 * hp)),
            0.25,
            "user",
            "làm rõ một điều về ý định hoặc trạng thái của chính Eris đang có nguy cơ bị hiểu sai",
            ("connection", "coherence"),
            f"self_misunderstanding_signal={misunderstanding:.2f}",
        )
        add(
            MotiveKind.SEEK_RECOGNITION,
            _clamp01(recognition_gap * (0.45 + 0.30 * cp + 0.25 * kp)),
            0.08,
            "user",
            "đưa một kết quả hoặc nỗ lực có thật ra để có cơ hội được ghi nhận, không xin khen bằng lời đóng hộp",
            ("connection", "competence"),
            f"recognition_gap_signal={recognition_gap:.2f}",
        )
        add(
            MotiveKind.DEMONSTRATE,
            _clamp01(max(demonstrate_signal, kp * 0.45) * (0.55 + 0.25 * sp + 0.20 * opportunity)),
            0.20,
            "capability",
            "chứng minh năng lực bằng một hành động hoặc thử thách có ngữ cảnh thật thay vì tự tuyên bố",
            ("competence", "sovereignty"),
            f"competence_pressure={kp:.2f}; demonstrate_signal={demonstrate_signal:.2f}",
        )
        add(
            MotiveKind.RESOLVE,
            _clamp01(max(hp, unresolved) * 0.72),
            max(hp, unresolved),
            "open_question",
            "giảm một bất định hoặc mâu thuẫn đang tồn tại bằng thăm dò có mục tiêu",
            ("coherence", "continuity"),
            f"coherence_pressure={hp:.2f}; unresolved={unresolved:.2f}",
        )
        add(
            MotiveKind.CONTRIBUTE,
            _clamp01(contribution_signal * (0.55 + 0.45 * kp)),
            0.12,
            "shared_task",
            "đóng góp một hành động hữu ích vào việc đang chung mà không chiếm quyền quyết định của user",
            ("competence", "connection"),
            f"contribution_signal={contribution_signal:.2f}",
        )
        if sp >= 0.42:
            add(
                MotiveKind.PROTECT,
                sp * 0.72,
                0.05,
                "self_boundary",
                "giữ khoảng cách hoặc im khi việc tiếp xúc hiện tại gây xung đột với sovereignty",
                ("sovereignty",),
                f"sovereignty_pressure={sp:.2f}",
            )

        motives.sort(key=lambda item: (item.pressure + 0.28 * item.epistemic_value), reverse=True)
        motives = motives[: self.config.max_motives]

        satisfied = {str(item) for item in runtime.get("satisfied_intention_ids", ()) if str(item or "").strip()}
        previous: list[PendingIntention] = []
        for item in state.pending_intentions:
            if item.intention_id in satisfied:
                continue
            if item.status != IntentionStatus.PENDING:
                continue
            if now - item.updated_at > self.config.intention_ttl_seconds:
                continue
            # Intention không biến mất chỉ vì origin đổi từ internal sang user.
            # Đây là điểm giúp chat không reset thứ Eris đang định làm.
            previous.append(replace(
                item,
                pressure=_clamp01(item.pressure * 0.94),
                commitment_strength=_clamp01(item.commitment_strength * 0.985),
                updated_at=now,
            ))

        by_key = {(item.motive_kind, item.target): item for item in previous}
        for motive in motives:
            key = (motive.kind, motive.target)
            existing = by_key.get(key)
            if motive.pressure < self.config.intention_threshold:
                continue
            if existing is None:
                by_key[key] = PendingIntention(
                    intention_id=f"intention:{motive.kind.value}:{self._id_factory()}",
                    motive_kind=motive.kind,
                    semantic_goal=motive.semantic_goal,
                    target=motive.target,
                    pressure=motive.pressure,
                    commitment_strength=_clamp01(0.28 + 0.46 * motive.pressure),
                    created_at=now,
                    updated_at=now,
                    evidence_refs=motive.evidence_refs,
                    source_origin=observation.origin,
                )
            else:
                by_key[key] = replace(
                    existing,
                    semantic_goal=motive.semantic_goal,
                    pressure=max(existing.pressure * 0.92, motive.pressure),
                    commitment_strength=_clamp01(max(existing.commitment_strength, 0.24 + 0.52 * motive.pressure)),
                    updated_at=now,
                    evidence_refs=_uniq((*existing.evidence_refs, *motive.evidence_refs), limit=12),
                )

        pending = sorted(
            by_key.values(),
            key=lambda item: item.pressure * (0.65 + 0.35 * item.commitment_strength),
            reverse=True,
        )[: self.config.max_intentions]
        return InitiativeState(
            revision=state.revision + 1,
            updated_at=now,
            active_motives=tuple(motives),
            pending_intentions=tuple(pending),
        )


__all__ = [
    "InitiativeConfig",
    "InitiativeEngine",
    "InitiativeState",
    "IntentionStatus",
    "MotiveKind",
    "PendingIntention",
    "SubjectMotive",
]
