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

import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .social_initiative import SocialSpeechCandidate


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
    delay_seconds: float = 3.0
    tone: str = "neutral"
    max_sentences: int = 1

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
        return cls(
            objective=objective,
            role=role,
            delay_seconds=_float(data.get("delay_seconds", 3.0), 3.0, minimum=1.2, maximum=45.0),
            tone=tone,
            max_sentences=_int(data.get("max_sentences", 1), 1, minimum=1, maximum=2),
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
    ) -> None:
        self._clock = clock or time.time
        self._persist = persist
        self._wake_callback = wake_callback
        self._logger = logger
        self._lock = threading.RLock()
        self._state = ConversationArcState.from_mapping(initial_state)
        self._timer_factory = timer_factory or threading.Timer
        self._timer: Any | None = None
        self._expire_if_needed(self._clock())
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
        with self._lock:
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
        with self._lock:
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
        return context

    def cancel_active(self, *, reason: str = "cancelled", now: float | None = None) -> bool:
        """Cancel a pending arc when its setup was interrupted or invalidated."""

        current = float(now if now is not None else self._clock())
        with self._lock:
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
        return True

    def notify_audio_finished(self, timestamp: float | None = None) -> None:
        """Start the rhetorical pause after audio, not after text commit."""

        current = float(timestamp if timestamp is not None else self._clock())
        with self._lock:
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

    def due_candidate(
        self,
        *,
        now: float | None = None,
        interaction_busy: bool = False,
    ) -> SocialSpeechCandidate | None:
        current = float(now if now is not None else self._clock())
        with self._lock:
            self._expire_if_needed(current)
            arc = self._state.active_arc
            if arc is None or not arc.active or interaction_busy:
                return None
            beat = arc.current_beat
            if beat is None or current < arc.due_at():
                self._arm_timer_locked()
                return None
            # IntentionPlan compacts topic aggressively. Put the beat objective
            # first; recent public history already contains the actual first line.
            topic = (
                f"Arc beat {beat.role}: {beat.objective}. "
                f"Long-horizon goal: {arc.goal}. "
                "Deliver one new self-contained callback after a real pause; do not repeat, "
                "explain timing, mention the arc, or ask the user to wait."
            )
            return SocialSpeechCandidate(
                decision="candidate",
                kind="conversation_arc",
                topic=_compact(topic, 900),
                speech_act=f"arc_{beat.role}",
                anchor_type="conversation",
                anchor_id=arc.arc_id,
                evidence_refs=(),
                requires_grounding=False,
                confidence=0.94,
                relevance=0.96,
                urgency=0.84,
                tone=beat.tone,
                reason=f"scheduled_arc_beat:{arc.next_beat_index + 1}/{len(arc.beats)}",
                source="conversation_arc_runtime",
            )

    def note_spoken(self, plan: Any, text: str, *, now: float | None = None) -> bool:
        semantics = getattr(plan, "semantics", None)
        if str(getattr(semantics, "turn_kind", "") or "").strip().lower() != "arc_continuation":
            return False
        current = float(now if now is not None else self._clock())
        with self._lock:
            arc = self._state.active_arc
            if arc is None or not arc.active:
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
        return True

    def defer_current_beat(self, *, seconds: float = 4.0, reason: str = "surface_deferred") -> None:
        current = self._clock()
        with self._lock:
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
        with self._lock:
            self._expire_if_needed(current)
            return bool(self._state.active_arc and self._state.active_arc.active)

    def is_due(self, *, now: float | None = None, interaction_busy: bool = False) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock:
            self._expire_if_needed(current)
            arc = self._state.active_arc
            return bool(arc and arc.active and not interaction_busy and current >= arc.due_at())

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = float(now if now is not None else self._clock())
        with self._lock:
            self._expire_if_needed(current)
            payload = self._state.to_dict()
            arc = self._state.active_arc
            payload["pending"] = bool(arc and arc.active)
            payload["due"] = bool(arc and arc.active and current >= arc.due_at())
            payload["seconds_until_due"] = max(0.0, arc.due_at() - current) if arc and arc.active else 0.0
            return payload

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer_locked()

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
        delay = max(0.05, arc.due_at() - self._clock())

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

    def _persist_locked(self) -> None:
        if self._persist is None:
            return
        try:
            self._persist(self._state.to_dict())
        except Exception as exc:
            self._log("debug", "[conversation arc] persistence failed: %s", exc)

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
