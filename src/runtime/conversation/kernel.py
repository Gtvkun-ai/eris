# -*- coding: utf-8 -*-
"""ConversationKernel V12 — lifecycle/concurrency owner, không phải conversation planner."""
from __future__ import annotations

from dataclasses import dataclass, replace
import time
import uuid
from typing import Any, Mapping, Sequence

from .agent import RootAgent
from .contracts import (
    ConversationAfter,
    ConversationEvent,
    ConversationSessionState,
    DeliveryReceipt,
    NextConversationMove,
    NoReply,
    RunPhase,
)
from .continuation import ContinuationLeaseScheduler
from .delivery import ConversationDelivery
from .receipts import DeliveryReceiptLedger
from .session_store import ConversationSessionStore
from .writer import ConversationWriter, RenderedConversationMove


@dataclass(frozen=True, slots=True)
class KernelTurn:
    session_id: str
    generation: int
    run_id: str
    move: NextConversationMove
    note: str
    continuation: bool = False

    def writer_context(self) -> dict[str, Any]:
        return {
            "schema": "eris.conversation_writer_context.v12",
            "session_id": self.session_id,
            "generation": self.generation,
            "run_id": self.run_id,
            "move": self.move.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ConversationRunResult:
    event: ConversationEvent
    decision: NoReply | NextConversationMove | None
    turn: KernelTurn | None = None
    rendered: RenderedConversationMove | None = None
    delivery_id: str = ""
    status: str = "idle"


class ConversationKernel:
    def __init__(self, agent: RootAgent, *, store: ConversationSessionStore | None = None,
                 continuation: ContinuationLeaseScheduler | None = None,
                 receipts: DeliveryReceiptLedger | None = None,
                 writer: ConversationWriter | None = None,
                 delivery: ConversationDelivery | None = None,
                 logger: Any = None) -> None:
        self.agent = agent
        self.store = store or ConversationSessionStore(logger=logger)
        self.continuation = continuation or ContinuationLeaseScheduler(logger=logger)
        self.receipts = receipts or DeliveryReceiptLedger(logger=logger)
        self.writer = writer
        self.delivery = delivery
        self.logger = logger

    def handle_event(
        self,
        event: ConversationEvent,
        *,
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
    ) -> ConversationRunResult:
        sid = str(event.session_id or "default")[:180]
        run_id = f"run:{uuid.uuid4().hex}"
        if event.kind == "user_turn":
            self.continuation.cancel_session(sid)
            state = self.store.mutate(
                sid,
                lambda prior, now: replace(
                    prior,
                    generation=prior.generation + 1,
                    active_run_id=run_id,
                    active_move_id="",
                    active_delivery_id="",
                    phase=RunPhase.THINKING,
                ),
            )
        else:
            state = self.store.load(sid)
            if event.generation not in {0, state.generation}:
                return ConversationRunResult(event=event, decision=None, status="stale")
            state = self.store.mutate(
                sid,
                lambda prior, now: replace(
                    prior,
                    active_run_id=run_id,
                    active_move_id="",
                    active_delivery_id="",
                    phase=RunPhase.THINKING,
                ),
            )

        normalized_event = replace(event, session_id=sid, generation=state.generation)
        decision = self.agent.decide(
            event=normalized_event,
            recent_history=recent_history,
            note=state.note,
            runtime_context=dict(runtime_context or {}),
        )
        if isinstance(decision, NoReply):
            self.store.mutate(
                sid,
                lambda prior, now: replace(
                    prior,
                    active_run_id="",
                    active_move_id="",
                    active_delivery_id="",
                    phase=RunPhase.WAITING_USER,
                ),
            )
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                status="no_reply",
            )

        turn = KernelTurn(
            session_id=sid,
            generation=state.generation,
            run_id=run_id,
            move=decision,
            note=state.note,
            continuation=event.kind == "continuation_due",
        )
        self.store.mutate(
            sid,
            lambda prior, now: replace(
                prior,
                active_move_id=decision.move_id,
                phase=RunPhase.WRITING,
            ),
        )
        if self.writer is None:
            self._fail_run(turn)
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                turn=turn,
                status="writer_unavailable",
            )
        try:
            rendered = self.writer.realize(
                turn=turn,
                event=normalized_event,
                recent_history=recent_history,
                runtime_context=dict(runtime_context or {}),
            )
        except Exception as exc:
            self._log("debug", "[conversation-v12] writer failed: %s", exc)
            self._fail_run(turn)
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                turn=turn,
                status="writer_failed",
            )

        current = self.store.load(sid)
        if current.generation != turn.generation or current.active_run_id != turn.run_id:
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                turn=turn,
                rendered=rendered,
                status="stale",
            )
        delivery_id = f"delivery:{uuid.uuid4().hex}"
        if self.delivery is None or not self.mark_delivery_started(turn, delivery_id=delivery_id):
            self._fail_run(turn)
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                turn=turn,
                rendered=rendered,
                status="delivery_unavailable",
            )
        try:
            self.delivery.deliver(turn=turn, rendered=rendered, delivery_id=delivery_id)
        except Exception as exc:
            self._log("debug", "[conversation-v12] delivery failed: %s", exc)
            self.settle_delivery(turn, delivery_id=delivery_id, successful=False)
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                turn=turn,
                rendered=rendered,
                delivery_id=delivery_id,
                status="delivery_failed",
            )
        return ConversationRunResult(
            event=normalized_event,
            decision=decision,
            turn=turn,
            rendered=rendered,
            delivery_id=delivery_id,
            status="delivering",
        )

    def _fail_run(self, turn: KernelTurn) -> None:
        state = self.store.load(turn.session_id)
        if state.generation != turn.generation or state.active_run_id != turn.run_id:
            return
        self.store.mutate(
            turn.session_id,
            lambda prior, now: replace(
                prior,
                active_delivery_id="",
                phase=RunPhase.FAILED,
            ),
        )

    def _log(self, level: str, message: str, *args: Any) -> None:
        method = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass

    def begin_user_turn(self, *, session_id: str, user_text: str,
                        recent_history: Sequence[Mapping[str, Any]] = (),
                        runtime_context: Mapping[str, Any] | None = None) -> KernelTurn:
        sid = str(session_id or "default")[:180]
        self.continuation.cancel_session(sid)
        run_id = f"run:{uuid.uuid4().hex}"
        state = self.store.mutate(
            sid,
            lambda prior, now: replace(
                prior,
                generation=prior.generation + 1,
                active_run_id=run_id,
                active_move_id="",
                active_delivery_id="",
                phase=RunPhase.THINKING,
            ),
        )
        event = ConversationEvent.user_turn(
            session_id=sid,
            text=str(user_text or ""),
            generation=state.generation,
        )
        decision = self.agent.decide(
            event=event,
            recent_history=recent_history,
            note=state.note,
            runtime_context=dict(runtime_context or {}),
        )
        if isinstance(decision, NoReply):
            self.store.mutate(sid, lambda prior, now: replace(prior, phase=RunPhase.WAITING_USER))
            raise RuntimeError("user_turn_no_reply")
        move = decision
        self.store.mutate(
            sid,
            lambda prior, now: replace(prior, active_move_id=move.move_id, phase=RunPhase.WRITING),
        )
        return KernelTurn(sid, state.generation, run_id, move, state.note, False)

    def begin_continuation(self, *, session_id: str,
                           recent_history: Sequence[Mapping[str, Any]] = (),
                           runtime_context: Mapping[str, Any] | None = None) -> KernelTurn | None:
        sid = str(session_id or "default")[:180]
        state = self.store.load(sid)
        lease = self.continuation.claim_due(session_id=sid, generation=state.generation)
        if lease is None:
            return None
        run_id = f"run:{uuid.uuid4().hex}"
        self.store.mutate(sid, lambda prior, now: replace(prior, active_run_id=run_id, phase=RunPhase.THINKING))
        try:
            event = ConversationEvent(
                event_id=f"continuation:{lease.lease_id}",
                session_id=sid,
                kind="continuation_due",
                generation=state.generation,
                metadata={"continuation_lease": lease.to_dict()},
            )
            decision = self.agent.decide(
                event=event,
                recent_history=recent_history,
                note=state.note,
                runtime_context={**dict(runtime_context or {}), "continuation_lease": lease.to_dict()},
            )
            self.continuation.consume(lease)
            if isinstance(decision, NoReply):
                self.store.mutate(
                    sid,
                    lambda prior, now: replace(
                        prior,
                        active_run_id="",
                        active_move_id="",
                        phase=RunPhase.WAITING_USER,
                    ),
                )
                return None
            move = decision
            self.store.mutate(
                sid,
                lambda prior, now: replace(prior, active_move_id=move.move_id, phase=RunPhase.WRITING),
            )
            return KernelTurn(sid, state.generation, run_id, move, state.note, True)
        except Exception:
            self.continuation.release(lease)
            raise

    def set_note(self, session_id: str, note: str) -> None:
        self.store.set_note(session_id, note)

    def clear_note(self, session_id: str) -> None:
        self.store.clear_note(session_id)

    def mark_delivery_started(self, turn: KernelTurn, *, delivery_id: str) -> bool:
        state = self.store.load(turn.session_id)
        if state.generation != turn.generation or state.active_run_id != turn.run_id:
            return False
        self.store.mutate(
            turn.session_id,
            lambda prior, now: replace(prior, active_delivery_id=str(delivery_id or "")[:180], phase=RunPhase.DELIVERING),
        )
        return True

    def settle_delivery(self, turn: KernelTurn, *, delivery_id: str, successful: bool) -> bool:
        state = self.store.load(turn.session_id)
        if state.generation != turn.generation:
            return False
        receipt = DeliveryReceipt(
            delivery_id=str(delivery_id or "")[:180], session_id=turn.session_id,
            generation=turn.generation, move_id=turn.move.move_id, successful=bool(successful),
        )
        if not self.receipts.commit_once(receipt):
            return False
        if not successful:
            self.store.mutate(turn.session_id, lambda prior, now: replace(prior, phase=RunPhase.FAILED, active_delivery_id=""))
            return True
        lease = self.continuation.schedule(
            session_id=turn.session_id,
            generation=turn.generation,
            move_id=turn.move.move_id,
            after=turn.move.after,
        )
        phase = RunPhase.CONTINUATION_PENDING if lease is not None else RunPhase.WAITING_USER
        self.store.mutate(
            turn.session_id,
            lambda prior, now: replace(
                prior,
                phase=phase,
                active_delivery_id="",
                last_delivered_move_id=turn.move.move_id,
                last_delivery_finished_at=now,
            ),
        )
        return True

    def preempt_for_user(self, session_id: str) -> ConversationSessionState:
        sid = str(session_id or "default")[:180]
        self.continuation.cancel_session(sid)
        return self.store.mutate(
            sid,
            lambda prior, now: replace(
                prior,
                generation=prior.generation + 1,
                active_run_id="",
                active_move_id="",
                active_delivery_id="",
                phase=RunPhase.CANCELLED,
            ),
        )

    def snapshot(self, session_id: str) -> ConversationSessionState:
        return self.store.load(session_id)


__all__ = ["ConversationKernel", "ConversationRunResult", "KernelTurn"]
