# -*- coding: utf-8 -*-
"""Atomic short-horizon continuation lanes for voice-first social timing.

Two lanes are intentionally distinct:

* afterbeat: the second beat was approved with the first line and only waits for
  audio completion plus a rhetorical pause;
* social exposure: the first line took a social risk, so recovery is contingent
  on a reaction window ending without a user signal.

The runtime owns IDs, clocks, leases and idempotency. The model owns semantic
objectives, keeping operational state out of model proposals.
"""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .atomic_state import SQLiteAtomicStateStore, SQLiteStateTransaction
from .social_candidate import SocialSpeechCandidate
from .affordance import ExecutiveAffordance
from .social_plan import normalize_afterbeat, normalize_exposure


CONTINUATION_STATE_SCHEMA = "eris.social_continuation_state.v1"
_FINAL_STATUSES = {"SPOKEN", "CANCELLED", "EXPIRED", "RESOLVED"}
_WAITING_STATUSES = {"WAITING_AUDIO_END", "WAITING_PAUSE", "WAITING_REACTION"}


def _compact(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(minimum, min(maximum, number))


def _pause_seconds(pause_class: str) -> float:
    return {"micro": 0.28, "short": 0.65, "held": 1.55}.get(str(pause_class or "short"), 0.65)


def _reaction_seconds(window_class: str) -> float:
    return {"micro": 0.85, "short": 2.2, "held": 4.0}.get(str(window_class or "short"), 2.2)


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


@dataclass(frozen=True, slots=True)
class ContinuationTicket:
    ticket_id: str
    lane: str
    source_turn_id: str
    source_text: str
    source_turn_seq: int
    objective: str
    role: str
    tone: str
    confidence: float
    created_at: float
    expires_at: float
    status: str = "WAITING_AUDIO_END"
    version: int = 1
    audio_finished_at: float = 0.0
    due_at: float = 0.0
    claim_owner: str = ""
    claim_until: float = 0.0
    claim_token: str = ""
    idempotency_key: str = ""
    expected_responses: tuple[str, ...] = ()
    silence_hypotheses: tuple[str, ...] = ()
    exposure_kind: str = "none"
    recovery_style: str = "none"
    timing_class: str = "short"
    actual_response: str = ""
    resolved_reason: str = ""
    spoken_text: str = ""
    updated_at: float = 0.0

    @property
    def active(self) -> bool:
        return self.status not in _FINAL_STATUSES

    @property
    def claimed(self) -> bool:
        return self.status == "CLAIMED"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ContinuationTicket | None":
        data = payload or {}
        ticket_id = _compact(data.get("ticket_id", ""), 120)
        lane = _compact(data.get("lane", ""), 48).lower()
        objective = _compact(data.get("objective", ""), 420)
        if not ticket_id or lane not in {"afterbeat", "social_exposure"} or not objective:
            return None
        created = _float(data.get("created_at", 0.0), 0.0, minimum=0.0, maximum=10**12)
        expires = _float(data.get("expires_at", created + 8.0), created + 8.0, minimum=created, maximum=created + 120.0)
        status = _compact(data.get("status", "CANCELLED"), 32).upper() or "CANCELLED"
        if status not in {
            "WAITING_AUDIO_END", "WAITING_PAUSE", "WAITING_REACTION", "CLAIMED",
            "SPOKEN", "CANCELLED", "EXPIRED", "RESOLVED",
        }:
            status = "CANCELLED"
        expected = tuple(
            item for item in (_compact(v, 96) for v in _sequence(data.get("expected_responses"))[:6]) if item
        )
        hypotheses = tuple(
            item for item in (_compact(v, 120) for v in _sequence(data.get("silence_hypotheses"))[:4]) if item
        )
        return cls(
            ticket_id=ticket_id,
            lane=lane,
            source_turn_id=_compact(data.get("source_turn_id", ""), 120),
            source_text=_compact(data.get("source_text", ""), 420),
            source_turn_seq=max(0, int(data.get("source_turn_seq", 0) or 0)),
            objective=objective,
            role=_compact(data.get("role", "afterthought"), 48).lower() or "afterthought",
            tone=_compact(data.get("tone", "neutral"), 48).lower() or "neutral",
            confidence=_float(data.get("confidence", 0.0), 0.0, minimum=0.0, maximum=1.0),
            created_at=created,
            expires_at=expires,
            status=status,
            version=max(1, int(data.get("version", 1) or 1)),
            audio_finished_at=_float(data.get("audio_finished_at", 0.0), 0.0, minimum=0.0, maximum=10**12),
            due_at=_float(data.get("due_at", 0.0), 0.0, minimum=0.0, maximum=10**12),
            claim_owner=_compact(data.get("claim_owner", ""), 120),
            claim_until=_float(data.get("claim_until", 0.0), 0.0, minimum=0.0, maximum=10**12),
            claim_token=_compact(data.get("claim_token", ""), 180),
            idempotency_key=_compact(data.get("idempotency_key", ""), 180),
            expected_responses=expected,
            silence_hypotheses=hypotheses,
            exposure_kind=_compact(data.get("exposure_kind", "none"), 64).lower() or "none",
            recovery_style=_compact(data.get("recovery_style", "none"), 64).lower() or "none",
            timing_class=_compact(data.get("timing_class", "short"), 24).lower() or "short",
            actual_response=_compact(data.get("actual_response", ""), 240),
            resolved_reason=_compact(data.get("resolved_reason", ""), 120),
            spoken_text=_compact(data.get("spoken_text", ""), 420),
            updated_at=_float(data.get("updated_at", created), created, minimum=0.0, maximum=10**12),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_responses"] = list(self.expected_responses)
        payload["silence_hypotheses"] = list(self.silence_hypotheses)
        return payload


@dataclass(frozen=True, slots=True)
class SocialContinuationState:
    version: int = 0
    tickets: tuple[ContinuationTicket, ...] = ()
    outcomes: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, int] = field(default_factory=dict)
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SocialContinuationState":
        data = payload or {}
        tickets = tuple(
            ticket
            for ticket in (
                ContinuationTicket.from_mapping(item)
                for item in _sequence(data.get("tickets"))[-24:]
                if isinstance(item, Mapping)
            )
            if ticket is not None
        )
        outcomes = tuple(dict(item) for item in _sequence(data.get("outcomes"))[-40:] if isinstance(item, Mapping))
        raw_metrics = data.get("metrics", {})
        metrics = {
            str(k): max(0, int(v or 0))
            for k, v in dict(raw_metrics).items()
            if isinstance(raw_metrics, Mapping)
        } if isinstance(raw_metrics, Mapping) else {}
        return cls(
            version=max(0, int(data.get("version", 0) or 0)),
            tickets=tickets,
            outcomes=outcomes,
            metrics=metrics,
            updated_at=_float(data.get("updated_at", 0.0), 0.0, minimum=0.0, maximum=10**12),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTINUATION_STATE_SCHEMA,
            "version": self.version,
            "tickets": [ticket.to_dict() for ticket in self.tickets],
            "outcomes": [dict(item) for item in self.outcomes],
            "metrics": dict(self.metrics),
            "updated_at": self.updated_at,
        }


class SocialContinuationRuntime:
    """Atomic owner of afterbeat and social-exposure tickets."""

    def __init__(
        self,
        *,
        initial_state: Mapping[str, Any] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        wake_callback: Callable[[str], None] | None = None,
        outcome_callback: Callable[..., None] | None = None,
        logger: Any | None = None,
        clock: Callable[[], float] | None = None,
        timer_factory: Callable[..., Any] | None = None,
        atomic_store: SQLiteAtomicStateStore | None = None,
        atomic_key: str = "eris.social_continuation",
    ) -> None:
        self._clock = clock or time.time
        self._persist = persist
        self._atomic_store = atomic_store
        self._atomic_key = str(atomic_key or "eris.social_continuation")
        self._atomic_tx: SQLiteStateTransaction | None = None
        self._wake_callback = wake_callback
        self._outcome_callback = outcome_callback
        self._logger = logger
        self._lock = threading.RLock()
        self._state = SocialContinuationState.from_mapping(initial_state)
        if self._atomic_store is not None:
            record = self._atomic_store.ensure(self._atomic_key, self._state.to_dict())
            self._state = SocialContinuationState.from_mapping(record.payload)
        self._timer_factory = timer_factory or threading.Timer
        self._timer: Any | None = None
        with self._lock, self._state_transaction_locked():
            self._repair_after_restart_locked(self._clock())
            self._arm_timer_locked()

    def schedule_from_social_plan(
        self,
        social_plan: Mapping[str, Any] | None,
        *,
        source_turn_id: str,
        source_text: str,
        source_turn_seq: int,
        semantic_frame: Mapping[str, Any] | None = None,
        assistant_act: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, bool]:
        data = social_plan or {}
        current = float(now if now is not None else self._clock())
        frame = semantic_frame or {}
        act = assistant_act or {}
        blocked = self._blocked_context(frame, act)
        afterbeat = normalize_afterbeat(data.get("afterbeat") if isinstance(data.get("afterbeat"), Mapping) else None)
        exposure = normalize_exposure(data.get("exposure") if isinstance(data.get("exposure"), Mapping) else None)
        result = {"afterbeat": False, "exposure": False}
        with self._lock, self._state_transaction_locked():
            # A newly committed public line invalidates old short-horizon tickets.
            self._cancel_active_locked("superseded_by_new_public_turn", current)
            tickets = list(self._state.tickets)
            if not blocked and afterbeat["decision"] == "reserve":
                tickets.append(self._make_afterbeat(afterbeat, source_turn_id, source_text, source_turn_seq, current))
                result["afterbeat"] = True
            if not blocked and not result["afterbeat"] and exposure["decision"] == "open":
                tickets.append(self._make_exposure(exposure, source_turn_id, source_text, source_turn_seq, current))
                result["exposure"] = True
            if result["afterbeat"] or result["exposure"]:
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    tickets=tuple(tickets[-24:]),
                    updated_at=current,
                )
                self._metric_locked("tickets_created", int(result["afterbeat"]) + int(result["exposure"]))
                self._persist_locked()
                self._arm_timer_locked()
        for lane, created in result.items():
            if created:
                self._emit("ticket_created", lane=lane, source_turn_id=source_turn_id)
        return result

    def notify_audio_finished(self, timestamp: float | None = None, *, source_turn_id: str = "") -> int:
        current = float(timestamp if timestamp is not None else self._clock())
        changed = 0
        with self._lock, self._state_transaction_locked():
            tickets = list(self._state.tickets)
            for index, ticket in enumerate(tickets):
                if ticket.status != "WAITING_AUDIO_END":
                    continue
                if source_turn_id and ticket.source_turn_id and ticket.source_turn_id != source_turn_id:
                    continue
                if current > ticket.expires_at:
                    tickets[index] = replace(
                        ticket,
                        status="EXPIRED",
                        resolved_reason="audio_finished_after_expiry",
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        version=ticket.version + 1,
                        updated_at=current,
                    )
                    self._append_outcome_locked(tickets[index], current)
                    self._metric_locked("tickets_expired", 1)
                    changed += 1
                    continue
                if ticket.lane == "afterbeat":
                    pause = _pause_seconds(ticket.timing_class or "short")
                    status = "WAITING_PAUSE"
                else:
                    pause = _reaction_seconds(ticket.timing_class or "short")
                    status = "WAITING_REACTION"
                tickets[index] = replace(
                    ticket,
                    status=status,
                    audio_finished_at=max(ticket.audio_finished_at, current),
                    due_at=max(ticket.due_at, current + pause),
                    version=ticket.version + 1,
                    updated_at=current,
                )
                changed += 1
            if changed:
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    tickets=tuple(tickets),
                    updated_at=current,
                )
                self._metric_locked("audio_finished", changed)
                self._persist_locked()
                self._arm_timer_locked()
        if changed:
            self._emit("audio_finished", count=changed, source_turn_id=source_turn_id)
        return changed

    def peek_due(
        self,
        *,
        now: float | None = None,
        interaction_busy: bool = False,
    ) -> ExecutiveAffordance | None:
        """Read the best due continuation without reserving it."""
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_and_reap_claims_locked(current)
            if interaction_busy:
                self._arm_timer_locked()
                return None
            ranked = sorted(
                (
                    (0 if ticket.lane == "afterbeat" else 1, ticket.due_at, index, ticket)
                    for index, ticket in enumerate(self._state.tickets)
                    if ticket.status in {"WAITING_PAUSE", "WAITING_REACTION"}
                    and ticket.due_at > 0.0
                    and current >= ticket.due_at
                    and current < ticket.expires_at
                ),
                key=lambda item: (item[0], item[1], item[2]),
            )
            if not ranked:
                self._arm_timer_locked()
                return None
            _, _, _, ticket = ranked[0]
            candidate = self._candidate_for(ticket)
            return ExecutiveAffordance(
                affordance_id=f"social_continuation:{ticket.ticket_id}:v{ticket.version}",
                owner="social_continuation",
                revision=ticket.version,
                candidate=candidate,
                claim_required=True,
                expires_at=ticket.expires_at,
                claim_key=ticket.ticket_id,
                metadata={"lane": ticket.lane},
            )

    def claim_affordance(
        self,
        affordance: ExecutiveAffordance,
        *,
        worker_id: str,
        now: float | None = None,
        lease_ms: int = 8000,
    ) -> SocialSpeechCandidate | None:
        """Atomically claim only the affordance selected by the Executive."""
        current = float(now if now is not None else self._clock())
        owner = _compact(worker_id or "anonymous", 100) or "anonymous"
        ticket_id = str(affordance.claim_key or "")
        with self._lock, self._state_transaction_locked():
            self._expire_and_reap_claims_locked(current)
            tickets = list(self._state.tickets)
            for index, ticket in enumerate(tickets):
                if ticket.ticket_id != ticket_id or ticket.version != int(affordance.revision):
                    continue
                if not (
                    ticket.status in {"WAITING_PAUSE", "WAITING_REACTION"}
                    and ticket.due_at > 0.0
                    and current >= ticket.due_at
                    and current < ticket.expires_at
                ):
                    return None
                new_version = ticket.version + 1
                token = f"{ticket.ticket_id}:v{new_version}:{owner}"
                claimed = replace(
                    ticket,
                    status="CLAIMED",
                    version=new_version,
                    claim_owner=owner,
                    claim_until=current + max(0.5, min(30.0, int(lease_ms) / 1000.0)),
                    claim_token=token,
                    updated_at=current,
                )
                tickets[index] = claimed
                self._state = replace(
                    self._state, version=self._state.version + 1, tickets=tuple(tickets), updated_at=current
                )
                self._metric_locked("claims_granted", 1)
                self._persist_locked()
                self._arm_timer_locked()
                self._emit("claim", lane=claimed.lane, ticket_id=claimed.ticket_id, worker_id=owner)
                return self._candidate_for(claimed)
        return None

    def claim_due(
        self,
        *,
        worker_id: str,
        now: float | None = None,
        interaction_busy: bool = False,
        lease_ms: int = 8000,
    ) -> SocialSpeechCandidate | None:
        """Compatibility wrapper over collect-before-claim."""
        preview = self.peek_due(now=now, interaction_busy=interaction_busy)
        if preview is None:
            return None
        return self.claim_affordance(preview, worker_id=worker_id, now=now, lease_ms=lease_ms)

    def release_claim(
        self,
        *,
        ticket_id: str,
        claim_token: str = "",
        reason: str,
        delay_seconds: float = 0.5,
        now: float | None = None,
    ) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            tickets = list(self._state.tickets)
            for index, ticket in enumerate(tickets):
                if ticket.ticket_id != ticket_id or ticket.status != "CLAIMED":
                    continue
                if not claim_token or ticket.claim_token != claim_token:
                    self._metric_locked("stale_release_attempts", 1)
                    return False
                waiting = "WAITING_PAUSE" if ticket.lane == "afterbeat" else "WAITING_REACTION"
                tickets[index] = replace(
                    ticket,
                    status=waiting,
                    due_at=current + max(0.05, min(8.0, float(delay_seconds))),
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    resolved_reason=_compact(reason, 120),
                    version=ticket.version + 1,
                    updated_at=current,
                )
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    tickets=tuple(tickets),
                    updated_at=current,
                )
                self._metric_locked("claims_released", 1)
                self._persist_locked()
                self._arm_timer_locked()
                self._emit("claim_released", lane=ticket.lane, ticket_id=ticket_id, reason=reason)
                return True
        return False

    def note_spoken(self, plan: Any, text: str, *, now: float | None = None) -> bool:
        current = float(now if now is not None else self._clock())
        semantics = getattr(plan, "semantics", None)
        ticket_id = str(getattr(plan, "continuation_ticket_id", "") or getattr(semantics, "subject_key", "") or "").strip()
        claim_token = str(getattr(plan, "continuation_claim_token", "") or "").strip()
        lane = str(getattr(plan, "continuation_lane", "") or "").strip().lower()
        if not ticket_id:
            return False
        with self._lock, self._state_transaction_locked():
            tickets = list(self._state.tickets)
            for index, ticket in enumerate(tickets):
                if ticket.ticket_id != ticket_id or ticket.status != "CLAIMED":
                    continue
                if lane and ticket.lane != lane:
                    return False
                if not claim_token or ticket.claim_token != claim_token:
                    self._metric_locked("stale_spoken_attempts", 1)
                    return False
                completed = replace(
                    ticket,
                    status="SPOKEN",
                    spoken_text=_compact(text, 420),
                    actual_response=ticket.actual_response or "silence",
                    resolved_reason="spoken",
                    claim_owner="",
                    claim_until=0.0,
                    version=ticket.version + 1,
                    updated_at=current,
                )
                tickets[index] = completed
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    tickets=tuple(tickets),
                    updated_at=current,
                )
                self._append_outcome_locked(completed, current)
                self._metric_locked("tickets_spoken", 1)
                self._persist_locked()
                self._arm_timer_locked()
                self._emit("spoken", lane=ticket.lane, ticket_id=ticket_id)
                return True
        return False

    def observe_user_signal(
        self,
        *,
        signal: str,
        text: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Cancel afterbeats and resolve exposure as soon as the user takes the floor."""
        current = float(now if now is not None else self._clock())
        summary = {"cancelled_afterbeats": 0, "resolved_exposures": 0}
        response = _compact(text or signal, 240)
        with self._lock, self._state_transaction_locked():
            tickets = list(self._state.tickets)
            for index, ticket in enumerate(tickets):
                if not ticket.active:
                    continue
                if ticket.lane == "afterbeat":
                    updated = replace(
                        ticket,
                        status="CANCELLED",
                        actual_response=response,
                        resolved_reason="user_signal_before_afterbeat",
                        claim_owner="",
                        claim_until=0.0,
                        version=ticket.version + 1,
                        updated_at=current,
                    )
                    summary["cancelled_afterbeats"] += 1
                else:
                    updated = replace(
                        ticket,
                        status="RESOLVED",
                        actual_response=response,
                        resolved_reason=f"reaction:{_compact(signal, 48)}",
                        claim_owner="",
                        claim_until=0.0,
                        version=ticket.version + 1,
                        updated_at=current,
                    )
                    summary["resolved_exposures"] += 1
                tickets[index] = updated
                self._append_outcome_locked(updated, current)
            if summary["cancelled_afterbeats"] or summary["resolved_exposures"]:
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    tickets=tuple(tickets),
                    updated_at=current,
                )
                self._metric_locked("user_signal_resolutions", summary["cancelled_afterbeats"] + summary["resolved_exposures"])
                self._persist_locked()
                self._arm_timer_locked()
        if summary["cancelled_afterbeats"] or summary["resolved_exposures"]:
            self._emit("user_signal", signal=signal, **summary)
        return summary

    def cancel_all(self, *, reason: str, now: float | None = None) -> int:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            count = self._cancel_active_locked(reason, current)
            if count:
                self._persist_locked()
                self._arm_timer_locked()
        if count:
            self._emit("cancel", reason=reason, count=count)
        return count

    def is_due(self, *, now: float | None = None, interaction_busy: bool = False) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_and_reap_claims_locked(current)
            return bool(
                not interaction_busy
                and any(
                    ticket.status in {"WAITING_PAUSE", "WAITING_REACTION"}
                    and ticket.due_at > 0.0
                    and current >= ticket.due_at
                    and current < ticket.expires_at
                    for ticket in self._state.tickets
                )
            )

    def has_pending(self, *, now: float | None = None) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_and_reap_claims_locked(current)
            return any(ticket.active for ticket in self._state.tickets)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_and_reap_claims_locked(current)
            payload = self._state.to_dict()
            payload["pending"] = sum(1 for ticket in self._state.tickets if ticket.active)
            payload["due"] = any(
                ticket.status in {"WAITING_PAUSE", "WAITING_REACTION"}
                and ticket.due_at > 0.0
                and current >= ticket.due_at
                for ticket in self._state.tickets
            )
            payload["claimed"] = sum(1 for ticket in self._state.tickets if ticket.status == "CLAIMED")
            return payload

    def shutdown(self) -> None:
        with self._lock, self._state_transaction_locked():
            self._cancel_timer_locked()

    @staticmethod
    def _blocked_context(frame: Mapping[str, Any], act: Mapping[str, Any]) -> bool:
        if _compact(frame.get("tool_intent", "none"), 60).lower() not in {"", "none"}:
            return True
        if _compact(frame.get("boundary_action", "none"), 60).lower() not in {"", "none"}:
            return True
        if _compact(act.get("kind", "other"), 40).lower() in {"silence", "question", "repair", "action_report"}:
            return True
        # Serious and safety-sensitive contexts suppress playful continuation
        # through an explicit runtime policy check.
        user_act = _compact(frame.get("user_act", ""), 64).lower()
        return user_act in {"crisis", "medical", "legal", "financial_harm", "grief", "safety_request"}

    def _make_afterbeat(self, proposal: Mapping[str, Any], turn_id: str, text: str, turn_seq: int, now: float) -> ContinuationTicket:
        ticket_id = f"aft_{uuid.uuid4().hex[:16]}"
        pause_class = str(proposal.get("pause_class", "short") or "short")
        return ContinuationTicket(
            ticket_id=ticket_id,
            lane="afterbeat",
            source_turn_id=_compact(turn_id, 120),
            source_text=_compact(text, 420),
            source_turn_seq=max(0, int(turn_seq or 0)),
            objective=_compact(proposal.get("objective", ""), 420),
            role=_compact(proposal.get("role", "afterthought"), 48).lower() or "afterthought",
            tone=_compact(proposal.get("tone", "neutral"), 48).lower() or "neutral",
            confidence=_float(proposal.get("confidence", 0.0), 0.0, minimum=0.0, maximum=1.0),
            created_at=now,
            expires_at=now + 6.0,
            idempotency_key=f"{turn_id}:afterbeat:0",
            timing_class=pause_class,
            updated_at=now,
        )

    def _make_exposure(self, proposal: Mapping[str, Any], turn_id: str, text: str, turn_seq: int, now: float) -> ContinuationTicket:
        ticket_id = f"exp_{uuid.uuid4().hex[:16]}"
        window = str(proposal.get("reaction_window_class", "short") or "short")
        return ContinuationTicket(
            ticket_id=ticket_id,
            lane="social_exposure",
            source_turn_id=_compact(turn_id, 120),
            source_text=_compact(text, 420),
            source_turn_seq=max(0, int(turn_seq or 0)),
            objective=(
                "Write one brief recovery only if the user gave no reaction. Own Eris's delivery, "
                "leave space, and never guilt-trip or demand a response."
            ),
            role="exposure_recovery",
            tone=_compact(proposal.get("recovery_style", "soft_embarrassed"), 48).lower() or "soft_embarrassed",
            confidence=_float(proposal.get("confidence", 0.0), 0.0, minimum=0.0, maximum=1.0),
            created_at=now,
            expires_at=now + 12.0,
            idempotency_key=f"{turn_id}:social_exposure:0",
            expected_responses=tuple(_compact(v, 96) for v in _sequence(proposal.get("expected_responses"))[:6] if _compact(v, 96)),
            silence_hypotheses=tuple(_compact(v, 120) for v in _sequence(proposal.get("silence_hypotheses"))[:4] if _compact(v, 120)),
            exposure_kind=_compact(proposal.get("kind", "none"), 64).lower() or "none",
            recovery_style=_compact(proposal.get("recovery_style", "none"), 64).lower() or "none",
            timing_class=window,
            updated_at=now,
        )

    def _candidate_for(self, ticket: ContinuationTicket) -> SocialSpeechCandidate:
        if ticket.lane == "afterbeat":
            topic = (
                f"Reserved afterbeat ({ticket.role}): {ticket.objective}. "
                f"The previous public line was: {ticket.source_text!r}. "
                "Add one new semantic beat, never repeat or explain the pause, and do not ask a question."
            )
            kind = "afterbeat"
            speech_act = f"afterbeat_{ticket.role}"
            urgency = 1.0
            relevance = 0.99
        else:
            expected = ", ".join(ticket.expected_responses) or "a laugh, denial, freeze, or counter-tease"
            hypotheses = ", ".join(ticket.silence_hypotheses) or "the user may be thinking or preparing to speak"
            topic = (
                f"Social-exposure recovery after no observed reaction. Previous line: {ticket.source_text!r}. "
                f"Exposure kind: {ticket.exposure_kind}; expected reactions: {expected}; humble silence hypotheses: {hypotheses}. "
                f"Recovery style: {ticket.recovery_style}. Write one short face-saving line, own Eris's surprise, "
                "do not accuse the user of freezing, and do not create emotional obligation."
            )
            kind = "social_exposure_recovery"
            speech_act = "exposure_recovery"
            urgency = 0.96
            relevance = 0.94
        return SocialSpeechCandidate(
            decision="candidate",
            kind=kind,
            topic=_compact(topic, 1200),
            speech_act=speech_act,
            anchor_type="conversation",
            anchor_id=ticket.ticket_id,
            evidence_refs=(ticket.source_turn_id,) if ticket.source_turn_id else (),
            requires_grounding=False,
            confidence=max(0.55, ticket.confidence),
            relevance=relevance,
            urgency=urgency,
            tone=ticket.tone,
            reason=f"claimed:{ticket.lane}:{ticket.claim_token}",
            source="social_continuation_runtime",
            continuation_lane=ticket.lane,
            claim_token=ticket.claim_token,
            idempotency_key=ticket.idempotency_key,
        )

    def _repair_after_restart_locked(self, now: float) -> None:
        tickets = list(self._state.tickets)
        changed = False
        for index, ticket in enumerate(tickets):
            if not ticket.active:
                continue
            if now >= ticket.expires_at:
                tickets[index] = replace(ticket, status="EXPIRED", resolved_reason="restart_after_expiry", updated_at=now)
                self._append_outcome_locked(tickets[index], now)
                changed = True
            elif ticket.status == "CLAIMED":
                # In the durable multi-worker backend another live process may
                # own this lease. Only reclaim an expired lease; construction of
                # a second worker is not, by itself, proof of a crash.
                if self._atomic_store is not None and ticket.claim_until > now:
                    continue
                waiting = "WAITING_PAUSE" if ticket.lane == "afterbeat" else "WAITING_REACTION"
                tickets[index] = replace(
                    ticket,
                    status=waiting,
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    due_at=max(now + 0.15, ticket.due_at),
                    version=ticket.version + 1,
                    resolved_reason="claim_recovered_after_restart",
                    updated_at=now,
                )
                changed = True
        if changed:
            self._state = replace(self._state, version=self._state.version + 1, tickets=tuple(tickets), updated_at=now)
            self._persist_locked()

    def _expire_and_reap_claims_locked(self, now: float) -> None:
        tickets = list(self._state.tickets)
        changed = False
        for index, ticket in enumerate(tickets):
            if not ticket.active:
                continue
            if now >= ticket.expires_at:
                tickets[index] = replace(
                    ticket,
                    status="EXPIRED",
                    resolved_reason="deadline_exceeded",
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    version=ticket.version + 1,
                    updated_at=now,
                )
                self._append_outcome_locked(tickets[index], now)
                self._metric_locked("tickets_expired", 1)
                changed = True
                continue
            if ticket.status == "CLAIMED" and ticket.claim_until > 0.0 and now >= ticket.claim_until:
                waiting = "WAITING_PAUSE" if ticket.lane == "afterbeat" else "WAITING_REACTION"
                tickets[index] = replace(
                    ticket,
                    status=waiting,
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    due_at=now,
                    version=ticket.version + 1,
                    resolved_reason="lease_expired",
                    updated_at=now,
                )
                self._metric_locked("leases_expired", 1)
                changed = True
        if changed:
            self._state = replace(self._state, version=self._state.version + 1, tickets=tuple(tickets), updated_at=now)
            self._persist_locked()
            self._arm_timer_locked()

    def _cancel_active_locked(self, reason: str, now: float) -> int:
        tickets = list(self._state.tickets)
        count = 0
        for index, ticket in enumerate(tickets):
            if not ticket.active:
                continue
            updated = replace(
                ticket,
                status="CANCELLED",
                resolved_reason=_compact(reason, 120),
                claim_owner="",
                claim_until=0.0,
                claim_token="",
                version=ticket.version + 1,
                updated_at=now,
            )
            tickets[index] = updated
            self._append_outcome_locked(updated, now)
            count += 1
        if count:
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                tickets=tuple(tickets),
                updated_at=now,
            )
            self._metric_locked("tickets_cancelled", count)
        return count

    def _append_outcome_locked(self, ticket: ContinuationTicket, now: float) -> None:
        outcome = {
            "ticket_id": ticket.ticket_id,
            "lane": ticket.lane,
            "source_turn_id": ticket.source_turn_id,
            "status": ticket.status,
            "actual_response": ticket.actual_response,
            "reason": ticket.resolved_reason,
            "spoken_text": ticket.spoken_text,
            "resolved_at": now,
        }
        outcomes = list(self._state.outcomes)
        outcomes.append(outcome)
        self._state = replace(self._state, outcomes=tuple(outcomes[-40:]))
        callback = self._outcome_callback
        if callable(callback):
            try:
                callback(outcome=outcome, now=now)
            except TypeError:
                try:
                    callback(outcome)
                except Exception as exc:
                    self._log("debug", "[social continuation] outcome callback failed: %s", exc)
            except Exception as exc:
                self._log("debug", "[social continuation] outcome callback failed: %s", exc)

    def _metric_locked(self, name: str, delta: int) -> None:
        metrics = dict(self._state.metrics)
        metrics[name] = max(0, int(metrics.get(name, 0) or 0) + int(delta))
        self._state = replace(self._state, metrics=metrics)

    def _arm_timer_locked(self) -> None:
        self._cancel_timer_locked()
        if self._wake_callback is None:
            return
        now = self._clock()
        due_times = [
            ticket.due_at
            for ticket in self._state.tickets
            if ticket.status in {"WAITING_PAUSE", "WAITING_REACTION"}
            and ticket.due_at > 0.0
            and ticket.expires_at > now
        ]
        claim_times = [
            ticket.claim_until
            for ticket in self._state.tickets
            if ticket.status == "CLAIMED" and ticket.claim_until > now
        ]
        targets = due_times + claim_times
        if not targets:
            return
        delay = max(0.05, min(targets) - now)

        def wake() -> None:
            try:
                self._wake_callback("social_continuation_due")
            except TypeError:
                self._wake_callback(reason="social_continuation_due")
            except Exception as exc:
                self._log("debug", "[social continuation] wake failed: %s", exc)

        try:
            timer = self._timer_factory(delay, wake)
            timer.daemon = True
            timer.start()
            self._timer = timer
        except Exception as exc:
            self._timer = None
            self._log("debug", "[social continuation] timer unavailable: %s", exc)

    def _cancel_timer_locked(self) -> None:
        timer = self._timer
        self._timer = None
        cancel = getattr(timer, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass

    @contextmanager
    def _state_transaction_locked(self):
        """Reload and mutate one durable snapshot under a process-safe DB lock."""
        if self._atomic_store is None or self._atomic_tx is not None:
            yield
            return
        with self._atomic_store.transaction(self._atomic_key, self._state.to_dict()) as tx:
            self._state = SocialContinuationState.from_mapping(tx.payload)
            self._atomic_tx = tx
            try:
                yield
            finally:
                self._atomic_tx = None

    def _persist_locked(self) -> None:
        payload = self._state.to_dict()
        if self._atomic_tx is not None:
            self._atomic_tx.stage(payload)
        elif self._atomic_store is not None:
            try:
                self._atomic_store.replace(self._atomic_key, payload)
            except Exception as exc:
                self._log("debug", "[atomic state] persistence failed: %s", exc)
        if self._persist is None:
            return
        try:
            self._persist(payload)
        except Exception as exc:
            self._log("debug", "[social continuation] persistence failed: %s", exc)

    def _emit(self, event: str, **fields: Any) -> None:
        self._log("info", "[social continuation] %s %s", event, fields)
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            tags = {"lane": str(fields.get("lane", "")), "event": str(event)}
            GLOBAL_OBSERVABILITY.log(
                f"social_continuation.{event}",
                tags=tags,
                fields=dict(fields),
                status="ok",
            )
            GLOBAL_OBSERVABILITY.increment(
                "eris_social_continuation_events_total", tags=tags, fields=dict(fields)
            )
            GLOBAL_OBSERVABILITY.gauge(
                "eris_social_continuation_pending",
                float(sum(1 for ticket in self._state.tickets if ticket.active)),
                tags={"lane": str(fields.get("lane", "all"))},
            )
        except Exception:
            pass

    def _log(self, level: str, message: str, *args: Any) -> None:
        method = getattr(self._logger, level, None) if self._logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = [
    "CONTINUATION_STATE_SCHEMA",
    "ContinuationTicket",
    "SocialContinuationRuntime",
    "SocialContinuationState",
]
