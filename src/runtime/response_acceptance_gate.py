from __future__ import annotations

"""Acceptance Gate cho câu chat public.

Gate này không cố viết văn hay. Nó chỉ chặn các ca vi phạm contract rõ ràng:
model hiểu sai cú repair, tự giới thiệu khi bị chê nói như AI, hoặc trả lời câu
"làm được gì" bằng disclaimer y tế/pháp lý. Nói cách khác: cái chốt cửa tối thiểu
để ERIS không tự đạp vào cái xô vừa thấy trước mặt.
"""

from dataclasses import dataclass, replace
from typing import Iterable

from domain import Decision
from runtime.response_contract import ResponseContract, build_response_contract, normalize_public_text
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    accepted: bool
    reasons: tuple[str, ...] = ()
    fallback_text: str = ""


class ResponseAcceptanceGate:
    def __init__(self, *, capability_action_ids: Iterable[str] | None = None) -> None:
        self.capability_action_ids = tuple(capability_action_ids or ()) or None

    def evaluate(self, decision: Decision, *, frame: TurnFrame) -> AcceptanceResult:
        contract = build_response_contract(frame, capability_action_ids=self.capability_action_ids)
        if not contract.active:
            return AcceptanceResult(True)
        text = str(getattr(decision, "text", "") or "").strip()
        norm = normalize_public_text(text)
        reasons: list[str] = []

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

        if not reasons:
            return AcceptanceResult(True)
        return AcceptanceResult(False, reasons=tuple(dict.fromkeys(reasons)), fallback_text=contract.fallback_text)

    def apply(self, decision: Decision, *, frame: TurnFrame) -> Decision:
        result = self.evaluate(decision, frame=frame)
        if result.accepted:
            return decision
        fallback = result.fallback_text.strip()
        if not fallback:
            return decision
        try:
            revised = replace(decision)
        except Exception:
            revised = decision
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
        marker = "response_contract_gate:" + ",".join(result.reasons[:5])
        trace = str(getattr(revised, "debug_trace", "") or "").strip()
        revised.debug_trace = f"{trace} | {marker}" if trace else marker
        tags = tuple(getattr(revised, "reasoning_tags", ()) or ())
        revised.reasoning_tags = tuple(dict.fromkeys((*tags, "response_contract_gate", *result.reasons[:3])))
        if not getattr(revised, "delivery_hint", ""):
            revised.delivery_hint = "dry_tease" if frame.has_relation("PROVOCATION") else "focused"
        if not getattr(revised, "stage_motion", ""):
            revised.stage_motion = "blink_slow" if frame.has_relation("PROVOCATION") else "tilt_head"
        return revised


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
    return any(m in norm for m in ("toi khong co me", "toi khong co bo", "toi khong co gia dinh", "ai khong co gia dinh"))
