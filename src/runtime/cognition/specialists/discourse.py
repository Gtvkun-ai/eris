# -*- coding: utf-8 -*-
"""DiscourseCortex: hiểu quan hệ giữa lượt mới và lời public gần nhất.

Module này không đánh giá tính cách và không viết câu trả lời. Việc duy nhất của
nó là xác định: user đang nối cái gì, sự mơ hồ thuộc về ai và move kế tiếp hợp lý.
"""

from __future__ import annotations

import re

from core.cognition import CognitiveFrame, DiscourseProjection
from runtime.cognition.normalization import contains_phrase, normalize_vi, token_overlap


class DiscourseCortex:
    CONTINUATION_PHRASES = (
        "rồi sao", "roi sao", "thế rồi sao", "the roi sao", "xong rồi sao", "xong roi sao",
        "tiếp đi", "tiep di", "nói tiếp", "noi tiep", "kể tiếp", "ke tiep", "nữa đi", "nua di",
        "rồi", "roi", "xong", "nữa", "nua", "thì sao", "thi sao", "sau đó", "sau do",
    )
    CLOSE_PHRASES = ("thôi bỏ đi", "thoi bo di", "khỏi", "khoi", "được rồi", "duoc roi")
    CRITICISM_MARKERS = (
        "generic", "chung chung", "vô hồn", "vo hon", "máy móc", "may moc", "như bot", "nhu bot",
        "support bot", "cộc", "coc", "lạnh", "lanh", "khô khan", "kho khan", "rỗng", "rong",
        "không đúng ý", "khong dung y", "làm màu", "lam mau", "thẳng quá", "thang qua",
    )
    ASSISTANT_MARKERS = (
        "bạn nói", "ban noi", "em nói", "em noi", "câu vừa rồi", "cau vua roi", "câu này", "cau nay",
        "trả lời", "tra loi", "eris nói", "eris noi",
    )

    def project(self, frame: CognitiveFrame) -> DiscourseProjection:
        current = normalize_vi(frame.user_text)
        previous = frame.last_assistant_text
        refs = ("turn:user_text", "history:last_assistant") if previous else ("turn:user_text",)
        if not current:
            return DiscourseProjection(confidence=0.2, ambiguity=0.9, evidence_ids=("turn:user_text",))

        if previous and contains_phrase(current, *self.CLOSE_PHRASES):
            return DiscourseProjection(
                relation="close_topic",
                ambiguity_owner="shared",
                expected_next_move="acknowledge_close",
                assistant_fault_probability=0.05,
                confidence=0.88,
                ambiguity=0.08,
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
            confidence=0.64,
            ambiguity=0.34,
            evidence_ids=("turn:user_text",),
        )

    def _is_continuation_bid(self, current: str) -> bool:
        stripped = current.strip(" ?.")
        if contains_phrase(stripped, *self.CONTINUATION_PHRASES):
            return len(stripped.split()) <= 8
        # "ehm/ừm, rồi sao á" và các filler tương tự.
        without_fillers = re.sub(r"^(?:eh+m+|uh+m+|um+|ừ+m+|ờ+m+|à+)\s+", "", stripped).strip()
        return contains_phrase(without_fillers, *self.CONTINUATION_PHRASES) and len(without_fillers.split()) <= 8

    def _is_criticism(self, current: str) -> bool:
        has_defect = contains_phrase(current, *self.CRITICISM_MARKERS)
        points_to_assistant = contains_phrase(current, *self.ASSISTANT_MARKERS)
        return has_defect and (points_to_assistant or len(current.split()) <= 8)

    @staticmethod
    def _challenges_assumption(current: str) -> bool:
        markers = (
            "là em nghĩ tôi sẽ", "la em nghi toi se", "là bạn nghĩ tôi sẽ", "la ban nghi toi se",
            "ý em là tôi", "y em la toi", "ý bạn là tôi", "y ban la toi", "em cho rằng tôi", "em cho rang toi",
            "bạn cho rằng tôi", "ban cho rang toi",
        )
        return contains_phrase(current, *markers)

    @staticmethod
    def _generic_clarification(current: str) -> bool:
        markers = (
            "cái đó là gì", "cai do la gi", "cái này là gì", "cai nay la gi", "ý em là gì", "y em la gi",
            "ý bạn là gì", "y ban la gi", "tức là sao", "tuc la sao", "nghĩa là gì", "nghia la gi",
            "em nói cái gì vậy", "em noi cai gi vay", "bạn nói cái gì vậy", "ban noi cai gi vay",
        )
        return contains_phrase(current, *markers)

    @staticmethod
    def _looks_open_ended(previous: str) -> bool:
        text = str(previous or "").strip()
        if not text:
            return False
        return text.endswith(("...", "…", ":", "-")) or any(
            marker in normalize_vi(text)
            for marker in ("nhung", "con", "phan con lai", "roi thi", "khong de", "khong on")
        )

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
