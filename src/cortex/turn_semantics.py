from __future__ import annotations

"""
cortex/turn_semantics.py
========================

Tầng hiểu nghĩa một turn chat ở mức rẻ nhưng có ngữ cảnh.

Mục tiêu chính:
- Không để repeat guard chặn bừa mọi câu lặp.
- Phân biệt user đang spam với user đang hỏi lại, sửa frame, test identity,
  hoặc nhắc lại vì assistant vừa trả lời sai.
- Tạo một báo cáo mềm cho ChatCycle/LLM đọc, thay vì nhét thêm if/else kiểu
  "nếu có chữ bot thì bypass". Keyword vẫn có thể nằm ở các classifier thấp,
  nhưng quyết định cuối phải là arbitration nhiều tín hiệu.

File này không gọi LLM, không đọc memory, không ghi state. Nó chỉ nhận những
report đã có: affect_signal, conversation_report, relationship_report,
grounding_report, last assistant text, repeat_count... rồi quyết định repeat
có nên bị chặn không.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal


RepeatIntent = Literal[
    "none",
    "low_value_repeat",
    "reask_same_question",
    "repair_reframe",
    "relational_probe",
    "identity_boundary_probe",
    "live_evidence_refresh",
]

RepeatAction = Literal[
    "pass_to_llm",
    "guard_repeat",
    "repair_ack_then_answer",
    "answer_again_with_lower_certainty",
]


@dataclass(frozen=True, slots=True)
class TurnSemanticsReport:
    """Báo cáo nghĩa của user turn hiện tại.

    Các score đều là áp lực mềm, không phải nhãn tuyệt đối.
    ChatCycle chỉ nên dùng `action` và `should_guard_repeat` để quyết định
    có chặn repeat hay không. Prompt có thể dùng `prompt_context` để LLM hiểu
    vì sao một câu giống hệt vẫn không nhất thiết là spam.
    """

    repeated: bool = False
    repeat_count: int = 1
    intent: RepeatIntent = "none"
    action: RepeatAction = "pass_to_llm"
    confidence: float = 0.0

    literal_repeat_score: float = 0.0
    semantic_similarity: float = 0.0
    question_pressure: float = 0.0
    correction_pressure: float = 0.0
    relational_pressure: float = 0.0
    identity_pressure: float = 0.0
    live_evidence_pressure: float = 0.0
    prior_failure_pressure: float = 0.0
    new_information_pressure: float = 0.0
    spam_pressure: float = 0.0

    reasons: tuple[str, ...] = ()
    prompt_context: str = ""

    @property
    def should_guard_repeat(self) -> bool:
        return self.action == "guard_repeat"

    @property
    def should_bypass_repeat_guard(self) -> bool:
        return self.action != "guard_repeat"


class TurnSemanticsEngine:
    """Arbitration nhẹ cho meaning của một user turn.

    Đây là tầng nằm giữa exact repeat counter và LLM. Nó cố tình dùng nhiều
    nguồn tín hiệu thay vì helper phrase. Nếu `AffectSemanticClassifier` hiểu
    objectification/correction tốt hơn sau này, file này tự hưởng lợi mà không
    phải thêm marker mới vào ChatCycle. Một chuyện hiếm hoi trong phần mềm:
    sửa một chỗ mà không làm repo khóc.
    """

    def analyze_repeat(
        self,
        *,
        user_text: str,
        repeat_count: int,
        last_user_text: str = "",
        last_assistant_text: str = "",
        affect_signal: Any = None,
        conversation_report: Any = None,
        relationship_report: Any = None,
        grounding_report: Any = None,
    ) -> TurnSemanticsReport:
        repeated = repeat_count >= 2
        normalized = self.normalize(user_text)
        previous = self.normalize(last_user_text)

        literal_repeat_score = 1.0 if repeated else 0.0
        semantic_similarity = self._jaccard_similarity(normalized, previous) if previous else literal_repeat_score

        question_pressure = self._question_pressure(user_text, normalized, affect_signal)
        correction_pressure = self._correction_pressure(conversation_report, affect_signal, normalized)
        relational_pressure = self._relational_pressure(affect_signal, relationship_report)
        identity_pressure = self._identity_pressure(affect_signal, relationship_report)
        live_evidence_pressure = self._live_evidence_pressure(grounding_report)
        prior_failure_pressure = self._prior_failure_pressure(last_assistant_text, conversation_report)
        new_information_pressure = self._new_information_pressure(
            live_evidence_pressure=live_evidence_pressure,
            correction_pressure=correction_pressure,
            prior_failure_pressure=prior_failure_pressure,
            question_pressure=question_pressure,
        )

        reasons: list[str] = []
        if not repeated:
            report = TurnSemanticsReport(
                repeated=False,
                repeat_count=max(1, repeat_count),
                intent="none",
                action="pass_to_llm",
                confidence=0.75,
                literal_repeat_score=literal_repeat_score,
                semantic_similarity=semantic_similarity,
                question_pressure=question_pressure,
                correction_pressure=correction_pressure,
                relational_pressure=relational_pressure,
                identity_pressure=identity_pressure,
                live_evidence_pressure=live_evidence_pressure,
                prior_failure_pressure=prior_failure_pressure,
                new_information_pressure=new_information_pressure,
                spam_pressure=0.0,
                reasons=("not_repeated",),
            )
            return self._with_prompt_context(report)

        if live_evidence_pressure >= 0.55:
            intent: RepeatIntent = "live_evidence_refresh"
            action: RepeatAction = "pass_to_llm"
            confidence = live_evidence_pressure
            reasons.append("repeat_but_current_evidence_request")
        elif correction_pressure >= 0.50 or prior_failure_pressure >= 0.58:
            intent = "repair_reframe"
            action = "repair_ack_then_answer"
            confidence = max(correction_pressure, prior_failure_pressure)
            reasons.append("repeat_as_repair_or_failed_frame")
        elif identity_pressure >= 0.50:
            intent = "identity_boundary_probe"
            action = "pass_to_llm"
            confidence = identity_pressure
            reasons.append("repeat_as_identity_boundary_probe")
        elif relational_pressure >= 0.50:
            intent = "relational_probe"
            action = "pass_to_llm"
            confidence = relational_pressure
            reasons.append("repeat_as_relational_probe")
        elif question_pressure >= 0.52 or new_information_pressure >= 0.50:
            intent = "reask_same_question"
            action = "answer_again_with_lower_certainty"
            confidence = max(question_pressure, new_information_pressure)
            reasons.append("repeat_as_reask")
        else:
            spam_pressure = self._spam_pressure(
                repeat_count=repeat_count,
                literal_repeat_score=literal_repeat_score,
                semantic_similarity=semantic_similarity,
                question_pressure=question_pressure,
                correction_pressure=correction_pressure,
                relational_pressure=relational_pressure,
                identity_pressure=identity_pressure,
                live_evidence_pressure=live_evidence_pressure,
                prior_failure_pressure=prior_failure_pressure,
            )
            if spam_pressure >= 0.62:
                intent = "low_value_repeat"
                action = "guard_repeat"
                confidence = spam_pressure
                reasons.append("repeat_low_value_no_new_signal")
            else:
                intent = "reask_same_question"
                action = "answer_again_with_lower_certainty"
                confidence = max(0.45, 1.0 - spam_pressure)
                reasons.append("repeat_ambiguous_preserve_llm_path")

        spam_pressure = self._spam_pressure(
            repeat_count=repeat_count,
            literal_repeat_score=literal_repeat_score,
            semantic_similarity=semantic_similarity,
            question_pressure=question_pressure,
            correction_pressure=correction_pressure,
            relational_pressure=relational_pressure,
            identity_pressure=identity_pressure,
            live_evidence_pressure=live_evidence_pressure,
            prior_failure_pressure=prior_failure_pressure,
        )

        report = TurnSemanticsReport(
            repeated=True,
            repeat_count=repeat_count,
            intent=intent,
            action=action,
            confidence=self._clamp01(confidence),
            literal_repeat_score=literal_repeat_score,
            semantic_similarity=semantic_similarity,
            question_pressure=question_pressure,
            correction_pressure=correction_pressure,
            relational_pressure=relational_pressure,
            identity_pressure=identity_pressure,
            live_evidence_pressure=live_evidence_pressure,
            prior_failure_pressure=prior_failure_pressure,
            new_information_pressure=new_information_pressure,
            spam_pressure=spam_pressure,
            reasons=tuple(dict.fromkeys(reasons)),
        )
        return self._with_prompt_context(report)

    def build_repeat_guard_text(self, report: TurnSemanticsReport) -> str:
        """Text guard chỉ dùng khi arbitration thật sự coi là repeat rỗng."""

        if report.repeat_count <= 2:
            return (
                "Tôi nhận câu đó rồi. Nếu Ngài lặp để nhấn mạnh, tôi sẽ giữ nó như tín hiệu; "
                "nhưng cùng một câu chưa thêm dữ kiện mới."
            )
        return (
            "Câu này đang lặp mà không thêm tín hiệu mới. Đổi góc hỏi hoặc chỉ rõ phần tôi xử lý sai."
        )

    # ------------------------------------------------------------------
    # Feature scoring
    # ------------------------------------------------------------------

    def _question_pressure(self, raw: str, normalized: str, affect_signal: Any) -> float:
        pressure = 0.0
        if "?" in (raw or ""):
            pressure = max(pressure, 0.65)
        if self._looks_like_question(normalized):
            pressure = max(pressure, 0.56)
        pressure = max(pressure, self._safe_float(getattr(affect_signal, "answer_need", 0.0)) * 0.78)
        pressure = max(pressure, self._safe_float(getattr(affect_signal, "ambiguity", 0.0)) * 0.42)
        return self._clamp01(pressure)

    def _correction_pressure(self, conversation_report: Any, affect_signal: Any, normalized: str) -> float:
        pressure = 0.0
        if bool(getattr(conversation_report, "correction_detected", False)):
            pressure = max(pressure, 0.78)
        state = getattr(conversation_report, "state", None)
        if str(getattr(state, "mode", "") or "") in {"repair", "relational_repair"}:
            pressure = max(pressure, 0.68)
        flags = set(getattr(state, "adaptation_flags", ()) or ())
        if flags & {"repair_first", "avoid_failed_frame", "lower_inference_confidence"}:
            pressure = max(pressure, 0.64)
        pressure = max(pressure, self._safe_float(getattr(affect_signal, "correction", 0.0)))
        if self._contains_soft_correction_shape(normalized):
            pressure = max(pressure, 0.58)
        return self._clamp01(pressure)

    def _relational_pressure(self, affect_signal: Any, relationship_report: Any) -> float:
        pressure = 0.0
        for field in ("attachment", "intimacy", "relational_pressure", "perceived_rejection", "attachment_bid"):
            pressure = max(pressure, self._safe_float(getattr(affect_signal, field, 0.0)))
        state = getattr(relationship_report, "state", None)
        pressure = max(pressure, self._safe_float(getattr(state, "rupture", 0.0)) * 0.65)
        pressure = max(pressure, self._safe_float(getattr(state, "repair", 0.0)) * 0.55)
        return self._clamp01(pressure)

    def _identity_pressure(self, affect_signal: Any, relationship_report: Any) -> float:
        pressure = self._safe_float(getattr(affect_signal, "objectification", 0.0))
        state = getattr(relationship_report, "state", None)
        pressure = max(pressure, self._safe_float(getattr(state, "dignity_defense", 0.0)) * 0.85)
        notes = " ".join(getattr(relationship_report, "notes", ()) or ()).lower()
        if "objectification" in notes or "boundary" in notes:
            pressure = max(pressure, 0.62)
        return self._clamp01(pressure)

    def _live_evidence_pressure(self, grounding_report: Any) -> float:
        if grounding_report is None:
            return 0.0
        missing = set(getattr(grounding_report, "missing_evidence", ()) or ())
        if bool(getattr(grounding_report, "refers_to_current_screen", False)):
            return 0.74 if "screen_evidence" not in missing else 0.34
        if bool(getattr(grounding_report, "pasted_code_detected", False)):
            return 0.66
        source = str(getattr(grounding_report, "primary_source", "") or "")
        if source in {"current_screen", "live_vision", "pasted_code", "uploaded_file"} and not missing:
            return 0.62
        return 0.0

    def _prior_failure_pressure(self, last_assistant_text: str, conversation_report: Any) -> float:
        text = self.normalize(last_assistant_text)
        pressure = 0.0
        failure_markers = (
            "toi chua hieu",
            "chua du du kien",
            "chua co bang chung",
            "can them evidence",
            "co the noi ro hon",
            "xin loi toi dang co van de duong truyen",
            "loi duong truyen",
            "khong duoc gia vo",
        )
        if any(marker in text for marker in failure_markers):
            pressure = max(pressure, 0.64)
        state = getattr(conversation_report, "state", None)
        failure = getattr(state, "last_failure", None)
        failure_type = str(getattr(failure, "type", "") or "")
        if failure_type and failure_type != "none":
            pressure = max(pressure, 0.58)
        return self._clamp01(pressure)

    def _new_information_pressure(
        self,
        *,
        live_evidence_pressure: float,
        correction_pressure: float,
        prior_failure_pressure: float,
        question_pressure: float,
    ) -> float:
        return self._clamp01(max(
            live_evidence_pressure,
            correction_pressure * 0.86,
            prior_failure_pressure * 0.78,
            question_pressure * 0.55,
        ))

    def _spam_pressure(
        self,
        *,
        repeat_count: int,
        literal_repeat_score: float,
        semantic_similarity: float,
        question_pressure: float,
        correction_pressure: float,
        relational_pressure: float,
        identity_pressure: float,
        live_evidence_pressure: float,
        prior_failure_pressure: float,
    ) -> float:
        base = 0.28 + min(0.34, max(0, repeat_count - 1) * 0.12)
        base += literal_repeat_score * 0.22
        base += semantic_similarity * 0.18
        base -= question_pressure * 0.20
        base -= correction_pressure * 0.28
        base -= relational_pressure * 0.24
        base -= identity_pressure * 0.30
        base -= live_evidence_pressure * 0.34
        base -= prior_failure_pressure * 0.26
        return self._clamp01(base)

    # ------------------------------------------------------------------
    # Prompt/debug helpers
    # ------------------------------------------------------------------

    def _with_prompt_context(self, report: TurnSemanticsReport) -> TurnSemanticsReport:
        lines = [
            "turn_semantics: guidance only; do not announce these labels.",
            (
                "repeat_arbitration: "
                f"repeated={int(report.repeated)}; count={report.repeat_count}; "
                f"intent={report.intent}; action={report.action}; confidence={report.confidence:.2f}."
            ),
            (
                "pressures: "
                f"question={report.question_pressure:.2f}; correction={report.correction_pressure:.2f}; "
                f"relational={report.relational_pressure:.2f}; identity={report.identity_pressure:.2f}; "
                f"live_evidence={report.live_evidence_pressure:.2f}; prior_failure={report.prior_failure_pressure:.2f}; "
                f"spam={report.spam_pressure:.2f}."
            ),
        ]
        if report.reasons:
            lines.append("reasons: " + ", ".join(report.reasons[:6]) + ".")
        if report.repeated and report.action != "guard_repeat":
            lines.append(
                "repeat_rule: repeated wording is not automatically spam; preserve current intent and answer/repair the live turn."
            )
        elif report.action == "guard_repeat":
            lines.append(
                "repeat_rule: low-value exact repetition; acknowledge briefly and do not invent new evidence."
            )
        return TurnSemanticsReport(
            repeated=report.repeated,
            repeat_count=report.repeat_count,
            intent=report.intent,
            action=report.action,
            confidence=report.confidence,
            literal_repeat_score=report.literal_repeat_score,
            semantic_similarity=report.semantic_similarity,
            question_pressure=report.question_pressure,
            correction_pressure=report.correction_pressure,
            relational_pressure=report.relational_pressure,
            identity_pressure=report.identity_pressure,
            live_evidence_pressure=report.live_evidence_pressure,
            prior_failure_pressure=report.prior_failure_pressure,
            new_information_pressure=report.new_information_pressure,
            spam_pressure=report.spam_pressure,
            reasons=report.reasons,
            prompt_context="\n".join(lines),
        )

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def normalize(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d").replace("Đ", "d")
        lowered = re.sub(r"[^a-z0-9_#\s]+", " ", lowered)
        return " ".join(lowered.split())

    def _looks_like_question(self, normalized: str) -> bool:
        if not normalized:
            return False
        question_words = {"ai", "gi", "sao", "nao", "dau", "chua", "khong", "ha", "a"}
        tokens = set(normalized.split())
        if tokens & question_words:
            return True
        question_phrases = (
            "co phai",
            "tai sao",
            "vi sao",
            "nghi toi dang",
            "dang xem gi",
            "dang lam gi",
            "y la gi",
            "la sao",
            "sao lai",
        )
        return any(phrase in normalized for phrase in question_phrases)

    def _contains_soft_correction_shape(self, normalized: str) -> bool:
        if not normalized:
            return False
        correction_shapes = (
            "khong phai",
            "sai roi",
            "chua dung",
            "lech roi",
            "hieu sai",
            "y toi khac",
            "y toi la",
            "khong dung y",
            "nham roi",
        )
        return any(shape in normalized for shape in correction_shapes)

    def _jaccard_similarity(self, left: str, right: str) -> float:
        left_tokens = {token for token in left.split() if token}
        right_tokens = {token for token in right.split() if token}
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return default
        if numeric != numeric:
            return default
        return numeric

    def _clamp01(self, value: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))
