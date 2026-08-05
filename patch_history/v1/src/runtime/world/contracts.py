# -*- coding: utf-8 -*-
"""Typed actuator and sandbox contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol

from cortex.subject.contracts import ActionRequest, OutcomeStatus, WorldOutcome


class SandboxCommandKind(StrEnum):
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"
    HTTP_REQUEST = "http_request"
    BODY_FRAME = "body_frame"
    TTS = "tts"
    SIMULATE = "simulate"


@dataclass(frozen=True, slots=True)
class CapabilityToken:
    token_id: str
    subject_id: str
    capabilities: frozenset[str]
    issued_at: float
    expires_at: float
    policy_version: str
    scope: Mapping[str, Any] = field(default_factory=dict)

    def permits(self, capability: str, *, now: float) -> bool:
        return self.issued_at <= now <= self.expires_at and capability in self.capabilities


@dataclass(frozen=True, slots=True)
class SandboxCommand:
    command_id: str
    action_id: str
    decision_id: str
    kind: SandboxCommandKind | str
    arguments: Mapping[str, Any]
    requested_capability: str
    idempotency_key: str
    created_at: float
    simulate: bool = False


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    request: ActionRequest
    outcome: WorldOutcome
    policy_transforms: tuple[str, ...] = ()
    rollback_handle: str | None = None

    def to_world_outcome(self) -> WorldOutcome:
        return self.outcome


class SandboxPort(Protocol):
    async def apply(self, command: SandboxCommand, capability: CapabilityToken) -> WorldOutcome: ...


class ActuatorPort(Protocol):
    async def execute(self, request: ActionRequest) -> ActionReceipt: ...
