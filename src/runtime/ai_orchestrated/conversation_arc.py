# -*- coding: utf-8 -*-
"""Long-horizon public conversation arcs for ERIS.

A normal public turn may intentionally leave one or more *semantic beats* for
later.  This module stores only the communicative goal and beat objectives.  It
never stores or emits prewritten dialogue; the autonomous Surface Worker still
owns final wording at the moment each beat is spoken.

That distinction matters.  A delayed canned sentence is a notification queue
wearing lipstick.  A conversation arc can adapt to the current public history,
yield when the user speaks, and preserve a small dramatic intention across
separate autonomous turns.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .atomic_state import SQLiteAtomicStateStore, SQLiteStateTransaction
from .social_candidate import SocialSpeechCandidate
from .affordance import ExecutiveAffordance
from cortex.subject.expression_commitment import commitment_payload


ARC_SCHEMA = "eris.conversation_arc.v1"
_ALLOWED_ROLES = {
    "callback",
    "reveal",
    "punchline",
    "escalate",
    "soften",
    "reconsider",
    "return_to_goal",
    "afterthought",
}
_ALLOWED_TONES = {
    "neutral",
    "soft_warm",
    "warm_embarrassed",
    "dry_tease",
    "playful",
    "curious",
    "focused",
    "cold_precision",
    "annoyed_soft",
    "sad_distant",
    "repair",
    "surprised",
}
_BLOCKED_ASSISTANT_ACTS = {"silence", "question", "repair", "action_report"}


def _compact(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed != parsed:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _enabled() -> bool:
    raw = str(os.getenv("ERIS_CONVERSATION_ARCS_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class ConversationBeat:
    objective: str
    role: str = "afterthought"
    delay_seconds: float = 0.65
    tone: str = "neutral"
    max_sentences: int = 1
    condition: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ConversationBeat | None":
        data = payload or {}
        objective = _compact(data.get("objective", ""), 360)
        if not objective:
            return None
        role = _compact(data.get("role", "afterthought"), 40).lower() or "afterthought"
        if role not in _ALLOWED_ROLES:
            role = "afterthought"
        tone = _compact(data.get("tone", "neutral"), 48).lower() or "neutral"
        if tone not in _ALLOWED_TONES:
            tone = "neutral"
        default_delay = 8.0 if "condition" in data and "delay_seconds" not in data else 0.65
        return cls(
            objective=objective,
            role=role,
            delay_seconds=_float(data.get("delay_seconds", default_delay), default_delay, minimum=0.25, maximum=30.0),
            tone=tone,
            max_sentences=_int(data.get("max_sentences", 1), 1, minimum=1, maximum=2),
            condition=_compact(data.get("condition", ""), 220),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConversationArc:
    arc_id: str
    goal: str
    thread_key: str
    source_turn_id: str
    source_text: str
    source_turn_seq: int
    created_at: float
    anchor_at: float
    expires_at: float
    beats: tuple[ConversationBeat, ...] = ()
    next_beat_index: int = 0
    user_reply_policy: str = "replan"
    status: str = "active"
    last_spoken_text: str = ""
    last_spoken_at: float = 0.0
    interrupted_reason: str = ""
    version: int = 1
    claim_owner: str = ""
    claim_until: float = 0.0
    claim_token: str = ""

    @property
    def active(self) -> bool:
        return self.status == "active" and self.next_beat_index < len(self.beats)

    @property
    def current_beat(self) -> ConversationBeat | None:
        if not self.active:
            return None
        return self.beats[self.next_beat_index]

    def due_at(self) -> float:
        beat = self.current_beat
        return self.anchor_at + beat.delay_seconds if beat is not None else self.expires_at

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ConversationArc | None":
        data = payload or {}
        beats = tuple(
            beat
            for beat in (
                ConversationBeat.from_mapping(item)
                for item in _sequence(data.get("beats"))[:3]
                if isinstance(item, Mapping)
            )
            if beat is not None
        )
        goal = _compact(data.get("goal", ""), 420)
        arc_id = _compact(data.get("arc_id", ""), 100)
        if not goal or not arc_id or not beats:
            return None
        created_at = _float(data.get("created_at", time.time()), time.time(), minimum=0.0, maximum=10**12)
        expires_at = _float(data.get("expires_at", created_at + 180.0), created_at + 180.0, minimum=created_at, maximum=created_at + 3600.0)
        policy = _compact(data.get("user_reply_policy", "replan"), 24).lower() or "replan"
        if policy not in {"cancel", "replan"}:
            policy = "replan"
        status = _compact(data.get("status", "active"), 24).lower() or "active"
        if status not in {"active", "completed", "cancelled", "interrupted", "expired"}:
            status = "cancelled"
        return cls(
            arc_id=arc_id,
            goal=goal,
            thread_key=_compact(data.get("thread_key", arc_id), 120) or arc_id,
            source_turn_id=_compact(data.get("source_turn_id", ""), 120),
            source_text=_compact(data.get("source_text", ""), 420),
            source_turn_seq=max(0, _int(data.get("source_turn_seq", 0), 0, minimum=0, maximum=10**9)),
            created_at=created_at,
            anchor_at=_float(data.get("anchor_at", created_at), created_at, minimum=0.0, maximum=10**12),
            expires_at=expires_at,
            beats=beats,
            next_beat_index=_int(data.get("next_beat_index", 0), 0, minimum=0, maximum=len(beats)),
            user_reply_policy=policy,
            status=status,
            last_spoken_text=_compact(data.get("last_spoken_text", ""), 420),
            last_spoken_at=_float(data.get("last_spoken_at", 0.0), 0.0, minimum=0.0, maximum=10**12),
            interrupted_reason=_compact(data.get("interrupted_reason", ""), 120),
            version=max(1, _int(data.get("version", 1), 1, minimum=1, maximum=10**9)),
            claim_owner=_compact(data.get("claim_owner", ""), 120),
            claim_until=_float(data.get("claim_until", 0.0), 0.0, minimum=0.0, maximum=10**12),
            claim_token=_compact(data.get("claim_token", ""), 180),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = ARC_SCHEMA
        payload["beats"] = [beat.to_dict() for beat in self.beats]
        payload["due_at"] = self.due_at()
        return payload


@dataclass(frozen=True, slots=True)
class ConversationArcState:
    version: int = 0
    active_arc: ConversationArc | None = None
    last_interrupted_arc: Mapping[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ConversationArcState":
        data = payload or {}
        active = ConversationArc.from_mapping(data.get("active_arc") if isinstance(data.get("active_arc"), Mapping) else {})
        interrupted = data.get("last_interrupted_arc", {})
        return cls(
            version=max(0, _int(data.get("version", 0), 0, minimum=0, maximum=10**9)),
            active_arc=active,
            last_interrupted_arc=dict(interrupted) if isinstance(interrupted, Mapping) else {},
            updated_at=_float(data.get("updated_at", 0.0), 0.0, minimum=0.0, maximum=10**12),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.conversation_arc_state.v1",
            "version": self.version,
            "active_arc": self.active_arc.to_dict() if self.active_arc else None,
            "last_interrupted_arc": dict(self.last_interrupted_arc),
            "updated_at": self.updated_at,
        }


class ConversationArcRuntime:
    """Owns one short public arc and exposes its next beat to autonomous runtime."""

    def __init__(
        self,
        *,
        initial_state: Mapping[str, Any] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        wake_callback: Callable[[str], None] | None = None,
        logger: Any | None = None,
        clock: Callable[[], float] | None = None,
        timer_factory: Callable[..., Any] | None = None,
        atomic_store: SQLiteAtomicStateStore | None = None,
        atomic_key: str = "eris.conversation_arc",
    ) -> None:
        self._clock = clock or time.time
        self._persist = persist
        self._atomic_store = atomic_store
        self._atomic_key = str(atomic_key or "eris.conversation_arc")
        self._atomic_tx: SQLiteStateTransaction | None = None
        self._wake_callback = wake_callback
        self._logger = logger
        self._lock = threading.RLock()
        self._state = ConversationArcState.from_mapping(initial_state)
        if self._atomic_store is not None:
            record = self._atomic_store.ensure(self._atomic_key, self._state.to_dict())
            self._state = ConversationArcState.from_mapping(record.payload)
        self._timer_factory = timer_factory or threading.Timer
        self._timer: Any | None = None
        with self._lock, self._state_transaction_locked():
            now = self._clock()
            self._expire_if_needed(now)
            self._repair_claim_after_restart_locked(now)
            self._arm_timer_locked()

    def schedule_from_model(
        self,
        payload: Mapping[str, Any] | None,
        *,
        source_turn_id: str,
        source_text: str,
        source_turn_seq: int,
        semantic_frame: Mapping[str, Any] | None = None,
        assistant_act: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> bool:
        """Commit a model-proposed semantic arc after the first public line succeeds."""

        if not _enabled() or not isinstance(payload, Mapping):
            return False
        data = payload
        decision = _compact(data.get("decision", "none"), 24).lower() or "none"
        if decision != "schedule":
            return False
        frame = semantic_frame or {}
        act = assistant_act or {}
        if _compact(frame.get("tool_intent", "none"), 60).lower() not in {"", "none"}:
            return False
        if _compact(frame.get("boundary_action", "none"), 60).lower() not in {"", "none"}:
            return False
        if _compact(act.get("kind", "other"), 40).lower() in _BLOCKED_ASSISTANT_ACTS:
            return False

        goal = _compact(data.get("goal", ""), 420)
        beats = tuple(
            beat
            for beat in (
                ConversationBeat.from_mapping(item)
                for item in _sequence(data.get("beats"))[:3]
                if isinstance(item, Mapping)
            )
            if beat is not None
        )
        if not goal or not beats:
            return False
        current = float(now if now is not None else self._clock())
        expiry = _float(data.get("expires_after_seconds", 180.0), 180.0, minimum=15.0, maximum=600.0)
        policy = _compact(data.get("user_reply_policy", "replan"), 24).lower() or "replan"
        if policy not in {"cancel", "replan"}:
            policy = "replan"
        arc_id = _compact(data.get("arc_id", ""), 100) or f"arc:{int(current * 1000)}:{max(0, int(source_turn_seq))}"
        thread_key = _compact(data.get("thread_key", ""), 120) or arc_id
        arc = ConversationArc(
            arc_id=arc_id,
            goal=goal,
            thread_key=thread_key,
            source_turn_id=_compact(source_turn_id, 120),
            source_text=_compact(source_text, 420),
            source_turn_seq=max(0, int(source_turn_seq or 0)),
            created_at=current,
            anchor_at=current,
            expires_at=current + expiry,
            beats=beats,
            user_reply_policy=policy,
        )
        with self._lock, self._state_transaction_locked():
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                active_arc=arc,
                updated_at=current,
            )
            self._persist_locked()
            self._arm_timer_locked()
        self._log(
            "info",
            "[conversation arc] scheduled id=%s beats=%s goal=%s",
            arc.arc_id,
            len(arc.beats),
            arc.goal,
        )
        self._emit("scheduled", arc_id=arc.arc_id, beats=len(arc.beats))
        return True

    def observe_user_turn(
        self,
        *,
        user_text: str,
        user_turn_seq: int = 0,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Yield the microphone and return context so the main writer can adapt."""

        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active:
                return {}
            beat = arc.current_beat
            context = {
                "schema": "eris.conversation_arc_interruption.v1",
                "arc_id": arc.arc_id,
                "goal": arc.goal,
                "thread_key": arc.thread_key,
                "source_text": arc.source_text,
                "last_spoken_text": arc.last_spoken_text,
                "pending_beat": beat.to_dict() if beat else None,
                "next_beat_index": arc.next_beat_index,
                "remaining_beats": max(0, len(arc.beats) - arc.next_beat_index),
                "user_reply_policy": arc.user_reply_policy,
                "instruction": (
                    "The user spoke before the autonomous beat. Respond to the user first. "
                    "Preserve, revise, or drop the dramatic goal naturally; never force the old beat."
                ),
            }
            interrupted = replace(
                arc,
                status="interrupted" if arc.user_reply_policy == "replan" else "cancelled",
                interrupted_reason="user_turn_before_next_beat",
            )
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                active_arc=None,
                last_interrupted_arc={
                    **context,
                    "user_text": _compact(user_text, 360),
                    "user_turn_seq": max(0, int(user_turn_seq or 0)),
                    "interrupted_at": current,
                    "status": interrupted.status,
                },
                updated_at=current,
            )
            self._cancel_timer_locked()
            self._persist_locked()
        self._log("info", "[conversation arc] yielded id=%s reason=user_turn", arc.arc_id)
        self._emit("yielded", arc_id=arc.arc_id, reason="user_turn")
        return context

    def cancel_active(self, *, reason: str = "cancelled", now: float | None = None) -> bool:
        """Cancel a pending arc when its setup was interrupted or invalidated."""

        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active:
                return False
            cancelled = replace(
                arc,
                status="cancelled",
                interrupted_reason=_compact(reason, 120),
            )
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                active_arc=None,
                last_interrupted_arc={**cancelled.to_dict(), "cancelled_at": current},
                updated_at=current,
            )
            self._cancel_timer_locked()
            self._persist_locked()
        self._log("info", "[conversation arc] cancelled id=%s reason=%s", arc.arc_id, reason)
        self._emit("cancelled", arc_id=arc.arc_id, reason=reason)
        return True

    def notify_audio_finished(self, timestamp: float | None = None) -> None:
        """Start the rhetorical pause after audio, not after text commit."""

        current = float(timestamp if timestamp is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active:
                return
            # Only move the anchor forward.  Late duplicate playback events cannot
            # make a beat fire earlier, an achievement timers rarely volunteer.
            if current > arc.anchor_at:
                arc = replace(arc, anchor_at=current)
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    active_arc=arc,
                    updated_at=current,
                )
                self._persist_locked()
            self._arm_timer_locked()

    def _candidate_for_arc(self, arc: ConversationArc) -> SocialSpeechCandidate | None:
        beat = arc.current_beat
        if beat is None:
            return None
        condition = f" Condition: {beat.condition}." if beat.condition else ""
        topic = (
            f"Arc beat {beat.role}: {beat.objective}.{condition} "
            f"Long-horizon goal: {arc.goal}. "
            "Deliver one new self-contained callback after a real pause; do not repeat, "
            "explain timing, mention the arc, or ask the user to wait."
        )
        return SocialSpeechCandidate(
            decision="candidate", kind="conversation_arc", topic=_compact(topic, 900),
            speech_act=f"arc_{beat.role}", anchor_type="conversation", anchor_id=arc.arc_id,
            evidence_refs=(), requires_grounding=False, confidence=0.94, relevance=0.96, urgency=1.0,
            tone=beat.tone, reason=f"reserved_arc_beat:{arc.next_beat_index + 1}/{len(arc.beats)}",
            source="conversation_arc_runtime", continuation_lane="conversation_arc",
            claim_token=arc.claim_token, idempotency_key=f"{arc.arc_id}:beat:{arc.next_beat_index}",
        )

    def peek_due(
        self, *, now: float | None = None, interaction_busy: bool = False
    ) -> ExecutiveAffordance | None:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active or interaction_busy:
                return None
            if arc.claim_owner and arc.claim_until > current:
                self._arm_timer_locked()
                return None
            if arc.current_beat is None or current < arc.due_at():
                self._arm_timer_locked()
                return None
            candidate = self._candidate_for_arc(arc)
            if candidate is None:
                return None
            # V66: một beat đã được arc owner giữ lại là continuation intent
            # của chính Eris. Nó không cần user im đủ lâu để "được phép" tồn tại.
            commitment = commitment_payload(
                origin="conversation_arc",
                source_id=f"{arc.arc_id}:beat:{arc.next_beat_index}",
                semantic_target=candidate.topic,
                motive=candidate.speech_act,
                pressure=max(candidate.urgency, candidate.relevance),
                freshness=candidate.confidence,
                persistence=0.96,
            )
            return ExecutiveAffordance(
                affordance_id=f"conversation_arc:{arc.arc_id}:beat:{arc.next_beat_index}:v{arc.version}",
                owner="conversation_arc", revision=arc.version, candidate=candidate,
                claim_required=True, expires_at=arc.expires_at, claim_key=arc.arc_id,
                metadata={
                    "beat_index": arc.next_beat_index,
                    "expression_commitment": commitment,
                },
            )

    def claim_affordance(
        self, affordance: ExecutiveAffordance, *, worker_id: str,
        now: float | None = None, lease_ms: int = 12000
    ) -> SocialSpeechCandidate | None:
        current = float(now if now is not None else self._clock())
        owner = _compact(worker_id or "anonymous", 100) or "anonymous"
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active or arc.arc_id != str(affordance.claim_key or ""):
                return None
            if arc.version != int(affordance.revision) or (arc.claim_owner and arc.claim_until > current):
                return None
            if arc.current_beat is None or current < arc.due_at():
                return None
            next_version = arc.version + 1
            token = f"{arc.arc_id}:beat:{arc.next_beat_index}:v{next_version}:{owner}"
            claimed = replace(
                arc, version=next_version, claim_owner=owner,
                claim_until=current + max(0.5, min(45.0, int(lease_ms) / 1000.0)),
                claim_token=token,
            )
            self._state = replace(
                self._state, version=self._state.version + 1, active_arc=claimed, updated_at=current
            )
            self._persist_locked()
            self._arm_timer_locked()
            self._emit("claimed", arc_id=claimed.arc_id, beat_index=claimed.next_beat_index, worker_id=owner)
            return self._candidate_for_arc(claimed)

    def claim_due(
        self, *, worker_id: str, now: float | None = None,
        interaction_busy: bool = False, lease_ms: int = 12000
    ) -> SocialSpeechCandidate | None:
        preview = self.peek_due(now=now, interaction_busy=interaction_busy)
        if preview is None:
            return None
        return self.claim_affordance(preview, worker_id=worker_id, now=now, lease_ms=lease_ms)

    def due_candidate(
        self,
        *,
        now: float | None = None,
        interaction_busy: bool = False,
    ) -> SocialSpeechCandidate | None:
        """Compatibility wrapper. New callers should supply a real worker ID."""

        return self.claim_due(
            worker_id="legacy_due_candidate",
            now=now,
            interaction_busy=interaction_busy,
        )

    def note_spoken(self, plan: Any, text: str, *, now: float | None = None) -> bool:
        semantics = getattr(plan, "semantics", None)
        if str(getattr(semantics, "turn_kind", "") or "").strip().lower() != "arc_continuation":
            return False
        current = float(now if now is not None else self._clock())
        claim_token = str(getattr(plan, "continuation_claim_token", "") or "").strip()
        ticket_id = str(getattr(plan, "continuation_ticket_id", "") or getattr(semantics, "subject_key", "") or "").strip()
        with self._lock, self._state_transaction_locked():
            arc = self._state.active_arc
            if arc is None or not arc.active:
                return False
            if ticket_id and ticket_id != arc.arc_id:
                return False
            if claim_token and claim_token != arc.claim_token:
                return False
            next_index = arc.next_beat_index + 1
            done = next_index >= len(arc.beats)
            updated = replace(
                arc,
                next_beat_index=next_index,
                anchor_at=current,
                last_spoken_text=_compact(text, 420),
                last_spoken_at=current,
                status="completed" if done else "active",
                version=arc.version + 1,
                claim_owner="",
                claim_until=0.0,
                claim_token="",
            )
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                active_arc=None if done else updated,
                updated_at=current,
            )
            if done:
                self._cancel_timer_locked()
            else:
                self._arm_timer_locked()
            self._persist_locked()
        self._log(
            "info",
            "[conversation arc] beat spoken id=%s index=%s/%s complete=%s",
            arc.arc_id,
            next_index,
            len(arc.beats),
            int(done),
        )
        self._emit("spoken", arc_id=arc.arc_id, beat_index=next_index, complete=done)
        return True

    def defer_current_beat(self, *, seconds: float = 4.0, reason: str = "surface_deferred") -> None:
        current = self._clock()
        with self._lock, self._state_transaction_locked():
            arc = self._state.active_arc
            if arc is None or not arc.active:
                return
            beat = arc.current_beat
            beat_delay = beat.delay_seconds if beat is not None else 0.0
            # due_at = anchor_at + beat.delay_seconds. Set anchor so the next
            # attempt occurs roughly ``seconds`` from now, not seconds + the
            # original dramatic pause all over again.
            retry_at = current + max(0.5, float(seconds))
            arc = replace(
                arc,
                anchor_at=max(arc.anchor_at, retry_at - beat_delay),
                interrupted_reason=_compact(reason, 120),
                version=arc.version + 1,
                claim_owner="",
                claim_until=0.0,
                claim_token="",
            )
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                active_arc=arc,
                updated_at=current,
            )
            self._persist_locked()
            self._arm_timer_locked()

    def has_pending(self, *, now: float | None = None) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            return bool(self._state.active_arc and self._state.active_arc.active)

    def is_due(self, *, now: float | None = None, interaction_busy: bool = False) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            arc = self._state.active_arc
            claim_free = bool(arc and (not arc.claim_owner or arc.claim_until <= current))
            return bool(arc and arc.active and claim_free and not interaction_busy and current >= arc.due_at())

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_if_needed(current)
            payload = self._state.to_dict()
            arc = self._state.active_arc
            payload["pending"] = bool(arc and arc.active)
            payload["reserved_continuation"] = bool(arc and arc.active)
            payload["claimed"] = bool(arc and arc.claim_owner and arc.claim_until > current)
            payload["due"] = bool(
                arc and arc.active and current >= arc.due_at()
                and (not arc.claim_owner or arc.claim_until <= current)
            )
            payload["seconds_until_due"] = max(0.0, arc.due_at() - current) if arc and arc.active else 0.0
            return payload

    def shutdown(self) -> None:
        with self._lock, self._state_transaction_locked():
            self._cancel_timer_locked()

    def _repair_claim_after_restart_locked(self, now: float) -> None:
        arc = self._state.active_arc
        if arc is None or not arc.active or not arc.claim_owner:
            return
        if self._atomic_store is not None and arc.claim_until > now:
            return
        repaired = replace(
            arc,
            claim_owner="",
            claim_until=0.0,
            claim_token="",
            version=arc.version + 1,
            anchor_at=max(arc.anchor_at, now - (arc.current_beat.delay_seconds if arc.current_beat else 0.0)),
            interrupted_reason="claim_recovered_after_restart",
        )
        self._state = replace(
            self._state,
            version=self._state.version + 1,
            active_arc=repaired,
            updated_at=now,
        )
        self._persist_locked()

    def _expire_if_needed(self, now: float) -> None:
        arc = self._state.active_arc
        if arc is None or not arc.active or now < arc.expires_at:
            return
        expired = replace(arc, status="expired", interrupted_reason="arc_expired")
        self._state = replace(
            self._state,
            version=self._state.version + 1,
            active_arc=None,
            last_interrupted_arc={**expired.to_dict(), "expired_at": now},
            updated_at=now,
        )
        self._cancel_timer_locked()
        self._persist_locked()
        self._log("info", "[conversation arc] expired id=%s", arc.arc_id)

    def _arm_timer_locked(self) -> None:
        self._cancel_timer_locked()
        arc = self._state.active_arc
        if arc is None or not arc.active or self._wake_callback is None:
            return
        now = self._clock()
        target = arc.claim_until if arc.claim_owner and arc.claim_until > now else arc.due_at()
        delay = max(0.05, target - now)

        def wake() -> None:
            try:
                self._wake_callback(f"conversation_arc_due:{arc.arc_id}")
            except Exception as exc:  # wake failure must not corrupt arc state
                self._log("debug", "[conversation arc] wake failed: %s", exc)

        try:
            timer = self._timer_factory(delay, wake)
            timer.daemon = True
            timer.start()
            self._timer = timer
        except Exception as exc:
            self._timer = None
            self._log("debug", "[conversation arc] timer unavailable: %s", exc)

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
            self._state = ConversationArcState.from_mapping(tx.payload)
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
            self._log("debug", "[conversation arc] persistence failed: %s", exc)

    def _emit(self, event: str, **fields: Any) -> None:
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            tags = {"event": str(event)}
            GLOBAL_OBSERVABILITY.log(
                f"conversation_arc.{event}", tags=tags, fields=dict(fields), status="ok"
            )
            GLOBAL_OBSERVABILITY.increment(
                "eris_conversation_arc_events_total", tags=tags, fields=dict(fields)
            )
            GLOBAL_OBSERVABILITY.gauge(
                "eris_conversation_arc_pending",
                1.0 if self._state.active_arc is not None and self._state.active_arc.active else 0.0,
            )
        except Exception:
            pass

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self._logger is None:
            return
        method = getattr(self._logger, level, None)
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = [
    "ARC_SCHEMA",
    "ConversationArc",
    "ConversationArcRuntime",
    "ConversationArcState",
    "ConversationBeat",
]
