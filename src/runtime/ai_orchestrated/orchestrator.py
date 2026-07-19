# -*- coding: utf-8 -*-
"""Đường chạy production của kiến trúc C.

File này cố ý không gọi Ni/Ti/Fe/appraisal/repair legacy trước main model. Những
thứ cần cho continuity đến từ StateReducer, những thứ cần cho sự thật đến từ
grounding/runtime. Main model không phải đi qua một phiên họp trước khi nói.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

from failure_meta import build_failure_meta
from runtime.no_fallback_policy import no_fallback_mode_enabled
from semantic_authority import SemanticAuthorityPolicy

from .contracts import AI_RUNTIME_VERSION, IntentionPlan, StateEvent
from .identity import PendingStrategyUse, PRIMARY_RELATIONSHIP_ID



def architecture_c_enabled() -> bool:
    """Kiến trúc production mặc định; legacy chỉ là đường rollback có chủ ý."""
    legacy_flag = str(os.getenv("ERIS_ARCHITECTURE_C_ENABLED", "1") or "1").strip().lower()
    if legacy_flag in {"0", "false", "no", "off"}:
        return False
    try:
        from runtime.runtime_settings_store import runtime_text
        mode = str(runtime_text("architecture", "mode", default="ai_orchestrated") or "ai_orchestrated").strip().lower()
        return mode not in {"legacy", "cortex_legacy", "disabled", "off"}
    except Exception:
        return True


def _runtime_language() -> str:
    try:
        from runtime.runtime_settings_store import runtime_text
        return str(runtime_text("tts", "language", default="vi") or "vi").strip().lower() or "vi"
    except Exception:
        return "vi"


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
        host = self.host
        semantic_policy = SemanticAuthorityPolicy.from_env()
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )

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
        host._append_chat_history("user", user_text)

        host._chat_snapshot_for_vision = snapshot
        try:
            screen_image_data_uri = host._capture_screen_frame_for_chat(user_text)
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
        except Exception:
            pass

        # Đảm bảo pending strategy của lượt trước đã vào single-writer trước khi
        # observer dùng phản ứng user hiện tại để chấm hậu quả.
        host.ai_state_reducer.wait_idle(0.15)
        mind_state = host.ai_state_reducer.snapshot()
        personality_context = mind_state.personality_prompt_context()
        relationship_context = mind_state.relationship.prompt_summary()
        grounding_context = str(getattr(grounding_report, "prompt_context", "") or "")
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        telemetry_payload = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
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
        use_escalation = semantic_policy.primary_uses_escalation_client if semantic_policy.qwen_first else False
        reasoning_effort = semantic_policy.primary_reasoning_effort if semantic_policy.qwen_first else None

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
                use_escalation=use_escalation,
                reasoning_effort=reasoning_effort,
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
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    allow_fallback=True,
                    language_hint=_runtime_language(),
                    planned_intention=chat_plan,
                )
        finally:
            host._set_background_memory_digest_remote_inflight(False)

        if not payload:
            fallback_payload = {
                "text": "",
                "should_speak": False,
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
            decision.parse_mode = "ai_runtime_format_block"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="ai_chat_orchestrator",
                origin="main_model",
                public_surface="silent",
                recoverable=False,
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
        host.ai_stage_planner.apply(decision, hint, state=state, channel="chat")
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
        host.ai_post_turn_observer.submit(
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=public_text,
            recent_history=recent_history,
            mechanical_outcomes=mechanical,
            state_summary=mind_state.to_dict(),
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
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception:
            pass

        host.last_chat_answer = public_text
        host.last_system_action = str(getattr(decision, "system_action", "") or "")
        clock = getattr(host, "interaction_clock", None)
        if clock is not None and public_text:
            clock.mark_assistant_text()
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
        host._send_decision_to_body(decision, channel="chat")
        host.logger.info("ERIS: %s", public_text)
        return public_text, assistant_meta


class AIAutonomousOrchestrator:
    def __init__(self, host: Any) -> None:
        self.host = host

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
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception:
            pass
        if not public_text:
            return "", None
        host.last_text = public_text
        clock = getattr(host, "interaction_clock", None)
        if clock is not None:
            try:
                clock.mark_assistant_text()
            except Exception:
                pass
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

        state = host.ai_state_reducer.snapshot()
        turn_seq = _next_ai_turn_seq(host)
        snapshot = {
            "event_kind": "startup",
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": dict(state.latest_observation),
            "recent_public_history": host._chat_history_for_llm(limit=4),
            "instruction": (
                "Decide whether one short opening line adds value. Do not report restore state, "
                "telemetry, memory machinery, or claim the user is present when there is no evidence."
            ),
        }
        plan = host.ai_intention_planner.plan_autonomous(
            snapshot,
            turn_seq=turn_seq,
        )
        if not (plan.speak and plan.confidence >= 0.56 and plan.importance >= 0.42):
            host.logger.info(
                "[architecture C startup] silence motive=%s conf=%.2f importance=%.2f",
                plan.motive,
                plan.confidence,
                plan.importance,
            )
            return False

        payload = host.ai_model_router.generate_autonomous_reply(
            plan=plan,
            personality_context=state.personality_prompt_context(),
            memory_context=state.relationship.prompt_summary(),
            grounding_context="startup_event_only; no direct screen evidence",
            recent_history=host._chat_history_for_llm(limit=4),
            avoid_text=str(getattr(host, "last_text", "") or ""),
            allow_fallback=not no_fallback_mode_enabled(),
            language_hint=_runtime_language(),
        )
        if not payload:
            return False
        raw = json.dumps(payload, ensure_ascii=False)
        host._log_raw_llm_output("startup_ai", raw)
        decision = host.parser.parse(raw)
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="session_ritual")
        text, _assistant_meta = self._commit_public(
            decision,
            channel="session_ritual",
            turn_seq=turn_seq,
        )
        if not text:
            return False
        spoken_at = time.time()
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
            except Exception:
                pass
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
            avoid_text=str(getattr(host, "last_text", "") or ""),
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
        host = self.host
        if not host.body_running_fn():
            host.stop()
            return False
        if host._process_pending_user_input():
            return host.running
        if host.chat_mode:
            time.sleep(0.2)
            return True

        now = time.time()
        blocked_until = float(getattr(host, "autonomous_presence_blocked_until", 0.0) or 0.0)
        if now < blocked_until:
            host._sleep_interruptible(min(4.0, max(0.2, blocked_until - now)))
            return True

        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        vision_facts = host._maybe_update_screen_facts()
        if vision_facts:
            try:
                host._attach_screen_facts(snapshot, vision_facts)
            except Exception:
                pass
        host.long_term_memory = host._memory_recall_texts(snapshot=snapshot)
        memory_resonance = host._recall_memory_resonance(
            snapshot=snapshot,
            channel="autonomous",
            fragments=tuple(vision_facts or ()),
        )
        memory_context = host._build_memory_context(snapshot, memory_resonance=memory_resonance)
        memory_context = host._merge_conversation_context(memory_context)
        state = host.ai_state_reducer.snapshot()
        turn_seq = _next_ai_turn_seq(host)
        telemetry_payload = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
        planner_snapshot = {
            "time": now,
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
            "seconds_since_assistant": max(0.0, now - float(getattr(host, "_temporal_last_assistant_turn_at", 0.0) or 0.0)),
            "last_autonomous_text": str(getattr(host, "last_text", "") or ""),
        }
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        if discovery_runtime is not None:
            planner_snapshot["discovery"] = discovery_runtime.planner_context(telemetry_payload, now=now)
            discovery_runtime.maybe_tick(planner_snapshot, now=now)
            planner_snapshot["discovery"] = discovery_runtime.planner_context(telemetry_payload, now=now)
        plan = host.ai_intention_planner.plan_autonomous(
            planner_snapshot,
            turn_seq=turn_seq,
        )
        discovery_id = ""
        discovery_grounding = ""
        if discovery_runtime is not None:
            plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(plan)
        discovery_requires_artifact = str(getattr(plan, "strategy", "") or "").strip().lower() == "share_discovery"
        worth_speaking = (
            plan.speak
            and plan.confidence >= 0.62
            and plan.importance >= 0.56
            and plan.importance >= plan.intrusion_risk + 0.10
            and bool(plan.topic.strip())
            and (not discovery_requires_artifact or bool(discovery_grounding))
        )
        initiative_reason = "not_evaluated"
        initiative = getattr(host, "ai_initiative_controller", None)
        if worth_speaking and initiative is not None:
            active_app = str(telemetry_payload.get("active_app", "") or "").strip().lower()
            active_title = str(telemetry_payload.get("active_window_title", "") or "").strip().lower()
            busy_markers = ("meeting", "meet", "zoom", "teams", "presentation", "full screen", "fullscreen")
            user_busy = any(marker in active_app or marker in active_title for marker in busy_markers)
            seconds_since_user = max(0.0, now - float(getattr(host, "_chat_last_activity_at", 0.0) or 0.0))
            allowed, initiative_reason = initiative.evaluate(
                plan,
                now=now,
                user_busy=user_busy,
                seconds_since_user=seconds_since_user,
            )
            worth_speaking = worth_speaking and allowed
        if not worth_speaking:
            host.logger.info(
                "[ai autonomous] silence motive=%s conf=%.2f importance=%.2f intrusion=%.2f initiative=%s",
                plan.motive,
                plan.confidence,
                plan.importance,
                plan.intrusion_risk,
                initiative_reason,
            )
            host._sleep_interruptible(max(8, min(24, host._choose_autonomous_sleep_duration(suppressed=True, ti_mode="ai_silence"))))
            return True

        if host._process_pending_user_input():
            return host.running
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
            avoid_text=str(getattr(host, "last_text", "") or ""),
            allow_fallback=not no_fallback_mode_enabled(),
            language_hint=_runtime_language(),
        )
        if not payload:
            host.logger.warning(
                "[ai autonomous] public generation failed motive=%s topic=%s",
                plan.motive,
                plan.topic[:120],
            )
            host._sleep_interruptible(10)
            return True
        raw = json.dumps(payload, ensure_ascii=False)
        host._log_raw_llm_output("autonomous_ai", raw)
        decision = host.parser.parse(raw)
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="autonomous")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            host.ai_state_reducer.submit(
                StateEvent.from_mechanical_outcome(
                    dict(decision.action_result_meta),
                    turn_seq=turn_seq,
                    turn_id=plan.plan_id,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        text, assistant_meta = self._commit_public(
            decision,
            channel="autonomous",
            turn_seq=turn_seq,
        )
        if text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, text)
        if not text:
            host._sleep_interruptible(10)
            return True
        host.last_autonomous_spoken_at = time.time()
        host._note_autonomous_spoken()
        if initiative is not None:
            initiative.record_spoken(plan, now=host.last_autonomous_spoken_at, channel="autonomous")
        autonomous_turn_id = f"autonomous:{turn_seq}"
        if plan.strategy:
            host.ai_state_reducer.submit(
                StateEvent.from_pending_strategy(
                    PendingStrategyUse(
                        strategy_use_id=f"strategy:{autonomous_turn_id}",
                        turn_seq=turn_seq,
                        strategy=plan.strategy,
                        goal=plan.topic,
                        context=tuple(item for item in (plan.motive, plan.value_focus, "autonomous") if str(item or "").strip()),
                        assistant_text=text,
                    ),
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        host.ai_post_turn_observer.submit(
            turn_id=autonomous_turn_id,
            turn_seq=turn_seq,
            user_text="",
            assistant_text=text,
            recent_history=tuple(host._chat_history_for_llm(limit=8)),
            mechanical_outcomes=(dict(decision.action_result_meta),)
                if isinstance(getattr(decision, "action_result_meta", None), Mapping)
                else (),
            state_summary=state.to_dict(),
            assistant_meta=assistant_meta,
            event_kind="autonomous",
        )
        host.logger.info(
            "[ai autonomous] spoke motive=%s topic=%s text=%s",
            plan.motive,
            plan.topic[:120],
            text,
        )
        host._sleep_interruptible(max(10, host._choose_autonomous_sleep_duration(suppressed=False, ti_mode="ai_intention")))
        return True


__all__ = [
    "AIChatOrchestrator",
    "AIAutonomousOrchestrator",
    "architecture_c_enabled",
]
