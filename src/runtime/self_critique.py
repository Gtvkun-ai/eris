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

from semantic_authority import SemanticAuthorityPolicy
from runtime.acceptance_types import GateVerdict


@dataclass(slots=True)
class CritiqueResult:
    """Kết quả tự đánh giá một câu nháp."""

    quality: float = 0.7
    needs_tool: bool = False
    tool_hint: str = ""
    action_input_hint: str = ""
    reason: str = ""
    source: str = "rule"
    mentor_wanted: bool = False
    rewrite_text: str = ""
    drop: bool = False


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
        if SemanticAuthorityPolicy.from_env().qwen_first:
            # Qwen-first uses explicit confidence/tags plus an advisory mentor
            # pass. Do not sneak the old keyword difficulty classifier back in.
            return False
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

        semantic_policy = SemanticAuthorityPolicy.from_env()
        if semantic_policy.qwen_first:
            return semantic_policy.primary_reasoning_effort

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

    def _utterance_evaluator(self):
        evaluator = getattr(self, "_utterance_evaluator_instance", None)
        if evaluator is not None:
            return evaluator
        try:
            from runtime.utterance_evaluator import UtteranceEvaluator

            evaluator = UtteranceEvaluator()
            self._utterance_evaluator_instance = evaluator
            return evaluator
        except Exception:
            return None

    def _sentence_mentor_enabled(self) -> bool:
        try:
            from runtime.utterance_evaluator import mentor_enabled

            return mentor_enabled()
        except Exception:
            return str(os.environ.get("ERIS_SENTENCE_MENTOR", "1")).strip().lower() not in {"0", "false", "off", "no"}

    def _mentor_critique_decision(
        self,
        decision,
        *,
        channel: str,
        user_text: str,
        mentor_context: str,
    ) -> CritiqueResult | None:
        """Gọi escalation/Gemini như một người dạy khâu nghe lại câu.

        Khác với re-run toàn lượt: mentor chỉ chấm câu nháp và, nếu cứu được,
        trả một câu sửa ngắn. Nó được gọi sau khi local evaluator đã phát hiện
        vấn đề, nên không tốn call cho mọi câu bình thường.
        """

        if not self._sentence_mentor_enabled():
            return None
        svc = getattr(self, "llm_service", None)
        if svc is None:
            return None
        resolver = getattr(svc, "_resolve_escalation_client", None)
        client = None
        if callable(resolver):
            try:
                client = resolver()
            except Exception:
                client = None
        client = client or getattr(svc, "style_client", None) or getattr(svc, "client", None)
        if client is None:
            return None
        draft = str(getattr(decision, "text", "") or "").strip()
        if not draft:
            return None
        system_prompt = (
            "Bạn là 'sư phụ' đánh giá câu nói của ERIS trước khi public. "
            "Không viết văn dài. Hãy quyết định câu nháp có đáng nói không, có bám evidence không, "
            "có tự suy diễn hoạt động của người dùng không, và có duyên tối thiểu không. "
            "Nếu câu sai frame/evidence, sửa thành một câu Việt ngắn hoặc bảo drop. "
            "Không thêm fact mới. Không nói về JSON/parser/debug. "
            "Chỉ trả JSON: {\"quality\":0..1,\"verdict\":\"allow|rewrite|drop\","
            "\"text\":\"câu sửa hoặc rỗng\",\"reason\":\"ngắn\"}."
        )
        user_prompt = (
            f"Channel: {channel}\n"
            f"User text: {str(user_text or '').strip()[:400]}\n"
            f"Draft:\n{draft[:700]}\n\n"
            f"Evaluation context:\n{mentor_context[:1600]}\n\n"
            "Rubric: đúng frame > có duyên > ngắn. Một câu đúng mà nhạt vẫn hơn một câu vivid nhưng sai."
        )
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.15,
                frequency_penalty=0.1,
                presence_penalty=0.0,
                max_tokens=180,
                response_format={"type": "json_object"},
                grammar=None,
            )
            raw = svc._extract_content(response) if hasattr(svc, "_extract_content") else str(response)
            extracted = svc._extract_first_json_object(raw) if hasattr(svc, "_extract_first_json_object") else None
            payload = json.loads(extracted or re.search(r"\{.*\}", raw, flags=re.DOTALL).group(0))
            quality = float(payload.get("quality", 0.7))
            verdict = str(payload.get("verdict", "allow") or "allow").strip().lower()
            text = str(payload.get("text", "") or "").strip()
            reason = str(payload.get("reason", "") or "mentor").strip()[:120]
            return CritiqueResult(
                quality=max(0.0, min(1.0, quality)),
                reason=reason,
                source="mentor",
                rewrite_text=text if verdict == "rewrite" else "",
                drop=verdict == "drop",
            )
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[sentence_mentor] failed: %s", exc)
            return None

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
        mentor_wanted = False
        mentor_context = ""
        drop = False

        semantic_policy = SemanticAuthorityPolicy.from_env()

        # Legacy-only keyword router. In qwen_first, Qwen owns tool selection;
        # the runtime no longer sees "Gemini" or "tra" and wrestles the wheel.
        if not semantic_policy.qwen_first and not system_action and lowered_user:
            if any(trigger in lowered_user for trigger in _WEATHER_TRIGGERS):
                needs_tool = True
                tool_hint = "get_weather"
                reasons.append("weather_requested_no_action")
            elif any(trigger in lowered_user for trigger in _LOOKUP_TRIGGERS):
                needs_tool = True
                tool_hint = "search_web"
                reasons.append("lookup_requested_no_action")

        # Qwen may explicitly ask for mentor support through structured tags.
        if semantic_policy.qwen_first and semantic_policy.requests_mentor_support(decision):
            quality = min(quality, 0.30)
            mentor_wanted = True
            reasons.append("qwen_requested_mentor_support")

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

        # 6) Câu có quyền tồn tại không? Đây là rubric "độ người" nằm trước repair:
        # phát hiện sai frame, đoán hoạt động user, hoặc micro-line nhạt/sáo.
        evaluator = self._utterance_evaluator()
        if evaluator is not None:
            try:
                evaluation = evaluator.evaluate(
                    text,
                    channel=channel,
                    user_text=user_text,
                    snapshot=snapshot,
                    speech_core=getattr(decision, "speech_core", None),
                )
                if not evaluation.ok:
                    quality = min(quality, evaluation.quality)
                    reasons.append(f"utterance:{evaluation.reason}")
                    mentor_wanted = bool(evaluation.mentor_wanted)
                    drop = bool(evaluation.verdict == "drop")
                    mentor_context = evaluator.mentor_context(
                        text=text,
                        evaluation=evaluation,
                        channel=channel,
                        user_text=user_text,
                        snapshot=snapshot,
                    )
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.debug("[utterance_evaluator] failed: %s", exc)

        result = CritiqueResult(
            quality=quality,
            needs_tool=needs_tool,
            tool_hint=tool_hint,
            action_input_hint=(user_text or "").strip()[:160] if needs_tool else "",
            reason="; ".join(reasons) or "ok",
            source="rule",
            mentor_wanted=mentor_wanted,
            drop=drop,
        )

        if mentor_wanted and mentor_context and not semantic_policy.qwen_first:
            mentor = self._mentor_critique_decision(
                decision,
                channel=channel,
                user_text=user_text,
                mentor_context=mentor_context,
            )
            if mentor is not None:
                result.quality = min(result.quality, mentor.quality)
                result.reason = f"{result.reason}; mentor:{mentor.reason}"
                result.source = "rule+mentor"
                result.rewrite_text = mentor.rewrite_text
                result.drop = result.drop or mentor.drop

        # 7) (Tuỳ chọn) LLM critic nâng cấp khi bật cờ. Chỉ ghi đè khi nó thấy TỆ HƠN
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

    def _record_tool_grounding(self, result, *, action_name: str = ""):
        """Đưa kết quả tool vào provenance chung của turn hiện tại.

        `last_grounding_context` và frame.source_grounding dùng cùng một object,
        nên cập nhật tại đây sẽ có hiệu lực cho final guards mà không phải đổi
        chữ ký của cả pipeline.
        """

        report = getattr(self, "last_grounding_context", None)
        engine = getattr(self, "source_grounding_engine", None)
        recorder = getattr(engine, "record_tool_result", None)
        if not callable(recorder):
            return report
        try:
            updated = recorder(
                report,
                action_name=action_name or getattr(result, "action_name", ""),
                result=result,
            )
            if updated is not None:
                self.last_grounding_context = updated
            return updated
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[source grounding] record tool result failed: %s", exc)
            return report

    def _run_tool_continuation(self, decision, *, channel: str, snapshot, regenerate):
        executor = getattr(self, "action_executor", None)
        if executor is None:
            return decision
        max_steps = self._escalation_max_continuations()
        steps = 0
        while getattr(decision, "system_action", "") and steps < max_steps:
            action_name = decision.system_action
            result = executor.execute(action_name, decision.action_input)
            self._record_tool_grounding(result, action_name=action_name)
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
            self._record_tool_grounding(result, action_name=decision.system_action)
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
        if SemanticAuthorityPolicy.from_env().qwen_first:
            return self._qwen_first_support_cycle(
                decision,
                user_text=user_text,
                snapshot=snapshot,
                chat_generation_kwargs=chat_generation_kwargs,
                ti_report=ti_report,
            )
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
        if critique.rewrite_text:
            decision.text = critique.rewrite_text.strip()
            decision.debug_trace = self._sc_join(getattr(decision, "debug_trace", ""), "sentence_mentor_rewrite")
            return decision
        if not self._should_escalate(critique, channel="chat"):
            return decision

        self.logger.info(
            "[escalation] chat draft escalated | quality=%.2f needs_tool=%s reason=%s",
            critique.quality,
            critique.needs_tool,
            critique.reason,
        )
        escalation_kwargs = dict(chat_generation_kwargs)
        # chat_cycle đã có thể đặt use_escalation_client trong kwargs gốc.
        # Khi self-critique tự re-run, bỏ key cũ để không truyền trùng keyword
        # vào service wrapper (lỗi: got multiple values for keyword argument).
        escalation_kwargs.pop("use_escalation_client", None)
        if critique.needs_tool:
            escalation_kwargs["ti_context"] = (
                (escalation_kwargs.get("ti_context", "") or "")
                + f"\nESCALATION: bạn đang nhờ tra cứu / hỏi nguồn ngoài. Nếu cần, đặt system_action="
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


    def _qwen_first_gate_bundle(self, decision, *, user_text: str, chat_generation_kwargs: dict):
        """Dùng đúng TurnFrame/ResponseContract hiện tại cho critique và gate."""
        try:
            from actions.contracts import VALID_SYSTEM_ACTION_LIST
            from runtime.response_acceptance_gate import ResponseAcceptanceGate
            from runtime.response_contract import build_response_contract
            from runtime.turn_frame import build_turn_frame

            frame = getattr(self, "current_elegant_turn_frame", None)
            if frame is None or str(getattr(frame, "user_text", "") or "") != str(user_text or ""):
                previous = str(getattr(self, "last_chat_answer", "") or "")
                reply_context = chat_generation_kwargs.get("reply_context")
                previous_turn = getattr(reply_context, "previous_public_turn", None) if reply_context is not None else None
                if previous_turn is not None:
                    previous = str(getattr(previous_turn, "text", "") or previous)
                frame = build_turn_frame(
                    user_text=user_text,
                    previous_assistant_text=previous,
                    previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
                    interrupt_event=getattr(self, "pending_speech_interrupt_event", None),
                )
            contract = getattr(self, "current_response_contract", None)
            if contract is None:
                contract = build_response_contract(frame, capability_action_ids=VALID_SYSTEM_ACTION_LIST)
            gate = ResponseAcceptanceGate(capability_action_ids=VALID_SYSTEM_ACTION_LIST)
            result = gate.evaluate(decision, frame=frame, contract=contract)
            return gate, frame, contract, result
        except Exception as exc:
            try:
                self.logger.debug("[acceptance-gate] precheck failed: %s", exc)
            except Exception:
                pass
            return None

    def _qwen_first_resolve_gate_before_support(
        self,
        decision,
        *,
        user_text: str,
        chat_generation_kwargs: dict,
        ti_report,
    ):
        """Trả ``None`` khi PASS; trả Decision khi gate đã xử lý xong."""
        bundle = self._qwen_first_gate_bundle(
            decision, user_text=user_text, chat_generation_kwargs=chat_generation_kwargs
        )
        if bundle is None:
            return None
        gate, frame, contract, result = bundle
        try:
            decision.debug_trace = self._sc_join(
                getattr(decision, "debug_trace", ""),
                f"gate_precheck:{result.verdict.value}:{','.join(result.reasons[:3])}",
            )
        except Exception:
            pass
        if result.verdict == GateVerdict.PASS:
            return None
        if result.verdict in {GateVerdict.BLOCK, GateVerdict.DOMAIN_FALLBACK}:
            return gate.apply(decision, frame=frame, contract=contract)

        policy = SemanticAuthorityPolicy.from_runtime()
        if result.verdict == GateVerdict.CONSTRAINED_RERUN and policy.bounded_refine_enabled:
            critique = CritiqueResult(
                quality=0.0,
                reason="acceptance_gate:" + ",".join(result.reasons[:6]),
                source="acceptance_gate",
            )
            try:
                from runtime.observability import ensure_observability
                ensure_observability(self).record_constrained_rerun(outcome="attempt", reasons=result.reasons, count=1)
            except Exception:
                pass
            revised = self._qwen_first_constrained_rerun(
                decision,
                user_text=user_text,
                critique=critique,
                chat_generation_kwargs=chat_generation_kwargs,
                ti_report=ti_report,
                notes=result.rerun_notes,
            )
            if revised is not None:
                second = gate.evaluate(revised, frame=frame, contract=contract)
                revised.debug_trace = self._sc_join(
                    getattr(revised, "debug_trace", ""),
                    f"gate_after_rerun:{second.verdict.value}:{','.join(second.reasons[:3])}",
                )
                try:
                    from runtime.observability import ensure_observability
                    ensure_observability(self).record_constrained_rerun(
                        outcome="pass" if second.verdict == GateVerdict.PASS else "fallback",
                        reasons=second.reasons,
                        count=0,
                    )
                except Exception:
                    pass
                if second.verdict == GateVerdict.PASS:
                    return gate.apply(revised, frame=frame, contract=contract)
                return gate.apply(revised, frame=frame, contract=contract)
        return gate.apply(decision, frame=frame, contract=contract)

    def _qwen_first_contract_fallback_decision(self, decision, *, user_text: str, chat_generation_kwargs: dict):
        """Fallback nhỏ khi critique đã biết draft yếu nhưng mentor/rerun chết.

        Không dùng để làm văn hay. Chỉ dùng để tránh fail-open: câu q<ngưỡng không
        được phát nguyên trạng như bản cũ. Nếu không có contract active thì trả
        một repair line rất ngắn, ít tệ hơn việc để câu lỗi tự do đi du lịch.
        """
        try:
            from actions.contracts import VALID_SYSTEM_ACTION_LIST
            from runtime.turn_frame import build_turn_frame
            from runtime.response_contract import build_response_contract

            previous = ""
            reply_context = chat_generation_kwargs.get("reply_context")
            previous_turn = getattr(reply_context, "previous_public_turn", None) if reply_context is not None else None
            if previous_turn is not None:
                previous = str(getattr(previous_turn, "text", "") or "")
            if not previous:
                previous = str(getattr(self, "last_chat_answer", "") or "")
            frame = getattr(self, "current_elegant_turn_frame", None)
            if frame is None or str(getattr(frame, "user_text", "") or "") != str(user_text or ""):
                frame = build_turn_frame(
                    user_text=user_text,
                    previous_assistant_text=previous,
                    previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
                )
            contract = build_response_contract(frame, capability_action_ids=VALID_SYSTEM_ACTION_LIST)
            fallback = str(contract.fallback_text or "").strip()
        except Exception:
            fallback = ""
        if not fallback:
            fallback = "Câu vừa rồi của tôi lệch nhịp. Tôi rút lại và trả lời gọn hơn: bạn nói tiếp phần chính đi."
        try:
            from dataclasses import replace
            revised = replace(decision)
        except Exception:
            revised = decision
        revised.text = fallback
        revised.should_speak = True
        revised.system_action = ""
        revised.action_input = ""
        revised.intent = revised.intent or "conversation_repair"
        revised.action = "none"
        revised.parse_mode = "qwen_first_low_quality_fallback"
        trace = str(getattr(revised, "debug_trace", "") or "").strip()
        revised.debug_trace = self._sc_join(trace, "qwen_first_low_quality_no_fail_open")
        try:
            revised.confidence = min(float(getattr(revised, "confidence", 0.55) or 0.55), 0.55)
        except Exception:
            revised.confidence = 0.55
        return revised

    def _qwen_first_constrained_rerun(self, decision, *, user_text: str, critique, chat_generation_kwargs: dict, ti_report, notes: str = ""):
        """Rerun bắt buộc bằng Qwen khi draft yếu, kể cả mentor chết.

        Đây là khác biệt quan trọng: mentor chỉ là ý kiến. Acceptance/quality mới là
        chốt cửa. Nếu Qwen viết câu dở và mentor không online, ta vẫn ép Qwen tự sửa
        bằng violation report thay vì mở cửa cho câu dở đi ra loa.
        """
        policy = SemanticAuthorityPolicy.from_runtime()
        if not policy.bounded_refine_enabled:
            return None
        kwargs = dict(chat_generation_kwargs)
        kwargs.pop("use_escalation_client", None)
        kwargs["reasoning_effort"] = policy.primary_reasoning_effort
        draft = str(getattr(decision, "text", "") or "").strip()
        violation = (
            f"LOW_QUALITY_DRAFT: quality={getattr(critique, 'quality', 0.0):.2f}; "
            f"reason={str(getattr(critique, 'reason', '') or '')[:220]}\n"
            f"Rejected draft:\n{draft[:700]}\n\n"
            "Rewrite the answer to the original user turn. Satisfy RESPONSE_CONTRACT/TURN_FRAME if present. "
            "Do not mention critique, mentor, rerun, policy, or internal labels. Keep ERIS voice direct."
        )
        if notes:
            violation += "\n\nPrivate advisory notes:\n" + str(notes).strip()[:1200]
        kwargs["ti_context"] = (str(kwargs.get("ti_context", "") or "") + "\n\n" + violation).strip()
        try:
            raw = self.llm_service.generate_chat_reply(**kwargs, use_escalation_client=False)
            revised = self.parser.parse(raw, user_hint=user_text)
            revised = self.ti_governor.enforce_decision(
                revised,
                ti_report,
                user_hint=user_text,
                vision_grounded=bool(getattr(self, "vision_facts", None)),
            )
            revised.debug_trace = self._sc_join(getattr(revised, "debug_trace", ""), "qwen_constrained_rerun")
            return revised
        except Exception as exc:
            try:
                self.logger.warning("[qwen-first support] constrained rerun failed: %s", exc)
            except Exception:
                pass
            return None

    def _qwen_first_support_cycle(
        self,
        decision,
        *,
        user_text: str,
        snapshot,
        chat_generation_kwargs: dict,
        ti_report,
    ):
        """Qwen drafts first; tools and Gemini only support that draft.

        Flow:
        1. Qwen may select a real ``system_action``. Execute it and let Qwen
           synthesize the tool result.
        2. If Qwen explicitly asks for support or emits a low-confidence weak
           draft, Gemini returns private notes only.
        3. Qwen receives those notes and writes the final ERIS answer.

        Gemini never becomes the public speaker in this mode.
        """

        policy = SemanticAuthorityPolicy.from_env()
        if getattr(decision, "system_action", ""):
            return self._run_tool_continuation(
                decision,
                channel="chat",
                snapshot=snapshot,
                regenerate=lambda tool_summary: self._regenerate_chat_after_tool_primary(
                    chat_generation_kwargs,
                    tool_summary,
                    user_text=user_text,
                    ti_report=ti_report,
                ),
            )

        gate_resolved = self._qwen_first_resolve_gate_before_support(
            decision,
            user_text=user_text,
            chat_generation_kwargs=chat_generation_kwargs,
            ti_report=ti_report,
        )
        if gate_resolved is not None:
            return gate_resolved

        if not self._self_critique_enabled():
            return decision

        try:
            critique = self._critique_decision(
                decision,
                channel="chat",
                user_text=user_text,
                snapshot=snapshot,
            )
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[qwen-first support] critique failed: %s", exc)
            return decision

        self._sc_trace(decision, critique, channel="chat")
        wants_support = policy.requests_mentor_support(decision) or critique.mentor_wanted
        weak_draft = critique.quality < self._escalation_threshold()
        if not (wants_support or weak_draft):
            return decision

        notes = self._request_mentor_support_notes(
            decision,
            user_text=user_text,
            critique=critique,
            context=str(chat_generation_kwargs.get("conversation_context", "") or ""),
        )
        if not notes and weak_draft and not policy.low_quality_fail_open:
            revised = self._qwen_first_constrained_rerun(
                decision,
                user_text=user_text,
                critique=critique,
                chat_generation_kwargs=chat_generation_kwargs,
                ti_report=ti_report,
                notes="",
            )
            return revised or self._qwen_first_contract_fallback_decision(
                decision, user_text=user_text, chat_generation_kwargs=chat_generation_kwargs
            )
        if not notes:
            return decision

        kwargs = dict(chat_generation_kwargs)
        kwargs.pop("use_escalation_client", None)
        kwargs["reasoning_effort"] = policy.primary_reasoning_effort
        kwargs["ti_context"] = (
            str(kwargs.get("ti_context", "") or "")
            + "\n\nMENTOR SUPPORT NOTES (private, advisory, not authoritative):\n"
            + notes
            + "\nQwen remains the semantic and stylistic authority. Re-answer the original user request "
              "using only useful suggestions. Do not mention the mentor, support pass, or these notes."
        )
        try:
            raw = self.llm_service.generate_chat_reply(
                **kwargs,
                use_escalation_client=False,
            )
            revised = self.parser.parse(raw, user_hint=user_text)
            revised = self.ti_governor.enforce_decision(
                revised,
                ti_report,
                user_hint=user_text,
                vision_grounded=bool(getattr(self, "vision_facts", None)),
            )
            revised.debug_trace = self._sc_join(
                getattr(revised, "debug_trace", ""),
                "qwen_after_mentor_support",
            )
        except Exception as exc:
            self.logger.warning("[qwen-first support] Qwen synthesis failed: %s", exc)
            if weak_draft and not policy.low_quality_fail_open:
                rerun = self._qwen_first_constrained_rerun(
                    decision,
                    user_text=user_text,
                    critique=critique,
                    chat_generation_kwargs=chat_generation_kwargs,
                    ti_report=ti_report,
                    notes=notes,
                )
                return rerun or self._qwen_first_contract_fallback_decision(
                    decision, user_text=user_text, chat_generation_kwargs=chat_generation_kwargs
                )
            return decision

        if weak_draft and not policy.low_quality_fail_open:
            # Mentor notes đã dùng để viết lại, nhưng vẫn không cho phép trả về
            # nguyên draft cũ nếu revision rỗng/bị parse thành câu trống.
            if not str(getattr(revised, "text", "") or "").strip():
                return self._qwen_first_contract_fallback_decision(
                    decision, user_text=user_text, chat_generation_kwargs=chat_generation_kwargs
                )

        if getattr(revised, "system_action", ""):
            revised = self._run_tool_continuation(
                revised,
                channel="chat",
                snapshot=snapshot,
                regenerate=lambda tool_summary: self._regenerate_chat_after_tool_primary(
                    kwargs,
                    tool_summary,
                    user_text=user_text,
                    ti_report=ti_report,
                ),
            )
        return revised

    def _request_mentor_support_notes(
        self,
        decision,
        *,
        user_text: str,
        critique: CritiqueResult,
        context: str = "",
    ) -> str:
        """Ask Gemini/strong client for ideas, never for the public answer."""

        svc = getattr(self, "llm_service", None)
        resolver = getattr(svc, "_resolve_escalation_client", None) if svc is not None else None
        if not callable(resolver):
            return ""
        try:
            client = resolver()
        except Exception:
            client = None
        if client is None:
            return ""

        draft = str(getattr(decision, "text", "") or "").strip()
        if not draft:
            return ""
        system_prompt = (
            "You are a private mentor for ERIS's Qwen model. Do not answer the user and do not imitate ERIS. "
            "Analyze whether the draft understood the full conversational intent. Provide compact ideas, missing "
            "angles, factual cautions, or useful associations. Never introduce unsupported facts. Return only JSON: "
            '{"useful":true,"problems":["..."],"suggestions":["..."],"cautions":["..."]}.'
        )
        user_prompt = (
            f"User request:\n{str(user_text or '').strip()[:700]}\n\n"
            f"Qwen draft:\n{draft[:900]}\n\n"
            f"Local quality signal: {critique.quality:.2f}; reason={critique.reason[:240]}\n\n"
            f"Conversation context (may be partial):\n{str(context or '')[:1400]}"
        )
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=300,
                response_format={"type": "json_object"},
                grammar=None,
            )
            raw = svc._extract_content(response) if hasattr(svc, "_extract_content") else str(response)
            extracted = svc._extract_first_json_object(raw) if hasattr(svc, "_extract_first_json_object") else ""
            payload = json.loads(extracted or re.search(r"\{.*\}", raw, flags=re.DOTALL).group(0))
            if not bool(payload.get("useful", True)):
                return ""
            lines: list[str] = []
            for key in ("problems", "suggestions", "cautions"):
                values = payload.get(key, ())
                if isinstance(values, str):
                    values = (values,)
                for item in tuple(values or ())[:5]:
                    clean = re.sub(r"\s+", " ", str(item or "")).strip()
                    if clean:
                        lines.append(f"- {clean[:260]}")
            return "\n".join(lines[:10])
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[qwen-first mentor] failed: %s", exc)
            return ""

    def _regenerate_chat_after_tool_primary(
        self,
        generation_kwargs: dict,
        tool_summary: str,
        *,
        user_text: str,
        ti_report,
    ):
        """Feed tool evidence back to Qwen, not to Gemini."""

        policy = SemanticAuthorityPolicy.from_env()
        kwargs = dict(generation_kwargs)
        kwargs.pop("use_escalation_client", None)
        kwargs["reasoning_effort"] = policy.primary_reasoning_effort
        report = getattr(self, "last_grounding_context", None)
        refreshed_grounding = str(getattr(report, "prompt_context", "") or "").strip()
        kwargs["grounding_context"] = (
            refreshed_grounding
            or str(kwargs.get("grounding_context", "") or "")
        ) + (
            "\nTOOL RESULT (primary evidence; synthesize it naturally and do not call another tool unless essential):\n"
            + tool_summary
        )
        kwargs["ti_context"] = (
            str(kwargs.get("ti_context", "") or "")
            + "\nA tool result is now available. Answer the original request directly in ERIS voice."
        )
        try:
            raw = self.llm_service.generate_chat_reply(
                **kwargs,
                use_escalation_client=False,
            )
            decision = self.parser.parse(raw, user_hint=user_text)
            return self.ti_governor.enforce_decision(
                decision,
                ti_report,
                user_hint=user_text,
                vision_grounded=bool(getattr(self, "vision_facts", None)),
            )
        except Exception as exc:
            self.logger.warning("[qwen-first tool continuation] failed: %s", exc)
            return None

    def _regenerate_chat_after_tool(self, escalation_kwargs: dict, tool_summary: str, *, user_text: str, ti_report):
        kwargs = dict(escalation_kwargs)
        kwargs.pop("use_escalation_client", None)
        report = getattr(self, "last_grounding_context", None)
        refreshed_grounding = str(getattr(report, "prompt_context", "") or "").strip()
        base_grounding = refreshed_grounding or (kwargs.get("grounding_context", "") or "")
        kwargs["grounding_context"] = (
            base_grounding
            + "\nTOOL_RESULT (đã tra cứu giúp bạn; đây là PRIMARY EVIDENCE của câu trả lời. "
            "Hãy diễn đạt tự nhiên thành câu nói của em, KHÔNG đặt system_action nữa, "
            "và không để bối cảnh màn hình phụ phủ định kết quả này):\n"
            f"{tool_summary}"
        )
        kwargs["ti_context"] = (
            (kwargs.get("ti_context", "") or "")
            + "\nĐã có kết quả công cụ ở trên; nói lại cho bạn bằng giọng của em, không gọi thêm action."
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
        if critique.drop:
            decision.text = ""
            decision.should_speak = False
            decision.debug_trace = self._sc_join(getattr(decision, "debug_trace", ""), "sentence_evaluator_drop")
            return decision
        if critique.rewrite_text:
            decision.text = critique.rewrite_text.strip()
            decision.debug_trace = self._sc_join(getattr(decision, "debug_trace", ""), "sentence_mentor_rewrite")
            return decision
        if not self._should_escalate(critique, channel=channel):
            return decision

        self.logger.info(
            "[escalation] %s draft escalated | quality=%.2f reason=%s",
            channel,
            critique.quality,
            critique.reason,
        )
        esc_kwargs = dict(directive_kwargs)
        esc_kwargs.pop("use_escalation_client", None)
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
        kwargs.pop("use_escalation_client", None)
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
