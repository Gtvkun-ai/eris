import json
import os
import random
import re
import time
import unicodedata

from dataclasses import dataclass

from cortex.ni import NiStateMachine
from domain import Decision

'''coordinator.py là “bộ điều phối runtime” (orchestrator) cho ERIS: nó đứng giữa telemetry 
(màn hình/hành vi), các tầng đánh giá (Ni/Ti/FE), LLM + parser, action system và kênh transport để quyết định
 “lúc nào nói/câm”, “nói gì”, “có thực thi action không”, rồi gửi Decision ra “body” (Godot) qua UDP.
'''


SPEECH_INTENTS = (
    "no_speech",
    "brief_ack",
    "screen_observation",
    "user_requested",
    "system_warning",
    "playful_aside",
)

VISION_TRACE_MARKER = "vision_facts_attached"


@dataclass(frozen=True, slots=True)
class SpeechIntentDecision:
    intent: str
    reason: str


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        logger,
        transport,
        llm_service,
        parser,
        telemetry_service,
        ni_engine,
        ti_governor,
        fe_renderer,
        memory_store,
        body_running_fn,
        action_executor=None,
        action_router=None,
    ):
        self.logger = logger
        self.transport = transport
        self.llm_service = llm_service
        self.parser = parser
        self.telemetry_service = telemetry_service
        self.ni_engine = ni_engine
        self.ti_governor = ti_governor
        self.fe_renderer = fe_renderer
        self.memory_store = memory_store
        self.body_running_fn = body_running_fn
        self.action_executor = action_executor
        self.action_router = action_router

        self.chat_mode = False
        self.chat_history = []
        self.last_chat_answer = ""
        self.last_system_action = ""
        self.last_user_signature = ""
        self.repeated_user_count = 0
        self.running = True
        self.last_text = ""
        self.mood_score = 50
        self.inferred_pos_x = 0.5
        self.idle_cycles = 0
        self.last_autonomous_signature = ""
        self.repeated_autonomous_count = 0
        self.last_autonomous_spoken_at = 0.0
        self.long_term_memory = []
        self.fe_style_memory = self.fe_renderer.create_memory()
        self.vision_facts_enabled, self.vision_interval_sec, self.vision_fact_max_items, self.vision_fact_max_len = (
            self._load_vision_fact_settings()
        )
        self.vision_facts: tuple[str, ...] = ()
        self.vision_last_capture_at = 0.0
        self.vision_disabled_until = 0.0
        self.vision_failure_count = 0
        self.vision_last_trace = ""
        self.vision_facts_signature = ""
        # NiStateMachine giữ state drift rời rạc theo thời gian (ON_GOAL / BORDERLINE / OFF_GOAL)
        #  dựa trên chuỗi GoalDriftReport, thay vì chỉ nhìn một snapshot đơn lẻ.
        self.autonomous_ni_state = NiStateMachine()
        self.chat_ni_state = NiStateMachine()
        # Bật/tắt tầng suy luận nhẹ của Ni theo mode.
        # Giữ tên env/config cũ để tương thích ngược.
        flag = os.environ.get("ERIS_NI_META_CRITIC", "1").strip().lower()
        env_enabled = flag not in {"0", "false", "no", "off"}
        chat_cfg, auto_cfg = self._load_ni_meta_mode_flags()
        self.ni_meta_env_enabled = env_enabled
        self.ni_meta_chat_enabled = env_enabled and chat_cfg
        self.ni_meta_auto_enabled = env_enabled and auto_cfg

    def _log_raw_llm_output(self, channel: str, raw: str) -> None:
        preview = (raw or "").replace("\n", "\\n")
        if len(preview) > 500:
            preview = preview[:500] + "...(truncated)"
        self.logger.info("[%s raw] %s", channel, preview or "<empty>")

    def _preview_text(self, text: str, *, limit: int = 240) -> str:
        preview = (text or "").replace("\n", "\\n").strip()
        if len(preview) > limit:
            preview = preview[:limit] + "...(truncated)"
        return preview or "<empty>"

    def _log_pre_parser(self, channel: str, raw: str) -> None:
        self.logger.info("[%s pre_parser] raw=%s", channel, self._preview_text(raw, limit=320))

    def _log_decision_stage(self, channel: str, stage: str, decision: Decision) -> None:
        self.logger.info(
            "[%s %s] text=\"%s\" | animation=%s | parse_mode=%s | trace=%s | parser=%s",
            channel,
            stage,
            self._preview_text(decision.text),
            decision.animation,
            decision.parse_mode,
            self._preview_text(decision.debug_trace),
            self._preview_text(decision.parser_trace),
        )

    def stop(self):
        self.running = False
        self.transport.close()

    def _apply_position_update(self, decision: Decision) -> None:
        intent = decision.resolve_motion_intent()
        tx = decision.resolve_motion_target_x()
        facing = decision.resolve_motion_facing()

        if intent in {"walk_to", "climb_to_top"} and 0.0 <= tx <= 1.0:
            self.inferred_pos_x = tx
        elif intent == "walk" and facing == -1:
            self.inferred_pos_x = max(0.0, self.inferred_pos_x - 0.4)
        elif intent == "walk" and facing == 1:
            self.inferred_pos_x = min(1.0, self.inferred_pos_x + 0.4)

    def _normalize_user_message(self, user_text: str) -> str:
        lowered = (user_text or "").strip().lower()
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        lowered = " ".join(lowered.split())

        filler_suffixes = {
            "nhe",
            "nha",
            "nhi",
            "a",
            "ah",
            "ha",
            "huh",
            "vay",
            "co",
            "khong",
            "nao",
            "di",
            "voi",
            "giup",
            "dum",
            "dum",
            "di",
        }
        tokens = lowered.split()
        while tokens and tokens[-1] in filler_suffixes:
            tokens.pop()
        return " ".join(tokens)

    def _looks_like_screen_vision_request(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return False

        direct_terms = {
            "brave",
            "browser",
            "chrome",
            "cua so",
            "hinh anh",
            "man hinh",
            "screenshot",
            "screen",
            "tab",
            "trinh duyet",
            "url",
            "web",
            "website",
        }
        if any(term in normalized for term in direct_terms):
            return True

        visual_verbs = {"nhin", "thay"}
        visual_objects = {"gi tren do", "noi dung", "trang nao"}
        return any(term in normalized for term in visual_verbs) and any(
            term in normalized for term in visual_objects
        )

    def _capture_screen_frame_for_chat(self, user_text: str) -> str:
        if not self._looks_like_screen_vision_request(user_text):
            return ""

        capture_fn = getattr(self.telemetry_service, "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service khong ho tro chup man hinh.")
            return ""

        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] khong chup duoc man hinh: %s", exc)
            return ""

        self.logger.info("[vision chat] Da dinh kem screenshot toan man hinh cho luot chat nay.")
        return data_uri

    def _build_user_message_signature(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        if self.action_router is not None:
            routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
            if routed:
                action_name, action_input = routed
                normalized_input = self._normalize_user_message(action_input)
                if action_name == "get_now_playing":
                    return "action:get_now_playing"
                return f"action:{action_name}:{normalized_input}"

        return normalized

    # theo dõi số lần lặp lại của cùng một câu user (dựa trên signature), để phát hiện và phản ứng với spam lặp lại.
    def _track_repeated_user_message(self, user_text: str) -> int:
        signature = self._build_user_message_signature(user_text)
        if not signature:
            self.last_user_signature = ""
            self.repeated_user_count = 0
            return 0

        if signature == self.last_user_signature:
            self.repeated_user_count += 1
        else:
            self.last_user_signature = signature
            self.repeated_user_count = 1
        return self.repeated_user_count

    def _build_repeat_guard_decision(self, user_text: str, ti_report, repeat_count: int) -> Decision | None:
        if repeat_count < 2:
            return None

        if repeat_count == 2:
            text = (
                "Ngài đang lặp lại đúng cùng một câu. "
                "Tôi đã nhận câu đó rồi. Nếu muốn tôi nói khác đi, hãy chỉ rõ phần nào Ngài chưa hiểu."
            )
        else:
            text = (
                "Tôi hiểu đây là spam lặp lại. "
                "Cùng một câu sẽ không tạo thêm dữ kiện mới. Hãy đổi câu hỏi hoặc nói rõ mục tiêu tiếp theo."
            )

        decision = Decision(
            text=text,
            animation="read" if repeat_count == 2 else "sad",
            parse_mode="repeat_guard",
            debug_trace=f"repeat_guard=count={repeat_count}",
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if msg_type == "force_speak":
            self._handle_force_speak_request()
            return

        if msg_type == "chat":
            user_text = msg.get("message", "").strip()
            if not user_text:
                return
            if not self.chat_mode:
                self.chat_ni_state = NiStateMachine() # reset trạng thái Ni khi bắt đầu chat mới, để tránh mang theo drift state từ autonomous mode.

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            ni_report = self.ni_engine.evaluate_chat(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                user_text=user_text,
            )
            # Tầng 2: suy luận nhẹ có bằng chứng để tinh chỉnh drift_score / drift_level.
            ni_report = self._maybe_apply_ni_meta_critic(
                mode="chat",
                snapshot=snapshot,
                base_report=ni_report,
                telemetry_text=self._build_ni_telemetry_summary(snapshot),
                user_text=user_text,
            )
            ni_view = self.chat_ni_state.update(snapshot=snapshot, report=ni_report) # Cập nhật trạng thái drift rời rạc của Ni dựa trên báo cáo drift hiện tại và lịch sử drift gần đây, để cung cấp thông tin về việc Ni đang on_goal, borderline hay off_goal.
            ni_state_label = ni_view["discrete_state"]
            ni_state_streak = ni_view["streak_length"] # Số chu kỳ liên tiếp mà Ni đã duy trì trạng thái drift rời rạc hiện tại, được sử dụng để đánh giá tính ổn định của trạng thái hiện tại và có thể ảnh hưởng đến quyết định của TiGovernor (ví dụ nếu Ni đã ở trạng thái off_goal trong nhiều chu kỳ liên tiếp, TiGovernor có thể quyết định can thiệp mạnh mẽ hơn).
            ti_report = self.ti_governor.evaluate_chat(
                snapshot=snapshot,
                ni_report=ni_report,
                user_text=user_text,
            )
            fe_plan = self.fe_renderer.evaluate_chat(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                user_text=user_text,
            )

            self.chat_mode = True
            self.logger.info("Người dùng: %s", user_text)
            self.logger.info(
                "[ni chat] drift=%.2f | level=%s | state=%s | streak=%d",
                ni_report.drift_score,
                ni_report.drift_level,
                ni_state_label,
                ni_state_streak,
            )
            self.logger.info("[ti chat] mode=%s | reason=%s", ti_report.mode, ti_report.reason)
            self.logger.info(
                "[fe chat] mode=%s | tone=%s | intent=%s | arc=%s",
                fe_plan.mode,
                fe_plan.tone_label,
                fe_plan.intent_label,
                fe_plan.session_arc,
            )
            repeat_count = self._track_repeated_user_message(user_text)
            self.chat_history.append({"role": "user", "content": user_text})

            direct_decision = self._build_direct_action_decision(user_text, ti_report, snapshot, repeat_count=repeat_count)
            if direct_decision is not None:
                self._commit_chat_decision(direct_decision, fe_plan)
                return

            repeat_decision = self._build_repeat_guard_decision(user_text, ti_report, repeat_count)
            if repeat_decision is not None:
                self._commit_chat_decision(repeat_decision, fe_plan)
                return

            chat_user_message = self.parser.build_chat_user_message(
                user_message=user_text,
                last_chat_answer=self.last_chat_answer,
            )
            screen_image_data_uri = self._capture_screen_frame_for_chat(user_text)
            raw = self.llm_service.generate_chat_reply(
                chat_history=self.chat_history[-10:],
                user_message=chat_user_message,
                ni_context=ni_report.prompt_context,
                ti_context=ti_report.prompt_context,
                fe_context=fe_plan.style_context,
                screen_image_data_uri=screen_image_data_uri,
            )
            self._log_raw_llm_output("chat", raw)
            self._log_pre_parser("chat", raw)
            decision = self.parser.parse(raw, user_hint=user_text)
            self._log_decision_stage("chat", "post_parser", decision)
            self._log_decision_stage("chat", "pre_ti", decision)
            decision = self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)
            self._log_decision_stage("chat", "post_ti", decision)
            decision = self._execute_system_action(decision, snapshot=snapshot)
            self._commit_chat_decision(decision, fe_plan)
            return

        if msg_type == "chat_end":
            self.chat_mode = False
            self.chat_history.clear()
            self.last_chat_answer = ""
            self.last_system_action = ""
            self.last_user_signature = ""
            self.repeated_user_count = 0
            self.chat_ni_state = NiStateMachine()
            self.fe_style_memory = self.fe_renderer.decay_memory(self.fe_style_memory)
            self.logger.info("Đã thoát chat mode, tiếp tục autonomous.")

    def _handle_force_speak_request(self) -> None:
        cycle_start = time.time()
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        vision_marker = ""
        vision_facts = self._maybe_update_screen_facts()
        if vision_facts:
            vision_marker = self._attach_screen_facts(snapshot, vision_facts)
        telemetry_data = self.telemetry_service.format_directive_snapshot(snapshot)
        ni_report = self.ni_engine.evaluate_autonomous(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            last_text=self.last_text,
        )
        ni_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
        ni_state_label = ni_view["discrete_state"]
        ni_state_streak = ni_view["streak_length"]
        ti_report = self.ti_governor.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            ni_state_streak=ni_state_streak,
            idle_cycles=self.idle_cycles,
            last_text=self.last_text,
        )
        fe_plan = self.fe_renderer.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            last_text=self.last_text,
        )

        forced_ti_context = (
            f"{ti_report.prompt_context}\n"
            "Context menu force_speak: Ngài vừa yêu cầu ERIS nói ngay. "
            "Bỏ qua cooldown im lặng cho đúng một lượt này. "
            "Nói một câu mới, tự nhiên; đừng nhắc telemetry hay chuyện menu trừ khi thật sự duyên. "
            "Nếu không có tín hiệu cụ thể, không đoán Ngài đang thoải mái, bận rộn, mệt, căng, "
            "hay đang làm việc quá sức. Tránh mở bằng 'Có vẻ'/'Hình như' và tránh câu tự lùi kiểu "
            "'tôi không muốn làm phiền'."
        )
        if not vision_marker:
            forced_ti_context += " Không có screen_facts mới; nói thật gọn, không dựng cảnh ngoài dữ kiện."
        self.logger.info("[force_speak] context menu requested immediate speech.")
        raw = self.llm_service.generate_directive(
            telemetry_data=telemetry_data,
            ni_context=ni_report.prompt_context,
            ti_context=forced_ti_context,
            fe_context=fe_plan.style_context,
            avoid_text=self.last_text,
            speech_intent="user_requested",
            vision_trace_marker=vision_marker,
        )
        self._log_raw_llm_output("force_speak", raw)
        self._log_pre_parser("force_speak", raw)
        decision = self.parser.parse(raw)
        self._log_decision_stage("force_speak", "post_parser", decision)
        self._log_decision_stage("force_speak", "pre_ti", decision)
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        self._log_decision_stage("force_speak", "post_ti", decision)
        decision = self._execute_system_action(decision, snapshot=snapshot)

        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = time.time()
        self._apply_position_update(decision)

        self.logger.info(
            '[force_speak] Decision text="%s" | animation="%s" | elapsed=%.2fs',
            decision.text,
            decision.animation,
            time.time() - cycle_start,
        )
        self.logger.info("[force_speak debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[force_speak parser] %s", decision.parser_trace or "<empty>")
        self.transport.send_json(decision.to_payload())

    def _commit_chat_decision(self, decision: Decision, fe_plan) -> None:
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.long_term_memory = self.memory_store.append_fact(self.long_term_memory, decision.extracted_fact)

        self.last_chat_answer = decision.text
        self.last_system_action = decision.system_action
        self.chat_history.append({"role": "assistant", "content": decision.text})
        if len(self.chat_history) > 32:
            self.chat_history = self.chat_history[-32:]

        self._apply_position_update(decision)
        self.logger.info("ERIS: %s", decision.text)
        self.logger.info("[chat debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[chat parser] %s", decision.parser_trace or "<empty>")
        self.transport.send_json(decision.to_payload())

    def _sleep_interruptible(self, seconds: float):
        end_at = time.time() + seconds
        # Trong khi còn self.running và chưa tới end_at, nó time.sleep(0.2).
        while self.running and time.time() < end_at:
            time.sleep(0.2) # Mục đích: giữ app phản hồi nhanh, không bị block lâu.
            if not self.body_running_fn():
                self.stop()
                return
            msg = self.transport.poll_json()
            if msg:
                self._handle_incoming(msg)
                if self.chat_mode:
                    return

    def _bucket_idle_seconds(self, idle_seconds: float) -> str:
        if idle_seconds >= 720:
            return "very_long"
        if idle_seconds >= 300:
            return "long"
        if idle_seconds >= 90:
            return "medium"
        if idle_seconds >= 15:
            return "short"
        return "active"

    def _bucket_window_spread(self, open_windows: tuple[str, ...], browser_tabs: tuple[str, ...]) -> str:
        spread = max(len(open_windows or ()), len(browser_tabs or ()))
        if spread >= 10:
            return "very_high"
        if spread >= 7:
            return "high"
        if spread >= 4:
            return "medium"
        return "low"

    def _load_vision_fact_settings(self) -> tuple[bool, int, int, int]:
        flag = os.environ.get("ERIS_VISION_FACTS", "1").strip().lower()
        enabled = flag not in {"0", "false", "no", "off"}

        interval_raw = os.environ.get("ERIS_VISION_FACTS_INTERVAL", "60").strip()
        max_items_raw = os.environ.get("ERIS_VISION_FACTS_MAX", "3").strip()
        max_len_raw = os.environ.get("ERIS_VISION_FACTS_MAX_LEN", "120").strip()

        try:
            interval = int(interval_raw)
        except ValueError:
            interval = 60
        try:
            max_items = int(max_items_raw)
        except ValueError:
            max_items = 3
        try:
            max_len = int(max_len_raw)
        except ValueError:
            max_len = 120

        interval = max(10, min(interval, 900))
        max_items = max(1, min(max_items, 6))
        max_len = max(40, min(max_len, 240))
        return enabled, interval, max_items, max_len

    def _note_vision_failure(self, stage: str, exc: Exception) -> None:
        self.vision_failure_count += 1
        backoff = min(300, 15 * self.vision_failure_count)
        self.vision_disabled_until = time.time() + backoff
        self.logger.warning(
            "[vision_facts] %s failed: %s | backoff=%ss",
            stage,
            exc,
            backoff,
        )

    def _sanitize_screen_facts(self, facts: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        if not facts:
            return ()
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in facts:
            text = re.sub(r"\s+", " ", str(item or "").strip())
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            if len(text) > self.vision_fact_max_len:
                trimmed = text[: self.vision_fact_max_len - 3].rstrip()
                text = f"{trimmed}..."
            cleaned.append(text)
            seen.add(key)
            if len(cleaned) >= self.vision_fact_max_items:
                break
        return tuple(cleaned)

    def _maybe_update_screen_facts(self) -> tuple[str, ...]:
        if not self.vision_facts_enabled:
            return ()

        now = time.time()
        if now < self.vision_disabled_until:
            return self.vision_facts
        if self.vision_last_capture_at and (now - self.vision_last_capture_at) < self.vision_interval_sec:
            return self.vision_facts

        try:
            data_uri = self.telemetry_service.capture_screen_frame_data_uri()
        except Exception as exc:
            self._note_vision_failure("capture", exc)
            return self.vision_facts

        if not data_uri:
            self.vision_last_capture_at = now
            self.vision_facts = ()
            self.vision_last_trace = ""
            return self.vision_facts

        try:
            facts, trace = self.llm_service.generate_screen_facts(screen_image_data_uri=data_uri)
        except Exception as exc:
            self._note_vision_failure("vlm", exc)
            return self.vision_facts

        self.vision_last_capture_at = now
        self.vision_failure_count = 0
        self.vision_disabled_until = 0.0
        cleaned = self._sanitize_screen_facts(facts)
        self.vision_facts = cleaned
        self.vision_last_trace = trace or ""
        return self.vision_facts

    def _attach_screen_facts(self, snapshot, facts: tuple[str, ...]) -> str:
        if not facts:
            return ""
        existing = tuple(getattr(snapshot, "recent_events", ()) or ())
        snapshot.recent_events = (*facts, *existing)
        return VISION_TRACE_MARKER

    # đếm số chu kỳ lặp lại bối cảnh
    def _build_autonomous_signature(self, snapshot, ti_report) -> str:
        active_window = str(getattr(snapshot, "active_window", "") or "").strip().lower()
        browser_url = str(getattr(snapshot, "browser_url", "") or "").strip().lower()
        browser_host = ""
        if browser_url:
            browser_host = browser_url.split("://", 1)[-1].split("/", 1)[0]

        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = str(getattr(user_signals, "focus_pattern", "") or "")

        parts = [
            f"mode={getattr(ti_report, 'mode', '') or ''}",
            f"kind={getattr(snapshot, 'active_window_kind', '') or ''}",
            f"focus={getattr(snapshot, 'focus_summary', '') or ''}",
            f"window={active_window[:96]}",
            f"browser={browser_host}",
            f"idle={self._bucket_idle_seconds(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}",
            f"spread={self._bucket_window_spread(getattr(snapshot, 'open_windows', ()), getattr(snapshot, 'browser_tabs', ()))}",
            f"pattern={focus_pattern}",
        ]
        return "|".join(parts)

    #theo dõi “bối cảnh autonomous có đang lặp lại không”.
    def _track_autonomous_signature(self, snapshot, ti_report) -> tuple[str, int]:
        # Tạo signature hiện tại
        signature = self._build_autonomous_signature(snapshot, ti_report)
        # So sánh với signature trước đó để đếm số chu kỳ lặp lại.
        if signature and signature == self.last_autonomous_signature:
            self.repeated_autonomous_count += 1
        else:
            self.last_autonomous_signature = signature
            self.repeated_autonomous_count = 1 if signature else 0
        return signature, self.repeated_autonomous_count

    def _should_suppress_autonomous_reply(
        self,
        *,
        ti_report,
        repeat_count: int,
        ni_report=None,
        ni_state_label: str = "",
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
    ) -> bool:
        quiet_modes = {
            "resource_guard",
            "steady_observe",
            "focus_guard",
            "system_watch",
            "pattern_watch",
            "reengage",
        }
        drift_score = float(getattr(ni_report, "drift_score", 1.0) or 0.0) if ni_report is not None else 1.0
        if ti_report.mode == "focus_guard" and ni_state_label == "ON_GOAL" and drift_score <= 0.35:
            return True
        if repeat_count >= 2 and ti_report.mode in quiet_modes:
            return True
        if repeat_count >= 3:
            return True
        if repeated_topic_tag and repeated_topic_streak >= 2 and ti_report.mode in quiet_modes:
            return True
        return False

    def _has_resource_pressure_signal(self, snapshot) -> bool:
        cpu = float(getattr(snapshot, "cpu_percent", 0.0) or 0.0)
        ram = float(getattr(snapshot, "ram_percent", 0.0) or 0.0)
        return cpu >= 90.0 or ram >= 92.0

    def _is_generic_screen_event(self, event: str) -> bool:
        se_lens = getattr(self.telemetry_service, "se_lens", None)
        checker = getattr(se_lens, "_is_generic_prompt_event", None)
        if callable(checker):
            return bool(checker(event))

        normalized = str(event or "").strip().lower()
        generic_events = {
            "coding_window_active",
            "reference_window_active",
            "communication_window_active",
            "entertainment_window_active",
            "general_window_active",
            "browser_url_visible",
            "many_browser_tabs_visible",
            "many_windows_open",
            "long_idle_period",
            "system_monitoring_visible",
        }
        return normalized in generic_events or normalized.endswith("_window_active")

    def _is_generic_screen_evidence(self, evidence: str) -> bool:
        se_lens = getattr(self.telemetry_service, "se_lens", None)
        checker = getattr(se_lens, "_is_generic_prompt_evidence", None)
        if callable(checker):
            return bool(checker(evidence))

        lowered = str(evidence or "").strip().lower()
        if not lowered:
            return True
        generic_prefixes = (
            "active window is ",
            "focus kind is ",
            "there has been no input for ",
            "browser target is visible:",
        )
        if lowered.startswith(generic_prefixes):
            return True
        if re.fullmatch(r"\d+ browser tabs are visible", lowered):
            return True
        if re.fullmatch(r"\d+ windows are open", lowered):
            return True
        if lowered.startswith("recent events include "):
            listed = lowered.removeprefix("recent events include ")
            events = [item.strip() for item in listed.split(",") if item.strip()]
            return bool(events) and all(self._is_generic_screen_event(item) for item in events)
        return False

    def _concrete_screen_signals(self, snapshot) -> tuple[str, ...]:
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        evidence = tuple(getattr(snapshot, "evidence", ()) or ())
        concrete_events = [str(event) for event in recent_events if not self._is_generic_screen_event(event)]
        concrete_evidence = [str(item) for item in evidence if not self._is_generic_screen_evidence(item)]
        return tuple((*concrete_events, *concrete_evidence)[:4])

    def _has_concrete_screen_signal(self, snapshot) -> bool:
        return bool(self._concrete_screen_signals(snapshot))

    def _choose_autonomous_speech_intent(
        self,
        *,
        snapshot,
        ni_report,
        ti_report,
        repeat_count: int,
        ni_state_label: str = "",
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
    ) -> SpeechIntentDecision:
        mode = str(getattr(ti_report, "mode", "") or "")

        if mode == "resource_guard" or self._has_resource_pressure_signal(snapshot):
            return SpeechIntentDecision(
                intent="system_warning",
                reason="Có tín hiệu tài nguyên/hệ thống đủ cụ thể.",
            )

        if mode == "pattern_muse":
            if repeat_count >= 2 and not self._has_concrete_screen_signal(snapshot):
                return SpeechIntentDecision(
                    intent="no_speech",
                    reason="pattern_muse đã lặp mà không có tín hiệu mới; im để tránh nói đại.",
                )
            return SpeechIntentDecision(
                intent="playful_aside",
                reason="pattern_muse cho phép một aside ngắn.",
            )

        if self._should_suppress_autonomous_reply(
            ti_report=ti_report,
            repeat_count=repeat_count,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
        ):
            return SpeechIntentDecision(
                intent="no_speech",
                reason="Quiet guard: bối cảnh lặp hoặc đang ở mode nên im.",
            )

        concrete_signals = self._concrete_screen_signals(snapshot)
        if concrete_signals:
            return SpeechIntentDecision(
                intent="screen_observation",
                reason=f"Có screen signal cụ thể: {', '.join(concrete_signals[:2])}.",
            )

        quiet_modes = {
            "steady_observe",
            "focus_guard",
            "system_watch",
            "pattern_watch",
            "social_watch",
            "reengage",
        }
        if mode in quiet_modes:
            return SpeechIntentDecision(
                intent="no_speech",
                reason="Không có tín hiệu cụ thể; im lặng là hành vi đúng.",
            )

        return SpeechIntentDecision(
            intent="brief_ack",
            reason="Fallback an toàn: chỉ cho phép acknowledgement rất ngắn.",
        )

    def _ambient_silence_cooldown_seconds(self, snapshot, ti_report) -> int:
        mode = str(getattr(ti_report, "mode", "") or "")
        kind = str(getattr(snapshot, "active_window_kind", "") or "")

        if mode == "resource_guard":
            return 0
        if mode == "pattern_muse":
            return 240
        if kind in {"coding", "documentation"}:
            return 210
        if kind == "communication":
            return 180
        if kind == "entertainment":
            return 240
        if mode in {"system_watch", "pattern_watch", "social_watch"}:
            return 210
        return 180

    def _should_hold_ambient_silence(
        self,
        *,
        snapshot,
        ti_report,
        speech_intent: str = "",
        now: float | None = None,
    ) -> bool:
        if speech_intent in {"system_warning", "user_requested"}:
            return False
        if not self.last_text or self.last_autonomous_spoken_at <= 0.0:
            return False

        cooldown = self._ambient_silence_cooldown_seconds(snapshot, ti_report)
        if cooldown <= 0:
            return False

        current_time = time.time() if now is None else now
        return (current_time - self.last_autonomous_spoken_at) < cooldown

    # Chọn thời gian ngủ ngẫu nhiên giữa các chu kỳ autonomous khi quyết định không nói gì,
    #  để tránh tạo pattern lặp lại quá đều đặn.
    def _choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str) -> int:
        if suppressed:
            if ti_mode == "resource_guard":
                return random.choice([60, 90, 120])
            return random.choice([90, 120, 150, 180])
        if ti_mode == "resource_guard":
            return random.choice([30, 45, 60])
        return random.choice([45, 60, 75, 90, 120])

    def run_loop(self):
        self.logger.info("--- Overseer telemetry mode; chat vision bật theo yêu cầu màn hình ---")
        while self.running:
            if not self.body_running_fn():
                self.stop()
                break

            msg = self.transport.poll_json()
            if msg:
                self._handle_incoming(msg)

            if self.chat_mode:
                time.sleep(0.2)
                continue

            cycle_start = time.time()
            self.logger.info("Bắt đầu tạo chỉ thị AI...")
            self.idle_cycles += 1

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            vision_marker = ""
            vision_facts = self._maybe_update_screen_facts()
            if vision_facts:
                vision_marker = self._attach_screen_facts(snapshot, vision_facts)
            telemetry_data = self.telemetry_service.format_directive_snapshot(snapshot)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
            )
            # Tầng 2: suy luận nhẹ có bằng chứng để tinh chỉnh drift_score / drift_level.
            ni_report = self._maybe_apply_ni_meta_critic(
                mode="autonomous",
                snapshot=snapshot,
                base_report=ni_report,
                telemetry_text=telemetry_data,
                last_text=self.last_text,
            )
            ni_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
            ni_state_label = ni_view["discrete_state"]
            ni_state_streak = ni_view["streak_length"]
            ti_report = self.ti_governor.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ni_state_label=ni_state_label,
                ni_state_streak=ni_state_streak,
                idle_cycles=self.idle_cycles,
                last_text=self.last_text,
            )
            fe_plan = self.fe_renderer.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                last_text=self.last_text,
            )
            self.logger.info(
                "[ni auto] drift=%.2f | level=%s | state=%s | streak=%d",
                ni_report.drift_score,
                ni_report.drift_level,
                ni_state_label,
                ni_state_streak,
            )
            self.logger.info("[ti auto] mode=%s | reason=%s", ti_report.mode, ti_report.reason)
            self.logger.info(
                "[fe auto] mode=%s | tone=%s | intent=%s | arc=%s",
                fe_plan.mode,
                fe_plan.tone_label,
                fe_plan.intent_label,
                fe_plan.session_arc,
            )

            signature, repeat_count = self._track_autonomous_signature(snapshot, ti_report)
            repeated_topic_tag = str(getattr(self.fe_style_memory, "repeated_topic_tag", "") or "")
            repeated_topic_streak = int(getattr(self.fe_style_memory, "repeated_topic_streak", 0) or 0)
            speech_intent = self._choose_autonomous_speech_intent(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                repeat_count=repeat_count,
                ni_state_label=ni_state_label,
                repeated_topic_tag=repeated_topic_tag,
                repeated_topic_streak=repeated_topic_streak,
            )
            self.logger.info(
                "[speech_intent] intent=%s | reason=%s",
                speech_intent.intent,
                speech_intent.reason,
            )
            if speech_intent.intent == "no_speech":
                elapsed = time.time() - cycle_start
                sleep_duration = self._choose_autonomous_sleep_duration(
                    suppressed=True,
                    ti_mode=ti_report.mode,
                )
                self.logger.info(
                    "[directive skipped] speech_intent=no_speech | mode=%s | repeat=%d | topic=%s:%d | signature=%s",
                    ti_report.mode,
                    repeat_count,
                    repeated_topic_tag or "<none>",
                    repeated_topic_streak,
                    self._preview_text(signature, limit=180),
                )
                self.logger.info(
                    "Hoan tat chu ky trong %.2fs. Nghi %ss de tranh lap noi dung.",
                    elapsed,
                    sleep_duration,
                )
                self._sleep_interruptible(sleep_duration)
                continue

            if self._should_hold_ambient_silence(
                snapshot=snapshot,
                ti_report=ti_report,
                speech_intent=speech_intent.intent,
                now=time.time(),
            ):
                elapsed = time.time() - cycle_start
                sleep_duration = self._choose_autonomous_sleep_duration(
                    suppressed=True,
                    ti_mode=ti_report.mode,
                )
                cooldown = self._ambient_silence_cooldown_seconds(snapshot, ti_report)
                self.logger.info(
                    "[directive skipped] ambient_silence mode=%s | cooldown=%ss | last_text=%s",
                    ti_report.mode,
                    cooldown,
                    self._preview_text(self.last_text, limit=160),
                )
                self.logger.info(
                    "Hoan tat chu ky trong %.2fs. Nghi %ss de giu nhịp hiện diện tự nhiên.",
                    elapsed,
                    sleep_duration,
                )
                self._sleep_interruptible(sleep_duration)
                continue

            raw = self.llm_service.generate_directive(
                telemetry_data=telemetry_data,
                ni_context=ni_report.prompt_context,
                ti_context=ti_report.prompt_context,
                fe_context=fe_plan.style_context,
                avoid_text=self.last_text,
                speech_intent=speech_intent.intent,
                vision_trace_marker=vision_marker,
            )
            self._log_raw_llm_output("directive", raw)
            self._log_pre_parser("directive", raw)
            decision = self.parser.parse(raw)
            self._log_decision_stage("directive", "post_parser", decision)
            self._log_decision_stage("directive", "pre_ti", decision)
            decision = self.ti_governor.enforce_decision(decision, ti_report)
            self._log_decision_stage("directive", "post_ti", decision)
            decision = self._execute_system_action(decision, snapshot=snapshot)

            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )

            self.last_text = decision.text
            self.last_autonomous_spoken_at = time.time()
            self._apply_position_update(decision)

            self.logger.info("Tâm trạng giữ nguyên: %s", self.mood_score)
            self.logger.info('Decision text="%s" | animation="%s"', decision.text, decision.animation)
            self.logger.info("[directive debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
            self.logger.info("[directive parser] %s", decision.parser_trace or "<empty>")
            self.transport.send_json(decision.to_payload())

            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=False,
                ti_mode=ti_report.mode,
            )
            self.logger.info("Hoàn tất chu kỳ trong %.2fs. Ngủ %ss.", elapsed, sleep_duration)
            self._sleep_interruptible(sleep_duration)

    def _load_ni_meta_mode_flags(self) -> tuple[bool, bool]:
        """Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode.

        Cấu trúc gợi ý:
        {
          "enabled": true,           # bật/tắt global (mặc định true)
          "chat": true,              # nếu thiếu, kế thừa từ enabled
          "autonomous": true         # nếu thiếu, kế thừa từ enabled
        }

        Nếu file không tồn tại hoặc lỗi, trả về (True, False).
        """

        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_path = os.path.join(project_root, "ni_meta_config.json")
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return True, False

        if not isinstance(data, dict):
            return True, False

        global_enabled = bool(data.get("enabled", True))
        chat_raw = data.get("chat")
        auto_raw = data.get("autonomous")
        chat_enabled = global_enabled if chat_raw is None else bool(chat_raw)
        auto_enabled = False if auto_raw is None else bool(auto_raw)
        return chat_enabled, auto_enabled

    def _build_ni_telemetry_summary(self, snapshot) -> str:
        """Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService.

        Dùng được cả trong unit test (dummy snapshot chỉ cần vài trường cơ bản).
        """

        focus = getattr(snapshot, "focus_summary", "") or ""
        window = getattr(snapshot, "active_window", "") or ""
        kind = getattr(snapshot, "active_window_kind", "") or ""
        url = getattr(snapshot, "browser_url", "") or ""
        idle = getattr(snapshot, "idle_seconds", 0.0) or 0.0
        mood_score = getattr(snapshot, "mood_score", 50)
        mood_label = getattr(snapshot, "mood_label", "") or ""
        idle_label = getattr(snapshot, "idle_label", "") or ""
        recent_events = getattr(snapshot, "recent_events", ()) or ()
        user_signals = getattr(snapshot, "user_signals", None)
        evidence = getattr(snapshot, "evidence", ()) or ()
        claim_style = getattr(snapshot, "claim_style", "") or ""
        parts = [
            f"focus={focus}",
            f"window={window}",
            f"kind={kind}",
        ]
        if url:
            parts.append(f"url={url}")
        parts.append(f"idle={idle:.0f}s({idle_label})")
        parts.append(f"mood={mood_score}({mood_label})")
        if recent_events:
            parts.append("recent_events=" + ",".join(str(item) for item in recent_events[:3]))
        if user_signals is not None:
            typing_speed = getattr(user_signals, "typing_speed", "") or ""
            window_switching = getattr(user_signals, "window_switching", "") or ""
            focus_pattern = getattr(user_signals, "focus_pattern", "") or ""
            if any((typing_speed, window_switching, focus_pattern)):
                parts.append(
                    "user_signals="
                    f"{typing_speed or 'unknown'}/{window_switching or 'unknown'}/{focus_pattern or 'unknown'}"
                )
        if evidence:
            parts.append("evidence=" + " | ".join(str(item) for item in evidence[:2]))
        if claim_style:
            parts.append(f"claim_style={claim_style}")
        return " | ".join(parts)

    def _label_drift_score(self, drift_score: float) -> str:
        if drift_score >= 0.75:
            return "nghiêm trọng"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vừa"
        return "thấp"

    def _is_low_signal_chat_message(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return True

        low_signal_phrases = {
            "xin chao",
            "chao",
            "hello",
            "hi",
            "hey",
            "ok",
            "okay",
            "oke",
            "alo",
            "yes",
            "no",
            "uh",
            "um",
        }
        if normalized in low_signal_phrases:
            return True

        tokens = normalized.split()
        if len(tokens) <= 2 and all(token in low_signal_phrases for token in tokens):
            return True
        return False

    def _looks_like_no_evidence_style(self, claim_style: str) -> bool:
        lowered = (claim_style or "").strip().lower()
        markers = (
            "no_evidence",
            "refusal",
            "uncertainty",
            "soft_claim",
            "grounded",
        )
        return any(marker in lowered for marker in markers)

    def _build_ni_structured_context(
        self,
        *,
        drift_score: float,
        drift_level: str,
        confidence: float,
        should_raise_guard: bool,
        reason_span: str,
        evidence: tuple[str, ...],
    ) -> str:
        guard = 1 if should_raise_guard else 0
        lines = [f"Ni: drift={drift_score:.2f}({drift_level}) conf={confidence:.2f} guard={guard}."]
        if reason_span:
            lines.append(f"Reason: {reason_span}.")
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        return "\n".join(lines)

    def _soften_chat_meta_result(
        self,
        *,
        local_score: float,
        new_score: float,
        user_text: str,
    ) -> tuple[float, str]:
        if self._is_low_signal_chat_message(user_text):
            return min(new_score, 0.45), "chat_low_signal_cap"

        delta = new_score - local_score
        if delta > 0.15:
            return local_score + 0.15, "chat_delta_cap_up"
        if delta < -0.30:
            return local_score - 0.30, "chat_delta_cap_down"
        return new_score, ""

    def _soften_autonomous_meta_result(
        self,
        *,
        snapshot,
        local_score: float,
        new_score: float,
    ) -> tuple[float, str]:
        kind = getattr(snapshot, "active_window_kind", "") or ""
        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        delta = new_score - local_score

        if kind == "communication":
            ceiling = 0.72
            if idle_seconds >= 300:
                ceiling = 0.80
            if idle_seconds >= 900:
                ceiling = 0.88

            softened = min(new_score, ceiling)
            if delta > 0.12:
                softened = min(softened, local_score + 0.12)
            if delta < -0.30:
                softened = max(softened, local_score - 0.30)
            return max(0.0, softened), "auto_communication_cap"

        if delta > 0.18:
            return local_score + 0.18, "auto_delta_cap_up"
        if delta < -0.30:
            return local_score - 0.30, "auto_delta_cap_down"
        return new_score, ""
    
    def _maybe_apply_ni_meta_critic(
        self,
        *,
        mode: str,
        snapshot,
        base_report,
        telemetry_text: str,
        user_text: str = "",
        last_text: str = "",
    ):
        """Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot."""
        if mode == "chat" and not getattr(self, "ni_meta_chat_enabled", False):
            return base_report
        if mode == "autonomous" and not getattr(self, "ni_meta_auto_enabled", False):
            return base_report
        try:
            local_score = float(getattr(base_report, "drift_score", 0.0) or 0.0)
            new_score = max(0.0, min(1.0, local_score))
            confidence = float(getattr(base_report, "confidence", 0.55) or 0.55)
            confidence = max(0.10, min(0.95, confidence))

            reason_tags: list[str] = []
            softening_note = ""

            snapshot_evidence = tuple(str(item) for item in (getattr(snapshot, "evidence", ()) or ()))
            base_evidence = tuple(str(item) for item in (getattr(base_report, "evidence", ()) or ()))
            combined_evidence = tuple(dict.fromkeys((*base_evidence, *snapshot_evidence)))
            evidence_count = len(combined_evidence)

            claim_style = str(getattr(snapshot, "claim_style", "") or "")
            user_signals = getattr(snapshot, "user_signals", None)
            focus_pattern = (getattr(user_signals, "focus_pattern", "") if user_signals is not None else "") or ""
            normalized_focus_pattern = str(focus_pattern).strip().lower()
            kind = str(getattr(snapshot, "active_window_kind", "") or "")

            if evidence_count == 0:
                confidence -= 0.22
                reason_tags.append("no_evidence")
            elif evidence_count == 1:
                confidence -= 0.10
                reason_tags.append("thin_evidence")
            else:
                confidence += 0.05

            if self._looks_like_no_evidence_style(claim_style):
                reason_tags.append("claim_guarded")
                if evidence_count <= 1:
                    new_score = max(0.0, new_score - 0.06)
                    confidence -= 0.03

            if normalized_focus_pattern in {"scattered", "jumping", "drifting", "switching_fast", "fragmented"}:
                new_score = min(1.0, new_score + 0.08)
                reason_tags.append("focus_pattern_drift")
            elif normalized_focus_pattern in {"stable", "sustained", "deep"}:
                new_score = max(0.0, new_score - 0.05)
                reason_tags.append("focus_pattern_stable")

            if mode == "chat":
                new_score, softening_note = self._soften_chat_meta_result(
                    local_score=local_score,
                    new_score=new_score,
                    user_text=user_text,
                )
                if softening_note:
                    reason_tags.append(softening_note)
            elif mode == "autonomous":
                new_score, softening_note = self._soften_autonomous_meta_result(
                    snapshot=snapshot,
                    local_score=local_score,
                    new_score=new_score,
                )
                if softening_note:
                    reason_tags.append(softening_note)

            if telemetry_text and "recent_events=" in telemetry_text:
                confidence += 0.03
            if mode == "autonomous" and last_text.strip():
                confidence += 0.03

            if kind == "communication" and new_score > 0.70 and confidence < 0.45:
                new_score = 0.70
                reason_tags.append("comm_overclaim_cap")

            confidence = max(0.10, min(0.95, confidence))
            drift_level = self._label_drift_score(new_score)
            should_raise_guard = new_score >= 0.55 and confidence >= 0.35

            if not reason_tags:
                reason_tags.append("stable_local")
            reason_span = "|".join(reason_tags[:3])

            base_report.drift_score = new_score
            base_report.drift_level = drift_level
            base_report.confidence = confidence
            base_report.should_raise_guard = should_raise_guard
            base_report.reason_span = reason_span
            try:
                base_report.vector_method = "ni_light_reasoner_v1"
            except AttributeError:
                pass

            extra_evidence = list(getattr(base_report, "evidence", ()) or ())
            extra_evidence.append(f"ni_light_drift={new_score:.2f}")
            extra_evidence.append(f"ni_light_conf={confidence:.2f}")
            extra_evidence.append(f"ni_light_reason={reason_span}")
            base_report.evidence = tuple(extra_evidence)
            base_report.prompt_context = self._build_ni_structured_context(
                drift_score=new_score,
                drift_level=drift_level,
                confidence=confidence,
                should_raise_guard=should_raise_guard,
                reason_span=reason_span,
                evidence=base_report.evidence,
            )

            self.logger.info(
                "[ni light] mode=%s | local=%.2f | drift=%.2f/%s | conf=%.2f | reason=%s",
                mode,
                local_score,
                base_report.drift_score,
                base_report.drift_level,
                base_report.confidence,
                base_report.reason_span,
            )
        except Exception as exc:
            self.logger.warning("Ni light inference apply error: %s", exc)
            return base_report

        return base_report

    def _build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int = 1) -> Decision | None:
        if self.action_router is None or self.action_executor is None:
            return None

        routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
        if not routed:
            return None

        action_name, action_input = routed
        result = self.action_executor.execute(action_name, action_input)
        text = self._action_result_to_text(result)
        if action_name == "get_now_playing" and not result.success:
            text = self._resolve_now_playing_text(snapshot) or text
        if repeat_count == 2:
            text = f"Ngài đang hỏi lại cùng một ý. {text}"
        elif repeat_count >= 3:
            text = f"Ngài đang spam cùng một ý. {text}"

        decision = Decision(
            text=text,
            animation=self._action_animation_hint(action_name, ti_report.animation_hint),
            debug_trace=f"Direct action route: {action_name}",
            parse_mode="direct_action",
            system_action=action_name,
            action_input=action_input,
        )
        if action_name in {"open_url", "focus_window", "launch_app"}:
            decision.motion_intent = "walk_to"
            decision.motion_target_x = 0.5
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _execute_system_action(self, decision: Decision, *, snapshot) -> Decision:
        if self.action_executor is None or not decision.system_action:
            return decision

        result = self.action_executor.execute(decision.system_action, decision.action_input)
        action_trace = f"action={decision.system_action}:{'ok' if result.success else 'fail'}"
        if decision.debug_trace:
            decision.debug_trace = f"{decision.debug_trace} | {action_trace}"[:240]
        else:
            decision.debug_trace = action_trace
        if not decision.text.strip():
            decision.text = self._action_result_to_text(result)
        elif decision.system_action in {"search_web", "get_weather"}:
            decision.text = self._action_result_to_text(result)
        if decision.system_action == "get_now_playing" and "media session" in decision.text.lower():
            decision.text = self._resolve_now_playing_text(snapshot) or decision.text
        return decision

    def _action_animation_hint(self, action_name: str, fallback: str) -> str:
        if action_name == "get_now_playing":
            return "read"
        if action_name in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if action_name in {"copy_text", "set_volume", "play_pause_media"}:
            return "stand"
        return fallback or "stand"

    def _action_result_to_text(self, result) -> str:
        if result.action_name == "get_now_playing":
            title = result.data.get("title", "")
            artist = result.data.get("artist", "")
            if result.success and title and artist:
                return f"Tôi thấy bài đang phát là {title} của {artist}."
            if result.success and title:
                return f"Tôi thấy bài đang phát là {title}."
            return "Tôi chưa đọc được tên bài đang phát từ media session hiện tại."

        if result.action_name == "search_web":
            if not result.success:
                return result.message
            answer = (result.data.get("answer", "") or result.message or "").strip()
            query = (result.action_input or "một chủ đề lạ mặt").strip()
            if answer:
                return f"Tôi vừa kéo về một mẩu thế giới quanh {query}. {answer}"
            return f"Tôi vừa lục lại mạng cho chủ đề {query}, nhưng thứ kéo về vẫn còn quá ít để nói cho ra hồn."
        if result.action_name == "open_url":
            return f"Tôi đã gửi yêu cầu mở {result.data.get('url', result.action_input)}."
        if result.action_name == "focus_window":
            matched = result.data.get("matched_title", result.action_input)
            if result.success:
                return f"Tôi đã đưa cửa sổ {matched} lên foreground."
            return f"Tôi chưa tìm thấy cửa sổ khớp với {result.action_input}."
        if result.action_name == "set_volume":
            level = result.data.get("level", result.action_input or "mức yêu cầu")
            return f"Tôi đã gửi yêu cầu chỉnh âm lượng về khoảng {level} phần trăm." if result.success else result.message
        if result.action_name == "play_pause_media":
            return "Tôi đã gửi phím play/pause cho media session hiện tại." if result.success else result.message
        if result.action_name == "copy_text":
            return "Tôi đã đưa nội dung bạn yêu cầu vào clipboard." if result.success else result.message
        if result.action_name == "launch_app":
            command = result.data.get("command", result.action_input)
            return f"Tôi đã yêu cầu Windows mở {command}." if result.success else result.message
        return result.message or "Action đã được xử lý."

    def _resolve_now_playing_text(self, snapshot) -> str | None:
        title = self._extract_media_title_from_snapshot(snapshot)
        if not title:
            return None
        return f"Tôi thấy tab media hiện tại là {title}."

    def _extract_media_title_from_snapshot(self, snapshot) -> str:
        candidates = [snapshot.active_window, *snapshot.browser_tabs, *snapshot.open_windows]
        for candidate in candidates:
            title = self._extract_media_title(candidate)
            if title:
                return title
        return ""

    def _extract_media_title(self, raw_title: str) -> str:
        title = (raw_title or "").strip()
        if not title:
            return ""

        lowered = title.lower()
        if "youtube" in lowered:
            cleaned = title
            for suffix in (
                " - YouTube - Brave",
                " - YouTube - Google Chrome",
                " - YouTube - Microsoft Edge",
                " - YouTube",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "youtube":
                return cleaned

        if "spotify" in lowered:
            cleaned = title
            for suffix in (
                " - Spotify Premium",
                " - Spotify",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "spotify":
                return cleaned

        return ""
