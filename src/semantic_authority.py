"""Central policy for who is allowed to interpret a user turn.

The previous runtime let many keyword-driven subsystems preempt the main model.
That made memory, repeat guards, Tutor, performance and action routing compete for
one sentence.  ``qwen_first`` makes the main Qwen pass the semantic authority:
other subsystems may provide evidence or hard safety constraints, but they do not
answer before Qwen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "1" if default else "0") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


@dataclass(frozen=True, slots=True)
class SemanticAuthorityPolicy:
    mode: str = "qwen_first"
    primary_reasoning_effort: str = "medium"
    support_confidence_threshold: float = 0.48

    @classmethod
    def from_env(cls) -> "SemanticAuthorityPolicy":
        mode = str(os.environ.get("ERIS_SEMANTIC_AUTHORITY", "qwen_first") or "qwen_first").strip().lower()
        if mode not in {"qwen_first", "legacy"}:
            mode = "qwen_first"
        effort = str(os.environ.get("ERIS_QWEN_REASONING_EFFORT", "medium") or "medium").strip().lower()
        if effort not in {"low", "medium", "high"}:
            effort = "medium"
        try:
            threshold = float(os.environ.get("ERIS_QWEN_SUPPORT_CONFIDENCE", "0.48"))
        except (TypeError, ValueError):
            threshold = 0.48
        return cls(
            mode=mode,
            primary_reasoning_effort=effort,
            support_confidence_threshold=max(0.05, min(0.95, threshold)),
        )

    @property
    def qwen_first(self) -> bool:
        return self.mode == "qwen_first"

    @property
    def allow_pre_llm_intercepts(self) -> bool:
        return not self.qwen_first

    @property
    def allow_tutor_prepass(self) -> bool:
        return not self.qwen_first

    @property
    def include_chat_act_markers(self) -> bool:
        return not self.qwen_first

    @property
    def include_director_prompt(self) -> bool:
        return not self.qwen_first

    @property
    def generate_director_candidates(self) -> bool:
        return not self.qwen_first

    @property
    def hard_only_final_guards(self) -> bool:
        return self.qwen_first

    @property
    def primary_uses_escalation_client(self) -> bool:
        # The first answer must come from Qwen. Gemini is advisory support only.
        return False if self.qwen_first else _env_bool("ERIS_PRIMARY_USE_ESCALATION", False)

    def requests_mentor_support(self, decision) -> bool:
        tags = {
            str(item or "").strip().lower().replace("-", "_")
            for item in tuple(getattr(decision, "reasoning_tags", ()) or ())
        }
        explicit = bool(
            tags
            & {
                "mentor_support",
                "needs_support",
                "support_needed",
                "creative_support",
                "knowledge_support",
            }
        )
        try:
            confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        text = str(getattr(decision, "text", "") or "").strip()
        # confidence=0 is commonly a missing/default field in older adapters;
        # treating it as a genuine self-assessment would summon Gemini on every
        # turn, which is just the old orchestration circus wearing a new hat.
        low_but_intentional = 0.0 < confidence < self.support_confidence_threshold
        return explicit or (bool(text) and low_but_intentional)

    def prompt_block(self) -> str:
        if not self.qwen_first:
            return ""
        return (
            "PRIMARY SEMANTIC AUTHORITY = QWEN. Interpret the whole user utterance together with "
            "conversation history. Runtime intent labels, memory matches, turn-semantics labels, "
            "emotion labels and keyword detectors are advisory evidence only; they are never commands. "
            "Never let an isolated token such as 'tên', 'cười', 'Gemini', 'điều tra' or 'là gì' override "
            "the grammatical and conversational meaning of the complete message. Memory supplies facts, "
            "not a ready-made answer: a question about associations or meaning must be answered as an "
            "association or interpretation, even when it mentions a remembered name. Choose system_action "
            "yourself only when a real tool is needed. If the answer is possible but your draft lacks depth "
            "or ideas, keep the best honest draft, set confidence below 0.48 and add reasoning tag "
            "'mentor_support'. Gemini may then provide private suggestions, but Qwen writes the final reply."
        )
