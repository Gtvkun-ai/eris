# -*- coding: utf-8 -*-
"""Đường chạy production của kiến trúc C.

File này cố ý không gọi Ni/Ti/Fe/appraisal/repair legacy trước main model. Những
thứ cần cho continuity đến từ StateReducer, những thứ cần cho sự thật đến từ
grounding/runtime. Main model không phải đi qua một phiên họp trước khi nói.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Mapping

from failure_meta import build_failure_meta
from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.grounding_surface_gate import evaluate_grounded_surface
from runtime.cognition.turn_anchor import anchor_from_semantic_frame
from runtime.social_stance_policy import guard_subjective_stance_payload
from runtime.companion_model_routing import route_companion_turn
from semantic_authority import SemanticAuthorityPolicy

from .contracts import AI_RUNTIME_VERSION, IntentionPlan, StateEvent
from .identity import PendingStrategyUse, PRIMARY_RELATIONSHIP_ID
from .self_turn_pipeline import SelfTurnPipeline
from .startup_grounding import (
    build_startup_fallback_text,
    build_startup_greeting_frame,
    choose_startup_text,
    collect_startup_grounding,
    ensure_grounded_startup_plan,
    select_startup_persona_preset,
)
from .self_context import build_autonomous_self_context


_LOG = logging.getLogger(__name__)


def _orchestrator_boundary_note(host: Any, operation: str, exc: Exception) -> None:
    logger = getattr(host, "logger", None)
    method = getattr(logger, "debug", None)
    if callable(method):
        try:
            method("[ai orchestrator] %s degraded: %s", operation, exc)
            return
        except Exception as log_exc:
            _LOG.debug("AI orchestrator logger failed: %s", log_exc, exc_info=log_exc)
    _LOG.debug("[ai orchestrator] %s degraded: %s", operation, exc, exc_info=exc)



def architecture_c_enabled() -> bool:
    """Cortex V2 là kiến trúc production duy nhất.

    Không còn cờ môi trường để âm thầm quay về legacy pipeline. Bootstrap lỗi
    phải lộ rõ và dừng lượt, thay vì đổi sang một bộ contract nhận thức khác.
    """
    return True


def _runtime_language() -> str:
    """Ngôn ngữ câu public của Main AI.

    Không đọc ``tts.language``: giọng/locale là tầng phát âm, không có quyền đổi
    ngôn ngữ suy nghĩ của Eris. Bản cũ ghép hai contract này nên ``auto`` ở Body
    bị chuẩn hóa thành ``ja`` và startup đột nhiên nói tiếng Nhật.
    """
    try:
        from runtime.runtime_settings_store import runtime_text
        raw = str(runtime_text("chat", "language", default="vi") or "vi").strip().lower()
    except Exception:
        raw = "vi"
    aliases = {
        "": "vi", "auto": "vi", "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "jp": "ja", "ja-jp": "ja", "japanese": "ja",
        "en-us": "en", "english": "en",
    }
    language = aliases.get(raw, raw)
    return language if language in {"vi", "ja", "en"} else "vi"


def _next_ai_turn_seq(host: Any, *, fallback: int = 1) -> int:
    lock = getattr(host, "_ai_turn_seq_lock", None)
    if lock is None:
        return max(1, int(fallback or 1))
    with lock:
        host._ai_turn_seq = max(
            int(getattr(host, "_ai_turn_seq", 0) or 0),
            int(host.ai_state_reducer.snapshot().last_applied_turn_seq or 0),
        ) + 1
        return int(host._ai_turn_seq)


def _typed_startup_persona_plan(*, reason: str = "typed_persona_startup") -> IntentionPlan:
    return IntentionPlan.from_mapping(
        {
            "speak": True,
            "motive": "startup_opening",
            "strategy": "persona_opening",
            "value_focus": "warm_relational_presence",
            "topic": "Offer one ordinary, warm-guarded opening with a small dry edge; no manifesto.",
            "importance": 0.72,
            "intrusion_risk": 0.05,
            "confidence": 0.74,
            "performance_hint": "soft",
            "evidence_refs": [],
            "semantics": {
                "turn_kind": "startup",
                "speech_act": "warm_session_opening",
                "subject_key": "session_arrival",
                "evidence_scope": "persona",
                "continuation_key": "none",
            },
            "notes": reason,
        },
        channel="startup",
    )


def _submit_local_startup_plan(host: Any, plan: IntentionPlan, *, turn_seq: int) -> None:
    reducer = getattr(host, "ai_state_reducer", None)
    if reducer is None or not callable(getattr(reducer, "submit", None)):
        return
    try:
        snapshot = reducer.snapshot() if callable(getattr(reducer, "snapshot", None)) else None
        base_version = int(getattr(snapshot, "version", 0) or 0)
        reducer.submit(
            StateEvent.from_intention(
                plan,
                turn_seq=turn_seq,
                base_version=base_version,
            )
        )
    except Exception as exc:
        _orchestrator_boundary_note(host, "startup_plan.submit", exc)


class _StaticIntentionPlanner:
    def __init__(self, plan: IntentionPlan) -> None:
        self.plan = plan

    def plan_autonomous(self, _snapshot: Mapping[str, Any], *, turn_seq: int = 0) -> IntentionPlan:
        return self.plan



class AIChatOrchestrator:
    def __init__(self, host: Any) -> None:
        self.host = host

    def run(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn: Any | None = None,
        speech_interrupt_context: str = "",
        speech_interrupt_event: Any | None = None,
        speech_interrupt_reaction: Any | None = None,
    ) -> None:
        # PDF annotation, pages 7 and 19-20: a user turn is a cancellation
        # scope. Entering it preempts queued optional lanes and prevents new
        # background requests from competing with the public reply.
        from runtime.inference_broker import GLOBAL_INFERENCE_BROKER

        scope = f"user_turn:{int(float(cycle_start) * 1000)}:{id(self):x}"
        with GLOBAL_INFERENCE_BROKER.user_turn(scope):
            result = self._run_unscoped(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
                speech_interrupt_context=speech_interrupt_context,
                speech_interrupt_event=speech_interrupt_event,
                speech_interrupt_reaction=speech_interrupt_reaction,
            )
            frame = dict(getattr(self.host, "last_semantic_frame", {}) or {})
            act = str(frame.get("user_act", "") or "").strip().lower()
            category = (
                "small_talk"
                if act in {
                    "greeting",
                    "acknowledgement",
                    "relational_check_in",
                    "closeness_bid",
                    "repair_request",
                }
                else "tool_or_action"
                if str(frame.get("tool_intent", "none") or "none").strip().lower() not in {"", "none"}
                else "general_chat"
                if frame
                else "unknown"
            )
            GLOBAL_INFERENCE_BROKER.set_user_turn_category(scope, category)
            return result

    def _run_unscoped(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn: Any | None = None,
        speech_interrupt_context: str = "",
        speech_interrupt_event: Any | None = None,
        speech_interrupt_reaction: Any | None = None,
    ) -> None:
        host = self.host
        # Avoid carrying a previous turn's semantic category into telemetry when
        # the current authority call fails before producing a frame.
        host.last_semantic_frame = {}
        semantic_policy = SemanticAuthorityPolicy.from_env()
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        telemetry_payload = (
            snapshot.to_machine_context()
            if callable(getattr(snapshot, "to_machine_context", None))
            else {}
        )
        engagement_runtime = getattr(host, "ai_engagement_runtime", None)
        engagement_context: dict[str, Any] = {"active": False}
        engagement_prompt_context = "active_engagement: none"
        if engagement_runtime is not None:
            try:
                active_app = str(telemetry_payload.get("active_app", "") or "").strip()
                active_title = str(
                    telemetry_payload.get("active_window_title", "")
                    or telemetry_payload.get("window_title", "")
                    or ""
                ).strip()
                engagement_runtime.observe_user_message(
                    user_text,
                    now=cycle_start,
                    binding={"app": active_app, "window_title": active_title},
                )
                engagement_context = engagement_runtime.planner_context(now=cycle_start)
                engagement_prompt_context = engagement_runtime.prompt_context(now=cycle_start)
            except Exception as exc:
                host.logger.debug("[engagement] chat observation failed: %s", exc)

        user_meta: dict[str, Any] = {
            "channel": "chat",
            "architecture": AI_RUNTIME_VERSION,
            "cognitive_observation_pending": True,
        }
        if speech_interrupt_event is not None and callable(getattr(speech_interrupt_event, "to_meta", None)):
            user_meta["speech_interrupt"] = speech_interrupt_event.to_meta()
        if speech_interrupt_reaction is not None and callable(getattr(speech_interrupt_reaction, "to_meta", None)):
            user_meta["speech_interrupt_reaction"] = speech_interrupt_reaction.to_meta()
        user_turn = host._ensure_session_turn_ledger().record_user(
            user_text,
            timestamp=cycle_start,
            meta=user_meta,
        )
        turn_seq = _next_ai_turn_seq(
            host,
            fallback=max(1, int(getattr(user_turn, "index", 0) or 0)),
        )
        turn_id = str(getattr(user_turn, "turn_id", "") or f"session_turn:{turn_seq}")
        user_meta["ai_turn_seq"] = turn_seq

        # Grounding quyết định nguồn sự thật, không quyết định cảm xúc hay wording.
        pre_grounding = host._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=None,
            screen_image_data_uri="",
        )
        host.last_grounding_context = pre_grounding
        if pre_grounding is not None and not bool(getattr(pre_grounding, "memory_answer_allowed", True)):
            host.long_term_memory = []
            memory_resonance = None
            memory_context = host._filter_memory_context_for_grounding("")
            host.active_memory_resonance = None
        else:
            host.long_term_memory = host._memory_recall_texts(snapshot=snapshot)
            memory_resonance = host._recall_memory_resonance(
                snapshot=snapshot,
                user_text=user_text,
                channel="chat",
                fragments=tuple(host._chat_history_for_llm(limit=2)) if host.chat_history else (),
            )
            memory_context = host._build_memory_context(snapshot, memory_resonance=memory_resonance)

        host.chat_mode = True
        host._chat_last_activity_at = time.time()
        host.logger.info("Người dùng: %s", user_text)
        prior_public_history = tuple(host._chat_history_for_llm(limit=16))
        if previous_public_context and not prior_public_history:
            prior_public_history = ({"role": "assistant", "content": previous_public_context},)
        host._append_chat_history("user", user_text)

        host._chat_snapshot_for_vision = snapshot
        try:
            screen_image_data_uri = host._capture_screen_frame_for_chat(
                user_text,
                previous_public_turn=previous_public_turn,
            )
        finally:
            host._chat_snapshot_for_vision = None
        grounding_report = host._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=memory_resonance,
            screen_image_data_uri=screen_image_data_uri,
        )
        host.last_grounding_context = grounding_report
        if grounding_report is not None and not bool(getattr(grounding_report, "memory_answer_allowed", True)):
            memory_context = host._filter_memory_context_for_grounding(memory_context)
        try:
            host._log_chat_source_grounding(grounding_report)
        except Exception as exc:
            _orchestrator_boundary_note(host, "chat_grounding.log", exc)

        # Đảm bảo pending strategy của lượt trước đã vào single-writer trước khi
        # observer dùng phản ứng user hiện tại để chấm hậu quả.
        host.ai_state_reducer.wait_idle(0.15)
        mind_state = host.ai_state_reducer.snapshot()

        # Continuity của phiên phải được xét trước profile memory. Nếu không, câu
        # "tôi vừa nói gì" có thể bị embedding kéo nhầm về user.name, đúng kiểu
        # tìm rất thông minh nhưng tìm sai căn nhà.
        deterministic_decision = None
        deterministic_source = ""
        build_continuity = getattr(host, "_build_conversation_continuity_decision", None)
        if callable(build_continuity):
            try:
                deterministic_decision = build_continuity(user_text)
                if deterministic_decision is not None:
                    deterministic_source = "conversation_continuity"
            except Exception as exc:
                host.logger.debug("[conversation continuity] deterministic answer failed: %s", exc)

        if deterministic_decision is None and (
            grounding_report is None or bool(getattr(grounding_report, "memory_answer_allowed", True))
        ):
            build_memory_recall = getattr(host, "_build_memory_recall_decision", None)
            if callable(build_memory_recall):
                try:
                    deterministic_decision = build_memory_recall(user_text)
                    if deterministic_decision is not None:
                        deterministic_source = "memory_recall"
                except Exception as exc:
                    host.logger.debug("[memory recall] deterministic answer failed: %s", exc)

        if deterministic_decision is not None:
            user_meta[f"{deterministic_source}_answer"] = True
            host.logger.info(
                "[%s] deterministic answer parse_mode=%s",
                deterministic_source.replace("_", " "),
                str(getattr(deterministic_decision, "parse_mode", "") or deterministic_source),
            )
            host.ai_stage_planner.apply(deterministic_decision, "neutral", state=mind_state, channel="chat")
            deterministic_decision = host._execute_system_action(deterministic_decision, snapshot=snapshot, frame=None)
            public_text, assistant_meta = self._commit(deterministic_decision)
            host.last_user_text_for_semantics = user_text
            recent_history = tuple(host._chat_history_for_llm(limit=8))
            host.ai_post_turn_observer.submit(
                turn_id=turn_id,
                turn_seq=turn_seq,
                user_text=user_text,
                assistant_text=public_text,
                recent_history=recent_history,
                mechanical_outcomes=[],
                state_summary=mind_state.to_dict(),
                user_meta=user_meta,
                assistant_meta=assistant_meta,
                event_kind="chat",
            )
            return

        personality_context = mind_state.personality_prompt_context()
        relationship_context = mind_state.relationship.prompt_summary()
        grounding_context = str(getattr(grounding_report, "prompt_context", "") or "")
        # PDF annotation, pages 12-13 and 20: P2 cleanup removed the legacy
        # discourse/semantic committee entirely. ``semantic_frame.v1`` from the
        # public writer is the only conversational meaning object.
        user_meta["semantic_authority"] = "semantic_frame.v1"
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        discovery_context = (
            discovery_runtime.planner_context(telemetry_payload)
            if discovery_runtime is not None
            else {}
        )
        planning_snapshot = {
            "event_kind": "chat",
            "user_text": user_text,
            "recent_public_history": host._chat_history_for_llm(limit=8)[:-1],
            "personality_summary": personality_context,
            "identity": mind_state.identity.panel_view(),
            "identity_summary": mind_state.identity_prompt_context(),
            "relationship_summary": relationship_context,
            "grounding_context": grounding_context,
            "memory_available": bool(str(memory_context or "").strip()),
            "interrupt_context": speech_interrupt_context,
            "discovery": discovery_context,
            "engagement_context": engagement_context,
        }
        chat_plan = host.ai_intention_planner.plan_chat(
            planning_snapshot,
            turn_seq=turn_seq,
        )
        discovery_id = ""
        if discovery_runtime is not None:
            chat_plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(chat_plan)
            if discovery_grounding:
                grounding_context = "\n".join(part for part in (grounding_context, discovery_grounding) if part)
            elif str(getattr(chat_plan, "strategy", "") or "").strip().lower() == "share_discovery":
                data = chat_plan.to_dict()
                data.update({
                    "strategy": "direct_answer",
                    "topic": (
                        "Answer honestly that no verified discovery is ready yet, or use a real current activity if present. "
                        "Do not invent a fact merely because the user asked for something interesting."
                    ),
                    "evidence_refs": [],
                })
                chat_plan = IntentionPlan.from_mapping(data, channel="chat")
        user_message = host.parser.build_chat_user_message(
            user_message=user_text,
            last_chat_answer=host.last_chat_answer,
        )
        history = host._chat_history_for_llm(limit=16)[:-1]
        route_decision = route_companion_turn(user_text, recent_history=history)
        use_escalation = route_decision.use_pro
        reasoning_effort = route_decision.reasoning_effort
        thinking_mode = route_decision.thinking_mode
        routing_context = route_decision.prompt_context()
        host.last_companion_model_route = route_decision.to_dict()
        payload: dict[str, Any] = {}
        host._set_background_memory_digest_remote_inflight(True)
        try:
            payload = host.ai_model_router.generate_public_reply(
                chat_history=history,
                user_text=user_message,
                memory_context=memory_context,
                grounding_context=grounding_context,
                relationship_context=relationship_context,
                personality_context=personality_context,
                interrupt_context=speech_interrupt_context,
                engagement_context=engagement_prompt_context,
                routing_context=routing_context,
                use_escalation=use_escalation,
                reasoning_effort=reasoning_effort,
                thinking_mode=thinking_mode,
                allow_fallback=False,
                language_hint=_runtime_language(),
                planned_intention=chat_plan,
            )
            if not payload and not no_fallback_mode_enabled():
                payload = host.ai_model_router.generate_public_reply(
                    chat_history=history,
                    user_text=user_message,
                    memory_context=memory_context,
                    grounding_context=grounding_context,
                    relationship_context=relationship_context,
                    personality_context=personality_context,
                    interrupt_context=speech_interrupt_context,
                    engagement_context=engagement_prompt_context,
                    routing_context=routing_context,
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    thinking_mode=thinking_mode,
                    allow_fallback=True,
                    language_hint=_runtime_language(),
                    planned_intention=chat_plan,
                    )
        finally:
            host._set_background_memory_digest_remote_inflight(False)

        if payload:
            payload = guard_subjective_stance_payload(payload)
            semantic_frame = dict(payload.get("semantic_frame", {}) or {})
            if semantic_frame:
                host.last_semantic_frame = semantic_frame
                user_meta["semantic_frame"] = semantic_frame
                try:
                    from runtime.observability import GLOBAL_OBSERVABILITY
                    GLOBAL_OBSERVABILITY.log(
                        "semantic_frame_v1",
                        tags={
                            "user_act": str(semantic_frame.get("user_act", "unknown") or "unknown"),
                            "target": str(semantic_frame.get("target", "unknown") or "unknown"),
                            "relation": str(semantic_frame.get("discourse_relation", "unknown") or "unknown"),
                        },
                        fields={"turn_seq": turn_seq, "frame": semantic_frame},
                    )
                except Exception as exc:
                    _orchestrator_boundary_note(host, "semantic_frame.observability", exc)
            draft_text = str(payload.get("text", "") or "")
            grounding_engine = getattr(host, "source_grounding_engine", None)
            grounding_verdict = evaluate_grounded_surface(
                grounding_engine, draft_text, report=grounding_report
            )
            grounding_annotations = grounding_verdict.annotations
            if not grounding_verdict.allowed:
                violation_codes = ["UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM"]
                host.logger.warning(
                    "[cortex v2 gate] turn=%s violations=%s; retrying public writer once",
                    turn_seq,
                    ",".join(violation_codes),
                )
                retry_instruction = grounding_verdict.retry_instruction()
                host._set_background_memory_digest_remote_inflight(True)
                try:
                    retried = host.ai_model_router.generate_public_reply(
                        chat_history=history,
                        user_text=user_message,
                        memory_context=memory_context,
                        grounding_context=grounding_context,
                        relationship_context=relationship_context,
                        personality_context=personality_context,
                        interrupt_context=speech_interrupt_context,
                        engagement_context=engagement_prompt_context,
                        routing_context=routing_context,
                        use_escalation=use_escalation,
                        reasoning_effort=reasoning_effort,
                        thinking_mode=thinking_mode,
                        allow_fallback=not no_fallback_mode_enabled(),
                        language_hint=_runtime_language(),
                        planned_intention=chat_plan,
                                retry_instruction=retry_instruction,
                        # PDF annotation, page 13: wording retry is forbidden
                        # from reinterpreting discourse/meaning.  The validated
                        # frame from the first authority call is immutable.
                        locked_semantic_frame=payload.get("semantic_frame", {}),
                    )
                finally:
                    host._set_background_memory_digest_remote_inflight(False)
                if retried:
                    retry_grounding_verdict = evaluate_grounded_surface(
                        grounding_engine, str(retried.get("text", "") or ""), report=grounding_report
                    )
                    retry_grounding = retry_grounding_verdict.annotations
                    if retry_grounding_verdict.allowed:
                        payload = retried
                    else:
                        retry_codes = ["UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM"] if retry_grounding else []
                        host.logger.warning(
                            "[cortex v2 gate] retry still invalid turn=%s violations=%s; suppressing unsafe surface",
                            turn_seq,
                            ",".join(retry_codes),
                        )
                        payload = {}
                else:
                    payload = {}


        if not payload:
            # Repair request ngắn không được biến thành im lặng. Adapter chỉ dùng
            # session ledger và không bịa nội dung; nếu không đủ bằng chứng nó
            # nhắc lại đúng câu user đang muốn làm rõ.
            repair_fallback = ""
            build_repair_fallback = getattr(host, "_conversation_repair_fallback_text", None)
            if callable(build_repair_fallback):
                try:
                    repair_fallback = str(build_repair_fallback(user_text) or "").strip()
                except Exception as exc:
                    host.logger.debug("[conversation repair] fallback failed: %s", exc)
            fallback_payload = {
                "text": repair_fallback,
                "should_speak": bool(repair_fallback),
                "animation": "stand",
                "next_animation": "",
                "direction": 0,
                "target_x": -1.0,
                "bounce_action": "",
                "system_action": "",
                "action_input": "",
                "delivery_hint": "",
                "nonverbal_cue": "",
                "stage_motion": "",
                "performance_hint": "neutral",
            }
            decision = host.parser.parse(
                json.dumps(fallback_payload, ensure_ascii=False),
                user_hint=user_text,
            )
            decision.parse_mode = "conversation_repair_fallback" if repair_fallback else "ai_runtime_format_block"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="ai_chat_orchestrator",
                origin="main_model",
                public_surface="repair_fallback" if repair_fallback else "silent",
                recoverable=bool(repair_fallback),
            )
        else:
            raw = json.dumps(payload, ensure_ascii=False)
            host._log_raw_llm_output("chat_ai", raw)
            decision = host.parser.parse(raw, user_hint=user_text)

        # Main model chỉ nêu hint; StagePlanner làm phần cơ học. Legacy stage fields
        # vẫn được chấp nhận để không làm frontend gãy, nhưng không cần thiết.
        hint = str(getattr(decision, "performance_hint", "") or "").strip().lower()
        if not hint or hint == "neutral":
            hint = str(getattr(chat_plan, "performance_hint", "") or "neutral")
        host.ai_stage_planner.apply(decision, hint, state=mind_state, channel="chat")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        public_text, assistant_meta = self._commit(decision)
        if public_text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, public_text)
        host.last_user_text_for_semantics = user_text

        if public_text and chat_plan.strategy:
            pending_strategy = PendingStrategyUse(
                strategy_use_id=f"strategy:{turn_id}",
                turn_seq=turn_seq,
                strategy=chat_plan.strategy,
                goal=chat_plan.topic,
                context=tuple(
                    item
                    for item in (chat_plan.motive, chat_plan.value_focus, "chat")
                    if str(item or "").strip()
                ),
                assistant_text=public_text,
                relationship_scope=PRIMARY_RELATIONSHIP_ID,
            )
            host.ai_state_reducer.submit(
                StateEvent.from_pending_strategy(
                    pending_strategy,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )

        mechanical: list[Mapping[str, Any]] = []
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            action_outcome = dict(decision.action_result_meta)
            mechanical.append(action_outcome)
            host.ai_state_reducer.submit(
                StateEvent.from_mechanical_outcome(
                    action_outcome,
                    turn_seq=turn_seq,
                    turn_id=turn_id,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        recent_history = tuple(host._chat_history_for_llm(limit=8))
        observer_state = mind_state.to_dict()
        # PDF annotation, pages 12-13 and 20: post-turn analysis receives the
        # same validated semantic authority frame instead of rebuilding meaning
        # through the retired discourse/social regex stack.
        observer_state["semantic_frame"] = dict(user_meta.get("semantic_frame", {}) or {})
        host.ai_post_turn_observer.submit(
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=public_text,
            recent_history=recent_history,
            mechanical_outcomes=mechanical,
            state_summary=observer_state,
            user_meta=user_meta,
            assistant_meta=assistant_meta,
            event_kind="chat",
        )

    def _commit(self, decision: Any) -> tuple[str, dict[str, Any] | None]:
        host = self.host
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(decision.text)
            public_text = surfaces.display_text
            memory_text = surfaces.memory_text
        except Exception:
            public_text = str(getattr(decision, "text", "") or "").strip()
            memory_text = public_text
        decision.text = public_text
        if public_text:
            engagement_runtime = getattr(host, "ai_engagement_runtime", None)
            if engagement_runtime is not None:
                try:
                    engagement_runtime.observe_assistant_output(public_text, now=time.time())
                except Exception as exc:
                    host.logger.debug("[engagement] assistant output observation failed: %s", exc)
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception as exc:
            _orchestrator_boundary_note(host, "chat_surface.seal", exc)

        host.last_chat_answer = public_text
        host.last_system_action = str(getattr(decision, "system_action", "") or "")
        clock = getattr(host, "interaction_clock", None)
        if clock is not None and public_text:
            clock.mark_assistant_text()
            # PDF annotation, pages 17-18: time-to-first-visible-text is a
            # first-class load-test metric, not something reconstructed from
            # screenshots after the fact.
            try:
                started_at = float(getattr(clock, "generation_started_at", 0.0) or 0.0)
                if started_at > 0.0:
                    from runtime.observability import GLOBAL_OBSERVABILITY

                    frame = dict(getattr(host, "last_semantic_frame", {}) or {})
                    act = str(frame.get("user_act", "") or "").strip().lower()
                    category = (
                        "small_talk"
                        if act in {
                            "greeting",
                            "acknowledgement",
                            "relational_check_in",
                            "closeness_bid",
                            "repair_request",
                        }
                        else "general_chat"
                    )
                    GLOBAL_OBSERVABILITY.observe(
                        "ttft_ms",
                        max(0.0, (time.time() - started_at) * 1000.0),
                        tags={"channel": "chat", "turn_category": category},
                    )
            except Exception as exc:
                _orchestrator_boundary_note(host, "chat_ttft.observe", exc)
        if memory_text:
            host._append_chat_history("assistant", memory_text, invalid=False)
        assistant_meta: dict[str, Any] | None = None
        if bool(getattr(decision, "should_speak", False)) and public_text:
            assistant_meta = {
                "architecture": AI_RUNTIME_VERSION,
                "system_action": host.last_system_action,
                "parse_mode": str(getattr(decision, "parse_mode", "") or "json"),
            }
            host._ensure_session_turn_ledger().record_assistant(public_text, meta=assistant_meta)
        if len(host.chat_history) > 32:
            host.chat_history = host.chat_history[-32:]
        host._apply_position_update(decision)
        if public_text or str(getattr(decision, "system_action", "") or "").strip():
            host._send_decision_to_body(decision, channel="chat")
        if public_text:
            host.logger.info("ERIS: %s", public_text)
        else:
            host.logger.info("[cortex v2 gate] public surface suppressed without canned fallback")
        return public_text, assistant_meta


class AIAutonomousOrchestrator:
    def __init__(self, host: Any) -> None:
        self.host = host
        self._last_body_only_at = 0.0
        self._last_body_only_signature = ""
        self.self_turn_pipeline = SelfTurnPipeline(
            host,
            next_turn_seq=_next_ai_turn_seq,
            commit_public=self._commit_public,
            emit_body_only=self._emit_body_only,
        )
        # Alias chỉ để panel/test adapter cũ truy cập trace. Logic production nằm
        # trong SelfTurnPipeline, không còn phình ở orchestrator facade.
        self.trace_store = self.self_turn_pipeline.trace_store

    def _commit_public(self, decision: Any, *, channel: str, turn_seq: int) -> tuple[str, dict[str, Any] | None]:
        """Commit một public turn autonomous vào cùng lịch sử/ledger với chat.

        Planner và observer có thể thông minh đến đâu cũng vô ích nếu câu public
        không được ghi vào continuity. Hàm này chỉ vận chuyển surface, không viết
        lại lời model.
        """
        host = self.host
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(str(getattr(decision, "text", "") or ""))
            public_text = surfaces.display_text
            memory_text = surfaces.memory_text
        except Exception:
            public_text = str(getattr(decision, "text", "") or "").strip()
            memory_text = public_text
        decision.text = public_text
        if public_text:
            engagement_runtime = getattr(host, "ai_engagement_runtime", None)
            if engagement_runtime is not None:
                try:
                    engagement_runtime.observe_assistant_output(public_text, now=time.time())
                except Exception as exc:
                    host.logger.debug("[engagement] autonomous output observation failed: %s", exc)
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception as exc:
            _orchestrator_boundary_note(host, "autonomous_surface.seal", exc)
        if not public_text:
            return "", None
        host.last_text = public_text
        # Startup/autonomous là public assistant turn thật, không phải hiệu ứng
        # trang trí. Giữ cùng con trỏ gần nhất với chat để câu user kế tiếp có
        # thể hỏi "ý câu vừa rồi là gì" mà không bị Eris giả mất trí nhớ.
        host.last_chat_answer = public_text
        clock = getattr(host, "interaction_clock", None)
        if clock is not None:
            try:
                clock.mark_assistant_text()
            except Exception as exc:
                _orchestrator_boundary_note(host, "autonomous_clock.mark", exc)
        if memory_text:
            host._append_chat_history("assistant", memory_text, invalid=False)
            if len(host.chat_history) > 32:
                host.chat_history = host.chat_history[-32:]
        meta = {
            "architecture": AI_RUNTIME_VERSION,
            "channel": channel,
            "ai_turn_seq": int(turn_seq),
            "system_action": str(getattr(decision, "system_action", "") or ""),
        }
        try:
            host._ensure_session_turn_ledger().record_assistant(public_text, meta=meta)
        except Exception:
            meta = None
        host._apply_position_update(decision)
        host._send_decision_to_body(decision, channel=channel)
        return public_text, meta

    def _emit_body_only(
        self,
        *,
        reason: str,
        activity_kind: str = "unknown",
        motion_hint: str = "",
        turn_seq: int,
        signature: str = "",
    ) -> bool:
        """Phát hiện diện phi ngôn ngữ sau deliberation của main planner.

        ``activity_kind`` chỉ là annotation typed từ planner. Motion lấy từ
        ``performance_hint``; runtime không phân loại game/code/media.
        """
        host = self.host
        now = time.time()
        signature = str(signature or f"{reason}:{motion_hint}")[:200]
        if now - self._last_body_only_at < 24.0 or (signature and signature == self._last_body_only_signature):
            return False
        try:
            from domain.decision import Decision
            hint = str(motion_hint or "").strip().lower()
            motion = {
                "focus": "focus",
                "curious": "tilt_head",
                "thinking": "blink_slow",
                "quiet_presence": "look_aside",
                "soft": "lean_in_small",
            }.get(hint, "tilt_head")
            decision = Decision(
                text="", animation="stand", should_speak=False, confidence=0.82,
                performance_hint="quiet_presence", stage_motion=motion, motion_intent=motion,
                nonverbal_cue="small_presence", debug_trace=f"body_only:{reason}",
            )
            host._send_decision_to_body(decision, channel="autonomous")
            self._last_body_only_at = now
            self._last_body_only_signature = signature
            self.trace_store.append("body_only", {
                "turn_seq": turn_seq, "activity_kind": activity_kind, "reason": reason,
                "motion_hint": hint, "result": "emitted", "body_only": True,
            }, now=now)
            return True
        except Exception as exc:
            _orchestrator_boundary_note(host, "body_only.emit", exc)
            return False

    def run_startup(self) -> bool:
        host = self.host
        try:
            from runtime.runtime_settings_store import runtime_bool
            enabled = runtime_bool("architecture", "startup_greeting", default=True)
        except Exception:
            enabled = str(os.getenv("ERIS_AI_STARTUP_GREETING_ENABLED", "1") or "1").strip().lower() in {
                "1", "true", "yes", "on",
            }
        if not enabled or bool(getattr(host, "_ai_startup_ran", False)):
            return False
        host._ai_startup_ran = True

        # UIA/OCR phải chạy trước câu mở đầu. Bản cũ chào xong mới start worker,
        # tức là Eris bị buộc phải "có chất riêng" trong khi mắt còn nhắm.
        startup_grounding = collect_startup_grounding(host)
        host.logger.info(
            "[architecture C startup grounding] direct=%s strong=%s telemetry_tab=%s evidence=%s runtime_opening=%s metadata=%s backend=%s wait=%.2fs notes=%s",
            int(startup_grounding.has_direct_screen_evidence),
            int(startup_grounding.has_strong_opening_anchor),
            int(startup_grounding.telemetry_surface_visible),
            len(startup_grounding.evidence),
            len(startup_grounding.runtime_opening_evidence),
            len(startup_grounding.runtime_metadata),
            startup_grounding.backend or "unknown",
            startup_grounding.waited_seconds,
            ",".join(startup_grounding.notes) or "none",
        )
        # Greeting chắc chắn không có nghĩa là chen lên tiếng user. Nếu chat đã
        # bắt đầu trong lúc prime UIA/OCR, nhường lượt này và để chat sở hữu loa.
        if bool(getattr(host, "chat_mode", False)) or bool(getattr(host, "_chat_processing", False)):
            host.logger.info("[architecture C startup] preempted_by_chat")
            return False

        state = host.ai_state_reducer.snapshot()
        recent_history = host._chat_history_for_llm(limit=4)
        greeting_frame = build_startup_greeting_frame(host, state, startup_grounding)
        latest_observation = dict(state.latest_observation)
        relationship_payload = state.relationship.to_dict()
        relationship_summary = state.relationship.prompt_summary()
        continuity_anchor = bool(
            tuple(state.open_loops)
            or recent_history
            or str(latest_observation.get("open_loop", "") or "").strip()
            or relationship_summary
        )
        turn_seq = _next_ai_turn_seq(host)
        try:
            from runtime.runtime_settings_store import runtime_bool
            force_startup_speech = runtime_bool("architecture", "startup_force_speak", default=True)
        except Exception:
            force_startup_speech = str(os.getenv("ERIS_AI_STARTUP_FORCE_SPEAK", "1") or "1").strip().lower() in {
                "1", "true", "yes", "on",
            }
        snapshot = {
            "event_kind": "startup",
            "startup_opening_required": bool(force_startup_speech),
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": latest_observation,
            "recent_public_history": recent_history,
            "startup_screen_evidence": startup_grounding.planner_context(),
            "instruction": (
                "Choose one short opening through this cascade: current OCR/UIA evidence, meaningful runtime signal, "
                "real continuity/memory, then personality-led presence. Startup does not require external evidence to speak. "
                "A low-risk inference is allowed only as a hypothesis with an explicit basis and room for correction. "
                "The opening must be self-contained: every phrase such as 'the real part', 'the rest', 'that thing', or 'what matters' "
                "must name its referent inside the same sentence. "
                "Never invent that the user plans to start, change, fix, or feel something. Do not report restore state "
                "or memory machinery."
            ),
        }
        startup_planner = getattr(host, "ai_intention_planner", None)
        skip_empty_startup_planner = bool(
            force_startup_speech
            and not startup_grounding.has_direct_screen_evidence
            and not startup_grounding.has_runtime_opening_anchor
            and not continuity_anchor
        )
        if skip_empty_startup_planner:
            host.logger.info("[architecture C startup] planner skipped; using typed persona plan reason=no_opening_anchor")
            local_plan = _typed_startup_persona_plan(reason="empty_startup_skipped_planner")
            _submit_local_startup_plan(host, local_plan, turn_seq=turn_seq)
            startup_planner = _StaticIntentionPlanner(local_plan)
        try:
            plan = startup_planner.plan_autonomous(
                snapshot,
                turn_seq=turn_seq,
            )
        except Exception as exc:
            # Startup presence không được chết chỉ vì planner/provider vừa thức
            # dậy chậm hơn phần còn lại của runtime.
            host.logger.warning("[architecture C startup] planner failed; using typed persona plan: %s", exc)
            plan = IntentionPlan.from_mapping(
                {
                    "speak": True,
                    "motive": "startup_opening",
                    "strategy": "persona_opening",
                    "value_focus": "warm_relational_presence",
                    "topic": "Offer one ordinary, warm-guarded opening with a small dry edge; no manifesto.",
                    "importance": 0.72,
                    "intrusion_risk": 0.05,
                    "confidence": 0.74,
                    "performance_hint": "soft",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "startup",
                        "speech_act": "warm_session_opening",
                        "subject_key": "session_arrival",
                        "evidence_scope": "persona",
                        "continuation_key": "none",
                    },
                },
                channel="startup",
            )
        try:
            from runtime.runtime_settings_store import runtime_bool
            force_screen_opening = runtime_bool("architecture", "startup_screen_opening", default=True)
        except Exception:
            force_screen_opening = str(os.getenv("ERIS_AI_STARTUP_SCREEN_OPENING", "1") or "1").strip().lower() in {
                "1", "true", "yes", "on",
            }
        plan = ensure_grounded_startup_plan(
            plan,
            startup_grounding,
            force_screen_opening=force_screen_opening,
            force_startup_speech=force_startup_speech,
            has_continuity_anchor=continuity_anchor,
        )
        host.logger.info(
            "[architecture C startup route] strategy=%s source=%s continuity=%s forced=%s",
            plan.strategy or "none",
            startup_grounding.opening_source,
            int(continuity_anchor),
            int(force_startup_speech),
        )
        if not (plan.speak and plan.confidence >= 0.56 and plan.importance >= 0.42):
            host.logger.info(
                "[architecture C startup] silence motive=%s conf=%.2f importance=%.2f",
                plan.motive,
                plan.confidence,
                plan.importance,
            )
            return False

        continuity_context = {
            "relationship": relationship_summary,
            "open_loops": list(state.open_loops)[:3],
            "latest_observation": latest_observation,
            "contract": (
                "Use only a real continuity item. Do not mention memory systems, restored state, or infer a fresh user action."
            ),
        }
        language = _runtime_language()
        avoid_text = str(getattr(host, "last_text", "") or "")
        payload = None
        if plan.strategy == "persona_opening":
            payload = select_startup_persona_preset(greeting_frame, avoid_text=avoid_text)
            if payload:
                host.logger.info(
                    "[architecture C startup greeting] source=preset id=%s situation=%s",
                    str(payload.get("preset_id", "") or "none"),
                    str(getattr(greeting_frame, "situation", "unknown") or "unknown"),
                )
        if not payload:
            payload = host.ai_model_router.generate_autonomous_reply(
                plan=plan,
                personality_context=(
                    f"{state.personality_prompt_context()}\n\n"
                    f"{greeting_frame.to_prompt_block()}"
                ),
                memory_context=json.dumps(continuity_context, ensure_ascii=False),
                grounding_context=(
                    f"{startup_grounding.prompt_context()}\n\n"
                    "STARTUP_WORDING_CONTRACT:\n"
                    "- GreetingFrame is the encounter model, not public text.\n"
                    "- Prefer ordinary spoken Vietnamese over slogans or philosophical declarations.\n"
                    "- Do not explain your role, availability, standards, principles, or abstract worldview."
                ),
                recent_history=recent_history,
                avoid_text=avoid_text,
                allow_fallback=not no_fallback_mode_enabled(),
                language_hint=language,
            )
            if payload and plan.strategy in {"persona_opening", "continuity_opening"}:
                selected_text, quality = choose_startup_text(
                    str(payload.get("text", "") or ""),
                    greeting_frame,
                    avoid_text=avoid_text,
                )
                payload["text"] = selected_text
                host.logger.info(
                    "[architecture C startup greeting] source=model score=%.3f accepted=%s reasons=%s situation=%s",
                    float(quality.get("score", 0.0) or 0.0),
                    int(bool(quality.get("accepted", False))),
                    ",".join(str(item) for item in (quality.get("reasons", ()) or ())) or "none",
                    str(getattr(greeting_frame, "situation", "unknown") or "unknown"),
                )
        if not payload:
            fallback_text = build_startup_fallback_text(
                open_loops=state.open_loops,
                latest_observation=latest_observation,
                relationship=relationship_payload,
                avoid_text=avoid_text,
                language=language,
            )
            payload = {
                "text": fallback_text,
                "should_speak": True,
                "performance_hint": "dry_tease",
            }
            host.logger.warning(
                "[architecture C startup] main reply unavailable; used personality fallback strategy=%s",
                plan.strategy,
            )
        raw = json.dumps(payload, ensure_ascii=False)
        host._log_raw_llm_output("startup_ai", raw)
        decision = host.parser.parse(raw)
        if not bool(getattr(decision, "should_speak", False)) or not str(getattr(decision, "text", "") or "").strip():
            fallback_text = build_startup_fallback_text(
                open_loops=state.open_loops,
                latest_observation=latest_observation,
                relationship=relationship_payload,
                avoid_text=str(getattr(host, "last_text", "") or ""),
                language=language,
            )
            fallback_payload = {
                "text": fallback_text,
                "should_speak": True,
                "performance_hint": "dry_tease",
            }
            decision = host.parser.parse(json.dumps(fallback_payload, ensure_ascii=False))
            host.logger.warning(
                "[architecture C startup] empty/silent model decision; used personality fallback strategy=%s",
                plan.strategy,
            )
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="session_ritual")
        text, _assistant_meta = self._commit_public(
            decision,
            channel="session_ritual",
            turn_seq=turn_seq,
        )
        if not text:
            return False
        spoken_at = time.time()
        host.last_autonomous_spoken_at = spoken_at
        host._note_autonomous_spoken(now=spoken_at)
        block = getattr(host, "_block_autonomous_presence_after_public_turn", None)
        if callable(block):
            block(now=spoken_at)
        host.logger.info(
            "[architecture C startup] spoke motive=%s text=%s",
            plan.motive,
            text,
        )
        return True

    def run_force_speak(self) -> None:
        host = self.host
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        vision_facts = host._maybe_update_screen_facts()
        if vision_facts:
            try:
                host._attach_screen_facts(snapshot, vision_facts)
            except Exception as exc:
                _orchestrator_boundary_note(host, "force_speak.attach_screen_facts", exc)
        host.long_term_memory = host._memory_recall_texts(snapshot=snapshot)
        memory_resonance = host._recall_memory_resonance(
            snapshot=snapshot,
            channel="force_speak",
            fragments=tuple(vision_facts or ()),
        )
        memory_context = host._build_memory_context(snapshot, memory_resonance=memory_resonance)
        state = host.ai_state_reducer.snapshot()
        turn_seq = _next_ai_turn_seq(host)
        telemetry_payload = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
        planner_snapshot = {
            "event_kind": "force_speak",
            "explicit_user_pull": True,
            "telemetry": telemetry_payload,
            "vision_facts": list(vision_facts or ()),
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": dict(state.latest_observation),
            "recent_public_history": host._chat_history_for_llm(limit=8),
            "instruction": "Choose one grounded, worthwhile thing to say now. Do not invent context.",
        }
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        if discovery_runtime is not None:
            planner_snapshot["discovery"] = discovery_runtime.planner_context(telemetry_payload)
        plan = host.ai_intention_planner.plan_autonomous(
            planner_snapshot,
            turn_seq=turn_seq,
        )
        discovery_id = ""
        discovery_grounding = ""
        if discovery_runtime is not None:
            plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(plan)
        if str(getattr(plan, "strategy", "") or "").strip().lower() == "share_discovery" and not discovery_grounding:
            plan = IntentionPlan.silence(channel="force_speak", reason="share_discovery_without_artifact")
        if not plan.speak or not plan.topic.strip():
            plan = IntentionPlan.from_mapping(
                {
                    "plan_id": f"force-speak-{int(time.time() * 1000)}",
                    "speak": True,
                    "motive": "user_force_speak",
                    "strategy": "direct_presence",
                    "value_focus": "continuity",
                    "topic": "Respond to the explicit request for presence with one short grounded line.",
                    "importance": 0.65,
                    "intrusion_risk": 0.05,
                    "confidence": 0.70,
                    "performance_hint": "neutral",
                    "tool_intent": "",
                    "tool_input": "",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "force_speak",
                        "speech_act": "respond_explicit_presence_pull",
                        "subject_key": "explicit_user_pull",
                        "evidence_scope": "conversation",
                        "continuation_key": "current_public_turn",
                    },
                    "notes": "mechanical explicit user pull fallback",
                },
                channel="force_speak",
            )

        payload = host.ai_model_router.generate_autonomous_reply(
            plan=plan,
            personality_context=state.personality_prompt_context(),
            memory_context=memory_context,
            grounding_context="\n".join(
                part for part in (
                    "\n".join(str(item) for item in (vision_facts or ())[-6:]),
                    discovery_grounding,
                ) if part
            ),
            recent_history=host._chat_history_for_llm(limit=8),
            avoid_text="\n".join(
                str(item.get("content", "") or "").strip()
                for item in host._chat_history_for_llm(limit=6)
                if isinstance(item, Mapping) and str(item.get("role", "") or "") == "assistant"
            )[-1800:] or str(getattr(host, "last_text", "") or ""),
            allow_fallback=not no_fallback_mode_enabled(),
            language_hint=_runtime_language(),
        )
        if not payload:
            host.logger.warning("[architecture C force_speak] generation failed")
            return
        raw = json.dumps(payload, ensure_ascii=False)
        host._log_raw_llm_output("force_speak_ai", raw)
        decision = host.parser.parse(raw)
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="force_speak")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        text = str(getattr(decision, "text", "") or "").strip()
        if not text:
            return
        turn_id = f"force_speak:{turn_seq}"
        text, assistant_meta = self._commit_public(
            decision,
            channel="force_speak",
            turn_seq=turn_seq,
        )
        if text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, text)
        if not text:
            return
        host.last_autonomous_spoken_at = time.time()
        host._note_autonomous_spoken()
        initiative = getattr(host, "ai_initiative_controller", None)
        if initiative is not None:
            initiative.record_spoken(plan, now=host.last_autonomous_spoken_at, channel="force_speak")
        if plan.strategy:
            host.ai_state_reducer.submit(
                StateEvent.from_pending_strategy(
                    PendingStrategyUse(
                        strategy_use_id=f"strategy:{turn_id}",
                        turn_seq=turn_seq,
                        strategy=plan.strategy,
                        goal=plan.topic,
                        context=tuple(item for item in (plan.motive, plan.value_focus, "force_speak") if str(item or "").strip()),
                        assistant_text=text,
                    ),
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            host.ai_state_reducer.submit(
                StateEvent.from_mechanical_outcome(
                    dict(decision.action_result_meta),
                    turn_seq=turn_seq,
                    turn_id=turn_id,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        host.ai_post_turn_observer.submit(
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text="[explicit force_speak request]",
            assistant_text=text,
            recent_history=tuple(host._chat_history_for_llm(limit=8)),
            mechanical_outcomes=(dict(decision.action_result_meta),)
                if isinstance(getattr(decision, "action_result_meta", None), Mapping)
                else (),
            state_summary=state.to_dict(),
            assistant_meta=assistant_meta,
            event_kind="force_speak",
        )
        host.logger.info("[architecture C force_speak] text=%s", text)

    def run_iteration(self) -> bool:
        """Facade mỏng; pipeline typed nằm trong ``self_turn_pipeline.py``."""
        # Adapter/test có thể thay trace_store trực tiếp trên facade. Đồng bộ lại
        # trước mỗi tick để không giữ hai sink debug khác nhau.
        self.self_turn_pipeline.trace_store = self.trace_store
        return self.self_turn_pipeline.run()


__all__ = [
    "AIChatOrchestrator",
    "AIAutonomousOrchestrator",
    "architecture_c_enabled",
]
