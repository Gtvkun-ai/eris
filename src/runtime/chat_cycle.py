from __future__ import annotations

import os
import re
import time

from runtime.interrupt_reaction_policy import InterruptReactionPolicy
from runtime.source_grounding import SourceGroundingEngine
from runtime.cognition.normalization import normalize_vi
from screen.screen_anaphora_rescue import ScreenAnaphoraRescue


class ChatCycleMixin:
    """Vòng chat mỏng cho Architecture C.

    Module này chỉ quản lý quyền phát loa, burst input và context ngắt lời. Toàn
    bộ hiểu nghĩa, lập kế hoạch và sinh lời nằm ở Cortex V2 + AIChatOrchestrator.
    """

    def _enter_chat_cycle(self) -> None:
        self._chat_last_activity_at = time.time()
        try:
            from runtime.public_lifecycle import lifecycle_for
            lifecycle_for(self).interrupt(reason="new_user_input")
        except Exception as exc:
            self.logger.debug("Public lifecycle interrupt failed: %s", exc)
        supersede_tts = getattr(self, "_supersede_tts_for_new_user_turn", None)
        if callable(supersede_tts):
            try:
                supersede_tts("user_speech_started")
            except Exception as exc:
                self.logger.debug("TTS early barge-in cancel failed: %s", exc)

        discovery = getattr(self, "ai_discovery_runtime", None)
        preempt_discovery = getattr(discovery, "preempt_for_chat", None)
        if callable(preempt_discovery):
            try:
                preempt_discovery(reason="enter_chat_mode")
            except Exception as exc:
                self.logger.debug("Discovery cooperative cancel failed: %s", exc)

        if self.chat_mode:
            return
        cancel_generation = getattr(getattr(self, "llm_service", None), "cancel_pending_requests", None)
        if callable(cancel_generation):
            try:
                cancel_generation(reason="enter_chat_mode")
            except Exception as exc:
                self.logger.debug("LLM cooperative cancel failed: %s", exc)
        self.chat_mode = True
        self.repeated_user_count = 0
        self.last_user_signature = ""
        self.last_user_text_for_semantics = ""
        self.logger.info("Entered chat mode; autonomous is paused for user messages.")

    def _end_chat_cycle(self) -> None:
        if not getattr(self, "chat_mode", False):
            return
        self.chat_mode = False
        self.last_system_action = ""
        self.last_user_signature = ""
        self.last_user_text_for_semantics = ""
        self.last_user_intent = ""
        self.active_conversational_topic = ""
        self.repeated_user_count = 0

        collision_fn = getattr(self, "_note_autonomous_turn_collision", None)
        if not callable(collision_fn):
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")
            return
        try:
            # V66: grace chỉ bảo vệ turn collision, không phải "user vừa nói nên
            # Eris phải im". Self-rhythm ở ExpressionCommitment xử lý mật độ riêng.
            raw_grace = str(os.environ.get("ERIS_POST_CHAT_GRACE_SEC", "2.5") or "2.5").strip()
            grace = max(1.5, float(raw_grace) if raw_grace else 2.5)
            collision_fn(now=time.time(), seconds=grace)
            self.logger.info("Exited chat mode; turn-collision guard %.1fs; self-cognition continues.", grace)
        except TypeError:
            collision_fn(now=time.time())
            self.logger.info("Exited chat mode; turn-collision guard applied.")
        except Exception:
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")

    def _run_chat_cycle(self, user_text: str, *, user_timestamp: float | None = None) -> None:
        cycle_start = time.time() if user_timestamp is None else float(user_timestamp)
        user_text = str(user_text or "").strip()
        if not user_text:
            return

        # User turn không "khởi động lại" tâm trí. Nó đẩy cùng TemporalMind
        # đang chạy nền sang trạng thái foreground và xóa quiet cooldown.
        temporal = getattr(self, "temporal_mind", None)
        if temporal is None:
            try:
                from runtime.temporal_mind import TemporalMind
                temporal = TemporalMind()
                self.temporal_mind = temporal
            except Exception:
                temporal = None
        note_user = getattr(temporal, "note_user_turn", None)
        if callable(note_user):
            try:
                note_user(now=cycle_start, focus_key="direct_chat")
            except Exception as exc:
                self.logger.debug("[temporal mind] user turn update failed: %s", exc)
        if getattr(self, "_chat_processing", False):
            self._queue_chat_burst_event(user_text, cycle_start)
            return

        self._chat_processing = True
        lifecycle_turn_id = f"chat:{int(cycle_start * 1000)}"
        self._active_public_lifecycle_turn_id = lifecycle_turn_id
        try:
            from runtime.public_lifecycle import lifecycle_for
            lifecycle_for(self).begin(
                turn_id=lifecycle_turn_id,
                channel="chat",
                reason="chat_composing",
                received=True,
            )
        except Exception as exc:
            self.logger.debug("Public lifecycle begin failed: %s", exc)
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            clock.mark_user_turn(cycle_start)
            clock.mark_generation_started(cycle_start)
        try:
            user_text = self._merge_rapid_chat_burst(user_text, first_timestamp=cycle_start)
            if not user_text:
                return
            self.current_stage_user_text = user_text

            speech_interrupt_event = None
            consume_interrupt = getattr(self, "_consume_speech_interrupt_event", None)
            if callable(consume_interrupt):
                speech_interrupt_event = consume_interrupt()

            speech_interrupt_reaction = None
            speech_interrupt_context = ""
            if speech_interrupt_event is not None:
                try:
                    policy = getattr(self, "interrupt_reaction_policy", None) or InterruptReactionPolicy()
                    self.interrupt_reaction_policy = policy
                    speech_interrupt_reaction = policy.decide(speech_interrupt_event)
                    speech_interrupt_context = speech_interrupt_reaction.to_prompt_context(speech_interrupt_event)
                except Exception as exc:
                    self.logger.debug("[interrupt] reaction policy failed: %s", exc)
                    render = getattr(speech_interrupt_event, "to_prompt_context", None)
                    speech_interrupt_context = render() if callable(render) else ""

            previous_public_turn = self._link_previous_public_turn_for_chat(cycle_start)
            previous_public_context = self._previous_public_turn_context(previous_public_turn)
            self._run_chat_cycle_inner(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
                speech_interrupt_context=speech_interrupt_context,
                speech_interrupt_event=speech_interrupt_event,
                speech_interrupt_reaction=speech_interrupt_reaction,
            )
        finally:
            if clock is not None:
                clock.mark_generation_finished()
            # PDF annotation, pages 17-19: acceptance is based on perceived
            # turn latency, not a cherry-picked provider timing.  Emit the full
            # user-turn duration so P50/P95 can be computed from production
            # JSONL without reconstructing timestamps by hand.
            try:
                from runtime.observability import GLOBAL_OBSERVABILITY

                from runtime.conversation.projection import infer_turn_category
                category = infer_turn_category(self)
                GLOBAL_OBSERVABILITY.observe(
                    "user_turn_latency_ms",
                    max(0.0, (time.time() - cycle_start) * 1000.0),
                    tags={"channel": "chat", "turn_category": category},
                )
            except Exception:
                pass
            try:
                from runtime.public_lifecycle import lifecycle_for
                lifecycle = lifecycle_for(self)
                state = lifecycle.snapshot()
                if state.turn_id == lifecycle_turn_id and state.state == "COMPOSING":
                    self.logger.warning(
                        "[chat-cycle] lifecycle vẫn COMPOSING sau khi cycle kết thúc "
                        "(no_public_commit). turn_id=%s — _send_decision_to_body bị miss.",
                        lifecycle_turn_id,
                    )
                    lifecycle.transition("DEGRADED", turn_id=lifecycle_turn_id, reason="no_public_commit")
            except Exception:
                pass
            self._temporal_last_user_turn_at = cycle_start
            self.current_stage_user_text = ""
            self.current_conversation_lane = None
            self._chat_processing = False

    def _run_chat_cycle_inner(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn=None,
        speech_interrupt_context: str = "",
        speech_interrupt_event=None,
        speech_interrupt_reaction=None,
    ) -> None:
        # Explicit output boundary được áp trước model call. Nó chỉ đóng/mở cửa
        # public expression; cognition/initiative của Eris không bị tắt theo.
        self._expression_boundary_preference_context = ""
        try:
            from runtime.expression_boundary_preference import apply_expression_boundary_preference
            preference = apply_expression_boundary_preference(self, user_text)
            if preference.applied:
                self._expression_boundary_preference_context = preference.prompt_context
        except Exception as exc:
            self.logger.debug("[expression boundary] detector failed: %s", exc)

        orchestrator = getattr(self, "ai_chat_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error("[architecture C] chat unavailable: runtime bootstrap failed; legacy path removed")
            return
        # WorldState owns the normalized user intent and conversation edge.
        # Downstream chat/subject/observer/seed lanes read projections from this
        # same state instead of reclassifying the utterance independently.
        try:
            from runtime.world_state import ensure_world_state_service
            ensure_world_state_service(self).observe_user_turn(user_text, now=cycle_start)
        except Exception as exc:
            self.logger.debug("[world state] user-turn ingest failed: %s", exc)

        orchestrator.run(
            user_text,
            cycle_start=cycle_start,
            previous_public_context=previous_public_context,
            previous_public_turn=previous_public_turn,
            speech_interrupt_context=speech_interrupt_context,
            speech_interrupt_event=speech_interrupt_event,
            speech_interrupt_reaction=speech_interrupt_reaction,
        )

    def _queue_chat_burst_event(self, user_text: str, timestamp: float | None = None) -> None:
        text = str(user_text or "").strip()
        if not text:
            return
        item = (time.time() if timestamp is None else float(timestamp), text)
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            self._chat_burst_queue = [item]
            return
        with lock:
            self._chat_burst_queue.append(item)

    def _merge_rapid_chat_burst(self, first_text: str, *, first_timestamp: float) -> str:
        collected = [(first_timestamp, str(first_text or "").strip())]
        collected.extend(self._pop_queued_chat_events())
        collected.extend(self._poll_ready_chat_events())
        if len(collected) <= 1:
            return collected[0][1]

        window = float(getattr(self, "rapid_burst_window", 1.2) or 0.0)
        quiet_until = time.time() + window
        while window > 0.0 and time.time() < quiet_until:
            time.sleep(0.05)
            new_events = self._pop_queued_chat_events()
            new_events.extend(self._poll_ready_chat_events())
            if new_events:
                collected.extend(new_events)
                quiet_until = time.time() + window
        collected.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in collected if text)

    def _pop_queued_chat_events(self) -> list[tuple[float, str]]:
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            return []
        with lock:
            queued = list(getattr(self, "_chat_burst_queue", []) or [])
            self._chat_burst_queue = []
        return [(float(ts), str(text or "").strip()) for ts, text in queued if str(text or "").strip()]

    def _poll_ready_chat_events(self) -> list[tuple[float, str]]:
        events: list[tuple[float, str]] = []
        poll = getattr(getattr(self, "transport", None), "poll_json", None)
        if not callable(poll):
            return events
        while True:
            msg = poll()
            if not msg:
                return events
            if msg.get("type") == "chat":
                text = str(msg.get("message", "") or "").strip()
                if text:
                    events.append((float(msg.get("timestamp") or time.time()), text))
                continue
            self._handle_incoming(msg)

    def _previous_assistant_text_for_screen_route(self, previous_public_turn=None) -> str:
        public_turn = previous_public_turn
        if public_turn is None:
            public_turn = getattr(getattr(self, "reply_context", None), "previous_public_turn", None)
        if public_turn is None:
            # Reply window chung chỉ 30 giây, hợp cho semantic correction nhưng
            # hơi ngắn khi TTS vừa nói xong rồi user mới đáp ``tự xem đi``. OCR
            # anaphora có cửa sổ riêng rộng hơn; nó chỉ mượn câu trước làm query,
            # không tự coi nội dung câu đó là bằng chứng màn hình.
            ledger = getattr(self, "public_turn_ledger", None)
            latest = getattr(ledger, "latest_visible_before", None)
            if callable(latest):
                try:
                    candidate = latest(time.time())
                    raw_window = str(os.environ.get("ERIS_SCREEN_ANAPHORA_WINDOW_SEC", "90") or "90")
                    window = max(30.0, min(240.0, float(raw_window)))
                    age = time.time() - float(getattr(candidate, "timestamp", 0.0) or 0.0)
                    if candidate is not None and 0.0 <= age <= window:
                        public_turn = candidate
                except Exception:
                    public_turn = None
        return " ".join(str(getattr(public_turn, "text", "") or "").split()).strip()

    def _ensure_chat_perception_coordinator(self):
        """Return the single chat perception coordinator used by every chat path.

        Bootstrap normally creates it, but tests/legacy launchers can construct the
        runtime out of order.  Lazily recovering here keeps one perception state
        instead of silently falling back to the old duplicated routing logic.
        Structured bridge sources are registered idempotently on every access so
        sources created after bootstrap (for example chess/browser/IDE bridges)
        immediately join the same evidence ladder.
        """
        coordinator = getattr(self, "chat_perception_coordinator", None)
        if coordinator is None:
            try:
                from runtime.chat_perception import ChatPerceptionCoordinator
                coordinator = ChatPerceptionCoordinator(
                    screen_evidence_store=getattr(self, "screen_evidence_store", None),
                    screen_text_worker=getattr(self, "screen_text_worker", None),
                    screen_relevance_router=getattr(self, "screen_relevance_router", None),
                    logger=getattr(self, "logger", None),
                )
                self.chat_perception_coordinator = coordinator
                self._chat_pending_vision_escalation = coordinator.pending_vision
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.debug("[chat perception] lazy coordinator init failed: %s", exc)
                return None
        try:
            coordinator.update_dependencies(
                screen_evidence_store=getattr(self, "screen_evidence_store", None),
                screen_text_worker=getattr(self, "screen_text_worker", None),
                screen_relevance_router=getattr(self, "screen_relevance_router", None),
            )
        except Exception:
            pass

        provider = getattr(coordinator, "structured_provider", None)
        register = getattr(provider, "register", None)
        if callable(register):
            # Keep this domain-agnostic at the contract boundary.  These are the
            # currently known late-bound bridges; any future source can also
            # expose itself through ``structured_evidence_sources``.
            sources = [
                getattr(self, "chess_bridge_service", None),
                getattr(self, "semantic_tutor_runtime", None),
                getattr(self, "ide_bridge_service", None),
                getattr(self, "browser_bridge_service", None),
            ]
            extra = getattr(self, "structured_evidence_sources", ())
            if isinstance(extra, dict):
                sources.extend(extra.values())
            elif isinstance(extra, (tuple, list, set)):
                sources.extend(extra)
            for source in sources:
                if source is None or not str(getattr(source, "structured_source_id", "") or "").strip():
                    continue
                try:
                    register(source)
                except Exception:
                    continue
        return coordinator

    def _looks_like_screen_vision_request(
        self,
        user_text: str,
        *,
        previous_assistant_text: str = "",
    ) -> bool:
        # Typed intent is authoritative for environment-vs-screen routing.  The
        # perception coordinator remains a compatibility/anaphora fallback.
        try:
            from runtime.intent_model import normalize_intent
            intent = normalize_intent(user_text)
            self.current_world_intent = intent
            if intent.environment_sufficient:
                return False
            if intent.domain == "screen":
                return True
        except Exception:
            intent = None
        coordinator = self._ensure_chat_perception_coordinator()
        looks = getattr(coordinator, "looks_like_screen_request", None)
        if callable(looks):
            try:
                return bool(looks(user_text, previous_assistant_text=previous_assistant_text))
            except Exception:
                pass
        resolution = ScreenAnaphoraRescue().resolve(
            user_text,
            previous_assistant_text=previous_assistant_text,
            explicit_reference=False,
        )
        return bool(resolution.references_screen)

    def _chat_current_environment_labels(self, snapshot=None) -> tuple[str, ...]:
        """Lấy identity/semantic labels của foreground hiện tại từ canonical WorldState."""
        labels: list[str] = []
        payload = self._chat_snapshot_machine_context(snapshot)
        for key in ("active_app", "active_window", "active_window_title", "window_title", "process_name"):
            value = str(payload.get(key, "") or "").strip()
            if value:
                labels.append(value)
        try:
            from runtime.environment_awareness import ensure_environment_awareness_hub
            from runtime.world_state import ensure_world_state_service
            ensure_environment_awareness_hub(self).refresh(
                machine_snapshot=snapshot, now=time.time(), source="direct_chat_entity_bind"
            )
            world = ensure_world_state_service(self).refresh_from_host(now=time.time())
            env = world.environment_compatibility_view(now=time.time())
            for key in (
                "focused_app", "focused_process", "focused_object",
                "activity", "task_hint", "phase", "last_action", "last_outcome",
            ):
                value = str(env.get(key, "") or "").strip()
                if value and value.casefold() not in {"unknown", "none"}:
                    labels.append(value)
        except Exception as exc:
            self.logger.debug("[deep environment chat] entity labels unavailable: %s", exc)
        return tuple(dict.fromkeys(labels))

    def _looks_like_deep_environment_request(self, user_text: str, snapshot=None) -> bool:
        """Typed intent + entity binding cho câu hỏi trạng thái foreground hiện tại."""
        try:
            from runtime.intent_model import (
                looks_like_entity_status_question,
                matches_current_environment_entity_status,
                normalize_intent,
            )
            intent = normalize_intent(user_text)
            self.current_world_intent = intent
            if bool(intent.environment_sufficient and intent.operation == "inspect_current_state"):
                return True
            # Chú thích VI: câu “X đang bị sao thế?” không chứa marker màn hình.
            # Chỉ bind nó vào Deep Environment khi X khớp app/process/window/task
            # thật đang active; tuyệt đối không hardcode GitPilot hay tên IDE.
            if looks_like_entity_status_question(user_text):
                labels = self._chat_current_environment_labels(snapshot)
                return matches_current_environment_entity_status(user_text, labels)
            return False
        except Exception:
            return False

    @staticmethod
    def _chat_snapshot_machine_context(snapshot) -> dict[str, object]:
        payload: dict[str, object] = {}
        to_context = getattr(snapshot, "to_machine_context", None)
        if callable(to_context):
            try:
                raw = to_context() or {}
                if isinstance(raw, dict):
                    payload.update(raw)
            except Exception:
                pass
        if isinstance(snapshot, dict):
            payload.update(snapshot)
        return payload

    def _chat_deep_environment_grounding_facts(
        self,
        snapshot,
        user_text: str = "",
    ) -> tuple[dict[str, object], ...]:
        """Ground direct chat from the canonical WorldState projection."""
        try:
            # Refresh the sensor compatibility projection first, then read the
            # shared world model. EnvironmentAwarenessHub publishes into
            # WorldState; chat never rebuilds task/activity semantics itself.
            from runtime.environment_awareness import ensure_environment_awareness_hub
            from runtime.world_state import ensure_world_state_service
            ensure_environment_awareness_hub(self).refresh(
                machine_snapshot=snapshot, now=time.time(), source="direct_chat"
            )
            world = ensure_world_state_service(self).refresh_from_host(now=time.time())
            env = world.environment_compatibility_view(now=time.time())
        except Exception as exc:
            self.logger.debug("[deep environment chat] world state unavailable: %s", exc)
            return ()

        facts: list[dict[str, object]] = []
        focus_parts: list[str] = []
        if env.get("focused_app"):
            focus_parts.append(f"app={str(env.get('focused_app'))[:120]}")
        if env.get("focused_process"):
            focus_parts.append(f"process={str(env.get('focused_process'))[:120]}")
        if env.get("focused_object"):
            focus_parts.append(f"window_or_object={str(env.get('focused_object'))[:220]}")
        if focus_parts:
            facts.append({
                "id": f"world_state:focus:r{int(env.get('revision', 0) or 0)}",
                "source": "runtime_state",
                "claim": "Deep Environment current focus: " + "; ".join(focus_parts) + ".",
                "confidence": min(0.98, max(0.72, float(env.get("confidence", 0.0) or 0.0))),
                "grounded": True,
                "stale": not bool(env.get("fresh", False)),
                "kind": "deep_environment_focus",
                "tags": ["runtime_state", "deep_environment", "world_state", "fact"],
            })
        semantic = []
        for key, label in (("activity", "activity"), ("task_hint", "task"), ("phase", "phase"), ("last_action", "last_action"), ("last_outcome", "last_outcome")):
            value = str(env.get(key, "") or "").strip()
            if value and value.casefold() not in {"unknown", "none"}:
                semantic.append(f"{label}={value[:220]}")
        if semantic:
            facts.append({
                "id": f"world_state:task:r{int(env.get('revision', 0) or 0)}",
                "source": "runtime_state",
                "claim": "Deep Environment semantic interpretation: " + "; ".join(semantic) + ".",
                "confidence": min(0.92, max(0.55, float(env.get("confidence", 0.0) or 0.0))),
                "grounded": True,
                "stale": not bool(env.get("fresh", False)),
                "kind": "deep_environment_task",
                "tags": ["runtime_state", "deep_environment", "world_state", "interpretation", "task_state"],
            })
        if facts and self._looks_like_deep_environment_request(user_text, snapshot):
            self.logger.info(
                "[deep environment chat] world_revision=%d env_revision=%d facts=%d app=%s task=%s phase=%s age=%.1fs",
                int(getattr(world, "revision", 0) or 0), int(env.get("revision", 0) or 0), len(facts),
                str(env.get("focused_app") or "unknown"), str(env.get("task_hint") or env.get("activity") or "unknown"),
                str(env.get("phase") or "unknown"), float(env.get("age_seconds", 9999.0) or 9999.0),
            )
        return tuple(facts)

    def _deep_environment_can_answer(self, user_text: str, snapshot=None) -> bool:
        if not self._looks_like_deep_environment_request(user_text, snapshot):
            return False
        facts = self._chat_deep_environment_grounding_facts(snapshot, user_text)
        if not facts:
            return False
        normalized = normalize_vi(user_text)
        # "đang code gì" cần ít nhất task hint/activity hoặc focused object;
        # app identity đơn thuần chưa đủ để tự bịa nội dung code.
        asks_exact_work = any(
            normalize_vi(marker) in normalized
            for marker in ("đang code gì", "tôi đang code gì", "tui đang code gì", "what am i working on")
        )
        if asks_exact_work:
            return any(
                str(item.get("kind", "")) == "deep_environment_task"
                and not bool(item.get("stale", False))
                for item in facts
            )
        return True

    def _chat_ambient_screen_blocks(self) -> tuple[object, ...]:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "ambient_screen_blocks", None)
        if callable(fn):
            try:
                return tuple(fn(max_age_seconds=8.0, max_items=8) or ())
            except Exception:
                pass
        return ()

    @staticmethod
    def _merge_chat_screen_blocks(*groups) -> tuple[object, ...]:
        try:
            from runtime.chat_perception import ChatPerceptionCoordinator
            return ChatPerceptionCoordinator.merge_screen_blocks(*groups)
        except Exception:
            merged, seen = [], set()
            for group in groups:
                for block in tuple(group or ()):
                    key = str(getattr(block, "block_id", "") or getattr(block, "text", "") or id(block))
                    if key in seen:
                        continue
                    seen.add(key); merged.append(block)
            return tuple(merged)

    def _looks_like_chess_context_request(self, user_text: str) -> bool:
        """Bind chat vào state cờ typed thay vì săn vài word marker cứng."""

        bridge = getattr(self, "chess_bridge_service", None)
        matches = getattr(bridge, "matches_turn", None)
        if not callable(matches):
            return False
        try:
            # Extension gửi snapshot theo biến động bàn cờ. Tuổi của event không
            # đồng nghĩa FEN sai: nếu engagement vẫn active và chưa có snapshot
            # mới thì đó vẫn là vị trí hiện tại, kể cả user suy nghĩ vài phút.
            return bool(matches(user_text))
        except Exception:
            return False

    def _chat_structured_grounding_facts(self, user_text: str) -> tuple[object, ...]:
        bridge = getattr(self, "chess_bridge_service", None)
        evidence_fn = getattr(bridge, "current_grounding_evidence", None)
        if not callable(evidence_fn):
            return ()
        relevant = self._looks_like_chess_context_request(user_text)
        move_request = False
        wants_move = getattr(bridge, "wants_move_suggestion", None)
        if relevant and callable(wants_move):
            try:
                move_request = bool(wants_move(user_text))
            except Exception:
                move_request = False
        max_age = 300.0 if relevant else 30.0
        try:
            try:
                return tuple(
                    evidence_fn(
                        max_age_seconds=max_age,
                        relevant_to_turn=relevant,
                        request_move_suggestion=move_request,
                    ) or ()
                )
            except TypeError:
                # Structured provider cũ chưa có cờ request_move_suggestion.
                return tuple(
                    evidence_fn(max_age_seconds=max_age, relevant_to_turn=relevant) or ()
                )
        except Exception as exc:
            self.logger.debug("[chess grounding] evidence unavailable: %s", exc)
            return ()

    def _chat_window_identity(self) -> tuple[str, int]:
        store = getattr(self, "screen_evidence_store", None)
        snapshot_fn = getattr(store, "snapshot", None)
        if not callable(snapshot_fn):
            return "", 0
        try:
            snapshot = snapshot_fn()
        except Exception:
            return "", 0
        window = getattr(snapshot, "window", None)
        key = "|".join(
            (
                str(getattr(window, "process_name", "") or "").strip().lower(),
                str(getattr(window, "hwnd", 0) or 0),
                str(getattr(window, "title", "") or "").strip().lower(),
            )
        )
        return key, int(getattr(snapshot, "revision", 0) or 0)

    def _chat_runtime_grounding_facts(self, snapshot, user_text: str) -> tuple[dict[str, object], ...]:
        """Cấp runtime facts tươi cho chat writer.

        System clock là sensor local có thẩm quyền. Weather chỉ được thêm khi
        telemetry/tool thật sự có dữ liệu; thiếu weather thì prompt cấm đoán bừa.
        OCR/vision giữ đường riêng trong ``screen_facts`` và chess giữ đường
        ``structured_facts`` để provenance không bị trộn thành một nồi súp.
        """
        from datetime import datetime

        now = datetime.now().astimezone()
        facts: list[dict[str, object]] = [{
            "id": f"runtime_clock:{now.strftime('%Y%m%d%H%M')}",
            "source": "runtime_state",
            "claim": (
                f"System local time is {now.strftime('%H:%M:%S')} on "
                f"{now.strftime('%Y-%m-%d')}; timezone={now.tzname() or ''}."
            ),
            "confidence": 1.0,
            "grounded": True,
            "stale": False,
            "kind": "system_clock",
            "captured_at": now.timestamp(),
            "tags": ["runtime_state", "system_clock", "local_sensor"],
        }]

        payload = self._chat_snapshot_machine_context(snapshot)
        for key in ("weather", "weather_condition", "temperature", "temperature_c", "weather_summary"):
            value = getattr(snapshot, key, None)
            if value not in (None, ""):
                payload.setdefault(key, value)

        weather = payload.get("weather") or payload.get("weather_summary") or payload.get("weather_condition")
        temperature = payload.get("temperature_c", payload.get("temperature"))
        if weather not in (None, "") or temperature not in (None, ""):
            facts.append({
                "id": f"runtime_weather:{int(now.timestamp() // 60)}",
                "source": "runtime_state",
                "claim": f"Weather telemetry: condition={weather or 'unknown'}; temperature={temperature if temperature not in (None, '') else 'unknown'}.",
                "confidence": 0.95,
                "grounded": True,
                "stale": False,
                "kind": "weather",
                "captured_at": now.timestamp(),
                "tags": ["runtime_state", "weather", "telemetry"],
            })

        # Deep Environment là sensor semantic local có cấu trúc. Nó luôn được
        # đưa vào chat như ambient runtime evidence; SourceGroundingEngine sẽ chỉ
        # nâng nó thành primary khi user hỏi trạng thái máy/task hiện tại.
        facts.extend(self._chat_deep_environment_grounding_facts(snapshot, user_text))

        preference = str(getattr(self, "_expression_boundary_preference_context", "") or "").strip()
        if preference:
            facts.append({
                "id": f"runtime_policy:expression_boundary:{int(now.timestamp())}",
                "source": "runtime_state",
                "claim": preference,
                "confidence": 1.0,
                "grounded": True,
                "stale": False,
                "kind": "runtime_policy",
                "tags": ["runtime_state", "policy_applied", "user_directive"],
            })
        return tuple(facts)

    def _chat_active_chess_engagement_id(self) -> str:
        facts = self._chat_structured_grounding_facts("")
        if not facts:
            return ""
        item = facts[0]
        if isinstance(item, dict):
            return str(item.get("engagement_id", "") or "")
        return str(getattr(item, "engagement_id", "") or "")

    def _queue_next_turn_vision(self, *, reason: str, user_text: str) -> None:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "queue_next_turn_vision", None)
        if callable(fn):
            fn(reason=reason, user_text=user_text)
            self._chat_pending_vision_escalation = coordinator.pending_vision

    def _consume_next_turn_vision(self, *, user_text: str) -> bool:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "consume_next_turn_vision", None)
        return bool(fn(user_text=user_text)) if callable(fn) else False

    def _ocr_needs_next_turn_vision(self, route) -> bool:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "ocr_needs_next_turn_vision", None)
        return bool(fn(route)) if callable(fn) else False

    def _ensure_screen_text_worker_for_request(self) -> None:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "ensure_screen_text_worker", None)
        if callable(fn):
            fn()

    def _refresh_screen_text_for_chat_request(self) -> bool:
        coordinator = self._ensure_chat_perception_coordinator()
        fn = getattr(coordinator, "refresh_screen_text", None)
        return bool(fn()) if callable(fn) else False


    def _capture_screen_frame_for_chat(self, user_text: str, *, previous_public_turn=None) -> str:
        started = time.perf_counter()
        self._chat_screen_route_decision = None
        self._chat_screen_text_evidence = ()
        self._chat_screen_capture_present = False
        self._chat_screen_capture_interpreted = False

        snapshot_for_environment = getattr(self, "_chat_snapshot_for_vision", None)
        if self._deep_environment_can_answer(user_text, snapshot_for_environment):
            coordinator = self._ensure_chat_perception_coordinator()
            pending = getattr(coordinator, "pending_vision", None)
            clear = getattr(pending, "clear", None)
            if callable(clear):
                clear()
            self.logger.info("[deep environment route] WorldState structured environment selected; OCR/vision skipped")
            return ""

        coordinator = self._ensure_chat_perception_coordinator()
        if coordinator is None:
            self.logger.warning("[chat perception] coordinator unavailable; screen perception degraded")
            return ""
        try:
            coordinator.update_dependencies(
                screen_evidence_store=getattr(self, "screen_evidence_store", None),
                screen_text_worker=getattr(self, "screen_text_worker", None),
                screen_relevance_router=getattr(self, "screen_relevance_router", None),
            )
        except Exception:
            pass
        previous_assistant_text = self._previous_assistant_text_for_screen_route(previous_public_turn)
        capture_fn = getattr(getattr(self, "telemetry_service", None), "capture_screen_frame_data_uri", None)
        snapshot = getattr(self, "_chat_snapshot_for_vision", None)

        def _interpret(data_uri: str):
            if snapshot is None:
                return getattr(self, "last_vision_grounding_report", None)
            self._refresh_screen_facts_from_data_uri(
                data_uri=data_uri, snapshot=snapshot, channel="chat",
                user_text=user_text, force_refresh=True,
            )
            return getattr(self, "last_vision_grounding_report", None)

        try:
            result = coordinator.prepare_turn(
                user_text,
                previous_assistant_text=previous_assistant_text,
                force_chat_vision=False,
                capture_fn=capture_fn,
                interpret_fn=_interpret,
            )
        except Exception as exc:
            self.logger.warning("[chat perception] prepare turn failed: %s", exc)
            return ""

        self._chat_screen_route_decision = result.route
        self._chat_screen_text_evidence = tuple(result.screen_blocks or ())
        self._chat_screen_capture_present = bool(result.capture_present)
        self._chat_screen_capture_interpreted = bool(result.capture_interpreted)
        self._chat_pending_vision_escalation = coordinator.pending_vision
        elapsed = max(0.0, (time.perf_counter() - started) * 1000.0)
        self.logger.info(
            "[chat perception] unified elapsed=%.0fms mode=%s blocks=%d structured=%s captured=%s interpreted=%s",
            elapsed, str(getattr(result.route, "mode", "none") or "none"),
            len(tuple(result.screen_blocks or ())), int(bool(result.structured_relevant)),
            int(bool(result.capture_present)), int(bool(result.capture_interpreted)),
        )
        return str(result.data_uri or "")

    def _chat_vision_status_prompt_context(self, *, screen_image_data_uri: str = "") -> str:
        """Prompt guard cho stance khi có frame nhưng chưa có grounded vision claim.

        PATCH: lượt chat có thể đã capture screenshot nhưng compressor/grounding
        vẫn trả grounded_claims=0. Khi đó public writer không được nói như thể
        đã thấy màn hình. Nó chỉ được nói thật: đã thử lấy frame, bằng chứng chưa
        đủ; nếu có OCR evidence thì chỉ nhận là đọc được một phần chữ.
        """

        if not str(screen_image_data_uri or "").strip():
            return ""

        route = getattr(self, "_chat_screen_route_decision", None)
        if not bool(getattr(route, "references_screen", False)):
            return ""

        report = getattr(self, "last_vision_grounding_report", None)
        grounded = tuple(getattr(report, "grounded_claims", ()) or ()) if report is not None else ()
        if grounded:
            return ""

        text_evidence_count = len(tuple(getattr(self, "_chat_screen_text_evidence", ()) or ()))
        return (
            "[VISION_STATUS]\n"
            "fresh_screen_capture: yes\n"
            "grounded_visual_claims: 0\n"
            f"screen_text_evidence_count: {text_evidence_count}\n"
            "epistemic_status: screenshot captured, but no visual claim passed grounding.\n"
            "rule: OCR/window-title text is partial text evidence only; it does not prove the full scene or user activity.\n"
            "required_stance: Không được nói hoặc ám chỉ 'tôi thấy', 'tôi thấy bàn cờ', hay bất kỳ khẳng định thị giác tương đương nào. "
            "You may cautiously quote a specific OCR/title fragment as partial evidence, explicitly hedge uncertainty, or ask the user to confirm.\n"
            "[/VISION_STATUS]"
        )


    def _chat_source_grounding_screen_facts(self, snapshot, *, screen_image_data_uri: str = "") -> tuple[object, ...]:
        coordinator = self._ensure_chat_perception_coordinator()
        build = getattr(coordinator, "build_screen_grounding_items", None)
        if not callable(build):
            return ()
        return tuple(build(
            screen_blocks=tuple(getattr(self, "_chat_screen_text_evidence", ()) or ()),
            route=getattr(self, "_chat_screen_route_decision", None),
            vision_report=getattr(self, "last_vision_grounding_report", None),
            screen_image_data_uri=screen_image_data_uri,
            capture_interpreted=bool(getattr(self, "_chat_screen_capture_interpreted", False)),
        ) or ())

    @staticmethod
    def _chat_screen_grounding_items_stale(items: tuple[object, ...]) -> bool:
        try:
            from runtime.chat_perception import ChatPerceptionCoordinator
            return ChatPerceptionCoordinator.grounding_items_stale(items)
        except Exception:
            return False

    def _build_chat_source_grounding_report(
        self, *, user_text: str, frame, snapshot, memory_resonance=None,
        screen_image_data_uri: str = "",
    ):
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            self.source_grounding_engine = engine
        screen_items = self._chat_source_grounding_screen_facts(
            snapshot, screen_image_data_uri=screen_image_data_uri,
        )
        return engine.analyze(
            user_text,
            frame=frame,
            screen_facts=screen_items,
            screen_facts_stale=self._chat_screen_grounding_items_stale(screen_items),
            structured_facts=self._chat_structured_grounding_facts(user_text),
            runtime_facts=self._chat_runtime_grounding_facts(snapshot, user_text),
            memory_packet=memory_resonance,
            runtime_state=snapshot,
            allow_web=False,
            attach_to_frame=True,
        )

    def _log_chat_source_grounding(self, report) -> None:
        if report is None:
            return
        self.logger.info(
            "[source grounding] grounding_source=%s | preempt_mode=%s | missing=%s | allowed=%s | cap=%.2f | memory_answer=%s | warnings=%s",
            getattr(report, "grounding_source", "unknown"),
            getattr(report, "preempt_mode", "") or "none",
            ",".join(getattr(report, "missing_evidence", ()) or ()) or "none",
            ",".join(getattr(report, "allowed_sources", ()) or ()) or "none",
            float(getattr(report, "confidence_cap", 0.0) or 0.0),
            int(bool(getattr(report, "memory_answer_allowed", True))),
            ",".join(getattr(report, "warnings", ()) or ()) or "none",
        )


__all__ = ["ChatCycleMixin"]
