# -*- coding: utf-8 -*-
"""Build the complete acceptance report requested by the ERIS PDF.

PDF annotation, pages 17-19
---------------------------
The report requires more than two latency percentiles: TTFT, calls per turn,
tokens per lane, queue pressure, 429s, shedding, cancellation, coalescing,
observer discard and background/chat quota ratio must all be visible.  This
command reads the runtime JSONL and emits an auditable before/after report.

Usage::

    python tools/report_pdf_acceptance.py \
      --baseline logs/before.jsonl \
      --input logs/after.jsonl \
      --semantic-eval logs/semantic_paraphrase_eval.json \
      --output logs/pdf_acceptance_report.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping


OPTIONAL_LANES = {
    "tts_current_turn", "tts", "speech_localizer", "tts_localizer",
    "romaji_localizer", "post_observer", "memory_digest",
    "private_mind", "private_mind_optional", "tutor_background",
    "micro_presence", "autonomous", "vision_ambient", "vision_compressor",
}
CHAT_LANES = {"chat_main", "chat", "chat_tool_required", "directive"}
SHED_REASONS = {
    "shed_optional_user_active", "provider_hot_optional",
    "quota_unavailable_optional", "concurrency_unavailable_optional",
    "queue_full", "lane_kill_switch", "preempted_by_user_turn",
}


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(math.ceil(len(ordered) * fraction) - 1)))
    return round(ordered[index], 3)


def _stats(values: Iterable[float]) -> dict[str, Any]:
    items = [float(value) for value in values]
    return {
        "count": len(items),
        "average": round(mean(items), 4) if items else None,
        "p50": _percentile(items, 0.50),
        "p95": _percentile(items, 0.95),
        "p99": _percentile(items, 0.99),
        "max": round(max(items), 3) if items else None,
        "sum": round(sum(items), 3) if items else 0.0,
    }


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL không hợp lệ ở dòng {line_number}: {exc}") from exc
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _tags(event: Mapping[str, Any]) -> dict[str, str]:
    raw = event.get("tags") if isinstance(event.get("tags"), dict) else {}
    return {str(key): str(value) for key, value in dict(raw or {}).items()}


def _value(event: Mapping[str, Any]) -> float | None:
    value = event.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _group_stats(events: list[dict[str, Any]], metric: str, tag: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if str(event.get("name", "") or "") != metric:
            continue
        value = _value(event)
        if value is None:
            continue
        grouped[_tags(event).get(tag, "unknown")].append(value)
    return {key: _stats(values) for key, values in sorted(grouped.items())}


def _counter_by_tags(
    events: list[dict[str, Any]], metric: str, keys: tuple[str, ...]
) -> Counter[str]:
    output: Counter[str] = Counter()
    for event in events:
        if str(event.get("name", "") or "") != metric:
            continue
        tags = _tags(event)
        label = "/".join(tags.get(key, "unknown") for key in keys)
        output[label] += int(_value(event) or 1)
    return output


def _load_semantic_eval(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("semantic eval phải là JSON object")
    return payload


def _summarize_events(
    events: list[dict[str, Any]],
    *,
    semantic_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metric_values: dict[str, list[float]] = defaultdict(list)
    rejection_reasons: Counter[str] = Counter()
    rate_limits_by_lane: Counter[str] = Counter()
    rate_limits_by_provider_model_lane: Counter[str] = Counter()
    observer_discard: Counter[str] = Counter()

    for event in events:
        name = str(event.get("name", "") or "")
        value = _value(event)
        tags = _tags(event)
        if value is not None:
            metric_values[name].append(value)
        if name == "broker_rejected_total":
            rejection_reasons[tags.get("reason", "unknown")] += int(value or 1)
        elif name == "rate_limit_429_total":
            lane = tags.get("lane", "unknown")
            rate_limits_by_lane[lane] += int(value or 1)
            key = "/".join((tags.get("provider", "unknown"), tags.get("model", "unknown"), lane))
            rate_limits_by_provider_model_lane[key] += int(value or 1)
        elif name == "observer_discard_total":
            observer_discard[tags.get("stage", "unknown")] += int(value or 1)

    def select(metric: str, *, small_talk: bool = False) -> list[float]:
        selected: list[float] = []
        fallback: list[float] = []
        for event in events:
            if str(event.get("name", "") or "") != metric:
                continue
            value = _value(event)
            if value is None:
                continue
            fallback.append(value)
            tags = _tags(event)
            category = tags.get("turn_category", tags.get("reason", ""))
            if category == "small_talk":
                selected.append(value)
        return selected if small_talk and selected else fallback

    latency = select("user_turn_latency_ms", small_talk=True)
    ttft = select("ttft_ms", small_talk=True)
    calls = select("remote_calls_per_user_turn", small_talk=True)

    input_by_lane = _group_stats(events, "input_tokens_by_lane", "lane")
    output_by_lane = _group_stats(events, "output_tokens_by_lane", "lane")
    queue_wait_by_lane = _group_stats(events, "broker_queue_wait_ms", "lane")
    queue_depth_by_lane = _group_stats(events, "broker_queue_depth", "lane")

    lane_tokens: dict[str, float] = defaultdict(float)
    for lane, item in input_by_lane.items():
        lane_tokens[lane] += float(item.get("sum", 0.0) or 0.0)
    for lane, item in output_by_lane.items():
        lane_tokens[lane] += float(item.get("sum", 0.0) or 0.0)
    background_tokens = sum(value for lane, value in lane_tokens.items() if lane in OPTIONAL_LANES)
    chat_tokens = sum(value for lane, value in lane_tokens.items() if lane in CHAT_LANES)
    background_to_chat_ratio = (
        round(background_tokens / chat_tokens, 4) if chat_tokens > 0.0 else None
    )

    optional_429 = sum(count for lane, count in rate_limits_by_lane.items() if lane in OPTIONAL_LANES)
    chat_429 = sum(count for lane, count in rate_limits_by_lane.items() if lane in CHAT_LANES)
    shed_total = sum(count for reason, count in rejection_reasons.items() if reason in SHED_REASONS)
    optional_on_critical = int(sum(metric_values.get("optional_background_admitted_during_user_turn_total", [])))
    coalesced = int(sum(metric_values.get("broker_coalesced_total", [])))
    cancel_before_start = int(sum(metric_values.get("broker_cancel_before_start_total", [])))
    cancel_inflight = int(sum(metric_values.get("broker_cancel_inflight_total", [])))
    targeted_preemptions = int(
        sum(metric_values.get("broker_optional_inflight_preempted_total", []))
    )
    required_degraded = int(sum(metric_values.get("broker_required_degraded_total", [])))
    degraded_input_saved = float(
        sum(metric_values.get("broker_degraded_input_tokens_saved", []))
    )
    degraded_output_saved = float(
        sum(metric_values.get("broker_degraded_output_tokens_saved", []))
    )
    observer_total_discard = sum(observer_discard.values())
    observer_inflight = observer_discard.get("inflight_or_started", 0)
    observer_inflight_rate = (
        round(observer_inflight / observer_total_discard, 4) if observer_total_discard else 0.0
    )

    hard_caps = metric_values.get("prompt_hard_cap", [])
    hard_cap_default_ok = None
    if hard_caps:
        hard_cap_default_ok = all(512.0 <= value < 1_000_000_000.0 for value in hard_caps)

    semantic_accuracy = None
    semantic_sample_count = 0
    if semantic_evaluation:
        raw_accuracy = semantic_evaluation.get("accuracy")
        if isinstance(raw_accuracy, (int, float)):
            semantic_accuracy = round(float(raw_accuracy), 4)
        semantic_sample_count = int(semantic_evaluation.get("sample_count", 0) or 0)

    latency_stats = _stats(latency)
    ttft_stats = _stats(ttft)
    call_stats = _stats(calls)
    acceptance = {
        "p50_small_talk_le_2000ms": None if latency_stats["p50"] is None else latency_stats["p50"] <= 2000.0,
        "p95_small_talk_le_4000ms": None if latency_stats["p95"] is None else latency_stats["p95"] <= 4000.0,
        "remote_calls_avg_le_1_1": None if call_stats["average"] is None else call_stats["average"] <= 1.1,
        "optional_background_on_critical_path_zero": optional_on_critical == 0,
        "discourse_paraphrase_accuracy_ge_95_percent": (
            None if semantic_accuracy is None else semantic_accuracy >= 0.95
        ),
        "observer_inflight_discard_rate_le_5_percent": observer_inflight_rate <= 0.05,
        "token_hard_cap_default_effective": hard_cap_default_ok,
    }

    return {
        "schema": "eris.pdf_acceptance.window.v3",
        "event_count": len(events),
        "sample_count": {
            "user_turn_latency": latency_stats["count"],
            "ttft": ttft_stats["count"],
            "remote_calls_per_user_turn": call_stats["count"],
            "semantic_paraphrases": semantic_sample_count,
        },
        "latency_ms": latency_stats,
        "ttft_ms": ttft_stats,
        "remote_calls_per_user_turn": call_stats,
        "tokens": {
            "input_by_lane": input_by_lane,
            "output_by_lane": output_by_lane,
            "background_total": round(background_tokens, 3),
            "chat_total": round(chat_tokens, 3),
            "background_to_chat_ratio": background_to_chat_ratio,
        },
        "queues": {
            "wait_ms_by_lane": queue_wait_by_lane,
            "depth_by_lane": queue_depth_by_lane,
        },
        "rate_limits": {
            "optional_lane_429": optional_429,
            "chat_lane_429": chat_429,
            "by_lane": dict(sorted(rate_limits_by_lane.items())),
            "by_provider_model_lane": dict(sorted(rate_limits_by_provider_model_lane.items())),
        },
        "load_shedding": {
            "shed_total": shed_total,
            "rejections": dict(sorted(rejection_reasons.items())),
            "optional_admitted_during_user_turn": optional_on_critical,
        },
        "cancellation": {
            "cancel_before_start": cancel_before_start,
            "cancel_inflight": cancel_inflight,
            "targeted_optional_preemptions": targeted_preemptions,
            "coalesced_jobs": coalesced,
        },
        "adaptive_degradation": {
            "required_requests_degraded": required_degraded,
            "input_tokens_saved": round(degraded_input_saved, 3),
            "output_tokens_saved": round(degraded_output_saved, 3),
        },
        "observer": {
            "discard_by_stage": dict(sorted(observer_discard.items())),
            "inflight_discard_rate": observer_inflight_rate,
        },
        "semantic": {
            "authority": "semantic_frame.v1",
            "paraphrase_accuracy": semantic_accuracy,
            "paraphrase_sample_count": semantic_sample_count,
        },
        "prompt_hard_cap": {
            "samples": _stats(hard_caps),
            "default_effective": hard_cap_default_ok,
        },
        "acceptance": acceptance,
        "notes": [
            "Small-talk percentile uses turn_category=small_talk when available; older logs fall back to all chat turns.",
            "Use --semantic-eval for the >=95% semantic-frame paraphrase criterion.",
            "Adaptive degradation counts only requests whose transport rewrote the actual payload to the smaller reservation.",
        ],
    }


def _reduction_percent(before: int | float, after: int | float) -> float | None:
    baseline = float(before or 0.0)
    if baseline <= 0.0:
        return None
    return round(((baseline - float(after or 0.0)) / baseline) * 100.0, 3)


def build_report(
    events: list[dict[str, Any]],
    *,
    baseline_events: list[dict[str, Any]] | None = None,
    semantic_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = _summarize_events(events, semantic_evaluation=semantic_evaluation)
    baseline = _summarize_events(baseline_events or []) if baseline_events is not None else None
    optional_reduction = None
    chat_reduction = None
    if baseline is not None:
        optional_reduction = _reduction_percent(
            baseline["rate_limits"]["optional_lane_429"],
            current["rate_limits"]["optional_lane_429"],
        )
        chat_reduction = _reduction_percent(
            baseline["rate_limits"]["chat_lane_429"],
            current["rate_limits"]["chat_lane_429"],
        )

    acceptance = dict(current.get("acceptance", {}))
    acceptance["optional_429_reduction_ge_80_percent"] = (
        None if optional_reduction is None else optional_reduction >= 80.0
    )
    current["acceptance"] = acceptance
    current["schema"] = "eris.pdf_acceptance.v3"
    current["comparison"] = {
        "baseline_supplied": baseline is not None,
        "optional_429_reduction_percent": optional_reduction,
        "chat_429_reduction_percent": chat_reduction,
    }
    if baseline is not None:
        current["baseline"] = {
            "event_count": baseline["event_count"],
            "sample_count": baseline["sample_count"],
            "latency_ms": baseline["latency_ms"],
            "ttft_ms": baseline["ttft_ms"],
            "remote_calls_per_user_turn": baseline["remote_calls_per_user_turn"],
            "rate_limits": baseline["rate_limits"],
            "tokens": baseline["tokens"],
        }
    else:
        current.setdefault("notes", []).append(
            "Tiêu chí giảm 429 >=80% cần --baseline để tính before/after."
        )
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="Tạo báo cáo acceptance đầy đủ theo PDF từ ERIS JSONL")
    parser.add_argument("--input", default="logs/eris_observability.jsonl", help="JSONL sau refactor")
    parser.add_argument("--baseline", default="", help="JSONL baseline trước refactor")
    parser.add_argument("--semantic-eval", default="", help="JSON kết quả paraphrase semantic evaluation")
    parser.add_argument("--output", default="", help="File JSON đầu ra; bỏ trống để in stdout")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Không tìm thấy file observability: {source}")
    baseline_events = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            raise SystemExit(f"Không tìm thấy file baseline: {baseline_path}")
        baseline_events = _load_events(baseline_path)
    semantic_eval = None
    if args.semantic_eval:
        semantic_path = Path(args.semantic_eval)
        if not semantic_path.exists():
            raise SystemExit(f"Không tìm thấy semantic eval: {semantic_path}")
        semantic_eval = _load_semantic_eval(semantic_path)

    report = build_report(
        _load_events(source),
        baseline_events=baseline_events,
        semantic_evaluation=semantic_eval,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(target)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
