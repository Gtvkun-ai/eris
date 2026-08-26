# -*- coding: utf-8 -*-
"""Protocol V2 projector cho Eris IDE bridge.

Internal event names được giữ ổn định cho audit/supervisor. Module này chỉ chiếu
chúng thành event semantic mà VS Code UI hiểu: message/activity/interrupt/artifact.
"""
from __future__ import annotations

from typing import Any


# Nhãn semantic dùng chung cho các surface IDE. Tên tool thật vẫn nằm trong
# payload.data để Developer Details/audit dùng khi cần, còn UI mặc định chỉ
# thấy hành động mà con người hiểu được.
_TOOL_LABELS: dict[str, str] = {
    "project_list_files": "Đọc cấu trúc dự án",
    "project_read_file": "Đọc file",
    "project_search_text": "Tìm trong code",
    "project_find_symbol": "Tìm symbol",
    "project_semantic_search": "Tìm code theo ngữ nghĩa",
    "project_git_log": "Đọc lịch sử Git",
    "project_dependency_summary": "Đọc dependency",
    "project_test_inventory": "Kiểm kê test suite",
    "project_git_diff": "Kiểm tra thay đổi Git",
    "project_apply_patch": "Áp dụng thay đổi",
    "project_run_tests": "Chạy kiểm thử",
    "project_run_command": "Chạy lệnh dự án",
    "editor_open_file": "Mở file trong VS Code",
    "editor_open_diff": "Mở diff",
    "editor_focus_problems": "Mở Problems",
    "editor_show_source_control": "Mở Source Control",
    "ide_get_current_file": "Đọc file hiện tại",
    "ide_get_selection": "Đọc vùng chọn",
    "ide_get_problems": "Đọc lỗi và cảnh báo",
    "ide_get_git_state": "Đọc trạng thái Git",
    "ide_get_terminal_recent": "Đọc terminal gần nhất",
    "ide_get_open_editors": "Đọc các tab đang mở",
    "ide_get_workspace_info": "Đọc thông tin workspace",
    "search_capabilities": "Tìm capability phù hợp",
    "activate_skill": "Nạp skill cần thiết",
    "ask_user_choice": "Chờ quyết định của người dùng",
}


def _tool_label(data: dict[str, Any], fallback: str = "Thực thi công cụ") -> str:
    tool = str(data.get("tool", "") or "").strip()
    return _TOOL_LABELS.get(tool, fallback if not tool else tool.replace("_", " "))


def _compact_detail(value: str, limit: int = 2400) -> str:
    """Giới hạn telemetry gửi sang Webview; log gốc vẫn nằm ở event store."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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
        # Một internal event có thể chiếu thành nhiều semantic event. Ví dụ
        # task_completed -> activity.end + message.assistant. Dùng cùng eventId
        # khiến Webview dedupe mất message cuối. Gắn semantic type vào ID để mỗi
        # packet có identity ổn định nhưng vẫn truy ngược được event gốc.
        projected_event_id = f"{event_id}:{event_type}" if event_id else ""
        return {
            "type": event_type,
            "protocol": "eris.ide.v2",
            "eventId": projected_event_id,
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
            # Permission card cần biết side effect cụ thể để user duyệt có thông tin.
            # Args ở đây đã đi qua _safe_tool_args trước khi được ghi vào event.
            "tool": str(data.get("tool", "") or ""),
            "args": dict(data.get("args") or {}) if isinstance(data.get("args"), dict) else {},
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
        "rollback_queued", "rollback_failed", "repository_context_started", "repository_context_ready",
        "context_gate_blocked", "completion_gate_blocked",
        "coding_team_selected", "team_handoff", "team_handoff_rejected",
        "team_plan_ready", "team_review_changes_requested",
    }:
        status = "running"
        if kind in {"tool_failed", "rollback_failed"}:
            status = "failed"
        elif kind == "task_paused":
            status = "paused"

        # Projector chịu trách nhiệm biến internal event thành ngôn ngữ UI.
        # Nhờ vậy cả custom panel lẫn @eris native chat đều không phải tự đoán
        # ý nghĩa từ tên RPC/tool cấp thấp.
        if kind == "agent_plan":
            label = "Đang lập kế hoạch thực thi"
        elif kind == "tool_started":
            label = _tool_label(data)
        elif kind == "tool_result":
            label = _tool_label(data)
            status = "completed"
        elif kind == "tool_failed":
            label = _tool_label(data, "Công cụ thất bại")
        elif kind == "skill_search":
            label = "Tìm capability phù hợp"
        elif kind == "skill_activated":
            label = "Đã nạp skill"
            status = "completed"
        elif kind == "checkpoint_created":
            label = "Đã tạo checkpoint"
            status = "completed"
        elif kind == "checkpoint_restored":
            label = "Đã khôi phục checkpoint"
            status = "completed"
        elif kind.startswith("supervisor_"):
            label = "Eris đang rà lại hướng thực thi"
        elif kind == "task_paused":
            label = "Task đã tạm dừng"
        elif kind == "task_resumed":
            label = "Task đang tiếp tục"
        elif kind.startswith("rollback_"):
            label = "Đang khôi phục thay đổi"
        elif kind == "repository_context_started":
            label = "Đang lập bản đồ repository"
        elif kind == "repository_context_ready":
            label = "Đã hiểu cấu trúc repository"
            status = "completed"
        elif kind == "context_gate_blocked":
            label = "Đang bổ sung ngữ cảnh trước khi sửa"
        elif kind == "completion_gate_blocked":
            label = "Đang xác minh thay đổi trước khi hoàn tất"
        elif kind == "coding_team_selected":
            label = "Đã lập coding team"
            status = "completed"
        elif kind == "team_handoff":
            source = str(data.get("from", "") or "").title()
            target = str(data.get("to", "") or "").title()
            label = f"{source} → {target}" if source and target else "Chuyển giao giữa specialist"
            status = "completed"
        elif kind == "team_plan_ready":
            label = "Planner đã chốt kế hoạch"
            status = "completed"
        elif kind == "team_review_changes_requested":
            label = "Reviewer yêu cầu Coder sửa thêm"
        elif kind == "team_handoff_rejected":
            label = "Handoff bị chặn"
            status = "failed"
        else:
            label = summary or "Đang xử lý"

        return [base("activity.update", {
            "label": label,
            "detail": _compact_detail(detail),
            "status": status,
            "kind": kind,
            "data": data,
        })]
    return []


__all__ = ["project_agent_event"]
