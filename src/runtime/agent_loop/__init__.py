# -*- coding: utf-8 -*-
"""Unified foreground AgentLoop V11.

Core export cố tình nhỏ: agent state, public beats, long-term speech plan, validator,
reasoner và runtime. API disclosure/pacing V6–V9 không còn là authority của hot path.
"""
from .completion import CompletionGate, CompletionVerdict
from .contracts import (
    AgentTurnResult,
    AgentTurnState,
    BeatKind,
    CognitivePlan,
    ConversationSpeechPlan,
    DialogueBeat,
    DiscoursePlan,
    ExecutionPlan,
    LoopBudget,
    ResponseRelation,
    SpeechContinuationMode,
    TurnFloor,
    TurnProjection,
    TurnAction,
    TurnDecision,
)
from .reasoner import DeterministicFallbackTurnReasoner, RuntimeModelTurnReasoner, TurnReasoner
from .speech_plan import SpeechPlanLedger, SpeechPlanSnapshot
from .tutor_role import TutorRoleContribution, TutorRoleCoordinator
from .validator import SpeechPlanValidation, SpeechPlanValidator
from .runtime import TurnAgentRuntime, build_degraded_turn_result, ensure_agent_turn_runtime

__all__ = [
    "AgentTurnResult", "AgentTurnState", "BeatKind", "CognitivePlan",
    "CompletionGate", "CompletionVerdict", "ConversationSpeechPlan",
    "DeterministicFallbackTurnReasoner", "DialogueBeat", "DiscoursePlan",
    "ExecutionPlan", "LoopBudget", "ResponseRelation", "RuntimeModelTurnReasoner",
    "SpeechContinuationMode", "SpeechPlanLedger", "SpeechPlanSnapshot",
    "TurnFloor", "TurnProjection",
    "SpeechPlanValidation", "SpeechPlanValidator", "TutorRoleContribution",
    "TutorRoleCoordinator", "TurnAction", "TurnAgentRuntime", "TurnDecision",
    "TurnReasoner", "build_degraded_turn_result", "ensure_agent_turn_runtime",
]
