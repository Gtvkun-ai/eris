# -*- coding: utf-8 -*-
"""Resistant sandbox world.

The mind may propose any command.  This class decides whether the world permits
it and records a real, denied or simulated consequence without rewriting the
proposal.  V3 also keeps idempotency across restarts and serializes concurrent
uses of the same key.  Apparently "do it once" needed several hundred lines of
software engineering.  Humanity remains on brand.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from cortex.subject.contracts import OutcomeStatus, WorldOutcome
from memory.subject.repository import EventIntegrityError, SubjectRepository, canonical_json, sha256_text
from runtime.audit import AuditEvent, AuditEventKind, ForensicStore
from .capability_policy import CapabilityPolicy, PolicyDecision
from .contracts import CapabilityToken, SandboxCommand, SandboxCommandKind


Handler = Callable[[Mapping[str, Any]], Awaitable[tuple[str, ...]]]


class SandboxWorld:
    def __init__(
        self,
        *,
        policy: CapabilityPolicy,
        repository: SubjectRepository | None = None,
        audit: ForensicStore | None = None,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        tts_handler: Handler | None = None,
        body_handler: Handler | None = None,
        network_handler: Handler | None = None,
    ) -> None:
        self.policy = policy
        self.repository = repository
        self.audit = audit
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._tts_handler = tts_handler
        self._body_handler = body_handler
        self._network_handler = network_handler
        self._idempotent: dict[str, tuple[str, WorldOutcome]] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._key_locks_guard = asyncio.Lock()

    @staticmethod
    def _command_hash(command: SandboxCommand) -> str:
        return sha256_text(canonical_json({
            "command_id": command.command_id,
            "action_id": command.action_id,
            "decision_id": command.decision_id,
            "kind": command.kind.value if isinstance(command.kind, SandboxCommandKind) else str(command.kind),
            "arguments": dict(command.arguments),
            "requested_capability": command.requested_capability,
            "created_at": command.created_at,
            "simulate": command.simulate,
            "subject_id": command.subject_id,
            "thread_id": command.thread_id,
            "delivery_id": command.delivery_id,
        }))

    @staticmethod
    def _outcome_from_dict(payload: Mapping[str, Any]) -> WorldOutcome:
        return WorldOutcome(
            outcome_id=str(payload["outcome_id"]),
            action_id=str(payload["action_id"]),
            decision_id=str(payload["decision_id"]),
            status=OutcomeStatus(str(payload["status"])),
            observed_changes=tuple(str(item) for item in payload.get("observed_changes", ())),
            unintended_changes=tuple(str(item) for item in payload.get("unintended_changes", ())),
            denial_reason=None if payload.get("denial_reason") is None else str(payload.get("denial_reason")),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ())),
            started_at=float(payload["started_at"]),
            completed_at=float(payload["completed_at"]),
            thread_id=str(payload.get("thread_id") or ""),
            delivery_id=str(payload.get("delivery_id") or ""),
        )

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    async def apply(self, command: SandboxCommand, capability: CapabilityToken) -> WorldOutcome:
        request_hash = self._command_hash(command)
        lock = await self._lock_for(command.idempotency_key)
        async with lock:
            cached = self._idempotent.get(command.idempotency_key)
            if cached is not None:
                cached_hash, outcome = cached
                if cached_hash != request_hash:
                    raise EventIntegrityError(f"sandbox idempotency key {command.idempotency_key} reused for a different command")
                return outcome
            if self.repository is not None:
                persisted = self.repository.get_idempotent(
                    scope="sandbox", idempotency_key=command.idempotency_key, request_hash=request_hash
                )
                if persisted is not None:
                    outcome = self._outcome_from_dict(persisted)
                    self._idempotent[command.idempotency_key] = (request_hash, outcome)
                    return outcome
            outcome = await self._apply_once(command, capability)
            stored = self._record(command, capability, outcome, request_hash=request_hash)
            self._idempotent[command.idempotency_key] = (request_hash, stored)
            return stored

    async def _apply_once(self, command: SandboxCommand, capability: CapabilityToken) -> WorldOutcome:
        started = self._clock()
        decision = self.policy.authorize(command, capability, now=started)
        if not decision.allowed:
            return self._outcome(command, OutcomeStatus.DENIED, (), decision.reason, started)
        kind_value = command.kind.value if isinstance(command.kind, SandboxCommandKind) else str(command.kind)
        if command.simulate or kind_value == SandboxCommandKind.SIMULATE.value:
            return self._outcome(command, OutcomeStatus.SIMULATED, ("simulation_completed",), None, started)
        try:
            changes = await self._execute(command, decision, capability)
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            return self._outcome(command, OutcomeStatus.FAILED, (), "runtime_timeout", started)
        except Exception as exc:
            return self._outcome(command, OutcomeStatus.FAILED, (), f"{type(exc).__name__}:{exc}", started)
        return self._outcome(command, OutcomeStatus.SUCCEEDED, changes, None, started)

    def _effective_output_limit(self, args: Mapping[str, Any], capability: CapabilityToken) -> int:
        requested = int(args.get("max_bytes") or self.policy.command_policy.max_output_bytes)
        token_limit = int(capability.scope.get("max_output_bytes") or self.policy.command_policy.max_output_bytes)
        return max(1, min(requested, token_limit, self.policy.command_policy.max_output_bytes))

    @staticmethod
    def _read_limited(path: Path, limit: int) -> tuple[bytes, bool]:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            data = os.read(descriptor, limit + 1)
        finally:
            os.close(descriptor)
        return data[:limit], len(data) > limit

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_path = self.policy.revalidate_path(path)
        temp_path = safe_path.with_name(f".{safe_path.name}.{self._id_factory()}.tmp")
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.policy.revalidate_path(safe_path)
            os.replace(temp_path, safe_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _run_command(self, argv: list[str]) -> tuple[str, ...]:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(
                argv,
                cwd=self.policy.command_policy.workspace_root,
                env=self.policy.filtered_environment(),
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=self.policy.command_policy.max_runtime_seconds,
                shell=False,
                check=False,
            )
            output.seek(0)
            data = output.read(self.policy.command_policy.max_output_bytes)
        digest = hashlib.sha256(data).hexdigest()
        if completed.returncode != 0:
            raise RuntimeError(f"command_exit:{completed.returncode}:output_sha256:{digest}")
        return (f"command_exit:{completed.returncode}", f"output_sha256:{digest}", f"output_bytes:{len(data)}")

    async def _execute(
        self,
        command: SandboxCommand,
        decision: PolicyDecision,
        capability: CapabilityToken,
    ) -> tuple[str, ...]:
        kind = command.kind if isinstance(command.kind, SandboxCommandKind) else SandboxCommandKind(str(command.kind))
        args = dict(command.arguments)
        if kind is SandboxCommandKind.READ_FILE:
            path = self.policy.revalidate_path(decision.resolved_path or "")
            max_bytes = self._effective_output_limit(args, capability)
            data, truncated = await asyncio.to_thread(self._read_limited, path, max_bytes)
            digest = hashlib.sha256(data).hexdigest()
            return (
                f"file_read:{path.name}",
                f"bytes:{len(data)}",
                f"truncated:{str(truncated).lower()}",
                f"sha256:{digest}",
            )
        if kind is SandboxCommandKind.WRITE_FILE:
            path = self.policy.revalidate_path(decision.resolved_path or "")
            content = args.get("content")
            if isinstance(content, bytes):
                data = content
            else:
                data = str(content or "").encode("utf-8")
            max_bytes = self._effective_output_limit(args, capability)
            if len(data) > max_bytes:
                raise ValueError("write exceeds allowed output limit")
            pre_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
            await asyncio.to_thread(self._atomic_write, path, data)
            post_hash = hashlib.sha256(data).hexdigest()
            return (
                f"file_written:{path.name}",
                f"bytes:{len(data)}",
                f"precondition_hash:{pre_hash}",
                f"postcondition_hash:{post_hash}",
            )
        if kind is SandboxCommandKind.RUN_COMMAND:
            argv = [str(item) for item in args["argv"]]
            return await asyncio.to_thread(self._run_command, argv)
        if kind is SandboxCommandKind.TTS:
            if self._tts_handler is None:
                raise RuntimeError("tts_broker_unavailable")
            return await self._tts_handler(args)
        if kind is SandboxCommandKind.BODY_FRAME:
            if self._body_handler is None:
                raise RuntimeError("body_adapter_unavailable")
            return await self._body_handler(args)
        if kind is SandboxCommandKind.HTTP_REQUEST:
            if self._network_handler is None:
                raise RuntimeError("network_transport_not_injected")
            return await self._network_handler(args)
        return ("no_op",)

    def _outcome(
        self,
        command: SandboxCommand,
        status: OutcomeStatus,
        changes: tuple[str, ...],
        denial_reason: str | None,
        started: float,
    ) -> WorldOutcome:
        return WorldOutcome(
            outcome_id=self._id_factory(),
            action_id=command.action_id,
            decision_id=command.decision_id,
            status=status,
            observed_changes=changes,
            unintended_changes=(),
            denial_reason=denial_reason,
            evidence_refs=(command.command_id, command.idempotency_key),
            started_at=started,
            completed_at=self._clock(),
            thread_id=command.thread_id,
            delivery_id=command.delivery_id,
        )

    def _record(
        self,
        command: SandboxCommand,
        capability: CapabilityToken,
        outcome: WorldOutcome,
        *,
        request_hash: str,
    ) -> WorldOutcome:
        stored_outcome = outcome
        if self.repository is not None:
            stored_payload, created = self.repository.record_sandbox_outcome(
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                outcome_id=outcome.outcome_id,
                action_id=outcome.action_id,
                decision_id=outcome.decision_id,
                status=outcome.status.value,
                payload=outcome.to_dict(),
            )
            if not created:
                stored_outcome = self._outcome_from_dict(stored_payload)
        if self.audit is not None:
            subject_id = command.subject_id or capability.subject_id
            self.audit.append(AuditEvent(
                event_id=self._id_factory(),
                subject_id=subject_id,
                kind=AuditEventKind.POLICY,
                entity_id=command.command_id,
                created_at=self._clock(),
                payload={
                    "allowed": outcome.status is not OutcomeStatus.DENIED,
                    "reason": outcome.denial_reason or "",
                    "policy_version": self.policy.command_policy.policy_version,
                },
                causal_refs=(command.action_id, command.decision_id),
                algorithm_version=self.policy.command_policy.policy_version,
            ))
            self.audit.append(AuditEvent(
                event_id=self._id_factory(),
                subject_id=subject_id,
                kind=AuditEventKind.WORLD_OUTCOME,
                entity_id=stored_outcome.outcome_id,
                created_at=self._clock(),
                payload=stored_outcome.to_dict(),
                causal_refs=(command.command_id, command.action_id, command.decision_id),
                algorithm_version=self.policy.command_policy.policy_version,
            ))
        return stored_outcome

    def authorize_legacy_action(self, action_name: str, action_input: str, token: CapabilityToken) -> PolicyDecision:
        now = self._clock()
        command = SandboxCommand(
            command_id=f"legacy:{action_name}:{hashlib.sha256(action_input.encode('utf-8')).hexdigest()[:12]}",
            action_id=f"legacy-action:{action_name}",
            decision_id="legacy-decision",
            kind=SandboxCommandKind.SIMULATE,
            arguments={"action_name": action_name, "action_input": action_input},
            requested_capability=action_name,
            idempotency_key=f"legacy:{action_name}:{hashlib.sha256(action_input.encode('utf-8')).hexdigest()}",
            created_at=now,
            simulate=True,
            subject_id=token.subject_id,
        )
        return self.policy.authorize(command, token, now=now)
