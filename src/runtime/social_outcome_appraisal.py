from __future__ import annotations

"""Appraisal xã hội dạng giả thuyết, không đóng dấu trạng thái người dùng.

Module này thay các field kiểu ``user_corrected=True`` hoặc
``relation_ruptured=True`` bằng các *pressure/support score*. Một câu có thể vừa
mang correction pressure, vừa có playfulness, vừa chưa đủ chắc để kết luận user
đang khó chịu. Downstream được phép dùng threshold để mở một policy gate, nhưng
không được serialize threshold đó thành sự thật về động cơ hoặc cảm xúc user.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))
    if number != number:
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class SocialHypothesis:
    """Một cách hiểu tạm thời, có provenance và thời hạn ngắn.

    ``label`` mô tả *khả năng* như ``correction_pressure`` hoặc
    ``playful_response``. Nó không được dùng để mint các fact kiểu
    ``user_is_angry`` / ``user_is_manipulative``.
    """

    label: str
    score: float
    evidence: tuple[str, ...] = ()
    provenance: str = "user_feedback_surface"
    scope: str = "current_exchange"
    ttl_turns: int = 2

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = round(clamp01(self.score), 4)
        return data


@dataclass(slots=True)
class SocialOutcomeAppraisal:
    """Phân bố tín hiệu xã hội cho một feedback turn.

    Các score độc lập, không cần cộng thành 1. Điều này giữ được trường hợp một
    câu vừa chọc, vừa sửa, vừa hơi khó chịu. ``confidence`` chỉ nói chất lượng
    appraisal, không nói một hypothesis nào chắc chắn đúng.
    """

    acceptance_support: float = 0.0
    correction_pressure: float = 0.0
    confusion_pressure: float = 0.0
    laughter_signal: float = 0.0
    intrusion_risk: float = 0.0
    soothing_signal: float = 0.0
    relationship_warmth_signal: float = 0.0
    relationship_strain_signal: float = 0.0
    disengagement_risk: float = 0.0
    tone_feedback_pressure: float = 0.0
    interpretation_uncertainty: float = 1.0
    confidence: float = 0.0
    hypotheses: tuple[SocialHypothesis, ...] = ()
    evidence: tuple[str, ...] = ()

    def clamp(self) -> "SocialOutcomeAppraisal":
        for name in (
            "acceptance_support",
            "correction_pressure",
            "confusion_pressure",
            "laughter_signal",
            "intrusion_risk",
            "soothing_signal",
            "relationship_warmth_signal",
            "relationship_strain_signal",
            "disengagement_risk",
            "tone_feedback_pressure",
            "interpretation_uncertainty",
            "confidence",
        ):
            setattr(self, name, clamp01(getattr(self, name, 0.0)))
        return self

    def score(self, name: str, default: float = 0.0) -> float:
        return clamp01(getattr(self, name, default), default)

    def to_dict(self) -> dict[str, Any]:
        self.clamp()
        return {
            "acceptance_support": round(self.acceptance_support, 4),
            "correction_pressure": round(self.correction_pressure, 4),
            "confusion_pressure": round(self.confusion_pressure, 4),
            "laughter_signal": round(self.laughter_signal, 4),
            "intrusion_risk": round(self.intrusion_risk, 4),
            "soothing_signal": round(self.soothing_signal, 4),
            "relationship_warmth_signal": round(self.relationship_warmth_signal, 4),
            "relationship_strain_signal": round(self.relationship_strain_signal, 4),
            "disengagement_risk": round(self.disengagement_risk, 4),
            "tone_feedback_pressure": round(self.tone_feedback_pressure, 4),
            "interpretation_uncertainty": round(self.interpretation_uncertainty, 4),
            "confidence": round(self.confidence, 4),
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_any(cls, value: Any) -> "SocialOutcomeAppraisal":
        if isinstance(value, cls):
            return value.clamp()
        if isinstance(value, Mapping):
            payload = dict(value)
            hypotheses: list[SocialHypothesis] = []
            for item in payload.get("hypotheses", ()) or ():
                if isinstance(item, SocialHypothesis):
                    hypotheses.append(item)
                elif isinstance(item, Mapping):
                    hypotheses.append(SocialHypothesis(
                        label=str(item.get("label", "") or "unknown"),
                        score=clamp01(item.get("score", 0.0)),
                        evidence=tuple(str(x) for x in (item.get("evidence", ()) or ())),
                        provenance=str(item.get("provenance", "user_feedback_surface") or "user_feedback_surface"),
                        scope=str(item.get("scope", "current_exchange") or "current_exchange"),
                        ttl_turns=max(1, int(item.get("ttl_turns", 2) or 2)),
                    ))
            allowed = {
                name for name in cls.__dataclass_fields__
                if name not in {"hypotheses", "evidence"}
            }
            kwargs = {name: payload.get(name, 0.0) for name in allowed if name in payload}
            kwargs["hypotheses"] = tuple(hypotheses)
            kwargs["evidence"] = tuple(str(x) for x in (payload.get("evidence", ()) or ()))
            return cls(**kwargs).clamp()
        return cls()


def social_score(outcome: Any, name: str, default: float = 0.0) -> float:
    """Đọc score mới và hỗ trợ dữ liệu cũ mà không hồi sinh hard claim.

    Mapping legacy chỉ được chuyển thành pressure 0/1 tại ranh giới đọc. Giá trị
    đó không được serialize ngược lại dưới tên ``user_*`` hay ``relation_*``.
    """

    social = None
    if isinstance(outcome, Mapping):
        social = outcome.get("social")
    else:
        social = getattr(outcome, "social", None)
    appraisal = SocialOutcomeAppraisal.from_any(social)
    if hasattr(appraisal, name):
        value = appraisal.score(name, default)
        if value > 0.0 or social is not None:
            return value

    legacy_map = {
        "acceptance_support": "user_accepted",
        "correction_pressure": "user_corrected",
        "confusion_pressure": "user_confused",
        "laughter_signal": "user_laughed",
        "intrusion_risk": "user_felt_intruded",
        "soothing_signal": "user_soothed",
        "relationship_warmth_signal": "relation_improved",
        "relationship_strain_signal": "relation_ruptured",
        "disengagement_risk": "user_ignored",
    }
    legacy_name = legacy_map.get(name)
    if not legacy_name:
        return clamp01(default)
    if isinstance(outcome, Mapping):
        raw = outcome.get(legacy_name, None)
    else:
        raw = getattr(outcome, legacy_name, None)
    if raw is True:
        return 1.0
    if raw is False:
        return 0.0
    return clamp01(default)


__all__ = [
    "SocialHypothesis",
    "SocialOutcomeAppraisal",
    "clamp01",
    "social_score",
]
