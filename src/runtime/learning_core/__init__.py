"""DeepTutor learning kernel ported into Eris.

This package is pure Python with no I/O except through LearningStore.
Nothing here imports runtime, companion, voice, or TTS subsystems.

Ported from HKUDS/DeepTutor @ ef2d9e5c (Apache 2.0).
See THIRD_PARTY_NOTICES.md at repo root.
"""
from __future__ import annotations

from runtime.learning_core.contracts import (
    KnowledgePoint,
    LearnerProfile,
    LearningEvidence,
    LearningPath,
    MasteryRecord,
    PendingInteraction,
    ReviewItem,
)
from runtime.learning_core.mastery import (
    MasteryPolicy,
    compute_mastery,
    gate_passed,
)
from runtime.learning_core.policy import (
    NavigationPolicy,
    TutorStep,
    next_step,
)
from runtime.learning_core.scheduler import (
    ReviewScheduler,
    compute_retrievability,
    due_items,
)
from runtime.learning_core.grading import (
    GradingResult,
    grade_choice,
)
from runtime.learning_core.pending import (
    PendingInteractionLedger,
    resolve_pending,
)
from runtime.learning_core.activation import (
    ActivationCooldown,
    ActivationDecision,
    ActivationLevel,
    decide_activation,
)
from runtime.learning_core.service import LearningService
from runtime.learning_core.store import LearningStore

__all__ = [
    # contracts
    "KnowledgePoint",
    "LearnerProfile",
    "LearningEvidence",
    "LearningPath",
    "MasteryRecord",
    "PendingInteraction",
    "ReviewItem",
    # mastery
    "MasteryPolicy",
    "compute_mastery",
    "gate_passed",
    # policy
    "NavigationPolicy",
    "TutorStep",
    "next_step",
    # scheduler
    "ReviewScheduler",
    "compute_retrievability",
    "due_items",
    # grading
    "GradingResult",
    "grade_choice",
    # pending
    "PendingInteractionLedger",
    "resolve_pending",
    # activation
    "ActivationCooldown",
    "ActivationDecision",
    "ActivationLevel",
    "decide_activation",
    # service + store
    "LearningService",
    "LearningStore",
]
