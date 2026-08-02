# -*- coding: utf-8 -*-
"""Aggregate inference-broker acceptance metrics from structured events."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

_OPTIONAL_LANES = {"vision_ambient", "post_observer", "background", "discovery", "memory_background", "social_agenda"}


def _values(events: Iterable[Mapping[str, Any]], name: str) -> list[float]:
    result = []
    for event in events:
        if str(event.get("name", "")) != name:
            continue
        value = event.get("value", 0)
        if isinstance(value, (int, float)):
            result.append(float(value))
    return result


def _percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return round(float(ordered[index]), 4)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 4) if values else None,
    }


def _rate_limits(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    optional = 0.0
    total = 0.0
    for event in events:
        if str(event.get("name", "")) != "rate_limit_429_total":
            continue
        value = float(event.get("value", 0) or 0)
        total += value
        tags = event.get("tags", {}) if isinstance(event.get("tags"), Mapping) else {}
        if str(tags.get("lane", "")) in _OPTIONAL_LANES:
            optional += value
    return {"total_429": int(total) if total.is_integer() else total, "optional_lane_429": int(optional) if optional.is_integer() else optional}


def build_report(
    events: Sequence[Mapping[str, Any]],
    *,
    baseline_events: Sequence[Mapping[str, Any]] | None = None,
    semantic_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = [dict(event) for event in events if isinstance(event, Mapping)]
    baseline = [dict(event) for event in (baseline_events or ()) if isinstance(event, Mapping)]
    current_limits = _rate_limits(current)
    baseline_limits = _rate_limits(baseline)
    before = float(baseline_limits["optional_lane_429"] or 0)
    after = float(current_limits["optional_lane_429"] or 0)
    reduction = None
    if before > 0:
        reduction = round(max(-100.0, min(100.0, (before - after) / before * 100.0)), 4)

    input_tokens = defaultdict(float)
    output_tokens = defaultdict(float)
    for event in current:
        tags = event.get("tags", {}) if isinstance(event.get("tags"), Mapping) else {}
        lane = str(tags.get("lane", "unknown"))
        value = float(event.get("value", 0) or 0)
        if event.get("name") == "input_tokens_by_lane":
            input_tokens[lane] += value
        elif event.get("name") == "output_tokens_by_lane":
            output_tokens[lane] += value
    chat_tokens = input_tokens.get("chat_main", 0.0) + output_tokens.get("chat_main", 0.0)
    background_tokens = sum(value for lane, value in input_tokens.items() if lane != "chat_main") + sum(value for lane, value in output_tokens.items() if lane != "chat_main")
    ratio = round(background_tokens / chat_tokens, 4) if chat_tokens else 0.0

    coalesced = sum(_values(current, "broker_coalesced_total"))
    cancel_before = sum(_values(current, "broker_cancel_before_start_total"))
    observer_before = sum(
        float(event.get("value", 0) or 0)
        for event in current
        if event.get("name") == "observer_discard_total"
        and isinstance(event.get("tags"), Mapping)
        and str(event["tags"].get("stage", "")) == "before_start"
    )
    critical_optional = sum(
        float(event.get("value", 0) or 0)
        for event in current
        if event.get("name") in {"optional_background_on_critical_path", "optional_lane_critical_path_total"}
    )
    semantic = dict(semantic_evaluation or {})
    semantic_accuracy = float(semantic.get("accuracy", 0.0) or 0.0)
    semantic_samples = int(semantic.get("sample_count", 0) or 0)

    report = {
        "schema": "eris.pdf_acceptance.v3",
        "user_turn_latency_ms": _distribution(_values(current, "user_turn_latency_ms")),
        "ttft_ms": _distribution(_values(current, "ttft_ms")),
        "remote_calls_per_user_turn": _distribution(_values(current, "remote_calls_per_user_turn")),
        "tokens": {
            "input_by_lane": dict(input_tokens),
            "output_by_lane": dict(output_tokens),
            "background_to_chat_ratio": ratio,
        },
        "queue": {"depth": _distribution(_values(current, "broker_queue_depth"))},
        "cancellation": {
            "coalesced_jobs": int(coalesced) if float(coalesced).is_integer() else coalesced,
            "cancelled_before_start": int(cancel_before) if float(cancel_before).is_integer() else cancel_before,
            "observer_discarded_before_start": int(observer_before) if float(observer_before).is_integer() else observer_before,
        },
        "rate_limits": current_limits,
        "baseline": {"rate_limits": baseline_limits},
        "comparison": {"optional_429_reduction_percent": reduction},
        "semantic_evaluation": semantic,
        "prompt_hard_cap": max(_values(current, "prompt_hard_cap"), default=None),
    }
    report["acceptance"] = {
        "optional_429_reduction_ge_80_percent": reduction is not None and reduction >= 80.0,
        "discourse_paraphrase_accuracy_ge_95_percent": semantic_samples > 0 and semantic_accuracy >= 0.95,
        "optional_background_on_critical_path_zero": critical_optional == 0,
    }
    return report


__all__ = ["build_report"]
