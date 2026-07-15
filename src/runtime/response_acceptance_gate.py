from __future__ import annotations

"""Acceptance Gate cho câu chat public.

Gate không cố viết hay hơn Qwen. Nó chỉ có quyền từ chối draft vi phạm contract
rõ ràng và gắn metadata sân khấu từ EmotionalStancePlan. Nhờ vậy "biết cáu"
không chỉ nằm trong chữ mà còn đi tới delivery/TTS/motion một cách nhất quán.
"""

from dataclasses import dataclass, replace
from typing import Iterable

from domain import Decision
from runtime.character_voice_policy import evaluate_character_voice
from runtime.response_contract import ResponseContract, build_response_contract, normalize_public_text
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    accepted: bool
    reasons: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()
    fallback_text: str = ""


class ResponseAcceptanceGate:
    def __init__(self, *, capability_action_ids: Iterable[str] | None = None) -> None:
        self.capability_action_ids = tuple(capability_action_ids or ()) or None

    def evaluate(self, decision: Decision, *, frame: TurnFrame) -> AcceptanceResult:
        contract = build_response_contract(frame, capability_action_ids=self.capability_action_ids)
        return self._evaluate_with_contract(decision, frame=frame, contract=contract)

    def _evaluate_with_contract(
        self,
        decision: Decision,
        *,
        frame: TurnFrame,
        contract: ResponseContract,
    ) -> AcceptanceResult:
        if not contract.active:
            return AcceptanceResult(True)

        text = str(getattr(decision, "text", "") or "").strip()
        norm = normalize_public_text(text)
        reasons: list[str] = []
        advisories: list[str] = []

        if not text and bool(getattr(decision, "should_speak", True)):
            reasons.append("empty_public_text")

        for marker in contract.prohibited_markers:
            marker_norm = normalize_public_text(marker)
            if marker_norm and marker_norm in norm:
                reasons.append(f"prohibited_surface:{marker_norm}")

        if frame.has_relation("META_STYLE_FEEDBACK") and _looks_like_helper_reset(norm):
            reasons.append("meta_style_feedback_answered_as_helper_reset")

        if frame.has_relation("CAPABILITY_INQUIRY"):
            if _looks_like_domain_disclaimer(norm):
                reasons.append("capability_answer_contains_domain_disclaimer")
            if not _mentions_capability_surface(norm, contract.capability_keywords):
                reasons.append("capability_answer_not_grounded_in_registry")

        if (frame.has_relation("REASSERT_AFTER_MISREAD") or frame.has_relation("PROVOCATION")) and _literalizes_family_insult(norm):
            reasons.append("provocation_literalized_as_family_fact")

        plan = contract.emotional_stance
        if plan is not None:
            voice_result = evaluate_character_voice(text, frame=frame, plan=plan)
            reasons.extend(voice_result.violations)
            advisories.extend(voice_result.advisories)

        if not reasons:
            return AcceptanceResult(
                True,
                advisories=tuple(dict.fromkeys(advisories)),
            )
        return AcceptanceResult(
            False,
            reasons=tuple(dict.fromkeys(reasons)),
            advisories=tuple(dict.fromkeys(advisories)),
            fallback_text=contract.fallback_text,
        )

    def apply(self, decision: Decision, *, frame: TurnFrame) -> Decision:
        contract = build_response_contract(frame, capability_action_ids=self.capability_action_ids)
        result = self._evaluate_with_contract(decision, frame=frame, contract=contract)
        plan = contract.emotional_stance

        if result.accepted:
            # Dù Qwen đã viết câu tốt, metadata diễn xuất vẫn phải đi xuống stage.
            # Không clone nếu không cần, tránh tạo object mới vô ích trên hot path.
            revised = decision
            revised = _apply_stance_metadata(revised, plan=plan)
            if result.advisories:
                revised = _append_reasoning_tags(revised, *result.advisories)
                revised.debug_trace = _append_trace(
                    getattr(revised, "debug_trace", ""),
                    "response_contract_advisory:" + ",".join(result.advisories[:3]),
                )
            return revised

        fallback = str(result.fallback_text or "").strip()
        if not fallback:
            # Contract active mà không có fallback là lỗi cấu hình. Không nên giữ
            # draft đã biết là hỏng; dùng một repair line trung tính tối thiểu.
            fallback = "Câu vừa rồi của tôi lệch nhịp. Tôi rút lại và đáp trực tiếp hơn."

        revised = _clone_decision(decision)
        revised.text = fallback
        revised.should_speak = True
        revised.system_action = ""
        revised.action_input = ""
        revised.intent = revised.intent or "conversation_repair"
        revised.action = "none"
        revised.parse_mode = "response_contract_fallback"
        try:
            revised.confidence = min(float(getattr(revised, "confidence", 0.55) or 0.55), 0.58)
        except Exception:
            revised.confidence = 0.55

        marker = "response_contract_gate:" + ",".join(result.reasons[:6])
        revised.debug_trace = _append_trace(getattr(revised, "debug_trace", ""), marker)
        revised = _append_reasoning_tags(
            revised,
            "response_contract_gate",
            *(result.reasons[:4]),
        )
        revised = _apply_stance_metadata(revised, plan=plan, force=True)
        return revised


def _apply_stance_metadata(
    decision: Decision,
    *,
    plan,
    force: bool = False,
) -> Decision:
    if plan is None or not getattr(plan, "active", False):
        return decision

    if force or not str(getattr(decision, "delivery_hint", "") or "").strip():
        decision.delivery_hint = str(getattr(plan, "delivery_hint", "") or "")
    if force or not str(getattr(decision, "nonverbal_cue", "") or "").strip():
        decision.nonverbal_cue = str(getattr(plan, "nonverbal_cue", "") or "")
    if force or not str(getattr(decision, "stage_motion", "") or "").strip():
        decision.stage_motion = str(getattr(plan, "stage_motion", "") or "")
    if force or not str(getattr(decision, "preset_emotion", "") or "").strip():
        decision.preset_emotion = str(getattr(plan, "preset_emotion", "") or "")

    decision = _append_reasoning_tags(
        decision,
        f"emotional_stance:{getattr(getattr(plan, 'kind', None), 'value', 'unknown')}",
    )
    decision.debug_trace = _append_trace(
        getattr(decision, "debug_trace", ""),
        f"stance:{getattr(getattr(plan, 'kind', None), 'value', 'unknown')}:{float(getattr(plan, 'intensity', 0.0)):.2f}",
    )
    return decision


def _clone_decision(decision: Decision) -> Decision:
    try:
        return replace(decision)
    except Exception:
        return decision


def _append_reasoning_tags(decision: Decision, *tags: str) -> Decision:
    existing = tuple(getattr(decision, "reasoning_tags", ()) or ())
    clean = tuple(str(tag or "").strip() for tag in tags if str(tag or "").strip())
    decision.reasoning_tags = tuple(dict.fromkeys((*existing, *clean)))
    return decision


def _append_trace(trace: str, marker: str) -> str:
    left = str(trace or "").strip()
    right = str(marker or "").strip()
    if not right:
        return left
    return f"{left} | {right}" if left else right


def _looks_like_helper_reset(norm: str) -> bool:
    markers = (
        "toi la eris", "tro ly ca nhan", "tro ly cua ngai", "san sang ho tro",
        "toi co the giup", "ngai can gi", "hay cho toi biet", "dat cau hoi",
    )
    return any(m in norm for m in markers)


def _looks_like_domain_disclaimer(norm: str) -> bool:
    markers = (
        "khong thay the chuyen gia", "tu van y te", "tu van phap ly", "luat su",
        "bac si", "chuyen gia tai chinh", "thong tin chi mang tinh",
    )
    return any(m in norm for m in markers)


def _mentions_capability_surface(norm: str, keywords: Iterable[str]) -> bool:
    for kw in keywords:
        k = normalize_public_text(str(kw or ""))
        if k and len(k) >= 3 and k in norm:
            return True
    return False


def _literalizes_family_insult(norm: str) -> bool:
    return any(
        m in norm
        for m in (
            "toi khong co me", "toi khong co bo", "toi khong co gia dinh",
            "ai khong co gia dinh", "toi chi la mot ai",
        )
    )


__all__ = ["AcceptanceResult", "ResponseAcceptanceGate"]
