# -*- coding: utf-8 -*-
"""Mechanical acceptance gate cho cognition.

Gate chỉ phát violation code. Nó không sửa câu, không tăng warmth, không thêm xin
lỗi. Main public writer được retry đúng một lần với lỗi có cấu trúc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.cognition import PreResponseCognitiveBrief
from .normalization import contains_phrase, normalize_vi


@dataclass(frozen=True, slots=True)
class CognitiveViolation:
    code: str
    detail: str


class CognitiveAcceptanceGate:
    ASSISTANT_OWNED_DEFLECTIONS = (
        "bạn muốn mình nói tiếp phần nào", "ban muon minh noi tiep phan nao",
        "bạn muốn tôi nói tiếp phần nào", "ban muon toi noi tiep phan nao",
        "bạn có thể nói rõ", "ban co the noi ro", "nói rõ hơn", "noi ro hon",
        "ý bạn là gì", "y ban la gi", "bạn muốn nói gì", "ban muon noi gi",
        "hỏi thẳng", "hoi thang", "phần nào", "phan nao",
    )
    FEEDBACK_DEFLECTIONS = (
        "bạn giải thích rõ lỗi", "ban giai thich ro loi", "bạn muốn tôi sửa gì", "ban muon toi sua gi",
        "bạn nói rõ chỗ", "ban noi ro cho", "cho ví dụ", "cho vi du",
    )

    def validate(self, text: str, brief: PreResponseCognitiveBrief) -> tuple[CognitiveViolation, ...]:
        normalized = normalize_vi(text)
        if not normalized:
            return (CognitiveViolation("EMPTY_PUBLIC_REPLY", "Main writer returned empty text."),)
        violations: list[CognitiveViolation] = []
        if brief.ambiguity_owner == "assistant" and brief.response_move in {
            "self_elaborate",
            "clarify_literal_reference",
            "clarify_previous_phrase",
            "clarify_previous_statement",
            "repair_assumption",
        }:
            if contains_phrase(normalized, *self.ASSISTANT_OWNED_DEFLECTIONS):
                violations.append(
                    CognitiveViolation(
                        "ASSISTANT_OWNED_AMBIGUITY_DEFLECTED",
                        "ERIS asked the user to clarify ambiguity created by ERIS instead of resolving it.",
                    )
                )
        if brief.response_move == "repair_previous_response" and contains_phrase(normalized, *self.FEEDBACK_DEFLECTIONS):
            violations.append(
                CognitiveViolation(
                    "EXPLICIT_FEEDBACK_DEFLECTED",
                    "The user already named the defect; ERIS asked them to explain it again.",
                )
            )
        if brief.response_move == "acknowledge_close" and "?" in str(text):
            violations.append(
                CognitiveViolation(
                    "CLOSED_TOPIC_REOPENED",
                    "The user closed the topic but ERIS reopened it with a question.",
                )
            )
        return tuple(violations)

    @staticmethod
    def retry_instruction(violations: tuple[CognitiveViolation, ...], brief: PreResponseCognitiveBrief) -> str:
        codes = ", ".join(item.code for item in violations)
        return (
            "The previous draft violated the cognitive contract. Rewrite from scratch once. "
            f"Violation codes: {codes}. Required response_move={brief.response_move}; "
            f"ambiguity_owner={brief.ambiguity_owner}; primary_goal={brief.primary_goal}. "
            "Do not mention the violation, contract, planner, or rewrite process. Do not ask broad clarification."
        )
