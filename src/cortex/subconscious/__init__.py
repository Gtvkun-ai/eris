# -*- coding: utf-8 -*-
"""Subconscious package Phase 0 → 7.

Public API cố tình nhỏ:
- ThoughtFragment / ThoughtObject: contract dữ liệu.
- SubconsciousBlackboard: nơi gom fragment.
- ConsciousSynthesizer: cổ chai nén fragment thành object.
- WorkerContext / RuleBasedWorker: nền cho worker Phase 1+.
- Worker builders: tạo bộ worker theo phase mà không ép runtime chính phải biết từng class.
"""

from .thought_fragment import (
    PrivacyLevel,
    RecommendedRoute,
    ThoughtFragment,
    ThoughtFragmentValidationError,
    ThoughtObject,
    clamp01,
)
from .blackboard import BlackboardSnapshot, SubconsciousBlackboard
from .synthesizer import ConsciousSynthesizer, SynthesisPolicy, SynthesisReport
from .model_synthesizer import ModelBackedConsciousSynthesizer, ModelSynthesisPolicy, InnerCourtReport
from .worker_base import RuleBasedWorker, SubconsciousWorker, WorkerContext

from .workers import (
    UserModelerAgent,
    MemoryResonatorAgent,
    GoalSimulatorAgent,
    SelfRegulatorAgent,
    RehearsalAgent,
    CuriosityGapAgent,
    DaydreamInjector,
    IndependentAgendaAgent,
    SpatialMindAgent,
    SubjectiveTimeAgent,
    MetaCognitiveAuditAgent,
    MetaAuditFinding,
    MetaAuditResult,
    ShadowAccumulator,
    ShadowAccumulatorPolicy,
    BeliefMutationEngine,
    BeliefMutationProposal,
    PreferenceDeltaProposal,
    HabitDeltaProposal,
    MutationCommitter,
    MutationCommitRecord,
    MutationDecision,
    build_phase12_workers,
    build_phase34_workers,
    build_phase1234_workers,
    build_phase5_workers,
    build_phase7_workers,
    build_phase6_workers,
    build_phase1234567_workers,
    build_phase123457_workers,
    build_default_subconscious_workers,
)

__all__ = [
    "PrivacyLevel",
    "RecommendedRoute",
    "ThoughtFragment",
    "ThoughtFragmentValidationError",
    "ThoughtObject",
    "clamp01",
    "BlackboardSnapshot",
    "SubconsciousBlackboard",
    "ConsciousSynthesizer",
    "SynthesisPolicy",
    "SynthesisReport",
    "ModelBackedConsciousSynthesizer",
    "ModelSynthesisPolicy",
    "InnerCourtReport",
    "RuleBasedWorker",
    "SubconsciousWorker",
    "WorkerContext",
    "UserModelerAgent",
    "MemoryResonatorAgent",
    "GoalSimulatorAgent",
    "SelfRegulatorAgent",
    "RehearsalAgent",
    "CuriosityGapAgent",
    "DaydreamInjector",
    "IndependentAgendaAgent",
    "SpatialMindAgent",
    "SubjectiveTimeAgent",
    "MetaCognitiveAuditAgent",
    "MetaAuditFinding",
    "MetaAuditResult",
    "ShadowAccumulator",
    "ShadowAccumulatorPolicy",
    "BeliefMutationEngine",
    "BeliefMutationProposal",
    "PreferenceDeltaProposal",
    "HabitDeltaProposal",
    "MutationCommitter",
    "MutationCommitRecord",
    "MutationDecision",
    "build_phase12_workers",
    "build_phase34_workers",
    "build_phase1234_workers",
    "build_phase5_workers",
    "build_phase7_workers",
    "build_phase6_workers",
    "build_phase1234567_workers",
    "build_phase123457_workers",
    "build_default_subconscious_workers",
]
