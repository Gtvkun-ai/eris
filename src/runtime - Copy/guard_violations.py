from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


GuardSeverity = Literal["hard", "soft"]
GuardRepairAction = Literal[
    "reroll",
    "soften",
    "suppress",
    "body_only",
    "static_fallback",
]


@dataclass(frozen=True, slots=True)
class GuardViolation:
    """Structured signal from a post-generation guard.

    A guard should describe what went wrong instead of becoming the final
    author of ERIS' public sentence.  Runtime code can then ask the wording
    layer to re-roll once, or fall back to a small deterministic line when the
    model path is unavailable.
    """

    rule: str
    severity: GuardSeverity
    reason: str
    original_text: str
    suggested_action: GuardRepairAction = "reroll"
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    trace_marker: str = ""
    fallback_text: str = ""

    def compact_trace(self) -> str:
        bits = [f"guard_violation={self.rule}"]
        if self.reason:
            bits.append(f"reason={self.reason}")
        if self.suggested_action:
            bits.append(f"action={self.suggested_action}")
        if self.missing_evidence:
            bits.append("missing=" + ",".join(self.missing_evidence))
        return "; ".join(bits)
