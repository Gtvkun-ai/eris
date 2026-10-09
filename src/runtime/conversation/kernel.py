# -*- coding: utf-8 -*-
"""ConversationKernel V12 — lifecycle/concurrency owner, không phải conversation planner."""
from __future__ import annotations

from dataclasses import dataclass, replace
import threading
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
from .context import ConversationNoteTools
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
    # Metadata cơ học của continuation chain. Writer không nhìn thấy hai field
    # này; kernel chỉ truyền lại scheduler để chống self-wake vô hạn.
    continuation_chain_started_at: float = 0.0
    consecutive_self_wakes: int = 0

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
        self._delivery_lock = threading.RLock()
        self._delivery_turns: dict[str, KernelTurn] = {}
        self._event_condition = threading.Condition(threading.RLock())
        self._event_results: dict[str, ConversationRunResult] = {}
        self._events_inflight: set[str] = set()

    def handle_event(
        self,
        event: ConversationEvent,
        *,
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
    ) -> ConversationRunResult:
        event_id = str(event.event_id or "")[:240]
        if not event_id:
            return self._handle_event_once(
                event,
                recent_history=recent_history,
                runtime_context=runtime_context,
            )
        with self._event_condition:
            while event_id in self._events_inflight:
                self._event_condition.wait()
            cached = self._event_results.get(event_id)
            if cached is not None:
                return cached
            self._events_inflight.add(event_id)
        try:
            result = self._handle_event_once(
                event,
                recent_history=recent_history,
                runtime_context=runtime_context,
            )
        except Exception:
            with self._event_condition:
                self._events_inflight.discard(event_id)
                self._event_condition.notify_all()
            raise
        with self._event_condition:
            if len(self._event_results) >= 512:
                self._event_results.pop(next(iter(self._event_results)))
            self._event_results[event_id] = result
            self._events_inflight.discard(event_id)
            self._event_condition.notify_all()
        return result

    def _handle_event_once(
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
            self._discard_session_deliveries(sid)
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
        agent_context = self._agent_runtime_context(sid, runtime_context)
        # Execution token được kernel cấp, không cho client/model tự chỉ định.
        agent_context["__conversation_run_id"] = run_id
        # Pin registry vào normalized generation của kernel. Input trước kernel
        # có thể mang generation=0; receipt từ Root phải dùng generation THỰC.
        from .claim_evidence import EvidenceRegistry
        registry = agent_context.get("__evidence_registry")
        if isinstance(registry, EvidenceRegistry):
            if registry.event_id == normalized_event.event_id and registry.session_id == sid:
                agent_context["__evidence_registry"] = replace(
                    registry, generation=normalized_event.generation, run_id=run_id,
                )
            else:
                # Deferred continuation có event_id riêng. Tuyệt đối không đem
                # sources của wake signal khác sang chứng minh lời đang nói.
                agent_context["__evidence_registry"] = None
        decision = self.agent.decide(
            event=normalized_event,
            recent_history=recent_history,
            note=state.note,
            runtime_context=agent_context,
        )
        current = self.store.load(sid)
        if current.generation != state.generation or current.active_run_id != run_id:
            return ConversationRunResult(
                event=normalized_event,
                decision=decision,
                status="stale",
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

        continuation_meta = (runtime_context or {}).get("continuation_lease", {})
        if not isinstance(continuation_meta, Mapping):
            continuation_meta = {}
        turn = KernelTurn(
            session_id=sid,
            generation=state.generation,
            run_id=run_id,
            move=decision,
            note=current.note,
            continuation=event.kind == "continuation_due",
            continuation_chain_started_at=float(continuation_meta.get("chain_started_at", 0.0) or 0.0),
            consecutive_self_wakes=max(0, int(continuation_meta.get("consecutive_self_wakes", 0) or 0)),
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
                runtime_context={**dict(runtime_context or {}),
                                 "__evidence_registry": agent_context.get("__evidence_registry")},
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
        with self._delivery_lock:
            self._delivery_turns[delivery_id] = turn
        try:
            self.delivery.deliver(turn=turn, rendered=rendered, delivery_id=delivery_id)
        except Exception as exc:
            self._log("warning", "[conversation-v12] delivery failed: %s", exc)
            self.settle_delivery_id(
                session_id=turn.session_id,
                delivery_id=delivery_id,
                successful=False,
            )
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

    def handle_due_continuation(
        self,
        *,
        session_id: str,
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> ConversationRunResult | None:
        sid = str(session_id or "default")[:180]
        state = self.store.load(sid)
        lease = self.continuation.claim_due(
            session_id=sid,
            generation=state.generation,
            now=now,
        )
        if lease is None:
            return None
        event = ConversationEvent.continuation_due(
            session_id=sid,
            generation=lease.generation,
            lease_id=lease.lease_id,
        )
        context = {
            **dict(runtime_context or {}),
            "continuation_lease": lease.to_dict(),
        }
        try:
            result = self.handle_event(
                event,
                recent_history=recent_history,
                runtime_context=context,
            )
        except Exception:
            if self.store.load(sid).generation == lease.generation:
                self.continuation.release(lease)
            raise
        if result.status in {"writer_failed", "writer_unavailable"}:
            if self.store.load(sid).generation == lease.generation:
                self.continuation.release(lease)
        else:
            self.continuation.consume(lease)
        return result

    def settle_delivery_id(
        self,
        *,
        session_id: str = "",
        delivery_id: str,
        successful: bool,
    ) -> bool:
        did = str(delivery_id or "")[:180]
        with self._delivery_lock:
            turn = self._delivery_turns.get(did)
        if turn is None:
            return False
        sid = str(session_id or turn.session_id)[:180]
        if sid != turn.session_id:
            return False
        settled = self.settle_delivery(turn, delivery_id=did, successful=successful)
        if settled:
            with self._delivery_lock:
                self._delivery_turns.pop(did, None)
        return settled

    def _discard_session_deliveries(self, session_id: str) -> None:
        with self._delivery_lock:
            stale = [
                delivery_id
                for delivery_id, turn in self._delivery_turns.items()
                if turn.session_id == session_id
            ]
            for delivery_id in stale:
                self._delivery_turns.pop(delivery_id, None)

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
            runtime_context=self._agent_runtime_context(sid, runtime_context),
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
                runtime_context=self._agent_runtime_context(
                    sid,
                    {**dict(runtime_context or {}), "continuation_lease": lease.to_dict()},
                ),
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
            return KernelTurn(
                sid,
                state.generation,
                run_id,
                move,
                state.note,
                True,
                lease.chain_started_at,
                lease.consecutive_self_wakes,
            )
        except Exception:
            self.continuation.release(lease)
            raise

    def _agent_runtime_context(
        self,
        session_id: str,
        runtime_context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Gắn note tools cơ học cho RootAgent mà không đưa chúng xuống writer.

        Capability registry (nếu caller cung cấp) được giữ nguyên trong mapping
        nội bộ. ``RuntimeModelRootAgent`` tự chặn các key ``__*`` khỏi model
        payload; writer cũng chỉ nhận public runtime context gốc.
        """

        sid = str(session_id or "default")[:180]
        context = dict(runtime_context or {})
        context["__conversation_note_tools"] = ConversationNoteTools(
            set_note=lambda text: self.store.set_note(sid, text),
            clear_note=lambda: self.store.clear_note(sid),
        )
        return context

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
            parent_chain_started_at=turn.continuation_chain_started_at if turn.continuation else 0.0,
            parent_self_wakes=turn.consecutive_self_wakes if turn.continuation else 0,
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
