# -*- coding: utf-8 -*-
"""Top-level orchestration across Mind, actuator, dialogue and audit boundaries."""
from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from cortex.subject.contracts import (
    LearningReceipt,
    MindDecision,
    SubjectDeliberationFrame,
    SubjectExecutiveCommit,
    WorldObservation,
    WorldOutcome,
)
from cortex.subject.service import SubjectService
from runtime.audit import AuditEvent, AuditEventKind
from runtime.world.contracts import ActionReceipt, ActuatorPort


class DialoguePort(Protocol):
    async def deliver(self, decision: MindDecision) -> Any: ...


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> Any: ...


class SubjectExecutivePort(Protocol):
    @property
    def enabled(self) -> bool: ...

    def commit_subject_frame(
        self,
        frame: SubjectDeliberationFrame,
        *,
        user_text: str = "",
        snapshot: dict[str, Any] | None = None,
        mode: str = "runtime",
    ) -> SubjectExecutiveCommit | None: ...


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    decision: MindDecision
    action_receipt: ActionReceipt | None
    learning_receipt: LearningReceipt | None
    dialogue_receipt: Any = None


class SubjectRuntime:
    def __init__(
        self,
        *,
        mind: SubjectService,
        actuator: ActuatorPort,
        dialogue: DialoguePort | None,
        audit: AuditSink | None,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        executive: SubjectExecutivePort | None = None,
    ) -> None:
        self._mind = mind
        self._actuator = actuator
        self._dialogue = dialogue
        self._audit = audit
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._executive = executive

    def bind_executive(self, executive: SubjectExecutivePort) -> None:
        """Gắn Executive sau bootstrap mà không tạo dependency vòng composition root."""
        self._executive = executive

    async def _audit_append(self, event: AuditEvent) -> None:
        if self._audit is None:
            return
        result = self._audit.append(event)
        if inspect.isawaitable(result):
            await result

    async def handle(self, observation: WorldObservation) -> RuntimeResult:
        await self._audit_append(AuditEvent(
            event_id=self._id_factory(),
            subject_id=observation.subject_id,
            kind=AuditEventKind.OBSERVATION,
            entity_id=observation.observation_id,
            created_at=self._clock(),
            payload=observation.to_dict(),
            causal_refs=observation.causal_refs,
            correlation_id=observation.correlation_id,
            algorithm_version=self._mind.config.algorithm_version,
        ))
        # Subject Core chuẩn bị nền; Executive cam kết; Mind mới ghi decision.
        # Khi runtime độc lập chưa bind Executive (chủ yếu unit test), fallback cũ
        # vẫn tồn tại và được authorship đánh dấu rõ, không giả làm executive commit.
        frame = await self._mind.prepare_deliberation(observation)
        commit = None
        if self._executive is not None:
            commit = self._executive.commit_subject_frame(
                frame,
                user_text=str(observation.context.get("user_text") or ""),
                snapshot=dict(observation.context),
                mode="runtime",
            )
            if commit is not None and commit.cognitive_requests:
                revised = await self._mind.review_deliberation(frame, commit.cognitive_requests)
                if revised.frame_id != frame.frame_id:
                    frame = revised
                    commit = self._executive.commit_subject_frame(
                        frame,
                        user_text=str(observation.context.get("user_text") or ""),
                        snapshot=dict(observation.context),
                        mode="runtime_review",
                    )
        decision = await self._mind.finalize_deliberation(frame, commit)
        await self._audit_append(AuditEvent(
            event_id=self._id_factory(),
            subject_id=observation.subject_id,
            kind=AuditEventKind.DECISION,
            entity_id=decision.decision_id,
            created_at=self._clock(),
            payload=decision.to_dict(),
            causal_refs=(observation.observation_id, *decision.appraisal_refs, decision.substrate_ref),
            correlation_id=observation.correlation_id,
            algorithm_version=self._mind.config.algorithm_version,
        ))

        if decision.proposed_action == "speak" and self._dialogue is not None:
            dialogue_receipt = await self._dialogue.deliver(decision)
            return RuntimeResult(decision=decision, action_receipt=None, learning_receipt=None, dialogue_receipt=dialogue_receipt)

        request = self._mind.to_action_request(
            decision,
            requested_capabilities=tuple(str(item) for item in decision.arguments.get("requested_capabilities", ())) or (decision.proposed_action,),
            expected_outcomes=tuple(str(item) for item in decision.arguments.get("expected_outcomes", ())),
        )
        await self._audit_append(AuditEvent(
            event_id=self._id_factory(),
            subject_id=observation.subject_id,
            kind=AuditEventKind.ACTION_REQUEST,
            entity_id=request.action_id,
            created_at=self._clock(),
            payload={
                "action_id": request.action_id,
                "decision_id": request.decision_id,
                "kind": request.kind,
                "arguments": dict(request.arguments),
                "requested_capabilities": list(request.requested_capabilities),
                "authorship_draft_id": request.authorship_draft_id,
            },
            causal_refs=(decision.decision_id, request.authorship_draft_id),
            correlation_id=observation.correlation_id,
            algorithm_version=self._mind.config.algorithm_version,
        ))
        receipt = await self._actuator.execute(request)
        outcome = receipt.to_world_outcome()
        await self._audit_append(AuditEvent(
            event_id=self._id_factory(),
            subject_id=observation.subject_id,
            kind=AuditEventKind.WORLD_OUTCOME,
            entity_id=outcome.outcome_id,
            created_at=self._clock(),
            payload=outcome.to_dict(),
            causal_refs=(outcome.action_id, outcome.decision_id),
            correlation_id=observation.correlation_id,
            algorithm_version=self._mind.config.algorithm_version,
        ))
        learning = await self._mind.observe_outcome(outcome)
        await self._audit_append(AuditEvent(
            event_id=self._id_factory(),
            subject_id=observation.subject_id,
            kind=AuditEventKind.LEARNING,
            entity_id=learning.receipt_id,
            created_at=self._clock(),
            payload={
                "outcome_id": learning.outcome_id,
                "closed_episode_ids": list(learning.closed_episode_ids),
                "belief_revision_ids": list(learning.belief_revision_ids),
                "authorship_id": learning.authorship_id,
            },
            causal_refs=(learning.outcome_id, learning.authorship_id, *learning.closed_episode_ids),
            correlation_id=observation.correlation_id,
            algorithm_version=self._mind.config.algorithm_version,
        ))
        return RuntimeResult(decision=decision, action_receipt=receipt, learning_receipt=learning)
