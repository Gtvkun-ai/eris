# -*- coding: utf-8 -*-
"""Luồng công việc dài của Eris, độc lập với đường thoại và TTS.

Root/Identity duy nhất được giao hoặc dừng công việc. Worker chỉ thực hiện
nhiệm vụ đã giao; mỗi lượt suy luận trả MỘT thao tác hoặc một kết quả, không
được tự tạo lượt nói công khai. Tiến độ được lưu SQLite và có thể truy vấn.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Mapping

# LLM nằm trong worker riêng; chat_main không đợi model hoặc tool của job.
_WORK_STEP_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "text", "action_id", "arguments"],
    "properties": {
        "kind": {"type": "string", "enum": ["progress", "tool", "complete", "wait_user"]},
        "text": {"type": "string"},
        "action_id": {"type": "string"},
        "arguments": {"type": "object", "additionalProperties": True},
    },
}
# Tool được phép chạy nền, dựa trên cơ chế sandbox/capability hiện hữu.
_WORK_TOOLS = frozenset({"math_workspace", "python_workspace", "project_read_file", "project_search_text", "project_run_tests"})
_TERMINAL = frozenset({"completed", "cancelled", "failed", "needs_review"})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


@dataclass
class WorkJob:
    job_id: str
    task: str
    status: str = "queued"
    revision: int = 0
    summary: str = ""
    last_evidence: str = ""
    cancel_requested: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "task": self.task, "status": self.status,
                "revision": self.revision, "summary": self.summary,
                "last_evidence": self.last_evidence}


class ParallelWorkService:
    """Một work-lane có bộ nhớ, không phải một coordinator nói chuyện thứ hai."""

    def __init__(self, db_path: str | Path, *, planner: Callable[[dict], Mapping[str, Any]] | None,
                 tool: Callable[[str, Mapping[str, Any]], Any] | None = None,
                 publish: Callable[[dict], Any] | None = None,
                 max_steps: int = 12, max_workers: int = 2):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.planner = planner
        self.tool = tool
        self.publish = publish or (lambda _: None)
        self.max_steps = max(1, min(30, int(max_steps)))
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ERIS-WorkLane")
        self._running: dict[str, WorkJob] = {}
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, task TEXT NOT NULL, status TEXT NOT NULL,
                    revision INTEGER NOT NULL, summary TEXT NOT NULL,
                    evidence TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    job_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL, at REAL NOT NULL,
                    PRIMARY KEY(job_id, revision)
                );
            """)
            # Không tự chạy lại side effect sau crash: chưa biết tool cũ đã thực thi chưa.
            con.execute("UPDATE jobs SET status='needs_review' WHERE status IN ('queued','running')")

    def _connect(self):
        con = sqlite3.connect(str(self.db_path), timeout=8)
        con.execute("PRAGMA busy_timeout=8000")
        return con

    def _store(self, job: WorkJob, kind: str, detail: str = "") -> None:
        with self._lock, self._connect() as con:
            job.revision += 1
            con.execute("INSERT INTO jobs(job_id,task,status,revision,summary,evidence,updated_at) "
                        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET "
                        "status=excluded.status,revision=excluded.revision,summary=excluded.summary,"
                        "evidence=excluded.evidence,updated_at=excluded.updated_at",
                        (job.job_id, job.task, job.status, job.revision, job.summary,
                         job.last_evidence, time.time()))
            con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                        (job.job_id, job.revision, kind, detail[:5000], time.time()))

    def _publish(self, job: WorkJob, kind: str, text: str) -> None:
        # Gói gửi UI không cấp quyền phát ngôn; lỗi UDP không làm hỏng công việc.
        evt = {"job_id": job.job_id, "revision": job.revision, "status": job.status,
               "kind": kind, "text": text[:3500]}
        try:
            self.publish(evt)
        except Exception:
            pass

    def start(self, task: str) -> dict:
        task = str(task or "").strip()
        if not task or len(task) > 6000:
            raise ValueError("Nhiệm vụ rỗng hoặc quá dài")
        job = WorkJob(job_id="work-" + uuid.uuid4().hex, task=task)
        self._store(job, "created", "Root giao nhiệm vụ")
        with self._lock:
            self._running[job.job_id] = job
        self._pool.submit(self._run, job)
        return job.snapshot()

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT job_id,task,status,revision,summary,evidence "
                              "FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
        return dict(zip(("job_id", "task", "status", "revision", "summary", "last_evidence"), row)) if row else None

    def recent(self, limit: int = 4) -> list[dict]:
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT job_id,task,status,revision,summary,evidence FROM jobs "
                               "ORDER BY updated_at DESC LIMIT ?", (max(1, min(10, limit)),)).fetchall()
        return [dict(zip(("job_id", "task", "status", "revision", "summary", "last_evidence"), row)) for row in rows]

    def events(self, job_id: str, limit: int = 15) -> list[dict]:
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT revision,kind,detail FROM events WHERE job_id=? "
                               "ORDER BY revision DESC LIMIT ?", (job_id, min(max(limit, 1), 30))).fetchall()
        return [{"revision": v, "kind": k, "detail": d} for v, k, d in reversed(rows)]

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._running.get(job_id)
            if job is None:
                snap = self.snapshot(job_id)
                return snap or {"error": "job_not_found"}
            job.cancel_requested = True
            # Không giả là tiến trình tool đã dừng khi nó đang I/O.
            self._store(job, "cancel_requested", "Chờ điểm ngắt hợp tác")
            return job.snapshot()

    def resume(self, job_id: str, answer: str) -> dict:
        """Root quyết định tiếp tục sau khi có câu trả lời user thật.

        Job chưa rõ side effect lúc crash không được resume mù; cần xem lại.
        """
        answer = str(answer or "").strip()
        if not answer or len(answer) > 4000:
            raise ValueError("Thiếu câu trả lời để tiếp tục công việc")
        with self._lock:
            snap = self.snapshot(job_id)
            if not snap or snap["status"] != "waiting_user" or job_id in self._running:
                return {"error": "job_not_waiting_user"}
            job = WorkJob(job_id=snap["job_id"], task=snap["task"],
                          status="queued", revision=snap["revision"],
                          summary=snap["summary"], last_evidence=snap["last_evidence"])
            self._store(job, "user_answer", answer)
            self._running[job.job_id] = job
            self._pool.submit(self._run, job)
            return job.snapshot()

    def _run(self, job: WorkJob) -> None:
        try:
            if self.planner is None:
                job.status = "needs_review"
                job.summary = "Chưa nối model giải quyết công việc."
                self._store(job, "planner_unavailable")
                return
            job.status = "running"
            self._store(job, "started")
            for _ in range(self.max_steps):
                if job.cancel_requested:
                    job.status = "cancelled"
                    self._store(job, "cancelled")
                    return
                context = {"task": job.task, "job_id": job.job_id,
                           "recent_events": self.events(job.job_id, 10),
                           "allowed_tools": sorted(_WORK_TOOLS)}
                step = self.planner(context)
                if not isinstance(step, Mapping):
                    raise ValueError("Model không trả work step hợp lệ")
                kind = str(step.get("kind", ""))
                narrative = str(step.get("text", "") or "").strip()[:3500]
                if kind == "progress":
                    if not narrative:
                        raise ValueError("Tiến độ không có nội dung")
                    job.summary = narrative
                    self._store(job, "progress", narrative)
                    self._publish(job, "progress", narrative)
                elif kind == "tool":
                    action = str(step.get("action_id", ""))
                    args = step.get("arguments", {})
                    if action not in _WORK_TOOLS or not isinstance(args, Mapping) or self.tool is None:
                        raise ValueError("Work tool chưa được cấp quyền hoặc chưa nối")
                    # Ghi intent TRƯỚC side effect. Crash giữa chừng không replay tự động.
                    self._store(job, "tool_dispatched", _json({"action": action, "args": args})[:5000])
                    if job.cancel_requested:
                        job.status = "cancelled"
                        self._store(job, "cancelled")
                        return
                    result = self.tool(action, args)
                    if job.cancel_requested:
                        job.status = "cancelled"
                        self._store(job, "late_tool_result_discarded")
                        return
                    success = bool(getattr(result, "success", False))
                    evidence = list(getattr(result, "evidence", ()) or ())
                    message = str(getattr(result, "message", "") or "")
                    data = getattr(result, "data", {}) or {}
                    detail = _json({"action": action, "ok": success, "message": message,
                                    "evidence": evidence, "data": data})[:5000]
                    job.last_evidence = detail
                    job.summary = narrative or ("Đã nhận kết quả công cụ." if success else "Công cụ báo lỗi.")
                    self._store(job, "tool_result", detail)
                    self._publish(job, "tool_result", job.summary)
                elif kind in {"complete", "wait_user"}:
                    job.status = "completed" if kind == "complete" else "waiting_user"
                    job.summary = narrative
                    self._store(job, kind, narrative)
                    self._publish(job, kind, narrative)
                    return
                else:
                    raise ValueError("Loại bước công việc không hợp lệ")
            job.status = "needs_review"
            job.summary = "Đã tới giới hạn bước; cần Eris quyết định tiếp."
            self._store(job, "step_limit")
        except Exception as exc:
            job.status = "failed"
            job.summary = "Work Lane thất bại: " + type(exc).__name__
            self._store(job, "error", type(exc).__name__)
        finally:
            self._publish(job, "state", job.summary)
            with self._lock:
                self._running.pop(job.job_id, None)


def plan_with_router(router: Any, context: Mapping[str, Any]) -> Mapping[str, Any]:
    """Gọi broker/model đã có, không sinh model mới hay đưa work vào chat_main."""
    call = getattr(router, "invoke_structured_worker", None)
    client = (getattr(router, "deep_client", None) or getattr(router, "surface_client", None))
    if not callable(call) or client is None:
        raise RuntimeError("work_model_unavailable")
    response = call(
        client,
        system=("Bạn là nhánh THỰC HIỆN CÔNG VIỆC được Eris Root giao, không phải chủ thể nói chuyện. "
                "Mỗi bước trả đúng JSON kind=progress/tool/complete/wait_user, text, action_id, arguments. "
                "Hãy chia công việc thành nhiều bước, gọi tool thật khi có ích, dựa trên EVIDENCE "
                "đã trả về để quyết định bước tiếp. KHÔNG tự nhận tool đã chạy khi chưa có receipt. "
                "Không tạo lời Bubble, không tự tạo mục tiêu ngoài task. "
                "Nếu chưa có căn cứ hoàn tất, dùng wait_user hoặc progress; không bịa kết quả. "
                "Mỗi bước ngắn, tool chỉ trong allowed_tools."),
        payload=dict(context), schema=_WORK_STEP_SCHEMA,
        name="eris_parallel_work_step", max_tokens=1000,
        inference_tier="subconscious_4b", priority=65, timeout_seconds=45.0,
        cognitive_lane="work_background", temperature=0.2,
    )
    if not isinstance(response, Mapping):
        raise ValueError("work_model_invalid_response")
    return response
