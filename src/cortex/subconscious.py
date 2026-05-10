"""Compatibility wrapper for the old subconscious API.

The runtime now uses ThoughtStream. These aliases keep older imports and saved
tests working while making speech consume only a surfaced thought tip.
"""

from .thought_stream import (
    AssociationGraph,
    CognitiveStream,
    CognitiveStreamEngine,
    CognitiveMomentumEngine,
    CognitiveTensionEngine,
    FragmentStore,
    MomentumClosure,
    PersistenceDecay,
    PredictionTracker,
    RecursiveReactivation,
    SubconsciousEngine,
    SubconsciousLoop,
    SurfaceSelector,
    ThoughtStream,
    ThoughtStreamEngine,
    UnresolvedTensionEngine,
)

__all__ = [
    "AssociationGraph",
    "CognitiveStream",
    "CognitiveStreamEngine",
    "CognitiveMomentumEngine",
    "CognitiveTensionEngine",
    "FragmentStore",
    "MomentumClosure",
    "PersistenceDecay",
    "PredictionTracker",
    "RecursiveReactivation",
    "SubconsciousEngine",
    "SubconsciousLoop",
    "SurfaceSelector",
    "ThoughtStream",
    "ThoughtStreamEngine",
    "UnresolvedTensionEngine",
]
