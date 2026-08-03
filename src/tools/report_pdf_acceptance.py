# -*- coding: utf-8 -*-
"""Tổng hợp metric acceptance của refactor inference từ event đã redaction."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def _values(events: Sequence[Mapping[str, Any]], name: str) -> list[float]:
    result: list[float] = []
    for event in events:
        if str(event.get("name", "") or "") != name:
            continue
        try:
            result.append(float(event.get("value", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return result


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return round(ordered[0], 4)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    weight = position - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 4)


def _metric_summary(events: Sequence[Mapping[str, Any]], name: str) -> dict[str, float]:
    values = _values(events, name)
    return {
        "count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": round(max(values), 4) if values else 0.0,
    }


def _sum_by_lane(events: Sequence[Mapping[str, Any]], name: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for event in events:
        if str(event.get("name", "") or "") != name:
            continue
        tags = event.get("tags", {}) if isinstance(event.get("tags"), Mapping) else {}
        lane = str(tags.get("lane", "unknown") or "unknown")
        try:
            value = float(event.get("value", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        totals[lane] = totals.get(lane, 0.0) + value
    return totals


def _optional_429(events: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for event in events:
        if str(event.get("name", "") or "") != "rate_limit_429_total":
            continue
        tags = event.get("tags", {}) if isinstance(event.get("tags"), Mapping) else {}
        lane = str(tags.get("lane", "") or "").lower()
        if lane and lane not in {"chat_main", "user_chat", "required"}:
            try:
                count += int(float(event.get("value", 1) or 1))
            except (TypeError, ValueError):
                count += 1
    return count


def build_report(
    events: Sequence[Mapping[str, Any]],
    *,
    baseline_events: Sequence[Mapping[str, Any]] | None = None,
    semantic_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = tuple(event for event in events if isinstance(event, Mapping))
    baseline = tuple(event for event in (baseline_events or ()) if isinstance(event, Mapping))
    input_by_lane = _sum_by_lane(current, "input_tokens_by_lane")
    output_by_lane = _sum_by_lane(current, "output_tokens_by_lane")
    chat_tokens = input_by_lane.get("chat_main", 0.0) + output_by_lane.get("chat_main", 0.0)
    background_tokens = sum(value for lane, value in input_by_lane.items() if lane != "chat_main")
    background_tokens += sum(value for lane, value in output_by_lane.items() if lane != "chat_main")
    ratio = background_tokens / chat_tokens if chat_tokens else 0.0

    current_429 = _optional_429(current)
    baseline_429 = _optional_429(baseline)
    reduction = ((baseline_429 - current_429) / baseline_429 * 100.0) if baseline_429 else 0.0
    semantic_accuracy = float((semantic_evaluation or {}).get("accuracy", 0.0) or 0.0)
    critical_path_optional = sum(_values(current, "optional_background_critical_path_total"))

    cancellation = {
        "coalesced_jobs": int(sum(_values(current, "broker_coalesced_total"))),
        "cancelled_before_start": int(sum(_values(current, "broker_cancel_before_start_total"))),
        "observer_discarded_before_start": int(sum(
            float(event.get("value", 0.0) or 0.0)
            for event in current
            if str(event.get("name", "") or "") == "observer_discard_total"
            and str((event.get("tags", {}) or {}).get("stage", "") or "") == "before_start"
        )),
    }
    acceptance = {
        "optional_429_reduction_ge_80_percent": baseline_429 > 0 and reduction >= 80.0,
        "discourse_paraphrase_accuracy_ge_95_percent": semantic_accuracy >= 0.95,
        "optional_background_on_critical_path_zero": critical_path_optional == 0,
    }
    return {
        "schema": "eris.pdf_acceptance.v3",
        "user_turn_latency_ms": _metric_summary(current, "user_turn_latency_ms"),
        "ttft_ms": _metric_summary(current, "ttft_ms"),
        "remote_calls_per_user_turn": _metric_summary(current, "remote_calls_per_user_turn"),
        "tokens": {
            "input_by_lane": input_by_lane,
            "output_by_lane": output_by_lane,
            "background_to_chat_ratio": round(ratio, 4),
        },
        "queue_depth": _metric_summary(current, "broker_queue_depth"),
        "cancellation": cancellation,
        "rate_limits": {"optional_lane_429": current_429},
        "baseline": {"rate_limits": {"optional_lane_429": baseline_429}},
        "comparison": {"optional_429_reduction_percent": round(reduction, 1)},
        "semantic_evaluation": dict(semantic_evaluation or {}),
        "acceptance": acceptance,
    }


__all__ = ["build_report"]
