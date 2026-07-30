from __future__ import annotations

import os
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
        self._chat_screen_text_evidence = ()
        self._chat_screen_capture_present = False
        self._chat_screen_capture_interpreted = False
        force_chat_vision = self._chat_main_vision_enabled()
        previous_assistant_text = self._previous_assistant_text_for_screen_route(previous_public_turn)
        explicit_or_inherited_request = self._looks_like_screen_vision_request(
            user_text,
            previous_assistant_text=previous_assistant_text,
        )
        if explicit_or_inherited_request:
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

        # OCR nền có thể vừa đổi frame nhưng chưa đến poll. Nếu route đã nhận ra
        # tham chiếu mà chưa có evidence đủ dùng, làm mới một lần rồi route lại.
        if (
            route is not None
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

        if route is None:
            if not explicit_or_inherited_request and not force_chat_vision:
                self.logger.debug("[screen route] mode=none reason=no_screen_reference")
                return ""
            try:
                from screen.evidence_models import ScreenRouteDecision
                route = ScreenRouteDecision(
                    mode="vision", references_screen=True,
                    reason="router_unavailable_explicit_or_inherited_request",
                )
            except Exception:
                from types import SimpleNamespace
                route = SimpleNamespace(
                    mode="vision",
                    references_screen=True,
                    needs_visual=True,
                    evidence=(),
                    confidence=0.55 if force_chat_vision else 0.70,
                    stale=False,
                    reason="router_unavailable_main_vision" if force_chat_vision else "router_unavailable_explicit_request",
                    debug={},
                )

        self._chat_screen_route_decision = route
        self._chat_screen_text_evidence = tuple(getattr(route, "evidence", ()) or ())
        debug = dict(getattr(route, "debug", {}) or {})
        self.logger.info(
            "[screen route] mode=%s refs=%s visual=%s evidence=%d confidence=%.2f stale=%s reason=%s anaphora=%s",
            str(getattr(route, "mode", "none") or "none"),
            int(bool(getattr(route, "references_screen", False))),
            int(bool(getattr(route, "needs_visual", False))),
            len(self._chat_screen_text_evidence),
            float(getattr(route, "confidence", 0.0) or 0.0),
            int(bool(getattr(route, "stale", False))),
            str(getattr(route, "reason", "") or "none"),
            int(bool(debug.get("anaphora_inherited", False))),
        )
        mode = str(getattr(route, "mode", "none") or "none")
        if mode != "vision" and not force_chat_vision:
            return ""
        if mode != "vision" and force_chat_vision:
            self.logger.info("[vision chat] forcing main vision despite route mode=%s", mode)
        capture_fn = getattr(self.telemetry_service, "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service không hỗ trợ chụp màn hình.")
            return ""
        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] không chụp được màn hình: %s", exc)
            return ""
        if not str(data_uri or "").strip():
            self.logger.warning("[vision chat] screen capture trả dữ liệu rỗng")
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
            "rule: Không được nói 'đang nhìn đây', 'tôi thấy', 'tôi đang xem', "
            "hoặc khẳng định như đã hiểu hình ảnh trên màn hình.\n"
            "required_stance: Nói thật rằng đã thử lấy khung hình nhưng chưa đủ bằng chứng "
            "để mô tả chắc. Nếu có OCR/text evidence, chỉ nói là đọc được một phần chữ/OCR, "
            "không gọi đó là nhìn thấy toàn cảnh.\n"
            "[/VISION_STATUS]"
        )


    def _chat_source_grounding_screen_facts(self, snapshot, *, screen_image_data_uri: str = "") -> tuple[object, ...]:
        route = getattr(self, "_chat_screen_route_decision", None)
        if (
            (route is None or str(getattr(route, "mode", "none") or "none") == "none")
            and not screen_image_data_uri
        ):
            return ()
        now = time.time()
        text_items: list[object] = []
        for block in tuple(getattr(self, "_chat_screen_text_evidence", ()) or ()):
            to_item = getattr(block, "to_grounding_item", None)
            if callable(to_item):
                try:
                    text_items.append(to_item(now=now, stale_after=8.0))
                    continue
                except Exception:
                    pass
            text = str(getattr(block, "text", "") or "").strip()
            if text:
                text_items.append({
                    "id": str(getattr(block, "block_id", "screen_text") or "screen_text"),
                    "source": str(getattr(block, "source", "screen_text_index") or "screen_text_index"),
                    "claim": text,
                    "confidence": float(getattr(block, "confidence", 0.65) or 0.65),
                    "grounded": True,
                    "stale": bool(getattr(route, "stale", False)),
                    "tags": ["screen", "screen_text"],
                })
        if text_items and not screen_image_data_uri:
            return tuple(text_items)
        report = getattr(self, "last_vision_grounding_report", None)
        if report is not None and screen_image_data_uri and not bool(getattr(report, "stale", False)):
            to_items = getattr(report, "to_evidence_items", None)
            if callable(to_items):
                facts = tuple(to_items(grounded_only=True))
                if facts:
                    return facts
        if text_items:
            return tuple(text_items)
        if screen_image_data_uri:
            return ({
                "id": "chat_screen_frame_unresolved",
                "source": "screen_capture",
                "claim": "fresh screenshot captured but no grounded semantic claim",
                "confidence": 0.25,
                "grounded": False,
                "tags": ["vision", "screen", "chat", "ungrounded"],
            },)
        return ()

    def _build_chat_source_grounding_report(
        self, *, user_text: str, frame, snapshot, memory_resonance=None,
        screen_image_data_uri: str = "",
    ):
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            self.source_grounding_engine = engine
        return engine.analyze(
            user_text,
            frame=frame,
            screen_facts=self._chat_source_grounding_screen_facts(
                snapshot, screen_image_data_uri=screen_image_data_uri,
            ),
            screen_facts_stale=bool(getattr(getattr(self, "_chat_screen_route_decision", None), "stale", False)),
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
