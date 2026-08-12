# -*- coding: utf-8 -*-
"""Bộ điều khiển *khi nào nên chủ động* của Subject Core (V58).

Module này cố ý không viết câu trả lời và không gọi model. Nó chỉ trả một trong
ba lựa chọn có nghĩa hành vi rõ ràng:

- SPEAK: ý định có nội dung, đủ quan trọng và thời điểm phù hợp để đưa vào vòng
  cạnh tranh của Executive/Neuro.
- WAIT: ý định vẫn đáng giữ nhưng hiện tại chưa nên làm phiền user.
- DROP: ý định đã yếu/cũ tới mức nên bỏ thay vì biến thành lời nhắc dai dẳng.

Điểm quan trọng: "có ý định" không đồng nghĩa "phải nói". Nếu thiếu lớp này,
agent rất dễ nhầm chủ động với spam, một nhầm lẫn mà con người đã minh họa đủ
trên mọi ứng dụng có notification.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


class InitiativeControlAction(StrEnum):
    SPEAK = "speak"
    WAIT = "wait"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class InitiativeControlConfig:
    speak_threshold: float = 0.52
    social_speak_threshold: float = 0.64
    drop_after_seconds: float = 12.0 * 60.0
    drop_pressure: float = 0.24
    drop_commitment: float = 0.34


@dataclass(frozen=True, slots=True)
class InitiativeControlDecision:
    action: InitiativeControlAction
    score: float
    reason: str
    intention_id: str
    motive_kind: str
    pressure: float
    commitment: float
    contentful: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.initiative_control.v58",
            "action": self.action.value,
            "score": round(self.score, 4),
            "reason": self.reason,
            "intention_id": self.intention_id,
            "motive_kind": self.motive_kind,
            "pressure": round(self.pressure, 4),
            "commitment": round(self.commitment, 4),
            "contentful": self.contentful,
        }


class InitiativeArbiter:
    """Cân mục tiêu + tò mò + quan hệ + ngữ cảnh để chọn SPEAK/WAIT/DROP."""

    _SOCIAL_MOTIVES = {"understand_user", "connect", "share", "seek_recognition"}
    _PERSISTENCE_MOTIVES = {"contribute", "resolve", "be_understood", "demonstrate"}

    def __init__(self, config: InitiativeControlConfig | None = None) -> None:
        self.config = config or InitiativeControlConfig()

    def decide(
        self,
        intention: Mapping[str, Any],
        *,
        relational: Mapping[str, Any] | None,
        runtime_context: Mapping[str, Any] | None,
        now: float,
        contentful: bool,
        reply_expected: bool = False,
        user_busy: bool = False,
        interaction_busy: bool = False,
    ) -> InitiativeControlDecision:
        rel = relational or {}
        runtime = runtime_context or {}
        intention_id = str(intention.get("intention_id") or "")
        motive = str(intention.get("motive_kind") or "").strip().lower()
        pressure = _clamp01(intention.get("pressure", 0.0))
        commitment = _clamp01(intention.get("commitment_strength", 0.0))
        created_at = float(intention.get("created_at", now) or now)
        age = max(0.0, float(now) - created_at)

        def result(action: InitiativeControlAction, score: float, reason: str) -> InitiativeControlDecision:
            return InitiativeControlDecision(
                action=action,
                score=_clamp01(score),
                reason=reason,
                intention_id=intention_id,
                motive_kind=motive,
                pressure=pressure,
                commitment=commitment,
                contentful=bool(contentful),
            )

        # Đây là các trường hợp "đừng giành micro". WAIT giữ nguyên intention để
        # Eris có thể quay lại sau, khác với DROP là chủ động từ bỏ.
        if reply_expected:
            return result(InitiativeControlAction.WAIT, 0.0, "user_reply_expected")
        if user_busy or interaction_busy:
            return result(InitiativeControlAction.WAIT, 0.0, "user_or_runtime_busy")
        if bool(runtime.get("last_public_turn_unanswered", False)) and _clamp01(runtime.get("recent_unsolicited_speech", 0.0)) >= 0.5:
            return result(InitiativeControlAction.WAIT, 0.0, "previous_autonomous_turn_unanswered")
        if motive in self._SOCIAL_MOTIVES and bool(runtime.get("startup_social_cooldown_active", False)):
            return result(InitiativeControlAction.WAIT, 0.0, "startup_social_cooldown")
        seconds_since_user = max(0.0, float(runtime.get("seconds_since_last_user_turn", 10_000.0) or 0.0))
        # Mục tiêu cũ chỉ được tự gợi lại sau một khoảng lặng đủ rõ. User vừa đổi
        # chủ đề xong mà Eris lập tức kéo project trở lại thì không phải persistence,
        # đó là không biết đọc phòng.
        if motive in self._PERSISTENCE_MOTIVES and seconds_since_user < 75.0:
            return result(InitiativeControlAction.WAIT, 0.0, "persistent_goal_too_soon_after_user")

        # Ý định cũ và yếu nên được bỏ. Không dùng DROP chỉ vì user đang bận,
        # nếu không một cuộc điện thoại đến cũng đủ làm Eris "quên" mục tiêu.
        if (
            age >= self.config.drop_after_seconds
            and pressure <= self.config.drop_pressure
            and commitment <= self.config.drop_commitment
        ):
            return result(InitiativeControlAction.DROP, 0.0, "stale_low_value_intention")

        # Không có đối tượng cụ thể để nói thì cứ WAIT. Curiosity chung chung vẫn
        # được giữ làm động lực nội tại, nhưng không được phép hóa thành câu hỏi NPC.
        if not contentful:
            return result(InitiativeControlAction.WAIT, 0.0, "no_contentful_object")

        opportunity = _clamp01(rel.get("opportunity", 0.45), 0.45)
        curiosity = _clamp01(rel.get("social_curiosity", 0.0))
        satiety = _clamp01(rel.get("interaction_satiety", 0.0))
        interruption = _clamp01(rel.get("interruption_cost", 0.25), 0.25)
        response_rate = _clamp01(runtime.get("user_response_rate", 0.7), 0.7)
        refractory = _clamp01(runtime.get("social_refractory_cost", 0.0))
        freshness = _clamp01(1.0 - age / max(60.0, self.config.drop_after_seconds * 1.8))
        persistence_bonus = 1.0 if motive in self._PERSISTENCE_MOTIVES else 0.0
        explicit_open_goal = 1.0 if str(runtime.get("active_goal_text") or "").strip() else 0.0
        silence_readiness = _clamp01((seconds_since_user - 60.0) / 120.0)

        # Công thức cố ý đơn giản và bounded để test/replay được. Nó không giả vờ
        # là "ý chí". Nó chỉ làm rõ tại sao một ý định được đưa ra public lúc này.
        score = (
            0.31 * pressure
            + 0.24 * commitment
            + 0.13 * opportunity
            + 0.08 * curiosity
            + 0.07 * freshness
            + 0.07 * response_rate
            + 0.08 * persistence_bonus
            + 0.08 * explicit_open_goal
            + 0.14 * silence_readiness
            - 0.16 * interruption
            - 0.12 * satiety
            - 0.20 * refractory
        )
        score = _clamp01(score)
        threshold = self.config.social_speak_threshold if motive in self._SOCIAL_MOTIVES else self.config.speak_threshold
        if score >= threshold:
            return result(InitiativeControlAction.SPEAK, score, "initiative_value_exceeds_context_cost")
        return result(InitiativeControlAction.WAIT, score, "initiative_not_worth_interrupting_yet")


__all__ = [
    "InitiativeArbiter",
    "InitiativeControlAction",
    "InitiativeControlConfig",
    "InitiativeControlDecision",
]
