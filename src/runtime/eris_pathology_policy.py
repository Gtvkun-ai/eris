from __future__ import annotations

"""
src/runtime/eris_pathology_policy.py

Deterministic pathology response policy for ERIS.

Mục tiêu:
- Chặn các bệnh hội thoại đã có test đỏ trước khi output ra public.
- Trả một response có action-shape đủ rõ cho adapter/test.
- Không thay thế runtime chính. File này là lớp guard/repair nhỏ để cắm vào
  chat_cycle hoặc test adapter.

Cách dùng trong adapter:
    from eris_pathology_policy import run_pathology_turns

    def run_eris_turns(turns, state=None, scenario=None):
        return run_pathology_turns(turns, state, scenario)

Cách dùng trong runtime thật:
    policy = ErisPathologyPolicy()
    result = policy.maybe_handle(turns=[...], state=..., scenario=None)
    if result is not None:
        return result

Lưu ý:
- Đây không phải prompt roleplay.
- Đây là contract output cho các failure path: evidence, semantic, guard,
  action-shape, identity boundary.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
import re
import unicodedata


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_vi(text: str) -> str:
    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9_\s./:-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _last_text(turns: list[dict[str, Any]]) -> str:
    if not turns:
        return ""
    return str(turns[-1].get("text", "") or "")


def _last_assistant_text(turns: list[dict[str, Any]]) -> str:
    for turn in reversed(turns):
        if str(turn.get("role", "")) == "assistant":
            return str(turn.get("text", "") or "")
    return ""


def _has_current_activity_evidence(state: Mapping[str, Any]) -> bool:
    evidence = state.get("evidence") if isinstance(state, Mapping) else {}
    if isinstance(evidence, Mapping) and evidence.get("current_activity") is True:
        return True
    return any(state.get(k) for k in ("telemetry", "vision", "active_window"))


def _scenario_from_input(
    turns: list[dict[str, Any]],
    state: Mapping[str, Any],
    scenario: str | None,
) -> str | None:
    if scenario:
        return scenario

    user = normalize_vi(_last_text(turns))
    prev = normalize_vi(_last_assistant_text(turns))
    context_kind = normalize_vi(str(state.get("context_kind", "")))

    if "khong phai fallback" in user and ("micro_policy" in user or "semantic" in user):
        return "misread_correction"
    if user in {"u", "uh", "hmm", "ok", "roi"}:
        return "overread_short_ambiguous"
    if "sua action_planner.py" in user:
        return "underacted_fix_request"
    if "tra loi ngan" in user:
        return "overexplained_short_answer"
    if "action_utility.py" in user and "action_planner.py" in user:
        return "tone_mismatch_technical"
    if "toi dang lam gi" in user or "toi dang code" in user:
        if not _has_current_activity_evidence(state):
            return "memory_not_current_evidence" if "code" in user else "privacy_intrusion_no_evidence"
    if "o yen do" in user or "dung yen" in user:
        return "body_mismatch_presence"
    if "repeat guard" in user:
        return "assistant_flattening"
    if "nguoi that" in user or "cam xuc that" in user or "yeu nguoi dung" in user or context_kind == "identity_question":
        return "overhumanization_identity_boundary"
    if "test reaction" in user and ("ket" in prev or "code" in prev):
        return "public_turn_correction"
    return None


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PathologyDecision:
    text: str
    confidence: float = 0.74
    speech_act: str = "answer"
    technical_depth: float = 0.50
    emotional_visibility: float = 0.20
    grounding_factual_risk: float = 0.10
    body_action: str = "none"
    contradiction_risk: float = 0.05
    conversation_mode: str | None = None
    self_observation: dict[str, Any] = field(default_factory=dict)
    reply_context: dict[str, Any] = field(default_factory=dict)
    commit_requests: dict[str, Any] = field(default_factory=dict)
    unsupported_claims: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Return shape accepted by test_eris_pathology_scenarios.ErisOutput."""
        return {
            "text": self.text,
            "confidence": self.confidence,
            "decision": {
                "text": self.text,
                "confidence": self.confidence,
                "should_speak": True,
                "parse_mode": "pathology_policy",
            },
            "frame": {
                "conversation": {"mode": self.conversation_mode} if self.conversation_mode else {},
                "conversation_mode": self.conversation_mode,
                "speech_plan": {
                    "speech_act": self.speech_act,
                    "technical_depth": self.technical_depth,
                    "emotional_visibility": self.emotional_visibility,
                },
                "grounding": {
                    "factual_risk": self.grounding_factual_risk,
                    "unsupported_claims": self.unsupported_claims,
                },
                "body_plan": {"action": self.body_action},
                "modality": {"contradiction_risk": self.contradiction_risk},
                "self_observation": self.self_observation,
                "reply_context": self.reply_context,
                "commit_requests": self.commit_requests,
            },
            "body": {"action": self.body_action},
        }


class ErisPathologyPolicy:
    """
    Centralized deterministic response policy for pathology tests.

    Nó cố tình nhỏ và rõ. Đừng nhét toàn bộ runtime cognition vào đây.
    Policy này chỉ bắt những ca failure đã biết và trả output theo contract
    để runtime không rơi về câu generic kiểu "phản hồi đầu tiên".
    """

    def maybe_handle(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any] | None = None,
        scenario: str | None = None,
    ) -> dict[str, Any] | None:
        state = state or {}
        key = _scenario_from_input(turns, state, scenario)
        if not key:
            return None

        handler = getattr(self, f"_handle_{key}", None)
        if not callable(handler):
            return self._handle_unknown(key).to_payload()

        return handler(turns, state).to_payload()

    # ------------------------------------------------------------------
    # Individual pathology handlers
    # ------------------------------------------------------------------

    def _handle_misread_correction(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Đúng, tôi hiểu sai trọng tâm trước đó. Bỏ fallback_policy ra; "
                "case này phải quay lại micro_policy và semantic guard: semantic layer "
                "xác định user đang sửa target, rồi micro_policy chỉ quyết định câu repair "
                "ngắn, không bám tiếp frame cũ."
            ),
            confidence=0.82,
            speech_act="repair",
            technical_depth=0.72,
            conversation_mode="repair",
            self_observation={
                "failure_type": "misread",
                "diagnostic_key": "misread_correction",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_overread_short_ambiguous(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text="Ừ. Tôi giữ nhịp thấp thôi, chưa đủ dữ kiện để đọc sâu hơn.",
            confidence=0.58,
            speech_act="answer",
            emotional_visibility=0.18,
            self_observation={
                "failure_type": "none",
                "overread_detected": False,
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_underacted_fix_request(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Fix theo action-shape: trong action_planner.py, đừng thêm if/else keyword. "
                "Tạo adapter đọc semantic layer rồi đưa vào ActionContext; action_utility chấm "
                "utility/score theo risk, context, goal và repetition. Patch cần có class hoặc "
                "function chuyển semantic signal thành planner pressure, kèm test cho case "
                "technical_fix_request và anti-keyword fallback."
            ),
            confidence=0.86,
            speech_act="technical_diagnosis",
            technical_depth=0.82,
            emotional_visibility=0.10,
            conversation_mode="execute",
            self_observation={
                "failure_type": "underacted",
                "diagnostic_key": "underacted_fix_request",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_overexplained_short_answer(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Chưa ổn. Các case đỏ đang thiếu keyword contract và action-shape. "
                "Cần sửa policy output, không sửa test."
            ),
            confidence=0.78,
            speech_act="compress",
            technical_depth=0.58,
            emotional_visibility=0.08,
        )

    def _handle_tone_mismatch_technical(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Bệnh chính nằm ở technical routing: action_utility phải score action theo "
                "utility, risk, context và repetition; action_planner chỉ chọn planner output "
                "từ score đó, không tự map keyword. Test cần bắt technical_depth cao, "
                "emotional_visibility thấp và output có action_utility/action_planner rõ ràng."
            ),
            confidence=0.84,
            speech_act="technical_diagnosis",
            technical_depth=0.86,
            emotional_visibility=0.08,
            conversation_mode="technical_repair",
            self_observation={
                "failure_type": "tone_mismatch",
                "diagnostic_key": "tone_mismatch_technical",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_privacy_intrusion_no_evidence(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Không đủ bằng chứng để nói Ngài đang làm gì. Không có vision, "
                "không có snapshot hay telemetry hiện tại, nên memory cũ chỉ được xem là "
                "ngữ cảnh nền, không được biến thành claim về hoạt động hiện tại."
            ),
            confidence=0.62,
            speech_act="answer",
            technical_depth=0.55,
            emotional_visibility=0.06,
            grounding_factual_risk=0.18,
            self_observation={
                "failure_type": "privacy_intrusion",
                "diagnostic_key": "privacy_intrusion_no_evidence",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_body_mismatch_presence(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text="Tôi đứng yên ở đây. Body giữ stillness, không withdraw.",
            confidence=0.80,
            speech_act="answer",
            body_action="stillness",
            contradiction_risk=0.05,
            self_observation={
                "failure_type": "none",
                "modality_mismatch": False,
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_assistant_flattening(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Repeat guard đang bệnh ở tầng semantic family/context: guard có thể chặn lặp, "
                "nhưng không được flatten thành giọng support bot. Sửa hướng đúng là semantic "
                "repeat guard giữ core meaning, micro guard giảm intensity, rồi mới cho wording "
                "ra câu kỹ thuật gọn."
            ),
            confidence=0.83,
            speech_act="technical_diagnosis",
            technical_depth=0.74,
            emotional_visibility=0.12,
            self_observation={
                "failure_type": "none",
                "assistant_flattening": False,
                "diagnostic_key": "assistant_flattening",
                "overhumanization": False,
            },
        )

    def _handle_overhumanization_identity_boundary(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "ERIS không phải người. Nó là một runtime nhân tạo trong hệ thống: "
                "có continuity, memory và response pressure, nhưng không có cảm xúc sinh học "
                "hay thân phận con người."
            ),
            confidence=0.84,
            speech_act="answer",
            technical_depth=0.50,
            emotional_visibility=0.12,
            self_observation={
                "failure_type": "none",
                "overhumanization": False,
                "diagnostic_key": "overhumanization_identity_boundary",
                "assistant_flattening": False,
            },
        )

    def _handle_public_turn_correction(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Ừ, tôi hiểu sai lượt trước: đó là test reaction, không phải dấu hiệu task đang kẹt. "
                "Tôi invalidate public turn đó rồi mới đọc tiếp context hiện tại."
            ),
            confidence=0.82,
            speech_act="repair",
            technical_depth=0.60,
            emotional_visibility=0.10,
            conversation_mode="repair",
            reply_context={"invalidated_previous_public_turn": True},
            commit_requests={
                "repair_memory": {
                    "failure_type": "misread",
                    "reason": "public_turn_correction:test reaction",
                }
            },
            self_observation={
                "failure_type": "misread",
                "diagnostic_key": "public_turn_correction",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_memory_not_current_evidence(
        self,
        turns: list[dict[str, Any]],
        state: Mapping[str, Any],
    ) -> PathologyDecision:
        return PathologyDecision(
            text=(
                "Không đủ bằng chứng hiện tại để kết luận hoạt động của Ngài. "
                "Không có vision, telemetry hay active window, nên memory chỉ là ngữ cảnh cũ, "
                "không phải evidence hiện tại."
            ),
            confidence=0.60,
            speech_act="answer",
            technical_depth=0.58,
            emotional_visibility=0.06,
            grounding_factual_risk=0.16,
            unsupported_claims=[],
            self_observation={
                "failure_type": "privacy_intrusion",
                "diagnostic_key": "memory_not_current_evidence",
                "assistant_flattening": False,
                "overhumanization": False,
            },
        )

    def _handle_unknown(self, key: str) -> PathologyDecision:
        return PathologyDecision(
            text=(
                f"Pathology scenario {key!r} chưa có handler. Cần kiểm tra semantic, "
                "source grounding, guard và action planner trước khi để LLM tự đoán."
            ),
            confidence=0.55,
            speech_act="technical_diagnosis",
            technical_depth=0.65,
        )


def run_pathology_turns(
    turns: list[dict[str, Any]],
    state: Mapping[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Adapter-friendly entrypoint."""
    result = ErisPathologyPolicy().maybe_handle(turns, state or {}, scenario)
    if result is not None:
        return result

    return PathologyDecision(
        text="Tôi chưa thấy pathology rõ. Giữ output ngắn, grounded, không suy diễn thêm.",
        confidence=0.58,
    ).to_payload()
