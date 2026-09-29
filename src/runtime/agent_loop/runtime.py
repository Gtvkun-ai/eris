# -*- coding: utf-8 -*-
"""Generic foreground TurnAgentRuntime — root loop duy nhất của mọi chat.

Mỗi user message đi qua runtime này. Tutor/coding/research/companion chỉ là role.
Từ V7, chính root executive trong agent loop sở hữu cả *disclosure decision*:
ý nào nói ngay, ý nào giữ lại, lúc nào WAIT và lúc nào COMPLETE. Runtime chỉ
validate + project quyết định đó; không tự cắt/chọn semantic beat thay agent.
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
    ConversationSpeechPlan,
    DiscoursePlan,
    ExecutionPlan,
    LoopBudget,
    TurnDecision,
)
from .director import ConversationDirector
from .pacing import DisclosureArcLedger
from .speech_plan import SpeechPlanLedger, SpeechPlanSnapshot
from .reasoner import DeterministicFallbackTurnReasoner, RuntimeModelTurnReasoner, TurnReasoner
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
        speech_plan_ledger: SpeechPlanLedger | None = None,
        tutor_role: TutorRoleCoordinator | None = None,
        logger: Any | None = None,
    ) -> None:
        self.reasoner = reasoner
        self.director = director or ConversationDirector()
        self.completion_gate = completion_gate or CompletionGate()
        self.budget = (budget or LoopBudget()).normalized()
        self.arc_ledger = arc_ledger or DisclosureArcLedger(logger=logger)
        self.speech_plan_ledger = speech_plan_ledger or SpeechPlanLedger(logger=logger)
        self.tutor_role = tutor_role or TutorRoleCoordinator(None, logger=logger)
        self.logger = logger
        self.last_result: AgentTurnResult | None = None
        self.last_tutor_role: Mapping[str, Any] = {}
        # Cơ học single-user foreground: bind delivery/audio về session agent vừa
        # commit. Đây không phải semantic ownership; chỉ là routing receipt.
        self._last_session_id: str = "default"
        self._awaiting_audio_session_id: str = ""

    def prepare_turn(
        self,
        *,
        turn_id: str,
        user_text: str,
        session_id: str = "default",
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
        continuation_wake: Mapping[str, Any] | None = None,
    ) -> AgentTurnResult:
        """Chạy agent loop cho đúng *một* user turn.

        ``session_id`` dùng để nối ConversationArc qua nhiều lượt. Nó không phải
        learning path ID và cũng không phải coding task thread ID.
        """
        context = dict(runtime_context or {})
        sid = str(session_id or "default")[:180]
        prior_arc = self.arc_ledger.load(sid)
        context["disclosure_arc"] = prior_arc.to_dict()
        prior_speech = self.speech_plan_ledger.load(sid)
        # V8: đưa lại đúng kế hoạch nói dài hạn mà ROOT AGENT đã lập ở turn trước.
        # Runtime chỉ lưu/khôi phục; không tự chọn planned_thread nào để nói.
        context["conversation_speech_plan"] = prior_speech.to_dict()
        if continuation_wake:
            context["continuation_wake"] = dict(continuation_wake)
        else:
            # User turn thật preempt timer cũ, nhưng semantic plan vẫn được giữ
            # nguyên trong snapshot để agent tự đọc và re-plan.
            self.speech_plan_ledger.note_user_turn(sid)

        # Tutor role được chuẩn bị TRƯỚC iteration đầu nếu không có pending answer.
        # Nếu đang chờ câu trả lời cũ, root semantic executive sẽ phân loại relation
        # trước; chỉ relation=answer mới được TutorExecutive chấm thành evidence.
        if continuation_wake:
            # Auto continuation không giả làm user turn mới. Giữ projection tutor
            # hiện tại; nếu tutor đang WAIT_USER thì validation sẽ chặn auto continue.
            tutor_contribution = self.tutor_role._last_contribution  # compatibility-safe internal snapshot
        else:
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
            speech_plan=prior_speech.plan,
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
            if continuation_wake:
                tutor_update = tutor_contribution
            else:
                tutor_update = self.tutor_role.apply_root_decision(
                    decision,
                    user_text=state.user_text,
                    turn_id=turn_id,
                    recent_history=recent_history,
                )
            self.last_tutor_role = tutor_update.to_dict()
            context["tutor_role"] = self.last_tutor_role

            # V7: discourse của iteration mới nhất là snapshot có chủ đích do
            # root executive quyết. Runtime không merge/dedupe/truncate semantic
            # beat vì như vậy runtime sẽ lén trở thành một discourse policy khác.
            merged_discourse = self.director.accept_agent_snapshot(
                state.discourse,
                decision.discourse,
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
                speech_plan=decision.speech_plan,
                progress=max(state.progress, decision.progress),
                uncertainty=min(state.uncertainty, decision.uncertainty),
                stall_count=stall_count,
                decision_summaries=summaries,
            )

            # Runtime chỉ validate disclosure contract. Nếu invalid, agent phải
            # tự re-plan ở iteration kế tiếp; runtime tuyệt đối không chọn/sửa beat.
            disclosure_validation = self.director.validate_agent_plan(
                decision.discourse,
                speech_plan=decision.speech_plan,
                completion_candidate=bool(decision.completion_candidate),
                waiting_for_user=bool(self.last_tutor_role.get("waiting_for_user")),
            )
            if disclosure_validation.valid:
                context.pop("agent_contract_feedback", None)
                context.pop("agent_disclosure_feedback", None)
            else:
                context["agent_contract_feedback"] = {
                    "valid": False,
                    "reason": disclosure_validation.reason,
                    "instruction": "Root executive phải tự sửa disclosure plan; runtime sẽ không sửa thay.",
                }
                # Compatibility key cho V7 tests/callers; cùng một validation result,
                # không phải policy thứ hai.
                context["agent_disclosure_feedback"] = dict(context["agent_contract_feedback"])

            verdict = self.completion_gate.evaluate(state=state, decision=decision, budget=self.budget)
            if (
                not disclosure_validation.valid
                and iteration + 1 < self.budget.hard_iterations
            ):
                verdict = replace(
                    verdict,
                    stop=False,
                    status="running",
                    reason="agent_disclosure_replan",
                )

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

        # V7: public plan là phép chiếu đúng ``say_now`` mà root agent đã quyết.
        # Không voice heuristic, không max-beat heuristic, không tự sinh deferred,
        # không fallback proposition. Nếu agent chọn 3 beat thì writer nhận cả 3.
        # Nếu agent chọn 1 beat thì writer nhận đúng 1.
        public_plan = self.director.project_for_writer(state.discourse)

        # Tutor lifecycle có quyền buộc WAIT, nhưng không có quyền chọn câu/beat.
        # Root executive đã phải tự tạo đúng một public teaching beat khi tutor
        # đang chờ user; validation phía trên sẽ yêu cầu re-plan nếu contract sai.
        if bool(self.last_tutor_role.get("waiting_for_user")):
            public_plan = replace(public_plan, user_response_required=True)
            state = replace(state, status="waiting_user")
            completion_reason = "tutor_requires_user_response"

        state = replace(state, discourse=public_plan)

        # Commit *kế hoạch tiếp tục*, không tự schedule speech. User turn kế tiếp
        # sẽ đọc state này và được quyền steering/replan.
        continuation = state.discourse.continuation
        speech_plan = state.speech_plan
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
            speech_goal=speech_plan.conversation_goal,
            planned_threads=speech_plan.planned_threads,
            next_intent=speech_plan.next_intent,
            continuation_mode=speech_plan.continuation_mode.value,
            resume_reason=speech_plan.resume_trigger,
            plan_status="agent_owned",
        )

        # Persist ĐÚNG snapshot SpeechPlan do executive ở iteration cuối commit.
        # Không merge với plan cũ, không suy diễn từ discourse/voice mode.
        self.speech_plan_ledger.commit_agent_plan(
            sid,
            plan=state.speech_plan,
            turn_id=state.turn_id,
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

    def commit_public_delivery(
        self,
        *,
        successful: bool,
        public_text: str = "",
        turn_id: str = "",
        session_id: str = "",
    ) -> None:
        """Public receipt: wording đã immutable; runtime chỉ ghi delivery lifecycle."""
        self.tutor_role.commit_public_delivery(successful=successful, public_text=public_text)
        sid = str(session_id or self._last_session_id or "default")[:180]
        if successful:
            self.speech_plan_ledger.note_public_delivery(
                sid, turn_id=turn_id, public_text=public_text
            )
            self._awaiting_audio_session_id = sid

    def note_audio_finished(self, *, session_id: str = "") -> SpeechPlanSnapshot:
        """TTS receipt -> schedule/yield đúng mode agent đã chọn, không chọn content."""
        sid = str(session_id or self._awaiting_audio_session_id or self._last_session_id or "default")[:180]
        snap = self.speech_plan_ledger.note_audio_finished(sid)
        self._awaiting_audio_session_id = ""
        return snap

    def speech_plan_snapshot(self, *, session_id: str = "") -> SpeechPlanSnapshot:
        sid = str(session_id or self._last_session_id or "default")[:180]
        return self.speech_plan_ledger.load(sid)

    def prepare_continuation_turn(
        self,
        *,
        session_id: str = "",
        recent_history: Sequence[Mapping[str, Any]] = (),
        runtime_context: Mapping[str, Any] | None = None,
    ) -> AgentTurnResult | None:
        """Wake cơ học -> gọi LẠI root agent; không replay câu hay thread từ runtime."""
        sid = str(session_id or self._last_session_id or "default")[:180]
        token = f"speech-wake:{time.time_ns()}"
        claimed = self.speech_plan_ledger.claim_auto_continue(sid, token=token)
        if claimed is None:
            return None
        try:
            result = self.prepare_turn(
                turn_id=f"speech-cont:{time.time_ns()}",
                user_text="",
                session_id=sid,
                recent_history=recent_history,
                runtime_context=runtime_context or {},
                continuation_wake={
                    "authorized": True,
                    "claim_token": token,
                    "previous_plan": claimed.plan.to_dict(),
                    "previous_public_text": claimed.last_public_text,
                },
            )
            return result
        except Exception:
            self.speech_plan_ledger.release_claim(sid, token=token, retry_seconds=0.75)
            raise

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
            "thread": decision.speech_plan.current_thread or decision.discourse.continuation.active_thread,
            "next_intent": decision.speech_plan.next_intent,
            "continuation_mode": decision.speech_plan.continuation_mode.value,
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


def build_degraded_turn_result(
    *,
    turn_id: str,
    user_text: str,
    session_id: str = "foreground:primary",
    recent_history: Sequence[Mapping[str, Any]] = (),
    runtime_context: Mapping[str, Any] | None = None,
    logger: Any = None,
) -> AgentTurnResult:
    """Deterministic emergency path vẫn giữ *agent-loop contract*.

    Mục đích của hàm này là tránh kiến trúc tụt ngược về ``planner -> writer``
    legacy khi structured worker/router có lỗi. Nó không cố reasoning sâu; chỉ
    tạo một typed one-iteration turn để downstream writer còn bị ràng buộc bởi
    DiscoursePlan và speech budget.
    """
    runtime = TurnAgentRuntime(
        DeterministicFallbackTurnReasoner(),
        budget=LoopBudget(soft_iterations=1, hard_iterations=1, max_wall_seconds=3.0),
        tutor_role=TutorRoleCoordinator(None, logger=logger),
        logger=logger,
    )
    result = runtime.prepare_turn(
        turn_id=turn_id,
        user_text=user_text,
        session_id=session_id,
        recent_history=recent_history,
        runtime_context=runtime_context or {},
    )
    return replace(result, degraded=True, completion_reason="deterministic_agent_fallback")


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

    atomic_store = None
    try:
        from runtime.ai_orchestrated.atomic_state import atomic_store_from_env
        atomic_store = atomic_store_from_env(logger=getattr(host, "logger", None))
    except Exception:
        atomic_store = None

    reasoner: TurnReasoner
    if router is None:
        reasoner = DeterministicFallbackTurnReasoner()
    else:
        reasoner = RuntimeModelTurnReasoner(router, logger=getattr(host, "logger", None))
    runtime = TurnAgentRuntime(
        reasoner,
        arc_ledger=DisclosureArcLedger(
            atomic_store=atomic_store,
            logger=getattr(host, "logger", None),
        ),
        speech_plan_ledger=SpeechPlanLedger(
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


__all__ = ["TurnAgentRuntime", "build_degraded_turn_result", "ensure_agent_turn_runtime"]
