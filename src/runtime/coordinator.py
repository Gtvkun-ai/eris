import json
import os
import random
import re
import time
import unicodedata
from urllib.parse import urlparse

from cortex.ni import NiStateMachine
from domain import Decision


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
        self.long_term_memory = []
        self.fe_style_memory = self.fe_renderer.create_memory()
        # NiStateMachine giữ state drift rời rạc theo thời gian (ON_GOAL / BORDERLINE / OFF_GOAL)
        #  dựa trên chuỗi GoalDriftReport, thay vì chỉ nhìn một snapshot đơn lẻ.
        self.autonomous_ni_state = NiStateMachine()
        self.chat_ni_state = NiStateMachine()
        # Bật/tắt tầng meta-cognition Ni dùng LLM: kết hợp env var và JSON config.
        # Env ERIS_NI_META_CRITIC là kill-switch tổng (0/false/no/off để tắt toàn bộ).
        # File ni_meta_config.json cho phép bật/tắt theo mode: chat/autonomous.
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

    def stop(self):
        self.running = False
        self.transport.close()

    def _apply_position_update(self, decision: Decision) -> None:
        tx = decision.target_x
        if tx is not None and 0.0 <= tx <= 1.0:
            self.inferred_pos_x = tx
        elif decision.direction == -1:
            self.inferred_pos_x = max(0.0, self.inferred_pos_x - 0.4)
        elif decision.direction == 1:
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
        if msg_type == "chat":
            user_text = msg.get("message", "").strip()
            if not user_text:
                return
            if not self.chat_mode:
                self.chat_ni_state = NiStateMachine()

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            ni_report = self.ni_engine.evaluate_chat(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                user_text=user_text,
            )
            # Tầng 2: meta-cognition bằng LLM để tinh chỉnh drift_score / drift_level.
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
            raw = self.llm_service.generate_chat_reply(
                chat_history=self.chat_history[-10:],
                user_message=chat_user_message,
                ni_context=ni_report.prompt_context,
                ti_context=ti_report.prompt_context,
                fe_context=fe_plan.style_context,
            )
            self._log_raw_llm_output("chat", raw)
            decision = self.parser.parse(raw, user_hint=user_text)
            decision = self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)
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
        while self.running and time.time() < end_at:
            time.sleep(0.2)
            if not self.body_running_fn():
                self.stop()
                return
            msg = self.transport.poll_json()
            if msg:
                self._handle_incoming(msg)
                if self.chat_mode:
                    return

    def run_loop(self):
        self.logger.info("--- Overseer text-only mode (vision tạm tắt) ---")
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
            telemetry_data = self.telemetry_service.format_snapshot(snapshot)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
            )
            # Tầng 2: meta-cognition bằng LLM để tinh chỉnh drift_score / drift_level.
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

            raw = self.llm_service.generate_directive(
                telemetry_data=telemetry_data,
                ni_context=ni_report.prompt_context,
                ti_context=ti_report.prompt_context,
                fe_context=fe_plan.style_context,
            )
            self._log_raw_llm_output("directive", raw)
            decision = self.parser.parse(raw)
            decision = self.ti_governor.enforce_decision(decision, ti_report)
            decision = self._execute_system_action(decision, snapshot=snapshot)

            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )

            self.last_text = decision.text
            self._apply_position_update(decision)

            self.logger.info("Tâm trạng giữ nguyên: %s", self.mood_score)
            self.logger.info('Decision text="%s" | animation="%s"', decision.text, decision.animation)
            self.logger.info("[directive debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
            self.logger.info("[directive parser] %s", decision.parser_trace or "<empty>")
            self.transport.send_json(decision.to_payload())

            elapsed = time.time() - cycle_start
            sleep_duration = random.choice([20, 30, 30, 45, 60])
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
        parts = [
            f"focus={focus}",
            f"window={window}",
            f"kind={kind}",
        ]
        if url:
            parts.append(f"url={url}")
        parts.append(f"idle={idle:.0f}s({idle_label})")
        parts.append(f"mood={mood_score}({mood_label})")
        return " | ".join(parts)

    def _build_ni_feature_vector(self, *, mode: str, snapshot, base_report, user_text: str, last_text: str) -> dict:
        """Xây feature vector cho tầng meta-cognition Ni dựa trên snapshot + báo cáo local.

        Không phụ thuộc chi tiết nội bộ của NiEngine, chỉ dùng TelemetrySnapshot và GoalDriftReport.
        """

        browser_url = getattr(snapshot, "browser_url", "") or ""
        domain = ""
        if browser_url:
            try:
                parsed = urlparse(browser_url)
                domain = (parsed.netloc or "").lower()
            except Exception:
                domain = ""

        focus = getattr(snapshot, "focus_summary", "") or ""
        window = getattr(snapshot, "active_window", "") or ""
        kind = getattr(snapshot, "active_window_kind", "") or ""
        idle = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        idle_label = getattr(snapshot, "idle_label", "") or ""
        mood_score = int(getattr(snapshot, "mood_score", 50) or 50)
        mood_label = getattr(snapshot, "mood_label", "") or ""
        open_windows = getattr(snapshot, "open_windows", ()) or ()

        drift_score_local = float(getattr(base_report, "drift_score", 0.0) or 0.0)
        similarity_local = float(getattr(base_report, "similarity", 0.0) or 0.0)
        drift_level_local = getattr(base_report, "drift_level", "") or ""
        should_raise_guard_local = bool(getattr(base_report, "should_raise_guard", False))
        feature_vector = {
            "mode": mode,
            "window_kind": kind,
            "active_window": window,
            "focus_summary": focus,
            "browser_url": browser_url,
            "browser_domain": domain,
            "idle_seconds": idle,
            "idle_label": idle_label,
            "mood_score": mood_score,
            "mood_label": mood_label,
            "open_window_count": len(open_windows),
            "drift_score_local": drift_score_local,
            "similarity_local": similarity_local,
            "drift_level_local": drift_level_local,
            "should_raise_guard_local": should_raise_guard_local,
            "long_term_memory_size": len(self.long_term_memory),
            "user_text_present": bool(user_text),
            "last_text_present": bool(last_text),
        }
        return feature_vector

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
        """Chạy tầng LLM meta-cognition cho Ni nếu được bật.

        Nếu có lỗi (LLM không sẵn, JSON hỏng, v.v.) thì trả lại base_report nguyên vẹn.
        """
        # Kiểm tra cấu hình theo mode.
        if mode == "chat" and not getattr(self, "ni_meta_chat_enabled", False):
            return base_report
        if mode == "autonomous" and not getattr(self, "ni_meta_auto_enabled", False):
            return base_report

        meta_fn = getattr(self.llm_service, "run_ni_meta_critic", None)
        if not callable(meta_fn):
            return base_report

        # Xây feature vector tổng hợp từ snapshot và báo cáo drift local để LLM đánh giá lại drift_score / drift_level.
        local_score = float(getattr(base_report, "drift_score", 0.0) or 0.0)
        local_level = getattr(base_report, "drift_level", "") or ""
        try:
            feature_vector = self._build_ni_feature_vector(
                mode=mode,
                snapshot=snapshot,
                base_report=base_report,
                user_text=user_text,
                last_text=last_text,
            )
            raw = meta_fn(
                goals=[],
                telemetry_text=telemetry_text,
                feature_vector=feature_vector,
            )
            self._log_raw_llm_output("ni_meta", raw)
            if not raw:
                return base_report
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return base_report
        except Exception as exc:
            self.logger.warning("Ni meta-critic error: %s", exc)
            return base_report

        # Áp dụng kết quả meta-critic lên GoalDriftReport hiện tại.
        try:
            raw_score = payload.get("drift_score", base_report.drift_score)
            try:
                new_score = float(raw_score)
            except (TypeError, ValueError):
                new_score = base_report.drift_score
            else:
                if new_score < 0.0:
                    new_score = 0.0
                if new_score > 1.0:
                    new_score = 1.0

            level_raw = str(payload.get("drift_level", base_report.drift_level) or "").strip().lower()
            level_map = {
                "thap": "thấp",
                "thấp": "thấp",
                "vua": "vừa",
                "vừa": "vừa",
                "cao": "cao",
                "nghiem trong": "nghiêm trọng",
                "nghiem_trong": "nghiêm trọng",
                "nghiêm trọng": "nghiêm trọng",
            }
            drift_level = level_map.get(level_raw, base_report.drift_level)

            explanation = str(payload.get("explanation", "") or "").strip()
            softening_note = ""

            if mode == "chat":
                new_score, softening_note = self._soften_chat_meta_result(
                    local_score=local_score,
                    new_score=new_score,
                    user_text=user_text,
                )
                drift_level = self._label_drift_score(new_score)
            elif mode == "autonomous":
                new_score, softening_note = self._soften_autonomous_meta_result(
                    snapshot=snapshot,
                    local_score=local_score,
                    new_score=new_score,
                )
                drift_level = self._label_drift_score(new_score)

            base_report.drift_score = new_score
            base_report.drift_level = drift_level
            # should_raise_guard dựa trên điểm số mới.
            base_report.should_raise_guard = new_score >= 0.55
            # Đánh dấu vector_method để biết báo cáo đã qua tầng meta-critic.
            try:
                base_report.vector_method = "ni_meta_critic_local_llm"
            except AttributeError:
                # Nếu GoalDriftReport cũ không có field này thì bỏ qua.
                pass

            # Bổ sung evidence và context với lời giải thích của LLM nếu có.
            extra_evidence = list(getattr(base_report, "evidence", ()) or ())
            extra_evidence.append(f"ni_meta_drift={new_score:.2f}")
            if softening_note:
                extra_evidence.append(f"ni_meta_adjustment={softening_note}")
            if explanation:
                snippet = explanation.replace("\n", " ")[:200]
                extra_evidence.append(f"ni_meta_explanation={snippet}")
            base_report.evidence = tuple(extra_evidence)

            if explanation:
                base_report.prompt_context = (base_report.prompt_context or "").split("\n[Ni meta-critic] ", 1)[0]

            if explanation:
                base_report.prompt_context = (
                    (base_report.prompt_context or "")
                    + "\n[Ni meta-critic] Giải thích: "
                    + explanation
                )
                base_report.prompt_context = base_report.prompt_context.split("\n[Ni meta-critic] ", 1)[0]
            # Logging so sánh local vs LLM để dễ tune prompt/meta-critic.
            self.logger.info(
                "[ni meta] mode=%s | local=%.2f/%s | llm=%.2f/%s",
                mode,
                local_score,
                local_level or "<none>",
                base_report.drift_score,
                base_report.drift_level,
            )
        except Exception as exc:
            self.logger.warning("Ni meta-critic apply error: %s", exc)
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
