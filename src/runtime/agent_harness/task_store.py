# -*- coding: utf-8 -*-
"""Durable task/event store for the Agent Console.

The store deliberately owns *task execution metadata*, not Eris' personality or
conversation memory.  LangGraph checkpoints remain the authority for the actual
agent state; this file is a small durable projection used by the UI and control
plane.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

_SCHEMA_VERSION = 2
_MAX_TASKS = 60
_MAX_EVENTS_PER_TASK = 360
_MAX_CONTROLS_PER_TASK = 80


def default_agent_console_state_path() -> Path:
    explicit = str(os.getenv("ERIS_AGENT_CONSOLE_STATE_PATH", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = Path(str(os.getenv("ERIS_STATE_DIR", ".eris_state") or ".eris_state")).expanduser()
    return (root / "agent_console" / "tasks.json").resolve()


class AgentTaskStore:
    """Thread-safe JSON projection of agent tasks, events and control messages."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else default_agent_console_state_path()
        self._lock = threading.RLock()
        self._data = self._load()

    def _empty(self) -> dict[str, Any]:
        return {"version": _SCHEMA_VERSION, "next_event_seq": 1, "tasks": []}

    def _load(self) -> dict[str, Any]:
        try:
            if not self.path.exists():
                return self._empty()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return self._empty()
            tasks = payload.get("tasks")
            if not isinstance(tasks, list):
                tasks = []
            tasks = tasks[-_MAX_TASKS:]

            # MIGRATION V2: event seq là cursor tăng đơn điệu cho WS replay.
            # State V1 cũ không có seq nên ta gán tiếp từ seq lớn nhất đã thấy;
            # không rewrite file ngay lúc boot để tránh I/O không cần thiết.
            max_seq = 0
            missing: list[dict[str, Any]] = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                for event in task.get("events", []) or []:
                    if not isinstance(event, dict):
                        continue
                    try:
                        seq = int(event.get("seq", 0) or 0)
                    except (TypeError, ValueError):
                        seq = 0
                    if seq > 0:
                        max_seq = max(max_seq, seq)
                    else:
                        missing.append(event)
            for event in sorted(missing, key=lambda item: (float(item.get("created_at", 0.0) or 0.0), str(item.get("event_id", "")))):
                max_seq += 1
                event["seq"] = max_seq

            try:
                declared_next = int(payload.get("next_event_seq", 0) or 0)
            except (TypeError, ValueError):
                declared_next = 0
            return {
                "version": _SCHEMA_VERSION,
                "next_event_seq": max(max_seq + 1, declared_next, 1),
                "tasks": tasks,
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._empty()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _compact_text(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _find_locked(self, task_id: str) -> dict[str, Any] | None:
        key = str(task_id or "").strip()
        for task in reversed(self._data["tasks"]):
            if str(task.get("task_id", "")) == key:
                return task
        return None

    def create_task(
        self,
        goal: str,
        *,
        task_id: str = "",
        executor: str = "gemini",
        model: str = "",
        thread_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            task_id = str(task_id or "").strip() or f"task_{uuid.uuid4().hex[:12]}"
            existing = self._find_locked(task_id)
            if existing is not None:
                return dict(existing)
            now = self._now()
            task = {
                "task_id": task_id,
                "thread_id": str(thread_id or task_id),
                "session_id": str(session_id or ""),
                "goal": self._compact_text(goal, 2000),
                "clarified_goal": "",
                "status": "queued",
                "executor": str(executor or "gemini"),
                "model": str(model or ""),
                "created_at": now,
                "updated_at": now,
                "started_at": 0.0,
                "finished_at": 0.0,
                "current_step": 0,
                "active_skills": [],
                "changed_files": [],
                "tests": {"passed": 0, "failed": 0, "summary": ""},
                "checkpoint_id": "",
                "checkpoint_count": 0,
                "last_event_seq": 0,
                "pending_interrupt": {},
                "events": [],
                "controls": [],
                "metadata": dict(metadata or {}),
            }
            self._data["tasks"].append(task)
            self._data["tasks"] = self._data["tasks"][-_MAX_TASKS:]
            self._save_locked()
            return dict(task)

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "goal", "clarified_goal", "status", "executor", "model", "started_at", "finished_at",
            "current_step", "active_skills", "changed_files", "tests", "checkpoint_id",
            "checkpoint_count", "metadata", "thread_id", "session_id", "pending_interrupt", "last_event_seq",
        }
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key in {"goal", "clarified_goal"}:
                    value = self._compact_text(value, 2000)
                task[key] = value
            task["updated_at"] = self._now()
            self._save_locked()
            return dict(task)

    def append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        actor: str = "system",
        summary: str = "",
        detail: str = "",
        step: int | None = None,
        importance: float = 0.5,
        data: dict[str, Any] | None = None,
        event_id: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return None
            try:
                seq = int(self._data.get("next_event_seq", 1) or 1)
            except (TypeError, ValueError):
                seq = 1
            self._data["next_event_seq"] = seq + 1
            event = {
                "event_id": str(event_id or "").strip() or f"ae_{uuid.uuid4().hex[:14]}",
                "seq": seq,
                "type": str(event_type or "agent_status"),
                "actor": str(actor or "system"),
                "summary": self._compact_text(summary, 1600),
                "detail": self._compact_text(detail, 8000),
                "step": int(step if step is not None else task.get("current_step", 0) or 0),
                "importance": max(0.0, min(1.0, float(importance))),
                "created_at": self._now(),
                "data": dict(data or {}),
            }
            events = task.setdefault("events", [])
            events.append(event)
            task["events"] = events[-_MAX_EVENTS_PER_TASK:]
            task["updated_at"] = event["created_at"]
            task["last_event_seq"] = seq
            if step is not None:
                task["current_step"] = max(int(task.get("current_step", 0) or 0), int(step))
            self._project_event_locked(task, event)
            self._save_locked()
            return dict(event)

    def _project_event_locked(self, task: dict[str, Any], event: dict[str, Any]) -> None:
        kind = str(event.get("type", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        now = float(event.get("created_at", self._now()) or self._now())
        if kind == "task_started":
            task["status"] = "running"
            task["started_at"] = task.get("started_at") or now
        elif kind == "task_completed":
            task["status"] = "completed"
            task["finished_at"] = now
        elif kind == "task_failed":
            task["status"] = "failed"
            task["finished_at"] = now
        elif kind == "task_paused":
            task["status"] = "paused"
        elif kind == "task_resumed":
            task["status"] = "running"
        elif kind == "task_stopped":
            task["status"] = "stopped"
            task["finished_at"] = now
        elif kind == "permission_requested":
            task["status"] = "waiting_permission"
            task["pending_interrupt"] = dict(data or {})
        elif kind in {"clarification_requested", "interrupt_requested"}:
            task["status"] = "waiting_user"
            task["pending_interrupt"] = dict(data or {})
        elif kind == "interrupt_resolved":
            task["status"] = "running"
            task["pending_interrupt"] = {}
        elif kind in {"checkpoint_created", "checkpoint_restored"}:
            checkpoint_id = str(data.get("checkpoint_id", "") or "")
            if checkpoint_id:
                task["checkpoint_id"] = checkpoint_id
            if kind == "checkpoint_created":
                task["checkpoint_count"] = int(task.get("checkpoint_count", 0) or 0) + 1
        elif kind == "skill_activated":
            skill = str(data.get("skill", "") or "").strip()
            if skill:
                skills = list(task.get("active_skills") or [])
                if skill not in skills:
                    skills.append(skill)
                task["active_skills"] = skills[-24:]
        elif kind == "file_changed":
            path = str(data.get("path", "") or "").strip()
            if path:
                files = list(task.get("changed_files") or [])
                if path not in files:
                    files.append(path)
                task["changed_files"] = files[-120:]
        elif kind == "test_result":
            task["tests"] = {
                "passed": int(data.get("passed", 0) or 0),
                "failed": int(data.get("failed", 0) or 0),
                "summary": self._compact_text(data.get("summary", event.get("summary", "")), 500),
            }

    def execution_projection(self, task_id: str) -> dict[str, Any]:
        """Small rollbackable UI projection, separate from immutable event history."""
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return {}
            return {
                "current_step": int(task.get("current_step", 0) or 0),
                "active_skills": list(task.get("active_skills") or []),
                "changed_files": list(task.get("changed_files") or []),
                "tests": dict(task.get("tests") or {}),
                "checkpoint_id": str(task.get("checkpoint_id", "") or ""),
                "checkpoint_count": int(task.get("checkpoint_count", 0) or 0),
            }

    def restore_execution_projection(
        self,
        task_id: str,
        projection: dict[str, Any],
        *,
        checkpoint_id: str = "",
    ) -> dict[str, Any] | None:
        """Restore task counters/state while preserving the audit/event timeline."""
        if not isinstance(projection, dict):
            return None
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return None
            task["current_step"] = max(0, int(projection.get("current_step", 0) or 0))
            task["active_skills"] = [str(x) for x in list(projection.get("active_skills") or [])][-24:]
            task["changed_files"] = [str(x) for x in list(projection.get("changed_files") or [])][-120:]
            tests = projection.get("tests") if isinstance(projection.get("tests"), dict) else {}
            task["tests"] = {
                "passed": int(tests.get("passed", 0) or 0),
                "failed": int(tests.get("failed", 0) or 0),
                "summary": self._compact_text(tests.get("summary", ""), 500),
            }
            task["checkpoint_id"] = str(checkpoint_id or projection.get("checkpoint_id", "") or "")
            # Count is historical, so never decrease it during rollback.
            task["checkpoint_count"] = max(
                int(task.get("checkpoint_count", 0) or 0),
                int(projection.get("checkpoint_count", 0) or 0),
            )
            task["status"] = "running"
            task["updated_at"] = self._now()
            self._save_locked()
            return dict(task)

    def enqueue_control(
        self,
        task_id: str,
        action: str,
        *,
        text: str = "",
        checkpoint_id: str = "",
        request_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return None
            control = {
                "control_id": str(request_id or "").strip() or f"ctl_{uuid.uuid4().hex[:12]}",
                "action": str(action or "").strip().lower(),
                "text": self._compact_text(text, 4000),
                "checkpoint_id": str(checkpoint_id or "").strip(),
                "created_at": self._now(),
                "consumed": False,
                "data": dict(data or {}),
            }
            controls = task.setdefault("controls", [])
            controls.append(control)
            task["controls"] = controls[-_MAX_CONTROLS_PER_TASK:]
            task["updated_at"] = control["created_at"]
            self._save_locked()
            return dict(control)

    def consume_controls(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return []
            pending = [dict(x) for x in task.get("controls", []) if isinstance(x, dict) and not x.get("consumed")]
            if not pending:
                return []
            pending_ids = {x.get("control_id") for x in pending}
            for item in task.get("controls", []):
                if isinstance(item, dict) and item.get("control_id") in pending_ids:
                    item["consumed"] = True
                    item["consumed_at"] = self._now()
            self._save_locked()
            return pending


    def events_since(
        self,
        seq: int,
        *,
        task_id: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Trả event theo cursor tăng đơn điệu để WS reconnect chỉ replay delta.

        Đây là projection đọc thuần; lịch sử task vẫn là nguồn audit chính.
        """
        try:
            after = max(0, int(seq))
        except (TypeError, ValueError):
            after = 0
        cap = max(1, min(2000, int(limit or 500)))
        wanted_task = str(task_id or "").strip()
        with self._lock:
            rows: list[dict[str, Any]] = []
            for task in self._data.get("tasks", []):
                if not isinstance(task, dict):
                    continue
                current_task_id = str(task.get("task_id", "") or "")
                if wanted_task and current_task_id != wanted_task:
                    continue
                for event in task.get("events", []) or []:
                    if not isinstance(event, dict):
                        continue
                    try:
                        event_seq = int(event.get("seq", 0) or 0)
                    except (TypeError, ValueError):
                        event_seq = 0
                    if event_seq <= after:
                        continue
                    item = self._public_event(event)
                    item["task_id"] = current_task_id
                    item["thread_id"] = str(task.get("thread_id", "") or "")
                    item["session_id"] = str(task.get("session_id", "") or "")
                    rows.append(item)
            rows.sort(key=lambda item: int(item.get("seq", 0) or 0))
            return rows[:cap]

    def latest_task_for_thread(
        self,
        thread_id: str,
        *,
        session_id: str = "",
        statuses: Iterable[str] | None = None,
        event_limit: int = 0,
    ) -> dict[str, Any] | None:
        """Tìm task mới nhất của một chat thread để tránh chạy hai graph chồng nhau."""
        wanted_thread = str(thread_id or "").strip()
        wanted_session = str(session_id or "").strip()
        allowed = {str(item or "").strip().lower() for item in (statuses or []) if str(item or "").strip()}
        if not wanted_thread:
            return None
        with self._lock:
            for task in reversed(self._data.get("tasks", [])):
                if not isinstance(task, dict) or str(task.get("thread_id", "") or "") != wanted_thread:
                    continue
                if wanted_session and str(task.get("session_id", "") or "") not in {"", wanted_session}:
                    continue
                if allowed and str(task.get("status", "") or "").strip().lower() not in allowed:
                    continue
                return self._public_task(task, event_limit=event_limit)
        return None

    def list_tasks(
        self,
        *,
        session_id: str = "",
        limit: int = 24,
        event_limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Danh sách task gọn cho IDE restore state sau reconnect/restart."""
        wanted_session = str(session_id or "").strip()
        cap = max(1, min(100, int(limit or 24)))
        with self._lock:
            rows: list[dict[str, Any]] = []
            for task in reversed(self._data.get("tasks", [])):
                if not isinstance(task, dict):
                    continue
                task_session = str(task.get("session_id", "") or "")
                if wanted_session and task_session not in {"", wanted_session}:
                    continue
                rows.append(self._public_task(task, event_limit=event_limit))
                if len(rows) >= cap:
                    break
            return rows

    def get_task(self, task_id: str, *, event_limit: int = 100) -> dict[str, Any] | None:
        with self._lock:
            task = self._find_locked(task_id)
            if task is None:
                return None
            return self._public_task(task, event_limit=event_limit)

    def snapshot(self, *, selected_task_id: str = "", task_limit: int = 18, event_limit: int = 120) -> dict[str, Any]:
        with self._lock:
            tasks = list(reversed(self._data.get("tasks", [])))[: max(1, task_limit)]
            if not selected_task_id and tasks:
                selected_task_id = str(tasks[0].get("task_id", ""))
            result = []
            for task in tasks:
                limit = event_limit if str(task.get("task_id", "")) == selected_task_id else 6
                result.append(self._public_task(task, event_limit=limit))
            return {
                "version": "agent_console.v1",
                "selected_task_id": selected_task_id,
                "tasks": result,
                "generated_at": self._now(),
            }

    @staticmethod
    def _public_task(task: dict[str, Any], *, event_limit: int) -> dict[str, Any]:
        public = {k: v for k, v in task.items() if k not in {"controls", "events"}}
        events = list(task.get("events") or [])
        selected = events[-max(0, event_limit):] if event_limit else []
        public["events"] = [AgentTaskStore._public_event(item) for item in selected if isinstance(item, dict)]
        public["pending_controls"] = sum(
            1 for item in task.get("controls", []) if isinstance(item, dict) and not item.get("consumed")
        )
        return public

    @staticmethod
    def _public_event(event: dict[str, Any]) -> dict[str, Any]:
        result = dict(event)
        detail = str(result.get("detail", "") or "")
        if len(detail) > 1600:
            result["detail"] = detail[:1599].rstrip() + "…"
        data = result.get("data")
        if isinstance(data, dict):
            # Choice cards are UI protocol, not debug payload. Preserve their
            # structure even when the original LLM text is verbose; clamp each
            # field instead of collapsing the whole object into {truncated:true}.
            if str(result.get("type", "") or "") in {"clarification_requested", "interrupt_requested"}:
                raw_options = data.get("options") if isinstance(data.get("options"), list) else []
                options = []
                for index, item in enumerate(raw_options[:5]):
                    if not isinstance(item, dict):
                        continue
                    label = AgentTaskStore._compact_text(item.get("label", ""), 120)
                    if not label:
                        continue
                    options.append({
                        "id": AgentTaskStore._compact_text(item.get("id", "") or f"option_{index + 1}", 64),
                        "label": label,
                        "description": AgentTaskStore._compact_text(item.get("description", ""), 160),
                        "value": AgentTaskStore._compact_text(item.get("value", "") or label, 220),
                    })
                result["data"] = {
                    "question": AgentTaskStore._compact_text(data.get("question", result.get("summary", "")), 500),
                    "options": options,
                    "allow_other": bool(data.get("allow_other", True)),
                }
                return result

            try:
                encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                encoded = ""
            if len(encoded) > 3500:
                # Inspector cần metadata nhỏ (path/checkpoint/test), không cần raw tool output.
                result["data"] = {
                    "truncated": True,
                    "keys": [str(key)[:80] for key in list(data.keys())[:24]],
                }
        return result


__all__ = ["AgentTaskStore", "default_agent_console_state_path"]
