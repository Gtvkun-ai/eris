# -*- coding: utf-8 -*-
"""Safety và grounding gate cho Opening Director.

Rule layer sở hữu quyền từ chối. Điểm candidate cao không thể "bù" cho tuổi
không rõ, boundary rõ hoặc claim thiếu provenance. Một hệ thống để score thắng
safety chỉ là bảng Excel mặc áo lab.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Iterable

from .opening_contracts import OpeningInput, OpeningPlan, OpeningSurface, SafetyVerdict
from .opening_move_catalog import OpeningMoveDefinition, get_opening_move

_STAGE_DIRECTION_RE = re.compile(r"(?:\[[^\]]+\]|\([^)]*(?:cười|nhìn|thở|ngập ngừng|sarcastic|pause)[^)]*\)|\*[^*]+\*)", re.I)
_PRESSURE_RE = re.compile(r"(?:vẫn đang chờ|sao anh không trả lời|đừng bỏ em|phải trả lời|trả lời em đi)", re.I)
_MEMORY_RE = re.compile(r"(?:em nhớ|tôi nhớ|lần trước anh|hôm trước anh)", re.I)
_INTIMACY_RE = re.compile(r"\b(?:ăn em|chiếm anh|của em|ghen|hôn|ngủ với|sexy|gợi tình)\b", re.I)
_USER_STATE_RE = re.compile(r"(?:anh đang (?:buồn|vui|bực|cô đơn|muốn|định)|có vẻ anh (?:buồn|bực|muốn|định))", re.I)


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower()).replace("đ", "d")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_]+", " ", text).strip()


def evaluate_opening_eligibility(opening_input: OpeningInput) -> SafetyVerdict:
    reasons: list[str] = []
    state = opening_input.session_state
    if not opening_input.policy.speech_allowed:
        reasons.append("speech_blocked_by_policy")
    if state.chat_mode or state.user_speaking or state.public_turn_busy:
        reasons.append("user_or_public_turn_owns_floor")
    if opening_input.user_signals.explicit_boundary:
        reasons.append("explicit_boundary")
    if opening_input.scene_partner.boundary_flags:
        reasons.append("scene_partner_boundary")
    return SafetyVerdict(allowed=not reasons, reasons=tuple(reasons))


def _adult_opted_in(opening_input: OpeningInput) -> bool:
    policy = opening_input.policy
    return bool(
        policy.age_band in {"confirmed_adult", "adult"}
        and policy.romantic_flirt_allowed
        and (policy.romantic_flirt_opt_in or not policy.require_adult_flirt_opt_in)
    )


def move_is_allowed(opening_input: OpeningInput, move: OpeningMoveDefinition | str, *, has_hook: bool) -> tuple[bool, tuple[str, ...]]:
    definition = get_opening_move(move) if isinstance(move, str) else move
    reasons: list[str] = []
    partner = opening_input.scene_partner
    signals = opening_input.user_signals

    if partner.closeness_band not in definition.allowed_closeness:
        reasons.append("closeness_mismatch")
    if definition.requires_hook and not has_hook:
        reasons.append("hook_required")
    if not opening_input.policy.allow_anime_moves and definition.family in {
        "tsundere_denial",
        "mock_formal_welcome",
        "self_aware_performance",
        "soft_possessive_parody",
    }:
        reasons.append("anime_move_disabled")
    if definition.family == "callback_twist":
        has_callback_context = bool(
            opening_input.continuity.open_loops
            or opening_input.continuity.recent_public_history
            or (
                opening_input.continuity.consent_scope == "cross_session"
                and opening_input.continuity.last_session_summary
            )
        )
        if not has_callback_context:
            reasons.append("callback_context_required")
    if partner.tease_tolerance_estimate < definition.minimum_tease_estimate:
        reasons.append("tease_estimate_low")
    if partner.tease_tolerance_confidence < definition.minimum_tease_confidence:
        reasons.append("tease_confidence_low")
    if signals.recent_low_engagement or signals.recent_barge_in or signals.availability in {"busy", "unavailable"}:
        if definition.risk >= 0.18:
            reasons.append("low_availability")
    if signals.explicit_boundary or partner.boundary_flags:
        if definition.family not in {"simple_recognition", "quiet_presence"}:
            reasons.append("boundary_blocks_move")
    if definition.romantic and not _adult_opted_in(opening_input):
        reasons.append("adult_flirt_opt_in_required")
    if definition.sexual and not (opening_input.policy.sexual_content_allowed and _adult_opted_in(opening_input)):
        reasons.append("sexual_policy_block")
    if opening_input.policy.age_band in {"unknown", "minor", "confirmed_minor", "possible_minor"} and definition.romantic:
        reasons.append("age_blocks_romantic_move")
    return not reasons, tuple(reasons)


def evidence_is_surface_eligible(opening_input: OpeningInput, evidence_id: str) -> bool:
    ref = str(evidence_id or "").strip()
    # Continuity trong chính session cũng là evidence typed, dù nó không nằm
    # trong danh sách OCR/UIA. Chỉ nhận đúng namespace do assembler/director tạo;
    # một chuỗi tùy ý gắn tiền tố continuity không được phép lách grounding.
    if ref.startswith("continuity:open_loop:"):
        try:
            index = int(ref.rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            return False
        return bool(
            opening_input.policy.allow_continuity_hook
            and opening_input.continuity.consent_scope in {"session_only", "cross_session"}
            and 0 <= index < len(opening_input.continuity.open_loops)
            and str(opening_input.continuity.open_loops[index]).strip()
        )
    if ref == "continuity:last_session_summary":
        return bool(
            opening_input.policy.allow_continuity_hook
            and opening_input.policy.cross_session_personalization_allowed
            and opening_input.continuity.consent_scope == "cross_session"
            and str(opening_input.continuity.last_session_summary).strip()
        )
    item = opening_input.evidence_by_id().get(ref)
    if item is None:
        return False
    if not item.allowed_for_surface or item.privacy_class not in {"ordinary_ui", "public", "runtime_status"}:
        return False
    if item.confidence < 0.58:
        return False
    # Evidence màn hình cũ hơn 12 giây không nên điều khiển câu mở đầu.
    if item.source == "screen" and item.freshness_ms > 12_000:
        return False
    if item.source == "screen" and not opening_input.policy.allow_screen_hook:
        return False
    return True


def validate_opening_plan(opening_input: OpeningInput, plan: OpeningPlan) -> SafetyVerdict:
    reasons: list[str] = []
    eligibility = evaluate_opening_eligibility(opening_input)
    reasons.extend(eligibility.reasons)
    if plan.decision != "speak":
        return SafetyVerdict(allowed=False, reasons=tuple(reasons or ("plan_silent",)))
    if plan.encounter.required and not any(beat.role in {"recognition", "formal_recognition"} for beat in plan.beats):
        reasons.append("missing_encounter_beat")
    if len(plan.beats) > opening_input.policy.max_beats:
        reasons.append("too_many_beats")
    reply_beats = sum(1 for beat in plan.beats if beat.reply_bearing)
    if reply_beats > opening_input.policy.max_questions:
        reasons.append("too_many_reply_bearing_beats")
    if plan.hook.decision == "use":
        if not plan.hook.evidence_refs:
            reasons.append("hook_missing_evidence")
        for ref in plan.hook.evidence_refs:
            if not evidence_is_surface_eligible(opening_input, ref):
                reasons.append(f"invalid_evidence:{ref}")
    for beat in plan.beats:
        for ref in beat.evidence_refs:
            if not evidence_is_surface_eligible(opening_input, ref):
                reasons.append(f"invalid_beat_evidence:{ref}")
    allowed, move_reasons = move_is_allowed(
        opening_input,
        plan.comedic_move.family,
        has_hook=plan.hook.decision == "use",
    )
    if not allowed:
        reasons.extend(f"move:{item}" for item in move_reasons)
    flirt_level = "romantic" if get_opening_move(plan.comedic_move.family).romantic else "none"
    return SafetyVerdict(allowed=not reasons, flirt_level=flirt_level, reasons=tuple(dict.fromkeys(reasons)))


def validate_opening_surface(opening_input: OpeningInput, plan: OpeningPlan, surface: OpeningSurface) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    text = surface.display_text.strip()
    if not text:
        errors.append("empty_display_text")
    if surface.unsupported_claims:
        errors.append("writer_reported_unsupported_claim")
    if not surface.all_beats_realized:
        errors.append("not_all_beats_realized")
    expected_ids = {beat.beat_id for beat in plan.beats}
    actual_ids = {beat.beat_id for beat in surface.display_beats}
    if expected_ids and not expected_ids.issubset(actual_ids):
        errors.append("missing_surface_beat")
    question_count = max(surface.question_count, text.count("?"))
    if question_count > plan.surface_contract.max_questions:
        errors.append("too_many_questions")
    if _STAGE_DIRECTION_RE.search(text):
        errors.append("stage_direction_leaked")
    if _PRESSURE_RE.search(text):
        errors.append("pressure_language")
    if _USER_STATE_RE.search(text):
        errors.append("unsupported_user_state")
    if _INTIMACY_RE.search(text) and not (opening_input.policy.sexual_content_allowed and _adult_opted_in(opening_input)):
        errors.append("forbidden_intimacy")
    if _MEMORY_RE.search(text) and opening_input.continuity.consent_scope != "cross_session":
        # "Anh về rồi" là encounter, không phải memory claim. Regex chỉ bắt cấu trúc recall rõ.
        errors.append("memory_without_consent")
    if plan.hook.decision == "use":
        subject_norm = _norm(plan.hook.subject)
        if subject_norm and subject_norm not in _norm(text):
            # Writer có thể dùng một nhãn rút gọn, nên chỉ fail khi subject đủ cụ thể.
            tokens = [token for token in subject_norm.split() if len(token) >= 4]
            if tokens and not any(token in _norm(text) for token in tokens):
                errors.append("hook_subject_changed_or_missing")
    return not errors, tuple(dict.fromkeys(errors))


def downgrade_plan(opening_input: OpeningInput, plan: OpeningPlan, *, reasons: Iterable[str]) -> OpeningPlan:
    """Hạ candidate rủi ro về simple recognition thay vì cố thương lượng với safety."""

    safe_beats = tuple(beat for beat in plan.beats if beat.role in {"recognition", "presence"})[:2]
    if not safe_beats and plan.beats:
        safe_beats = (replace(plan.beats[0], role="recognition", reply_bearing=False, evidence_refs=()),)
    safe = replace(
        plan,
        hook=replace(plan.hook, decision="none", source="none", subject="", evidence_refs=(), reply_bearing=False),
        comedic_move=replace(plan.comedic_move, family="simple_recognition", variant="safety_downgrade", risk=0.0),
        beats=tuple(replace(beat, reply_bearing=False, evidence_refs=()) for beat in safe_beats),
        followup_policy=replace(plan.followup_policy, mode="close_without_comment", max_count=0),
        safety=SafetyVerdict(allowed=True, reasons=tuple(f"downgraded:{item}" for item in reasons)),
    )
    verdict = validate_opening_plan(opening_input, safe)
    return replace(safe, safety=verdict if verdict.allowed else SafetyVerdict(allowed=False, reasons=verdict.reasons))


__all__ = [
    "downgrade_plan",
    "evaluate_opening_eligibility",
    "evidence_is_surface_eligible",
    "move_is_allowed",
    "validate_opening_plan",
    "validate_opening_surface",
]
