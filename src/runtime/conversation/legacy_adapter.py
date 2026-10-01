# -*- coding: utf-8 -*-
"""Adapter tạm từ ConversationKernel V12 sang consumer V11 còn sống.

Đây là adapter **một chiều**: V12 -> shape cũ. Không một quyết định semantic nào
được đọc ngược từ SpeechPlan/TurnProjection để điều khiển V12. Khi writer/body
cutover xong, file này phải được xóa mà không thay đổi ConversationKernel.
"""
from __future__ import annotations

from dataclasses import replace
import time
from typing import Any, Mapping, Sequence

from runtime.agent_loop.contracts import (
    AgentTurnResult, AgentTurnState, BeatKind, CognitivePlan, ConversationSpeechPlan,
    DialogueBeat, DiscoursePlan, SpeechContinuationMode, TurnFloor, TurnProjection,
)
from runtime.agent_loop.speech_plan import SpeechPlanSnapshot

from .contracts import ConversationAfter, NextConversationMove, RunPhase
from .kernel import ConversationKernel, KernelTurn


def move_to_legacy_result(turn: KernelTurn, *, user_text: str, degraded: bool = False) -> AgentTurnResult:
    move = turn.move
    if move.after == ConversationAfter.CONTINUE_SELF:
        mode = SpeechContinuationMode.AUTO_CONTINUE
        floor = TurnFloor.HOLD
        resume = "auto_after_audio"
    elif move.after == ConversationAfter.MAY_CONTINUE:
        # V11 không có may_continue. Adapter chỉ cần giữ consumer cũ không crash;
        # scheduler thật vẫn nằm trong V12 và không đọc giá trị này ngược lại.
        mode = SpeechContinuationMode.AUTO_CONTINUE
        floor = TurnFloor.OPEN
        resume = "auto_after_audio"
    else:
        mode = SpeechContinuationMode.NONE
        floor = TurnFloor.YIELD
        resume = ""

    beat = DialogueBeat(
        kind=BeatKind.EXPLANATION,
        proposition=move.say,
        communicative_goal=move.intent,
        relation_to_previous="continue",
        detail_level="normal",
        needs_example=False,
    )
    speech_plan = ConversationSpeechPlan(
        plan_id=move.move_id,
        topic="",
        conversation_goal=move.intent,
        current_thread="",
        discussed=(),
        planned_threads=(),
        next_intent="continue only by re-running root agent" if mode == SpeechContinuationMode.AUTO_CONTINUE else "",
        desired_shape=move.delivery,
        continuation_mode=mode,
        resume_trigger=resume,
        pause_seconds=0.0,
    )
    state = AgentTurnState(
        turn_id=turn.run_id,
        user_text=str(user_text or "")[:16000],
        session_id=turn.session_id,
        iteration=0,
        cognitive=CognitivePlan(
            situation_summary="V12 root conversation move",
            objective=move.intent,
            task_shape="conversation",
            active_roles=("general",),
            work_items=(),
            uncertainties=(),
        ),
        discourse=DiscoursePlan(public_beats=(beat,), style_notes=(), user_response_required=False),
        speech_plan=speech_plan,
        turn_projection=TurnProjection(
            floor=floor,
            continuation_feel="neutral",
            verbal_bridge_hint="",
        ),
        progress=1.0,
        uncertainty=0.0,
        status="complete",
        decision_summaries=("V12 NextConversationMove finalized",),
    )
    result = AgentTurnResult(state=state, completion_reason="v12_root_move", model_iterations=1, degraded=degraded)
    # Dataclass cũ không có field move; caller lấy payload qua helper bên dưới.
    return result


def result_payload_with_v12(result: AgentTurnResult, turn: KernelTurn) -> dict[str, Any]:
    payload = result.to_dict()
    payload["schema"] = "eris.agent_turn.v12_adapter"
    payload["next_conversation_move"] = turn.move.to_dict()
    payload["conversation_kernel"] = {
        "session_id": turn.session_id,
        "generation": turn.generation,
        "run_id": turn.run_id,
        "continuation": turn.continuation,
    }
    return payload


class V12AgentTurnRuntime:
    """Giữ API ``agent_turn_runtime`` cũ nhưng toàn bộ semantic đi qua V12."""

    def __init__(self, kernel: ConversationKernel, *, tutor_role: Any = None, logger: Any = None) -> None:
        self.kernel = kernel
        self.tutor_role = tutor_role
        self.logger = logger
        self.last_result: AgentTurnResult | None = None
        self.last_kernel_turn: KernelTurn | None = None
        self.last_payload: Mapping[str, Any] = {}
        self.last_tutor_role: Mapping[str, Any] = {}
        self._last_session_id = "default"
        self._delivery_turns: dict[str, KernelTurn] = {}
        # no_tts có thể báo receipt đồng bộ bên trong stage trước khi _commit()
        # trả về để orchestrator gọi commit_public_delivery. Giữ receipt cơ học
        # này để settle đúng thứ tự mà không schedule continuation sớm.
        self._pending_finished_delivery_ids: set[str] = set()

    def prepare_turn(self, *, turn_id: str, user_text: str, session_id: str = "default",
                     recent_history: Sequence[Mapping[str, Any]] = (),
                     runtime_context: Mapping[str, Any] | None = None,
                     continuation_wake: Mapping[str, Any] | None = None) -> AgentTurnResult:
        del turn_id, continuation_wake
        context = dict(runtime_context or {})
        sid = str(session_id or "default")[:180]
        self._last_session_id = sid

        # Tutor hiện chỉ là domain advisor. Nó có thể cung cấp evidence/directive,
        # nhưng root V12 vẫn là nơi duy nhất chọn câu public và lifecycle.
        if self.tutor_role is not None:
            try:
                contribution = self.tutor_role.begin_turn(
                    turn_id=f"v12:{time.time_ns()}", user_text=user_text,
                    recent_history=recent_history,
                )
                self.last_tutor_role = contribution.to_dict()
                context["tutor_capability"] = self.last_tutor_role
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[conversation-v12] tutor advisor degraded: %s", exc)

        turn = self.kernel.begin_user_turn(
            session_id=sid,
            user_text=user_text,
            recent_history=recent_history,
            runtime_context=context,
        )
        result = move_to_legacy_result(turn, user_text=user_text)
        self.last_kernel_turn = turn
        self.last_result = result
        self.last_payload = result_payload_with_v12(result, turn)
        return result

    def payload_for(self, result: AgentTurnResult | None = None) -> dict[str, Any]:
        if result is self.last_result and self.last_payload:
            return dict(self.last_payload)
        if self.last_kernel_turn is not None:
            return result_payload_with_v12(result or self.last_result, self.last_kernel_turn) if (result or self.last_result) else {}
        return result.to_dict() if result is not None else {}

    def commit_public_delivery(self, *, successful: bool, public_text: str = "", turn_id: str = "",
                               session_id: str = "") -> None:
        del public_text
        turn = self.last_kernel_turn
        if turn is None:
            return
        sid = str(session_id or turn.session_id or self._last_session_id)[:180]
        if sid != turn.session_id:
            return
        delivery_id = str(turn_id or f"delivery:{time.time_ns()}")[:180]
        if successful:
            # Text đã commit chưa đồng nghĩa audio đã xong. Chỉ đánh dấu delivery
            # started; continuation được schedule ở receipt audio_done/no_tts.
            self.kernel.mark_delivery_started(turn, delivery_id=delivery_id)
            self._delivery_turns[delivery_id] = turn
            if delivery_id in self._pending_finished_delivery_ids:
                self._pending_finished_delivery_ids.discard(delivery_id)
                self.kernel.settle_delivery(turn, delivery_id=delivery_id, successful=True)
                self._delivery_turns.pop(delivery_id, None)
        else:
            self.kernel.settle_delivery(turn, delivery_id=delivery_id, successful=False)
        if self.tutor_role is not None:
            try:
                self.tutor_role.commit_public_delivery(successful=successful, public_text="")
            except Exception:
                pass

    def note_audio_finished(self, *, session_id: str = "", delivery_id: str = "") -> SpeechPlanSnapshot:
        sid = str(session_id or self._last_session_id or "default")[:180]
        turn = None
        if delivery_id:
            turn = self._delivery_turns.pop(str(delivery_id)[:180], None)
        if turn is None:
            turn = self.last_kernel_turn
        if turn is not None and turn.session_id == sid:
            did = str(delivery_id or self.kernel.snapshot(sid).active_delivery_id or f"delivery:{time.time_ns()}")[:180]
            state = self.kernel.snapshot(sid)
            if not state.active_delivery_id:
                # Receipt đến trước commit_public_delivery (thường là no_tts sync).
                self._pending_finished_delivery_ids.add(did)
            else:
                self.kernel.settle_delivery(turn, delivery_id=did, successful=True)
                self._delivery_turns.pop(did, None)
        return self.speech_plan_snapshot(session_id=sid)

    def speech_plan_snapshot(self, *, session_id: str = "") -> SpeechPlanSnapshot:
        sid = str(session_id or self._last_session_id or "default")[:180]
        state = self.kernel.snapshot(sid)
        lease = self.kernel.continuation.peek(sid)
        mode = SpeechContinuationMode.NONE
        due_at = 0.0
        status = "waiting_user"
        if lease is not None:
            mode = SpeechContinuationMode.AUTO_CONTINUE
            due_at = lease.due_at
            status = "auto_continue_scheduled"
        plan = ConversationSpeechPlan(
            continuation_mode=mode,
            next_intent="wake root agent" if lease is not None else "",
            resume_trigger="auto_after_audio" if lease is not None else "",
        )
        return SpeechPlanSnapshot(
            session_id=sid,
            plan=plan,
            turn_projection=TurnProjection(),
            status=status,
            last_turn_id=state.active_run_id,
            last_public_text="",
            due_at=due_at,
            claim_token="",
            version=state.version,
            updated_at=state.updated_at,
        )

    def prepare_continuation_turn(self, *, session_id: str = "",
                                  recent_history: Sequence[Mapping[str, Any]] = (),
                                  runtime_context: Mapping[str, Any] | None = None) -> AgentTurnResult | None:
        sid = str(session_id or self._last_session_id or "default")[:180]
        turn = self.kernel.begin_continuation(
            session_id=sid,
            recent_history=recent_history,
            runtime_context=runtime_context or {},
        )
        if turn is None:
            return None
        result = move_to_legacy_result(turn, user_text="")
        self.last_kernel_turn = turn
        self.last_result = result
        self.last_payload = result_payload_with_v12(result, turn)
        return result

    def preempt_for_user(self, *, session_id: str = "") -> None:
        self.kernel.preempt_for_user(str(session_id or self._last_session_id or "default")[:180])

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["V12AgentTurnRuntime", "move_to_legacy_result", "result_payload_with_v12"]
