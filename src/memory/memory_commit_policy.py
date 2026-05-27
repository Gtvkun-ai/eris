from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .memory_models import (
    DecayPolicy,
    MemoryCommitDecision,
    MemoryKind,
    MemoryTarget,
    SurfaceMode,
)
from .text_normalize_vi import compact_spaces, normalize_vi


@dataclass(frozen=True)
class ExtractedFact:
    """Fact ứng viên được rút ra từ một user turn."""

    kind: MemoryKind
    value: str
    raw_span: str
    confidence: float
    evidence_reason: str


class UserFactExtractor:
    """
    Rút fact từ câu user theo dạng cấu trúc.

    Có pattern, nhưng không phải fallback keyword vá cháy. Pattern chỉ làm
    nhiệm vụ evidence extraction cho các fact người dùng tự khai báo rõ ràng.
    Suy diễn cao cấp hơn nên đặt ở tầng Meaning/ToM, không đặt ở đây.
    """

    _NAME_PATTERNS = (
        re.compile(r"\b(?:tôi|toi|tao|mình|minh|tớ|to)\s+tên\s+là\s+(.+)$", re.IGNORECASE),
        re.compile(r"\b(?:tên\s+(?:của\s+)?(?:tôi|toi|tao|mình|minh|tớ|to)\s+là)\s+(.+)$", re.IGNORECASE),
        re.compile(r"\b(?:gọi\s+(?:tôi|toi|tao|mình|minh|tớ|to)\s+là)\s+(.+)$", re.IGNORECASE),
    )

    _BIRTH_MONTH_PATTERNS = (
        re.compile(r"\b(?:tháng\s+sinh|thang\s+sinh)\s+(?:là|la)?\s*(?:tháng|thang)?\s*(\d{1,2})\b", re.IGNORECASE),
        re.compile(r"\b(?:tôi|toi|mình|minh)\s+sinh\s+(?:tháng|thang)\s*(\d{1,2})\b", re.IGNORECASE),
    )

    _ENDING_STYLE_PATTERNS = (
        re.compile(r"\b(?:kết\s*thúc|ket\s*thuc)\s+câu\s+(?:bằng|bang)\s+(.+?)(?:\s+(?:bắt đầu|bat dau)\s+từ\s+giờ|\s*$)", re.IGNORECASE),
        re.compile(r"\b(?:sau này|sau nay).{0,40}(?:kết\s*thúc|ket\s*thuc).{0,20}(?:bằng|bang)\s+(.+)$", re.IGNORECASE),
    )

    # ASCII/Unicode-safe overrides for environments where legacy literals were saved
    # with mojibake but runtime inputs are still normalized correctly.
    _NAME_PATTERNS = (
        re.compile(r"\b(?:toi|tôi|tao|minh|mình|to|tớ)\s+(?:ten|tên)\s+(?:la|là)\s+(.+)$", re.IGNORECASE),
        re.compile(r"\b(?:ten|tên)\s+(?:cua\s+|của\s+)?(?:toi|tôi|tao|minh|mình|to|tớ)\s+(?:la|là)\s+(.+)$", re.IGNORECASE),
        re.compile(r"\b(?:goi|gọi)\s+(?:toi|tôi|tao|minh|mình|to|tớ)\s+(?:la|là)\s+(.+)$", re.IGNORECASE),
    )

    _BIRTH_MONTH_PATTERNS = (
        re.compile(r"\b(?:thang\s+sinh|tháng\s+sinh)\s+(?:la|là)?\s*(?:thang|tháng)?\s*(\d{1,2})\b", re.IGNORECASE),
        re.compile(r"\b(?:toi|tôi|minh|mình)\s+sinh\s+(?:thang|tháng)\s*(\d{1,2})\b", re.IGNORECASE),
    )

    _ENDING_STYLE_PATTERNS = (
        re.compile(r"\b(?:ket\s*thuc|kết\s*thúc)\s+cau\s+(?:bang|bằng)\s+(.+?)(?:\s+(?:bat\s+dau|bắt đầu)\s+tu\s+gio|\s*$)", re.IGNORECASE),
        re.compile(r"\b(?:sau\s+nay|sau này).{0,40}(?:ket\s*thuc|kết\s*thúc).{0,20}(?:bang|bằng)\s+(.+)$", re.IGNORECASE),
    )

    _MEMORY_TEST_HINTS = (
        "cau thu",
        "cau hoi thu",
        "nho cau",
        "toi da hoi bao nhieu",
        "cau nao la nhieu ky tu",
        "dai nhat",
    )

    def extract(self, user_text: str) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        raw = compact_spaces(user_text)
        normalized = normalize_vi(raw)

        facts.extend(self._extract_name(raw))
        facts.extend(self._extract_birth_month(raw))
        facts.extend(self._extract_response_style(raw, normalized))

        if any(hint in normalized for hint in self._MEMORY_TEST_HINTS):
            facts.append(
                ExtractedFact(
                    kind=MemoryKind.SESSION_MEMORY_TEST,
                    value="user đang kiểm tra khả năng nhớ thứ tự, số lượng hoặc nguyên văn câu trong phiên",
                    raw_span=raw,
                    confidence=0.80,
                    evidence_reason="user_memory_test_prompt",
                )
            )

        return facts

    def _extract_name(self, raw: str) -> Iterable[ExtractedFact]:
        for pattern in self._NAME_PATTERNS:
            match = pattern.search(raw)
            if not match:
                continue
            name = self._clean_value(match.group(1))
            if self._valid_person_name(name):
                yield ExtractedFact(
                    kind=MemoryKind.USER_NAME,
                    value=name,
                    raw_span=match.group(0),
                    confidence=0.98,
                    evidence_reason="explicit_user_name_statement",
                )
            return

    def _extract_birth_month(self, raw: str) -> Iterable[ExtractedFact]:
        normalized_raw = normalize_vi(raw)
        for pattern in self._BIRTH_MONTH_PATTERNS:
            match = pattern.search(normalized_raw)
            if not match:
                continue
            month = int(match.group(1))
            if 1 <= month <= 12:
                yield ExtractedFact(
                    kind=MemoryKind.USER_BIRTH_MONTH,
                    value=str(month),
                    raw_span=raw,
                    confidence=0.92,
                    evidence_reason="explicit_birth_month_statement",
                )
            return

    def _extract_response_style(self, raw: str, normalized: str) -> Iterable[ExtractedFact]:
        for pattern in self._ENDING_STYLE_PATTERNS:
            match = pattern.search(normalized)
            if not match:
                continue

            marker = self._clean_value(match.group(1))
            marker = marker.strip(" .'\"")
            if 1 <= len(marker) <= 12:
                yield ExtractedFact(
                    kind=MemoryKind.USER_RESPONSE_STYLE,
                    value=f"kết thúc câu bằng {marker}",
                    raw_span=raw,
                    confidence=0.90,
                    evidence_reason="explicit_response_style_preference",
                )
            return

    @staticmethod
    def _clean_value(value: str) -> str:
        value = compact_spaces(value)
        value = value.strip(" .,:;!?\"'“”")
        return value

    @staticmethod
    def _valid_person_name(value: str) -> bool:
        if not value:
            return False
        if len(value) > 80:
            return False
        bad_fragments = ("tháng", "thang", "câu", "cau", "không", "khong", "gì", "gi")
        normalized = normalize_vi(value)
        return not any(fragment in normalized for fragment in bad_fragments)


class MemoryCommitPolicy:
    """
    Quyết định commit memory theo ý nghĩa, không theo raw transcript.

    Mục tiêu:
    - fact định danh rõ ràng phải vào semantic memory;
    - preference phản hồi phải vào procedural memory;
    - test trí nhớ/thứ tự câu chỉ là episodic gist hoặc event ledger phiên;
    - không biến long-term memory thành máy quote nguyên văn.
    """

    def __init__(self, extractor: UserFactExtractor | None = None) -> None:
        self.extractor = extractor or UserFactExtractor()

    def decide_from_user_turn(self, user_text: str, *, turn_id: str | None = None) -> list[MemoryCommitDecision]:
        decisions: list[MemoryCommitDecision] = []

        for fact in self.extractor.extract(user_text):
            if fact.kind == MemoryKind.USER_NAME:
                decisions.append(self._user_name_decision(fact, turn_id))
            elif fact.kind == MemoryKind.USER_BIRTH_MONTH:
                decisions.append(self._birth_month_decision(fact, turn_id))
            elif fact.kind == MemoryKind.USER_RESPONSE_STYLE:
                decisions.append(self._response_style_decision(fact, turn_id))
            elif fact.kind == MemoryKind.SESSION_MEMORY_TEST:
                decisions.append(self._memory_test_decision(fact, turn_id))

        return self._dedupe(decisions)

    def _user_name_decision(self, fact: ExtractedFact, turn_id: str | None) -> MemoryCommitDecision:
        return MemoryCommitDecision(
            target=MemoryTarget.SEMANTIC,
            kind=MemoryKind.USER_NAME,
            claim=f"User's name is {fact.value}",
            surface=f"Ngài từng nói tên mình là {fact.value}.",
            confidence=fact.confidence,
            importance=0.98,
            surface_mode=SurfaceMode.SEMANTIC,
            decay=DecayPolicy.STABLE,
            evidence=[turn_id] if turn_id else [],
            metadata={
                "value": fact.value,
                "evidence_reason": fact.evidence_reason,
                "overwrite_policy": "replace_same_kind_if_user_self_declares",
            },
        )

    def _birth_month_decision(self, fact: ExtractedFact, turn_id: str | None) -> MemoryCommitDecision:
        return MemoryCommitDecision(
            target=MemoryTarget.SEMANTIC,
            kind=MemoryKind.USER_BIRTH_MONTH,
            claim=f"User's birth month is {fact.value}",
            surface=f"Ngài từng nói tháng sinh của mình là tháng {fact.value}.",
            confidence=fact.confidence,
            importance=0.72,
            surface_mode=SurfaceMode.SEMANTIC,
            decay=DecayPolicy.STABLE,
            evidence=[turn_id] if turn_id else [],
            metadata={
                "value": fact.value,
                "evidence_reason": fact.evidence_reason,
                "overwrite_policy": "replace_same_kind_if_user_self_declares",
            },
        )

    def _response_style_decision(self, fact: ExtractedFact, turn_id: str | None) -> MemoryCommitDecision:
        return MemoryCommitDecision(
            target=MemoryTarget.PROCEDURAL,
            kind=MemoryKind.USER_RESPONSE_STYLE,
            claim=f"User prefers ERIS to {fact.value}",
            surface=f"Ngài muốn tôi {fact.value}.",
            confidence=fact.confidence,
            importance=0.86,
            surface_mode=SurfaceMode.SEMANTIC,
            decay=DecayPolicy.STABLE,
            evidence=[turn_id] if turn_id else [],
            metadata={
                "value": fact.value,
                "scope": "until_changed",
                "evidence_reason": fact.evidence_reason,
                "overwrite_policy": "replace_same_kind_if_user_updates_style",
            },
        )

    def _memory_test_decision(self, fact: ExtractedFact, turn_id: str | None) -> MemoryCommitDecision:
        return MemoryCommitDecision(
            target=MemoryTarget.EPISODIC,
            kind=MemoryKind.SESSION_MEMORY_TEST,
            claim="User tested ERIS recall about previous turns in the current session.",
            surface="Ngài từng kiểm tra trí nhớ của tôi bằng các câu hỏi về thứ tự, số lượng hoặc nội dung câu trong phiên.",
            confidence=fact.confidence,
            importance=0.38,
            surface_mode=SurfaceMode.GIST,
            decay=DecayPolicy.SHORT,
            evidence=[turn_id] if turn_id else [],
            metadata={
                "gist": fact.value,
                "do_not_store_exact_user_text": True,
                "evidence_reason": fact.evidence_reason,
            },
        )

    @staticmethod
    def _dedupe(decisions: list[MemoryCommitDecision]) -> list[MemoryCommitDecision]:
        seen: set[tuple[str, str, str]] = set()
        out: list[MemoryCommitDecision] = []
        for decision in decisions:
            key = (decision.target.value, decision.kind.value, decision.claim)
            if key in seen:
                continue
            seen.add(key)
            out.append(decision)
        return out
