# -*- coding: utf-8 -*-
"""Private mind package cho ERIS.

Public API cố ý nhỏ: contract, concern store, dossier, evaluators, synthesizer,
mutation bus và surface valve. Đừng import vòng vào coordinator ở đây. Import vòng
là nghi lễ hiến tế thời gian debug, không phải kiến trúc.
"""

from .contracts import (
    EvidenceDossier,
    InternalJudgment,
    PrivateConcern,
    PrivateMindTickResult,
    RankedHypothesis,
    StateMutation,
    SurfaceCandidate,
    ThoughtFragment,
)
from .concern_store import ConcernStore
from .evidence_dossier import EvidenceDossierBuilder
from .inner_synthesizer import GemmaInnerSynthesizer
from .mini_evaluators import (
    FutureBiasEvaluator,
    IntentEvaluator,
    MemoryResonanceEvaluator,
    MiniEvaluatorPipeline,
    RiskAndPermissionEvaluator,
)
from .state_mutation_bus import StateMutationBus
from .surface_valve import SurfaceValve
from .thought_continuity import ThoughtContinuityStore, ThoughtEntry

__all__ = [
    "ConcernStore",
    "EvidenceDossier",
    "EvidenceDossierBuilder",
    "FutureBiasEvaluator",
    "GemmaInnerSynthesizer",
    "IntentEvaluator",
    "InternalJudgment",
    "MemoryResonanceEvaluator",
    "MiniEvaluatorPipeline",
    "PrivateConcern",
    "PrivateMindTickResult",
    "RankedHypothesis",
    "RiskAndPermissionEvaluator",
    "StateMutation",
    "StateMutationBus",
    "SurfaceCandidate",
    "SurfaceValve",
    "ThoughtContinuityStore",
    "ThoughtEntry",
    "ThoughtFragment",
]
