# -*- coding: utf-8 -*-
"""Typed semantic-frame invariants for the single chat authority.

PDF annotation, pages 12-13.  These checks validate logical consistency only;
they do not re-classify the user's sentence with regexes and therefore cannot
become a second semantic authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SemanticFrameValidation:
    frame: dict[str, Any]
    violations: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


def validate_semantic_frame(value: Mapping[str, Any] | None) -> SemanticFrameValidation:
    frame = dict(value or {})
    violations: list[str] = []

    frame["version"] = "semantic_frame.v1"
    for key in (
        "turn_kind", "discourse_relation", "user_act", "target",
        "ambiguity_owner", "boundary_action", "continuation_key",
        "evidence_scope", "tool_intent",
    ):
        frame[key] = str(frame.get(key, "") or "").strip()
    frame["literal_question"] = bool(frame.get("literal_question", False))
    frame["missing_evidence"] = [
        str(item).strip() for item in tuple(frame.get("missing_evidence", ()) or ())
        if str(item).strip()
    ][:8]

    obligation = dict(frame.get("reply_obligation", {}) or {})
    obligation = {
        "must_answer": bool(obligation.get("must_answer", True)),
        "must_not_broad_clarify": bool(obligation.get("must_not_broad_clarify", False)),
        "must_not_call_tool": bool(obligation.get("must_not_call_tool", False)),
    }

    # Logical invariants from the report.  Repair the metadata conservatively;
    # the public wording remains model-owned and is never rewritten here.
    if frame["ambiguity_owner"] == "assistant" and not obligation["must_not_broad_clarify"]:
        violations.append("assistant_owned_ambiguity_requires_no_broad_clarification")
        obligation["must_not_broad_clarify"] = True

    if frame["discourse_relation"].startswith("continuation_") and not frame["continuation_key"]:
        violations.append("continuation_requires_key")
        frame["continuation_key"] = "recent_assistant_thread"

    if frame["boundary_action"] and frame["boundary_action"] != "none":
        obligation["must_answer"] = True

    if frame["missing_evidence"] and not frame["evidence_scope"]:
        violations.append("missing_evidence_requires_scope")
        frame["evidence_scope"] = "user_message_plus_available_grounding"

    if frame["target"] == "assistant" and frame["user_act"] == "relational_check_in":
        if frame["tool_intent"] not in {"", "none"}:
            violations.append("assistant_check_in_must_not_call_tool")
        frame["tool_intent"] = "none"
        obligation["must_answer"] = True
        obligation["must_not_broad_clarify"] = True
        obligation["must_not_call_tool"] = True

    frame["reply_obligation"] = obligation
    return SemanticFrameValidation(frame=frame, violations=tuple(dict.fromkeys(violations)))


__all__ = ["SemanticFrameValidation", "validate_semantic_frame"]
