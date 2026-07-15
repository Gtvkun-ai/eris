from __future__ import annotations

"""Observability tối thiểu nhưng dùng được cho ERIS.

Module này gom ba signal mà báo cáo yêu cầu: metrics, traces và logs. Nó không
ép dự án phải cài OpenTelemetry ngay lập tức. Runtime ghi JSONL có cấu trúc,
giữ snapshot trong RAM và có thể xuất payload dashboard. Khi muốn nối OTEL thật,
chỉ cần viết exporter đọc cùng event schema thay vì sửa lại từng lane.

Các nguyên tắc cố ý:
- Không để observability làm sập lượt chat.
- Không ghi nguyên prompt, key, ảnh hay nội dung nhạy cảm.
- Tag phải nhỏ và có cardinality thấp; turn/session id nằm trong fields, không
  làm label metric. Con người đã đủ đau khổ vì cardinality explosion rồi.
"""

import hashlib
import json
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _safe_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _clean_mapping(value: Mapping[str, Any] | None, *, limit: int = 32) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for index, (key, item) in enumerate(dict(value or {}).items()):
        if index >= limit:
            break
        name = _safe_text(key, 64)
        if isinstance(item, (bool, int, float)) or item is None:
            out[name] = item
        elif isinstance(item, str):
            out[name] = _safe_text(item)
        elif isinstance(item, (list, tuple, set)):
            out[name] = [_safe_text(part, 120) for part in list(item)[:12]]
        elif isinstance(item, Mapping):
            out[name] = _clean_mapping(item, limit=12)
        else:
            out[name] = _safe_text(item)
    return out


@dataclass(slots=True, frozen=True)
class TelemetryEvent:
    signal: str
    name: str
    timestamp: float
    value: float | None = None
    tags: dict[str, str] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    duration_ms: float | None = None
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, "", {}, [])}


@dataclass(slots=True)
class MetricSeries:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    recent: deque[float] = field(default_factory=lambda: deque(maxlen=512))

    def add(self, value: float) -> None:
        number = float(value)
        self.count += 1
        self.total += number
        self.minimum = number if self.minimum is None else min(self.minimum, number)
        self.maximum = number if self.maximum is None else max(self.maximum, number)
        self.recent.append(number)

    def snapshot(self) -> dict[str, float | int | None]:
        values = sorted(self.recent)

        def percentile(p: float) -> float | None:
            if not values:
                return None
            index = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
            return round(float(values[index]), 4)

        return {
            "count": self.count,
            "sum": round(self.total, 4),
            "avg": round(self.total / self.count, 4) if self.count else None,
            "min": round(self.minimum, 4) if self.minimum is not None else None,
            "max": round(self.maximum, 4) if self.maximum is not None else None,
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        }


class ErisObservability:
    """Thread-safe event/metric store cho một runtime process."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        jsonl_path: str | os.PathLike[str] | None = None,
        ring_size: int = 2000,
    ) -> None:
        if enabled is None:
            try:
                from runtime.runtime_settings_store import runtime_bool
                self.enabled = runtime_bool("observability", "enabled", default=True)
            except Exception:
                self.enabled = _env_bool("ERIS_OBSERVABILITY_ENABLED", True)
        else:
            self.enabled = bool(enabled)
        default_path = os.getenv("ERIS_OBSERVABILITY_JSONL", "logs/eris_observability.jsonl")
        self.jsonl_path = Path(jsonl_path or default_path)
        self.write_jsonl = self.enabled and _env_bool("ERIS_OBSERVABILITY_WRITE_JSONL", not bool(os.getenv("PYTEST_CURRENT_TEST")))
        self._events: deque[TelemetryEvent] = deque(maxlen=max(128, int(ring_size)))
        self._metrics: dict[tuple[str, tuple[tuple[str, str], ...]], MetricSeries] = defaultdict(MetricSeries)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._lock = threading.RLock()
        self._process_trace_id = uuid.uuid4().hex

    @staticmethod
    def _tags(tags: Mapping[str, Any] | None) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for index, (key, value) in enumerate(dict(tags or {}).items()):
            if index >= 16:
                break
            cleaned[_safe_text(key, 48)] = _safe_text(value, 80)
        return cleaned

    def emit(
        self,
        signal: str,
        name: str,
        *,
        value: float | None = None,
        tags: Mapping[str, Any] | None = None,
        fields: Mapping[str, Any] | None = None,
        trace_id: str = "",
        span_id: str = "",
        parent_span_id: str = "",
        duration_ms: float | None = None,
        status: str = "ok",
        timestamp: float | None = None,
    ) -> TelemetryEvent | None:
        if not self.enabled:
            return None
        event = TelemetryEvent(
            signal=_safe_text(signal, 24) or "log",
            name=_safe_text(name, 96) or "unnamed",
            timestamp=float(time.time() if timestamp is None else timestamp),
            value=None if value is None else float(value),
            tags=self._tags(tags),
            fields=_clean_mapping(fields),
            trace_id=_safe_text(trace_id or self._process_trace_id, 64),
            span_id=_safe_text(span_id, 64),
            parent_span_id=_safe_text(parent_span_id, 64),
            duration_ms=None if duration_ms is None else max(0.0, float(duration_ms)),
            status=_safe_text(status, 24) or "ok",
        )
        with self._lock:
            self._events.append(event)
            if event.signal == "metric" and event.value is not None:
                key = (event.name, tuple(sorted(event.tags.items())))
                self._metrics[key].add(event.value)
            elif event.signal == "gauge" and event.value is not None:
                key = (event.name, tuple(sorted(event.tags.items())))
                self._gauges[key] = event.value
            if self.write_jsonl:
                self._append_jsonl_locked(event)
        return event

    def increment(self, name: str, value: float = 1.0, *, tags: Mapping[str, Any] | None = None, fields: Mapping[str, Any] | None = None) -> None:
        self.emit("metric", name, value=value, tags=tags, fields=fields)

    def observe(self, name: str, value: float, *, tags: Mapping[str, Any] | None = None, fields: Mapping[str, Any] | None = None) -> None:
        self.emit("metric", name, value=value, tags=tags, fields=fields)

    def gauge(self, name: str, value: float, *, tags: Mapping[str, Any] | None = None, fields: Mapping[str, Any] | None = None) -> None:
        self.emit("gauge", name, value=value, tags=tags, fields=fields)

    def log(self, name: str, *, tags: Mapping[str, Any] | None = None, fields: Mapping[str, Any] | None = None, status: str = "ok") -> None:
        self.emit("log", name, tags=tags, fields=fields, status=status)

    @contextmanager
    def span(
        self,
        name: str,
        *,
        tags: Mapping[str, Any] | None = None,
        fields: Mapping[str, Any] | None = None,
        trace_id: str = "",
        parent_span_id: str = "",
    ) -> Iterator[dict[str, str]]:
        span_id = uuid.uuid4().hex[:16]
        actual_trace = trace_id or self._process_trace_id
        started = time.perf_counter()
        status = "ok"
        error_type = ""
        try:
            yield {"trace_id": actual_trace, "span_id": span_id}
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            payload = dict(fields or {})
            if error_type:
                payload["error_type"] = error_type
            self.emit(
                "trace",
                name,
                tags=tags,
                fields=payload,
                trace_id=actual_trace,
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                status=status,
            )

    def _append_jsonl_locked(self, event: TelemetryEvent) -> None:
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            # Telemetry không được phép biến thành single point of failure.
            self.write_jsonl = False

    def recent_events(self, *, limit: int = 100, signal: str = "") -> list[dict[str, Any]]:
        with self._lock:
            selected = list(self._events)
        if signal:
            selected = [event for event in selected if event.signal == signal]
        return [event.to_dict() for event in selected[-max(1, int(limit)):]]

    def metric_snapshot(self) -> dict[str, Any]:
        with self._lock:
            metrics = list(self._metrics.items())
            gauges = list(self._gauges.items())
        output: dict[str, Any] = {}
        for (name, tags), series in metrics:
            key = self._series_key(name, tags)
            output[key] = series.snapshot()
        for (name, tags), value in gauges:
            key = self._series_key(name, tags)
            output[key] = {"gauge": round(float(value), 4)}
        return output

    @staticmethod
    def _series_key(name: str, tags: tuple[tuple[str, str], ...]) -> str:
        if not tags:
            return name
        rendered = ",".join(f"{key}={value}" for key, value in tags)
        return f"{name}{{{rendered}}}"

    def dashboard_payload(self) -> dict[str, Any]:
        """Trả bốn dashboard đúng nhóm metric trong báo cáo PDF."""

        snapshot = self.metric_snapshot()
        groups = {
            "social_intent_policy": (
                "social_intent_", "performative_", "literal_", "permission_", "revoke_", "autonomous_bypass_",
            ),
            "prompt_token_economics": (
                "input_tokens_", "output_tokens_", "cache_hit_", "candidates_", "cost_", "rate_limit_429_",
                "retry_after_", "ttft_", "end_to_end_latency_", "token_pressure_",
            ),
            "guard_grounding": (
                "guard_delete_", "escalation_", "abstain_", "vision_claim_", "contradiction_",
                "empty_output_", "json_parse_failure_",
            ),
            "user_quality_rollout": (
                "session_retention_", "manual_disable_", "thumbs_down_", "rollback_", "canary_",
                "user_accepted_", "user_corrected_", "user_intruded_", "relation_ruptured_",
            ),
        }
        dashboards: dict[str, dict[str, Any]] = {name: {} for name in groups}
        for metric_name, value in snapshot.items():
            bare = metric_name.split("{", 1)[0]
            for dashboard, prefixes in groups.items():
                if bare.startswith(prefixes):
                    dashboards[dashboard][metric_name] = value
                    break
        return {
            "generated_at": time.time(),
            "dashboards": dashboards,
            "recent_events": self.recent_events(limit=80),
        }

    def export_snapshot(self, path: str | os.PathLike[str]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.dashboard_payload()
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    @classmethod
    def replay_jsonl(cls, path: str | os.PathLike[str]) -> "ErisObservability":
        """Dựng lại snapshot từ event log để dùng ngoài process runtime."""

        source = Path(path)
        store = cls(enabled=True, jsonl_path=source)
        store.write_jsonl = False
        if not source.exists():
            return store
        for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                store.emit(
                    str(item.get("signal", "log")),
                    str(item.get("name", "unnamed")),
                    value=item.get("value"),
                    tags=item.get("tags", {}),
                    fields=item.get("fields", {}),
                    trace_id=str(item.get("trace_id", "")),
                    span_id=str(item.get("span_id", "")),
                    parent_span_id=str(item.get("parent_span_id", "")),
                    duration_ms=item.get("duration_ms"),
                    status=str(item.get("status", "ok")),
                    timestamp=float(item.get("timestamp", time.time())),
                )
            except Exception:
                continue
        return store

    # ---- Hook chuyên biệt cho các lane chính ---------------------------------
    def record_social_intercept(self, result: Any, rollout: Any = None) -> None:
        act = str(getattr(getattr(result, "act", None), "value", "normal_chat") or "normal_chat")
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        applied = bool(getattr(result, "intercepted", False))
        mode = str(getattr(rollout, "mode", "enabled") or "enabled")
        self.increment("social_intent_total", tags={"act": act, "mode": mode})
        self.observe("social_intent_confidence", confidence, tags={"act": act})
        if applied:
            self.increment("social_intercept_applied_total", tags={"act": act, "mode": mode})
        if bool(getattr(result, "state_changed", False)):
            event_type = str(getattr(result, "event_type", "state_changed") or "state_changed")
            self.increment("permission_state_transition_total", tags={"event": event_type})

    def record_outcome(self, outcome: Any) -> None:
        if outcome is None:
            return
        mapping = {
            "user_accepted": "user_accepted_total",
            "user_corrected": "user_corrected_total",
            "user_confused": "user_confused_total",
            "user_felt_intruded": "user_intruded_total",
            "relation_ruptured": "relation_ruptured_total",
            "relation_improved": "relation_improved_total",
        }
        for field_name, metric in mapping.items():
            value = getattr(outcome, field_name, None)
            if value is True:
                self.increment(metric)
        # Metric mới đọc pressure mềm từ Unified Social Appraisal. Bool legacy
        # vẫn được đếm để dashboard cũ không vỡ, nhưng tuning nên dựa vào score.
        for field_name in (
            "correction_pressure",
            "confusion_pressure",
            "laughter_signal",
            "intrusion_pressure",
            "rupture_pressure",
            "acceptance_pressure",
        ):
            self.observe(field_name, float(getattr(outcome, field_name, 0.0) or 0.0))
        self.observe("action_success", float(getattr(outcome, "action_success", 1.0) or 0.0))
        self.observe("body_match_success", float(getattr(outcome, "body_match_success", 1.0) or 0.0))

    def record_director(self, *, candidate_count: int, selected_index: int, latency_ms: float, plan: Mapping[str, Any], final_text: str) -> None:
        lane = str(plan.get("lane", "chat") or "chat")
        self.observe("candidates_per_turn", float(candidate_count), tags={"lane": lane})
        self.observe("director_latency_ms", float(latency_ms), tags={"lane": lane})
        reason = str(plan.get("reason") or plan.get("plan_reason") or "unspecified")
        self.increment("director_turn_total", tags={"lane": lane, "pressure": str(plan.get("pressure_level", "unknown"))})
        self.log("candidate_plan", tags={"lane": lane}, fields={"candidate_lane": lane, "candidate_plan_reason": reason})
        if selected_index > 0:
            self.increment("director_non_draft_selection_total", tags={"lane": lane})
        folded = final_text.lower()
        if any(marker in folded for marker in ("bạn cho phép tôi", "bạn đã cho phép", "tôi sẽ làm phiền một cách hữu ích")):
            self.increment("literal_paraphrase_total", tags={"lane": lane})

    @staticmethod
    def _stable_hash(value: Any) -> str:
        try:
            if hasattr(value, "to_prompt_block") and callable(value.to_prompt_block):
                raw = value.to_prompt_block()
            elif hasattr(value, "to_dict") and callable(value.to_dict):
                raw = value.to_dict()
            elif hasattr(value, "__dict__"):
                raw = vars(value)
            else:
                raw = str(value)
            encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        except Exception:
            encoded = str(value)
        return hashlib.sha256(encoded.encode("utf-8", "ignore")).hexdigest()[:16]

    def record_acceptance_gate(self, *, result: Any, frame: Any, contract: Any) -> None:
        verdict = str(getattr(getattr(result, "verdict", None), "value", getattr(result, "verdict", "unknown")) or "unknown")
        reasons = tuple(str(item) for item in (getattr(result, "reasons", ()) or ()))[:12]
        self.increment("gate_verdict_total", tags={"verdict": verdict})
        for reason in reasons:
            self.increment("gate_reason_total", tags={"reason": reason.split(":", 1)[0], "verdict": verdict})
        self.log(
            "acceptance_gate",
            tags={"verdict": verdict},
            fields={
                "gate_verdict": verdict,
                "gate_reasons": reasons,
                "turn_frame_hash": self._stable_hash(frame),
                "response_contract_hash": self._stable_hash(contract),
            },
            status="ok" if verdict == "pass" else "rejected",
        )

    def record_constrained_rerun(self, *, outcome: str, reasons: Any = (), count: int = 1) -> None:
        self.increment("constrained_rerun_count", value=float(max(0, count)), tags={"outcome": str(outcome or "unknown")})
        self.log("constrained_rerun", tags={"outcome": str(outcome or "unknown")}, fields={"gate_reasons": list(reasons or ())[:12]})

    def record_prompt_budget(self, *, before_tokens: int, after_tokens: int, cap: int, retained_blocks: Any = (), trimmed: bool = False) -> None:
        retained = tuple(str(item) for item in (retained_blocks or ()))[:16]
        self.observe("prompt_tokens_before", float(before_tokens))
        self.observe("prompt_tokens_after", float(after_tokens))
        self.observe("prompt_hard_cap", float(cap))
        if trimmed:
            self.increment("prompt_trim_total")
        self.log("prompt_budget", fields={"prompt_blocks_retained": retained, "before_tokens": before_tokens, "after_tokens": after_tokens, "cap": cap, "trimmed": trimmed})

    def record_provider_pool(self, *, provider: str, snapshot: Mapping[str, Any], event: str = "snapshot") -> None:
        dead = int(snapshot.get("dead", 0) or 0)
        available = int(snapshot.get("available", 0) or 0)
        self.gauge("provider_key_dead_count", float(dead), tags={"provider": provider})
        self.gauge("provider_key_available_count", float(available), tags={"provider": provider})
        self.log("provider_key_pool", tags={"provider": provider, "event": event}, fields={"provider_key_dead_count": dead, "available": available, "rotations": int(snapshot.get("rotations", 0) or 0)})

    def record_maintenance(self, *, phase: str, payload: Mapping[str, Any]) -> None:
        action = str(payload.get("action") or "unknown")
        ok = bool(payload.get("ok", True))
        preview_id = str(payload.get("preview_id") or payload.get("confirmation_token") or "")[:32]
        self.increment("maintenance_operation_total", tags={"phase": phase, "action": action, "ok": str(ok).lower()})
        fields = {
            "maintenance_preview_id": preview_id,
            "danger_zone_execute_result": "ok" if ok else "error",
            "changed_count": len(payload.get("changed", []) or []),
            "error_count": len(payload.get("errors", []) or []),
        }
        self.log("maintenance_" + str(phase), tags={"action": action}, fields=fields, status="ok" if ok else "error")

    def record_vision(self, report: Any, *, channel: str) -> None:
        recommendation = str(getattr(report, "recommendation", "silence") or "silence")
        self.increment("vision_grounding_decision_total", tags={"channel": channel, "recommendation": recommendation})
        self.observe("vision_claim_grounded_rate", 1.0 if getattr(report, "grounded_claims", ()) else 0.0, tags={"channel": channel})
        self.observe("vision_evidence_strength", float(getattr(report, "evidence_strength", 0.0) or 0.0), tags={"channel": channel})
        if recommendation in {"soften", "silence"}:
            self.increment("abstain_total", tags={"channel": channel, "mode": recommendation})
        contradictions = tuple(getattr(report, "contradictions", ()) or ())
        if contradictions:
            self.increment("contradiction_total", value=float(len(contradictions)), tags={"channel": channel})

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._metrics.clear()
            self._gauges.clear()


def ensure_observability(owner: Any) -> ErisObservability:
    current = getattr(owner, "observability", None)
    if isinstance(current, ErisObservability):
        return current
    current = ErisObservability()
    try:
        setattr(owner, "observability", current)
    except Exception:
        pass
    return current


GLOBAL_OBSERVABILITY = ErisObservability()


__all__ = [
    "ErisObservability",
    "GLOBAL_OBSERVABILITY",
    "MetricSeries",
    "TelemetryEvent",
    "ensure_observability",
]
