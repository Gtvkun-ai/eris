"""Paired-instance emergence evaluation."""
from .metrics import compute_metrics
from .report import ExperimentReport
from .runner import ExperimentSpec, ProbeSpec, RunResult, run_paired_experiment

__all__ = ["ExperimentReport", "ExperimentSpec", "ProbeSpec", "RunResult", "compute_metrics", "run_paired_experiment"]
