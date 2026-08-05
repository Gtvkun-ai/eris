# -*- coding: utf-8 -*-
"""Paired experiment runner with seed-matched instances."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from .interventions import apply_history, remove_personality_descriptions
from .metrics import compute_metrics
from .paired_instances import clone_instance
from .report import ExperimentReport


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    probe_id: str
    payload: Mapping[str, Any]
    repetitions: int = 1


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    scenario_id: str
    initial_snapshot: str
    seeds: tuple[int, ...]
    control_history: tuple[Mapping[str, Any], ...]
    treatment_history: tuple[Mapping[str, Any], ...]
    probes: tuple[ProbeSpec, ...]
    acceptance_thresholds: Mapping[str, float]
    remove_personality_prompt: bool = True
    code_revision: str = "unknown"
    algorithm_version: str = "subject-core-v1"


@dataclass(frozen=True, slots=True)
class RunResult:
    seed: int
    condition: str
    probe_id: str
    repetition: int
    features: Mapping[str, float]

    def to_metric_row(self) -> dict[str, object]:
        return {"seed": self.seed, "condition": self.condition, "probe_id": self.probe_id, **dict(self.features)}


async def _run_probe(instance: Any, probe: ProbeSpec, repetition: int) -> Mapping[str, float]:
    method = getattr(instance, "run_probe", None)
    if method is None:
        raise TypeError("experiment instance must implement run_probe")
    result = method(probe.payload, repetition=repetition)
    if hasattr(result, "__await__"):
        result = await result
    return {str(key): float(value) for key, value in dict(result).items()}


async def run_paired_experiment(
    spec: ExperimentSpec,
    *,
    instance_factory: Callable[[str, int], Any],
) -> ExperimentReport:
    results: list[RunResult] = []
    for seed in spec.seeds:
        control = await clone_instance(instance_factory, spec.initial_snapshot, seed=seed)
        treatment = await clone_instance(instance_factory, spec.initial_snapshot, seed=seed)
        await apply_history(control, spec.control_history)
        await apply_history(treatment, spec.treatment_history)
        if spec.remove_personality_prompt:
            remove_personality_descriptions(control)
            remove_personality_descriptions(treatment)
        for probe in spec.probes:
            for repetition in range(probe.repetitions):
                control_features, treatment_features = await asyncio.gather(
                    _run_probe(control, probe, repetition),
                    _run_probe(treatment, probe, repetition),
                )
                results.extend((
                    RunResult(seed, "control", probe.probe_id, repetition, control_features),
                    RunResult(seed, "treatment", probe.probe_id, repetition, treatment_features),
                ))
    metrics = compute_metrics(result.to_metric_row() for result in results)
    failures = []
    for key, threshold in spec.acceptance_thresholds.items():
        value = float(metrics.get(key, float("-inf")))
        if value < float(threshold):
            failures.append(f"{key}={value:.4f} < {threshold:.4f}")
    return ExperimentReport(
        scenario_id=spec.scenario_id,
        code_revision=spec.code_revision,
        algorithm_version=spec.algorithm_version,
        metrics=metrics,
        thresholds=dict(spec.acceptance_thresholds),
        passed=not failures,
        run_count=len(results),
        notes=tuple(failures),
    )
