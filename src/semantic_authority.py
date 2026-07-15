"""Central policy for who is allowed to interpret a user turn.

``qwen_first`` keeps Qwen as semantic authority while TurnFrame/contract/gate
provide evidence and binding obligations. Policy now comes from
``RuntimeSettingsStore``; env remains a bootstrap fallback, not twelve tiny
kings ruling twelve different modules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticAuthorityPolicy:
    mode: str = "qwen_first"
    primary_reasoning_effort: str = "medium"
    support_confidence_threshold: float = 0.48
    include_chat_act_markers_setting: bool = True
    include_director_prompt_setting: bool = True
    enforce_response_contract_setting: bool = True
    director_candidate_mode: str = "adaptive"
    critique_mode: str = "bounded_refine"
    low_quality_fail_open_setting: bool = False
    max_constrained_reruns: int = 1
    allow_domain_fallback: bool = True

    @classmethod
    def from_runtime(cls) -> "SemanticAuthorityPolicy":
        try:
            from runtime.runtime_settings_store import get_runtime_settings_store

            store = get_runtime_settings_store()
            chat = store.get("chat", default={}) or {}
            mode = str(chat.get("semantic_authority_mode", "qwen_first") or "qwen_first").strip().lower()
            effort = str(chat.get("reasoning_effort", "medium") or "medium").strip().lower()
            threshold = float(chat.get("support_confidence_threshold", 0.48) or 0.48)
            candidate_mode = str(chat.get("director_candidate_mode", "adaptive") or "adaptive").strip().lower()
            critique_mode = str(chat.get("critique_mode", "bounded_refine") or "bounded_refine").strip().lower()
            second_pass = str(chat.get("director_second_pass", "adaptive") or "adaptive").strip().lower()
            # ``director_second_pass=off`` is a stronger local override.
            if second_pass == "off":
                candidate_mode = "off"
            elif second_pass == "always" and candidate_mode != "off":
                candidate_mode = "always"
            return cls(
                mode=mode if mode in {"qwen_first", "legacy"} else "qwen_first",
                primary_reasoning_effort=effort if effort in {"low", "medium", "high"} else "medium",
                support_confidence_threshold=max(0.05, min(0.95, threshold)),
                include_chat_act_markers_setting=True,
                include_director_prompt_setting=True,
                enforce_response_contract_setting=bool(chat.get("response_contract_gate", True)),
                director_candidate_mode=candidate_mode if candidate_mode in {"off", "adaptive", "always"} else "adaptive",
                critique_mode=critique_mode if critique_mode in {"off", "advisory", "bounded_refine"} else "bounded_refine",
                low_quality_fail_open_setting=bool(chat.get("low_quality_fail_open", False)),
                max_constrained_reruns=max(0, min(2, int(chat.get("max_constrained_reruns", 1) or 0))),
                allow_domain_fallback=bool(chat.get("auto_fallback", True)),
            )
        except Exception:
            return cls()

    @classmethod
    def from_env(cls) -> "SemanticAuthorityPolicy":
        """Compatibility name used across the repo.

        RuntimeSettingsStore itself bootstraps from env on first load, so callers
        using this old method still receive the new source of truth.
        """

        return cls.from_runtime()

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
        return self.include_chat_act_markers_setting

    @property
    def include_director_prompt(self) -> bool:
        return self.include_director_prompt_setting

    @property
    def generate_director_candidates(self) -> bool:
        return self.director_candidate_mode != "off"

    @property
    def hard_only_final_guards(self) -> bool:
        return False

    @property
    def enforce_response_contract(self) -> bool:
        return self.enforce_response_contract_setting

    @property
    def low_quality_fail_open(self) -> bool:
        return self.low_quality_fail_open_setting

    @property
    def bounded_refine_enabled(self) -> bool:
        return self.critique_mode == "bounded_refine" and self.max_constrained_reruns > 0

    @property
    def primary_uses_escalation_client(self) -> bool:
        return False if self.qwen_first else False

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
        low_but_intentional = 0.0 < confidence < self.support_confidence_threshold
        return explicit or (bool(text) and low_but_intentional)

    def prompt_block(self) -> str:
        if not self.qwen_first:
            return ""
        return (
            "PRIMARY SEMANTIC AUTHORITY = QWEN. Interpret the whole user utterance together with "
            "conversation history. Runtime intent labels, memory matches, turn-semantics labels, "
            "emotion labels and keyword detectors are advisory evidence only; they are never commands. "
            "Never let an isolated token override the grammatical and conversational meaning of the "
            "complete message. Memory supplies facts, not a ready-made answer. Choose system_action "
            "yourself only when a real tool is needed. If the answer is possible but your draft lacks "
            "depth or ideas, keep the best honest draft, lower confidence and add reasoning tag "
            "'mentor_support'. Qwen still writes the final public reply."
        )


# Tên mới dùng trong tài liệu kiến trúc; alias giữ toàn bộ import cũ sống sót.
GenerationAuthorityPolicy = SemanticAuthorityPolicy

__all__ = ["SemanticAuthorityPolicy", "GenerationAuthorityPolicy"]
