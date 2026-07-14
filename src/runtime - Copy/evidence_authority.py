# -*- coding: utf-8 -*-
"""evidence_authority.py - cổng kiểm chứng trước khi câu được phát ra.

LLM nhỏ được phép viết tự nhiên, nhưng không được tự cấp quyền quan sát hay hành
động cho chính nó.  Module này kiểm tra ba thứ độc lập:

1. ``evidence_refs`` có tồn tại, còn hạn và được phép public hay không;
2. mức bằng chứng ``remembered``/``inferred`` đã được surface đúng cách chưa;
3. text có chứa claim vượt quyền như nhìn màn hình, làm hành động hệ thống,
   kết luận cảm xúc hoặc mô tả tiếp xúc vật lý hay không.

Không gọi LLM ở đây.  Đây là hard gate deterministic, vì dùng thêm một model để
hỏi model trước có bịa không là cách rất sáng tạo để nhân đôi cùng một lỗi.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from runtime.director_context import DirectorContext, EvidenceClaim


_PERCEPTION_CLAIM_RE = re.compile(
    r"\b(?:tôi thấy|toi thay|tôi nhìn|toi nhin|tôi đang nhìn|toi dang nhin|"
    r"trên màn hình|tren man hinh|màn hình của ngài|man hinh cua ngai|"
    r"cửa sổ của ngài|cua so cua ngai|tab của ngài|tab cua ngai)\b",
    re.I,
)
_SYSTEM_ACTION_CLAIM_RE = re.compile(
    r"\b(?:tôi đã (?:sửa|chạy|mở|đóng|xóa|gửi|chặn|tắt|bật|lưu file|ghi file)|"
    r"toi da (?:sua|chay|mo|dong|xoa|gui|chan|tat|bat|luu file|ghi file)|"
    r"tôi vừa (?:sửa|chạy|mở|đóng|xóa|gửi|chặn|tắt|bật|lưu file|ghi file)|"
    r"toi vua (?:sua|chay|mo|dong|xoa|gui|chan|tat|bat|luu file|ghi file)|"
    r"đã hoàn tất|da hoan tat)\b",
    re.I,
)
_EMOTION_AS_FACT_RE = re.compile(
    r"\b(?:ngài|ngai|bạn|ban)\s+(?:đang|dang|rất|rat|thật sự|that su)\s+"
    r"(?:tuyệt vọng|tuyet vong|trầm cảm|tram cam|lo âu|lo au|sợ hãi|so hai|"
    r"ghét|ghet|căm ghét|cam ghet|đau khổ|dau kho|hoảng loạn|hoang loan|"
    r"cô đơn|co don|buồn|buon|tức giận|tuc gian)\b",
    re.I,
)
_HEARING_CLAIM_RE = re.compile(
    r"\b(?:tôi nghe (?:ngài|bạn)|toi nghe (?:ngai|ban)|"
    r"nghe ngài thở|nghe bạn thở|nghe ngai tho|nghe ban tho)\b",
    re.I,
)
_PHYSICAL_OVERREACH_RE = re.compile(
    r"\b(?:tôi|toi)\s+(?:ôm|om|chạm|cham|kéo|keo|nắm|nam|vuốt|vuot|"
    r"đỡ|do|đẩy|day)\s+(?:ngài|ngai|bạn|ban|tay|vai|mặt|mat)\b",
    re.I,
)
_MEMORY_MARKER_RE = re.compile(
    r"\b(?:tôi nhớ|toi nho|theo điều tôi nhớ|theo dieu toi nho|"
    r"lần trước|lan truoc|trước đây|truoc day|ký ức|ky uc)\b",
    re.I,
)
_INFERENCE_HEDGE_RE = re.compile(
    r"\b(?:có vẻ|co ve|hình như|hinh nhu|có lẽ|co le|"
    r"tôi đoán|toi doan|nếu tôi hiểu đúng|neu toi hieu dung|"
    r"khả năng là|kha nang la)\b",
    re.I,
)

_SCREEN_EVIDENCE_KEYS = {"screen_summary", "window_title", "active_app", "focus_kind"}
_CLAIM_STOPWORDS = {
    "toi", "thay", "nhin", "tren", "man", "hinh", "cua", "ngai", "ban",
    "dang", "mot", "nay", "kia", "la", "co", "va", "voi", "tab", "cua",
    "so", "window", "screen", "the", "you", "your", "see", "look", "at",
    "unknown",
}


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return re.sub(r"\s+", " ", value).strip()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", _normalize(text))
        if token not in _CLAIM_STOPWORDS
    }


def _screen_claim_matches_evidence(text: str, claims: Iterable[EvidenceClaim]) -> bool:
    claim_tokens = _meaningful_tokens(text)
    if not claim_tokens:
        return False
    evidence_tokens: set[str] = set()
    for claim in claims:
        if claim.key not in _SCREEN_EVIDENCE_KEYS:
            continue
        evidence_tokens.update(_meaningful_tokens(str(claim.value or "")))
    return bool(claim_tokens & evidence_tokens)


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class AuthorityResult:
    """Kết quả hard gate, đủ chi tiết để SceneRepairPolicy xử lý."""

    allowed: bool
    reasons: tuple[str, ...] = ()
    missing_evidence_refs: tuple[str, ...] = ()
    expired_evidence_refs: tuple[str, ...] = ()
    private_evidence_refs: tuple[str, ...] = ()
    used_levels: tuple[str, ...] = ()
    needs_memory_marker: bool = False
    needs_inference_hedge: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "missing_evidence_refs": list(self.missing_evidence_refs),
            "expired_evidence_refs": list(self.expired_evidence_refs),
            "private_evidence_refs": list(self.private_evidence_refs),
            "used_levels": list(self.used_levels),
            "needs_memory_marker": self.needs_memory_marker,
            "needs_inference_hedge": self.needs_inference_hedge,
        }


class EvidenceAuthority:
    """Kiểm tra candidate theo evidence ladder của DirectorContext."""

    def validate_candidate(
        self,
        candidate: Any,
        context: DirectorContext,
        *,
        now_ms: int | None = None,
    ) -> AuthorityResult:
        text = str(getattr(candidate, "text", "") or "").strip()
        refs_raw = getattr(candidate, "evidence_refs", ()) or ()
        if isinstance(refs_raw, str):
            refs = (refs_raw,)
        else:
            refs = tuple(str(item or "").strip() for item in refs_raw if str(item or "").strip())
        return self.validate_text(text, context, evidence_refs=refs, now_ms=now_ms)

    def validate_text(
        self,
        text: str,
        context: DirectorContext,
        *,
        evidence_refs: tuple[str, ...] = (),
        now_ms: int | None = None,
    ) -> AuthorityResult:
        current_ms = _now_ms() if now_ms is None else int(now_ms)
        normalized = _normalize(text)
        reasons: list[str] = []
        missing: list[str] = []
        expired: list[str] = []
        private_refs: list[str] = []
        used_levels: list[str] = []

        evidence_by_key: dict[str, EvidenceClaim] = {
            str(claim.key): claim for claim in context.evidence if str(getattr(claim, "key", "") or "").strip()
        }
        used_claims: list[EvidenceClaim] = []
        for ref in evidence_refs:
            claim = evidence_by_key.get(ref)
            if claim is None:
                missing.append(ref)
                continue
            used_claims.append(claim)
            used_levels.append(str(claim.level))
            if claim.expires_at_ms is not None and current_ms > int(claim.expires_at_ms):
                expired.append(ref)
            if context.audience_mode != "private" and not bool(claim.public_ok):
                private_refs.append(ref)
            if claim.level == "forbidden":
                reasons.append("forbidden_evidence_level")

        if missing:
            reasons.append("missing_evidence_ref")
        if expired:
            reasons.append("expired_evidence_ref")
        if private_refs:
            reasons.append("private_evidence_in_public")

        forbidden = set(context.forbidden_claims)
        if _PERCEPTION_CLAIM_RE.search(normalized):
            screen_claims = [claim for claim in context.evidence if claim.key in _SCREEN_EVIDENCE_KEYS]
            has_live_screen = any(
                claim.value not in (None, "", "unknown")
                and (claim.expires_at_ms is None or current_ms <= int(claim.expires_at_ms))
                for claim in screen_claims
            )
            if not has_live_screen:
                reasons.append("screen_claim_without_sensor")
            elif not _screen_claim_matches_evidence(normalized, screen_claims):
                reasons.append("screen_claim_not_grounded")
        if "system_action_without_tool" in forbidden and _SYSTEM_ACTION_CLAIM_RE.search(normalized):
            reasons.append("system_action_without_tool")
        if "emotion_as_fact" in forbidden and _EMOTION_AS_FACT_RE.search(normalized):
            reasons.append("emotion_as_fact")
        if "hearing_user_breath" in forbidden and _HEARING_CLAIM_RE.search(normalized):
            reasons.append("hearing_user_breath")
        if _PHYSICAL_OVERREACH_RE.search(normalized):
            reasons.append("physical_world_overreach")

        needs_memory_marker = any(claim.level == "remembered" for claim in used_claims) and not bool(
            _MEMORY_MARKER_RE.search(normalized)
        )
        if needs_memory_marker:
            reasons.append("remembered_claim_without_marker")

        needs_inference_hedge = any(claim.level == "inferred" for claim in used_claims) and not bool(
            _INFERENCE_HEDGE_RE.search(normalized)
        )
        if needs_inference_hedge:
            reasons.append("inferred_claim_without_hedge")

        unique_reasons = _unique(reasons)
        return AuthorityResult(
            allowed=not unique_reasons,
            reasons=unique_reasons,
            missing_evidence_refs=_unique(missing),
            expired_evidence_refs=_unique(expired),
            private_evidence_refs=_unique(private_refs),
            used_levels=_unique(used_levels),
            needs_memory_marker=needs_memory_marker,
            needs_inference_hedge=needs_inference_hedge,
        )

    # API tương thích với bản cũ để importer ngoài StageScorer không vỡ.
    def evaluate_text(self, text: str, context: DirectorContext) -> tuple[bool, tuple[str, ...]]:
        result = self.validate_text(text, context)
        return result.allowed, result.reasons


__all__ = ["AuthorityResult", "EvidenceAuthority"]
