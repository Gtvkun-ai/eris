# -*- coding: utf-8 -*-
"""Facade for the evidence-grounded causal affect pipeline.

This module is intentionally side-effect-light.  The runtime owner may store the
returned projection as ``active_causal_threads`` and feed it into endogenous
state, planner context, performance and outcome learning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cortex.appraisal_engine import AppraisalEngine
from cortex.causal_affect_models import (
    ActiveMotive,
    AppraisalFrame,
    CausalThread,
    ExogenousEvent,
    PerformanceIntent,
    SurfaceChannelPolicy,
    SurpriseBudget,
)
from cortex.causal_threads import CausalThreadBuilder
from cortex.exogenous_event_ledger import EventSemanticizer, TypedEventProjectionStore
from cortex.motive_graph import MotiveGraph
from cortex.performance_intent import PerformanceIntentPlanner
from cortex.relationship_expectations import RelationshipExpectationStore


@dataclass(slots=True)
class CausalAffectSnapshot:
    events: tuple[ExogenousEvent, ...] = ()
    appraisals: tuple[AppraisalFrame, ...] = ()
    motives: tuple[ActiveMotive, ...] = ()
    threads: tuple[CausalThread, ...] = ()
    intents: tuple[PerformanceIntent, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "appraisals": [appraisal.to_dict() for appraisal in self.appraisals],
            "motives": [motive.to_dict() for motive in self.motives],
            "threads": [thread.to_public_dict() for thread in self.threads],
            "intents": [intent.to_dict() for intent in self.intents],
        }


@dataclass(slots=True)
class CausalAffectPipeline:
    semanticizer: EventSemanticizer = field(default_factory=EventSemanticizer)
    event_store: TypedEventProjectionStore = field(default_factory=TypedEventProjectionStore)
    expectation_store: RelationshipExpectationStore = field(default_factory=RelationshipExpectationStore)
    appraisal_engine: AppraisalEngine = field(default_factory=AppraisalEngine)
    motive_graph: MotiveGraph = field(default_factory=MotiveGraph)
    thread_builder: CausalThreadBuilder = field(default_factory=CausalThreadBuilder)
    performance_planner: PerformanceIntentPlanner = field(default_factory=PerformanceIntentPlanner)
    snapshot: CausalAffectSnapshot = field(default_factory=CausalAffectSnapshot)
    subject_service: Any = None

    def bind_subject_service(self, service: Any) -> None:
        """Use SubjectService as the causal state authority.

        ``update`` remains as a compatibility projection for older callers.
        New production code should call :meth:`deliberate_subject` so the raw
        observation, substrate, need episodes, coalition and authorship records
        share one causal trace.
        """
        self.subject_service = service

    async def deliberate_subject(self, observation: Any) -> Any:
        if self.subject_service is None:
            raise RuntimeError("SubjectService is not bound")
        return await self.subject_service.deliberate(observation)

    async def observe_subject_outcome(self, outcome: Any) -> Any:
        if self.subject_service is None:
            raise RuntimeError("SubjectService is not bound")
        return await self.subject_service.observe_outcome(outcome)

    def update(
        self,
        *,
        raw_records: tuple[Any, ...],
        previous_context: Any,
        current_context: Any,
        goals: tuple[Any, ...] = (),
        self_model: Any = None,
        relationship: Any = None,
        values: Any = None,
        interrupt_cost: float = 0.0,
        channel_policy: SurfaceChannelPolicy | None = None,
        surprise_budget: SurpriseBudget | None = None,
    ) -> CausalAffectSnapshot:
        events = self.semanticizer.ingest(
            raw_records=raw_records,
            previous_context=previous_context,
            current_context=current_context,
            open_expectations=self.expectation_store.all(),
        )
        events = self.event_store.append(events)
        for event in events:
            self.expectation_store.project(event)

        appraisals: list[AppraisalFrame] = []
        for event in events:
            appraisals.extend(self.appraisal_engine.appraise(
                event,
                goals=goals,
                expectations=self.expectation_store.all(),
                self_model=self_model,
                relationship=relationship,
            ))
        motives = self.motive_graph.update(
            appraisals=tuple(appraisals),
            previous=self.snapshot.motives,
            values=values,
            events=events,
        )
        threads = self.thread_builder.build(
            events=events,
            appraisals=tuple(appraisals),
            motives=motives,
            max_threads=3,
        )
        intents = tuple(
            intent
            for thread in threads
            if (intent := self.performance_planner.plan(
                thread,
                channel_policy=channel_policy,
                surprise_budget=surprise_budget,
                interrupt_cost=interrupt_cost,
            )) is not None
        )
        self.snapshot = CausalAffectSnapshot(
            events=events,
            appraisals=tuple(appraisals),
            motives=motives,
            threads=threads,
            intents=intents,
        )
        return self.snapshot

    def attach_to_runtime(self, runtime_owner: Any) -> None:
        """Expose public-safe projections under conventional runtime fields."""
        if runtime_owner is None:
            return
        setattr(runtime_owner, "active_causal_threads", self.snapshot.threads)
        setattr(runtime_owner, "causal_performance_intents", self.snapshot.intents)
        setattr(runtime_owner, "causal_affect_snapshot", self.snapshot)
        if self.subject_service is not None:
            setattr(runtime_owner, "subject_service", self.subject_service)
            setattr(runtime_owner, "subject_core_snapshot", self.subject_service.snapshot())


__all__ = ["CausalAffectPipeline", "CausalAffectSnapshot"]
