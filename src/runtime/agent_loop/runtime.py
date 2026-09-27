# -*- coding: utf-8 -*-
"""Generic foreground TurnAgentRuntime — root loop duy nhất của mọi chat.

Mỗi user message đi qua runtime này. Tutor/coding/research/companion chỉ là role.
Runtime không public chain-of-thought; nó tích lũy typed state rồi mới giao cho
public writer một DiscoursePlan đã được cắt theo nhịp hội thoại/TTS.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import time
from typing import Any, Mapping, Sequence

from .completion import CompletionGate
from .contracts import (
    AgentTurnResult,
    AgentTurnState,
    CognitivePlan,
    DisclosureMode,
    DiscoursePlan,
    ExecutionPlan,
    LoopBudget,
    TurnDecision,
    TurnSpeechBudget,
)
from .director import ConversationDirector
from .pacing import DisclosureArcLedger
from .reasoner import RuntimeModelTurnReasoner, TurnReasoner
from .tutor_role import TutorRoleCoordinator


class TurnAgentRuntime:
    def __init__(
        self,
        reasoner: TurnReasoner,
        *,
        director: ConversationDirector | None = None,
        completion_gate: CompletionGate | None = None,
        budget: LoopBudget | None = None,
        arc_ledger: DisclosureArcLedger | None = None,
        tutor_role: TutorRoleCoordinator | None = None,
        logger: Any | None = None,
    ) -> None:
        self.reasoner = reasoner
        self.director = director or ConversationDirector()
        self.completion_gate = completion_gate or CompletionGate()
        self.budget = (budget or LoopBudget()).normalized()
        self.arc_ledger = arc_ledger or DisclosureArcLedger(logger=logger)
        self.tutor_role = tutor_role or TutorRoleCoordinator(None, logger=logger)
        self.logger = logger
        self.last_result: AgentTurnResult | None = None
        self.last_tutor_role: Mapping[str, Any] = {}

    def prepare_turn(
        self,
        *,
        turn_id: str,
        user_text: str,
        session_id: str = "default",
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
    ) -> AgentTurnResult:
        """Chạy agent loop cho đúng *một* user turn.

        ``session_id`` dùng để nối ConversationArc qua nhiều lượt. Nó không phải
        learning path ID và cũng không phải coding task thread ID.
        """
        context = dict(runtime_context or {})
        sid = str(session_id or "default")[:180]
        prior_arc = self.arc_ledger.load(sid)
        context["disclosure_arc"] = prior_arc.to_dict()

        # Tutor role được chuẩn bị TRƯỚC iteration đầu nếu không có pending answer.
        # Nếu đang chờ câu trả lời cũ, root semantic executive sẽ phân loại relation
        # trước; chỉ relation=answer mới được TutorExecutive chấm thành evidence.
        tutor_contribution = self.tutor_role.begin_turn(
            turn_id=turn_id,
            user_text=user_text,
            recent_history=recent_history,
        )
        context["tutor_role"] = tutor_contribution.to_dict()

        state = AgentTurnState(
            turn_id=str(turn_id or "")[:160],
            user_text=str(user_text or "")[:16000],
            session_id=sid,
            discourse=DiscoursePlan(style_notes=self.director.DEFAULT_STYLE_NOTES),
        )
        previous_fingerprint = ""
        degraded = False
        model_iterations = 0
        completion_reason = ""
        started_at = time.monotonic()

        for iteration in range(self.budget.hard_iterations):
            if iteration > 0 and (time.monotonic() - started_at) >= self.budget.max_wall_seconds:
                completion_reason = "wall_clock_budget"
                state = replace(state, status="complete")
                break
            state = replace(state, iteration=iteration)
            try:
                decision = self.reasoner.decide(
                    user_text=state.user_text,
                    recent_history=recent_history,
                    state=state.to_model_dict(),
                    runtime_context=context,
                )
                model_iterations += 1
            except Exception as exc:  # noqa: BLE001
                self._log("warning", "[agent-turn] reasoner failed: %s", exc)
                degraded = True
                break

            # Root executive vừa phân loại relation với tutor pending move. Adapter
            # có thể commit evidence hoặc sinh TeachingMove mới, nhưng KHÔNG public.
            tutor_update = self.tutor_role.apply_root_decision(
                decision,
                user_text=state.user_text,
                turn_id=turn_id,
                recent_history=recent_history,
            )
            self.last_tutor_role = tutor_update.to_dict()
            context["tutor_role"] = self.last_tutor_role

            merged_discourse = self.director.merge(
                state.discourse,
                decision.discourse,
                max_beats=self.budget.max_beats,
            )
            execution = ExecutionPlan(
                completed_items=decision.completed_items,
                remaining_items=decision.remaining_items,
                external_action_needed=_external_action_needed(context),
                external_action_status=_external_action_status(context),
            )
            cognitive = self._merge_cognitive(state.cognitive, decision.cognitive)
            fingerprint = self._decision_fingerprint(decision)
            stalled = bool(previous_fingerprint and fingerprint == previous_fingerprint)
            stall_count = state.stall_count + 1 if stalled else 0
            previous_fingerprint = fingerprint
            summaries = tuple(item for item in (*state.decision_summaries, decision.decision_summary) if item)[-5:]
            state = replace(
                state,
                cognitive=cognitive,
                execution=execution,
                discourse=merged_discourse,
                progress=max(state.progress, decision.progress),
                uncertainty=min(state.uncertainty, decision.uncertainty),
                stall_count=stall_count,
                decision_summaries=summaries,
            )

            verdict = self.completion_gate.evaluate(state=state, decision=decision, budget=self.budget)

            # Nếu tutor vừa tạo/chuyển TeachingMove trong iteration này thì model
            # cần được thấy directive mới ở iteration kế tiếp trước khi COMPLETE.
            # Ngoại lệ: hard budget hết thì fail-soft với context tốt nhất hiện có.
            if (
                tutor_update.changed_this_iteration
                and iteration + 1 < self.budget.hard_iterations
            ):
                verdict = replace(verdict, stop=False, status="running", reason="tutor_role_replan")

            if verdict.stop:
                completion_reason = verdict.reason
                state = replace(state, status=verdict.status)
                break

            # Soft budget chỉ kéo dài khi còn work có tên hoặc turn là deep dialogue.
            if iteration + 1 >= self.budget.soft_iterations:
                has_named_work = bool(decision.remaining_items)
                deep_mode = state.discourse.response_mode in {"deep", "progressive"}
                if not has_named_work and not deep_mode and not tutor_update.changed_this_iteration:
                    completion_reason = "soft_budget_sufficient"
                    state = replace(state, status="complete")
                    break
        else:
            completion_reason = "hard_iteration_budget"
            state = replace(state, status="complete")

        if state.status == "running":
            state = replace(state, status="complete")
            completion_reason = completion_reason or "degraded_runtime_completion"
            degraded = True

        speakable = self.director.ensure_speakable(state.discourse, objective=state.cognitive.objective)

        # Voice/TTS là pacing concern, không phải reasoning concern. Agent được
        # nghĩ sâu như cũ, nhưng public speech bị cắt ngắn để user còn chen vào.
        voice_mode = bool(context.get("voice_mode", False))
        paced = self.director.apply_turn_pacing(
            speakable,
            voice_mode=voice_mode,
            explicit_exhaustive_request=(speakable.disclosure_mode == DisclosureMode.REPORT),
        )

        # Tutor question cần response => một beat là đủ, rồi HARD WAIT sau delivery.
        if bool(self.last_tutor_role.get("waiting_for_user")):
            one_beat = paced.beats[:1]
            paced = replace(
                paced,
                beats=one_beat,
                user_response_required=True,
                speech_budget=TurnSpeechBudget(
                    target_words=min(paced.speech_budget.target_words, 70 if voice_mode else 110),
                    hard_max_words=min(paced.speech_budget.hard_max_words, 110 if voice_mode else 170),
                    max_beats=1,
                    target_seconds=min(paced.speech_budget.target_seconds, 20.0 if voice_mode else 30.0),
                ).normalized(),
            )
            state = replace(state, status="waiting_user")
            completion_reason = "tutor_requires_user_response"

        state = replace(state, discourse=paced)

        # Commit *kế hoạch tiếp tục*, không tự schedule speech. User turn kế tiếp
        # sẽ đọc state này và được quyền steering/replan.
        continuation = state.discourse.continuation
        discussed = tuple(
            beat.proposition for beat in state.discourse.beats if beat.proposition
        )
        self.arc_ledger.commit(
            sid,
            topic=state.cognitive.objective,
            active_thread=continuation.active_thread,
            discussed_threads=discussed,
            deferred_threads=continuation.deferred_threads,
            continuation_anchor=continuation.continuation_anchor,
            next_if_continue=continuation.next_if_continue,
        )

        result = AgentTurnResult(
            state=state,
            completion_reason=completion_reason or "complete",
            model_iterations=model_iterations,
            degraded=degraded,
        )
        self.last_result = result
        self._log(
            "info",
            "[agent-turn] turn=%s iterations=%s status=%s reason=%s roles=%s beats=%s disclosure=%s",
            state.turn_id,
            model_iterations,
            state.status,
            result.completion_reason,
            ",".join(state.cognitive.active_roles) or "general",
            len(state.discourse.beats),
            state.discourse.disclosure_mode.value,
        )
        return result

    def commit_public_delivery(self, *, successful: bool, public_text: str = "") -> None:
        """Public receipt hook; tutor side-effect chỉ xảy ra sau delivery thật."""
        self.tutor_role.commit_public_delivery(successful=successful, public_text=public_text)

    @staticmethod
    def _merge_cognitive(current: CognitivePlan, incoming: CognitivePlan) -> CognitivePlan:
        return CognitivePlan(
            situation_summary=incoming.situation_summary or current.situation_summary,
            objective=incoming.objective or current.objective,
            task_shape=incoming.task_shape or current.task_shape,
            active_roles=incoming.active_roles or current.active_roles,
            work_items=incoming.work_items or current.work_items,
            uncertainties=incoming.uncertainties,
        )

    @staticmethod
    def _decision_fingerprint(decision: TurnDecision) -> str:
        raw = json.dumps({
            "action": decision.action.value,
            "objective": decision.cognitive.objective,
            "work": decision.cognitive.work_items,
            "remaining": decision.remaining_items,
            "beats": [beat.proposition for beat in decision.discourse.beats],
            "thread": decision.discourse.continuation.active_thread,
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


def _external_action_status(context: Mapping[str, Any]) -> str:
    route = context.get("agent_execution_route")
    if not isinstance(route, Mapping):
        return "none"
    action = str(route.get("action", "none") or "none").strip().lower()
    status = str(route.get("start_status", "") or "").strip().lower()
    if action in {"execute", "consult"}:
        return status or "routed"
    if action == "clarify":
        return "needs_clarification"
    return "none"


def _external_action_needed(context: Mapping[str, Any]) -> bool:
    route = context.get("agent_execution_route")
    if not isinstance(route, Mapping):
        return False
    return str(route.get("action", "none") or "none").strip().lower() in {"execute", "consult", "clarify"}


def ensure_agent_turn_runtime(host: Any) -> TurnAgentRuntime:
    runtime = getattr(host, "agent_turn_runtime", None)
    if isinstance(runtime, TurnAgentRuntime):
        # Tutor có thể được bootstrap sau agent runtime trong một số test fixture.
        if runtime.tutor_role.executive is None and getattr(host, "tutor_executive", None) is not None:
            runtime.tutor_role = TutorRoleCoordinator(
                getattr(host, "tutor_executive", None),
                logger=getattr(host, "logger", None),
            )
        return runtime
    router = getattr(host, "ai_model_router", None)
    if router is None:
        raise RuntimeError("ai_model_router is required before creating TurnAgentRuntime")

    atomic_store = None
    try:
        from runtime.ai_orchestrated.atomic_state import atomic_store_from_env
        atomic_store = atomic_store_from_env(logger=getattr(host, "logger", None))
    except Exception:
        atomic_store = None

    runtime = TurnAgentRuntime(
        RuntimeModelTurnReasoner(router, logger=getattr(host, "logger", None)),
        arc_ledger=DisclosureArcLedger(
            atomic_store=atomic_store,
            logger=getattr(host, "logger", None),
        ),
        tutor_role=TutorRoleCoordinator(
            getattr(host, "tutor_executive", None),
            logger=getattr(host, "logger", None),
        ),
        logger=getattr(host, "logger", None),
    )
    host.agent_turn_runtime = runtime
    return runtime


__all__ = ["TurnAgentRuntime", "ensure_agent_turn_runtime"]
