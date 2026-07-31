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

        block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
        if not callable(block_fn):
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")
            return
        try:
            raw_grace = str(os.environ.get("ERIS_POST_CHAT_GRACE_SEC", "18") or "18").strip()
            grace = max(8.0, float(raw_grace) if raw_grace else 18.0)
            block_fn(now=time.time(), seconds=grace)
            self.logger.info("Exited chat mode; autonomous blocked for %.0fs (post-chat grace).", grace)
        except TypeError:
            block_fn(now=time.time())
            self.logger.info("Exited chat mode; autonomous grace applied.")
        except Exception:
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")

    def _run_chat_cycle(self, user_text: str, *, user_timestamp: float | None = None) -> None:
        cycle_start = time.time() if user_timestamp is None else float(user_timestamp)
        user_text = str(user_text or "").strip()
        if not user_text:
            return
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

                frame = dict(getattr(self, "last_semantic_frame", {}) or {})
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
        # Directive sản phẩm rõ ràng được áp trước model call. Nhờ vậy Surface
        # nhận context "đã bật" và không đẩy việc nghĩ nội dung ngược lại user.
        self._autonomous_surface_preference_context = ""
        try:
            from runtime.autonomous_surface_preference import apply_autonomous_surface_preference
            preference = apply_autonomous_surface_preference(self, user_text)
            if preference.applied:
                self._autonomous_surface_preference_context = preference.prompt_context
        except Exception as exc:
            self.logger.debug("[autonomous preference] detector failed: %s", exc)

        orchestrator = getattr(self, "ai_chat_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error("[architecture C] chat unavailable: runtime bootstrap failed; legacy path removed")
            return
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

    def _looks_like_screen_vision_request(
        self,
        user_text: str,
        *,
        previous_assistant_text: str = "",
    ) -> bool:
        normalized = normalize_vi(user_text)
        if not normalized:
            return False
        raw_lower = str(user_text or "").lower()
        if re.search(r"(?<!\w)bàn(?!\w)", raw_lower):
            return True
        direct_terms = tuple(
            normalize_vi(item)
            for item in (
                "màn hình", "trên màn hình", "screenshot", "screen", "vision",
                "nhìn màn hình", "xem màn hình",
                "nhìn màn hình tui", "nhìn màn hình tôi",
                "em nhìn màn hình", "em xem màn hình",
                "look at this", "this screen",
                "xem đi", "bạn xem đi", "tôi đang code gì", "đang code gì",
                "xem được tui làm gì", "xem được tôi làm gì", "thấy được tui làm gì", "thấy được tôi làm gì",
                "em không xem được", "không xem được tui làm gì", "không xem được tôi làm gì",
                "biết tui làm gì", "biết tôi làm gì",
                "đoạn đang mở", "file đang mở", "đang hiện gì", "lỗi này trên màn hình",
                # Yêu cầu model tự nhìn vào ảnh — không tìm chữ qua OCR.
                "tự xem", "tự nhìn", "tự phân tích", "xem thử đi", "nhìn thử đi",
                "xem giúp", "nhìn giúp", "em xem đi", "em nhìn đi",
                "phân tích màn hình", "look at", "take a look", "check the screen",
                # PATCH: follow-up/phàn nàn về vision phải giữ mode màn hình.
                "mù vision", "còn mù vision", "em còn mù vision",
                "không nhìn được", "không thấy được", "không thấy gì",
            )
        )
        if any(term and term in normalized for term in direct_terms):
            return True
        resolution = ScreenAnaphoraRescue().resolve(
            user_text,
            previous_assistant_text=previous_assistant_text,
            explicit_reference=False,
        )
        return bool(resolution.references_screen)

    def _chat_ambient_screen_blocks(self) -> tuple[object, ...]:
        """Lấy OCR/UIA cache cho mọi lượt chat, không cưỡng bức OCR lại."""

        store = getattr(self, "screen_evidence_store", None)
        ambient = getattr(store, "ambient_blocks", None)
        if callable(ambient):
            try:
                return tuple(ambient(max_age_seconds=8.0, max_items=8) or ())
            except Exception as exc:
                self.logger.debug("[screen text] ambient cache read failed: %s", exc)
        snapshot_fn = getattr(store, "snapshot", None)
        if not callable(snapshot_fn):
            return ()
        try:
            snapshot = snapshot_fn()
        except Exception:
            return ()
        if bool(getattr(snapshot, "privacy_blocked", False)):
            return ()
        now = time.time()
        blocks = [
            block
            for block in tuple(getattr(snapshot, "blocks", ()) or ())
            if now - float(getattr(block, "captured_at", 0.0) or 0.0) <= 8.0
            and str(getattr(block, "text", "") or "").strip()
        ]
        blocks.sort(
            key=lambda block: (
                float(getattr(block, "confidence", 0.0) or 0.0),
                float(getattr(block, "captured_at", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return tuple(blocks[:8])

    @staticmethod
    def _merge_chat_screen_blocks(*groups) -> tuple[object, ...]:
        merged: list[object] = []
        seen: set[str] = set()
        for group in groups:
            for block in tuple(group or ()):
                key = str(
                    getattr(block, "block_id", "")
                    or getattr(block, "content_hash", "")
                    or getattr(block, "text", "")
                    or id(block)
                ).strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(block)
        return tuple(merged)

    def _looks_like_chess_context_request(self, user_text: str) -> bool:
        """Bind chat vào state cờ typed thay vì săn vài word marker cứng."""

        bridge = getattr(self, "chess_bridge_service", None)
        matches = getattr(bridge, "matches_turn", None)
        fresh = getattr(bridge, "is_state_fresh", None)
        if not callable(matches):
            return False
        try:
            if callable(fresh) and not bool(fresh(max_age_seconds=30.0)):
                return False
            return bool(matches(user_text))
        except Exception:
            return False

    def _chat_structured_grounding_facts(self, user_text: str) -> tuple[object, ...]:
        bridge = getattr(self, "chess_bridge_service", None)
        evidence_fn = getattr(bridge, "current_grounding_evidence", None)
        if not callable(evidence_fn):
            return ()
        relevant = self._looks_like_chess_context_request(user_text)
        try:
            return tuple(
                evidence_fn(max_age_seconds=30.0, relevant_to_turn=relevant) or ()
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

        preference = str(getattr(self, "_autonomous_surface_preference_context", "") or "").strip()
        if preference:
            facts.append({
                "id": f"runtime_policy:autonomous_surface:{int(now.timestamp())}",
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
        try:
            from screen.evidence_models import PendingVisionEscalation
        except Exception:
            return
        now = time.time()
        try:
            ttl = max(8.0, min(90.0, float(os.environ.get("ERIS_CHAT_VISION_PENDING_TTL_SEC", "30") or 30.0)))
        except (TypeError, ValueError):
            ttl = 30.0
        window_key, revision = self._chat_window_identity()
        pending = PendingVisionEscalation(
            pending=True,
            reason=str(reason or "ocr_ambiguous")[:160],
            requested_at=now,
            expires_at=now + ttl,
            window_key=window_key,
            screen_revision=revision,
            engagement_id=self._chat_active_chess_engagement_id(),
            query_hint=" ".join(str(user_text or "").split())[:240],
        )
        self._chat_pending_vision_escalation = pending
        self.logger.info(
            "[vision pending] queued reason=%s ttl=%.0fs revision=%d",
            pending.reason,
            ttl,
            revision,
        )

    def _consume_next_turn_vision(self, *, user_text: str) -> bool:
        pending = getattr(self, "_chat_pending_vision_escalation", None)
        active = getattr(pending, "active", None)
        now = time.time()
        if not callable(active) or not active(now=now):
            clear = getattr(pending, "clear", None)
            if callable(clear):
                clear()
            return False

        # Structured chess state supersedes a queued screenshot. Nếu extension
        # vừa gửi FEN đủ dùng thì vision không còn lý do để nhìn lại bàn.
        if self._looks_like_chess_context_request(user_text):
            pending.clear()
            self.logger.info("[vision pending] cancelled reason=fresh_chess_bridge")
            return False

        current_window, _revision = self._chat_window_identity()
        current_engagement = self._chat_active_chess_engagement_id()
        same_window = bool(not pending.window_key or pending.window_key == current_window)
        same_engagement = bool(
            pending.engagement_id
            and current_engagement
            and pending.engagement_id == current_engagement
        )
        if not same_window and not same_engagement:
            pending.clear()
            self.logger.info("[vision pending] dropped reason=context_changed")
            return False

        reason = pending.reason
        pending.clear()
        self.logger.info("[vision pending] consumed reason=%s", reason or "ocr_ambiguous")
        return True

    def _ocr_needs_next_turn_vision(self, route) -> bool:
        if route is None or not bool(getattr(route, "references_screen", False)):
            return False
        if bool(getattr(route, "needs_visual", False)):
            return False
        mode = str(getattr(route, "mode", "none") or "none")
        evidence = tuple(getattr(route, "evidence", ()) or ())
        confidence = float(getattr(route, "confidence", 0.0) or 0.0)
        useful_chars = sum(
            len("".join(str(getattr(block, "text", "") or "").split()))
            for block in evidence[:6]
        )
        try:
            threshold = max(
                0.48,
                min(0.78, float(os.environ.get("ERIS_CHAT_OCR_VISION_ESCALATION_CONFIDENCE", "0.62") or 0.62)),
            )
        except (TypeError, ValueError):
            threshold = 0.62
        return bool(
            mode == "vision"
            or not evidence
            or (mode == "text_evidence_soft" and confidence < threshold)
            or useful_chars < 16
        )

    def _ensure_screen_text_worker_for_request(self) -> None:
        worker = getattr(self, "screen_text_worker", None)
        if worker is None:
            return
        try:
            worker.start()
        except Exception as exc:
            self.logger.warning("[screen text] lazy start error: %s", exc)

    def _refresh_screen_text_for_chat_request(self) -> bool:
        """Cưỡng bức một lượt UIA/OCR trước khi bỏ cuộc sang vision.

        Chỉ gọi khi router đã xác nhận câu hiện tại hoặc câu trước đang trỏ màn
        hình. Chat thường không bị OCR chặn; riêng lệnh ``xem đi`` thì việc thử
        đọc thật đáng giá hơn một câu hỏi lại rất máy.
        """

        worker = getattr(self, "screen_text_worker", None)
        refresh = getattr(worker, "refresh_now", None)
        if not callable(refresh):
            return False
        try:
            snapshot = refresh(force_ocr=True)
        except TypeError:
            snapshot = refresh()
        except Exception as exc:
            self.logger.warning("[screen text] chat refresh error: %s", exc)
            return False
        if snapshot is None:
            return False
        self.logger.info(
            "[screen text] chat refresh revision=%s backend=%s blocks=%d privacy=%s",
            int(getattr(snapshot, "revision", 0) or 0),
            str(getattr(snapshot, "backend", "unknown") or "unknown"),
            len(tuple(getattr(snapshot, "blocks", ()) or ())),
            int(bool(getattr(snapshot, "privacy_blocked", False))),
        )
        return True

    def _chat_main_vision_enabled(self) -> bool:
        raw = os.environ.get("ERIS_CHAT_MAIN_VISION", "0").strip().lower()
        return raw in {"1", "true", "yes", "on", "always"}

    def _capture_screen_frame_for_chat(self, user_text: str, *, previous_public_turn=None) -> str:
        self._chat_screen_route_decision = None
        ambient_blocks = self._chat_ambient_screen_blocks()
        self._chat_screen_text_evidence = ambient_blocks
        self._chat_screen_capture_present = False
        self._chat_screen_capture_interpreted = False

        force_chat_vision = self._chat_main_vision_enabled()
        pending_force_vision = self._consume_next_turn_vision(user_text=user_text)
        previous_assistant_text = self._previous_assistant_text_for_screen_route(previous_public_turn)
        explicit_or_inherited_request = self._looks_like_screen_vision_request(
            user_text,
            previous_assistant_text=previous_assistant_text,
        )
        chess_relevant = self._looks_like_chess_context_request(user_text)

        if explicit_or_inherited_request and not chess_relevant:
            self._ensure_screen_text_worker_for_request()

        router = getattr(self, "screen_relevance_router", None)
        route = None
        if router is not None:
            try:
                route = router.route(
                    user_text,
                    previous_assistant_text=previous_assistant_text,
                )
            except TypeError:
                # Adapter/router cũ trong test vẫn dùng chữ ký một tham số.
                route = router.route(user_text)
            except Exception as exc:
                self.logger.warning("[screen route] router lỗi: %s", exc)

        # OCR nền có thể vừa đổi frame nhưng chưa đến poll. Chỉ refresh cưỡng bức
        # khi user thật sự hỏi màn hình và structured chess state không đủ trả lời.
        if (
            not chess_relevant
            and route is not None
            and bool(getattr(route, "references_screen", False))
            and (not tuple(getattr(route, "evidence", ()) or ()) or bool(getattr(route, "stale", False)))
            and self._refresh_screen_text_for_chat_request()
            and router is not None
        ):
            try:
                route = router.route(
                    user_text,
                    previous_assistant_text=previous_assistant_text,
                )
            except TypeError:
                route = router.route(user_text)
            except Exception as exc:
                self.logger.warning("[screen route] reroute sau OCR lỗi: %s", exc)

        # Hai classifier từng bất đồng: request detector nhận ra “xem giúp”, router
        # lại trả mode=none. Explicit request thắng để evidence ladder còn hoạt động.
        route_mode = str(getattr(route, "mode", "none") or "none") if route is not None else "none"
        if route is None or (route_mode == "none" and explicit_or_inherited_request):
            if route is None and not explicit_or_inherited_request and not force_chat_vision and not pending_force_vision:
                self.logger.debug("[screen route] mode=none reason=no_screen_reference")
                # Không return sớm khỏi grounding: ambient OCR vẫn được đọc trực
                # tiếp từ ScreenEvidenceStore trong _chat_source_grounding_screen_facts.
                return ""
            try:
                from screen.evidence_models import ScreenRouteDecision
                route = ScreenRouteDecision(
                    mode="vision",
                    references_screen=True,
                    needs_visual=bool(pending_force_vision),
                    reason=(
                        "pending_vision_escalation"
                        if pending_force_vision
                        else "explicit_request_overrode_none_route"
                    ),
                    evidence=tuple(getattr(route, "evidence", ()) or ()) if route is not None else (),
                    confidence=float(getattr(route, "confidence", 0.0) or 0.0) if route is not None else 0.0,
                    stale=bool(getattr(route, "stale", False)) if route is not None else False,
                    debug=dict(getattr(route, "debug", {}) or {}) if route is not None else {},
                )
            except Exception:
                from types import SimpleNamespace
                route = SimpleNamespace(
                    mode="vision",
                    references_screen=True,
                    needs_visual=bool(pending_force_vision),
                    evidence=(),
                    confidence=0.70,
                    stale=False,
                    reason="pending_vision_escalation" if pending_force_vision else "explicit_request_overrode_none_route",
                    debug={},
                )

        # Pending escalation luôn force vision ở lượt N+1, kể cả router lượt mới
        # chỉ thấy text evidence. Nó là một lần consume, không phải always-on vision.
        if pending_force_vision and str(getattr(route, "mode", "none") or "none") != "vision":
            try:
                from screen.evidence_models import ScreenRouteDecision
                route = ScreenRouteDecision(
                    mode="vision",
                    references_screen=True,
                    needs_visual=True,
                    requires_strong_evidence=bool(getattr(route, "requires_strong_evidence", False)),
                    reason="pending_vision_escalation",
                    evidence=tuple(getattr(route, "evidence", ()) or ()),
                    confidence=float(getattr(route, "confidence", 0.0) or 0.0),
                    stale=bool(getattr(route, "stale", False)),
                    debug=dict(getattr(route, "debug", {}) or {}),
                )
            except Exception:
                pass

        route_blocks = tuple(getattr(route, "evidence", ()) or ())
        self._chat_screen_route_decision = route
        self._chat_screen_text_evidence = self._merge_chat_screen_blocks(
            ambient_blocks,
            route_blocks,
        )
        debug = dict(getattr(route, "debug", {}) or {})
        self.logger.info(
            "[screen route] mode=%s refs=%s visual=%s evidence=%d ambient=%d confidence=%.2f stale=%s reason=%s anaphora=%s",
            str(getattr(route, "mode", "none") or "none"),
            int(bool(getattr(route, "references_screen", False))),
            int(bool(getattr(route, "needs_visual", False))),
            len(route_blocks),
            len(ambient_blocks),
            float(getattr(route, "confidence", 0.0) or 0.0),
            int(bool(getattr(route, "stale", False))),
            str(getattr(route, "reason", "") or "none"),
            int(bool(debug.get("anaphora_inherited", False))),
        )

        # FEN tươi từ extension là direct structured evidence. Không chụp vision
        # lại bàn cờ và cũng không queue một escalation vô ích.
        if chess_relevant:
            self.logger.info("[chess route] structured bridge selected; vision skipped")
            pending = getattr(self, "_chat_pending_vision_escalation", None)
            clear = getattr(pending, "clear", None)
            if callable(clear):
                clear()
            return ""

        mode = str(getattr(route, "mode", "none") or "none")
        should_capture_now = bool(
            force_chat_vision
            or pending_force_vision
            or (mode == "vision" and bool(getattr(route, "needs_visual", False)))
        )

        # OCR mơ hồ ở lượt N chỉ đặt cờ. Vision được nhét vào lượt N+1 nếu vẫn
        # cùng window/engagement, thay vì gọi model ảnh ngay trong mọi request.
        if not should_capture_now and self._ocr_needs_next_turn_vision(route):
            self._queue_next_turn_vision(
                reason=str(getattr(route, "reason", "ocr_ambiguous") or "ocr_ambiguous"),
                user_text=user_text,
            )
            return ""

        if not should_capture_now:
            return ""
        if mode != "vision" and force_chat_vision:
            self.logger.info("[vision chat] forcing main vision despite route mode=%s", mode)

        capture_fn = getattr(getattr(self, "telemetry_service", None), "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service không hỗ trợ chụp màn hình.")
            if pending_force_vision:
                self._queue_next_turn_vision(reason="pending_capture_unavailable", user_text=user_text)
            return ""
        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] không chụp được màn hình: %s", exc)
            if pending_force_vision:
                self._queue_next_turn_vision(reason="pending_capture_failed", user_text=user_text)
            return ""
        if not str(data_uri or "").strip():
            self.logger.warning("[vision chat] screen capture trả dữ liệu rỗng")
            if pending_force_vision:
                self._queue_next_turn_vision(reason="pending_capture_empty", user_text=user_text)
            return ""
        self._chat_screen_capture_present = True
        self.logger.info("[vision chat] captured=1 bytes=%d", len(str(data_uri)))
        snapshot = getattr(self, "_chat_snapshot_for_vision", None)
        if snapshot is not None:
            try:
                self._refresh_screen_facts_from_data_uri(
                    data_uri=data_uri, snapshot=snapshot, channel="chat",
                    user_text=user_text, force_refresh=True,
                )
                report = getattr(self, "last_vision_grounding_report", None)
                grounded_count = len(tuple(getattr(report, "grounded_claims", ()) or ())) if report is not None else 0
                self._chat_screen_capture_interpreted = grounded_count > 0
                self.logger.info(
                    "[vision chat] interpreted=%s grounded_claims=%d recommendation=%s source=%s",
                    int(self._chat_screen_capture_interpreted),
                    grounded_count,
                    str(getattr(report, "recommendation", "none") or "none"),
                    str(getattr(report, "source", "unknown") or "unknown"),
                )
            except Exception as exc:
                self.logger.warning("[vision chat] không nén được screenshot: %s", exc)
        return data_uri

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
        """Gộp ambient OCR + route OCR + grounded vision cho mọi lượt chat."""

        route = getattr(self, "_chat_screen_route_decision", None)
        now = time.time()
        blocks = self._merge_chat_screen_blocks(
            self._chat_ambient_screen_blocks(),
            tuple(getattr(self, "_chat_screen_text_evidence", ()) or ()),
            tuple(getattr(route, "evidence", ()) or ()) if route is not None else (),
        )
        items: list[object] = []
        seen: set[str] = set()

        for block in blocks:
            to_item = getattr(block, "to_grounding_item", None)
            item = None
            if callable(to_item):
                try:
                    item = dict(to_item(now=now, stale_after=8.0))
                except Exception:
                    item = None
            if item is None:
                text = str(getattr(block, "text", "") or "").strip()
                if not text:
                    continue
                captured_at = float(getattr(block, "captured_at", 0.0) or 0.0)
                item = {
                    "id": str(getattr(block, "block_id", "screen_text") or "screen_text"),
                    "source": str(getattr(block, "source", "screen_text_index") or "screen_text_index"),
                    "claim": text,
                    "confidence": float(getattr(block, "confidence", 0.65) or 0.65),
                    "grounded": True,
                    "stale": bool(captured_at and now - captured_at > 8.0),
                    "captured_at": captured_at,
                    "tags": ["screen", "screen_text", "ocr_ambient"],
                }
            item.setdefault("role", "ambient")
            tags = list(item.get("tags", ()) or ())
            if "ocr_ambient" not in tags:
                tags.append("ocr_ambient")
            item["tags"] = tags
            item_id = str(item.get("id", "") or item.get("claim", ""))
            if item_id in seen:
                continue
            seen.add(item_id)
            items.append(item)

        report = getattr(self, "last_vision_grounding_report", None)
        if report is not None and screen_image_data_uri and not bool(getattr(report, "stale", False)):
            to_items = getattr(report, "to_evidence_items", None)
            if callable(to_items):
                try:
                    for raw in tuple(to_items(grounded_only=True) or ()):
                        item = dict(raw) if isinstance(raw, dict) else raw
                        item_id = str(
                            item.get("id", "") if isinstance(item, dict)
                            else getattr(item, "id", "")
                        )
                        if item_id and item_id in seen:
                            continue
                        if item_id:
                            seen.add(item_id)
                        items.append(item)
                except Exception:
                    pass

        if screen_image_data_uri and not self._chat_screen_capture_interpreted:
            items.append({
                "id": "chat_screen_frame_unresolved",
                "source": "screen_capture",
                "claim": "fresh screenshot captured but no grounded semantic claim",
                "confidence": 0.25,
                "grounded": False,
                "stale": False,
                "tags": ["vision", "screen", "chat", "ungrounded"],
            })
        return tuple(items)

    @staticmethod
    def _chat_screen_grounding_items_stale(items: tuple[object, ...]) -> bool:
        grounded: list[object] = []
        for item in tuple(items or ()):
            marker = item.get("grounded") if isinstance(item, dict) else getattr(item, "grounded", None)
            if marker is False or str(marker).strip().lower() == "false":
                continue
            grounded.append(item)
        if not grounded:
            return False
        return all(
            bool(item.get("stale", False)) if isinstance(item, dict) else bool(getattr(item, "stale", False))
            for item in grounded
        )

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
