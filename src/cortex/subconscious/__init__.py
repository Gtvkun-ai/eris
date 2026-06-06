# -*- coding: utf-8 -*-
"""Subconscious Phase 0 package.

Public API cố tình nhỏ:
- ThoughtFragment / ThoughtObject: contract dữ liệu.
- SubconsciousBlackboard: nơi gom fragment.
- ConsciousSynthesizer: cổ chai nén fragment thành object.
- WorkerContext / RuleBasedWorker: nền cho Phase 1+.
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
from .worker_base import RuleBasedWorker, SubconsciousWorker, WorkerContext

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
    "RuleBasedWorker",
    "SubconsciousWorker",
    "WorkerContext",
]
