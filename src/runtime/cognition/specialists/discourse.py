# -*- coding: utf-8 -*-
"""DiscourseCortex: quan hệ giữa lượt mới và lời public gần nhất.

Không đọc personality, không quyết định warmth, không viết câu. Module chỉ trả
relation, ownership và move kế tiếp kèm evidence thật của frame.
"""

from __future__ import annotations

import re

from core.cognition import CognitiveFrame, DiscourseProjection
from runtime.cognition.normalization import contains_phrase, normalize_vi, token_overlap


class DiscourseCortex:
    _FILLER_PREFIX = re.compile(r"^(?:(?:eh+m+|uh+m+|um+|u+m+|o+m+|hm+|hmm+|a+|nay+)\s+)+")
    _SOFT_SUFFIX = re.compile(r"\s+(?:a|ah|ha|nhi|nhe|vay|the|coi|di|nao)$")

    EXACT_CONTINUATION = {
        "roi", "roi sao", "the roi sao", "xong", "xong roi sao", "sau do", "sau do thi sao",
        "tiep", "tiep di", "noi tiep", "ke tiep", "lam tiep", "giai thich tiep",
        "nua", "nua di", "con nua", "con gi nua", "phan sau", "phan con lai",
        "va", "va roi", "continue",
    }
    CONTINUATION_PATTERNS = (
        re.compile(r"^(?:noi|ke|lam|giai thich|phan tich)\s+tiep(?:\s+.*)?$"),
        re.compile(r"^(?:con|phan)\s+.*\s+(?:nua|dau|sao)$"),
        re.compile(r"^(?:roi|xong|sau do)\s+(?:thi\s+)?sao$"),
    )
    DIRECT_QUESTION_PREFIXES = (
        "roi toi ", "the toi ", "vay toi ", "con toi ", "roi minh ", "the minh ", "vay minh ",
        "roi em ", "the em ", "vay em ", "con em ", "roi ban ", "the ban ", "vay ban ",
    )
    CLOSE_EXACT = {
        "thoi bo di", "thoi bo", "bo di", "bo", "khoi", "thoi", "duoc roi", "ok bo qua", "khong can nua",
    }
    CRITICISM_MARKERS = (
        "generic", "chung chung", "vo hon", "may moc", "nhu bot", "support bot", "coc", "lanh",
        "kho khan", "rong", "khong dung y", "lam mau", "thang qua", "khong tu nhien",
    )
    ASSISTANT_MARKERS = (
        "ban noi", "em noi", "cau vua roi", "cau nay", "tra loi", "eris noi", "cach noi",
    )

    def project(self, frame: CognitiveFrame) -> DiscourseProjection:
        current = normalize_vi(frame.user_text)
        previous = frame.last_assistant_text
        previous_id = frame.last_assistant_evidence_id
        refs = ("turn:user_text", previous_id) if previous_id else ("turn:user_text",)
        if not current:
            return DiscourseProjection(confidence=0.2, ambiguity=0.9, evidence_ids=("turn:user_text",))

        cue = self._compact_cue(current)
        if previous and cue in self.CLOSE_EXACT:
            return DiscourseProjection(
                relation="close_topic",
                ambiguity_owner="shared",
                expected_next_move="acknowledge_close",
                assistant_fault_probability=0.05,
                confidence=0.90,
                ambiguity=0.06,
                evidence_ids=refs,
            )

        if previous and self._is_criticism(current):
            return DiscourseProjection(
                relation="style_feedback",
                ambiguity_owner="assistant",
                expected_next_move="repair_previous_response",
                open_loop=previous,
                referenced_phrase="previous assistant response",
                assistant_fault_probability=0.86,
                confidence=0.93,
                ambiguity=0.08,
                evidence_ids=refs,
            )

        identity = self._identity_reference(current, previous)
        if identity:
            return DiscourseProjection(
                relation="clarify_assistant_reference",
                ambiguity_owner="assistant",
                expected_next_move="clarify_literal_reference",
                open_loop=previous,
                referenced_phrase=identity,
                assistant_fault_probability=0.62,
                confidence=0.90,
                ambiguity=0.12,
                evidence_ids=refs,
            )

        phrase = self._phrase_reference(current, previous)
        if phrase:
            return DiscourseProjection(
                relation="clarify_assistant_phrase",
                ambiguity_owner="assistant",
                expected_next_move="clarify_previous_phrase",
                open_loop=previous,
                referenced_phrase=phrase,
                assistant_fault_probability=0.68,
                confidence=0.91,
                ambiguity=0.10,
                evidence_ids=refs,
            )

        if previous and self._challenges_assumption(current):
            return DiscourseProjection(
                relation="challenge_assistant_assumption",
                ambiguity_owner="assistant",
                expected_next_move="repair_assumption",
                open_loop=previous,
                referenced_phrase="previous implied assumption",
                assistant_fault_probability=0.78,
                confidence=0.90,
                ambiguity=0.12,
                evidence_ids=refs,
            )

        # "Thì sao?" thường là đòi ERIS giải thích relevance/consequence của claim,
        # không phải câu hỏi mới vô chủ. Tách khỏi "rồi sao?" để tránh làm mọi
        # continuation thành một nhãn duy nhất rồi tự khen mình hiểu discourse.
        if previous and cue in {"thi sao", "roi thi sao", "the thi sao"}:
            return DiscourseProjection(
                relation="challenge_assistant_relevance",
                ambiguity_owner="assistant",
                expected_next_move="explain_relevance",
                open_loop=previous,
                referenced_phrase="previous assistant claim",
                assistant_fault_probability=0.44,
                confidence=0.88,
                ambiguity=0.12,
                evidence_ids=refs,
            )

        if previous and self._is_continuation_bid(current):
            return DiscourseProjection(
                relation="continue_assistant_move",
                ambiguity_owner="assistant",
                expected_next_move="self_elaborate",
                open_loop=previous,
                assistant_fault_probability=0.72 if self._looks_open_ended(previous) else 0.48,
                confidence=0.94,
                ambiguity=0.06,
                evidence_ids=refs,
            )

        if previous and self._generic_clarification(current):
            return DiscourseProjection(
                relation="clarify_assistant_statement",
                ambiguity_owner="assistant",
                expected_next_move="clarify_previous_statement",
                open_loop=previous,
                referenced_phrase="previous statement",
                assistant_fault_probability=0.60,
                confidence=0.84,
                ambiguity=0.18,
                evidence_ids=refs,
            )

        return DiscourseProjection(
            relation="new_or_direct_turn",
            ambiguity_owner="unknown",
            expected_next_move="answer",
            assistant_fault_probability=0.0,
            confidence=0.66,
            ambiguity=0.32,
            evidence_ids=("turn:user_text",),
        )

    def _compact_cue(self, current: str) -> str:
        text = current.strip(" ?.!,")
        text = self._FILLER_PREFIX.sub("", text).strip()
        # Gỡ tối đa hai tiểu từ cuối. "rồi sao á vậy" hiếm nhưng loài người có
        # quyền sáng tạo, parser không cần nổi giận vì chuyện đó.
        for _ in range(2):
            reduced = self._SOFT_SUFFIX.sub("", text).strip()
            if reduced == text:
                break
            text = reduced
        for acknowledgement in ("duoc roi ", "ok ", "uh ", "u "):
            if text.startswith(acknowledgement):
                text = text[len(acknowledgement):].strip()
                break
        return text

    def _is_continuation_bid(self, current: str) -> bool:
        cue = self._compact_cue(current)
        if not cue or len(cue.split()) > 10:
            return False
        if cue.startswith(self.DIRECT_QUESTION_PREFIXES):
            return False
        # Một câu kể đã hoàn tất như "tôi làm xong rồi" có từ rồi nhưng không
        # phải lời mời ERIS tiếp tục. Exact cue tránh lỗi contains-phrase cũ.
        if any(token in cue.split() for token in ("toi", "minh", "em")) and cue not in self.EXACT_CONTINUATION:
            return False
        if cue in self.EXACT_CONTINUATION:
            return True
        return any(pattern.match(cue) for pattern in self.CONTINUATION_PATTERNS)

    def _is_criticism(self, current: str) -> bool:
        has_defect = contains_phrase(current, *self.CRITICISM_MARKERS)
        points_to_assistant = contains_phrase(current, *self.ASSISTANT_MARKERS)
        return has_defect and (points_to_assistant or len(current.split()) <= 9)

    @staticmethod
    def _challenges_assumption(current: str) -> bool:
        markers = (
            "la em nghi toi se", "la ban nghi toi se", "y em la toi", "y ban la toi",
            "em cho rang toi", "ban cho rang toi", "sao em lai nghi toi", "sao ban lai nghi toi",
        )
        return contains_phrase(current, *markers)

    @staticmethod
    def _generic_clarification(current: str) -> bool:
        markers = (
            "cai do la gi", "cai nay la gi", "y em la gi", "y ban la gi", "tuc la sao",
            "nghia la gi", "em noi cai gi vay", "ban noi cai gi vay", "la sao",
        )
        return contains_phrase(current, *markers)

    @staticmethod
    def _looks_open_ended(previous: str) -> bool:
        text = str(previous or "").strip()
        normalized = normalize_vi(text)
        if not text:
            return False
        if text.endswith(("...", "…", ":", "-")):
            return True
        return bool(re.search(r"\b(?:nhung|con|roi thi|phan con lai|chua het)\s*$", normalized))

    @staticmethod
    def _identity_reference(current: str, previous: str) -> str:
        if not previous:
            return ""
        patterns = (
            r"^(?P<subject>.+?)\s+la\s+(?:ban|em|eris)(?:\s+(?:a|ah|ha|khong|dung khong|phai khong))?$",
            r"^(?P<subject>.+?)\s+co phai\s+(?:ban|em|eris)(?:\s+khong)?$",
            r"^(?P<subject>.+?)\s+phai\s+(?:ban|em|eris)(?:\s+khong)?$",
        )
        for pattern in patterns:
            match = re.match(pattern, current)
            if not match:
                continue
            subject = match.group("subject").strip()
            generic = subject in {"cai do", "cai nay", "no", "do", "nay"}
            if generic or token_overlap(subject, previous) >= 0.60:
                return subject
        return ""

    @staticmethod
    def _phrase_reference(current: str, previous: str) -> str:
        if not previous:
            return ""
        patterns = (
            r"^(?P<subject>.+?)\s+la\s+(?:gi|phan nao|cai gi|sao|nhu nao|the nao)$",
            r"^(?P<subject>.+?)\s+nghia\s+la\s+(?:gi|sao)$",
            r"^y\s+(?P<subject>.+?)\s+la\s+(?:gi|sao|the nao)$",
        )
        for pattern in patterns:
            match = re.match(pattern, current)
            if not match:
                continue
            subject = match.group("subject").strip()
            generic = subject in {"cai do", "cai nay", "cau do", "cau nay", "do", "nay", "phan do", "y do"}
            if generic or token_overlap(subject, previous) >= 0.72:
                return subject
        return ""
