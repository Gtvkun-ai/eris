# -*- coding: utf-8 -*-
"""Neo deterministic mỏng cho các câu hỏi sửa/giải thích phát ngôn ngay trước đó.

Main model vẫn sở hữu lời public. Module này chỉ chỉ ra khi user đang trỏ vào một
cụm vừa được ERIS nói, để planner không hiểu nó thành biệt danh mới, yêu cầu tool,
hay một màn phân tích tính cách vô duyên.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import IntentionPlan


def _norm(text: Any) -> str:
    value = unicodedata.normalize("NFD", str(text or "").casefold()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_#+.()\-]+", " ", value).strip()


def _compact(text: Any, limit: int = 360) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: max(0, limit - 3)].rstrip() + "..."


def _last_assistant_text(history: Sequence[Mapping[str, Any] | str]) -> str:
    for item in reversed(tuple(history or ())):
        if isinstance(item, Mapping):
            role = str(item.get("role", "") or "").strip().lower()
            if role != "assistant":
                continue
            text = item.get("content", item.get("text", ""))
            if str(text or "").strip():
                return _compact(text, 1000)
        elif str(item or "").strip():
            # Chỉ dùng string làm fallback khi history không có role.
            return _compact(item, 1000)
    return ""


def _token_overlap(needle: str, haystack: str) -> float:
    needle_tokens = {token for token in re.findall(r"[a-z0-9_#+.\-]+", _norm(needle)) if len(token) >= 2}
    haystack_tokens = set(re.findall(r"[a-z0-9_#+.\-]+", _norm(haystack)))
    if not needle_tokens:
        return 0.0
    return len(needle_tokens & haystack_tokens) / len(needle_tokens)


@dataclass(frozen=True, slots=True)
class ReferenceRepairContext:
    active: bool = False
    kind: str = "none"
    confidence: float = 0.0
    previous_assistant_text: str = ""
    referenced_phrase: str = ""
    instruction: str = ""

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return ("history:last_assistant",) if self.active else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "kind": self.kind,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 3),
            "previous_assistant_text": self.previous_assistant_text,
            "referenced_phrase": self.referenced_phrase,
            "instruction": self.instruction,
            "evidence_refs": list(self.evidence_refs),
        }

    def prompt_context(self) -> str:
        if not self.active:
            return ""
        return (
            "reference_repair_contract:\n"
            f"- kind: {self.kind}\n"
            f"- previous_assistant_text: {self.previous_assistant_text}\n"
            f"- referenced_phrase: {self.referenced_phrase or '<implicit previous claim>'}\n"
            f"- instruction: {self.instruction}\n"
            "- Answer the literal clarification first. Do not reinterpret the phrase as a nickname, user trait, emotional bid, or tool request.\n"
            "- If the previous wording was misleading, acknowledge and correct it directly before adding any personality."
        )


def resolve_reference_repair(
    user_text: str,
    recent_history: Sequence[Mapping[str, Any] | str],
) -> ReferenceRepairContext:
    previous = _last_assistant_text(recent_history)
    if not previous:
        return ReferenceRepairContext()

    raw = re.sub(r"\s+", " ", str(user_text or "")).strip()
    normalized = _norm(raw)
    if not normalized:
        return ReferenceRepairContext()

    # "Eris debug là bạn á?", "cái đó là em hả?", "X có phải bạn không?"
    identity_patterns = (
        r"^(?P<subject>.+?)\s+la\s+(?:ban|em|eris)(?:\s+(?:a|ah|ha|ha|khong|dung khong|phai khong))?$",
        r"^(?P<subject>.+?)\s+co phai\s+(?:ban|em|eris)(?:\s+khong)?$",
        r"^(?P<subject>.+?)\s+phai\s+(?:ban|em|eris)(?:\s+khong)?$",
    )
    for pattern in identity_patterns:
        match = re.match(pattern, normalized)
        if not match:
            continue
        subject = _compact(match.group("subject"), 120)
        generic = subject in {"cai do", "cai nay", "no", "do", "nay"}
        overlap = 1.0 if generic else _token_overlap(subject, previous)
        if generic or overlap >= 0.60:
            return ReferenceRepairContext(
                active=True,
                kind="clarify_previous_reference_identity",
                confidence=0.94 if overlap >= 0.85 else 0.84,
                previous_assistant_text=previous,
                referenced_phrase=subject,
                instruction=(
                    "Resolve whether the referenced phrase in the previous ERIS message denotes ERIS herself. "
                    "Explain its literal runtime/window meaning in one direct sentence."
                ),
            )

    # "là em nghĩ tôi sẽ làm gì đó hả", "ý em là tôi đang định thay đổi gì à"
    assumption_markers = (
        "la em nghi toi se", "la ban nghi toi se", "y em la toi", "y ban la toi",
        "em dang nghi toi", "ban dang nghi toi", "em cho rang toi", "ban cho rang toi",
    )
    if any(marker in normalized for marker in assumption_markers):
        return ReferenceRepairContext(
            active=True,
            kind="challenge_previous_assumption",
            confidence=0.90,
            previous_assistant_text=previous,
            referenced_phrase="previous implied assumption",
            instruction=(
                "Check the previous ERIS sentence for an unsupported assumption about what the user would do, "
                "change, start, or feel. Answer yes/no directly and repair the assumption instead of reversing subjects."
            ),
        )

    clarification_markers = (
        "cai do la gi", "cai nay la gi", "y em la gi", "y ban la gi", "tuc la sao",
        "nghia la gi", "sao co", "em noi cai gi vay", "ban noi cai gi vay",
    )
    if any(marker in normalized for marker in clarification_markers):
        return ReferenceRepairContext(
            active=True,
            kind="clarify_previous_statement",
            confidence=0.82,
            previous_assistant_text=previous,
            referenced_phrase="previous statement",
            instruction="Explain the previous ERIS statement literally and briefly; do not invent a new premise.",
        )

    return ReferenceRepairContext()


def apply_reference_repair_to_plan(
    plan: IntentionPlan,
    context: ReferenceRepairContext,
) -> IntentionPlan:
    if not context.active:
        return plan
    data = plan.to_dict()
    refs = tuple(dict.fromkeys((*plan.evidence_refs, *context.evidence_refs)))[:5]
    data.update(
        {
            "speak": True,
            "motive": "repair_previous_miss",
            "strategy": "direct_repair",
            "value_focus": "accuracy",
            "topic": context.instruction,
            "importance": max(0.82, float(plan.importance or 0.0)),
            "intrusion_risk": 0.0,
            "confidence": max(0.88, float(plan.confidence or 0.0)),
            "performance_hint": "repair",
            "tool_intent": "",
            "tool_input": "",
            "evidence_refs": list(refs),
            "notes": f"reference repair: {context.kind}",
        }
    )
    return IntentionPlan.from_mapping(data, channel="chat")


__all__ = [
    "ReferenceRepairContext",
    "apply_reference_repair_to_plan",
    "resolve_reference_repair",
]
