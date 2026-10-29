# -*- coding: utf-8 -*-
"""Gắn Goal do Eris đã chấp nhận với Work Session hiện có.

Đây là cầu nối dữ liệu, KHÔNG phải một bộ điều phối Identity mới:
- Chỉ GoalEventLedger trạng thái active mới có quyền giao việc.
- Work job không tự công bố goal đạt chỉ vì trả 'complete'.
- Mỗi goal chỉ có một Work job được claim; sau crash không tự replay.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from runtime.autonomy.goal_events import GoalEventLedger, GoalConflict


class GoalSessionBridge:
    def __init__(self, *, work_db_path: str | Path, goal_ledger: GoalEventLedger,
                 start_work: Callable[[str], dict], snapshot_work: Callable[[str], dict | None]):
        self.work_db_path = Path(work_db_path)
        self.goals = goal_ledger
        self._start_work = start_work
        self._snapshot_work = snapshot_work
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS work_goal_links (
                goal_id TEXT PRIMARY KEY, job_id TEXT UNIQUE, state TEXT NOT NULL,
                outcome_ref TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def _db(self):
        return sqlite3.connect(str(self.work_db_path), timeout=8)

    def list(self) -> dict[str, Any]:
        with self._db() as db:
            links = dict(db.execute('SELECT goal_id,job_id FROM work_goal_links').fetchall())
        return {"goals": [{"goal_id": g.goal_id, "title": g.title, "status": g.status,
                            "revision": g.revision, "job_id": links.get(g.goal_id) or ""}
                           for g in self.goals.list_goals()]}

    def state(self, goal_id: str) -> dict[str, Any]:
        goal = self.goals.get(str(goal_id))
        if not goal:
            return {"error": "goal_not_found"}
        with self._db() as db:
            linked = db.execute('SELECT job_id,state,outcome_ref FROM work_goal_links WHERE goal_id=?',
                                (goal.goal_id,)).fetchone()
        job_id = linked[0] if linked else ""
        return {"goal_id": goal.goal_id, "status": goal.status, "revision": goal.revision,
                "title": goal.title, "criteria": goal.success_criteria,
                "job_id": job_id or "", "link_state": linked[1] if linked else "unlinked",
                "outcome_ref": linked[2] if linked else "",
                "work": self._snapshot_work(job_id) if job_id else None}

    def start_goal(self, goal_id: str) -> dict[str, Any]:
        goal = self.goals.get(goal_id)
        if not goal:
            return {"error": "goal_not_found"}
        if goal.status != "active" or not goal.adoption_commit_id:
            return {"error": "goal_not_adopted", "status": goal.status}
        # V3 vẫn có vòng thực thi sandbox riêng. Không tạo công việc thứ hai
        # khi receipt hành động cũ chưa được đối chiếu xong.
        with self.goals._db() as goal_db:
            unknown = goal_db.execute("""SELECT action_id FROM autonomy_actions
                WHERE goal_id=? AND status IN ('in_flight','unknown') LIMIT 1""", (goal_id,)).fetchone()
        if unknown:
            return {"error": "goal_has_unreconciled_action", "action_id": unknown[0]}
        # SQLite unique goal_id + BEGIN IMMEDIATE: hai request không thể tạo 2 job.
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT job_id,state FROM work_goal_links WHERE goal_id=?', (goal_id,)).fetchone()
            if existing:
                db.rollback()
                return {"goal_id": goal_id, "job_id": existing[0] or "",
                        "status": existing[1], "already_claimed": True}
            db.execute("INSERT INTO work_goal_links(goal_id,job_id,state) VALUES(?,NULL,'claiming')", (goal_id,))
            db.commit()
        candidate = goal.payload.get("candidate", {})
        motives = ", ".join(str(v)[:60] for v in candidate.get("motive_ids", ())[:6])
        task = (f"Mục tiêu Eris đã commit [{goal.goal_id[:180]}]: {goal.title[:1600]}\n"
                f"Tiêu chí thành công: {goal.success_criteria[:2400]}\n"
                f"Nguồn động cơ: {motives}. Không được tự tuyên bố goal đạt "
                "khi chưa có evidence. Work Session chỉ thi hành và báo kết quả.")
        # Nếu Executive vừa dừng goal trong lúc claim, không tạo job mới.
        latest = self.goals.get(goal_id)
        if latest is None or latest.status != "active" or latest.epoch != goal.epoch:
            with self._db() as db:
                db.execute("UPDATE work_goal_links SET state='goal_changed' WHERE goal_id=?", (goal_id,))
            return {"error": "goal_changed_before_start"}
        try:
            job = self._start_work(task)
        except Exception:
            with self._db() as db:
                db.execute("UPDATE work_goal_links SET state='needs_review' WHERE goal_id=?", (goal_id,))
            raise
        with self._db() as db:
            db.execute("UPDATE work_goal_links SET job_id=?,state='linked' WHERE goal_id=?",
                       (job["job_id"], goal_id))
        # Worker có thể hoàn thành trước lúc ghi link, nên reconcile ngay.
        self.reconcile(job["job_id"])
        return {"goal_id": goal_id, "job_id": job["job_id"], "status": job["status"]}

    def reconcile(self, job_id: str) -> None:
        """Receipt job → outcome của goal; không tự đổi trạng thái achieved."""
        snap = self._snapshot_work(job_id)
        if not snap or snap.get("status") not in {"completed", "failed", "needs_review", "cancelled"}:
            return
        with self._db() as db:
            link = db.execute('SELECT goal_id,outcome_ref FROM work_goal_links WHERE job_id=?', (job_id,)).fetchone()
        if not link or link[1]:
            return
        goal_id = link[0]
        current = self.goals.get(goal_id)
        if not current or current.status != "active":
            with self._db() as db:
                db.execute("UPDATE work_goal_links SET state='goal_changed' WHERE job_id=?", (job_id,))
            return
        ref = f"work-session:{job_id}:rev-{snap['revision']}"
        try:
            self.goals.attach_outcome(goal_id, expected_revision=current.revision,
                                      event_id=f"work-outcome:{job_id}",
                                      outcome_ref=ref, outcome_status=str(snap["status"]),
                                      action_id=job_id)
        except GoalConflict:
            # Retry hữu hạn sau thay đổi revision hợp lệ, không override goal bị suspend.
            current = self.goals.get(goal_id)
            if current is None or current.status != "active":
                return
            try:
                self.goals.attach_outcome(goal_id, expected_revision=current.revision,
                                          event_id=f"work-outcome:{job_id}",
                                          outcome_ref=ref, outcome_status=str(snap["status"]),
                                          action_id=job_id)
            except GoalConflict:
                return
        with self._db() as db:
            db.execute("UPDATE work_goal_links SET state='outcome_recorded',outcome_ref=? WHERE job_id=?",
                       (ref, job_id))

    def goal_fresh(self, job_id: str) -> bool:
        """Lệnh worker chỉ tiếp tục khi goal nguồn vẫn active.

        Không dùng để suy đoán ý định Eris; chỉ kiểm tra hiệu lực của
        công việc đã được giao. Tool đang chạy cần tự xử lý hủy riêng.
        """
        with self._db() as db:
            row = db.execute('SELECT goal_id FROM work_goal_links WHERE job_id=?', (job_id,)).fetchone()
        if not row:
            return True  # Job do user/Root giao trực tiếp, không gắn goal.
        goal = self.goals.get(row[0])
        return bool(goal and goal.status == 'active')

    def reconcile_all(self) -> None:
        """Khôi phục link/outcome đã commit sau restart, không chạy lại action."""
        with self._db() as db:
            jobs = [row[0] for row in db.execute(
                "SELECT job_id FROM work_goal_links WHERE job_id IS NOT NULL AND outcome_ref='' ").fetchall()]
        for job_id in jobs:
            self.reconcile(job_id)

    def on_work_event(self, event: dict) -> None:
        if event.get("kind") in {"complete", "state"}:
            self.reconcile(str(event.get("job_id", "")))


__all__ = ["GoalSessionBridge"]
