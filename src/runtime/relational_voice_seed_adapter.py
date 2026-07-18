"""Retired compatibility shim for the old relational voice-seed prepass.

The production chat path no longer classifies a turn, asks a style model for an
opening fragment, then asks the main model to continue that fragment. One model
now owns the entire public reply. These names remain only so old extensions do
not crash on import while migrating.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from domain import Decision


class ChatRegister(Enum):
    SOCIAL = "social"
    TASK = "task"


class VoiceSeedScope(Enum):
    OFF = "off"
    RELATIONAL = "relational"
    SOCIAL = "social"
    ALWAYS = "always"

    @classmethod
    def from_str(cls, raw: str | None) -> "VoiceSeedScope":
        return cls.OFF


class RelationalAct(Enum):
    NONE = "none"
    SELF_IDENTITY = "self_identity"
    AFFECTION = "affection"
    HAS_FEELINGS = "has_feelings"
    SADNESS = "sadness_loneliness"
    DISTANCE = "distance_coldness"


def normalize_text(raw: str) -> str:
    return " ".join(str(raw or "").lower().split())


def detect_relational_act(raw_user_text: str) -> RelationalAct:
    return RelationalAct.NONE


def classify_chat_register(
    raw_user_text: str,
    *,
    ti_mode: str = "",
    chat_act_name: str = "",
    looks_like_code: bool | None = None,
) -> ChatRegister:
    return ChatRegister.SOCIAL


def should_use_voice_seed(register: ChatRegister, scope: VoiceSeedScope, act: RelationalAct) -> bool:
    return False


@dataclass(slots=True, frozen=True)
class CognitionStance:
    register: ChatRegister = ChatRegister.SOCIAL
    scope: VoiceSeedScope = VoiceSeedScope.OFF
    act: RelationalAct = RelationalAct.NONE
    fe_tone: str = ""
    fe_intent: str = ""
    appraisal_context: str = ""
    adaptation_flags: tuple[str, ...] = ()
    flag_imperatives: tuple[str, ...] = ()
    preferred_distance: float = 0.0
    attachment_visibility: float = 0.0
    trust: float = 0.0
    conversation_prompt_context: str = ""


@dataclass(slots=True, frozen=True)
class RelationalVoiceSeedConfig:
    enabled: bool = False
    scope: VoiceSeedScope = VoiceSeedScope.OFF

    @classmethod
    def from_env(cls) -> "RelationalVoiceSeedConfig":
        return cls()


@dataclass(slots=True)
class RelationalVoiceSeedAdapter:
    llm_service: Any = None
    config: RelationalVoiceSeedConfig = field(default_factory=RelationalVoiceSeedConfig.from_env)
    logger: Any = None

    def try_answer(self, user_text: str, *, stance: CognitionStance | None = None) -> Optional[Decision]:
        return None


__all__ = [
    "ChatRegister",
    "VoiceSeedScope",
    "RelationalAct",
    "CognitionStance",
    "RelationalVoiceSeedConfig",
    "RelationalVoiceSeedAdapter",
    "normalize_text",
    "detect_relational_act",
    "classify_chat_register",
    "should_use_voice_seed",
]
