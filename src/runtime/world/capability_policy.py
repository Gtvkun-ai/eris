# -*- coding: utf-8 -*-
"""Capability policy for the resistant world boundary.

The policy validates authority, scope and command shape before the sandbox does
anything observable.  It is intentionally boring.  Boring authorization code
is one of civilization's less glamorous achievements.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import CapabilityToken, SandboxCommand, SandboxCommandKind


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    executable_allowlist: frozenset[str]
    workspace_root: str
    network_enabled: bool = False
    allowed_network_hosts: frozenset[str] = frozenset()
    allowed_http_methods: frozenset[str] = frozenset({"GET", "HEAD", "POST"})
    max_runtime_seconds: int = 30
    max_output_bytes: int = 1_000_000
    max_memory_mb: int = 512
    max_command_age_seconds: float = 300.0
    max_future_skew_seconds: float = 30.0
    environment_allowlist: frozenset[str] = frozenset()
    writable: bool = True
    allow_symlinks: bool = False
    allow_executable_paths: bool = False
    policy_version: str = "v1"

    def __post_init__(self) -> None:
        if self.max_runtime_seconds <= 0 or self.max_output_bytes <= 0 or self.max_memory_mb <= 0:
            raise ValueError("resource limits must be positive")
        if self.max_command_age_seconds <= 0 or self.max_future_skew_seconds < 0:
            raise ValueError("command time limits must be valid")
        object.__setattr__(self, "workspace_root", str(Path(self.workspace_root).resolve()))
        object.__setattr__(self, "executable_allowlist", frozenset(str(item) for item in self.executable_allowlist))
        object.__setattr__(self, "allowed_network_hosts", frozenset(str(item).lower() for item in self.allowed_network_hosts))
        object.__setattr__(self, "allowed_http_methods", frozenset(str(item).upper() for item in self.allowed_http_methods))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    transforms: tuple[str, ...] = ()
    resolved_path: str | None = None


class CapabilityPolicy:
    def __init__(self, command_policy: CommandPolicy) -> None:
        self.command_policy = command_policy

    def _contains_symlink(self, root: Path, candidate: Path) -> bool:
        if self.command_policy.allow_symlinks:
            return False
        current = root
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return True
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                return True
        return False

    def _resolve_workspace_path(self, raw_path: str) -> Path:
        if not raw_path.strip():
            raise ValueError("path required")
        if "\x00" in raw_path:
            raise ValueError("nul byte denied")
        root = Path(self.command_policy.workspace_root).resolve()
        raw = Path(raw_path)
        lexical = Path(os.path.abspath(str(root / raw if not raw.is_absolute() else raw)))
        try:
            lexical.relative_to(root)
        except ValueError as exc:
            raise PermissionError("path escapes workspace") from exc
        if self._contains_symlink(root, lexical):
            raise RuntimeError("symlink path denied")
        candidate = lexical.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PermissionError("path escapes workspace") from exc
        return candidate

    def revalidate_path(self, path: str | os.PathLike[str]) -> Path:
        """Re-check a previously authorized path immediately before I/O."""
        root = Path(self.command_policy.workspace_root).resolve()
        candidate = Path(path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PermissionError("path escapes workspace") from exc
        if self._contains_symlink(root, candidate):
            raise PermissionError("symlink path denied")
        return candidate

    @staticmethod
    def _scope_values(scope: Mapping[str, Any], key: str) -> frozenset[str]:
        raw = scope.get(key)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            return frozenset({raw})
        if isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset(str(item) for item in raw)
        return frozenset()

    def _scope_denial(self, command: SandboxCommand, token: CapabilityToken) -> str | None:
        scope = token.scope
        if command.subject_id and command.subject_id != token.subject_id:
            return "token_subject_mismatch"
        for field_name, scope_key in (
            (command.command_id, "command_ids"),
            (command.action_id, "action_ids"),
            (command.decision_id, "decision_ids"),
        ):
            allowed = self._scope_values(scope, scope_key)
            if allowed and field_name not in allowed:
                return f"{scope_key[:-1]}_outside_token_scope"
        return None

    def authorize(self, command: SandboxCommand, token: CapabilityToken, *, now: float) -> PolicyDecision:
        if token.policy_version != self.command_policy.policy_version:
            return PolicyDecision(False, "policy_version_mismatch")
        if not token.permits(command.requested_capability, now=now):
            return PolicyDecision(False, "capability_missing_or_expired")
        scope_denial = self._scope_denial(command, token)
        if scope_denial:
            return PolicyDecision(False, scope_denial)
        if command.created_at > now + self.command_policy.max_future_skew_seconds:
            return PolicyDecision(False, "command_from_future")
        if now - command.created_at > self.command_policy.max_command_age_seconds:
            return PolicyDecision(False, "command_expired")
        try:
            kind = command.kind if isinstance(command.kind, SandboxCommandKind) else SandboxCommandKind(str(command.kind))
        except ValueError:
            return PolicyDecision(False, "unsupported_command_kind")
        args = dict(command.arguments)

        if kind in (SandboxCommandKind.READ_FILE, SandboxCommandKind.WRITE_FILE):
            raw_path = str(args.get("path") or "")
            try:
                path = self._resolve_workspace_path(raw_path)
            except ValueError as exc:
                return PolicyDecision(False, "path_required" if "required" in str(exc) else "path_invalid")
            except PermissionError:
                return PolicyDecision(False, "path_outside_workspace")
            except RuntimeError:
                return PolicyDecision(False, "symlink_path_denied")
            prefixes = self._scope_values(token.scope, "workspace_prefixes")
            if prefixes:
                rel = path.relative_to(Path(self.command_policy.workspace_root)).as_posix()
                if not any(rel == prefix.rstrip("/") or rel.startswith(prefix.rstrip("/") + "/") for prefix in prefixes):
                    return PolicyDecision(False, "path_outside_token_scope")
            if kind is SandboxCommandKind.WRITE_FILE and not self.command_policy.writable:
                return PolicyDecision(False, "workspace_read_only")
            return PolicyDecision(True, resolved_path=str(path))

        if kind is SandboxCommandKind.RUN_COMMAND:
            argv = args.get("argv")
            if not isinstance(argv, (list, tuple)) or not argv:
                return PolicyDecision(False, "argv_required")
            if len(argv) > 64 or sum(len(str(item)) for item in argv) > 16_384:
                return PolicyDecision(False, "argv_too_large")
            raw_executable = str(argv[0])
            if not self.command_policy.allow_executable_paths and (Path(raw_executable).is_absolute() or "/" in raw_executable or "\\" in raw_executable):
                return PolicyDecision(False, "executable_path_denied")
            executable = Path(raw_executable).name
            if executable not in self.command_policy.executable_allowlist:
                return PolicyDecision(False, "executable_not_allowlisted")
            metacharacters = (";", "&&", "||", "`", "$(", "\n", "\r", "\x00")
            if any(any(marker in str(arg) for marker in metacharacters) for arg in argv):
                return PolicyDecision(False, "shell_metacharacters_denied")
            return PolicyDecision(True)

        if kind is SandboxCommandKind.HTTP_REQUEST:
            if not self.command_policy.network_enabled:
                return PolicyDecision(False, "network_disabled")
            host = str(args.get("host") or "").strip().lower().rstrip(".")
            if not host:
                return PolicyDecision(False, "host_required")
            token_hosts = self._scope_values(token.scope, "network_hosts")
            if host not in self.command_policy.allowed_network_hosts or (token_hosts and host not in token_hosts):
                return PolicyDecision(False, "host_not_allowlisted")
            method = str(args.get("method") or "GET").upper()
            if method not in self.command_policy.allowed_http_methods:
                return PolicyDecision(False, "http_method_not_allowlisted")
            return PolicyDecision(True)

        if kind in (SandboxCommandKind.BODY_FRAME, SandboxCommandKind.TTS, SandboxCommandKind.SIMULATE):
            return PolicyDecision(True)
        return PolicyDecision(False, "unsupported_command_kind")

    def filtered_environment(self, source: Mapping[str, str] | None = None) -> dict[str, str]:
        source = dict(source or os.environ)
        return {key: value for key, value in source.items() if key in self.command_policy.environment_allowlist}
