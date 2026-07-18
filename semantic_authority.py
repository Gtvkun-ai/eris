"""Single-owner policy for public chat generation.

The configured main model interprets the whole user turn and owns the first
valid public Decision. Legacy markers, critics and directors may remain for
telemetry or non-chat compatibility, but they are not fed back into chat text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticAuthorityPolicy:
    mode: str = "primary_model"
    primary_reasoning_effort: str = "medium"
    support_confidence_threshold: float = 0.48
    include_chat_act_markers_setting: bool = False
    include_director_prompt_setting: bool = False
    enforce_response_contract_setting: bool = False
    director_candidate_mode: str = "off"
    critique_mode: str = "off"
    low_quality_fail_open_setting: bool = True
    max_constrained_reruns: int = 0
    allow_domain_fallback: bool = False
    final_passthrough_setting: bool = True

    @classmethod
    def from_runtime(cls) -> "SemanticAuthorityPolicy":
        try:
            from runtime.runtime_settings_store import get_runtime_settings_store

            store = get_runtime_settings_store()
            chat = store.get("chat", default={}) or {}
            mode = str(chat.get("semantic_authority_mode", "primary_model") or "primary_model").strip().lower()
            effort = str(chat.get("reasoning_effort", "medium") or "medium").strip().lower()
            threshold = float(chat.get("support_confidence_threshold", 0.48) or 0.48)
            candidate_mode = str(chat.get("director_candidate_mode", "off") or "off").strip().lower()
            critique_mode = str(chat.get("critique_mode", "off") or "off").strip().lower()
            second_pass = str(chat.get("director_second_pass", "off") or "off").strip().lower()
            # ``director_second_pass=off`` is a stronger local override.
            if second_pass == "off":
                candidate_mode = "off"
            elif second_pass == "always" and candidate_mode != "off":
                candidate_mode = "always"
            return cls(
                mode=mode if mode in {"primary_model", "qwen_first", "legacy"} else "primary_model",
                primary_reasoning_effort=effort if effort in {"low", "medium", "high"} else "medium",
                support_confidence_threshold=max(0.05, min(0.95, threshold)),
                include_chat_act_markers_setting=False,
                include_director_prompt_setting=False,
                enforce_response_contract_setting=False,
                director_candidate_mode="off",
                critique_mode="off",
                low_quality_fail_open_setting=True,
                max_constrained_reruns=0,
                allow_domain_fallback=False,
                # Raw final passthrough là invariant kiến trúc, không đọc toggle.
                final_passthrough_setting=True,
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
        return self.mode in {"primary_model", "qwen_first"}

    @property
    def primary_model_first(self) -> bool:
        """Clear name for the production invariant; qwen_first stays as an import shim."""
        return self.qwen_first

    @property
    def allow_pre_llm_intercepts(self) -> bool:
        # Main model receives the turn first. Exact tools/actions are executed from
        # its structured Decision instead of Python phrase detectors answering hộ.
        return False

    @property
    def allow_tutor_prepass(self) -> bool:
        return not self.qwen_first

    @property
    def allow_relational_pre_llm_intercept(self) -> bool:
        """Không cho Python trả lời hộ model ở các lượt xã hội mở."""
        return False

    @property
    def include_chat_act_markers(self) -> bool:
        return False

    @property
    def include_director_prompt(self) -> bool:
        return False

    @property
    def final_passthrough(self) -> bool:
        return bool(self.final_passthrough_setting)

    @property
    def generate_director_candidates(self) -> bool:
        return False if self.final_passthrough else self.director_candidate_mode != "off"

    @property
    def hard_only_final_guards(self) -> bool:
        return bool(self.final_passthrough)

    @property
    def enforce_response_contract(self) -> bool:
        return False if self.final_passthrough else self.enforce_response_contract_setting

    @property
    def low_quality_fail_open(self) -> bool:
        return True if self.final_passthrough else self.low_quality_fail_open_setting

    @property
    def bounded_refine_enabled(self) -> bool:
        return False if self.final_passthrough else (
            self.critique_mode == "bounded_refine" and self.max_constrained_reruns > 0
        )

    @property
    def primary_uses_escalation_client(self) -> bool:
        return False if self.qwen_first else False

    def prompt_block(self) -> str:
        if not self.qwen_first:
            return ""
        return (
            "The configured main model owns whole-turn meaning and final wording. "
            "Use history, evidence and memory as context only; ignore runtime labels that conflict with the user's sentence."
        )


# Tên mới dùng trong tài liệu kiến trúc; alias giữ toàn bộ import cũ sống sót.
GenerationAuthorityPolicy = SemanticAuthorityPolicy

__all__ = ["SemanticAuthorityPolicy", "GenerationAuthorityPolicy"]
