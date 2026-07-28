# -*- coding: utf-8 -*-
"""Post-turn observer. Không có pre-turn social gate."""

from __future__ import annotations

import os
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Sequence

from .contracts import CognitiveObservation, StateEvent


@dataclass(slots=True)
class ObservationTicket:
    ticket_id: str
    turn_id: str
    turn_seq: int
    user_text: str
    assistant_text: str
    event_kind: str
    submitted_at: float
    future: Future[CognitiveObservation]
    user_meta: MutableMapping[str, Any] | None = None
    assistant_meta: MutableMapping[str, Any] | None = None
    _claimed: bool = False
    _timer: threading.Timer | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


class PostTurnObserver:
    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None, workers: int = 2) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, int(workers or 2))),
            thread_name_prefix="eris-post-turn-observer",
        )
        self._tickets: dict[str, ObservationTicket] = {}
        self._lock = threading.RLock()
        try:
            self.deadline_seconds = max(1.0, min(60.0, float(os.getenv("ERIS_POST_OBSERVER_DEADLINE_SEC", "30.0") or 30.0)))
        except (TypeError, ValueError):
            self.deadline_seconds = 30.0

    def submit(
        self,
        *,
        turn_id: str,
        turn_seq: int,
        user_text: str,
        assistant_text: str,
        event_kind: str = "chat",
        recent_history: Sequence[Mapping[str, Any] | str] = (),
        mechanical_outcomes: Sequence[Mapping[str, Any]] = (),
        state_summary: Mapping[str, Any] | None = None,
        user_meta: MutableMapping[str, Any] | None = None,
        assistant_meta: MutableMapping[str, Any] | None = None,
    ) -> ObservationTicket:
        ticket_id = f"observe-{uuid.uuid4().hex[:12]}"
        submitted_at = time.time()
        cancel_scope = f"background:post_observer:{turn_id}"

        def observe_when_idle() -> CognitiveObservation:
            # PDF annotation, pages 5 and 7-9: observer work is never allowed on
            # the user-facing critical path. It waits for chat to leave the
            # broker, then enters a short optional/deadline-aware lane.
            from runtime.inference_broker import (
                GLOBAL_INFERENCE_BROKER,
                InferenceRejected,
                inference_context,
            )

            remaining = max(0.0, submitted_at + self.deadline_seconds - time.time())
            if not GLOBAL_INFERENCE_BROKER.wait_for_user_idle(remaining):
                raise InferenceRejected("post_observer_user_turn_deadline")
            with inference_context(
                "post_observer",
                optional=True,
                deadline_at=submitted_at + self.deadline_seconds,
                cancel_scope=cancel_scope,
                coalesce_key=f"post_observer:{turn_id}",
                idempotency_key=f"post_observer:{turn_id}",
                metadata={"turn_seq": turn_seq, "event_kind": event_kind},
            ):
                return self.router.observe_completed_turn(
                    turn_id=turn_id,
                    turn_seq=turn_seq,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    recent_history=recent_history,
                    mechanical_outcomes=mechanical_outcomes,
                    state_summary=state_summary,
                    event_kind=event_kind,
                )

        future = self.executor.submit(observe_when_idle)
        ticket = ObservationTicket(
            ticket_id=ticket_id,
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=assistant_text,
            event_kind=str(event_kind or "chat"),
            submitted_at=submitted_at,
            future=future,
            user_meta=user_meta,
            assistant_meta=assistant_meta,
        )
        with self._lock:
            self._tickets[ticket_id] = ticket
        timer = threading.Timer(self.deadline_seconds, self._expire, args=(ticket,))
        timer.daemon = True
        ticket._timer = timer
        timer.start()
        future.add_done_callback(lambda done: self._complete(ticket, done))
        return ticket

    def _complete(self, ticket: ObservationTicket, future: Future[CognitiveObservation]) -> None:
        if not ticket.claim():
            return
        with self._lock:
            self._tickets.pop(ticket.ticket_id, None)
        if ticket._timer is not None:
            ticket._timer.cancel()
        try:
            observation = future.result()
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[post observer] failed turn=%s: %s", ticket.turn_seq, exc)
            return
        payload = observation.to_dict()
        if ticket.user_meta is not None:
            ticket.user_meta["cognitive_observation"] = payload
            ticket.user_meta["cognitive_observation_pending"] = False
        if ticket.assistant_meta is not None:
            ticket.assistant_meta["cognitive_observation_source"] = observation.source
        self.reducer.submit(
            StateEvent.from_observation(
                observation,
                base_version=self.reducer.snapshot().version,
            )
        )
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            GLOBAL_OBSERVABILITY.increment(
                "observer_completed_total", tags={"event_kind": ticket.event_kind}
            )
            GLOBAL_OBSERVABILITY.observe(
                "observer_latency_ms",
                max(0.0, (time.time() - ticket.submitted_at) * 1000.0),
                tags={"event_kind": ticket.event_kind},
            )
        except Exception as exc:
            self._log("debug", "post-observer metric emission failed: %s", exc)
        self._log(
            "info",
            "[post observer] turn=%s act=%s meaning=%s conf=%.2f repair=%s traits=%s frame=%s strategy=%s source=%s latency=%.0fms",
            observation.turn_seq,
            observation.user_act,
            observation.relationship_meaning,
            observation.confidence,
            observation.repair_needed,
            len(observation.trait_signals),
            observation.self_interpretation.frame,
            observation.consequence.strategy or "none",
            observation.source,
            observation.latency_ms,
        )

    def _expire(self, ticket: ObservationTicket) -> None:
        if not ticket.claim():
            return
        with self._lock:
            self._tickets.pop(ticket.ticket_id, None)
        try:
            from runtime.inference_broker import GLOBAL_INFERENCE_BROKER
            GLOBAL_INFERENCE_BROKER.cancel_scope(f"background:post_observer:{ticket.turn_id}")
        except Exception as exc:
            self._log("debug", "post-observer broker cancellation failed: %s", exc)
        # PDF annotation, pages 5 and 18-19: distinguish work dropped before
        # provider start from a late in-flight discard.  The acceptance target
        # is near-zero remote work for the former, not a vague aggregate count.
        was_running = False
        cancelled_before_start = False
        try:
            was_running = ticket.future.running()
            cancelled_before_start = bool(ticket.future.cancel())
        except Exception as exc:
            self._log("debug", "post-observer future cancellation failed: %s", exc)
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            stage = "before_start" if cancelled_before_start and not was_running else "inflight_or_started"
            GLOBAL_OBSERVABILITY.increment(
                "observer_discard_total",
                tags={"stage": stage, "event_kind": ticket.event_kind},
            )
        except Exception as exc:
            self._log("debug", "post-observer discard metric failed: %s", exc)
        if ticket.user_meta is not None:
            ticket.user_meta["cognitive_observation_pending"] = False
            ticket.user_meta["cognitive_observation_timeout"] = True
        if ticket.assistant_meta is not None:
            ticket.assistant_meta["cognitive_observation_source"] = "timeout_discarded"
        self._log(
            "warning",
            "[post observer] deadline turn=%s after %.1fs; result discarded",
            ticket.turn_seq,
            self.deadline_seconds,
        )

    def shutdown(self) -> None:
        with self._lock:
            tickets = tuple(self._tickets.values())
            self._tickets.clear()
        for ticket in tickets:
            if ticket._timer is not None:
                ticket._timer.cancel()
            try:
                ticket.future.cancel()
            except Exception as exc:
                self._log("debug", "post-observer ticket cancellation failed: %s", exc)
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            self._log("debug", "post-observer executor shutdown failed: %s", exc)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception as exc:
            _LOG.debug("post-observer logger failed: %s", exc, exc_info=exc)


__all__ = ["ObservationTicket", "PostTurnObserver"]
