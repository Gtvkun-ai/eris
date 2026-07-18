# -*- coding: utf-8 -*-
"""Post-turn observer. Không có pre-turn social gate."""

from __future__ import annotations

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
        future = self.executor.submit(
            self.router.observe_completed_turn,
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=assistant_text,
            recent_history=recent_history,
            mechanical_outcomes=mechanical_outcomes,
            state_summary=state_summary,
            event_kind=event_kind,
        )
        ticket = ObservationTicket(
            ticket_id=ticket_id,
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=assistant_text,
            event_kind=str(event_kind or "chat"),
            submitted_at=time.time(),
            future=future,
            user_meta=user_meta,
            assistant_meta=assistant_meta,
        )
        with self._lock:
            self._tickets[ticket_id] = ticket
        future.add_done_callback(lambda done: self._complete(ticket, done))
        return ticket

    def _complete(self, ticket: ObservationTicket, future: Future[CognitiveObservation]) -> None:
        if not ticket.claim():
            return
        with self._lock:
            self._tickets.pop(ticket.ticket_id, None)
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
        self._log(
            "info",
            "[post observer] turn=%s act=%s meaning=%s conf=%.2f repair=%s source=%s latency=%.0fms",
            observation.turn_seq,
            observation.user_act,
            observation.relationship_meaning,
            observation.confidence,
            observation.repair_needed,
            observation.source,
            observation.latency_ms,
        )

    def shutdown(self) -> None:
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["ObservationTicket", "PostTurnObserver"]
