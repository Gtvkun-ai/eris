# -*- coding: utf-8 -*-
"""Observer xã hội chạy song song cho ERIS.

Mục tiêu của module này rất hẹp:
- Model phụ chỉ đọc tín hiệu xã hội và trả event có cấu trúc.
- Model phụ không viết, sửa, chặn hay chọn câu public.
- Runtime chỉ áp dụng delta nhỏ, có giới hạn, cho state dài hạn.
- Lỗi provider phải fail-open: chat chính vẫn chạy bình thường.

Nói ngắn gọn: đây là cảm biến, không phải biên tập viên. Ta đã thử để cảm biến
cầm bút rồi; kết quả giống việc giao vô-lăng cho nhiệt kế.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, MutableMapping, Sequence


SOCIAL_OBSERVER_VERSION = "social_observer.v1.observe_only"


def _clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def _compact_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


_ALLOWED_ACTS = {
    "neutral",
    "greeting",
    "task",
    "compliment",
    "affection_bid",
    "request_reciprocity",
    "vulnerability",
    "correction",
    "repair_request",
    "playful_tease",
    "hostility",
    "boundary_probe",
    "acceptance",
    "other",
}


@dataclass(frozen=True, slots=True)
class SocialObservation:
    act: str = "neutral"
    closeness_bid: float = 0.0
    vulnerability: float = 0.0
    compliment: float = 0.0
    playfulness: float = 0.0
    correction: float = 0.0
    repair_signal: float = 0.0
    assistant_fault_probability: float = 0.0
    hostility: float = 0.0
    acceptance: float = 0.0
    boundary_probe: float = 0.0
    user_requests_less_distance: float = 0.0
    ambiguity: float = 0.0
    confidence: float = 0.0
    memory_worthy: bool = False
    evidence: tuple[str, ...] = ()
    notes: str = ""
    source: str = "none"
    latency_ms: float = 0.0

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        source: str = "model",
        latency_ms: float = 0.0,
    ) -> "SocialObservation":
        data = payload or {}
        act = str(data.get("act", "neutral") or "neutral").strip().lower()
        if act not in _ALLOWED_ACTS:
            act = "other"
        raw_evidence = data.get("evidence", ())
        if isinstance(raw_evidence, str):
            evidence = (_compact_text(raw_evidence, 140),) if raw_evidence.strip() else ()
        elif isinstance(raw_evidence, Sequence):
            evidence = tuple(
                item
                for item in (_compact_text(value, 140) for value in raw_evidence[:3])
                if item
            )
        else:
            evidence = ()
        return cls(
            act=act,
            closeness_bid=_clamp01(data.get("closeness_bid", 0.0)),
            vulnerability=_clamp01(data.get("vulnerability", 0.0)),
            compliment=_clamp01(data.get("compliment", 0.0)),
            playfulness=_clamp01(data.get("playfulness", 0.0)),
            correction=_clamp01(data.get("correction", 0.0)),
            repair_signal=_clamp01(data.get("repair_signal", 0.0)),
            assistant_fault_probability=_clamp01(data.get("assistant_fault_probability", 0.0)),
            hostility=_clamp01(data.get("hostility", 0.0)),
            acceptance=_clamp01(data.get("acceptance", 0.0)),
            boundary_probe=_clamp01(data.get("boundary_probe", 0.0)),
            user_requests_less_distance=_clamp01(data.get("user_requests_less_distance", 0.0)),
            ambiguity=_clamp01(data.get("ambiguity", 0.0)),
            confidence=_clamp01(data.get("confidence", 0.0)),
            memory_worthy=bool(data.get("memory_worthy", False)),
            evidence=evidence,
            notes=_compact_text(data.get("notes", ""), 220),
            source=str(source or "model"),
            latency_ms=max(0.0, float(latency_ms or 0.0)),
        )

    @property
    def needs_deep_review(self) -> bool:
        if self.confidence < 0.68 or self.ambiguity >= 0.42:
            return True
        # Correction/repair/vulnerability mạnh đáng được xem kỹ hơn. Không phải
        # để sửa câu hiện tại, mà để đừng ghi state dài hạn sai chỉ vì parser vội.
        return max(self.correction, self.repair_signal, self.vulnerability, self.boundary_probe) >= 0.72

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SOCIAL_OBSERVER_VERSION,
            "act": self.act,
            "closeness_bid": round(self.closeness_bid, 4),
            "vulnerability": round(self.vulnerability, 4),
            "compliment": round(self.compliment, 4),
            "playfulness": round(self.playfulness, 4),
            "correction": round(self.correction, 4),
            "repair_signal": round(self.repair_signal, 4),
            "assistant_fault_probability": round(self.assistant_fault_probability, 4),
            "hostility": round(self.hostility, 4),
            "acceptance": round(self.acceptance, 4),
            "boundary_probe": round(self.boundary_probe, 4),
            "user_requests_less_distance": round(self.user_requests_less_distance, 4),
            "ambiguity": round(self.ambiguity, 4),
            "confidence": round(self.confidence, 4),
            "memory_worthy": self.memory_worthy,
            "evidence": list(self.evidence),
            "notes": self.notes,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 2),
        }

    def prompt_hint(self) -> str:
        """Tóm tắt cực ngắn cho lượt kế tiếp, không phải social contract."""
        if self.confidence < 0.60:
            return ""
        bits: list[str] = []
        if self.act not in {"neutral", "other", "task"}:
            bits.append(f"tín hiệu gần nhất={self.act}")
        if self.repair_signal >= 0.60 or self.correction >= 0.60:
            bits.append("còn một điểm cần sửa/đáp lại trực tiếp")
        if self.closeness_bid >= 0.60:
            bits.append("người dùng đang chủ động gần gũi")
        if self.vulnerability >= 0.60:
            bits.append("lượt trước có sự dễ tổn thương rõ")
        if self.hostility >= 0.68:
            bits.append("có xung đột thật, không mặc định là đùa")
        if not bits:
            return ""
        return "; ".join(bits[:3])


SOCIAL_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "act",
        "closeness_bid",
        "vulnerability",
        "compliment",
        "playfulness",
        "correction",
        "repair_signal",
        "assistant_fault_probability",
        "hostility",
        "acceptance",
        "boundary_probe",
        "user_requests_less_distance",
        "ambiguity",
        "confidence",
        "memory_worthy",
        "evidence",
        "notes",
    ],
    "properties": {
        "act": {
            "type": "string",
            "enum": sorted(_ALLOWED_ACTS),
        },
        **{
            name: {"type": "number", "minimum": 0.0, "maximum": 1.0}
            for name in (
                "closeness_bid",
                "vulnerability",
                "compliment",
                "playfulness",
                "correction",
                "repair_signal",
                "assistant_fault_probability",
                "hostility",
                "acceptance",
                "boundary_probe",
                "user_requests_less_distance",
                "ambiguity",
                "confidence",
            )
        },
        "memory_worthy": {"type": "boolean"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "notes": {"type": "string"},
    },
}


@dataclass(slots=True)
class SocialObserverTicket:
    ticket_id: str
    turn_id: str
    user_text: str
    previous_assistant_text: str
    submitted_at: float
    future: Future[SocialObservation]
    metadata_target: MutableMapping[str, Any] | None = None
    previous_frame: Any | None = None
    _completed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def claim_completion(self) -> bool:
        with self._lock:
            if self._completed:
                return False
            self._completed = True
            return True


class SocialObserverRuntime:
    """Chạy observer ngoài hot path và áp dụng kết quả sau public commit."""

    def __init__(self, router: Any, *, logger: Any | None = None, max_workers: int = 2) -> None:
        self.router = router
        self.logger = logger
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, int(max_workers or 2))),
            thread_name_prefix="eris-social-observer",
        )
        self._tickets: dict[str, SocialObserverTicket] = {}
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        user_text: str,
        previous_assistant_text: str = "",
        previous_user_text: str = "",
        history: Sequence[str] = (),
        turn_id: str = "",
        metadata_target: MutableMapping[str, Any] | None = None,
        previous_frame: Any | None = None,
    ) -> SocialObserverTicket:
        ticket_id = f"social_{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()

        def _work() -> SocialObservation:
            try:
                observation = self.router.observe_turn(
                    user_text=user_text,
                    previous_assistant_text=previous_assistant_text,
                    previous_user_text=previous_user_text,
                    history=history,
                )
                elapsed = (time.perf_counter() - started) * 1000.0
                return replace(observation, latency_ms=elapsed)
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    try:
                        self.logger.warning("[social observer] worker failed: %s", exc)
                    except Exception:
                        pass
                return SocialObservation(source=f"error:{type(exc).__name__}")

        ticket = SocialObserverTicket(
            ticket_id=ticket_id,
            turn_id=str(turn_id or ticket_id),
            user_text=str(user_text or ""),
            previous_assistant_text=str(previous_assistant_text or ""),
            submitted_at=time.time(),
            future=self.executor.submit(_work),
            metadata_target=metadata_target,
            previous_frame=previous_frame,
        )
        with self._lock:
            self._tickets[ticket_id] = ticket
        return ticket

    def take(self, ticket_id: str) -> SocialObserverTicket | None:
        with self._lock:
            return self._tickets.pop(str(ticket_id or ""), None)

    def complete(
        self,
        ticket: SocialObserverTicket | None,
        *,
        host: Any,
        assistant_text: str = "",
        assistant_meta: MutableMapping[str, Any] | None = None,
    ) -> None:
        if ticket is None:
            return

        def _apply_from_future(future: Future[SocialObservation]) -> None:
            if not ticket.claim_completion():
                return
            try:
                observation = future.result()
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    try:
                        self.logger.warning("[social observer] result failed: %s", exc)
                    except Exception:
                        pass
                return
            self._apply_observation(
                host,
                observation,
                user_text=ticket.user_text,
                assistant_text=assistant_text,
                turn_id=ticket.turn_id,
                user_meta=ticket.metadata_target,
                assistant_meta=assistant_meta,
                previous_frame=ticket.previous_frame,
            )

        if ticket.future.done():
            _apply_from_future(ticket.future)
        else:
            # Callback chỉ được đăng ký SAU khi chat đã commit frame/state. Nhờ đó
            # observer không đua rồi bị frame cũ ghi đè ngay sau đó.
            ticket.future.add_done_callback(_apply_from_future)

    def _apply_observation(
        self,
        host: Any,
        observation: SocialObservation,
        *,
        user_text: str,
        assistant_text: str,
        turn_id: str,
        user_meta: MutableMapping[str, Any] | None,
        assistant_meta: MutableMapping[str, Any] | None,
        previous_frame: Any | None,
    ) -> None:
        payload = observation.to_dict()
        if user_meta is not None:
            user_meta["social_observer"] = payload
            user_meta["social_observer_pending"] = False
        if assistant_meta is not None:
            assistant_meta["social_observer_source"] = observation.source
        setattr(host, "latest_social_observation", observation)
        setattr(host, "current_social_observation", observation)
        setattr(
            host,
            "pending_social_repair",
            bool(
                observation.confidence >= 0.60
                and max(observation.repair_signal, observation.correction) >= 0.58
            ),
        )

        engine = getattr(host, "social_cognition_v2", None)
        ingest = getattr(engine, "ingest_observation", None)
        if callable(ingest):
            try:
                ingest(user_text=user_text, observation=observation, turn_id=turn_id)
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    try:
                        self.logger.debug("[social observer] social-state ingest failed: %s", exc)
                    except Exception:
                        pass

        self._apply_outcome_feedback(
            previous_frame,
            observation,
            user_text=user_text,
            payload=payload,
        )
        self._nudge_relationship_state(host, observation)
        self._write_panel_telemetry(host, payload)

        if self.logger is not None:
            try:
                self.logger.info(
                    "[social observer] act=%s conf=%.2f ambiguity=%.2f close=%.2f repair=%.2f "
                    "hostility=%.2f source=%s latency=%.0fms",
                    observation.act,
                    observation.confidence,
                    observation.ambiguity,
                    observation.closeness_bid,
                    observation.repair_signal,
                    observation.hostility,
                    observation.source,
                    observation.latency_ms,
                )
            except Exception:
                pass

    @staticmethod
    def _apply_outcome_feedback(
        previous_frame: Any | None,
        observation: SocialObservation,
        *,
        user_text: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Chiếu feedback AI vào OutcomeReport của frame trước.

        Đây là học hậu kỳ, không phải một gate của câu đang nói. Observer có thể
        báo lượt trước bị sửa/được chấp nhận, nhưng không được quay ngược thời gian
        để giật câu public hiện tại khỏi tay model chính.
        """
        if previous_frame is None or observation.confidence < 0.52:
            return
        try:
            from runtime.outcome_observer import OutcomeReport

            outcome = OutcomeReport.from_any(getattr(previous_frame, "outcome", None))
            correction_pressure = max(
                float(getattr(outcome, "correction_pressure", 0.0) or 0.0),
                observation.correction,
                observation.repair_signal,
                observation.assistant_fault_probability * 0.88,
            )
            rupture_pressure = max(
                float(getattr(outcome, "rupture_pressure", 0.0) or 0.0),
                observation.hostility * 0.86,
                observation.boundary_probe * 0.62,
                observation.repair_signal * 0.52,
            )
            acceptance_pressure = max(
                float(getattr(outcome, "acceptance_pressure", 0.0) or 0.0),
                observation.acceptance,
                observation.compliment * 0.52,
            )
            outcome.correction_pressure = _clamp01(correction_pressure)
            outcome.rupture_pressure = _clamp01(rupture_pressure)
            outcome.acceptance_pressure = _clamp01(acceptance_pressure)
            outcome.user_corrected = bool(outcome.user_corrected or correction_pressure >= 0.58)
            if acceptance_pressure >= 0.66 and rupture_pressure < 0.34:
                outcome.user_accepted = True
                outcome.relation_improved = True
            if rupture_pressure >= 0.68:
                outcome.relation_ruptured = True
            outcome.feedback_text = _compact_text(user_text, 320)
            outcome.correction_text = (
                _compact_text(user_text, 240) if correction_pressure >= 0.58 else outcome.correction_text
            )
            outcome.confidence = max(float(getattr(outcome, "confidence", 0.0) or 0.0), observation.confidence)
            outcome.social_appraisal = dict(payload)
            outcome.evidence = list(dict.fromkeys((
                *list(getattr(outcome, "evidence", ()) or ()),
                *list(observation.evidence),
            )))[:8]
            outcome.tags = list(dict.fromkeys((
                *list(getattr(outcome, "tags", ()) or ()),
                "ai_social_observer",
                f"social_act:{observation.act}",
            )))
            previous_frame.outcome = outcome
            metadata = getattr(previous_frame, "metadata", None)
            if isinstance(metadata, MutableMapping):
                metadata["ai_social_feedback"] = dict(payload)
        except Exception:
            return

    @staticmethod
    def _nudge_relationship_state(host: Any, observation: SocialObservation) -> None:
        if observation.confidence < 0.55:
            return
        getter = getattr(host, "_get_internal_state", None)
        setter = getattr(host, "_set_internal_state", None)
        if not callable(getter) or not callable(setter):
            return
        try:
            from cortex.relationship_dynamics import RelationshipDynamicsState

            internal = getter()
            relation = RelationshipDynamicsState.from_dict(
                getattr(getattr(internal, "relationship_dynamics", None), "to_dict", lambda: {})()
            )
            weight = max(0.15, min(1.0, observation.confidence))

            # Delta luôn nhỏ. Observer đề xuất hướng; runtime giữ quán tính.
            relation.familiarity = _clamp01(
                relation.familiarity
                + weight * 0.010 * max(observation.acceptance, observation.closeness_bid, observation.compliment)
            )
            relation.trust = _clamp01(
                relation.trust
                + weight * (
                    0.018 * observation.acceptance
                    + 0.010 * observation.closeness_bid
                    - 0.020 * observation.hostility
                    - 0.012 * observation.assistant_fault_probability
                )
            )
            relation.rupture = _clamp01(
                relation.rupture
                + weight * (
                    0.026 * max(observation.repair_signal, observation.correction)
                    + 0.020 * observation.hostility
                    - 0.018 * observation.acceptance
                )
            )
            relation.repair = _clamp01(
                relation.repair
                + weight * 0.014 * observation.acceptance * max(0.25, relation.rupture)
            )
            relation.attachment_visibility = _clamp01(
                relation.attachment_visibility
                + weight * (
                    0.010 * observation.closeness_bid
                    + 0.006 * observation.vulnerability
                    - 0.018 * observation.boundary_probe
                )
            )
            relation.preferred_distance = _clamp01(
                relation.preferred_distance
                + weight * (
                    0.018 * observation.boundary_probe
                    + 0.012 * observation.hostility
                    - 0.014 * observation.user_requests_less_distance
                    - 0.006 * observation.closeness_bid
                )
            )
            relation.engagement_investment = _clamp01(
                relation.engagement_investment
                + weight * 0.012 * max(
                    observation.closeness_bid,
                    observation.vulnerability,
                    observation.compliment,
                    observation.acceptance,
                    observation.playfulness,
                )
            )
            relation.playful_safety = _clamp01(
                relation.playful_safety
                + weight * (0.016 * observation.playfulness - 0.018 * observation.hostility)
            )
            relation.overread_correction = _clamp01(
                relation.overread_correction
                + weight * 0.020 * max(observation.correction, observation.assistant_fault_probability)
            )
            relation.irritation_memory = _clamp01(
                relation.irritation_memory + weight * 0.010 * observation.hostility
            )
            relation.last_event = f"ai_observer:{observation.act}"
            relation.last_update_turn = max(0, int(getattr(relation, "last_update_turn", 0) or 0) + 1)
            updated = replace(internal, relationship_dynamics=relation)
            setter(updated)
        except Exception:
            # Observer không bao giờ được quyền làm chết chat.
            return

    @staticmethod
    def _write_panel_telemetry(host: Any, payload: Mapping[str, Any]) -> None:
        try:
            relation = getattr(host._get_internal_state(), "relationship_dynamics", None)
            relation_payload = (
                relation.to_dict()
                if relation is not None and callable(getattr(relation, "to_dict", None))
                else {}
            )
            from runtime.panel_snapshot import write_social_observation

            write_social_observation(
                dict(payload),
                relationship_state=relation_payload,
            )
        except Exception:
            return

    @staticmethod
    def build_prompt_context(host: Any) -> str:
        """Context quan hệ tối đa vài chục token cho lượt kế tiếp."""
        observation = getattr(host, "latest_social_observation", None)
        hint = observation.prompt_hint() if isinstance(observation, SocialObservation) else ""
        try:
            relation = getattr(host._get_internal_state(), "relationship_dynamics", None)
            rupture = float(getattr(relation, "rupture", 0.0) or 0.0)
            distance = float(getattr(relation, "preferred_distance", 0.58) or 0.58)
            familiarity = float(getattr(relation, "familiarity", 0.0) or 0.0)
        except Exception:
            rupture, distance, familiarity = 0.0, 0.58, 0.0

        state_bits: list[str] = []
        if familiarity >= 0.68:
            state_bits.append("độ quen thuộc cao")
        elif familiarity >= 0.38:
            state_bits.append("độ quen thuộc vừa")
        if rupture >= 0.25:
            state_bits.append("còn dư âm cần repair")
        if distance <= 0.38:
            state_bits.append("khoảng cách hiện tại khá gần")
        elif distance >= 0.72:
            state_bits.append("đang giữ khoảng cách")

        parts = [part for part in ("; ".join(state_bits[:2]), hint) if part]
        return ". ".join(parts[:2]).strip()

    def shutdown(self) -> None:
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


__all__ = [
    "SOCIAL_OBSERVATION_SCHEMA",
    "SOCIAL_OBSERVER_VERSION",
    "SocialObservation",
    "SocialObserverRuntime",
    "SocialObserverTicket",
]
