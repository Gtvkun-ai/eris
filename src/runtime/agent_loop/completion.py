# -*- coding: utf-8 -*-
"""Deterministic completion gate cho foreground agent loop."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import AgentTurnState, LoopBudget, TurnAction, TurnDecision


@dataclass(frozen=True, slots=True)
class CompletionVerdict:
    stop: bool
    status: str
    reason: str


class CompletionGate:
    """Model đề xuất COMPLETE/WAIT, runtime mới có quyền kết thúc vòng."""

    def evaluate(
        self,
        *,
        state: AgentTurnState,
        decision: TurnDecision,
        budget: LoopBudget,
    ) -> CompletionVerdict:
        if decision.action == TurnAction.WAIT_USER or decision.requires_user_response:
            return CompletionVerdict(True, "waiting_user", "model_requested_user_response")

        if decision.action == TurnAction.COMPLETE and decision.completion_candidate:
            if not decision.remaining_items:
                return CompletionVerdict(True, "complete", "coverage_complete")
            # COMPLETE nhưng còn checklist chưa làm là premature completion.
            if state.iteration + 1 >= budget.hard_iterations:
                return CompletionVerdict(True, "complete", "hard_budget_with_remaining_work")
            return CompletionVerdict(False, "running", "remaining_work_blocks_completion")

        if state.stall_count >= budget.stall_limit:
            return CompletionVerdict(True, "complete", "stall_guard")

        if state.iteration + 1 >= budget.hard_iterations:
            return CompletionVerdict(True, "complete", "hard_iteration_budget")

        return CompletionVerdict(False, "running", "continue")


__all__ = ["CompletionGate", "CompletionVerdict"]
