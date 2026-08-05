# -*- coding: utf-8 -*-
"""Competence calibration and practice planning."""
from __future__ import annotations

from typing import Callable

from .contracts import (
    CompetenceEstimate,
    CompetenceGap,
    PracticePlan,
    ProcessingBudget,
    ProjectState,
    Value,
)


class CompetenceService:
    def __init__(self, id_factory: Callable[[], str], clock: Callable[[], float]) -> None:
        self._id_factory = id_factory
        self._clock = clock
        self._estimates: dict[tuple[str, str], CompetenceEstimate] = {}

    def predict(self, skill_id: str, context_key: str = "general") -> float:
        estimate = self._estimates.get((skill_id, context_key))
        return estimate.posterior_mean if estimate else 0.5

    def update(
        self,
        task: str,
        prediction: float,
        result: float,
        *,
        skill_id: str | None = None,
        context_key: str = "general",
        result_ref: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> CompetenceEstimate:
        skill_id = skill_id or task
        prediction = max(0.0, min(1.0, float(prediction)))
        result = max(0.0, min(1.0, float(result)))
        previous = self._estimates.get((skill_id, context_key))
        alpha = 1.0 + (previous.success_count if previous else 0)
        beta = 1.0 + ((previous.trial_count - previous.success_count) if previous else 0)
        alpha += result
        beta += 1.0 - result
        mean = alpha / (alpha + beta)
        variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
        trials = (previous.trial_count if previous else 0) + 1
        successes = (previous.success_count if previous else 0) + int(result >= 0.5)
        brier_current = (prediction - result) ** 2
        brier = ((previous.brier_score * (trials - 1)) + brier_current) / trials if previous else brier_current
        calibration = abs(prediction - result)
        estimate = CompetenceEstimate(
            estimate_id=self._id_factory(),
            skill_id=skill_id,
            context_key=context_key,
            posterior_mean=mean,
            posterior_variance=variance,
            trial_count=trials,
            success_count=successes,
            calibration_error=calibration,
            brier_score=brier,
            last_prediction=prediction,
            last_result_ref=result_ref,
            evidence_refs=tuple(dict.fromkeys((*evidence_refs, result_ref))),
            estimated_at=self._clock(),
        )
        self._estimates[(skill_id, context_key)] = estimate
        return estimate

    def all(self) -> tuple[CompetenceEstimate, ...]:
        return tuple(sorted(self._estimates.values(), key=lambda item: (item.skill_id, item.context_key)))


class PracticePlanner:
    def __init__(self, id_factory: Callable[[], str], clock: Callable[[], float]) -> None:
        self._id_factory = id_factory
        self._clock = clock

    def plan(
        self,
        *,
        gaps: tuple[CompetenceGap, ...],
        available_projects: tuple[ProjectState, ...],
        processing_budget: ProcessingBudget,
        current_values: tuple[Value, ...],
    ) -> PracticePlan | None:
        del current_values
        if not gaps or processing_budget.max_tasks <= 0:
            return None
        ordered = sorted(gaps, key=lambda gap: (-(gap.target_level - gap.current_level), gap.skill_id))
        selected = ordered[: processing_budget.max_tasks]
        project_tasks = [
            task
            for project in sorted(available_projects, key=lambda item: (-item.viability, item.project_id))
            for task in project.available_tasks
        ]
        exercise_tasks = tuple(project_tasks[: len(selected)] or [f"practice:{gap.skill_id}" for gap in selected])
        difficulties = tuple(max(0.05, min(0.95, gap.current_level + 0.10)) for gap in selected)
        return PracticePlan(
            plan_id=self._id_factory(),
            target_skill_ids=tuple(gap.skill_id for gap in selected),
            exercise_tasks=exercise_tasks,
            difficulty_schedule=difficulties,
            success_criteria=tuple(f"externally_scored:{gap.skill_id}" for gap in selected),
            resource_budget=processing_budget,
            stop_conditions=("environmental_failure_repeats", "processing_budget_exhausted"),
            transfer_probe=f"transfer:{selected[0].skill_id}:new_context",
            created_at=self._clock(),
        )
