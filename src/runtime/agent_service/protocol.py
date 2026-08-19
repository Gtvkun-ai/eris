# -*- coding: utf-8 -*-
"""Protocol V2 projector cho Eris IDE bridge.

Internal event names được giữ ổn định cho audit/supervisor. Module này chỉ chiếu
chúng thành event semantic mà VS Code UI hiểu: message/activity/interrupt/artifact.
"""
from __future__ import annotations

from typing import Any


def project_agent_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(event.get("type", "") or "")
    task_id = str(event.get("task_id", "") or "")
    thread_id = str(event.get("thread_id", "") or "")
    session_id = str(event.get("session_id", "") or "")
    seq = int(event.get("seq", 0) or 0)
    event_id = str(event.get("event_id", "") or "")
    created_at = float(event.get("created_at", 0.0) or 0.0)
    summary = str(event.get("summary", "") or "")
    detail = str(event.get("detail", "") or "")
    data = dict(event.get("data") or {}) if isinstance(event.get("data"), dict) else {}

    def base(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "type": event_type,
            "protocol": "eris.ide.v2",
            "eventId": event_id,
            "seq": seq,
            "taskId": task_id,
            "threadId": thread_id,
            "sessionId": session_id,
            "timestamp": created_at,
            "payload": dict(payload or {}),
        }

    if kind == "user_message":
        attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
        return [base("message.user", {
            "content": str(data.get("content", "") or summary),
            "source": str(data.get("source", "") or ""),
            # Chỉ project metadata an toàn cho UI/history; absolute path không cần
            # lộ ra Webview sau khi Extension Host đã resolve attachment.
            "attachments": [dict(item) for item in attachments[:8] if isinstance(item, dict)],
        })]
    if kind == "task_started":
        return [base("activity.start", {"label": summary or "Đang bắt đầu task", "status": "running"})]
    if kind == "task_completed":
        final = str(data.get("final", "") or detail or summary)
        rows = [base("activity.end", {"label": "Hoàn tất", "status": "completed", "detail": summary})]
        if final.strip():
            rows.append(base("message.assistant", {"content": final, "final": True}))
        return rows
    if kind == "task_failed":
        return [base("activity.end", {"label": "Task lỗi", "status": "failed", "detail": summary})]
    if kind == "task_stopped":
        return [base("activity.end", {"label": "Đã dừng", "status": "stopped", "detail": summary})]
    if kind in {"interrupt_requested", "clarification_requested", "permission_requested"}:
        options = data.get("options") if isinstance(data.get("options"), list) else []
        return [base("interrupt.request", {
            "reason": str(data.get("reason", "user_choice") or "user_choice"),
            "question": str(data.get("question", "") or summary),
            "options": options,
            "allowOther": bool(data.get("allowOther", data.get("allow_other", True))),
            "toolCallId": str(data.get("toolCallId", data.get("tool_call_id", "")) or ""),
        })]
    if kind == "interrupt_resolved":
        return [base("interrupt.resolved", {"summary": summary})]
    if kind == "file_changed":
        return [base("artifact.modified", {
            "path": str(data.get("path", "") or ""),
            "summary": summary,
            "operationId": str(data.get("operation_id", "") or ""),
            "diff": str(data.get("diff", "") or ""),
        })]
    if kind == "diff_observed":
        return [base("artifact.diff", {
            "summary": summary,
            "chars": int(data.get("chars", 0) or 0),
            "diff": str(data.get("diff", "") or ""),
        })]
    if kind == "coding_state":
        return [base("coding.state", data)]
    if kind == "editor_command":
        return [base("editor.command", data)]
    if kind == "editor_result":
        return [base("editor.result", {
            "requestId": str(data.get("requestId", "") or ""),
            "command": str(data.get("command", "") or ""),
            "success": bool(data.get("success", False)),
            "message": str(data.get("message", "") or summary),
        })]
    if kind == "ide_request":
        return [base("ide.request", {
            "requestId": str(data.get("requestId", "") or ""),
            "method": str(data.get("method", "") or ""),
            "params": dict(data.get("params") or {}) if isinstance(data.get("params"), dict) else {},
        })]
    if kind == "changeset_created":
        return [base("changeset.created", {
            "changeSetId": str(data.get("change_set_id", data.get("operation_id", "")) or ""),
            "operationId": str(data.get("operation_id", "") or ""),
            "checkpointId": str(data.get("checkpoint_id", "") or ""),
            "files": list(data.get("files") or []) if isinstance(data.get("files"), list) else [],
            "status": str(data.get("status", "pending") or "pending"),
            "summary": summary,
        })]
    if kind in {"changeset_accepted", "changeset_reverted"}:
        return [base("changeset.updated", {
            "changeSetId": str(data.get("change_set_id", data.get("operation_id", "")) or ""),
            "operationId": str(data.get("operation_id", "") or ""),
            "status": "accepted" if kind == "changeset_accepted" else "reverted",
            "files": list(data.get("files") or []) if isinstance(data.get("files"), list) else [],
            "summary": summary,
        })]
    if kind == "test_result":
        return [base("activity.update", {
            "label": "Tests",
            "detail": detail or summary,
            "status": "failed" if int(data.get("failed", 0) or 0) else "completed",
            "passed": int(data.get("passed", 0) or 0),
            "failed": int(data.get("failed", 0) or 0),
        })]

    if kind in {
        "agent_status", "agent_plan", "tool_started", "tool_result", "tool_failed",
        "skill_search", "skill_activated", "checkpoint_created", "checkpoint_restored",
        "supervisor_comment", "supervisor_advisory", "supervisor_redirect", "supervisor_veto",
        "supervisor_ask_user", "supervisor_stop",
        "task_paused", "task_resumed", "interrupt_resume_requested", "rollback_requested",
        "rollback_queued", "rollback_failed",
    }:
        status = "running"
        if kind in {"tool_failed", "rollback_failed"}:
            status = "failed"
        elif kind == "task_paused":
            status = "paused"
        return [base("activity.update", {
            "label": summary or kind,
            "detail": detail,
            "status": status,
            "kind": kind,
            "data": data,
        })]
    return []


__all__ = ["project_agent_event"]
