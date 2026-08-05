from __future__ import annotations

from pathlib import Path

import pytest

from cortex.subject import SubjectService, SubjectServiceConfig
from cortex.subject.contracts import WorldObservation
from memory.subject import SubjectRepository
from runtime.audit import ForensicStore
from runtime.subject_runtime import SubjectRuntime
from runtime.world import (
    CapabilityPolicy,
    CapabilityToken,
    CommandPolicy,
    SandboxActuator,
    SandboxWorld,
)


class Determinism:
    def __init__(self) -> None:
        self.i = 0
        self.t = 100.0

    def id(self) -> str:
        self.i += 1
        return f"id-{self.i}"

    def clock(self) -> float:
        self.t += 1.0
        return self.t


@pytest.mark.asyncio
async def test_observation_to_decision_sandbox_outcome_learning_and_audit(tmp_path: Path) -> None:
    d = Determinism()
    repository = SubjectRepository(tmp_path / "subject.db", clock=d.clock, id_factory=d.id)
    audit = ForensicStore(tmp_path / "audit.db", clock=d.clock, id_factory=d.id)
    mind = SubjectService(
        config=SubjectServiceConfig(subject_id="eris", deterministic=True),
        repository=repository,
        audit=audit,
        clock=d.clock,
        id_factory=d.id,
    )
    sandbox = SandboxWorld(
        policy=CapabilityPolicy(CommandPolicy(frozenset(), str(tmp_path))),
        repository=repository,
        audit=audit,
        clock=d.clock,
        id_factory=d.id,
    )
    token = CapabilityToken("token", "eris", frozenset({"practice"}), 0.0, 9999.0, "v1")
    actuator = SandboxActuator(sandbox=sandbox, token_provider=lambda _request: token, clock=d.clock, id_factory=d.id)
    runtime = SubjectRuntime(mind=mind, actuator=actuator, dialogue=None, audit=audit, clock=d.clock, id_factory=d.id)

    result = await runtime.handle(WorldObservation(
        observation_id="obs",
        subject_id="eris",
        kind="task_failure",
        created_at=d.clock(),
        facts=("test failed",),
        evidence_refs=("test-log",),
        context={
            "affected_need_ids": ("competence",),
            "action_proposals": ({
                "action_kind": "practice",
                "arguments": {"requested_capabilities": ("practice",)},
                "supporting_need_ids": ("competence",),
                "expected_need_relief": 0.9,
                "expected_action_efficacy": 0.8,
                "expected_epistemic_value": 0.4,
                "value_congruence": 0.5,
                "substrate_cost": 0.1,
                "uncertainty": 0.2,
            },),
        },
    ))
    assert result.action_receipt is not None
    assert result.learning_receipt is not None
    assert result.action_receipt.outcome.status.value == "simulated"
    assert audit.verify_chain("eris")
    trace = audit.causal_trace(result.learning_receipt.receipt_id)
    assert trace.chain_valid
