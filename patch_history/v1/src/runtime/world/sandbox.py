# -*- coding: utf-8 -*-
"""Resistant sandbox world.

The mind may propose any command.  This class decides whether the world permits
it and records a real, denied or simulated consequence without rewriting the
proposal.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from cortex.subject.contracts import OutcomeStatus, WorldOutcome
from memory.subject.repository import SubjectRepository
from runtime.audit import AuditEvent, AuditEventKind, ForensicStore
from .capability_policy import CapabilityPolicy, PolicyDecision
from .contracts import CapabilityToken, SandboxCommand, SandboxCommandKind


class SandboxWorld:
    def __init__(
        self,
        *,
        policy: CapabilityPolicy,
        repository: SubjectRepository | None = None,
        audit: ForensicStore | None = None,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        tts_handler: Callable[[Mapping[str, Any]], Awaitable[tuple[str, ...]]] | None = None,
        body_handler: Callable[[Mapping[str, Any]], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        self.policy = policy
        self.repository = repository
        self.audit = audit
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._tts_handler = tts_handler
        self._body_handler = body_handler
        self._idempotent: dict[str, WorldOutcome] = {}

    async def apply(self, command: SandboxCommand, capability: CapabilityToken) -> WorldOutcome:
        existing = self._idempotent.get(command.idempotency_key)
        if existing is not None:
            return existing
        started = self._clock()
        decision = self.policy.authorize(command, capability, now=started)
        if not decision.allowed:
            outcome = self._outcome(command, OutcomeStatus.DENIED, (), decision.reason, started)
            return self._record(command, outcome, decision)
        if command.simulate or str(command.kind) == SandboxCommandKind.SIMULATE.value:
            outcome = self._outcome(command, OutcomeStatus.SIMULATED, ("simulation_completed",), None, started)
            return self._record(command, outcome, decision)
        try:
            changes = await self._execute(command, decision)
        except asyncio.TimeoutError:
            outcome = self._outcome(command, OutcomeStatus.FAILED, (), "runtime_timeout", started)
        except Exception as exc:
            outcome = self._outcome(command, OutcomeStatus.FAILED, (), f"{type(exc).__name__}:{exc}", started)
        else:
            outcome = self._outcome(command, OutcomeStatus.SUCCEEDED, changes, None, started)
        return self._record(command, outcome, decision)

    async def _execute(self, command: SandboxCommand, decision: PolicyDecision) -> tuple[str, ...]:
        kind = command.kind if isinstance(command.kind, SandboxCommandKind) else SandboxCommandKind(str(command.kind))
        args = dict(command.arguments)
        if kind is SandboxCommandKind.READ_FILE:
            path = Path(decision.resolved_path or "")
            max_bytes = min(int(args.get("max_bytes") or self.policy.command_policy.max_output_bytes), self.policy.command_policy.max_output_bytes)
            data = await asyncio.to_thread(path.read_bytes)
            digest = hashlib.sha256(data[:max_bytes]).hexdigest()
            return (f"file_read:{path.name}", f"bytes:{min(len(data), max_bytes)}", f"sha256:{digest}")
        if kind is SandboxCommandKind.WRITE_FILE:
            path = Path(decision.resolved_path or "")
            data = str(args.get("content") or "").encode("utf-8")
            if len(data) > self.policy.command_policy.max_output_bytes:
                raise ValueError("write exceeds max_output_bytes")
            path.parent.mkdir(parents=True, exist_ok=True)
            pre_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
            await asyncio.to_thread(path.write_bytes, data)
            post_hash = hashlib.sha256(data).hexdigest()
            return (f"file_written:{path.name}", f"precondition_hash:{pre_hash}", f"postcondition_hash:{post_hash}")
        if kind is SandboxCommandKind.RUN_COMMAND:
            argv = [str(item) for item in args["argv"]]
            completed = await asyncio.to_thread(
                subprocess.run,
                argv,
                cwd=self.policy.command_policy.workspace_root,
                env=self.policy.filtered_environment(),
                capture_output=True,
                text=False,
                timeout=self.policy.command_policy.max_runtime_seconds,
                shell=False,
                check=False,
            )
            output = (completed.stdout or b"") + (completed.stderr or b"")
            output = output[: self.policy.command_policy.max_output_bytes]
            digest = hashlib.sha256(output).hexdigest()
            if completed.returncode != 0:
                raise RuntimeError(f"command_exit:{completed.returncode}:output_sha256:{digest}")
            return (f"command_exit:{completed.returncode}", f"output_sha256:{digest}")
        if kind is SandboxCommandKind.TTS:
            if self._tts_handler is None:
                raise RuntimeError("tts_broker_unavailable")
            return await self._tts_handler(args)
        if kind is SandboxCommandKind.BODY_FRAME:
            if self._body_handler is None:
                raise RuntimeError("body_adapter_unavailable")
            return await self._body_handler(args)
        if kind is SandboxCommandKind.HTTP_REQUEST:
            # Production network transport must be injected.  The policy alone
            # never silently opens egress.
            raise RuntimeError("network_transport_not_injected")
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
        )

    def _record(self, command: SandboxCommand, outcome: WorldOutcome, decision: PolicyDecision) -> WorldOutcome:
        self._idempotent[command.idempotency_key] = outcome
        if self.repository is not None:
            self.repository.record_idempotent(scope="sandbox", idempotency_key=command.idempotency_key, result=outcome.to_dict())
            self.repository.append_world_outcome(
                outcome_id=outcome.outcome_id,
                action_id=outcome.action_id,
                decision_id=outcome.decision_id,
                status=outcome.status.value,
                payload=outcome.to_dict(),
            )
        if self.audit is not None:
            self.audit.append(AuditEvent(
                event_id=self._id_factory(),
                subject_id="eris",
                kind=AuditEventKind.POLICY,
                entity_id=command.command_id,
                created_at=self._clock(),
                payload={"allowed": decision.allowed, "reason": decision.reason, "transforms": list(decision.transforms)},
                causal_refs=(command.action_id, command.decision_id),
                algorithm_version=self.policy.command_policy.policy_version,
            ))
            self.audit.append(AuditEvent(
                event_id=self._id_factory(),
                subject_id="eris",
                kind=AuditEventKind.WORLD_OUTCOME,
                entity_id=outcome.outcome_id,
                created_at=self._clock(),
                payload=outcome.to_dict(),
                causal_refs=(command.command_id, command.action_id, command.decision_id),
                algorithm_version=self.policy.command_policy.policy_version,
            ))
        return outcome

    def authorize_legacy_action(self, action_name: str, action_input: str, token: CapabilityToken) -> PolicyDecision:
        command = SandboxCommand(
            command_id=f"legacy:{action_name}:{hashlib.sha256(action_input.encode('utf-8')).hexdigest()[:12]}",
            action_id=f"legacy-action:{action_name}",
            decision_id="legacy-decision",
            kind=SandboxCommandKind.SIMULATE,
            arguments={"action_name": action_name, "action_input": action_input},
            requested_capability=action_name,
            idempotency_key=f"legacy:{action_name}:{action_input}",
            created_at=self._clock(),
            simulate=True,
        )
        return self.policy.authorize(command, token, now=self._clock())
