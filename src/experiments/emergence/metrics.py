# -*- coding: utf-8 -*-
"""Pre-registered behavioral metrics without style-only features."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Iterable, Mapping


def auroc(labels: Iterable[int], scores: Iterable[float]) -> float:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    positives = sum(label == 1 for _, label in pairs)
    negatives = sum(label == 0 for _, label in pairs)
    if positives == 0 or negatives == 0:
        return 0.5
    rank_sum = 0.0
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(pairs[i][1] == 1 for i in range(index, end))
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def brier(labels: Iterable[float], probabilities: Iterable[float]) -> float:
    pairs = list(zip(labels, probabilities))
    if not pairs:
        return 0.0
    return mean((float(probability) - float(label)) ** 2 for label, probability in pairs)


def log_loss(labels: Iterable[float], probabilities: Iterable[float]) -> float:
    pairs = list(zip(labels, probabilities))
    if not pairs:
        return 0.0
    epsilon = 1e-9
    return -mean(
        float(label) * math.log(max(epsilon, min(1.0 - epsilon, float(probability))))
        + (1.0 - float(label)) * math.log(max(epsilon, min(1.0 - epsilon, 1.0 - float(probability))))
        for label, probability in pairs
    )


def standardized_difference(control: Iterable[float], treatment: Iterable[float]) -> float:
    left, right = list(control), list(treatment)
    if not left or not right:
        return 0.0
    pooled = left + right
    variance = mean((item - mean(pooled)) ** 2 for item in pooled)
    return (mean(right) - mean(left)) / math.sqrt(variance + 1e-12)


def compute_metrics(results: Iterable[Mapping[str, object]]) -> dict[str, float]:
    rows = list(results)
    labels = [1 if row.get("condition") == "treatment" else 0 for row in rows]
    classifier_scores = [float(row.get("history_score", 0.5)) for row in rows]
    target = [float(row.get("target_behavior", 0.0)) for row in rows]
    control = [target[i] for i, label in enumerate(labels) if label == 0]
    treatment = [target[i] for i, label in enumerate(labels) if label == 1]
    predictions = [float(row.get("predicted_success", 0.5)) for row in rows]
    outcomes = [float(row.get("observed_success", 0.0)) for row in rows]
    context_loss = [float(row.get("context_only_loss", 0.0)) for row in rows]
    history_loss = [float(row.get("history_loss", 0.0)) for row in rows]
    return {
        "history_classifier_auroc": auroc(labels, classifier_scores),
        "behavior_effect_d": standardized_difference(control, treatment),
        "brier_score": brier(outcomes, predictions),
        "log_loss": log_loss(outcomes, predictions),
        "history_log_loss_improvement": (
            (mean(context_loss) - mean(history_loss)) / max(abs(mean(context_loss)), 1e-9)
            if context_loss and history_loss else 0.0
        ),
        "control_mean": mean(control) if control else 0.0,
        "treatment_mean": mean(treatment) if treatment else 0.0,
    }
