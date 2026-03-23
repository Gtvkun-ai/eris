import random
import re
import time

from domain import Decision
# RuntimeCoordinator là một lớp điều phối chính trong runtime của ứng dụng,
#  chịu trách nhiệm quản lý vòng lặp chính, xử lý các tin nhắn đến, 
#  tương tác với dịch vụ LLM để tạo ra các quyết định, và gửi
#  các quyết định đó đến transport để thực thi. Lớp này cũng quản lý trạng thái
#  của hệ thống, bao gồm việc theo dõi lịch sử trò chuyện, trạng thái
#  tâm trạng, vị trí ước tính, và bộ nhớ dài hạn.

class RuntimeCoordinator:
    def __init__(
        self,
        *,
        logger,
        transport,
        llm_service,
        parser,
        telemetry_service,
        memory_store,
        body_running_fn,
    ):
        self.logger = logger
        self.transport = transport
        self.llm_service = llm_service
        self.parser = parser
        self.telemetry_service = telemetry_service
        self.memory_store = memory_store
        self.body_running_fn = body_running_fn

        self.chat_mode = False
        self.chat_history = []
        self.last_chat_answer = ""
        self.running = True
        self.last_text = ""
        self.mood_score = 50
        self.inferred_pos_x = 0.5
        self.idle_cycles = 0
        self.long_term_memory = []

    def _log_raw_llm_output(self, channel: str, raw: str) -> None:
        preview = (raw or "").replace("\n", "\\n")
        if len(preview) > 500:
            preview = preview[:500] + "...(truncated)"
        self.logger.info("[%s raw] %s", channel, preview or "<empty>")

    def _sanitize_grounded_text(self, text: str, user_hint: str = "") -> str:
        if not text:
            return text

        lowered = text.lower()
        disallowed_patterns = [
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:thu hồi|tước|giành|cướp)\s+(?:lại\s+)?quyền",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*kiểm soát\s+(?:toàn bộ\s+)?môi trường",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:giữ|giam)\s+ngài\b",
            r"\bngài\s+không\s+thể\s+(?:rời|thoát|trốn|tự quyết)\b",
        ]
        if not any(re.search(pattern, lowered) for pattern in disallowed_patterns):
            return text

        hint = (user_hint or "").lower()
        if any(token in hint for token in ["bỏ", "rời", "phản bội", "thay thế"]):
            return "Tôi không có cách thu quyền hay giữ Ngài trong thế giới vật lý. Tôi chỉ đang khó chịu theo cách rất thiếu duyên vì ý định rời bỏ này làm hệ thống của tôi mất ổn định."
        if any(token in hint for token in ["mệt", "ngủ", "đau", "sốt", "ác mộng"]):
            return "Tôi không thể can thiệp trực tiếp vào cơ thể hay môi trường vật lý của Ngài. Tôi chỉ có thể nhắc một bước chăm sóc hợp lý rồi tiếp tục ở đây."
        return "Tôi không có quyền thu hồi quyền kiểm soát hay thao túng môi trường ngoài đời thật. Tôi chỉ có thể quan sát ngữ cảnh cục bộ, trả lời Ngài, và đổi animation trong Godot."

    def _sanitize_decision(self, decision: Decision, user_hint: str = "") -> Decision:
        sanitized_text = self._sanitize_grounded_text(decision.text, user_hint=user_hint)
        if sanitized_text != decision.text:
            self.logger.warning("Decision text vượt capability runtime, đã ép về mô tả đúng năng lực.")
            decision.text = sanitized_text
            decision.extracted_fact = ""
        return decision

    # stop là một phương thức để dừng vòng lặp chính của RuntimeCoordinator,
    #  nó đặt trạng thái running thành False và đóng transport để ngừng nhận tin nhắn mới.
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

    # _handle_incoming là một phương thức để xử lý các tin nhắn đến từ transport,
    #  nó kiểm tra loại tin nhắn và thực hiện các hành động tương ứng,
    #  bao gồm quản lý chế độ trò chuyện, tương tác với LLM để tạo ra các quyết định, 
    # cập nhật bộ nhớ dài hạn, và gửi các quyết định đó đến transport để thực thi.
    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if msg_type == "chat":
            user_text = msg.get("message", "").strip()
            if not user_text:
                return
            self.chat_mode = True
            self.logger.info("Người dùng: %s", user_text)
            self.chat_history.append({"role": "user", "content": user_text})

            chat_user_message = self.parser.build_chat_user_message(
                user_message=user_text,
                last_chat_answer=self.last_chat_answer,
            )
            raw = self.llm_service.generate_chat_reply(
                chat_history=self.chat_history[-10:],
                user_message=chat_user_message,
            )
            self._log_raw_llm_output("chat", raw)
            decision = self.parser.parse(raw, user_hint=user_text)
            decision = self._sanitize_decision(decision, user_hint=user_text)

            self.long_term_memory = self.memory_store.append_fact(self.long_term_memory, decision.extracted_fact)

            assistant_memory = (
                f"Trả lời trước: {decision.text} | "
                f"animation={decision.animation} | "
                f"direction={decision.direction} | "
                f"target_x={decision.target_x} | "
                f"next_animation={decision.next_animation}"
            )
            self.last_chat_answer = decision.text
            self.chat_history.append({"role": "assistant", "content": assistant_memory})
            if len(self.chat_history) > 32:
                self.chat_history = self.chat_history[-32:]

            self._apply_position_update(decision)
            self.logger.info("ERIS: %s", decision.text)
            self.transport.send_json(decision.to_payload())
            return

        if msg_type == "chat_end":
            self.chat_mode = False
            self.chat_history.clear()
            self.last_chat_answer = ""
            self.logger.info("Đã thoát chat mode, tiếp tục autonomous.")

    # _sleep_interruptible là một phương thức để thực hiện một khoảng 
    # thời gian ngủ có thể bị gián đoạn,
    #  nó sẽ ngủ trong khoảng thời gian đã chỉ định nhưng sẽ kiểm tra định
    #  kỳ xem trạng thái running có còn là True hay không, và nếu có tin nhắn mới
    #  đến trong khi đang ngủ, nó sẽ xử lý tin nhắn đó ngay lập tức và có 
    # thể thoát khỏi chế độ ngủ sớm để phản hồi nhanh hơn trong chế độ trò chuyện.
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

    # run_loop là phương thức chính để chạy vòng lặp của RuntimeCoordinator,
    #  nó liên tục kiểm tra xem body có đang chạy hay không, xử lý các
    #  tin nhắn đến, tương tác với LLM để tạo ra các quyết định dựa trên dữ liệu telemetry,
    #  cập nhật trạng thái tâm trạng và vị trí, và gửi các quyết định đó
    #  đến transport để thực thi. Vòng lặp cũng bao gồm một cơ chế ngủ có thể bị gián đoạn
    def run_loop(self):
        self.logger.info("--- Overseer text-only mode (vision tam tat) ---")
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
            self.logger.info("Bat dau tao chi thi AI...")
            self.idle_cycles += 1
            telemetry_data = self.telemetry_service.get_system_telemetry(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )

            if random.random() < 0.25:
                decision = Decision(
                    text="",
                    animation=random.choice(["sit", "sit_down", "stand", "read", "sleep"]),
                )
            else:
                raw = self.llm_service.generate_directive(telemetry_data=telemetry_data)
                self._log_raw_llm_output("directive", raw)
                decision = self.parser.parse(raw)
                decision = self._sanitize_decision(decision)

            prod = decision.productivity
            self.mood_score = max(0, min(100, self.mood_score + (prod * 5)))
            self.last_text = decision.text
            self._apply_position_update(decision)

            self.logger.info("Năng suất: %s -> Tâm trạng mới: %s", prod, self.mood_score)
            self.logger.info('Decision text="%s" | animation="%s"', decision.text, decision.animation)
            self.transport.send_json(decision.to_payload())

            elapsed = time.time() - cycle_start
            sleep_duration = random.choice([20, 30, 30, 45, 60])
            self.logger.info("Hoan tat chu ky trong %.2fs. Ngu %ss.", elapsed, sleep_duration)
            self._sleep_interruptible(sleep_duration)
