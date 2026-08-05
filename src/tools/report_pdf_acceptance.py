"""Build acceptance summaries from Eris observability events.

The report format is intentionally pure-Python and deterministic so it can be
used in tests, CI, and offline release review without pulling in a dashboard
stack merely to add several numbers together, a mercy rarely granted by modern
software.
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil
from typing import Any, Iterable, Mapping, Sequence

_OPTIONAL_LANES = frozenset({
    "vision_ambient",
    "post_observer",
    "inner_reflection",
    "seed_generation",
    "semantic_background",
    "background",
})
_CHAT_LANES = frozenset({"chat_main", "interactive", "user_turn"})


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result:
        return 0.0
    return result


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    rank = max(1, ceil((percentile / 100.0) * len(ordered)))
    return round(ordered[min(len(ordered), rank) - 1], 4)


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": round(max(values), 4) if values else 0.0,
    }


def _lane(tags: Mapping[str, Any]) -> str:
    return str(tags.get("lane", "") or "").strip().lower()


def _is_optional_lane(tags: Mapping[str, Any]) -> bool:
    lane = _lane(tags)
    if lane in _OPTIONAL_LANES:
        return True
    optional = tags.get("optional")
    return optional is True or str(optional or "").strip().lower() in {"1", "true", "yes"}


def _summarize(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    token_input: dict[str, float] = defaultdict(float)
    token_output: dict[str, float] = defaultdict(float)
    rate_429_total = 0.0
    optional_429 = 0.0
    optional_critical_path = 0.0

    for event in events:
        if not isinstance(event, Mapping):
            continue
        name = str(event.get("name", "") or "").strip()
        value = _number(event.get("value", 0.0))
        tags_raw = event.get("tags", {})
        tags = tags_raw if isinstance(tags_raw, Mapping) else {}
        values[name].append(value)
        lane = _lane(tags)
        if name == "input_tokens_by_lane":
            token_input[lane or "unknown"] += value
        elif name == "output_tokens_by_lane":
            token_output[lane or "unknown"] += value
        elif name == "rate_limit_429_total":
            rate_429_total += value
            if _is_optional_lane(tags):
                optional_429 += value
        if _is_optional_lane(tags) and (
            tags.get("critical_path") is True
            or str(tags.get("critical_path", "") or "").strip().lower() in {"1", "true", "yes"}
        ):
            optional_critical_path += value if value else 1.0

    chat_total = sum(
        token_input.get(lane, 0.0) + token_output.get(lane, 0.0)
        for lane in _CHAT_LANES
    )
    background_total = sum(
        amount for lane, amount in token_input.items() if lane not in _CHAT_LANES
    ) + sum(
        amount for lane, amount in token_output.items() if lane not in _CHAT_LANES
    )
    token_ratio = background_total / chat_total if chat_total > 0 else 0.0

    return {
        "user_turn_latency_ms": _distribution(values.get("user_turn_latency_ms", ())),
        "ttft_ms": _distribution(values.get("ttft_ms", ())),
        "remote_calls_per_user_turn": _distribution(values.get("remote_calls_per_user_turn", ())),
        "tokens": {
            "input_by_lane": {key: round(value, 4) for key, value in sorted(token_input.items())},
            "output_by_lane": {key: round(value, 4) for key, value in sorted(token_output.items())},
            "chat_total": round(chat_total, 4),
            "background_total": round(background_total, 4),
            "background_to_chat_ratio": round(token_ratio, 4),
        },
        "queue": {
            "depth": _distribution(values.get("broker_queue_depth", ())),
        },
        "cancellation": {
            "coalesced_jobs": int(round(sum(values.get("broker_coalesced_total", ())))),
            "cancelled_before_start": int(round(sum(values.get("broker_cancel_before_start_total", ())))),
            "observer_discarded_before_start": int(round(sum(
                value for value in values.get("observer_discard_total", ())
            ))),
        },
        "rate_limits": {
            "total_429": int(round(rate_429_total)),
            "optional_lane_429": int(round(optional_429)),
        },
        "prompt": {
            "hard_cap": max(values.get("prompt_hard_cap", ()), default=0.0),
        },
        "optional_background_critical_path_events": int(round(optional_critical_path)),
    }


def build_report(
    events: Iterable[Mapping[str, Any]],
    *,
    baseline_events: Iterable[Mapping[str, Any]] | None = None,
    semantic_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable ``eris.pdf_acceptance.v3`` report."""
    current = _summarize(tuple(events))
    baseline = _summarize(tuple(baseline_events or ()))
    baseline_optional = int(baseline["rate_limits"]["optional_lane_429"])
    current_optional = int(current["rate_limits"]["optional_lane_429"])
    if baseline_optional > 0:
        reduction = max(0.0, min(100.0, (baseline_optional - current_optional) * 100.0 / baseline_optional))
    else:
        reduction = 0.0
    semantic = dict(semantic_evaluation or {})
    semantic_accuracy = _number(semantic.get("accuracy", 0.0))
    semantic_samples = int(_number(semantic.get("sample_count", 0)))

    acceptance = {
        "optional_429_reduction_ge_80_percent": baseline_optional > 0 and reduction >= 80.0,
        "discourse_paraphrase_accuracy_ge_95_percent": semantic_samples > 0 and semantic_accuracy >= 0.95,
        "optional_background_on_critical_path_zero": current["optional_background_critical_path_events"] == 0,
        "prompt_hard_cap_present": current["prompt"]["hard_cap"] > 0,
    }
    report = {
        "schema": "eris.pdf_acceptance.v3",
        "user_turn_latency_ms": current["user_turn_latency_ms"],
        "ttft_ms": current["ttft_ms"],
        "remote_calls_per_user_turn": current["remote_calls_per_user_turn"],
        "tokens": current["tokens"],
        "queue": current["queue"],
        "cancellation": current["cancellation"],
        "rate_limits": current["rate_limits"],
        "prompt": current["prompt"],
        "semantic_evaluation": {
            "accuracy": round(semantic_accuracy, 4),
            "sample_count": semantic_samples,
        },
        "comparison": {
            "optional_429_reduction_percent": round(reduction, 1),
        },
        "baseline": {
            "rate_limits": baseline["rate_limits"],
            "tokens": baseline["tokens"],
        },
        "acceptance": acceptance,
    }
    return report


__all__ = ["build_report"]
