# -*- coding: utf-8 -*-
"""Unified foreground agent loop cho mọi chat turn của ERIS."""
from .completion import CompletionGate, CompletionVerdict
from .contracts import (
    AgentTurnResult,
    AgentTurnState,
    BeatKind,
    CognitivePlan,
    ContinuationPlan,
    DialogueBeat,
    DisclosureMode,
    DiscoursePlan,
    ExecutionPlan,
    LoopBudget,
    ResponseRelation,
    TurnSpeechBudget,
    TurnAction,
    TurnDecision,
)
from .director import ConversationDirector
from .reasoner import DeterministicFallbackTurnReasoner, RuntimeModelTurnReasoner, TurnReasoner
from .pacing import DisclosureArcLedger, DisclosureArcState
from .tutor_role import TutorRoleContribution, TutorRoleCoordinator
from .runtime import TurnAgentRuntime, build_degraded_turn_result, ensure_agent_turn_runtime

__all__ = [
    "AgentTurnResult",
    "AgentTurnState",
    "BeatKind",
    "CognitivePlan",
    "CompletionGate",
    "CompletionVerdict",
    "ConversationDirector",
    "ContinuationPlan",
    "DeterministicFallbackTurnReasoner",
    "DialogueBeat",
    "DisclosureArcLedger",
    "DisclosureArcState",
    "DisclosureMode",
    "DiscoursePlan",
    "ExecutionPlan",
    "LoopBudget",
    "ResponseRelation",
    "RuntimeModelTurnReasoner",
    "TutorRoleContribution",
    "TutorRoleCoordinator",
    "TurnSpeechBudget",
    "TurnAction",
    "TurnAgentRuntime",
    "build_degraded_turn_result",
    "TurnDecision",
    "TurnReasoner",
    "ensure_agent_turn_runtime",
]
