from __future__ import annotations

"""Chọn số candidate theo lane, độ mơ hồ và áp lực token.

Không còn hai cực đoan "một candidate tuyệt đối" và "3-5 candidate mọi nơi".
Controller chỉ mở model pass thứ hai khi nó có lý do rõ ràng và provider còn đủ
headroom. Candidate deterministic trong Director vẫn luôn tồn tại làm lưới an
toàn rẻ tiền.
"""

from dataclasses import dataclass
from typing import Iterable

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
    ) -> CandidatePlan:
        lane_key = str(lane or "chat").strip().lower()
        act, act_confidence = classify_chat_act_with_confidence(user_text)
        pressure = float(getattr(token_snapshot, "pressure", 0.0) or 0.0)
        pressure_level = str(getattr(token_snapshot, "level", "normal") or "normal")
        max_candidates = int(getattr(token_snapshot, "max_model_candidates", 3) or 0)
        shed_optional = bool(getattr(token_snapshot, "shed_optional_passes", False))

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
        # confidence=0 thường là field cũ bị thiếu, không phải model tự thú rằng
        # nó mù tịt. Chỉ coi low-confidence khi giá trị dương có chủ ý.
        if (0.0 < confidence < 0.70) or had_pragmatic_failure:
            requested = 3
            reason = "low_confidence_or_recent_failure"
        elif act in PERFORM_NOW_ACTS:
            requested = 2
            reason = "social_performative_turn"
        elif act in {ChatAct.GRANT_RELATIONAL_PERMISSION, ChatAct.META_SOCIAL_BOUNDARY} and act_confidence < 0.95:
            requested = 2
            reason = "social_boundary_ambiguity"

        requested = min(requested, max_candidates)
        # Một model candidate đơn độc không đáng mở thêm request. Draft hiện tại đã
        # là candidate số một; pass phụ chỉ có ích khi sinh được ít nhất hai biến thể.
        if requested == 1:
            requested = 0
            reason = "pressure_left_only_one_variant"

        return CandidatePlan(
            lane=lane_key,
            chat_act=act,
            act_confidence=act_confidence,
            model_candidates=requested,
            reason=reason,
            token_pressure=pressure,
            pressure_level=pressure_level,
        )


__all__ = ["AdaptiveCandidateController", "CandidatePlan"]
