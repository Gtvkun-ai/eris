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
from runtime.public_reply_context import compile_public_reply_context
from runtime.reply_obligation import enforce_reply_obligation
from runtime.discourse_state import assistant_proposition_link
from runtime.discourse_surface import DiscourseSurface, DiscourseSurfaceRenderer
from runtime.json_boundary import public_payload
from runtime.semantic_frame import (
    AssistantAct,
    SemanticFrame,
    validate_assistant_act,
    validate_semantic_frame,
)
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


def _deepseek_web_authority_mode() -> bool:
    provider = str(os.getenv("ERIS_REMOTE_PROVIDER", "") or "").strip().lower().replace("-", "_")
    return provider in {"deepseek_web", "ds2api", "whale2api", "whale"}


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


def _runtime_speech_language() -> str:
    """Ngôn ngữ transcript TTS do cùng semantic authority render."""
    try:
        from runtime.runtime_settings_store import runtime_text
        raw = str(runtime_text("tts", "language", default="ja") or "ja").strip().lower()
    except Exception:
        raw = "ja"
    aliases = {
        "": "ja", "auto": "ja", "jp": "ja", "ja-jp": "ja", "japanese": "ja",
        "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "en-us": "en", "english": "en",
    }
    language = aliases.get(raw, raw)
    return language if language in {"vi", "ja", "en"} else "ja"


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



def _serializable_public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa payload public trước JSON và bỏ cache object typed nội bộ."""

    return public_payload(payload)


def _previous_active_proposition_root(ledger: Any) -> int:
    """Lấy root đang active mà không coi acknowledgement là proposition mới."""

    try:
        turns = ledger.all_turns()
    except Exception:
        return 0
    for turn in reversed(turns):
        if getattr(turn, "role", "") != "assistant":
            continue
        discourse = dict(getattr(turn, "meta", {}).get("discourse", {}) or {})
        root = int(
            discourse.get("active_proposition_root_turn_index", 0)
            or discourse.get("proposition_root_turn_index", 0)
            or 0
        )
        if root:
            return root
    return 0


def _decision_from_discourse_surface(host: Any, surface: DiscourseSurface, *, user_text: str):
    payload = {
        "text": surface.text,
        "should_speak": bool(surface.text),
        "animation": "stand",
        "next_animation": "stand",
        "direction": 0,
        "target_x": -1.0,
        "bounce_action": "",
        "system_action": "",
        "action_input": "",
        "delivery_hint": "focused",
        "performance_hint": surface.performance_hint,
    }
    decision = host.parser.parse(json.dumps(payload, ensure_ascii=False), user_hint=user_text)
    decision.intent = surface.intent
    decision.parse_mode = "typed_discourse"
    decision.reasoning_tags = ("answer_first", "typed_discourse", surface.intent)
    return decision


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
            preempt_background = getattr(self.host, "_preempt_background_for_chat", None)
            if callable(preempt_background):
                try:
                    preempt_background("user_turn")
                except Exception as exc:
                    logger = getattr(self.host, "logger", None)
                    if logger is not None:
                        try:
                            logger.debug("background preempt failed: %s", exc)
                        except Exception:
                            pass
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
        # Discourse resolution for fallbacks / failed turns: if previous turn failed or used repair obligation,
        # and user asks "nói lại", "gửi lại", etc., retry the specific cached failed turn text rather than
        # treating "nói lại" as a generic/new proposition.
        cached_failed_turn = getattr(host, "_cached_failed_user_turn", "")
        clean_user_text = str(user_text or "").strip().lower()
        repair_keywords = {
            "nói lại", "nhắc lại", "gửi lại", "nói lại đi", "nhắc lại xem", "nói tiếp đi",
            "gửi lại câu đó", "nói lại câu đó", "lại đi", "lại nào", "lại", "say again", "repeat",
        }
        if cached_failed_turn and (clean_user_text in repair_keywords or any(k in clean_user_text for k in ("nói lại", "nhắc lại", "gửi lại"))):
            host.logger.info(
                "[discourse resolution] User requested repair (%r); substituting with cached failed turn: %r",
                user_text,
                cached_failed_turn,
            )
            user_text = cached_failed_turn
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

        # Semantic authority phải phân loại conversation act trước khi runtime
        # quyết định dùng session ledger hay long-term memory. Không còn bước
        # regex đứng trước model, vì chính bước đó từng biến vài câu mới thành
        # một cuộc săn marker vô tận.
        discourse_context = ""
        build_discourse_context = getattr(host, "_build_discourse_prompt_context", None)
        if callable(build_discourse_context):
            try:
                discourse_context = str(
                    build_discourse_context(current_turn_index=user_turn.index) or ""
                )
            except Exception as exc:
                host.logger.debug("[typed discourse] prompt context failed: %s", exc)

        personality_context = mind_state.personality_prompt_context()
        relationship_context = mind_state.relationship.prompt_summary()
        grounding_context = str(getattr(grounding_report, "prompt_context", "") or "")
        vision_status_context = ""
        build_vision_status = getattr(host, "_chat_vision_status_prompt_context", None)
        if callable(build_vision_status):
            try:
                vision_status_context = str(
                    build_vision_status(screen_image_data_uri=screen_image_data_uri) or ""
                )
            except Exception as exc:
                host.logger.debug("[vision status] prompt context failed: %s", exc)
        if vision_status_context:
            # PATCH: source grounding có thể nói “có frame”, nhưng nếu grounded_claims=0
            # public writer phải giữ stance trung thực, không mở bằng “đang nhìn đây”.
            grounding_context = "\n\n".join(
                part for part in (grounding_context, vision_status_context) if str(part).strip()
            )
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
            "discourse_context": discourse_context,
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
        use_escalation = bool(route_decision.use_pro and not _deepseek_web_authority_mode())
        reasoning_effort = route_decision.reasoning_effort
        thinking_mode = route_decision.thinking_mode
        routing_context = route_decision.prompt_context()
        host.last_companion_model_route = route_decision.to_dict()
        compiled_context = compile_public_reply_context(
            route=route_decision,
            personality=personality_context,
            relationship=relationship_context,
            grounding=grounding_context,
            memory=memory_context,
            interrupt=speech_interrupt_context,
            engagement=engagement_prompt_context,
            routing=routing_context,
            discourse=discourse_context,
        )
        host.last_public_context_compilation = compiled_context.to_dict()
        payload: dict[str, Any] = {}
        host._set_background_memory_digest_remote_inflight(True)
        try:
            payload = host.ai_model_router.generate_public_reply(
                chat_history=history,
                user_text=user_message,
                memory_context=compiled_context.memory,
                grounding_context=compiled_context.grounding,
                relationship_context=compiled_context.relationship,
                personality_context=compiled_context.personality,
                interrupt_context=compiled_context.interrupt,
                engagement_context=compiled_context.engagement,
                routing_context=compiled_context.routing,
                discourse_context=compiled_context.discourse,
                use_escalation=use_escalation,
                reasoning_effort=reasoning_effort,
                thinking_mode=thinking_mode,
                allow_fallback=False,
                language_hint=_runtime_language(),
                speech_language_hint=_runtime_speech_language(),
                planned_intention=chat_plan,
            )
            if (
                not payload
                and not no_fallback_mode_enabled()
                and not _deepseek_web_authority_mode()
            ):
                payload = host.ai_model_router.generate_public_reply(
                    chat_history=history,
                    user_text=user_message,
                    memory_context=compiled_context.memory,
                    grounding_context=compiled_context.grounding,
                    relationship_context=compiled_context.relationship,
                    personality_context=compiled_context.personality,
                    interrupt_context=compiled_context.interrupt,
                    engagement_context=compiled_context.engagement,
                    routing_context=compiled_context.routing,
                    discourse_context=compiled_context.discourse,
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    thinking_mode=thinking_mode,
                    allow_fallback=True,
                    language_hint=_runtime_language(),
                    speech_language_hint=_runtime_speech_language(),
                    planned_intention=chat_plan,
                    )
        finally:
            host._set_background_memory_digest_remote_inflight(False)

        discourse_resolution = None
        assistant_discourse_meta: dict[str, Any] = {}
        deterministic_decision = None
        deterministic_source = ""
        typed_frame: SemanticFrame | None = None
        assistant_act: AssistantAct = AssistantAct()
        discourse_surface = DiscourseSurface()

        if payload:
            payload = guard_subjective_stance_payload(payload)
            typed_frame = payload.get("_typed_semantic_frame")
            if not isinstance(typed_frame, SemanticFrame):
                typed_frame = validate_semantic_frame(payload.get("semantic_frame", {})).frame
            typed_assistant_act = payload.get("_typed_assistant_act")
            if isinstance(typed_assistant_act, AssistantAct):
                assistant_act = typed_assistant_act
            else:
                assistant_act = validate_assistant_act(payload.get("assistant_act", {})).act

            semantic_frame = typed_frame.to_dict()
            host.last_semantic_frame = semantic_frame
            user_meta["semantic_frame"] = semantic_frame
            try:
                from runtime.observability import GLOBAL_OBSERVABILITY
                GLOBAL_OBSERVABILITY.log(
                    "semantic_frame_v1",
                    tags={
                        "user_act": typed_frame.user_act or "unknown",
                        "target": typed_frame.target or "unknown",
                        "relation": typed_frame.discourse_relation or "unknown",
                    },
                    fields={"turn_seq": turn_seq, "frame": semantic_frame},
                )
            except Exception as exc:
                _orchestrator_boundary_note(host, "semantic_frame.observability", exc)

            try:
                host._ensure_session_turn_ledger().merge_turn_meta(
                    user_turn.index,
                    {"semantic_frame": semantic_frame},
                )
            except Exception as exc:
                host.logger.debug("[typed discourse] user frame commit failed: %s", exc)

            resolve_discourse = getattr(host, "_resolve_discourse_frame", None)
            if callable(resolve_discourse):
                try:
                    discourse_resolution = resolve_discourse(
                        typed_frame,
                        current_user_turn_index=user_turn.index,
                    )
                    assistant_discourse_meta = discourse_resolution.assistant_meta(
                        user_turn_index=user_turn.index
                    )
                    assistant_discourse_meta["assistant_act"] = assistant_act.to_dict()
                    discourse_surface = DiscourseSurfaceRenderer().render(
                        discourse_resolution.action,
                        model_text=str(payload.get("text", "") or ""),
                    )
                    if discourse_surface.deterministic and discourse_surface.text:
                        deterministic_decision = _decision_from_discourse_surface(
                            host,
                            discourse_surface,
                            user_text=user_text,
                        )
                        assistant_discourse_meta["assistant_act"] = {
                            "kind": "answer",
                            "proposition_mode": "new",
                            "confidence": 1.0,
                        }
                        deterministic_source = "typed_discourse"
                except Exception as exc:
                    host.logger.debug("[typed discourse] resolution failed: %s", exc)

            # Memory query đã được semantic authority chuẩn hóa thành object typed.
            # Không gọi compiler trên raw user text thêm lần nữa.
            if (
                deterministic_decision is None
                and discourse_resolution is not None
                and discourse_resolution.memory_recall_requested
                and (grounding_report is None or bool(getattr(grounding_report, "memory_answer_allowed", True)))
            ):
                build_memory_recall = getattr(host, "_build_typed_memory_recall_decision", None)
                if callable(build_memory_recall):
                    try:
                        deterministic_decision = build_memory_recall(
                            discourse_resolution.memory_query,
                            raw_text=user_text,
                        )
                        if deterministic_decision is not None:
                            deterministic_source = "memory_recall"
                    except Exception as exc:
                        host.logger.debug("[memory recall] typed fulfillment failed: %s", exc)

            if deterministic_decision is not None:
                user_meta[f"{deterministic_source}_answer"] = True
                host.logger.info(
                    "[%s] deterministic fulfillment parse_mode=%s",
                    deterministic_source.replace("_", " "),
                    str(getattr(deterministic_decision, "parse_mode", "") or deterministic_source),
                )
                host.ai_stage_planner.apply(
                    deterministic_decision,
                    "neutral",
                    state=mind_state,
                    channel="chat",
                )
                deterministic_decision = host._execute_system_action(
                    deterministic_decision,
                    snapshot=snapshot,
                    frame=None,
                )
                public_text, assistant_meta = self._commit(
                    deterministic_decision,
                    assistant_meta_extra=assistant_discourse_meta,
                    idempotency_key=f"chat:{turn_id}:assistant",
                )
                host.last_user_text_for_semantics = user_text
                recent_history = tuple(host._chat_history_for_llm(limit=8))
                observer_state = mind_state.to_dict()
                observer_state["semantic_frame"] = semantic_frame
                host.ai_post_turn_observer.submit(
                    turn_id=turn_id,
                    turn_seq=turn_seq,
                    user_text=user_text,
                    assistant_text=public_text,
                    recent_history=recent_history,
                    mechanical_outcomes=[],
                    state_summary=observer_state,
                    user_meta=user_meta,
                    assistant_meta=assistant_meta,
                    event_kind="chat",
                )
                return

            if discourse_surface.text and not str(payload.get("text", "") or "").strip():
                payload["text"] = discourse_surface.text
                payload["should_speak"] = True
                payload["performance_hint"] = discourse_surface.performance_hint

            obligation = enforce_reply_obligation(
                payload,
                user_text=user_text,
                frame=typed_frame,
                language_hint=_runtime_language(),
                direct_user_turn=True,
            )
            payload = obligation.payload
            if obligation.repaired:
                host.logger.warning(
                    "[reply obligation] repaired turn=%s reason=%s",
                    turn_seq,
                    obligation.reason,
                )
                assistant_act = validate_assistant_act(payload.get("assistant_act", {})).act
                payload["_typed_assistant_act"] = assistant_act
                assistant_discourse_meta["assistant_act"] = assistant_act.to_dict()

            draft_text = str(payload.get("text", "") or "")
            grounding_engine = getattr(host, "source_grounding_engine", None)
            grounding_verdict = evaluate_grounded_surface(
                grounding_engine, draft_text, report=grounding_report
            )
            grounding_annotations = grounding_verdict.annotations
            if not grounding_verdict.allowed:
                violation_codes = ["UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM"]
                if _deepseek_web_authority_mode():
                    # DeepSeek Web owns one atomic semantic attempt. An unsafe
                    # candidate is suppressed and degraded locally; a second
                    # remote rewrite would violate the one-authority/one-deadline
                    # contract and can double perceived latency.
                    host.logger.warning(
                        "[cortex v2 gate] turn=%s violations=%s; suppressing web commit without remote retry",
                        turn_seq,
                        ",".join(violation_codes),
                    )
                    payload = {}
                else:
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
                            memory_context=compiled_context.memory,
                            grounding_context=compiled_context.grounding,
                            relationship_context=compiled_context.relationship,
                            personality_context=compiled_context.personality,
                            interrupt_context=compiled_context.interrupt,
                            engagement_context=compiled_context.engagement,
                            routing_context=compiled_context.routing,
                            discourse_context=compiled_context.discourse,
                            use_escalation=use_escalation,
                            reasoning_effort=reasoning_effort,
                            thinking_mode=thinking_mode,
                            allow_fallback=not no_fallback_mode_enabled(),
                            language_hint=_runtime_language(),
                            speech_language_hint=_runtime_speech_language(),
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
                            # Wording retry không được đổi assistant act/proposition mode.
                            retried["assistant_act"] = assistant_act.to_dict()
                            retried["_typed_assistant_act"] = assistant_act
                            retried["semantic_frame"] = typed_frame.to_dict() if typed_frame is not None else retried.get("semantic_frame", {})
                            retried["_typed_semantic_frame"] = typed_frame
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
            # Khi provider/grounding không để lại public text, dùng reference đã
            # resolve nếu có. Nếu cả frame cũng không có, trả lỗi hội thoại chung
            # thay vì im lặng; không suy ý định bằng marker câu chữ.
            fallback_payload = enforce_reply_obligation(
                {"text": str(discourse_surface.text or "").strip(), "should_speak": bool(discourse_surface.text)},
                user_text=user_text,
                frame=typed_frame,
                language_hint=_runtime_language(),
                direct_user_turn=True,
            ).payload
            fallback_payload.update({
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
                "performance_hint": str(fallback_payload.get("performance_hint", "neutral") or "neutral"),
            })
            decision = host.parser.parse(
                json.dumps(_serializable_public_payload(fallback_payload), ensure_ascii=False),
                user_hint=user_text,
            )
            decision.parse_mode = "typed_discourse_fallback"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="ai_chat_orchestrator",
                origin="main_model",
                public_surface="typed_discourse_fallback",
                recoverable=True,
            )
        else:
            public_payload = _serializable_public_payload(payload)
            raw = json.dumps(public_payload, ensure_ascii=False)
            host._log_raw_llm_output("chat_ai", raw)
            decision = host.parser.parse(raw, user_hint=user_text)

        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(
                getattr(host, "_active_public_lifecycle_turn_id", "") or turn_id
            )

        if not payload or getattr(decision, "parse_mode", "") == "typed_discourse_fallback" or bool(getattr(decision, "failure_meta", None)):
            setattr(host, "_cached_failed_user_turn", user_text)
        elif hasattr(host, "_cached_failed_user_turn") and getattr(host, "_cached_failed_user_turn", ""):
            setattr(host, "_cached_failed_user_turn", "")

        # Main model chỉ nêu hint; StagePlanner làm phần cơ học. Legacy stage fields
        # vẫn được chấp nhận để không làm frontend gãy, nhưng không cần thiết.
        hint = str(getattr(decision, "performance_hint", "") or "").strip().lower()
        if not hint or hint == "neutral":
            hint = str(getattr(chat_plan, "performance_hint", "") or "neutral")
        host.ai_stage_planner.apply(decision, hint, state=mind_state, channel="chat")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        public_text, assistant_meta = self._commit(
            decision,
            assistant_meta_extra=assistant_discourse_meta,
            idempotency_key=f"chat:{turn_id}:assistant",
        )
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

    def _commit(
        self,
        decision: Any,
        *,
        assistant_meta_extra: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        from runtime.public_turn_transaction import registry_for

        return registry_for(self.host).run_once(
            idempotency_key,
            lambda: self._commit_once(
                decision,
                assistant_meta_extra=assistant_meta_extra,
                idempotency_key=idempotency_key,
            ),
        )

    def _commit_once(
        self,
        decision: Any,
        *,
        assistant_meta_extra: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        host = self.host
        if idempotency_key and not str(getattr(decision, "director_trace_id", "") or "").strip():
            decision.director_trace_id = str(idempotency_key)
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
                "idempotency_key": str(idempotency_key or ""),
                # Assistant turn không mang semantic frame của user. Chỉ giữ version
                # để debug protocol, còn user_meta đã lưu frame đúng chủ thể.
                "incoming_user_frame_version": str(
                    dict(getattr(host, "last_semantic_frame", {}) or {}).get("version", "") or ""
                ),
            }
            extra = dict(assistant_meta_extra or {})
            for key, value in extra.items():
                if key == "discourse" and isinstance(value, Mapping):
                    merged_discourse = dict(assistant_meta.get("discourse", {}) or {})
                    merged_discourse.update(dict(value))
                    assistant_meta["discourse"] = merged_discourse
                else:
                    assistant_meta[key] = value

            assistant_act = validate_assistant_act(assistant_meta.get("assistant_act", {})).act
            assistant_meta["assistant_act"] = assistant_act.to_dict()
            discourse = dict(assistant_meta.get("discourse", {}) or {})
            ledger = host._ensure_session_turn_ledger()
            previous_active_root = _previous_active_proposition_root(ledger)
            assistant_turn = ledger.record_assistant(public_text, meta=assistant_meta)
            proposition_root, active_root = assistant_proposition_link(
                assistant_act=assistant_act,
                assistant_turn_index=assistant_turn.index,
                referenced_root_turn_index=int(
                    discourse.get("active_proposition_root_turn_index", 0) or 0
                ),
                previous_active_root_turn_index=previous_active_root,
            )
            discourse["proposition_root_turn_index"] = proposition_root
            discourse["active_proposition_root_turn_index"] = active_root
            assistant_meta["discourse"] = discourse
            ledger.merge_turn_meta(
                assistant_turn.index,
                {
                    "assistant_act": assistant_act.to_dict(),
                    "discourse": discourse,
                },
            )
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
        from runtime.public_turn_transaction import registry_for

        idempotency_key = f"{str(channel or 'autonomous')}:{int(turn_seq)}:assistant"
        return registry_for(self.host).run_once(
            idempotency_key,
            lambda: self._commit_public_once(
                decision,
                channel=channel,
                turn_seq=turn_seq,
                idempotency_key=idempotency_key,
            ),
        )

    def _commit_public_once(
        self,
        decision: Any,
        *,
        channel: str,
        turn_seq: int,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        host = self.host
        if idempotency_key and not str(getattr(decision, "director_trace_id", "") or "").strip():
            decision.director_trace_id = str(idempotency_key)
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
            "idempotency_key": str(idempotency_key or ""),
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

        from runtime.public_lifecycle import lifecycle_for
        startup_turn_id = str(plan.plan_id or f"startup:{turn_seq}")
        host._active_public_lifecycle_turn_id = startup_turn_id
        lifecycle_for(host).begin(
            turn_id=startup_turn_id,
            channel="session_ritual",
            reason="startup_composing",
            received=False,
        )

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
        # Online startup follows the same single semantic-authority path as chat.
        # Preset prose is reserved for degraded mode; it must not silently bypass
        # the bilingual UtteranceSpec contract when DeepSeek Web is available.
        model_router = getattr(host, "ai_model_router", None)
        generate_autonomous = getattr(model_router, "generate_autonomous_reply", None)
        payload = generate_autonomous(
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
            speech_language_hint=_runtime_speech_language(),
        ) if callable(generate_autonomous) else {}
        if payload and plan.strategy in {"persona_opening", "continuity_opening"}:
            _selected_text, quality = choose_startup_text(
                str(payload.get("text", "") or ""),
                greeting_frame,
                avoid_text=avoid_text,
            )
            # Quality is observational only. Replacing display alone would break
            # the committed Japanese speech surface and create a second writer.
            host.logger.info(
                "[architecture C startup greeting] source=deepseek_web score=%.3f accepted=%s reasons=%s situation=%s",
                float(quality.get("score", 0.0) or 0.0),
                int(bool(quality.get("accepted", False))),
                ",".join(str(item) for item in (quality.get("reasons", ()) or ())) or "none",
                str(getattr(greeting_frame, "situation", "unknown") or "unknown"),
            )
        if not payload:
            preset_payload = select_startup_persona_preset(greeting_frame, avoid_text=avoid_text)
            if preset_payload:
                from runtime.utterance_spec import degrade_surface_payload
                payload = degrade_surface_payload(
                    preset_payload,
                    text=str(preset_payload.get("text", "") or ""),
                    language=language,
                    reason="startup_web_unavailable_preset",
                    performance_preset=str(preset_payload.get("performance_hint", "dry_tease") or "dry_tease"),
                    should_speak=True,
                )
                payload["preset_id"] = str(preset_payload.get("preset_id", "") or "")
                host.logger.info(
                    "[architecture C startup greeting] source=degraded_preset id=%s situation=%s",
                    payload.get("preset_id") or "none",
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
            from runtime.utterance_spec import degrade_surface_payload
            payload = degrade_surface_payload(
                {"performance_hint": "dry_tease"},
                text=fallback_text,
                language=language,
                reason="startup_semantic_deadline",
                performance_preset="dry_tease",
                should_speak=True,
            )
            host.logger.warning(
                "[architecture C startup] main reply unavailable; used personality fallback strategy=%s",
                plan.strategy,
            )
        raw = json.dumps(_serializable_public_payload(payload), ensure_ascii=False)
        host._log_raw_llm_output("startup_ai", raw)
        decision = host.parser.parse(raw)
        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(plan.plan_id or f"startup:{turn_seq}")
        if not bool(getattr(decision, "should_speak", False)) or not str(getattr(decision, "text", "") or "").strip():
            fallback_text = build_startup_fallback_text(
                open_loops=state.open_loops,
                latest_observation=latest_observation,
                relationship=relationship_payload,
                avoid_text=str(getattr(host, "last_text", "") or ""),
                language=language,
            )
            from runtime.utterance_spec import degrade_surface_payload
            fallback_payload = degrade_surface_payload(
                {"performance_hint": "dry_tease"},
                text=fallback_text,
                language=language,
                reason="startup_empty_commit",
                performance_preset="dry_tease",
                should_speak=True,
            )
            decision = host.parser.parse(json.dumps(_serializable_public_payload(fallback_payload), ensure_ascii=False))
            decision.utterance_turn_id = str(plan.plan_id or f"startup:{turn_seq}")
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
            lifecycle_for(host).transition(
                "DEGRADED", turn_id=startup_turn_id, reason="empty_public_commit"
            )
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

        from runtime.public_lifecycle import lifecycle_for
        force_turn_id = str(plan.plan_id or f"force_speak:{turn_seq}")
        host._active_public_lifecycle_turn_id = force_turn_id
        lifecycle_for(host).begin(
            turn_id=force_turn_id,
            channel="force_speak",
            reason="force_speak_composing",
            received=False,
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
            speech_language_hint=_runtime_speech_language(),
        )
        if not payload:
            lifecycle_for(host).transition(
                "DEGRADED", turn_id=force_turn_id, reason="semantic_deadline"
            )
            host.logger.warning("[architecture C force_speak] generation failed")
            return
        raw = json.dumps(_serializable_public_payload(payload), ensure_ascii=False)
        host._log_raw_llm_output("force_speak_ai", raw)
        decision = host.parser.parse(raw)
        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(plan.plan_id or f"force_speak:{turn_seq}")
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="force_speak")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        text = str(getattr(decision, "text", "") or "").strip()
        if not text:
            lifecycle_for(host).transition(
                "DEGRADED", turn_id=force_turn_id, reason="empty_public_commit"
            )
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
