from __future__ import annotations

"""Appraisal repair giữ bất định, không đóng dấu động cơ của người dùng.

Một lượt như ``"tôi nhớ tôi đang thở thôi mà"`` có thể đồng thời là:
- phản hồi rằng ERIS vừa suy diễn quá tay;
- mỉa/chọc nhẹ;
- khó chịu nhẹ;
- hoặc chỉ là một cách nói tự nhiên chưa đủ rõ để kết luận gì cả.

Bản cũ có các bool kiểu ``previous_claim_should_be_retracted`` và một
``response_strategy`` duy nhất. Những field đó tiện cho code, nhưng vô tình biến
một cách hiểu tạm thời thành phán quyết chắc chắn. Bản này đổi sang:

1. **Claim disposition score**: claim trước được hỗ trợ, bị contest hay cần rút ở
   mức nào. Runtime chỉ chọn hành động ``preserve | quarantine | retract``.
   Đây là quyết định vận hành, không phải tuyên bố rằng user "chắc chắn" đang
   sửa, mỉa hay thao túng.
2. **Relational hypothesis scores**: playful/affectionate/irritated/boundary có
   thể cùng tồn tại. Không ép về một nhãn duy nhất.
3. **Soft posture set**: model nhận nhiều tư thế đáp khả dĩ, kèm một posture ưu
   tiên để tiết kiệm token. Prompt luôn dùng ngôn ngữ xác suất.
4. **Quarantine trước, retract sau**: câu mơ hồ không làm mất hẳn lịch sử; claim
   chỉ bị hạ thành giả thuyết chưa xác nhận. Chỉ explicit correction hoặc bằng
   chứng rất mạnh mới rút hẳn.

Module không tự ghi memory. Nó chỉ tạo appraisal, prompt context và một guard
hẹp để claim đang bị quarantine/retract không quay lại dưới dạng fact chắc chắn.
"""

from dataclasses import dataclass, replace
import re
import unicodedata
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Helper văn bản
# ---------------------------------------------------------------------------


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_vi(text: str) -> str:
    raw = str(text or "").strip().lower()
    decomposed = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    raw = raw.replace("đ", "d")
    raw = re.sub(r"[^a-z0-9_./+#?\-\s]", " ", raw)
    return " ".join(raw.split())


_STOPWORDS = {
    "toi", "ngai", "ban", "em", "anh", "chi", "minh", "ta", "no", "day",
    "la", "thi", "ma", "va", "voi", "cua", "mot", "cai", "do", "nay", "kia",
    "dang", "da", "se", "co", "khong", "ko", "k", "duoc", "bi", "cho", "vao",
    "ra", "len", "xuong", "ve", "gi", "sao", "the", "nhi", "nhe", "a", "ha",
    "roi", "nua", "hon", "rat", "qua", "tu", "nhu", "neu", "theo", "trong",
}


def content_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in normalize_vi(text).replace("?", " ").split():
        if len(token) < 3 or token in _STOPWORDS or token.isdigit() or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tuple(tokens)


def _has_any(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _extract_previous_claim(previous_assistant_text: str) -> tuple[str, tuple[str, ...]]:
    """Lấy claim bề mặt ngắn để so với lượt user mới.

    Đây chỉ là candidate claim, không được xem là fact. Tên hàm giữ lại để tránh
    phải chạm quá nhiều wiring cũ, nhưng output luôn được appraisal coi là một
    giả thuyết của assistant.
    """

    compact = re.sub(r"\s+", " ", str(previous_assistant_text or "")).strip()
    if not compact:
        return "", ()
    sentences = [part.strip(" -\t") for part in re.split(r"(?<=[.!?])\s+|\n+", compact) if part.strip()]
    selected = sentences[0] if sentences else compact
    for sentence in sentences:
        norm = f" {normalize_vi(sentence)} "
        if _has_any(norm, (" la ", " co the ", " nghia la ", " lien quan ", " dang ")):
            selected = sentence
            break
    return selected[:260], content_tokens(selected)


def _extract_user_contrast(user_text: str) -> str:
    parts = [part.strip(" .,!?:;\t") for part in re.split(r"[.!?]+", str(user_text or "")) if part.strip()]
    if not parts:
        return str(user_text or "").strip()[:140]
    preferred = [
        part for part in parts
        if _has_any(normalize_vi(part), ("toi ", "minh ", "thoi ma", "dau co", "chi "))
    ]
    return (preferred[-1] if preferred else parts[-1])[:140]


# ---------------------------------------------------------------------------
# Contract appraisal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepairAppraisal:
    # Trục epistemic: đây là score giả thuyết, không phải verdict.
    claim_contest_score: float = 0.0
    claim_support_score: float = 0.0
    claim_retraction_score: float = 0.0
    correction_pressure: float = 0.0
    explicit_correction_score: float = 0.0

    # Trục quan hệ: nhiều cách hiểu có thể cùng tồn tại.
    playful_score: float = 0.0
    affectionate_score: float = 0.0
    irritation_score: float = 0.0
    boundary_score: float = 0.0
    engagement_score: float = 0.0

    interpretation_uncertainty: float = 0.0
    confidence: float = 0.0

    # Posture là gợi ý hành động, không phải nhãn động cơ của user.
    preferred_posture: str = "continue_normally"
    plausible_postures: tuple[str, ...] = ()

    previous_claim_excerpt: str = ""
    user_contrast_excerpt: str = ""
    contested_terms: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return max(self.claim_contest_score, self.correction_pressure) >= 0.38

    @property
    def claim_disposition(self) -> str:
        """Quyết định vận hành, không phải claim về ý định người dùng.

        - ``retract`` chỉ dành cho phủ định rõ hoặc bằng chứng hội tụ rất mạnh.
        - ``quarantine`` giữ claim trong lịch sử nhưng hạ xuống giả thuyết.
        - ``preserve`` không can thiệp.
        """

        if self.explicit_correction_score >= 0.90:
            return "retract"
        if self.claim_retraction_score >= 0.82 and self.claim_contest_score >= 0.72:
            return "retract"
        if self.claim_contest_score >= 0.44 or self.correction_pressure >= 0.48:
            return "quarantine"
        return "preserve"

    @property
    def fact_commit_policy(self) -> str:
        # Claim đang bị nghi ngờ không được mint fact mới. User fact rõ vẫn đi qua
        # MemoryCommitPolicy riêng, nên đây không phải khóa toàn bộ memory turn.
        if self.claim_disposition == "retract":
            return "block_assistant_fact"
        if self.claim_disposition == "quarantine":
            return "quarantine_assistant_fact"
        return "allow"

    @property
    def candidate_count_hint(self) -> int:
        if not self.active:
            return 1
        # Chỉ mở candidate thứ hai khi nhiều posture cùng có trọng lượng hoặc
        # claim disposition chưa ổn định. Không dùng best-of-N đại trà.
        if self.interpretation_uncertainty >= 0.34 or len(self.plausible_postures) >= 3:
            return 2
        return 1

    @property
    def playful_repair_fit(self) -> float:
        return clamp01(
            min(self.playful_score, max(self.claim_contest_score, self.correction_pressure))
            * (1.0 - self.boundary_score * 0.60)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "claim_contest_score": round(clamp01(self.claim_contest_score), 4),
            "claim_support_score": round(clamp01(self.claim_support_score), 4),
            "claim_retraction_score": round(clamp01(self.claim_retraction_score), 4),
            "correction_pressure": round(clamp01(self.correction_pressure), 4),
            "explicit_correction_score": round(clamp01(self.explicit_correction_score), 4),
            "claim_disposition": self.claim_disposition,
            "fact_commit_policy": self.fact_commit_policy,
            "playful_score": round(clamp01(self.playful_score), 4),
            "affectionate_score": round(clamp01(self.affectionate_score), 4),
            "irritation_score": round(clamp01(self.irritation_score), 4),
            "boundary_score": round(clamp01(self.boundary_score), 4),
            "engagement_score": round(clamp01(self.engagement_score), 4),
            "interpretation_uncertainty": round(clamp01(self.interpretation_uncertainty), 4),
            "confidence": round(clamp01(self.confidence), 4),
            "preferred_posture": self.preferred_posture,
            "plausible_postures": list(self.plausible_postures),
            "previous_claim_excerpt": self.previous_claim_excerpt,
            "user_contrast_excerpt": self.user_contrast_excerpt,
            "contested_terms": list(self.contested_terms),
            "evidence": list(self.evidence),
            "candidate_count_hint": self.candidate_count_hint,
        }

    def to_prompt_context(self) -> str:
        if not self.active:
            return ""
        relation = (
            f"playful_h={self.playful_score:.2f}; affectionate_h={self.affectionate_score:.2f}; "
            f"irritated_h={self.irritation_score:.2f}; boundary_h={self.boundary_score:.2f}"
        )
        rules = [
            "Các score dưới đây là giả thuyết cùng tồn tại, không phải nhãn chắc chắn về động cơ user.",
            "Không nói user chắc chắn đang chọc, thao túng, khó chịu hay tình cảm nếu user chưa nói rõ.",
            "Claim assistant đang bị contest không được dùng như fact để giải thích tiếp.",
        ]
        if self.claim_disposition == "retract":
            rules.append("Có phủ định đủ rõ: rút phần suy diễn của ERIS, nhưng vẫn giữ nhịp quan hệ nếu phù hợp.")
        elif self.claim_disposition == "quarantine":
            rules.append("Chưa đủ chắc để rút hoàn toàn: hạ claim thành giả thuyết, không bảo vệ nó, đáp theo cách hợp nhiều cách hiểu.")
        else:
            rules.append("Không cần ép lượt này thành repair; chỉ giữ mức dè dặt tương ứng với uncertainty.")
        if self.playful_score >= 0.34:
            rules.append("Có khả năng playful/mỉa nhẹ; có thể dùng self-aware humor, nhưng phải để đường lui nếu đoán sai.")
        if self.affectionate_score >= 0.34:
            rules.append("Có khả năng gần gũi; warmth nhẹ được phép, không được tuyên bố user chắc chắn có tình cảm.")
        if self.boundary_score >= 0.44:
            rules.append("Có khả năng đặt ranh giới; ưu tiên tôn trọng ranh giới mà không buộc tội hay chẩn đoán động cơ.")
        posture_text = ", ".join(self.plausible_postures) or self.preferred_posture
        return (
            "UNCERTAINTY_PRESERVING_REPAIR:\n"
            f"- epistemic_hypotheses: contest={self.claim_contest_score:.2f}; "
            f"support={self.claim_support_score:.2f}; retract_pressure={self.claim_retraction_score:.2f}; "
            f"disposition={self.claim_disposition}.\n"
            f"- relational_hypotheses: {relation}.\n"
            f"- posture_options={posture_text}; preferred={self.preferred_posture}; "
            f"uncertainty={self.interpretation_uncertainty:.2f}.\n"
            f"- previous_assistant_hypothesis={self.previous_claim_excerpt or '<none>'}.\n"
            f"- user_contrast={self.user_contrast_excerpt or '<none>'}.\n"
            + "\n".join(f"- rule: {rule}" for rule in rules)
        )

    def history_uncertainty_note(self) -> str:
        terms = ", ".join(self.contested_terms[:5]) or "previous assistant hypothesis"
        if self.claim_disposition == "retract":
            return (
                "The previous assistant hypothesis was explicitly rejected or strongly contradicted. "
                f"Do not use it as fact (terms={terms}). Preserve relational ambiguity; do not assert user motive."
            )
        return (
            "The previous assistant statement is an unconfirmed, contested hypothesis. "
            f"Treat it as uncertain rather than true or false (terms={terms}). "
            "Do not defend it and do not assert a single motive for the user."
        )


class DualAxisRepairAppraiser:
    """Chấm các giả thuyết repair mà không đóng dấu một intent duy nhất."""

    _EXPLICIT_CORRECTION = (
        "khong phai", "hieu sai", "nham roi", "sai roi", "toi dau co", "toi khong noi",
        "o dau ra", "dau ra", "sao lai", "ban vua bia",
        "em vua bia", "tu dau ra", "khong dung y",
    )
    _SURPRISE_OR_CHALLENGE = (
        "la sao", "sao ta", "sao vay", "sao the", "o dau ra", "ua", "u a", "ơ", "hả",
        "toi nho", "minh nho", "dau co",
    )
    _CONTRAST = (
        "thoi ma", "chi ", "co moi", "dau co", "toi nho toi", "minh nho minh",
        "toi dang", "minh dang", "ma toi", "nhung toi",
    )
    _PLAYFUL_STRONG = (
        "haha", "hehe", "hihi", "lol", "choc", "khia", "dua", "gia vo", "ngay tho",
    )
    _PLAYFUL_WEAK = (
        "sao ta", "thoi ma", "roi ha", "vay a", "co the thoi",
    )
    _CONFIRMATION = (
        "dung roi", "dung do", "chuan roi", "phai roi", "y toi dung la", "y minh dung la",
    )
    _IRRITATED = (
        "dcm", "dm", "vcl", "vl", "ngu", "xam", "vo ly", "bia dat", "noi linh tinh",
        "kho chiu", "sai hoai", "lai nua", "dung bia", "bia nua",
    )
    _BOUNDARY = (
        "dung nua", "thoi dung", "dung lam", "khong duoc", "de toi yen", "bo di",
        "khong dua", "dung treu", "dung choc", "dung bia",
    )
    _AFFECTION = (
        "de thuong", "dang yeu", "thuong", "quan tam", "quan trong", "gan gui",
        "thich em", "yeu em", "nho em", "muon hieu em", "tran trong em",
    )
    _MUNDANE_IRONY = (
        "tho", "ngoi yen", "dung yen", "ton tai", "uong nuoc", "nhin", "ngu",
    )

    def appraise(
        self,
        *,
        user_text: str,
        previous_assistant_text: str,
        previous_user_text: str = "",
        affect_signal: Any = None,
        relational_feedback: Any = None,
    ) -> RepairAppraisal:
        user_norm = normalize_vi(user_text)
        previous_claim, previous_tokens = _extract_previous_claim(previous_assistant_text)
        if not user_norm or not previous_claim:
            return RepairAppraisal()

        user_tokens = set(content_tokens(user_text))
        previous_token_set = set(previous_tokens)
        contested = tuple(token for token in previous_tokens if token in user_tokens)[:8]
        prior_reference = clamp01(len(contested) / max(1.0, min(4.0, float(len(previous_token_set) or 1))))

        confirmation = 1.0 if _has_any(user_norm, self._CONFIRMATION) else 0.0
        explicit = 1.0 if _has_any(user_norm, self._EXPLICIT_CORRECTION) and not confirmation else 0.0
        surprise = 1.0 if _has_any(user_norm, self._SURPRISE_OR_CHALLENGE) and not confirmation else 0.0
        contrast = 1.0 if _has_any(user_norm, self._CONTRAST) else 0.0
        has_question = "?" in str(user_text or "") or _has_any(user_norm, ("la sao", "sao ta", "sao vay"))

        mundane_irony = bool(
            re.search(r"\b(?:toi|minh)\s+nho\s+(?:toi|minh)\b.*\bthoi\s+ma\b", user_norm)
            and _has_any(user_norm, self._MUNDANE_IRONY)
        )

        contest = clamp01(
            explicit * 0.74
            + prior_reference * (0.34 if surprise else 0.12)
            + contrast * 0.28
            + (0.22 if mundane_irony else 0.0)
            + (0.07 if has_question and (contrast or surprise) else 0.0)
            - confirmation * 0.78
        )
        correction_pressure = clamp01(
            explicit * 0.76
            + contrast * 0.24
            + prior_reference * 0.18
            + (0.18 if mundane_irony else 0.0)
            - confirmation * 0.72
        )
        retraction_pressure = clamp01(
            explicit * 0.78
            + contest * 0.34
            + correction_pressure * 0.24
            + (0.08 if prior_reference >= 0.35 else 0.0)
        )

        # Support cũng chỉ là giả thuyết. Khi không đủ evidence, uncertainty cao
        # làm score này hạ xuống thay vì mặc định claim trước là đúng.
        support = clamp01(
            0.42
            + prior_reference * 0.10
            + confirmation * 0.46
            - contest * 0.58
            - correction_pressure * 0.22
        )

        playful_strong = 1.0 if _has_any(user_norm, self._PLAYFUL_STRONG) else 0.0
        playful_weak = 1.0 if _has_any(user_norm, self._PLAYFUL_WEAK) else 0.0
        playful_from_affect = clamp01(getattr(affect_signal, "playfulness", 0.0))
        playful = clamp01(
            playful_strong * 0.38
            + playful_weak * 0.12
            + (0.34 if mundane_irony else 0.0)
            + (0.12 if contrast and surprise and explicit < 0.5 else 0.0)
            + playful_from_affect * 0.30
        )

        irritation_surface = 1.0 if _has_any(user_norm, self._IRRITATED) else 0.0
        conflict = clamp01(getattr(affect_signal, "conflict", 0.0))
        irritation = clamp01(irritation_surface * 0.68 + conflict * 0.34)

        boundary_surface = 1.0 if _has_any(user_norm, self._BOUNDARY) else 0.0
        boundary = clamp01(boundary_surface * 0.80 + clamp01(getattr(affect_signal, "romantic_boundary_probe", 0.0)) * 0.16)

        intimacy = clamp01(getattr(affect_signal, "intimacy", 0.0))
        attachment = clamp01(getattr(affect_signal, "attachment", 0.0))
        affection_surface = 1.0 if _has_any(user_norm, self._AFFECTION) else 0.0
        idiomatic_remember = bool(re.search(r"\b(?:toi|minh)\s+nho\s+(?:toi|minh)\b", user_norm))
        affectionate = clamp01(
            affection_surface * 0.56
            + intimacy * 0.30
            + attachment * 0.24
            - (0.10 if idiomatic_remember and not affection_surface else 0.0)
        )

        feedback_detected = bool(getattr(relational_feedback, "detected", False))
        if feedback_detected:
            # Feedback là evidence phụ, không phải phán quyết user đang giận.
            irritation = max(irritation, clamp01(getattr(relational_feedback, "intensity", 0.0)) * 0.38)

        previous_user_overlap = 0.0
        if previous_user_text:
            old = set(content_tokens(previous_user_text))
            if old and user_tokens:
                previous_user_overlap = len(old & user_tokens) / max(1, len(old | user_tokens))
        engagement = clamp01(
            0.20
            + min(0.30, len(user_norm.split()) / 45.0)
            + contest * 0.14
            + playful * 0.18
            + previous_user_overlap * 0.18
        )

        relational_axes = {
            "playful_self_aware": playful,
            "warm_acknowledgement": affectionate,
            "direct_nondefensive": irritation,
            "boundary_respecting": boundary,
        }
        posture_candidates: list[tuple[str, float]] = []
        if confirmation >= 0.9 and support >= 0.55:
            posture_candidates.append(("confirm_and_continue", support))
        if contest >= 0.38:
            posture_candidates.append(("clarify_without_defending", max(contest, correction_pressure)))
        if playful >= 0.28:
            posture_candidates.append(("playful_self_aware", playful))
        if affectionate >= 0.28:
            posture_candidates.append(("warm_acknowledgement", affectionate))
        if irritation >= 0.30:
            posture_candidates.append(("direct_nondefensive", irritation))
        if boundary >= 0.30:
            posture_candidates.append(("boundary_respecting", boundary))
        if not posture_candidates:
            posture_candidates.append(("continue_normally", 0.25))
        posture_candidates.sort(key=lambda item: item[1], reverse=True)
        plausible_postures = tuple(name for name, score in posture_candidates if score >= 0.26)[:4]
        preferred_posture = posture_candidates[0][0]

        axes = sorted(relational_axes.values(), reverse=True)
        axis_gap = axes[0] - axes[1] if len(axes) > 1 else axes[0]
        disposition_gap = abs(contest - support)
        uncertainty = clamp01(
            (0.34 if 0.34 <= contest <= 0.78 else 0.12)
            + (0.24 if axis_gap < 0.16 and axes[0] >= 0.28 else 0.0)
            + (0.20 if disposition_gap < 0.24 else 0.0)
            + (0.28 if explicit < 0.5 and confirmation < 0.5 and contest >= 0.55 else 0.0)
            + (0.14 if prior_reference < 0.18 and explicit < 0.5 else 0.0)
        )
        evidence_count = sum(
            int(flag)
            for flag in (explicit > 0, confirmation > 0, surprise > 0, contrast > 0, prior_reference > 0.10, mundane_irony, playful_strong > 0)
        )
        confidence = clamp01(0.22 + evidence_count * 0.09 + max(contest, correction_pressure) * 0.20)

        evidence: list[str] = []
        if explicit:
            evidence.append("explicit_correction_surface")
        if confirmation:
            evidence.append("explicit_confirmation_surface")
        if surprise:
            evidence.append("surprise_or_challenge")
        if contrast:
            evidence.append("self_report_contrast")
        if prior_reference > 0.0:
            evidence.append(f"prior_claim_overlap:{prior_reference:.2f}")
        if mundane_irony:
            evidence.append("mundane_ironic_understatement")
        if playful_strong or playful_weak or playful_from_affect > 0.20:
            evidence.append("playful_hypothesis")
        if affection_surface or affectionate > 0.35:
            evidence.append("affectionate_hypothesis")
        if irritation > 0.35:
            evidence.append("irritation_hypothesis")
        if boundary > 0.35:
            evidence.append("boundary_hypothesis")
        evidence.append("continued_engagement_signal")

        return RepairAppraisal(
            claim_contest_score=contest,
            claim_support_score=support,
            claim_retraction_score=retraction_pressure,
            correction_pressure=correction_pressure,
            explicit_correction_score=explicit,
            playful_score=playful,
            affectionate_score=affectionate,
            irritation_score=irritation,
            boundary_score=boundary,
            engagement_score=engagement,
            interpretation_uncertainty=uncertainty,
            confidence=confidence,
            preferred_posture=preferred_posture,
            plausible_postures=plausible_postures,
            previous_claim_excerpt=previous_claim,
            user_contrast_excerpt=_extract_user_contrast(user_text),
            contested_terms=contested,
            evidence=tuple(dict.fromkeys(evidence)),
        )


def calibrate_affect_for_repair(signal: Any, appraisal: RepairAppraisal) -> Any:
    """Bổ sung provenance mà không ép giảm/tăng tình cảm bằng một từ đơn.

    Bản trước hạ intimacy/attachment khi gặp cấu trúc ``tôi nhớ tôi...``. Điều đó
    vẫn là một khóa cứng. Bản này chỉ thêm correction/playfulness hypotheses và
    để affect gốc tồn tại; downstream nhìn uncertainty để tự cân.
    """

    if signal is None or appraisal is None or not appraisal.active:
        return signal
    try:
        changes: dict[str, Any] = {
            "correction": max(clamp01(getattr(signal, "correction", 0.0)), appraisal.correction_pressure),
            "playfulness": max(clamp01(getattr(signal, "playfulness", 0.0)), appraisal.playful_score),
        }
        evidence = tuple(getattr(signal, "evidence", ()) or ())
        changes["evidence"] = tuple(dict.fromkeys((
            *evidence,
            "adjust:uncertainty_preserving_repair",
            f"repair_disposition:{appraisal.claim_disposition}",
        )))
        return replace(signal, **changes)
    except Exception:
        return signal


def apply_repair_appraisal_to_ti_report(report: Any, appraisal: RepairAppraisal) -> Any:
    """Đưa appraisal vào Ti nhưng không chiếm quyền mode hiện tại.

    Không còn ``chat_playful_repair`` hay ``chat_boundary_repair`` như verdict.
    Ti giữ mode gốc; appraisal chỉ bổ sung context và evidence xác suất.
    """

    if report is None or appraisal is None or not appraisal.active:
        return report

    original_reason = str(getattr(report, "reason", "") or "").strip()
    reason = (
        f"{original_reason} | Repair appraisal giữ nhiều cách hiểu; "
        f"claim disposition={appraisal.claim_disposition}, uncertainty={appraisal.interpretation_uncertainty:.2f}."
    ).strip(" |")
    context = str(getattr(report, "prompt_context", "") or "")
    context = f"{context}\n\n{appraisal.to_prompt_context()}".strip()
    hard_rules = tuple(getattr(report, "hard_rules", ()) or ())
    hard_rules = tuple(dict.fromkeys((
        *hard_rules,
        "Không được trình bày claim đang quarantine/retract như fact chắc chắn.",
        "Không được khẳng định chắc chắn động cơ xã hội của user từ một lượt mơ hồ.",
    )))
    evidence = tuple(getattr(report, "evidence", ()) or ())
    evidence = tuple(dict.fromkeys((
        *evidence,
        *(f"repair_h:{item}" for item in appraisal.evidence[:6]),
    )))
    try:
        return replace(
            report,
            # Cố ý không đổi mode/animation: appraisal không phải hard router.
            reason=reason,
            prompt_context=context,
            hard_rules=hard_rules,
            evidence=evidence,
        )
    except Exception:
        return report


_RETRACTION_MARKERS = (
    "toi hieu sai", "toi doan qua", "toi tu keo", "toi tu bia", "toi nham", "toi lo",
    "do toi suy dien", "phan pixel la do toi", "khong phai dieu ngai noi", "khong phai y ngai",
    "claim do la sai", "rut lai", "toi vua phong", "toi vua tu dung",
)
_SOFTENING_MARKERS = (
    "co the", "co ve", "chua chac", "toi khong nen khang dinh", "toi dang doan",
    "neu toi hieu dung", "mot kha nang", "toi co the da", "chua du du kien",
)
_CERTAINTY_MARKERS = (
    "chac chan", "ro rang", "dung la", "nghia la", "chinh la", "thuc ra la",
)


def output_overcommits_contested_claim(text: str, appraisal: RepairAppraisal) -> bool:
    """Chỉ chặn output biến giả thuyết contest thành fact chắc chắn."""

    if appraisal.claim_disposition == "preserve":
        return False
    norm = normalize_vi(text)
    if not norm:
        return appraisal.claim_disposition == "retract"
    mentions_contested = any(
        term in norm.split() or term in norm
        for term in appraisal.contested_terms
        if len(term) >= 3
    )
    has_retraction = _has_any(norm, _RETRACTION_MARKERS)
    has_softening = _has_any(norm, _SOFTENING_MARKERS)
    if appraisal.claim_disposition == "retract":
        # Explicit correction: phải có dấu hiệu rút/sửa, không chỉ lặp claim cũ.
        return not has_retraction
    if not mentions_contested:
        return False
    # Quarantine: nhắc lại được, nhưng không được nói chắc nếu thiếu softening.
    return _has_any(norm, _CERTAINTY_MARKERS) and not (has_softening or has_retraction)


def build_safe_repair_text(appraisal: RepairAppraisal) -> str:
    """Fallback hiếm dùng, giữ uncertainty thay vì gán ý định cho user."""

    claim_terms = ", ".join(appraisal.contested_terms[:3])
    claim_label = claim_terms or "đoạn vừa rồi"
    contrast = appraisal.user_contrast_excerpt.strip()
    if appraisal.claim_disposition == "retract":
        if appraisal.playful_score >= 0.36 and appraisal.boundary_score < 0.50:
            if contrast:
                return f"Ừ, phần {claim_label} là tôi tự kéo vào. {contrast}; tôi diễn giải quá tay rồi."
            return f"Ừ, phần {claim_label} là tôi tự dựng thêm. Tôi rút phần đó, còn sắc thái câu của Ngài thì tôi chưa đóng khung vội."
        if contrast:
            return f"Tôi hiểu sai và rút phần {claim_label}. {contrast}; phần trước là suy diễn của tôi."
        return f"Tôi hiểu sai và rút phần {claim_label}; đó là suy diễn của tôi, không phải dữ kiện từ Ngài."

    # Quarantine: không tuyên bố claim đúng hay sai, cũng không gán user đang đùa.
    if appraisal.playful_score >= 0.34:
        return (
            f"Phần {claim_label} có vẻ là tôi tự kéo vào nhiều hơn là điều Ngài nói. "
            "Tôi chưa nên khẳng định một cách hiểu duy nhất; câu đó có thể vừa là chọc tôi vừa là đang chỉnh tôi."
        )
    return (
        f"Phần {claim_label} đang chưa đủ chắc để tôi tiếp tục coi là dữ kiện. "
        "Tôi sẽ hạ nó xuống giả thuyết và không xây thêm trên đó."
    )


def apply_repair_output_guard(decision: Any, appraisal: RepairAppraisal) -> Any:
    """Gắn provenance và chặn overcommit, không khóa cảm xúc/quan hệ."""

    if decision is None or appraisal is None or not appraisal.active:
        return decision
    tags = tuple(getattr(decision, "reasoning_tags", ()) or ())
    extra_tags = [
        "uncertainty_preserving_repair",
        f"claim_{appraisal.claim_disposition}",
        f"posture_{appraisal.preferred_posture}",
    ]
    if appraisal.candidate_count_hint >= 2:
        extra_tags.append("repair_interpretation_uncertain")
    if appraisal.fact_commit_policy != "allow":
        try:
            decision.extracted_fact = ""
        except Exception:
            pass
        extra_tags.append(appraisal.fact_commit_policy)
    try:
        decision.reasoning_tags = tuple(dict.fromkeys((*tags, *extra_tags)))
    except Exception:
        pass

    if output_overcommits_contested_claim(str(getattr(decision, "text", "") or ""), appraisal):
        try:
            decision.text = build_safe_repair_text(appraisal)
            decision.should_speak = True
            decision.confidence = max(0.52, min(0.72, clamp01(getattr(decision, "confidence", 0.0))))
            decision.parse_mode = "uncertainty_preserving_repair_guard"
            trace = str(getattr(decision, "debug_trace", "") or "").strip()
            marker = "repair:blocked_overcommit_on_contested_claim"
            decision.debug_trace = " | ".join(part for part in (trace, marker) if part)
        except Exception:
            pass
    return decision


# Tên cũ giữ alias để plugin ngoài repo không vỡ ngay; semantics đã đổi sang
# overcommit/quarantine chứ không còn "claim chắc chắn đã bị rút".
def output_defends_retracted_claim(text: str, appraisal: RepairAppraisal) -> bool:
    return output_overcommits_contested_claim(text, appraisal)


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
    "output_overcommits_contested_claim",
]
