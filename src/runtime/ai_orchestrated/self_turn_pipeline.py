# -*- coding: utf-8 -*-
"""Pipeline self-initiated turn của Architecture C V18.

Mỗi bước có đúng một trách nhiệm:
1. Perception + Context gom signal cơ học và public-safe cognition.
2. ``TypedCognitiveBlackboard`` chuẩn hóa observer/inner/critic/memory outputs.
3. ``Social Initiative Worker`` đề xuất desire/topic bằng typed candidate.
4. ``InitiativeController`` chỉ làm governor timing/quyền phát.
5. ``Surface Worker`` chỉ viết wording cho SpeechIntent đã duyệt.
6. ``AutonomousGroundingValidator`` khóa provenance trước và sau model call.
7. PublicTurnCommitter đưa câu qua TTS + Live2D cùng ledger với chat.

Không còn model call để quyết định có nên nói, rồi controller mới từ chối sau
88 giây. Loài người đã thử cách đó; log cho thấy kết quả khá nghệ thuật.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.grounding_surface_gate import evaluate_grounded_surface
from runtime.json_boundary import public_payload

from .activity_session import ActivitySession, ActivitySessionTracker
from .ambient_screen_context import AmbientScreenContext, AmbientScreenTracker
from .autonomous_trace import AutonomousTraceStore
from .commentary_cadence import CommentaryCadence, CommentaryExpectation
from .cognitive_blackboard import TypedCognitiveBlackboard
from .contracts import AI_RUNTIME_VERSION, IntentionPlan, StateEvent
from .discourse_state import DiscourseState, DiscourseStateBuilder
from .identity import PendingStrategyUse
from .initiative import InitiativeAction, InitiativeDecision
from .self_context import AutonomousSelfContext, build_autonomous_self_context
from runtime.engagements import InteractionDecision


@dataclass(frozen=True, slots=True)
class PerceptionBundle:
    now: float
    snapshot: Any
    telemetry: Mapping[str, Any]
    screen: AmbientScreenContext
    vision_facts: tuple[Any, ...]
    observer_frame: Any = None

    @property
    def mechanical_delta(self) -> bool:
        return bool(self.screen.meaningful_delta or self.screen.window_changed)


@dataclass(frozen=True, slots=True)
class SelfTurnBundle:
    perception: PerceptionBundle
    state: Any
    turn_seq: int
    recent_history: tuple[Mapping[str, Any], ...]
    seconds_since_user: float
    seconds_since_assistant: float
    discourse: DiscourseState
    activity: ActivitySession
    self_context: AutonomousSelfContext
    memory_context: str
    engagement_context: Mapping[str, Any]
    engagement_prompt_context: str
    engagement_interaction: InteractionDecision
    commentary: CommentaryExpectation


class SelfTurnPipeline:
    """Một authority semantic, nhiều adapter cơ học nhỏ."""

    def __init__(
        self,
        host: Any,
        *,
        next_turn_seq: Callable[..., int],
        commit_public: Callable[..., tuple[str, dict[str, Any] | None]],
        emit_body_only: Callable[..., bool],
    ) -> None:
        self.host = host
        self.next_turn_seq = next_turn_seq
        self.commit_public = commit_public
        self.emit_body_only = emit_body_only
        self.screen_tracker = AmbientScreenTracker()
        self.activity_tracker = ActivitySessionTracker()
        self.discourse_builder = DiscourseStateBuilder()
        self.trace_store = AutonomousTraceStore(logger=getattr(host, "logger", None))
        self.commentary_cadence = CommentaryCadence()
        self._last_deliberation_at = 0.0
        self._last_probe_at = 0.0
        self._observer_thread: threading.Thread | None = None
        self._observer_thread_lock = threading.Lock()

    def run(self) -> bool:
        host = self.host
        if not host.body_running_fn():
            host.stop()
            return False
        if host._process_pending_user_input():
            return host.running
        if not self._acquire_baton():
            return True

        now = time.time()
        blocked_until = float(getattr(host, "autonomous_presence_blocked_until", 0.0) or 0.0)
        if now < blocked_until:
            host._sleep_interruptible(min(4.0, max(0.2, blocked_until - now)))
            return True

        phase_started = time.monotonic()
        perception = self._assemble_perception(now)
        perception_ms = (time.monotonic() - phase_started) * 1000.0
        phase_started = time.monotonic()
        context = self._assemble_context(perception)
        context_ms = (time.monotonic() - phase_started) * 1000.0
        phase_started = time.monotonic()
        planner_snapshot, discovery_runtime = self._planner_snapshot(context)
        snapshot_ms = (time.monotonic() - phase_started) * 1000.0
        should_deliberate, trigger_reason = self._should_deliberate(context, planner_snapshot)
        if not should_deliberate:
            self.trace_store.append("attention_skip", {
                "turn_seq": context.turn_seq,
                "trigger_reason": trigger_reason,
                "screen_delta": perception.mechanical_delta,
                "discourse_mode": context.discourse.mode,
                "has_public_seed": context.self_context.has_public_seed,
            }, now=now)
            host._sleep_interruptible(max(8, min(24, host._choose_autonomous_sleep_duration(
                suppressed=True, ti_mode="attention_quiet",
            ))))
            return True

        self._last_deliberation_at = now

        # V18: model sở hữu *mong muốn và topic*, runtime chỉ làm governor.
        # Candidate worker dùng cùng role=surface nhưng contract riêng; nó chưa có
        # quyền phát ngôn và không viết câu cuối.
        blackboard = TypedCognitiveBlackboard.from_snapshot(planner_snapshot, now=now)
        candidate_started = time.monotonic()
        candidate = None
        social_engine = getattr(host, "ai_social_initiative_engine", None)
        if social_engine is not None:
            candidate = social_engine.propose(blackboard, snapshot=planner_snapshot)
        candidate_ms = (time.monotonic() - candidate_started) * 1000.0
        initiative = getattr(host, "ai_initiative_controller", None)
        if initiative is None:
            decision = InitiativeDecision(
                InitiativeAction.NO_OP,
                "initiative_controller_unavailable",
                IntentionPlan.silence(channel="autonomous", reason="controller_unavailable"),
            )
        else:
            decision = initiative.decide(blackboard, candidate)
        host.logger.info(
            "[autonomous latency] perception=%.0fms context=%.0fms snapshot=%.0fms candidate=%.0fms total_to_governor=%.0fms",
            perception_ms, context_ms, snapshot_ms, candidate_ms,
            perception_ms + context_ms + snapshot_ms + candidate_ms,
        )
        if candidate is not None:
            host.logger.info(
                "[social initiative] source=%s kind=%s anchor=%s confidence=%.2f relevance=%.2f reason=%s",
                candidate.source, candidate.kind, candidate.anchor_type, candidate.confidence, candidate.relevance, candidate.reason,
            )

        plan = decision.plan
        discovery_grounding = ""
        discovery_id = ""
        if decision.should_speak and discovery_runtime is not None:
            plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(plan)
            # bind_plan có thể bổ sung artifact/evidence; SpeechIntent phải dùng
            # plan cuối cùng, nhưng không được đổi action mà controller đã chọn.
            speech_intent = decision.speech_intent
            if speech_intent is not None and plan is not speech_intent.plan:
                from dataclasses import replace
                speech_intent = replace(speech_intent, plan=plan)
                decision = replace(decision, plan=plan, speech_intent=speech_intent)

        activity = self.activity_tracker.annotate(plan.activity, now=now)
        host.last_ai_intention_plan = plan
        self._submit_intention(plan, turn_seq=context.turn_seq)

        self.trace_store.append("initiative_decision", {
            "turn_seq": context.turn_seq,
            "action": decision.action.value,
            "reason": decision.reason,
            "anchor": decision.speech_intent.anchor_type if decision.speech_intent else "none",
            "semantic_signature": plan.semantic_signature,
            "candidate": candidate.to_dict() if candidate is not None else None,
        }, now=now)

        # Log một dòng ngắn để runtime log cho biết Eris đang thật sự quyết
        # định gì. NO_OP để debug nhằm tránh spam; BODY_ONLY/SPEECH là INFO vì
        # chúng tạo hành vi nhìn thấy được và hữu ích khi chẩn đoán "đứng đơ".
        initiative_log = host.logger.info if decision.action is not InitiativeAction.NO_OP else host.logger.debug
        initiative_log(
            "[initiative] action=%s anchor=%s reason=%s",
            decision.action.value,
            decision.speech_intent.anchor_type if decision.speech_intent else "none",
            decision.reason,
        )

        if decision.action is InitiativeAction.NO_OP:
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason=decision.reason,
            )
        if decision.action is InitiativeAction.BODY_ONLY:
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason=decision.reason,
                force_body_only=True, body_motion=decision.body_motion,
            )
        if host._process_pending_user_input():
            return host.running

        speech_intent = decision.speech_intent
        if speech_intent is None:
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason="missing_speech_intent",
            )

        validator = getattr(host, "ai_autonomous_grounding_validator", None)
        if validator is not None:
            preflight = validator.validate_intent(speech_intent, blackboard)
            if not preflight.allowed:
                return self._finish_silence(
                    plan=plan, context=context, activity=activity, gate_reason=preflight.reason,
                    force_body_only=bool(context.perception.mechanical_delta or activity.has_new_event),
                    body_motion=decision.body_motion,
                )

        from runtime.public_lifecycle import lifecycle_for
        lifecycle_turn_id = str(plan.plan_id or f"autonomous:{context.turn_seq}")
        host._active_public_lifecycle_turn_id = lifecycle_turn_id
        public_lifecycle = lifecycle_for(host)
        public_lifecycle.begin(
            turn_id=lifecycle_turn_id,
            channel="autonomous",
            reason="autonomous_composing",
            received=False,
        )

        surface_payload = None
        surface_engine = getattr(host, "ai_surface_intent_engine", None)
        surface_turn = None
        if surface_engine is not None:
            try:
                surface_turn = surface_engine.realize(
                    speech_intent, blackboard, snapshot=planner_snapshot,
                )
            except Exception as exc:
                host.logger.warning("[surface worker] realization failed: %s", exc)
        if surface_turn is not None:
            plan = surface_turn.plan
            surface_payload = surface_turn.public_payload
            host.last_ai_intention_plan = plan
        elif surface_engine is not None:
            # Không gọi Main AI/planner lần hai. Một micro-line optional không
            # được phép kéo theo chuỗi retry/fallback dài rồi giữ ERIS im lặng.
            surface_payload = surface_engine.fallback_payload(
                speech_intent,
                blackboard,
                avoid_text=str(getattr(host, "last_text", "") or ""),
                language=self._runtime_language(),
            )
            if surface_payload:
                host.logger.info(
                    "[surface worker] local fallback mode=%s reason=provider_unavailable_or_timeout",
                    speech_intent.mode,
                )
        if not surface_payload:
            public_lifecycle.transition(
                "DEGRADED",
                turn_id=lifecycle_turn_id,
                reason="surface_unavailable",
            )
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason="surface_unavailable",
                force_body_only=True, body_motion=decision.body_motion,
            )

        return self._surface(
            plan=plan,
            context=context,
            activity=activity,
            discovery_grounding=discovery_grounding,
            discovery_id=discovery_id,
            discovery_runtime=discovery_runtime,
            prebuilt_payload=surface_payload,
            allow_model_generation=False,
        )

    def _submit_intention(self, plan: IntentionPlan, *, turn_seq: int) -> None:
        """Ghi typed plan vào single-writer reducer sau deterministic decision."""

        reducer = getattr(self.host, "ai_state_reducer", None)
        if reducer is None:
            return
        try:
            state = reducer.snapshot()
            reducer.submit(
                StateEvent.from_intention(
                    plan,
                    turn_seq=turn_seq,
                    base_version=getattr(state, "version", -1),
                )
            )
        except Exception as exc:
            self.host.logger.debug("[initiative] reducer submit failed: %s", exc)

    def _acquire_baton(self) -> bool:
        host = self.host
        if not bool(getattr(host, "chat_mode", False)):
            return True
        # Không được tự nhả baton khi chat worker còn sinh câu hoặc audio/public
        # turn vẫn đang bận. Timer stale không có quyền chen vào giữa hai tin nhắn.
        if bool(getattr(host, "_chat_processing", False)):
            time.sleep(0.2)
            return False
        clock = getattr(host, "interaction_clock", None)
        if clock is not None and bool(getattr(clock, "busy", False)):
            time.sleep(0.2)
            return False
        stale_check = getattr(host, "_conversation_went_stale", None)
        if callable(stale_check) and stale_check():
            end_chat_cycle = getattr(host, "_end_chat_cycle", None)
            if callable(end_chat_cycle):
                end_chat_cycle()
            else:
                host.chat_mode = False
            host.logger.info("[self turn] chat baton released after stale public activity")
            return True
        time.sleep(0.2)
        return False

    def _assemble_perception(self, now: float) -> PerceptionBundle:
        host = self.host
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        telemetry = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
        screen_snapshot = None
        screen_store = getattr(host, "screen_evidence_store", None)
        if screen_store is not None:
            try:
                screen_snapshot = screen_store.snapshot()
            except Exception as exc:
                host.logger.debug("[self turn screen] snapshot unavailable: %s", exc)
        screen = self.screen_tracker.observe(screen_snapshot, telemetry=telemetry, now=now)

        attention = getattr(host, "last_cortex_attention", None)
        force_visual_refresh = bool(
            not screen.privacy_blocked
            and not screen.changed_text
            and (
                bool(getattr(attention, "vision_refresh_recommended", False))
                or (screen.meaningful_delta and screen.changed_ratio >= 0.12)
            )
        )
        previous_observer = getattr(host, "last_observer_frame", None)
        # Không để autonomous turn chờ observer/model vision. Nếu chưa có cached
        # observer, ta schedule refresh nền và dùng facts đã grounded từ tick trước.
        # Tick sau sẽ nhận kết quả; UI không đứng đợi một lane advisory đi họp.
        if previous_observer is None:
            vision_facts = tuple(
                () if bool(getattr(host, "vision_facts_are_stale", False))
                else tuple(getattr(host, "vision_facts", ()) or ())
            )
            self._schedule_observer_refresh(snapshot, vision_facts, now)
        else:
            try:
                vision_facts = host._maybe_update_screen_facts(
                    snapshot=snapshot,
                    channel="autonomous",
                    observer_frame=previous_observer,
                    force_refresh=force_visual_refresh,
                    started_at=now,
                )
            except TypeError:
                vision_facts = host._maybe_update_screen_facts()
            vision_facts = tuple(vision_facts or ())
            self._schedule_observer_refresh(snapshot, vision_facts, now)
        if vision_facts:
            try:
                host._attach_screen_facts(snapshot, vision_facts)
            except Exception:
                pass

        observer_frame = previous_observer
        if screen.meaningful_delta or screen.scene_kind != "unknown":
            host.logger.info(
                "[self turn screen] backend=%s ocr=%s upstream_scene=%s conf=%.2f delta=%s changed_text=%s",
                screen.backend or "unknown",
                int(screen.ocr_active),
                screen.scene_kind,
                screen.scene_confidence,
                int(screen.meaningful_delta),
                len(screen.changed_text),
            )
        return PerceptionBundle(
            now=now,
            snapshot=snapshot,
            telemetry=telemetry,
            screen=screen,
            vision_facts=vision_facts,
            observer_frame=observer_frame,
        )

    def _schedule_observer_refresh(
        self,
        snapshot: Any,
        vision_facts: tuple[Any, ...],
        started_at: float,
    ) -> None:
        """Refresh observer ở daemon thread; autonomous turn không chờ kết quả."""

        runner = getattr(self.host, "_run_background_observer", None)
        if not callable(runner):
            return
        with self._observer_thread_lock:
            thread = self._observer_thread
            if thread is not None and thread.is_alive():
                return

            def work() -> None:
                began = time.monotonic()
                try:
                    runner(
                        snapshot=snapshot,
                        channel="autonomous",
                        user_text="",
                        vision_facts=vision_facts,
                        started_at=started_at,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.host.logger.warning("[background observer] refresh failed: %s", exc)
                finally:
                    self.host.logger.debug(
                        "[background observer] refresh finished latency=%.0fms",
                        (time.monotonic() - began) * 1000.0,
                    )

            self._observer_thread = threading.Thread(
                target=work,
                name="eris-autonomous-observer",
                daemon=True,
            )
            self._observer_thread.start()

    def _assemble_context(self, perception: PerceptionBundle) -> SelfTurnBundle:
        host = self.host
        host.long_term_memory = host._memory_recall_texts(snapshot=perception.snapshot)
        memory_resonance = host._recall_memory_resonance(
            snapshot=perception.snapshot,
            channel="autonomous",
            fragments=perception.vision_facts,
        )
        memory_context = host._merge_conversation_context(
            host._build_memory_context(perception.snapshot, memory_resonance=memory_resonance)
        )
        state = host.ai_state_reducer.snapshot()
        turn_seq = self.next_turn_seq(host)
        recent = tuple(host._chat_history_for_llm(limit=8))
        seconds_since_user = max(0.0, perception.now - float(
            getattr(host, "_temporal_last_user_turn_at", 0.0)
            or getattr(host, "_chat_last_activity_at", 0.0)
            or 0.0
        ))
        seconds_since_assistant = max(0.0, perception.now - float(
            getattr(host, "_temporal_last_assistant_turn_at", 0.0) or 0.0
        ))
        discourse = self.discourse_builder.build(
            recent,
            open_loops=tuple(state.open_loops),
            latest_observation=dict(state.latest_observation),
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
        )
        activity = self.activity_tracker.observe(
            perception.screen,
            telemetry=perception.telemetry,
            now=perception.now,
        )
        self_context = build_autonomous_self_context(host)
        engagement_context: Mapping[str, Any] = {"active": False}
        engagement_prompt_context = "active_engagement: none"
        engagement_interaction = InteractionDecision()
        engagement_runtime = getattr(host, "ai_engagement_runtime", None)
        if engagement_runtime is not None:
            try:
                engagement_runtime.observe_activity(activity, now=perception.now)
                engagement_context = engagement_runtime.planner_context(now=perception.now)
                engagement_prompt_context = engagement_runtime.prompt_context(now=perception.now)
                engagement_interaction = engagement_runtime.interaction_decision(
                    now=perception.now,
                    seconds_since_user=seconds_since_user,
                    seconds_since_assistant=seconds_since_assistant,
                    telemetry=perception.telemetry,
                )
            except Exception as exc:
                host.logger.debug("[engagement] autonomous context failed: %s", exc)
        commentary = self.commentary_cadence.evaluate(
            now=perception.now,
            last_commentary_at=float(getattr(host, "last_autonomous_spoken_at", 0.0) or 0.0),
            session_started_at=float(getattr(host, "_temporal_session_started_at", 0.0) or 0.0),
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
            discourse_open=bool(discourse.assistant_may_continue and discourse.thread_fresh),
            perception_delta=bool(perception.mechanical_delta),
            activity_event=bool(activity.has_new_event),
            has_public_seed=bool(self_context.has_public_seed),
            telemetry=perception.telemetry,
            engagement_decision=engagement_interaction,
        )
        return SelfTurnBundle(
            perception=perception,
            state=state,
            turn_seq=turn_seq,
            recent_history=recent,
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
            discourse=discourse,
            activity=activity,
            self_context=self_context,
            memory_context=memory_context,
            engagement_context=engagement_context,
            engagement_prompt_context=engagement_prompt_context,
            engagement_interaction=engagement_interaction,
            commentary=commentary,
        )

    def _planner_snapshot(self, context: SelfTurnBundle) -> tuple[dict[str, Any], Any]:
        perception = context.perception
        state = context.state
        initiative = getattr(self.host, "ai_initiative_controller", None)
        recent_initiative = []
        if initiative is not None:
            try:
                recent_initiative = initiative.panel_view(now=perception.now).get("recent_events", [])[:8]
            except Exception:
                recent_initiative = []
        snapshot = {
            "time": perception.now,
            "event_kind": "self_initiated_turn",
            "telemetry": dict(perception.telemetry),
            "screen_context": perception.screen.to_dict(),
            "conversation_baton": context.discourse.to_dict(),
            "activity_session": context.activity.to_dict(),
            "vision_facts": list(perception.vision_facts),
            "vision_grounding": (
                getattr(self.host, "last_vision_grounding_report", None).to_dict()
                if callable(getattr(getattr(self.host, "last_vision_grounding_report", None), "to_dict", None))
                else {}
            ),
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": dict(state.latest_observation),
            "recent_public_history": context.recent_history,
            "seconds_since_user": context.seconds_since_user,
            "seconds_since_assistant": context.seconds_since_assistant,
            "self_context": context.self_context.to_dict(),
            "memory_context": context.memory_context,
            "recent_self_turn_semantics": recent_initiative,
            "commentary_expectation": context.commentary.to_dict(),
            "engagement_context": dict(context.engagement_context),
            "engagement_interaction": context.engagement_interaction.to_dict(),
            "instruction": (
                "This snapshot feeds a typed Social Initiative candidate generator. "
                "Observer/inner/critic/memory contribute public-safe signals; they do not own public speech. "
                "The candidate model owns desire and topic only. Runtime owns permission and timing. "
                "Surface owns final wording. Grounding owns factual claims. "
                "Raw OCR/window titles are mechanical deltas, never public facts unless vision_grounding contains "
                "a grounded non-stale claim with evidence ids. Social chat may be non-factual and require no screen anchor. "
                "When engagement_context.active=true, preserve its objective and do not switch to unrelated banter."
            ),
        }
        discovery_runtime = getattr(self.host, "ai_discovery_runtime", None)
        if discovery_runtime is not None:
            snapshot["discovery"] = discovery_runtime.planner_context(perception.telemetry, now=perception.now)
            discovery_runtime.maybe_tick(snapshot, now=perception.now)
            snapshot["discovery"] = discovery_runtime.planner_context(perception.telemetry, now=perception.now)
        return snapshot, discovery_runtime

    def _should_deliberate(self, context: SelfTurnBundle, snapshot: Mapping[str, Any]) -> tuple[bool, str]:
        """Attention trigger rẻ; không kết luận có nên nói hay nói gì."""
        discovery = snapshot.get("discovery")
        discovery_ready = bool(isinstance(discovery, Mapping) and (
            discovery.get("ready_to_share") or discovery.get("artifact") or discovery.get("artifact_ready")
        ))
        attention = context.self_context.attention
        pressure = max(
            float(attention.get("external_pressure", 0.0) or 0.0),
            float(attention.get("internal_drive", 0.0) or 0.0),
        )
        now = context.perception.now
        # Liveness wake-up chỉ mời Social Initiative Worker đề xuất topic; nó
        # không ép nói. Dùng cùng soft-silence contract thay vì một hằng số 300s
        # nằm lạc trong scheduler, vì hằng số bí mật là cách runtime nuôi ma.
        try:
            soft_silence = max(45.0, min(3600.0, float(
                os.getenv("ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC", "180") or 180.0
            )))
        except (TypeError, ValueError):
            soft_silence = 180.0
        try:
            probe_interval = max(30.0, min(600.0, float(
                os.getenv(
                    "ERIS_SOCIAL_INITIATIVE_PROBE_INTERVAL_SEC",
                    str(min(180.0, max(45.0, soft_silence / 2.0))),
                ) or 90.0
            )))
        except (TypeError, ValueError):
            probe_interval = min(180.0, max(45.0, soft_silence / 2.0))
        quiet_opportunity = context.seconds_since_assistant >= soft_silence
        presence_probe_due = quiet_opportunity and now - self._last_probe_at >= probe_interval
        checks = (
            (context.discourse.assistant_may_continue and context.discourse.thread_fresh, "open_discourse"),
            (context.perception.mechanical_delta, "perception_delta"),
            (context.activity.has_new_event, "activity_delta"),
            (context.self_context.has_public_seed, "public_self_seed"),
            (discovery_ready, "discovery_ready"),
            (pressure >= 0.58, "cortex_attention"),
            (context.commentary.due, context.commentary.reason),
            (presence_probe_due, "presence_probe"),
        )
        for allowed, reason in checks:
            if allowed:
                if reason == "presence_probe":
                    self._last_probe_at = now
                return True, reason
        return False, "no_new_attention_signal"

    # V18 không còn planner model-owned tự quyết speak/silence trong Surface.
    # Candidate model -> governor -> realizer đã thay đường đó ở run().

    def _finish_silence(
        self,
        *,
        plan: IntentionPlan,
        context: SelfTurnBundle,
        activity: ActivitySession,
        gate_reason: str,
        force_body_only: bool = False,
        body_motion: str = "",
    ) -> bool:
        initiative = getattr(self.host, "ai_initiative_controller", None)
        has_delta = bool(context.perception.mechanical_delta or activity.has_new_event)
        should_body = bool(
            force_body_only
            or (
                not context.perception.screen.privacy_blocked
                and has_delta
                and (
                    gate_reason == "model_silence"
                    or initiative is None
                    or initiative.should_body_only(gate_reason, has_perception_delta=has_delta)
                )
            )
        )
        body_only = False
        if should_body:
            body_only = self.emit_body_only(
                reason=gate_reason,
                activity_kind=plan.activity.activity_kind,
                motion_hint=body_motion or plan.performance_hint,
                turn_seq=context.turn_seq,
                signature=plan.semantic_signature or ":".join(activity.new_event_keys),
            )
        self.trace_store.append("deliberation_result", {
            "turn_seq": context.turn_seq,
            "semantic_signature": plan.semantic_signature,
            "turn_kind": plan.semantics.turn_kind,
            "speech_act": plan.semantics.speech_act,
            "importance": plan.importance,
            "intrusion_risk": plan.intrusion_risk,
            "confidence": plan.confidence,
            "initiative_reason": gate_reason,
            "result": "body_only" if body_only else "silence",
            "body_only": body_only,
        }, now=context.perception.now)
        self._record_result(
            plan,
            result="body_only" if body_only else "silence",
            gate_reason=gate_reason,
        )
        self.host.logger.info(
            "[ai autonomous] silence kind=%s act=%s conf=%.2f importance=%.2f gate=%s body_only=%s",
            plan.semantics.turn_kind,
            plan.semantics.speech_act,
            plan.confidence,
            plan.importance,
            gate_reason,
            int(body_only),
        )
        self.host._sleep_interruptible(max(8, min(24, self.host._choose_autonomous_sleep_duration(
            suppressed=True, ti_mode="ai_silence",
        ))))
        return True


    def _autonomous_grounding_report(self, context: SelfTurnBundle, plan: IntentionPlan):
        """Đóng evidence autonomous thành SourceGroundingReport cho gate chung."""

        from runtime.source_grounding import SourceGroundingReport

        screen = context.perception.screen
        report = getattr(getattr(self, "host", None), "last_vision_grounding_report", None)
        grounded_claims = tuple(getattr(report, "grounded_claims", ()) or ())
        plan_refs = tuple(str(item) for item in getattr(plan, "evidence_refs", ()) or () if str(item).strip())
        grounded_ids = {
            str(evidence_id)
            for claim in grounded_claims
            for evidence_id in tuple(getattr(claim, "evidence_ids", ()) or ())
            if str(evidence_id).strip()
        }
        screen_scope = str(plan.semantics.evidence_scope or "").startswith("screen")
        selected_ids = [ref for ref in plan_refs if ref in grounded_ids]
        fresh_screen = bool(
            screen_scope
            and not screen.privacy_blocked
            and str(getattr(report, "recommendation", "silence") or "silence") == "speak"
            and selected_ids
        )
        previews = [
            str(getattr(claim, "text", "") or "").strip()
            for claim in grounded_claims
            if str(getattr(claim, "text", "") or "").strip()
            and any(ref in selected_ids for ref in tuple(getattr(claim, "evidence_ids", ()) or ()))
        ]
        return SourceGroundingReport(
            user_text="",
            primary_source="runtime_state",
            confidence_cap=0.86 if fresh_screen else 0.58,
            refers_to_current_screen=screen_scope,
            screen_reference_strength=1.0 if fresh_screen else 0.0,
            screen_evidence_present=fresh_screen,
            screen_facts_preview=list(dict.fromkeys(previews))[:8],
            screen_facts_are_stale=not fresh_screen if screen_scope else False,
            evidence_ids=list(dict.fromkeys(selected_ids)),
            allowed_sources=["runtime_state"] + (["current_screen"] if fresh_screen else []),
            grounding_source="current_screen" if fresh_screen else "runtime_state",
            missing_evidence=[] if (fresh_screen or not screen_scope) else ["grounded_screen_evidence"],
        )

    def _surface(
        self,
        *,
        plan: IntentionPlan,
        context: SelfTurnBundle,
        activity: ActivitySession,
        discovery_grounding: str,
        discovery_id: str,
        discovery_runtime: Any,
        prebuilt_payload: Mapping[str, Any] | None = None,
        allow_model_generation: bool = True,
    ) -> bool:
        host = self.host
        payload = dict(prebuilt_payload or {})
        if not payload and allow_model_generation:
            payload = host.ai_model_router.generate_autonomous_reply(
                plan=plan,
                personality_context=context.state.personality_prompt_context(),
                memory_context=context.memory_context,
                grounding_context="\n".join(part for part in (
                    context.perception.screen.prompt_context(),
                    "\n".join(str(item) for item in context.perception.vision_facts[-6:]),
                    discovery_grounding,
                    f"AUTONOMOUS_SELF_CONTEXT:\n{context.self_context.prompt_context()}",
                ) if part),
                engagement_context=context.engagement_prompt_context,
                recent_history=context.recent_history,
                avoid_text=str(getattr(host, "last_text", "") or ""),
                allow_fallback=not no_fallback_mode_enabled(),
                language_hint=self._runtime_language(),
                speech_language_hint=self._runtime_speech_language(),
            )
        if not payload:
            host.logger.warning(
                "[ai autonomous] public generation failed kind=%s subject=%s",
                plan.semantics.turn_kind,
                plan.semantics.subject_key,
            )
            self._record_result(plan, result="generation_failed", gate_reason="public_generation_failed")
            host._sleep_interruptible(10)
            return True
        raw = json.dumps(public_payload(payload), ensure_ascii=False)
        host._log_raw_llm_output("autonomous_ai", raw)
        decision = host.parser.parse(raw)
        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(plan.plan_id or f"autonomous:{context.turn_seq}")
        grounding_report = self._autonomous_grounding_report(context, plan)
        validator = getattr(host, "ai_autonomous_grounding_validator", None)
        if validator is not None:
            grounding_verdict = validator.validate_surface(
                str(getattr(decision, "text", "") or ""),
                report=grounding_report,
                engine=getattr(host, "source_grounding_engine", None),
            )
            grounding_allowed = grounding_verdict.allowed
            grounding_code = grounding_verdict.violation_code or grounding_verdict.reason
        else:
            legacy_verdict = evaluate_grounded_surface(
                getattr(host, "source_grounding_engine", None),
                str(getattr(decision, "text", "") or ""),
                report=grounding_report,
            )
            grounding_allowed = bool(legacy_verdict.allowed)
            grounding_code = str(legacy_verdict.violation_code or "grounding_blocked")
        if not grounding_allowed:
            # V41: postflight chỉ ghi telemetry. Không được vứt câu đã sinh hoặc
            # kéo autonomous sang fallback chung chung vì một word-marker nhận
            # nhầm claim. Preflight provenance vẫn giữ privacy/evidence boundary.
            host.logger.warning(
                "[grounding gate] autonomous surface risk subject=%s violations=%s; passing through",
                plan.semantics.subject_key,
                grounding_code,
            )
            try:
                setattr(decision, "grounding_risk", {
                    "allowed": False,
                    "violation": grounding_code,
                    "policy": "annotate_and_pass_through",
                })
            except Exception:
                pass
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=context.state, channel="autonomous")
        decision = host._execute_system_action(decision, snapshot=context.perception.snapshot, frame=None)
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            host.ai_state_reducer.submit(StateEvent.from_mechanical_outcome(
                dict(decision.action_result_meta),
                turn_seq=context.turn_seq,
                turn_id=plan.plan_id,
                base_version=host.ai_state_reducer.snapshot().version,
            ))
        text, assistant_meta = self.commit_public(
            decision,
            channel="autonomous",
            turn_seq=context.turn_seq,
        )
        if text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, text)
        if not text:
            self._record_result(plan, result="stage_silence", gate_reason="no_public_text")
            host._sleep_interruptible(10)
            return True

        host.last_autonomous_spoken_at = time.time()
        host._note_autonomous_spoken()
        initiative = getattr(host, "ai_initiative_controller", None)
        if initiative is not None:
            initiative.record_spoken(plan, now=host.last_autonomous_spoken_at, channel="autonomous")
        autonomous_turn_id = f"autonomous:{context.turn_seq}"
        if plan.strategy:
            host.ai_state_reducer.submit(StateEvent.from_pending_strategy(
                PendingStrategyUse(
                    strategy_use_id=f"strategy:{autonomous_turn_id}",
                    turn_seq=context.turn_seq,
                    strategy=plan.strategy,
                    goal=plan.topic,
                    context=tuple(item for item in (plan.motive, plan.value_focus, "autonomous") if str(item or "").strip()),
                    assistant_text=text,
                ),
                base_version=host.ai_state_reducer.snapshot().version,
            ))
        host.ai_post_turn_observer.submit(
            turn_id=autonomous_turn_id,
            turn_seq=context.turn_seq,
            user_text="",
            assistant_text=text,
            recent_history=tuple(host._chat_history_for_llm(limit=8)),
            mechanical_outcomes=(dict(decision.action_result_meta),)
                if isinstance(getattr(decision, "action_result_meta", None), Mapping)
                else (),
            state_summary=context.state.to_dict(),
            assistant_meta=assistant_meta,
            event_kind="autonomous",
        )
        self.trace_store.append("deliberation_result", {
            "turn_seq": context.turn_seq,
            "semantic_signature": plan.semantic_signature,
            "turn_kind": plan.semantics.turn_kind,
            "speech_act": plan.semantics.speech_act,
            "importance": plan.importance,
            "intrusion_risk": plan.intrusion_risk,
            "confidence": plan.confidence,
            "initiative_reason": "allowed",
            "result": "spoken",
            "body_only": False,
        }, now=host.last_autonomous_spoken_at)
        self._record_result(plan, result="spoken", gate_reason="allowed")
        host.logger.info(
            "[ai autonomous] spoke kind=%s act=%s subject=%s text=%s",
            plan.semantics.turn_kind,
            plan.semantics.speech_act,
            plan.semantics.subject_key,
            text,
        )
        host._sleep_interruptible(max(10, host._choose_autonomous_sleep_duration(
            suppressed=False, ti_mode="ai_intention",
        )))
        return True


    def _record_result(self, plan: IntentionPlan, *, result: str, gate_reason: str) -> None:
        """Đẩy metric typed; lỗi quan sát không được làm gãy public turn."""
        observability = getattr(self.host, "observability", None)
        record = getattr(observability, "record_self_turn", None)
        if not callable(record):
            return
        try:
            record(
                semantic_signature=plan.semantic_signature,
                turn_kind=plan.semantics.turn_kind,
                speech_act=plan.semantics.speech_act,
                result=result,
                gate_reason=gate_reason,
                importance=plan.importance,
                intrusion_risk=plan.intrusion_risk,
            )
        except Exception as exc:
            try:
                self.host.logger.debug("[self turn observability] failed: %s", exc)
            except Exception:
                pass

    @staticmethod
    def _runtime_speech_language() -> str:
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


    @staticmethod
    def _runtime_language() -> str:
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


__all__ = ["PerceptionBundle", "SelfTurnBundle", "SelfTurnPipeline"]
