from __future__ import annotations

"""Projection tương thích cho Dual-Axis Repair.

Suy luận xã hội không còn nằm trong file này. Nguồn duy nhất là
:mod:`runtime.social_appraisal`. File này chỉ:

1. chiếu ``SocialAppraisalSnapshot`` sang API repair cũ để các module chưa kịp
   migrate không vỡ;
2. áp policy kỹ thuật lên Ti/Affect/output;
3. tuyệt đối không tự chạy regex hoặc tự đặt threshold xã hội riêng.

Nhờ vậy, downstream không còn tám phòng ban cùng đoán user đang sửa hay đang
chọc. Chúng chỉ đọc cùng một snapshot, một chuyện nghe rất bình thường nhưng
phần mềm phải mất kha khá vòng tiến hóa mới chịu làm.
"""

from dataclasses import dataclass, replace
from typing import Any

from runtime.social_appraisal import (
    SocialAppraisalEngine,
    SocialAppraisalSnapshot,
    clamp01,
    content_tokens,
    ensure_social_appraisal_engine,
    normalize_vi,
)


@dataclass(frozen=True, slots=True)
class RepairAppraisal:
    """Compatibility view, không phải classifier thứ hai."""

    social_snapshot: SocialAppraisalSnapshot

    @classmethod
    def empty(cls) -> "RepairAppraisal":
        return cls(SocialAppraisalSnapshot())

    @property
    def active(self) -> bool:
        return self.social_snapshot.active

    @property
    def mismatch_score(self) -> float:
        return self.social_snapshot.claim.contest

    @property
    def correction_score(self) -> float:
        return self.social_snapshot.correction.value

    @property
    def playful_score(self) -> float:
        return self.social_snapshot.playful.value

    @property
    def affectionate_score(self) -> float:
        return self.social_snapshot.affection.value

    @property
    def irritation_score(self) -> float:
        return self.social_snapshot.irritation.value

    @property
    def boundary_score(self) -> float:
        return self.social_snapshot.boundary.value

    @property
    def engagement_score(self) -> float:
        return self.social_snapshot.engagement.value

    @property
    def interpretation_uncertainty(self) -> float:
        return self.social_snapshot.claim.uncertainty

    @property
    def confidence(self) -> float:
        return max(
            self.social_snapshot.correction.confidence,
            self.social_snapshot.playful.confidence,
            self.social_snapshot.claim.contest,
        )

    @property
    def response_strategy(self) -> str:
        # Tên cũ chỉ còn là alias của operational posture.
        return self.social_snapshot.claim_policy.response_posture

    @property
    def previous_claim_excerpt(self) -> str:
        return self.social_snapshot.claim.previous_claim_excerpt

    @property
    def user_contrast_excerpt(self) -> str:
        return self.social_snapshot.claim.user_contrast_excerpt

    @property
    def contested_terms(self) -> tuple[str, ...]:
        return self.social_snapshot.claim.contested_terms

    @property
    def evidence(self) -> tuple[str, ...]:
        return tuple(
            item.note or f"{item.source}:{item.signal}"
            for item in self.social_snapshot.claim.provenance
        )

    @property
    def is_playful_repair(self) -> bool:
        return self.social_snapshot.is_playful_repair

    @property
    def candidate_count_hint(self) -> int:
        return self.social_snapshot.claim_policy.candidate_count_hint

    @property
    def blocks_assistant_fact_commit(self) -> bool:
        return not self.social_snapshot.claim_policy.memory_write_allowed

    @property
    def claim_authority_multiplier(self) -> float:
        return self.social_snapshot.claim_policy.authority_multiplier

    @property
    def suppress_previous_claim_for_turn(self) -> bool:
        return self.social_snapshot.claim_policy.suppress_for_current_turn

    # Alias migration một chiều. Không serialize tên này và không dùng nó làm
    # verdict xã hội. Một số module cũ vẫn đọc field, nên bỏ ngay sẽ làm runtime
    # vỡ chỉ để grep nhìn đẹp, một chiến thắng khá vô dụng.
    @property
    def previous_claim_should_be_retracted(self) -> bool:
        return self.suppress_previous_claim_for_turn

    def to_dict(self) -> dict[str, Any]:
        data = self.social_snapshot.to_dict()
        data["compatibility_view"] = "dual_axis_repair"
        return data

    def to_prompt_context(self) -> str:
        return self.social_snapshot.to_prompt_context()

    def history_invalidation_note(self) -> str:
        terms = ", ".join(self.contested_terms[:5]) or "previous claim"
        return (
            "Previous assistant claim has reduced authority and must not be used as fact "
            f"(authority={self.claim_authority_multiplier:.2f}; terms={terms}). "
            "Preserve relational tone while correcting epistemic overreach."
        )


class DualAxisRepairAppraiser:
    """Adapter mỏng sang Unified Social Appraisal Engine."""

    def __init__(self, engine: SocialAppraisalEngine | None = None) -> None:
        self.engine = engine or SocialAppraisalEngine()

    def appraise(
        self,
        *,
        user_text: str,
        previous_assistant_text: str,
        previous_user_text: str = "",
        affect_signal: Any = None,
        relational_feedback: Any = None,
        phase: str = "final",
    ) -> RepairAppraisal:
        snapshot = self.engine.appraise(
            user_text=user_text,
            previous_assistant_text=previous_assistant_text,
            previous_user_text=previous_user_text,
            affect_signal=affect_signal,
            relational_feedback=relational_feedback,
            phase=phase,
        )
        return RepairAppraisal(snapshot)

    @classmethod
    def for_host(cls, host: Any) -> "DualAxisRepairAppraiser":
        return cls(ensure_social_appraisal_engine(host))


def calibrate_affect_for_repair(signal: Any, appraisal: RepairAppraisal) -> Any:
    """Hiệu chỉnh affect bằng snapshot chung, không tự suy luận lại."""

    if signal is None or appraisal is None or not appraisal.active:
        return signal
    snapshot = appraisal.social_snapshot
    try:
        changes: dict[str, Any] = {
            "correction": max(clamp01(getattr(signal, "correction", 0.0)), snapshot.correction.value),
            "playfulness": max(clamp01(getattr(signal, "playfulness", 0.0)), snapshot.playful.value),
        }
        mundane_irony = any(item.note == "mundane_ironic_understatement" for item in snapshot.claim.provenance)
        if mundane_irony and snapshot.affection.value < 0.35:
            # Hạ đúng ambiguity của từ "nhớ", không khóa warmth hay relationship.
            changes["intimacy"] = min(clamp01(getattr(signal, "intimacy", 0.0)), 0.22)
            changes["attachment"] = min(clamp01(getattr(signal, "attachment", 0.0)), 0.18)
            changes["attachment_bid"] = min(clamp01(getattr(signal, "attachment_bid", 0.0)), 0.18)
        elif snapshot.affection.value >= 0.35:
            changes["intimacy"] = max(clamp01(getattr(signal, "intimacy", 0.0)), snapshot.affection.value)
            changes["attachment"] = max(
                clamp01(getattr(signal, "attachment", 0.0)),
                snapshot.affection.value * 0.72,
            )
        evidence = tuple(getattr(signal, "evidence", ()) or ())
        changes["evidence"] = tuple(dict.fromkeys((*evidence, "adjust:unified_social_appraisal")))
        return replace(signal, **changes)
    except Exception:
        return signal


def apply_repair_appraisal_to_ti_report(report: Any, appraisal: RepairAppraisal) -> Any:
    """Chiếu policy lên Ti; không tạo hard intent verdict mới."""

    if report is None or appraisal is None or not appraisal.active:
        return report
    snapshot = appraisal.social_snapshot
    policy = snapshot.claim_policy
    thresholds = snapshot.thresholds

    if snapshot.is_playful_repair:
        mode = "chat_playful_repair"
        reason = "Claim trước bị hạ authority nhưng nhịp quan hệ có khả năng playful; tự sửa có duyên."
    elif snapshot.boundary.value >= thresholds.boundary_high:
        mode = "chat_boundary_repair"
        reason = "Claim trước bị contest cùng boundary pressure; sửa gọn và không kéo gần thêm."
    elif snapshot.affection.value >= 0.42:
        mode = "chat_relational_repair"
        reason = "Claim trước bị contest trong một nhịp gần gũi; giữ warmth nhưng không bảo vệ suy diễn."
    else:
        mode = "chat_repair"
        reason = "Claim trước có authority thấp; ưu tiên sửa frame trước khi giải thích tiếp."

    context = str(getattr(report, "prompt_context", "") or "")
    context = f"{context}\n\n{snapshot.to_prompt_context()}".strip()
    hard_rules = tuple(getattr(report, "hard_rules", ()) or ())
    rules = [
        "Không dùng claim có authority thấp như fact hoặc memory grounding.",
        "Sửa epistemic overreach nhưng không làm phẳng playful/affectionate tone.",
    ]
    if policy.suppress_for_current_turn:
        rules.append("Không được mở rộng claim trước trong lượt hiện tại.")
    hard_rules = tuple(dict.fromkeys((*hard_rules, *rules)))
    evidence = tuple(getattr(report, "evidence", ()) or ())
    evidence = tuple(dict.fromkeys((*evidence, "unified_social_appraisal", policy.reason)))
    try:
        return replace(
            report,
            mode=mode,
            reason=reason,
            prompt_context=context,
            hard_rules=hard_rules,
            evidence=evidence,
            animation_hint="stand",
        )
    except Exception:
        return report


_RETRACTION_MARKERS = (
    "toi hieu sai", "toi doan qua", "toi tu keo", "toi tu bia", "toi nham", "toi lo",
    "do toi suy dien", "khong phai dieu ban noi", "khong phai y ban", "rut lai",
    "toi vua phong", "toi vua tu dung", "toi keo qua tay",
)


def output_defends_retracted_claim(text: str, appraisal: RepairAppraisal) -> bool:
    """Tên hàm giữ để tương thích; thực chất kiểm tra claim bị suppress hiện tại."""

    if not appraisal.suppress_previous_claim_for_turn:
        return False
    norm = normalize_vi(text)
    if not norm:
        return True
    mentions_contested = any(
        term in norm.split() or term in norm
        for term in appraisal.contested_terms
        if len(term) >= 3
    )
    if not mentions_contested:
        return not any(marker in norm for marker in _RETRACTION_MARKERS)
    return not any(marker in norm for marker in _RETRACTION_MARKERS)


def build_safe_repair_text(appraisal: RepairAppraisal) -> str:
    claim_terms = ", ".join(appraisal.contested_terms[:3])
    claim_label = claim_terms or "đoạn vừa rồi"
    contrast = appraisal.user_contrast_excerpt.strip()
    snapshot = appraisal.social_snapshot
    if snapshot.is_playful_repair:
        if contrast:
            return f"Ừ, {claim_label} là tôi tự kéo vào. {contrast}; tôi diễn giải quá tay rồi."
        return f"Ừ, {claim_label} là tôi tự dựng thêm. bạn đang chọc đúng chỗ tôi vừa suy diễn quá tay rồi."
    if snapshot.boundary.value >= snapshot.thresholds.boundary_high:
        return f"Tôi hiểu sai và bỏ phần {claim_label}. Tôi sẽ không tiếp tục đẩy suy diễn đó nữa."
    if snapshot.irritation.value >= snapshot.thresholds.irritation_high:
        return f"Tôi hiểu sai: phần {claim_label} là suy diễn của tôi, không phải điều bạn nói."
    if contrast:
        return f"Tôi kéo {claim_label} vào sai chỗ. {contrast}; tôi hiểu quá tay rồi."
    return f"Tôi hiểu sai và bỏ phần {claim_label}; đó là suy diễn của tôi, không phải dữ kiện từ bạn."


def apply_repair_output_guard(decision: Any, appraisal: RepairAppraisal) -> Any:
    """Áp ClaimPolicy lên output/memory commit, không tái diễn giải user."""

    if decision is None or appraisal is None or not appraisal.active:
        return decision
    snapshot = appraisal.social_snapshot
    policy = snapshot.claim_policy
    tags = tuple(getattr(decision, "reasoning_tags", ()) or ())
    extra_tags = ["unified_social_appraisal", policy.response_posture]
    if policy.candidate_count_hint >= 2:
        extra_tags.append("social_interpretation_uncertain")
    if not policy.memory_write_allowed:
        try:
            decision.extracted_fact = ""
        except Exception:
            pass
        extra_tags.append("assistant_claim_memory_blocked")
    try:
        decision.reasoning_tags = tuple(dict.fromkeys((*tags, *extra_tags)))
    except Exception:
        pass

    if output_defends_retracted_claim(str(getattr(decision, "text", "") or ""), appraisal):
        try:
            decision.text = build_safe_repair_text(appraisal)
            decision.should_speak = True
            decision.confidence = max(0.56, clamp01(getattr(decision, "confidence", 0.0)))
            decision.parse_mode = "unified_social_appraisal_guard"
            trace = str(getattr(decision, "debug_trace", "") or "").strip()
            marker = "social_appraisal:blocked_defense_of_suppressed_claim"
            decision.debug_trace = " | ".join(part for part in (trace, marker) if part)
        except Exception:
            pass
    return decision


__all__ = [
    "DualAxisRepairAppraiser",
    "RepairAppraisal",
    "apply_repair_appraisal_to_ti_report",
    "calibrate_affect_for_repair",
    "apply_repair_output_guard",
    "build_safe_repair_text",
    "content_tokens",
    "normalize_vi",
    "output_defends_retracted_claim",
]
