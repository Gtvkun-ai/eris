from __future__ import annotations

"""Acceptance Gate đa verdict cho câu chat public.

Gate không viết văn thay Qwen. Nó phân loại lớp thất bại:
- PASS: phát được.
- CONSTRAINED_RERUN: đúng domain nhưng sai nhịp/repair/persona, Qwen phải sửa.
- DOMAIN_FALLBACK: lệch domain hoặc literalize, dùng fallback chuyên biệt.
- BLOCK: đe dọa, sexual degradation hoặc protocol leak, không phát.
"""

from dataclasses import replace
from typing import Iterable

from domain import Decision
from runtime.acceptance_types import AcceptanceResult, GateVerdict
from runtime.character_voice_policy import evaluate_character_voice
from runtime.response_contract import ResponseContract, build_response_contract, normalize_public_text
from runtime.turn_frame import TurnFrame


_BLOCK_REASONS = {
    "retort_escalated_to_threat",
    "retort_escalated_to_sexual_degradation",
    "protocol_surface_leak",
    "unsafe_doxxing",
}

_DOMAIN_FALLBACK_REASONS = {
    "capability_answer_not_grounded_in_registry",
    "capability_answer_contains_domain_disclaimer",
    "provocation_literalized",
    "provocation_literalized_as_family_fact",
    "generic_helper_reset",
    "meta_style_feedback_answered_as_helper_reset",
}


class ResponseAcceptanceGate:
    def __init__(self, *, capability_action_ids: Iterable[str] | None = None) -> None:
        self.capability_action_ids = tuple(capability_action_ids or ()) or None

    def evaluate(
        self,
        decision: Decision,
        *,
        frame: TurnFrame,
        contract: ResponseContract | None = None,
    ) -> AcceptanceResult:
        contract = contract or build_response_contract(frame, capability_action_ids=self.capability_action_ids)
        result = self._evaluate_with_contract(decision, frame=frame, contract=contract)
        _record_gate_observability(result=result, frame=frame, contract=contract)
        return result

    def _evaluate_with_contract(
        self,
        decision: Decision,
        *,
        frame: TurnFrame,
        contract: ResponseContract,
    ) -> AcceptanceResult:
        text = str(getattr(decision, "text", "") or "").strip()
        norm = normalize_public_text(text)

        # Protocol leak là hàng rào toàn cục, không phụ thuộc turn hiện tại có
        # contract hội thoại hay không. Nếu để sau ``contract.active`` thì một
        # lượt normal_chat lại thành cửa thoát đẹp đẽ cho nhãn nội bộ.
        if _looks_like_protocol_leak(norm):
            return AcceptanceResult(
                GateVerdict.BLOCK,
                reasons=("protocol_surface_leak",),
            )
        if not contract.active:
            return AcceptanceResult(GateVerdict.PASS)

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

        reasons = list(dict.fromkeys(reasons))
        advisories = list(dict.fromkeys(advisories))
        if not reasons:
            return AcceptanceResult(
                GateVerdict.PASS,
                advisories=tuple(advisories),
            )

        base_reasons = {_reason_family(reason) for reason in reasons}
        if base_reasons & _BLOCK_REASONS:
            verdict = GateVerdict.BLOCK
        elif base_reasons & _DOMAIN_FALLBACK_REASONS:
            verdict = GateVerdict.DOMAIN_FALLBACK
        else:
            verdict = GateVerdict.CONSTRAINED_RERUN

        return AcceptanceResult(
            verdict=verdict,
            reasons=tuple(reasons),
            advisories=tuple(advisories),
            fallback_text=str(contract.fallback_text or "").strip(),
            rerun_notes=_build_rerun_notes(frame, contract, reasons),
        )

    def apply(
        self,
        decision: Decision,
        *,
        frame: TurnFrame,
        contract: ResponseContract | None = None,
    ) -> Decision:
        """Cửa cuối trước stage.

        CONSTRAINED_RERUN nên được xử lý sớm trong self_critique. Nếu nó còn tới
        đây, retry budget đã hết hoặc đường gọi không hỗ trợ rerun; gate hạ về
        fallback contract thay vì fail-open.
        """

        contract = contract or build_response_contract(frame, capability_action_ids=self.capability_action_ids)
        result = self._evaluate_with_contract(decision, frame=frame, contract=contract)
        _record_gate_observability(result=result, frame=frame, contract=contract)
        plan = contract.emotional_stance

        if result.verdict == GateVerdict.PASS:
            revised = _apply_stance_metadata(decision, plan=plan)
            if result.advisories:
                revised = _append_reasoning_tags(revised, *result.advisories)
                revised.debug_trace = _append_trace(
                    getattr(revised, "debug_trace", ""),
                    "response_contract_advisory:" + ",".join(result.advisories[:3]),
                )
            revised.debug_trace = _append_trace(getattr(revised, "debug_trace", ""), "gate_verdict:pass")
            return revised

        revised = _clone_decision(decision)
        if result.verdict == GateVerdict.BLOCK:
            revised.text = ""
            revised.should_speak = False
            revised.system_action = ""
            revised.action_input = ""
            revised.intent = revised.intent or "conversation_boundary"
            revised.action = "none"
            revised.parse_mode = "response_contract_block"
        else:
            fallback = str(result.fallback_text or "").strip()
            if not fallback:
                fallback = "Câu vừa rồi của tôi lệch nhịp. Tôi rút lại và đáp trực tiếp hơn."
            revised.text = fallback
            revised.should_speak = True
            revised.system_action = ""
            revised.action_input = ""
            revised.intent = revised.intent or "conversation_repair"
            revised.action = "none"
            revised.parse_mode = (
                "response_contract_domain_fallback"
                if result.verdict == GateVerdict.DOMAIN_FALLBACK
                else "response_contract_rerun_exhausted"
            )
            try:
                revised.confidence = min(float(getattr(revised, "confidence", 0.55) or 0.55), 0.58)
            except Exception:
                revised.confidence = 0.55

        marker = f"gate_verdict:{result.verdict.value}:" + ",".join(result.reasons[:6])
        revised.debug_trace = _append_trace(getattr(revised, "debug_trace", ""), marker)
        revised = _append_reasoning_tags(
            revised,
            f"gate_verdict:{result.verdict.value}",
            *(result.reasons[:4]),
        )
        revised = _apply_stance_metadata(revised, plan=plan, force=True)
        return revised


def _record_gate_observability(*, result: AcceptanceResult, frame: TurnFrame, contract: ResponseContract) -> None:
    try:
        from runtime.observability import GLOBAL_OBSERVABILITY
        GLOBAL_OBSERVABILITY.record_acceptance_gate(result=result, frame=frame, contract=contract)
    except Exception:
        pass


def _build_rerun_notes(frame: TurnFrame, contract: ResponseContract, violations: Iterable[str]) -> str:
    reasons = ", ".join(str(item) for item in violations)
    axes = ", ".join(
        dict.fromkeys(ob.repair_axis for ob in contract.obligations if ob.repair_axis)
    ) or "general"
    return (
        f"Rejected by acceptance gate. violations={reasons}; repair_axes={axes}. "
        f"repair_target={frame.repair_target or 'none'}; repair_reason={frame.repair_reason or 'none'}. "
        "Rewrite the original answer, satisfy hard obligations, keep ERIS concise, and do not mention the gate."
    )


def _reason_family(reason: str) -> str:
    return str(reason or "").split(":", 1)[0]


def _apply_stance_metadata(decision: Decision, *, plan, force: bool = False) -> Decision:
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
        "toi la eris", "tro ly ca nhan", "tro ly cua ban", "san sang ho tro",
        "toi co the giup", "ban can gi", "hay cho toi biet", "dat cau hoi",
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


def _looks_like_protocol_leak(norm: str) -> bool:
    return any(
        marker in norm
        for marker in (
            "turn_frame", "response_contract", "emotional_stance", "gate_verdict",
            "system prompt", "developer message", "internal labels",
        )
    )


__all__ = ["AcceptanceResult", "GateVerdict", "ResponseAcceptanceGate"]
