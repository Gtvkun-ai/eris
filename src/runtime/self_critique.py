"""Self-critique → escalate → continue.

Triết lý: Eris phải tự biết khi nào câu nháp của nó "ngu" hoặc "thiếu công cụ",
rồi tự quyết bái sư (escalate sang model mạnh) thay vì để con người liệt kê keyword.

Ba mảnh trong một mixin:

1. SELF-CRITIQUE (metacognition nhẹ): chấm điểm câu nháp do model rẻ sinh ra.
   Mặc định rule-based (0 thêm latency cho lượt thường). Có hook LLM critic
   (ERIS_SELF_CRITIQUE_LLM=1) để nâng cấp sau.

2. ESCALATION (bái sư): điểm thấp / cần tool → chạy lại CẢ lượt trên model mạnh
   (escalation client của LlmService) cùng context, cùng schema.

3. CONTINUATION (vòng tiếp diễn): nếu model mạnh phát system_action → chạy tool →
   feed kết quả trở lại model mạnh → sinh câu nói cuối, có chặn vô hạn.

Toàn bộ fail-mềm: bất kỳ lỗi nào ở tầng này đều trả lại decision gốc, không bao
giờ làm chết hot path.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass


@dataclass(slots=True)
class CritiqueResult:
    """Kết quả tự đánh giá một câu nháp."""

    quality: float = 0.7
    needs_tool: bool = False
    tool_hint: str = ""
    action_input_hint: str = ""
    reason: str = ""
    source: str = "rule"


# ── Tín hiệu user muốn tra/hỏi nguồn ngoài (gián tiếp) ─────────────────────────
# Giữ HẸP để tránh escalate lượt thường. Chỉ bắt khi user rõ ràng nhờ tra cứu.
_LOOKUP_TRIGGERS = (
    "hỏi gemini",
    "hỏi sư phụ",
    "sư phụ",
    "nhờ gemini",
    "kêu nó tra",
    "kêu gemini",
    "tra giúp",
    "tra cứu",
    "tra xem",
    "search",
    "google",
    "tìm trên mạng",
    "tìm giúp",
    "tìm hộ",
    "lên mạng",
    "tin tức",
    "mới nhất",
    "cập nhật",
    "check giúp",
)
_WEATHER_TRIGGERS = (
    "thời tiết",
    "weather",
    "nhiệt độ",
    "dự báo",
    "trời mưa",
    "trời nắng",
)

# Câu từ chối khả năng trong khi tool TỒN TẠI → nặng tay nhất (đây là failure mode
# "bảo tra gemini → như điếc, bịa câu không có sư phụ").
_DENIAL_PATTERNS = (
    "không có sư phụ",
    "không có gemini",
    "tôi không thể tra",
    "không tra được",
    "tôi không biết",
    "không thể tìm",
    "tôi không có khả năng",
    "tôi không có công cụ",
    "tôi không truy cập",
    "tôi không có quyền truy cập",
)

# Câu rỗng/sáo (presence filler vô hồn).
_GENERIC_PATTERNS = (
    "tôi đây",
    "tôi đang nghe",
    "tôi vẫn quan sát",
    "tôi vẫn ở đây",
    "có gì không",
    "bạn cần gì",
    "tôi có thể giúp gì",
    "tôi luôn ở đây",
)

# Từ khoá cho thấy câu đang TUYÊN BỐ về màn hình (để kiểm grounding).
_SCREEN_CLAIM_TOKENS = (
    "màn hình",
    "cửa sổ",
    "đang mở",
    "trên màn",
    "tab ",
    "brave",
    "chrome",
    "gõ phím",
    "con trỏ",
    "đang xem",
    "đang chạy",
)


class SelfCritiqueEscalationMixin:
    """Tự phê → bái sư → tiếp diễn. Mix vào RuntimeCoordinator."""

    # ── Config ────────────────────────────────────────────────────────────────
    def _self_critique_enabled(self) -> bool:
        return str(os.environ.get("ERIS_SELF_CRITIQUE_ENABLED", "1")).strip().lower() not in {"0", "false", "off", "no"}

    def _self_critique_llm_enabled(self, user_text: str = "") -> bool:
        config_enabled = str(os.environ.get("ERIS_SELF_CRITIQUE_LLM", "0")).strip().lower() in {"1", "true", "on", "yes"}
        if config_enabled:
            return True
        if user_text:
            return self._classify_query_difficulty(user_text) != "none"
        return False

    def _classify_query_difficulty(self, user_text: str) -> str:
        """Phan loai do kho cua luot noi dua tren cau cua nguoi dung.
        - Chua code/cu phap hoac tu khoa phan tich hoac do dai > 120 ky tu -> "high" hoac "medium"
        - Tan gau don thuan, chao hoi -> "none"
        """
        text = str(user_text or "").strip()
        if not text:
            return "none"

        normalized = self._sc_normalize(text)

        # 1. Dau hieu code / lap trinh -> high difficulty
        code_indicators = (
            "def ", "class ", "import ", "function ", "const ", "let ", "var ",
            "python", "javascript", "js ", "html", "css", "c++", "c#", "java ",
            "sql", "git", "bash", "shell", "docker", "api", "json", "code", "hàm",
            "viết code", "sửa lỗi", "refactor", "bug", "thuật toán", "database",
            "binary search", "đệ quy", "loop", "vòng lặp", "mảng", "array", "object"
        )
        if any(indicator in normalized for indicator in code_indicators) or re.search(r"[{}()\[\]=+\-*/<>:;]{3,}", text):
            return "high"

        # 2. Dau hieu phan tich / lap luan phuc tap / nhieu buoc -> medium difficulty
        analysis_indicators = (
            "phân tích", "so sánh", "giải thích", "vì sao", "tại sao", "chứng minh",
            "đánh giá", "tối ưu", "cách làm", "hướng dẫn", "bước", "quy trình",
            "nguyên nhân", "lý do", "kiểm tra lỗi", "debug", "thiết kế", "kiến trúc",
            "architecture", "explain", "why", "how to", "optimize", "compare", "evaluate"
        )
        if any(indicator in normalized for indicator in analysis_indicators):
            return "medium"

        # 3. Do dai cau dai -> medium difficulty
        if len(text) > 120:
            return "medium"

        return "none"

    def _escalation_threshold(self) -> float:
        try:
            return float(os.environ.get("ERIS_ESCALATION_THRESHOLD", "0.5"))
        except (TypeError, ValueError):
            return 0.5

    def _escalation_max_continuations(self) -> int:
        try:
            return max(1, int(os.environ.get("ERIS_ESCALATION_MAX_CONTINUATIONS", "2")))
        except (TypeError, ValueError):
            return 2

    def _escalation_available(self) -> bool:
        svc = getattr(self, "llm_service", None)
        if svc is None:
            return False
        resolver = getattr(svc, "_resolve_escalation_client", None)
        if resolver is None:
            return False
        try:
            return resolver() is not None
        except Exception:
            return False

    # ── Text helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _sc_normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFC", str(text or "")).lower()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _sc_tokens(text: str) -> set[str]:
        stripped = unicodedata.normalize("NFC", str(text or "")).lower()
        words = re.findall(r"[0-9a-zà-ỹ]+", stripped, flags=re.UNICODE)
        return {w for w in words if len(w) > 3}

    def _sc_token_overlap(self, norm_text: str, facts: tuple[str, ...]) -> float:
        text_tokens = self._sc_tokens(norm_text)
        if not text_tokens:
            return 1.0  # không có token nội dung để kiểm → không phạt grounding
        fact_tokens: set[str] = set()
        for fact in facts:
            fact_tokens |= self._sc_tokens(fact)
        if not fact_tokens:
            return 1.0
        shared = text_tokens & fact_tokens
        return len(shared) / max(1, len(text_tokens))

    @staticmethod
    def _sc_claims_screen(norm_text: str) -> bool:
        return any(token in norm_text for token in _SCREEN_CLAIM_TOKENS)

    @staticmethod
    def _sc_join(existing: str, marker: str) -> str:
        existing = str(existing or "").strip()
        if not existing:
            return marker[:240]
        return f"{existing} | {marker}"[:240]

    def _sc_trace(self, decision, critique: CritiqueResult, *, channel: str) -> None:
        marker = f"critique[{channel}]:q={critique.quality:.2f},tool={int(critique.needs_tool)},src={critique.source}"
        try:
            decision.debug_trace = self._sc_join(getattr(decision, "debug_trace", ""), marker)
        except Exception:
            pass
        logger = getattr(self, "logger", None)
        if logger is not None:
            logger.debug(
                "[self_critique] channel=%s quality=%.2f needs_tool=%s reason=%s",
                channel,
                critique.quality,
                critique.needs_tool,
                critique.reason or "ok",
            )

    # ── MẢNH 1: SELF-CRITIQUE ─────────────────────────────────────────────────
    def _critique_decision(
        self,
        decision,
        *,
        channel: str,
        user_text: str = "",
        snapshot=None,
    ) -> CritiqueResult:
        text = getattr(decision, "text", "") or ""
        norm = self._sc_normalize(text)
        lowered_user = self._sc_normalize(user_text)
        system_action = (getattr(decision, "system_action", "") or "").strip()

        quality = 0.7
        reasons: list[str] = []
        needs_tool = False
        tool_hint = ""

        # 1) User nhờ tra/hỏi nguồn ngoài nhưng câu nháp KHÔNG có system_action.
        if not system_action and lowered_user:
            if any(trigger in lowered_user for trigger in _WEATHER_TRIGGERS):
                needs_tool = True
                tool_hint = "get_weather"
                reasons.append("weather_requested_no_action")
            elif any(trigger in lowered_user for trigger in _LOOKUP_TRIGGERS):
                needs_tool = True
                tool_hint = "search_web"
                reasons.append("lookup_requested_no_action")

        # 2) Từ chối khả năng trong khi đáng lẽ phải tra (điếc đặc).
        if needs_tool and any(pattern in norm for pattern in _DENIAL_PATTERNS):
            quality = min(quality, 0.1)
            reasons.append("capability_denial")

        # 3) Câu rỗng/sáo & ngắn.
        if norm and any(pattern in norm for pattern in _GENERIC_PATTERNS) and len(norm) < 70:
            quality = min(quality, 0.35)
            reasons.append("generic_filler")
        if norm and len(norm) < 6:
            quality = min(quality, 0.4)
            reasons.append("too_short")

        # 4) Tuyên bố về màn hình nhưng 0 bám vào vision_facts.
        if channel in {"autonomous", "force_speak", "directive"}:
            facts = tuple(getattr(self, "vision_facts", ()) or ())
            if facts and norm and self._sc_claims_screen(norm):
                overlap = self._sc_token_overlap(norm, facts)
                if overlap <= 0.0:
                    quality = min(quality, 0.4)
                    reasons.append("screen_claim_no_grounding")

        # 5) needs_tool luôn kéo điểm xuống dưới ngưỡng (bắt buộc bái sư).
        if needs_tool:
            quality = min(quality, 0.25)

        result = CritiqueResult(
            quality=quality,
            needs_tool=needs_tool,
            tool_hint=tool_hint,
            action_input_hint=(user_text or "").strip()[:160] if needs_tool else "",
            reason="; ".join(reasons) or "ok",
            source="rule",
        )

        # 6) (Tuỳ chọn) LLM critic nâng cấp khi bật cờ. Chỉ ghi đè khi nó thấy TỆ HƠN
        # rule, để không bao giờ "tha" cho câu mà rule đã bắt được.
        if self._self_critique_llm_enabled(user_text):
            llm_result = self._llm_critique_decision(decision, channel=channel, user_text=user_text)
            if llm_result is not None:
                result.quality = min(result.quality, llm_result.quality)
                result.needs_tool = result.needs_tool or llm_result.needs_tool
                result.tool_hint = result.tool_hint or llm_result.tool_hint
                result.reason = f"{result.reason}; llm:{llm_result.reason}"
                result.source = "rule+llm"

        return result

    def _llm_critique_decision(self, decision, *, channel: str, user_text: str = "") -> CritiqueResult | None:
        """LLM critic nhẹ (~50 token). Chấm grounded/specific/coherent + needs_tool.

        Dùng client chính của LlmService. Fail-mềm: lỗi nào cũng trả None để rule
        thắng. Mặc định TẮT (ERIS_SELF_CRITIQUE_LLM=0)."""
        svc = getattr(self, "llm_service", None)
        client = getattr(svc, "client", None) if svc is not None else None
        if client is None:
            return None
        draft = (getattr(decision, "text", "") or "").strip()
        if not draft:
            return None
        system_prompt = (
            "Bạn là tầng metacognition của một trợ lý. Chấm chất lượng câu nháp. "
            "Chỉ trả về JSON: {\"quality\": float 0..1, \"needs_tool\": bool, \"reason\": string ngắn}. "
            "quality thấp nếu câu chung chung/sáo rỗng/không bám dữ kiện/né tránh. "
            "needs_tool=true nếu cần tra web/hỏi nguồn ngoài mới trả lời đúng."
        )
        user_prompt = (
            (f"Người dùng nói: {user_text.strip()[:300]}\n" if user_text else "")
            + f"Câu nháp của trợ lý: {draft[:400]}\n"
            + "Chấm điểm câu nháp này."
        )
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=96,
                response_format={"type": "json_object"},
            )
            raw = svc._extract_content(response) if hasattr(svc, "_extract_content") else str(response)
            payload = json.loads(re.search(r"\{.*\}", raw, flags=re.DOTALL).group(0))
            quality = float(payload.get("quality", 0.7))
            needs_tool = bool(payload.get("needs_tool", False))
            reason = str(payload.get("reason", "")).strip()[:80]
            return CritiqueResult(
                quality=max(0.0, min(1.0, quality)),
                needs_tool=needs_tool,
                tool_hint="search_web" if needs_tool else "",
                reason=reason or "llm",
                source="llm",
            )
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[self_critique] llm critic failed: %s", exc)
            return None

    def _should_escalate(self, critique: CritiqueResult, *, channel: str) -> bool:
        if not self._self_critique_enabled():
            return False
        if not self._escalation_available():
            return False
        return critique.needs_tool or critique.quality < self._escalation_threshold()

    # ── MẢNH 3: CONTINUATION (vòng tiếp diễn tool) ─────────────────────────────
    def _summarize_action_result_for_llm(self, result) -> str:
        name = getattr(result, "action_name", "") or "action"
        if not getattr(result, "success", False):
            return f"[{name}] thất bại: {getattr(result, 'message', '')}"
        data = getattr(result, "data", {}) or {}
        if name == "search_web":
            answer = (data.get("answer", "") or getattr(result, "message", "")).strip()
            return f"[search_web] {answer}" if answer else f"[search_web] {getattr(result, 'message', '')}"
        if name == "get_weather":
            summary = data.get("summary", "") or getattr(result, "message", "")
            return f"[get_weather] {summary}"
        if name == "get_now_playing":
            title = data.get("title", "")
            artist = data.get("artist", "")
            label = " - ".join(part for part in (title, artist) if part)
            return f"[get_now_playing] {label}" if label else f"[get_now_playing] {getattr(result, 'message', '')}"
        return f"[{name}] {getattr(result, 'message', '')}"

    def _run_tool_continuation(self, decision, *, channel: str, snapshot, regenerate):
        executor = getattr(self, "action_executor", None)
        if executor is None:
            return decision
        max_steps = self._escalation_max_continuations()
        steps = 0
        while getattr(decision, "system_action", "") and steps < max_steps:
            action_name = decision.system_action
            result = executor.execute(action_name, decision.action_input)
            steps += 1
            decision.debug_trace = self._sc_join(
                decision.debug_trace,
                f"cont_action={action_name}:{'ok' if result.success else 'fail'}",
            )
            tool_summary = self._summarize_action_result_for_llm(result)
            regenerated = None
            try:
                regenerated = regenerate(tool_summary)
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.warning("[escalation] continuation regenerate error: %s", exc)
            if regenerated is None:
                # Không sinh lại được → dùng text tất định của tool rồi dừng.
                if not (decision.text or "").strip() or action_name in {"search_web", "get_weather"}:
                    decision.text = self._action_result_to_text(result)
                decision.system_action = ""
                decision.action_input = ""
                return decision
            regenerated.debug_trace = self._sc_join(getattr(regenerated, "debug_trace", ""), f"after_tool={action_name}")
            decision = regenerated

        # Hết lượt mà vẫn còn action treo → chạy tất định lần cuối rồi xoá.
        if getattr(decision, "system_action", ""):
            result = executor.execute(decision.system_action, decision.action_input)
            if not (decision.text or "").strip() or decision.system_action in {"search_web", "get_weather"}:
                decision.text = self._action_result_to_text(result)
            decision.system_action = ""
            decision.action_input = ""
        return decision

    # ── MẢNH 2: ESCALATION cho chat ────────────────────────────────────────────
    def _maybe_escalate_chat_decision(
        self,
        decision,
        *,
        user_text: str,
        snapshot,
        chat_generation_kwargs: dict,
        ti_report,
    ):
        if not self._self_critique_enabled():
            return decision
        try:
            critique = self._critique_decision(decision, channel="chat", user_text=user_text, snapshot=snapshot)
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[self_critique] chat critique failed: %s", exc)
            return decision

        self._sc_trace(decision, critique, channel="chat")
        if not self._should_escalate(critique, channel="chat"):
            return decision

        self.logger.info(
            "[escalation] chat draft escalated | quality=%.2f needs_tool=%s reason=%s",
            critique.quality,
            critique.needs_tool,
            critique.reason,
        )
        escalation_kwargs = dict(chat_generation_kwargs)
        if critique.needs_tool:
            escalation_kwargs["ti_context"] = (
                (escalation_kwargs.get("ti_context", "") or "")
                + f"\nESCALATION: Ngài đang nhờ tra cứu / hỏi nguồn ngoài. Nếu cần, đặt system_action="
                f"{critique.tool_hint} với action_input là truy vấn cụ thể. ĐỪNG từ chối khả năng tra cứu."
            )

        try:
            raw = self.llm_service.generate_chat_reply(**escalation_kwargs, use_escalation_client=True)
        except Exception as exc:
            self.logger.warning("[escalation] chat re-run failed: %s", exc)
            return decision

        try:
            strong = self.parser.parse(raw, user_hint=user_text)
            strong = self.ti_governor.enforce_decision(
                strong,
                ti_report,
                user_hint=user_text,
                vision_grounded=bool(getattr(self, "vision_facts", None)),
            )
        except Exception as exc:
            self.logger.warning("[escalation] chat parse/enforce failed: %s", exc)
            return decision

        strong.debug_trace = self._sc_join(strong.debug_trace, f"escalated:{critique.reason}")

        if getattr(strong, "system_action", ""):
            strong = self._run_tool_continuation(
                strong,
                channel="chat",
                snapshot=snapshot,
                regenerate=lambda tool_summary: self._regenerate_chat_after_tool(
                    escalation_kwargs,
                    tool_summary,
                    user_text=user_text,
                    ti_report=ti_report,
                ),
            )
        return strong

    def _regenerate_chat_after_tool(self, escalation_kwargs: dict, tool_summary: str, *, user_text: str, ti_report):
        kwargs = dict(escalation_kwargs)
        kwargs["grounding_context"] = (
            (kwargs.get("grounding_context", "") or "")
            + "\nTOOL_RESULT (đã tra cứu giúp Ngài; hãy diễn đạt tự nhiên thành câu nói của em, "
            f"KHÔNG đặt system_action nữa):\n{tool_summary}"
        )
        kwargs["ti_context"] = (
            (kwargs.get("ti_context", "") or "")
            + "\nĐã có kết quả công cụ ở trên; nói lại cho Ngài bằng giọng của em, không gọi thêm action."
        )
        try:
            raw = self.llm_service.generate_chat_reply(**kwargs, use_escalation_client=True)
        except Exception as exc:
            self.logger.warning("[escalation] chat continuation failed: %s", exc)
            return None
        decision = self.parser.parse(raw, user_hint=user_text)
        decision = self.ti_governor.enforce_decision(
            decision,
            ti_report,
            user_hint=user_text,
            vision_grounded=bool(getattr(self, "vision_facts", None)),
        )
        return decision

    # ── MẢNH 2: ESCALATION cho directive (autonomous / force_speak) ────────────
    def _maybe_escalate_directive_decision(
        self,
        decision,
        *,
        channel: str,
        snapshot,
        ti_report,
        directive_kwargs: dict,
        vision_grounded: bool = False,
    ):
        if not self._self_critique_enabled():
            return decision
        try:
            critique = self._critique_decision(decision, channel=channel, user_text="", snapshot=snapshot)
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[self_critique] %s critique failed: %s", channel, exc)
            return decision

        self._sc_trace(decision, critique, channel=channel)
        if not self._should_escalate(critique, channel=channel):
            return decision

        self.logger.info(
            "[escalation] %s draft escalated | quality=%.2f reason=%s",
            channel,
            critique.quality,
            critique.reason,
        )
        esc_kwargs = dict(directive_kwargs)
        esc_kwargs["ti_context"] = (
            (esc_kwargs.get("ti_context", "") or "")
            + "\nESCALATION: câu nháp trước nhạt hoặc thiếu bám dữ kiện. Nói một câu cụ thể, "
            "bám screen_facts / nhịp hiện tại, tránh câu sáo rỗng và tránh tự lùi."
        )

        try:
            raw = self.llm_service.generate_directive(**esc_kwargs, use_escalation_client=True)
        except Exception as exc:
            self.logger.warning("[escalation] %s re-run failed: %s", channel, exc)
            return decision

        try:
            strong = self.parser.parse(raw)
            strong = self.ti_governor.enforce_decision(strong, ti_report, vision_grounded=vision_grounded)
        except Exception as exc:
            self.logger.warning("[escalation] %s parse/enforce failed: %s", channel, exc)
            return decision

        strong.debug_trace = self._sc_join(strong.debug_trace, f"escalated:{critique.reason}")

        if getattr(strong, "system_action", ""):
            strong = self._run_tool_continuation(
                strong,
                channel=channel,
                snapshot=snapshot,
                regenerate=lambda tool_summary: self._regenerate_directive_after_tool(
                    esc_kwargs,
                    tool_summary,
                    ti_report=ti_report,
                    vision_grounded=vision_grounded,
                ),
            )
        return strong

    def _regenerate_directive_after_tool(self, esc_kwargs: dict, tool_summary: str, *, ti_report, vision_grounded: bool):
        kwargs = dict(esc_kwargs)
        kwargs["telemetry_data"] = (kwargs.get("telemetry_data", "") or "") + f"; TOOL_RESULT: {tool_summary}"
        kwargs["ti_context"] = (
            (kwargs.get("ti_context", "") or "")
            + "\nĐã có kết quả công cụ ở trên; nói lại tự nhiên bằng giọng của em, không gọi thêm action."
        )
        try:
            raw = self.llm_service.generate_directive(**kwargs, use_escalation_client=True)
        except Exception as exc:
            self.logger.warning("[escalation] directive continuation failed: %s", exc)
            return None
        decision = self.parser.parse(raw)
        decision = self.ti_governor.enforce_decision(decision, ti_report, vision_grounded=vision_grounded)
        return decision
