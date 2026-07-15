from __future__ import annotations

"""Chọn số candidate theo lane, độ mơ hồ và áp lực token.

Không còn hai cực đoan "một candidate tuyệt đối" và "3-5 candidate mọi nơi".
Controller chỉ mở model pass thứ hai khi nó có lý do rõ ràng và provider còn đủ
headroom. Candidate deterministic trong Director vẫn luôn tồn tại làm lưới an
toàn rẻ tiền.
"""

from dataclasses import dataclass
from typing import Any, Iterable

from llm.token_pressure import TokenPressureSnapshot
from runtime.social_act import ChatAct, PERFORM_NOW_ACTS, classify_chat_act_with_confidence


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    lane: str
    chat_act: ChatAct
    act_confidence: float
    model_candidates: int
    reason: str
    token_pressure: float
    pressure_level: str
    candidate_lanes: tuple[str, ...] = ()

    @property
    def use_model_second_pass(self) -> bool:
        return self.model_candidates > 0


class AdaptiveCandidateController:
    """Policy deterministic, dễ test và không tự gọi model."""

    _FAILURE_MARKERS = (
        "literal_paraphrase",
        "literalism",
        "social_ack_instead_of_perform",
        "low_pragmatic_fit",
        "candidate_generation_failed",
    )

    def decide(
        self,
        *,
        lane: str,
        user_text: str,
        draft_confidence: float,
        recent_failures: Iterable[str] = (),
        token_snapshot: TokenPressureSnapshot | None = None,
        turn_frame: Any | None = None,
    ) -> CandidatePlan:
        lane_key = str(lane or "chat").strip().lower()
        act, act_confidence = classify_chat_act_with_confidence(user_text)
        pressure = float(getattr(token_snapshot, "pressure", 0.0) or 0.0)
        pressure_level = str(getattr(token_snapshot, "level", "normal") or "normal")
        max_candidates = int(getattr(token_snapshot, "max_model_candidates", 3) or 0)
        shed_optional = bool(getattr(token_snapshot, "shed_optional_passes", False))

        relation_kinds = {
            str(getattr(item, "kind", "") or "").strip().upper()
            for item in tuple(getattr(turn_frame, "discourse_relations", ()) or ())
        }
        stance_kinds = {
            str(getattr(item, "kind", "") or "").strip().upper()
            for item in tuple(getattr(turn_frame, "social_stances", ()) or ())
        }

        if lane_key == "micro_presence":
            return CandidatePlan(lane_key, act, act_confidence, 0, "micro_presence_single_candidate", pressure, pressure_level)
        if shed_optional or max_candidates <= 0:
            return CandidatePlan(lane_key, act, act_confidence, 0, "token_pressure_shed", pressure, pressure_level)

        failure_blob = " ".join(str(item or "").lower() for item in recent_failures)
        had_pragmatic_failure = any(marker in failure_blob for marker in self._FAILURE_MARKERS)
        try:
            confidence = max(0.0, min(1.0, float(draft_confidence)))
        except (TypeError, ValueError):
            confidence = 0.0

        requested = 0
        reason = "single_draft_sufficient"
        candidate_lanes: tuple[str, ...] = ()
        repair_uncertain = "repair_uncertain" in failure_blob

        # Các lane dưới đây bám nghĩa vụ hội thoại, không mở candidate theo kiểu
        # "nhiều hơn chắc hay hơn". Con người đã phát minh đủ cách đốt quota rồi.
        if "META_STYLE_FEEDBACK" in relation_kinds:
            requested = 2
            reason = "meta_style_repair_axes"
            candidate_lanes = ("direct_repair", "self_aware_dry")
        elif "CAPABILITY_INQUIRY" in relation_kinds:
            requested = 2
            reason = "capability_registry_axes"
            candidate_lanes = ("compact_registry", "natural_registry")
        elif {"REASSERT_AFTER_MISREAD", "PROVOCATION"}.issubset(relation_kinds):
            requested = 2
            reason = "repair_then_provocation_axes"
            candidate_lanes = ("repair_then_retort", "repair_then_boundary")
        elif "REPEATED_PROVOCATION" in relation_kinds and "HOSTILE_PROVOCATION" in stance_kinds:
            requested = 2
            reason = "repeated_hostile_axes"
            candidate_lanes = ("sharp_retort", "cold_boundary")
        # Repair uncertainty chỉ cần đúng hai biến thể: một direct, một playful.
        # Không mở 3 candidate vì một lượt tự sửa sai không đáng đốt provider như
        # cuộc thi văn mẫu. Token pressure ở trên vẫn có quyền shed toàn bộ pass.
        elif repair_uncertain:
            requested = 2
            reason = "dual_axis_repair_uncertainty"
            candidate_lanes = ("direct_repair", "repair_then_retort")
        # confidence=0 thường là field cũ bị thiếu, không phải model tự thú rằng
        # nó mù tịt. Chỉ coi low-confidence khi giá trị dương có chủ ý.
        elif (0.0 < confidence < 0.70) or had_pragmatic_failure:
            requested = 3
            reason = "low_confidence_or_recent_failure"
            candidate_lanes = ("direct", "self_aware", "boundary_safe")
        elif act in PERFORM_NOW_ACTS:
            requested = 2
            reason = "social_performative_turn"
            candidate_lanes = ("perform_direct", "perform_character")
        elif act in {ChatAct.GRANT_RELATIONAL_PERMISSION, ChatAct.META_SOCIAL_BOUNDARY} and act_confidence < 0.95:
            requested = 2
            reason = "social_boundary_ambiguity"
            candidate_lanes = ("warm_boundary", "cold_boundary")

        requested = min(requested, max_candidates)
        candidate_lanes = candidate_lanes[:requested]
        # Một model candidate đơn độc không đáng mở thêm request. Draft hiện tại đã
        # là candidate số một; pass phụ chỉ có ích khi sinh được ít nhất hai biến thể.
        if requested == 1:
            requested = 0
            reason = "pressure_left_only_one_variant"
            candidate_lanes = ()

        return CandidatePlan(
            lane=lane_key,
            chat_act=act,
            act_confidence=act_confidence,
            model_candidates=requested,
            reason=reason,
            token_pressure=pressure,
            pressure_level=pressure_level,
            candidate_lanes=candidate_lanes,
        )


__all__ = ["AdaptiveCandidateController", "CandidatePlan"]
