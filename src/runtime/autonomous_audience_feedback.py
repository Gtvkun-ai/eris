# -*- coding: utf-8 -*-
"""autonomous_audience_feedback.py - vòng phản hồi khán giả cho autonomous.

Phase 1-4 giúp Eris phát hiện cơ hội, giữ nhịp phiên, xây show arc và dùng
playbook theo scene. Nhưng hệ vẫn thiếu một vòng kín quan trọng: sau khi tự nói,
Eris phải biết câu đó được đón nhận, bị sửa, bị từ chối hay đơn giản là rơi vào
khoảng không.

Module này không "đọc cảm xúc" người dùng. Nó chỉ tổng hợp các tín hiệu hành vi
có thể kiểm chứng: user trả lời bằng text, yêu cầu dừng/đính chính, tiếp tục tập
trung, đổi scene hoặc không có phản hồi trong một cửa sổ ngắn. Kết quả chỉ được
dùng để siết cadence/budget ở các lượt autonomous sau, không biến thành fact về
trạng thái tâm lý của người dùng.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_speak_gate import SpeakPermit


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))


@dataclass(slots=True)
class AudienceFeedbackConfig:
    reply_window_ms: int = 22_000
    ignored_window_ms: int = 32_000
    recent_outcomes: int = 16
    negative_kind_cooldown_ms: int = 12 * 60_000


@dataclass(frozen=True, slots=True)
class PendingAutonomousAct:
    act_id: str
    opportunity_id: str
    opportunity_kind: str
    scene_mode: str
    intent: str
    hook_id: str
    text_signature: str
    spoken_at_ms: int
    reply_deadline_ms: int
    ignored_deadline_ms: int

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AudienceOutcome:
    outcome_id: str
    act_id: str
    opportunity_kind: str
    kind: str
    valence: float
    confidence: float
    observed_at_ms: int
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AudienceFeedbackDirective:
    mode: str
    engagement_score: float
    intrusion_pressure: float
    body_only_bias: float
    cooldown_multiplier: float
    max_words_cap: int
    suppressed_kinds: tuple[str, ...]
    recent_outcome: str
    pending_act_id: str
    reason: str

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["suppressed_kinds"] = list(self.suppressed_kinds)
        return payload


class AutonomousAudienceFeedbackLoop:
    """Theo dõi phản ứng sau một act và trả policy cho lượt kế tiếp.

    Vòng này chỉ được quyền *siết* permit. Nó không tự nâng một opportunity yếu
    thành lời nói chỉ vì user từng cười một lần. Con người gọi đó là học từ phản
    hồi; phần mềm thường gọi là một dịp tuyệt vời để overfit. Ta không làm vậy.
    """

    _REJECT_PATTERNS = (
        r"\b(?:im đi|đừng nói|đừng chen|nói nhiều|ồn quá|thôi nói|câm|đừng tự nói)\b",
        r"\b(?:không cần nhắc|để tôi yên|tập trung đi|đừng làm phiền)\b",
    )
    _CORRECTION_PATTERNS = (
        r"^(?:không[, ]|không phải|ý tôi là|sai rồi|nhầm rồi|đính chính)",
        r"\b(?:không đúng|hiểu sai|đọc sai)\b",
    )
    _AFFIRM_PATTERNS = (
        r"\b(?:haha+|hihi+|đúng rồi|chuẩn|hay đấy|được đấy|ổn đấy|ok|ừ đúng)\b",
    )

    def __init__(self, config: AudienceFeedbackConfig | None = None) -> None:
        self.config = config or AudienceFeedbackConfig()
        self.pending_act: PendingAutonomousAct | None = None
        self._outcomes: deque[AudienceOutcome] = deque(maxlen=max(4, self.config.recent_outcomes))
        self._last_negative_by_kind: dict[str, int] = {}

    def record_act(
        self,
        *,
        opportunity: AutonomousOpportunity,
        scene_mode: str,
        text: str,
        intent: str = "",
        hook_id: str = "",
        at_ms: int | None = None,
    ) -> PendingAutonomousAct:
        now = int(at_ms if at_ms is not None else _now_ms())
        # Act mới thay act cũ. Nếu act cũ vẫn chưa có kết quả, đóng nó như một
        # lần bị bỏ qua nhẹ thay vì để pending treo mãi qua cả buổi.
        if self.pending_act is not None:
            self._close_pending(
                kind="superseded",
                valence=-0.04,
                confidence=0.62,
                reason="new_autonomous_act_superseded_pending",
                now_ms=now,
            )
        signature = _clean(text).lower()[:120]
        act = PendingAutonomousAct(
            act_id=f"actfb_{uuid.uuid4().hex[:12]}",
            opportunity_id=opportunity.opportunity_id,
            opportunity_kind=opportunity.kind,
            scene_mode=str(scene_mode or opportunity.scene_mode or "unknown"),
            intent=_clean(intent),
            hook_id=_clean(hook_id),
            text_signature=signature,
            spoken_at_ms=now,
            reply_deadline_ms=now + max(3_000, int(self.config.reply_window_ms)),
            ignored_deadline_ms=now + max(5_000, int(self.config.ignored_window_ms)),
        )
        self.pending_act = act
        return act

    def observe(
        self,
        *,
        channel: str = "",
        user_text: str = "",
        scene: SceneRuntimeState | None = None,
        now_ms: int | None = None,
    ) -> AudienceOutcome | None:
        now = int(now_ms if now_ms is not None else _now_ms())
        pending = self.pending_act
        if pending is None:
            return None

        channel_name = _clean(channel).lower()
        text = _clean(user_text)
        if channel_name == "chat" and text and now <= pending.ignored_deadline_ms:
            folded = text.lower()
            if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in self._REJECT_PATTERNS):
                return self._close_pending(
                    kind="rejected",
                    valence=-1.0,
                    confidence=0.95,
                    reason="explicit_stop_or_intrusion_feedback",
                    now_ms=now,
                )
            if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in self._CORRECTION_PATTERNS):
                return self._close_pending(
                    kind="corrected",
                    valence=-0.62,
                    confidence=0.86,
                    reason="user_corrected_autonomous_line",
                    now_ms=now,
                )
            if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in self._AFFIRM_PATTERNS):
                return self._close_pending(
                    kind="affirmed",
                    valence=0.78,
                    confidence=0.78,
                    reason="user_affirmed_or_laughed",
                    now_ms=now,
                )
            return self._close_pending(
                kind="engaged",
                valence=0.34,
                confidence=0.66,
                reason="user_replied_after_autonomous_act",
                now_ms=now,
            )

        if now >= pending.ignored_deadline_ms:
            if scene is not None and bool(getattr(scene, "user_typing", False)):
                return self._close_pending(
                    kind="continued_focus",
                    valence=-0.05,
                    confidence=0.70,
                    reason="user_continued_task_without_reply",
                    now_ms=now,
                )
            return self._close_pending(
                kind="ignored",
                valence=-0.24,
                confidence=0.62,
                reason="no_observable_response_in_feedback_window",
                now_ms=now,
            )

        if scene is not None and scene.name != pending.scene_mode and now > pending.reply_deadline_ms:
            return self._close_pending(
                kind="scene_shift",
                valence=-0.08,
                confidence=0.58,
                reason=f"scene_shifted:{pending.scene_mode}->{scene.name}",
                now_ms=now,
            )
        return None

    def directive(
        self,
        *,
        opportunity: AutonomousOpportunity | None = None,
        now_ms: int | None = None,
    ) -> AudienceFeedbackDirective:
        now = int(now_ms if now_ms is not None else _now_ms())
        weighted_valence = 0.0
        weight_total = 0.0
        negative_weight = 0.0
        ignored_weight = 0.0
        for idx, outcome in enumerate(reversed(self._outcomes)):
            # Outcome gần nhất có trọng số lớn hơn; chỉ là decay hành vi, không
            # phải mô hình tâm lý bí hiểm được đặt tên bằng tiếng Hy Lạp.
            recency = max(0.18, 1.0 - idx * 0.12)
            weight = recency * _clamp01(outcome.confidence, 0.5)
            weighted_valence += max(-1.0, min(1.0, outcome.valence)) * weight
            weight_total += weight
            if outcome.kind in {"rejected", "corrected"}:
                negative_weight += weight
            elif outcome.kind in {"ignored", "continued_focus", "scene_shift"}:
                ignored_weight += weight * 0.55

        engagement = 0.0 if weight_total <= 0 else max(-1.0, min(1.0, weighted_valence / weight_total))
        intrusion = _clamp01((negative_weight * 0.42 + ignored_weight * 0.20) / max(1.0, weight_total))
        if self._outcomes:
            latest = self._outcomes[-1]
            if latest.kind == "rejected":
                intrusion = max(intrusion, 0.92)
            elif latest.kind == "corrected":
                intrusion = max(intrusion, 0.62)
            elif latest.kind == "ignored":
                intrusion = max(intrusion, 0.36)
        recent_outcome = self._outcomes[-1].kind if self._outcomes else "none"

        suppressed: list[str] = []
        for kind, ts in list(self._last_negative_by_kind.items()):
            if now - ts <= self.config.negative_kind_cooldown_ms:
                suppressed.append(kind)
            else:
                self._last_negative_by_kind.pop(kind, None)

        same_kind_suppressed = bool(opportunity is not None and opportunity.kind in suppressed)
        body_bias = _clamp01(intrusion * 0.82 + (0.26 if same_kind_suppressed else 0.0))
        cooldown = 1.0 + intrusion * 1.8 + max(0.0, -engagement) * 0.45
        max_words_cap = 14
        mode = "normal"
        if intrusion >= 0.78:
            mode = "recovery"
            max_words_cap = 7
        elif intrusion >= 0.42 or engagement <= -0.20:
            mode = "low_intrusion"
            max_words_cap = 9
        elif engagement >= 0.35:
            mode = "engaged"
            max_words_cap = 14

        reason = (
            f"mode={mode};engagement={engagement:.3f};intrusion={intrusion:.3f};"
            f"recent={recent_outcome};same_kind_suppressed={same_kind_suppressed}"
        )
        return AudienceFeedbackDirective(
            mode=mode,
            engagement_score=engagement,
            intrusion_pressure=intrusion,
            body_only_bias=body_bias,
            cooldown_multiplier=max(1.0, cooldown),
            max_words_cap=max_words_cap,
            suppressed_kinds=tuple(sorted(set(suppressed))),
            recent_outcome=recent_outcome,
            pending_act_id=self.pending_act.act_id if self.pending_act else "",
            reason=reason,
        )

    def adjust_opportunities(
        self,
        opportunities: Sequence[AutonomousOpportunity],
        *,
        now_ms: int | None = None,
    ) -> tuple[AutonomousOpportunity, ...]:
        now = int(now_ms if now_ms is not None else _now_ms())
        directive = self.directive(now_ms=now)
        output: list[AutonomousOpportunity] = []
        for item in opportunities:
            strength = item.strength
            novelty = item.novelty
            if item.kind in directive.suppressed_kinds:
                strength -= 0.18
                novelty -= 0.14
            if directive.recent_outcome == "ignored" and item.kind == "dead_air":
                strength -= 0.12
            if directive.mode == "recovery" and item.kind not in {"new_error", "task_progress"}:
                strength -= 0.16
            if directive.engagement_score >= 0.40 and item.kind in {"task_progress", "return_after_idle"}:
                strength += 0.04
            output.append(
                replace(
                    item,
                    strength=_clamp01(strength),
                    novelty=_clamp01(novelty),
                )
            )
        output.sort(
            key=lambda item: item.strength + item.urgency * 0.25 + item.novelty * 0.15,
            reverse=True,
        )
        return tuple(output)

    def apply_to_permit(
        self,
        permit: SpeakPermit,
        directive: AudienceFeedbackDirective,
        *,
        opportunity: AutonomousOpportunity | None,
    ) -> SpeakPermit:
        if not permit.allowed:
            return permit
        kind = str(getattr(opportunity, "kind", "") or "")
        urgency = float(getattr(opportunity, "urgency", 0.0) or 0.0)
        urgent_exception = kind == "new_error" and urgency >= 0.88
        same_kind_suppressed = kind in set(directive.suppressed_kinds)

        if (directive.intrusion_pressure >= 0.78 or same_kind_suppressed) and not urgent_exception:
            return SpeakPermit(
                allowed=False,
                mode="body_only",
                max_words=0,
                max_duration_ms=0,
                reason="audience_feedback_prefers_silence",
                cooldown_after_ms=0,
                confidence=max(permit.confidence, directive.intrusion_pressure),
            )

        words = max(1, min(int(permit.max_words), int(directive.max_words_cap)))
        if directive.mode == "low_intrusion":
            words = min(words, 9)
        if urgent_exception and directive.mode == "recovery":
            words = min(words, 10)
        ratio = words / max(1.0, float(permit.max_words or words))
        duration_ms = max(650, int(permit.max_duration_ms * max(0.55, ratio)))
        cooldown_ms = max(
            permit.cooldown_after_ms,
            int(permit.cooldown_after_ms * directive.cooldown_multiplier),
        )
        return SpeakPermit(
            allowed=True,
            mode=permit.mode,
            max_words=words,
            max_duration_ms=duration_ms,
            reason=f"{permit.reason}|audience:{directive.mode}",
            cooldown_after_ms=cooldown_ms,
            confidence=permit.confidence,
        )

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        directive = self.directive(now_ms=now_ms)
        return {
            "directive": directive.to_payload(),
            "pending_act": self.pending_act.to_payload() if self.pending_act else None,
            "recent_outcomes": [item.to_payload() for item in self._outcomes],
        }

    def _close_pending(
        self,
        *,
        kind: str,
        valence: float,
        confidence: float,
        reason: str,
        now_ms: int,
    ) -> AudienceOutcome | None:
        pending = self.pending_act
        if pending is None:
            return None
        outcome = AudienceOutcome(
            outcome_id=f"outfb_{uuid.uuid4().hex[:12]}",
            act_id=pending.act_id,
            opportunity_kind=pending.opportunity_kind,
            kind=kind,
            valence=max(-1.0, min(1.0, float(valence))),
            confidence=_clamp01(confidence, 0.5),
            observed_at_ms=int(now_ms),
            reason=reason,
        )
        self._outcomes.append(outcome)
        if kind in {"rejected", "corrected"}:
            self._last_negative_by_kind[pending.opportunity_kind] = int(now_ms)
        self.pending_act = None
        return outcome


__all__ = [
    "AudienceFeedbackConfig",
    "AudienceFeedbackDirective",
    "AudienceOutcome",
    "AutonomousAudienceFeedbackLoop",
    "PendingAutonomousAct",
]
