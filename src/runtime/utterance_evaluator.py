from __future__ import annotations

"""Đánh giá câu trước khi cho ra public.

Tầng này không phải persona writer. Nó là tai nghe lại câu nháp:
- câu có bám evidence hiện tại không;
- có đang tự suy diễn hoạt động của Ngài không;
- có nên im thay vì cố nói không;
- có đáng gọi mentor/Gemini để sửa không.

Nếu câu nguồn đã biết tự đánh giá, lớp repair phía sau sẽ nhẹ hơn rất nhiều.
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal


UtteranceVerdict = Literal["allow", "rewrite", "drop"]


@dataclass(frozen=True, slots=True)
class UtteranceEvaluation:
    verdict: UtteranceVerdict = "allow"
    quality: float = 0.72
    issues: tuple[str, ...] = ()
    reason: str = "ok"
    mentor_wanted: bool = False
    missing_evidence: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict == "allow" and self.quality >= 0.50


def evaluator_enabled() -> bool:
    raw = str(os.environ.get("ERIS_SENTENCE_EVALUATOR", "1") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def mentor_enabled() -> bool:
    raw = str(os.environ.get("ERIS_SENTENCE_MENTOR", "1") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _normalize_vi(text: Any) -> str:
    lowered = str(text or "").strip().lower()
    try:
        fixed = lowered.encode("latin1").decode("utf-8")
        if fixed:
            lowered = fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    lowered = unicodedata.normalize("NFD", lowered)
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = re.sub(r"[^a-z0-9_./:+\-\s?]", " ", lowered)
    return " ".join(lowered.split())


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_as_text(item) for item in value)
    return str(value)


class UtteranceEvaluator:
    """Rubric nhỏ để câu nháp tự qua một lượt nghe lại.

    Luật cố tình ít nhưng sắc:
    - current screen domain thắng memory/private seed;
    - claim "Ngài đang..." phải có evidence;
    - micro-presence không được thành filler/status ping;
    - khi user sửa lỗi, đừng hỏi rộng như chưa nghe.
    """

    _PROTOCOL_MARKERS = (
        "json",
        "parser",
        "parse mode",
        "parse_mode",
        "debug_trace",
        "reasoning_tags",
        "system_action",
        "metadata",
        "format",
    )
    _GENERIC_FILLER = (
        "toi day",
        "toi dang nghe",
        "toi van o day",
        "toi van quan sat",
        "co gi khong",
        "ban can gi",
        "toi co the giup gi",
        "ngai can gi",
        "im hoi lau",
        "nhip nay",
        "khoang yen nay",
    )
    _CORRECTION_MARKERS = (
        "khong phai",
        "co dau",
        "co code dau",
        "toi co code dau",
        "sai",
        "nham",
        "lech",
        "chi nghe nhac",
        "hieu sai",
        "ha",
    )
    _BROAD_CLARIFY = (
        "ngai dang lam gi",
        "ngai co the noi ro",
        "noi ro hon",
        "toi chua hieu",
        "co ve nhu toi da hieu sai",
    )
    _ASSERTIVE_USER_ACTIVITY = (
        "ngai dang",
        "ngai vua",
        "toi thay ngai",
        "toi doan ngai dang",
        "hinh nhu ngai dang",
        "co ve ngai dang",
    )
    _HEDGE_MARKERS = (
        "toi doan",
        "co ve",
        "hinh nhu",
        "phai khong",
        "dung khong",
        "neu",
    )

    def evaluate(
        self,
        text: str,
        *,
        channel: str = "",
        user_text: str = "",
        snapshot: Any = None,
        frame: Any = None,
        speech_core: Any = None,
        grounding: Any = None,
    ) -> UtteranceEvaluation:
        if not evaluator_enabled():
            return UtteranceEvaluation()
        raw = str(text or "").strip()
        normalized = _normalize_vi(raw)
        if not normalized:
            return UtteranceEvaluation(verdict="allow", quality=0.60, reason="empty_or_body_only")

        issues: list[str] = []
        missing: list[str] = []
        quality = 0.78
        verdict: UtteranceVerdict = "allow"

        if any(marker in normalized for marker in self._PROTOCOL_MARKERS):
            issues.append("protocol_or_schema_leak")
            quality = min(quality, 0.10)
            verdict = "rewrite"

        if len(normalized.split()) <= 2 and str(channel or "") in {"autonomous", "force_speak", "surface"}:
            issues.append("too_thin_to_speak")
            quality = min(quality, 0.38)
            verdict = "drop"

        if any(pattern in normalized for pattern in self._GENERIC_FILLER):
            issues.append("generic_presence_filler")
            quality = min(quality, 0.34)
            verdict = "rewrite"

        user_norm = _normalize_vi(user_text)
        if any(marker in user_norm for marker in self._CORRECTION_MARKERS) and any(
            marker in normalized for marker in self._BROAD_CLARIFY
        ):
            issues.append("correction_answered_with_broad_clarifier")
            quality = min(quality, 0.24)
            verdict = "rewrite"

        evidence_text = self._evidence_text(snapshot=snapshot, frame=frame, speech_core=speech_core, grounding=grounding)
        current_domain = self._domain_from_text(evidence_text, current_context=True)
        text_domain = self._domain_from_text(raw)
        if current_domain and text_domain and current_domain != "mixed" and text_domain != "mixed" and current_domain != text_domain:
            issues.append(f"domain_contradiction:{text_domain}_vs_{current_domain}")
            missing.append(f"current_{text_domain}_evidence")
            quality = min(quality, 0.18)
            verdict = "rewrite"

        claims_activity = any(marker in normalized for marker in self._ASSERTIVE_USER_ACTIVITY)
        hedged = any(marker in normalized for marker in self._HEDGE_MARKERS)
        if claims_activity and not self._has_activity_support(normalized, evidence_text):
            issues.append("unsupported_user_activity_claim")
            missing.append("activity_evidence")
            quality = min(quality, 0.28 if hedged else 0.18)
            verdict = "rewrite"

        if str(channel or "") in {"autonomous", "force_speak", "surface", "micro_presence"}:
            words = normalized.split()
            if len(words) > 24:
                issues.append("micro_line_too_long")
                quality = min(quality, 0.46)
                verdict = "rewrite"
            if not issues and claims_activity and self._token_overlap(normalized, evidence_text) < 0.12:
                issues.append("low_evidence_overlap")
                quality = min(quality, 0.42)
                verdict = "rewrite"

        if verdict == "rewrite" and quality <= 0.45:
            mentor = True
        else:
            mentor = False
        if verdict == "drop" and quality > 0.30:
            mentor = False

        return UtteranceEvaluation(
            verdict=verdict,
            quality=max(0.0, min(1.0, quality)),
            issues=tuple(dict.fromkeys(issues)),
            reason=";".join(dict.fromkeys(issues)) or "ok",
            mentor_wanted=mentor,
            missing_evidence=tuple(dict.fromkeys(missing)),
        )

    def mentor_context(
        self,
        *,
        text: str,
        evaluation: UtteranceEvaluation,
        channel: str = "",
        user_text: str = "",
        snapshot: Any = None,
        frame: Any = None,
        speech_core: Any = None,
        grounding: Any = None,
    ) -> str:
        evidence = self._evidence_text(snapshot=snapshot, frame=frame, speech_core=speech_core, grounding=grounding)
        return (
            f"channel={channel or 'unknown'}\n"
            f"user_text={str(user_text or '').strip()[:300]}\n"
            f"draft={str(text or '').strip()[:500]}\n"
            f"quality={evaluation.quality:.2f}; verdict={evaluation.verdict}; issues={','.join(evaluation.issues)}\n"
            f"missing_evidence={','.join(evaluation.missing_evidence) or 'none'}\n"
            f"current_evidence={evidence[:1000] or 'none'}"
        )

    def _evidence_text(self, *, snapshot: Any = None, frame: Any = None, speech_core: Any = None, grounding: Any = None) -> str:
        parts: list[str] = []
        for owner in (snapshot, frame, speech_core, grounding):
            if owner is None:
                continue
            for attr in (
                "active_window_kind",
                "focus_kind",
                "focus_kind_hint",
                "focus_summary",
                "activity_intent",
                "semantic_family",
                "topic_seed",
                "speech_evidence",
                "reason",
                "primary_source",
                "epistemic_mode",
            ):
                value = getattr(owner, attr, "")
                if value:
                    parts.append(str(value))
            for attr in (
                "vision_facts",
                "recent_events",
                "evidence",
                "allowed_sources",
                "missing_evidence",
                "grounded_facts",
            ):
                value = getattr(owner, attr, ())
                if value:
                    parts.append(_as_text(value))
        return " ".join(part for part in parts if part)

    def _domain_from_text(self, text: Any, *, current_context: bool = False) -> str:
        normalized = _normalize_vi(text)
        if not normalized:
            return ""
        media_markers = (
            "youtube", "youtu be", "nhac", "music", "playlist", "video",
            "anime", "thumbnail", "media", "lofi", "song", "mv", "watch",
            "browsing", "gaming", "stream",
        )
        code_markers = (
            "code", "coding", "vscode", "visual studio code", "ide", "repo",
            "terminal", "pytest", "unit test", "test failure", "build",
            "compile", "debug", "bug", "stack trace", "python", "javascript",
            "typescript", "editor", "src/", "pull request",
        )
        media_score = sum(1 for marker in media_markers if marker in normalized)
        code_score = sum(1 for marker in code_markers if marker in normalized)
        if current_context:
            if media_score >= max(2, code_score + 1):
                return "media"
            if code_score >= max(2, media_score + 1):
                return "code"
        if media_score and code_score:
            if media_score >= code_score + 1:
                return "media"
            if code_score >= media_score + 1:
                return "code"
            return "mixed"
        if media_score:
            return "media"
        if code_score:
            return "code"
        return ""

    def _has_activity_support(self, normalized_text: str, evidence_text: str) -> bool:
        evidence_norm = _normalize_vi(evidence_text)
        if not evidence_norm:
            return False
        text_domain = self._domain_from_text(normalized_text)
        evidence_domain = self._domain_from_text(evidence_norm, current_context=True) or self._domain_from_text(evidence_norm)
        if text_domain and evidence_domain and text_domain == evidence_domain:
            return True
        activity_words = {"code", "coding", "nhac", "music", "youtube", "video", "build", "terminal", "playlist"}
        return bool(set(normalized_text.split()) & activity_words & set(evidence_norm.split()))

    def _token_overlap(self, normalized_text: str, evidence_text: str) -> float:
        text_tokens = {tok for tok in normalized_text.split() if len(tok) > 3}
        evidence_tokens = {tok for tok in _normalize_vi(evidence_text).split() if len(tok) > 3}
        if not text_tokens or not evidence_tokens:
            return 0.0
        return len(text_tokens & evidence_tokens) / max(1, len(text_tokens))


__all__ = ["UtteranceEvaluation", "UtteranceEvaluator", "evaluator_enabled", "mentor_enabled"]
