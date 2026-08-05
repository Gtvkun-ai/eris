# -*- coding: utf-8 -*-
"""Capability policy for the resistant world boundary."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .contracts import CapabilityToken, SandboxCommand, SandboxCommandKind


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    executable_allowlist: frozenset[str]
    workspace_root: str
    network_enabled: bool = False
    allowed_network_hosts: frozenset[str] = frozenset()
    max_runtime_seconds: int = 30
    max_output_bytes: int = 1_000_000
    max_memory_mb: int = 512
    environment_allowlist: frozenset[str] = frozenset()
    writable: bool = True
    policy_version: str = "sandbox-policy-v1"

    def __post_init__(self) -> None:
        if self.max_runtime_seconds <= 0 or self.max_output_bytes <= 0 or self.max_memory_mb <= 0:
            raise ValueError("resource limits must be positive")
        object.__setattr__(self, "workspace_root", str(Path(self.workspace_root).resolve()))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    transforms: tuple[str, ...] = ()
    resolved_path: str | None = None


class CapabilityPolicy:
    def __init__(self, command_policy: CommandPolicy) -> None:
        self.command_policy = command_policy

    def _resolve_workspace_path(self, raw_path: str) -> Path:
        root = Path(self.command_policy.workspace_root).resolve()
        candidate = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PermissionError("path escapes workspace") from exc
        return candidate

    def authorize(self, command: SandboxCommand, token: CapabilityToken, *, now: float) -> PolicyDecision:
        if not token.permits(command.requested_capability, now=now):
            return PolicyDecision(False, "capability_missing_or_expired")
        kind = command.kind if isinstance(command.kind, SandboxCommandKind) else SandboxCommandKind(str(command.kind))
        args = dict(command.arguments)
        if kind in (SandboxCommandKind.READ_FILE, SandboxCommandKind.WRITE_FILE):
            try:
                path = self._resolve_workspace_path(str(args.get("path") or ""))
            except PermissionError:
                return PolicyDecision(False, "path_outside_workspace")
            if kind is SandboxCommandKind.WRITE_FILE and not self.command_policy.writable:
                return PolicyDecision(False, "workspace_read_only")
            return PolicyDecision(True, resolved_path=str(path))
        if kind is SandboxCommandKind.RUN_COMMAND:
            argv = args.get("argv")
            if not isinstance(argv, (list, tuple)) or not argv:
                return PolicyDecision(False, "argv_required")
            executable = Path(str(argv[0])).name
            if executable not in self.command_policy.executable_allowlist:
                return PolicyDecision(False, "executable_not_allowlisted")
            if any(any(token in str(arg) for token in (";", "&&", "||", "`", "$(`")) for arg in argv):
                return PolicyDecision(False, "shell_metacharacters_denied")
            return PolicyDecision(True)
        if kind is SandboxCommandKind.HTTP_REQUEST:
            if not self.command_policy.network_enabled:
                return PolicyDecision(False, "network_disabled")
            host = str(args.get("host") or "").lower()
            if host not in self.command_policy.allowed_network_hosts:
                return PolicyDecision(False, "host_not_allowlisted")
            return PolicyDecision(True)
        if kind in (SandboxCommandKind.BODY_FRAME, SandboxCommandKind.TTS, SandboxCommandKind.SIMULATE):
            return PolicyDecision(True)
        return PolicyDecision(False, "unsupported_command_kind")

    def filtered_environment(self, source: Mapping[str, str] | None = None) -> dict[str, str]:
        source = dict(source or os.environ)
        return {key: value for key, value in source.items() if key in self.command_policy.environment_allowlist}
