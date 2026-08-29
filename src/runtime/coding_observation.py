# -*- coding: utf-8 -*-
"""V79: journal + interpreter read-only cho luồng coding GitPilot.

Module này cố ý KHÔNG import AgentHarness/GitPilot và không có API điều khiển task.
Nó chỉ nhận telemetry đã sanitize từ Eris Code, ghi journal nhỏ và suy ra các
anti-pattern có bằng chứng rõ để V80 Mentor dùng làm nguyên liệu giảng dạy.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from runtime.workspace_manager import default_eris_home

_SCHEMA = "eris.coding.observation.v1"
_ALLOWED_ACTORS = {"explorer", "planner", "coder", "reviewer", "validation", "gitpilot", "unknown"}
_ALLOWED_EVENTS = {
    "task_started", "phase_changed", "plan_step", "phase_summary", "tool_started", "tool_finished",
    "file_changed", "approval_requested", "approval_resolved", "test_result",
    "diagnostics", "task_completed", "task_failed", "task_cancelled",
}


def _text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").replace("\x00", "").split())
    # Sink cũng tự redact, không tin extension/local caller đã sanitize hoàn hảo.
    clean = re.sub(r"(?i)(api[_-]?key|token|authorization|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=<redacted>", clean)
    clean = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", clean)
    return clean[:limit]


def _path(value: Any) -> str:
    return _text(value, 520).replace("\\", "/")


def sanitize_coding_observation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Allow-list schema; tuyệt đối không serialize raw prompt/source-code payload."""
    if str(payload.get("schema", "")) != _SCHEMA:
        raise ValueError("unsupported_schema")
    event_type = _text(payload.get("event_type"), 64).lower()
    if event_type not in _ALLOWED_EVENTS:
        raise ValueError("unsupported_event_type")
    actor = _text(payload.get("actor"), 32).lower()
    if actor not in _ALLOWED_ACTORS:
        actor = "unknown"
    task_id = _text(payload.get("task_id"), 160)
    if not task_id:
        raise ValueError("task_id_required")

    clean: dict[str, Any] = {
        "schema": _SCHEMA,
        "source": "eris-code/gitpilot",
        "task_id": task_id,
        "session_id": _text(payload.get("session_id"), 160),
        "thread_id": _text(payload.get("thread_id"), 160),
        "workspace": _path(payload.get("workspace")),
        "actor": actor,
        "event_type": event_type,
        "at": float(payload.get("at") or time.time()),
    }
    field_limits = (("tool", 120), ("command", 320), ("status", 80), ("evidence", 2600 if event_type == "phase_summary" else 800))
    for key, limit in field_limits:
        value = _text(payload.get(key), limit)
        if value:
            clean[key] = value
    files = payload.get("files")
    if isinstance(files, (list, tuple)):
        clean_files: list[str] = []
        for item in files[:12]:
            value = _path(item)
            if value and value not in clean_files:
                clean_files.append(value)
        if clean_files:
            clean["files"] = clean_files
    metrics = payload.get("metrics")
    if isinstance(metrics, Mapping):
        clean_metrics: dict[str, Any] = {}
        for key, value in list(metrics.items())[:16]:
            if isinstance(value, (bool, int, float, str)):
                clean_metrics[_text(key, 48)] = value if not isinstance(value, str) else _text(value, 120)
        if clean_metrics:
            clean["metrics"] = clean_metrics
    return clean


@dataclass
class _TaskFlow:
    task_id: str
    workspace: str = ""
    actor: str = "unknown"
    inspected_any: bool = False
    changed_files: set[str] = field(default_factory=set)
    tools_started: int = 0
    tests_seen: int = 0
    failed_test_runs: int = 0
    diagnostics_seen: int = 0
    reviewer_seen: bool = False
    phase_summaries: dict[str, str] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0
    status: str = "running"

    def finding(self, code: str, message: str, severity: str = "warning", *, evidence: str = "") -> None:
        if any(item.get("code") == code for item in self.findings):
            return
        item = {"code": code, "severity": severity, "message": message}
        if evidence:
            item["evidence"] = evidence[:420]
        self.findings.append(item)


class CodingFlowInterpreter:
    """Suy ra flow từ event observable; không đoán chain-of-thought của model."""

    _READ_TOOL_MARKERS = ("read", "search", "list", "grep", "git diff", "git status", "git log")

    def __init__(self) -> None:
        self._tasks: dict[str, _TaskFlow] = {}
        self._lock = threading.RLock()

    def observe(self, event: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            task_id = str(event["task_id"])
            state = self._tasks.setdefault(task_id, _TaskFlow(task_id=task_id))
            state.workspace = str(event.get("workspace") or state.workspace)
            state.actor = str(event.get("actor") or state.actor)
            kind = str(event.get("event_type") or "")
            at = float(event.get("at") or time.time())
            if kind == "task_started":
                state.started_at = state.started_at or at
                state.status = "running"
            elif kind == "phase_changed" and state.actor == "reviewer":
                state.reviewer_seen = True
            elif kind == "phase_summary":
                state.phase_summaries[state.actor] = str(event.get("evidence") or "")[:2600]
                if state.actor == "reviewer":
                    state.reviewer_seen = True
            elif kind == "tool_started":
                state.tools_started += 1
                tool = str(event.get("tool") or "").lower()
                if any(marker in tool for marker in self._READ_TOOL_MARKERS):
                    state.inspected_any = True
            elif kind == "tool_finished" and str(event.get("status")) == "error":
                signature_raw = f"{event.get('actor')}|{event.get('tool')}|{event.get('evidence')}"
                signature = hashlib.sha1(signature_raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
                state.failures[signature] = state.failures.get(signature, 0) + 1
                if state.failures[signature] >= 3:
                    state.finding(
                        "repeated_same_failure",
                        "Cùng một tool/error đã lặp lại ít nhất 3 lần mà chưa đổi chiến lược.",
                        evidence=str(event.get("evidence") or ""),
                    )
            elif kind == "file_changed":
                for path in event.get("files", ()) or ():
                    state.changed_files.add(str(path))
                if not state.inspected_any:
                    state.finding(
                        "patch_before_inspection",
                        "Có thay đổi file trước khi journal thấy bước đọc/search repository.",
                    )
                if len(state.changed_files) >= 8:
                    state.finding(
                        "scope_expansion",
                        "Task đã chạm từ 8 file trở lên; nên kiểm tra lại scope và nguyên nhân lan rộng.",
                    )
            elif kind == "test_result":
                state.tests_seen += 1
                failed = int((event.get("metrics") or {}).get("failed", 0) or 0)
                if failed > 0:
                    state.failed_test_runs += 1
                if state.failed_test_runs >= 3:
                    state.finding(
                        "repeated_test_failure",
                        "Test vẫn fail sau nhiều vòng validation; cần quay lại giả thuyết/root cause thay vì retry mù.",
                    )
            elif kind == "diagnostics":
                state.diagnostics_seen += 1
            elif kind in {"task_completed", "task_failed", "task_cancelled"}:
                state.ended_at = at
                state.status = "completed" if kind == "task_completed" else "failed" if kind == "task_failed" else "cancelled"
                if kind == "task_completed" and state.changed_files and not (state.tests_seen or state.diagnostics_seen):
                    state.finding(
                        "no_structured_verification",
                        "Task có sửa file nhưng journal chưa thấy test_result/diagnostics có cấu trúc.",
                        severity="info",
                    )
                if kind == "task_completed" and state.changed_files and not state.reviewer_seen:
                    state.finding(
                        "review_not_observed",
                        "Task đã sửa code nhưng chưa quan sát thấy phase Reviewer.",
                        severity="info",
                    )
            return self.snapshot(task_id)

    def snapshot(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._tasks.get(str(task_id))
            if state is None:
                return {}
            return {
                "schema": "eris.coding.flow.v1",
                "task_id": state.task_id,
                "workspace": state.workspace,
                "actor": state.actor,
                "status": state.status,
                "started_at": state.started_at,
                "ended_at": state.ended_at,
                "tools_started": state.tools_started,
                "changed_files": sorted(state.changed_files),
                "tests_seen": state.tests_seen,
                "failed_test_runs": state.failed_test_runs,
                "diagnostics_seen": state.diagnostics_seen,
                "reviewer_seen": state.reviewer_seen,
                "phase_summaries": dict(state.phase_summaries),
                "findings": list(state.findings),
            }

    def recent_snapshots(self, *, workspace: str = "", limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            states = list(self._tasks.values())
            if workspace:
                normalized = _path(workspace).lower()
                states = [item for item in states if _path(item.workspace).lower() == normalized]
            states.sort(key=lambda item: item.ended_at or item.started_at, reverse=True)
            return [self.snapshot(item.task_id) for item in states[: max(1, min(int(limit), 20))]]


class CodingObservationService:
    """Append-only coding journal cho Desktop; bounded in-memory cache + JSONL."""

    def __init__(self, *, path: Path | None = None, logger: Any = None, memory_limit: int = 1200) -> None:
        self.path = path or (default_eris_home() / "logs" / "coding_observations.jsonl")
        self.logger = logger
        self.memory_limit = max(100, int(memory_limit))
        self.interpreter = CodingFlowInterpreter()
        self._recent: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._load_tail()

    def ingest(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        event = sanitize_coding_observation(payload)
        with self._lock:
            self._recent.append(event)
            if len(self._recent) > self.memory_limit:
                del self._recent[: len(self._recent) - self.memory_limit]
            self._append(event)
            flow = self.interpreter.observe(event)
        return {"accepted": True, "event_type": event["event_type"], "task_id": event["task_id"], "flow": flow}

    def recent(self, *, task_id: str = "", workspace: str = "", limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        if task_id:
            items = [item for item in items if item.get("task_id") == task_id]
        if workspace:
            normalized = _path(workspace).lower()
            items = [item for item in items if _path(item.get("workspace")).lower() == normalized]
        return items[-max(1, min(int(limit), 500)):]

    def flow(self, task_id: str) -> dict[str, Any]:
        return self.interpreter.snapshot(task_id)

    def recent_flows(self, *, workspace: str = "", limit: int = 8) -> list[dict[str, Any]]:
        return self.interpreter.recent_snapshots(workspace=workspace, limit=limit)

    def _load_tail(self) -> None:
        """Replay tail để Desktop restart vẫn hiểu task gần đây mà không cần raw chat."""
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                lines = list(deque(handle, maxlen=self.memory_limit))
        except Exception:
            return
        for line in lines:
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                event = sanitize_coding_observation(raw)
            except Exception:
                continue
            self._recent.append(event)
            self.interpreter.observe(event)

    def _append(self, event: Mapping[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True, default=str) + "\n")
        except Exception as exc:
            if self.logger is not None:
                try:
                    self.logger.debug("[coding-observation] journal write failed: %s", exc)
                except Exception:
                    pass


__all__ = [
    "CodingFlowInterpreter",
    "CodingObservationService",
    "sanitize_coding_observation",
]
