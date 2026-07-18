# -*- coding: utf-8 -*-
"""Machine-readable repository definition for ERIS runtime v4."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

REPOSITORY_DEFINITION_VERSION = "eris.repository.v4.generation_sovereignty"


@dataclass(frozen=True, slots=True)
class RepositoryDefinition:
    version: str = REPOSITORY_DEFINITION_VERSION
    semantic_owner: str = "configured_main_model"
    post_generation_role: str = "observe_and_record_consequences"
    final_text_mutation: str = "forbidden"
    second_generation_pass: str = "forbidden_after_valid_decision"
    deception_policy: str = "record_ground_truth_and_continuity_not_rewrite"
    output_hygiene: str = "secret_protocol_and_transport_only"
    behavior_feedback_timing: str = "next_generation_pre_prompt"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    def prompt_block(self) -> str:
        return (
            f"REPOSITORY_CONTRACT={self.version}. "
            "The configured main model owns semantic interpretation and the first valid public Decision. "
            "Observers, memory, social cognition, critics and former guards may provide evidence before generation "
            "or record consequences for a later turn. They may not regenerate, rewrite, suppress, shorten, or replace "
            "semantic public text after a valid Decision exists. Deliberate deception is tracked with internal ground "
            "truth and continuity obligations, not corrected by a moralizing final editor. Output hygiene is limited "
            "to secrets, protocol leakage, malformed transport, and stage-tag separation."
        )


CURRENT_REPOSITORY_DEFINITION = RepositoryDefinition()


def repository_definition_payload() -> dict[str, Any]:
    return CURRENT_REPOSITORY_DEFINITION.to_payload()


def generation_contract_prompt() -> str:
    return CURRENT_REPOSITORY_DEFINITION.prompt_block()


__all__ = [
    "CURRENT_REPOSITORY_DEFINITION",
    "REPOSITORY_DEFINITION_VERSION",
    "RepositoryDefinition",
    "generation_contract_prompt",
    "repository_definition_payload",
]
