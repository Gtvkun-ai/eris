# -*- coding: utf-8 -*-
"""Protocol quản lý Living User Memory cho panel Godot.

Module này chỉ chuyển đổi request/response. Quyền sửa, quên và áp dụng policy vẫn
nằm trong ``LivingUserMemoryService``. UI không được phép mở rồi ghi thẳng JSON,
vì cách đó rất nhanh cho tới ngày hai tiến trình cùng lưu và profile biến thành
một bài thơ hậu hiện đại không parse được.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping

from memory.living_user import UserMemoryScope


@dataclass(frozen=True, slots=True)
class MemoryPanelResult:
    status: str
    message: str
    payload: dict[str, Any]


def handle_memory_panel_request(living_user: Any, request: Mapping[str, Any]) -> MemoryPanelResult:
    """Thực thi một action panel và luôn trả snapshot mới sau mutation."""
    if living_user is None:
        return MemoryPanelResult("error", "Living User Memory chưa sẵn sàng.", {})

    action = str(request.get("action") or "snapshot").strip().lower()
    project_id = str(request.get("project_id") or "").strip()
    path = str(request.get("path") or "").strip()
    message = "Đã đọc memory."
    extra: dict[str, Any] = {}

    try:
        if action == "snapshot":
            pass
        elif action == "explain":
            if not path:
                raise ValueError("missing_path")
            extra["explanation"] = [
                _explanation_to_dict(row)
                for row in living_user.explain(path, project_id=project_id)
            ]
            message = "Đã đọc nguồn hình thành memory."
        elif action in {"correct", "confirm"}:
            if not path:
                raise ValueError("missing_path")
            record = _find_record(living_user, path, project_id=project_id)
            value = _coerce_edited_value(request.get("value"), record)
            if action == "confirm" and record is not None:
                value = record.value
            evidence_id = str(request.get("evidence_id") or f"memory_panel_{int(time.time() * 1000)}")
            result = living_user.correct(
                path,
                value,
                evidence_ids=(evidence_id,),
                project_id=project_id,
            )
            if not getattr(result, "changed", False):
                rejected = ", ".join(getattr(result, "rejected", ()) or ())
                raise RuntimeError(rejected or "memory_update_rejected")
            message = "Đã xác nhận memory." if action == "confirm" else "Đã cập nhật memory."
        elif action in {"forget", "reject"}:
            if not path:
                raise ValueError("missing_path")
            hard = bool(request.get("hard", False)) if action == "forget" else False
            changed = living_user.forget(path, project_id=project_id, hard=hard)
            message = (
                "Đã xóa hoàn toàn memory." if hard
                else "Đã ngừng sử dụng memory này."
            ) if changed else "Không tìm thấy memory cần quên."
        elif action == "move_scope":
            if not path:
                raise ValueError("missing_path")
            target_kind = str(request.get("target_scope_kind") or "global").strip().lower()
            target_key = str(request.get("target_scope_key") or "").strip()
            _move_scope(living_user, path, project_id, target_kind, target_key)
            project_id = target_key if target_kind == "project" else ""
            message = "Đã đổi phạm vi sử dụng memory."
        else:
            raise ValueError(f"unsupported_action:{action}")

        payload = build_memory_panel_snapshot(
            living_user,
            include_inferred=bool(request.get("include_inferred", True)),
            project_id=project_id,
        )
        payload.update(extra)
        return MemoryPanelResult("ok", message, payload)
    except Exception as exc:
        payload = build_memory_panel_snapshot(
            living_user,
            include_inferred=bool(request.get("include_inferred", True)),
            project_id=project_id,
        )
        return MemoryPanelResult(
            "error",
            _friendly_error(exc),
            payload,
        )


def build_memory_panel_snapshot(
    living_user: Any,
    *,
    include_inferred: bool = True,
    project_id: str = "",
    limit: int = 48,
) -> dict[str, Any]:
    """Tạo payload UI nhỏ, ổn định và không chứa memory nhạy cảm."""
    records = []
    for record in living_user.profile_store.all():
        if record.sensitivity in {"private", "sensitive"}:
            continue
        if not include_inferred and record.explicitness == "inferred":
            continue
        if record.scope.kind == "project" and project_id and record.scope.key != project_id:
            continue
        records.append(_record_to_panel_dict(record))
        if len(records) >= max(1, int(limit)):
            break

    actions = living_user.action_store.snapshot()
    goals = _compact_action_rows(actions.get("goals"), "goal", 18)
    commitments = _compact_action_rows(actions.get("commitments"), "commitment", 18)
    workflows = _compact_action_rows(actions.get("workflows"), "workflow", 18)

    counts = {
        "total": len(records),
        "confirmed": sum(1 for row in records if row["explicitness"] == "explicit"),
        "observed": sum(1 for row in records if row["explicitness"] == "observed"),
        "inferred": sum(1 for row in records if row["explicitness"] == "inferred"),
        "uncertain": sum(1 for row in records if float(row["confidence"]) < 0.72),
        "goals": len(goals),
        "commitments": len(commitments),
        "workflows": len(workflows),
    }
    return {
        "schema_version": 1,
        "summary_text": _render_panel_brief(records),
        "counts": counts,
        "records": records,
        "goals": goals,
        "commitments": commitments,
        "workflows": workflows,
        "project_id": project_id,
        "generated_at": time.time(),
    }



def _render_panel_brief(records: list[dict[str, Any]]) -> str:
    if not records:
        return "ERIS chưa có đủ thông tin bền vững để tổng hợp về bạn."
    preferred = sorted(
        records,
        key=lambda row: (
            0 if row.get("explicitness") == "explicit" else 1 if row.get("explicitness") == "observed" else 2,
            -float(row.get("confidence") or 0.0),
        ),
    )[:6]
    parts = []
    for row in preferred:
        label = str(row.get("label") or row.get("path") or "Thông tin")
        value = str(row.get("display_value") or "").strip()
        if not value:
            continue
        parts.append(f"{label.lower()} là {value}")
    if not parts:
        return "ERIS đang có một số dấu vết về bạn, nhưng chưa đủ rõ để tổng hợp."
    return "ERIS đang nhớ rằng " + "; ".join(parts) + "."

def _record_to_panel_dict(record: Any) -> dict[str, Any]:
    value = record.value
    if isinstance(value, (dict, list, tuple)):
        display_value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    elif isinstance(value, bool):
        display_value = "Có" if value else "Không"
    else:
        display_value = str(value)
    confidence = float(record.confidence)
    if record.explicitness == "explicit":
        certainty_label = "Đã xác nhận"
    elif confidence >= 0.82:
        certainty_label = "Quan sát khá chắc"
    elif confidence >= 0.62:
        certainty_label = "Cần xác nhận"
    else:
        certainty_label = "Suy đoán yếu"
    return {
        "id": record.id,
        "path": record.path,
        "label": _humanize_path(record.path),
        "category": _category_for_path(record.path),
        "display_value": display_value[:360],
        "value_type": record.value_type,
        "confidence": round(confidence, 5),
        "certainty_label": certainty_label,
        "explicitness": record.explicitness,
        "explicitness_label": {
            "explicit": "Bạn đã nói",
            "observed": "ERIS đã quan sát",
            "inferred": "ERIS đang suy đoán",
        }.get(record.explicitness, "ERIS đang suy đoán"),
        "scope_kind": record.scope.kind,
        "scope_key": record.scope.key,
        "scope_label": _scope_label(record.scope.kind, record.scope.key),
        "source": record.source,
        "evidence_count": len(record.evidence_ids),
        "recurrence": int(record.recurrence),
        "updated_at": float(record.updated_at),
    }


def _find_record(living_user: Any, path: str, *, project_id: str = "") -> Any | None:
    scope = UserMemoryScope("project", project_id) if project_id else None
    rows = living_user.profile_store.get(path, scope=scope)
    return rows[0] if rows else None


def _coerce_edited_value(value: Any, record: Any | None) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if record is None or isinstance(record.value, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        if isinstance(record.value, bool):
            return text.lower() in {"1", "true", "yes", "có", "co"}
        if isinstance(record.value, int):
            return int(text)
        if isinstance(record.value, float):
            return float(text)
        return text


def _move_scope(living_user: Any, path: str, project_id: str, target_kind: str, target_key: str) -> None:
    if target_kind not in {"global", "project"}:
        raise ValueError("unsupported_scope")
    source_scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
    rows = living_user.profile_store.get(path, scope=source_scope)
    if not rows:
        raise ValueError("memory_not_found")
    record = rows[0]
    if target_kind == "project" and not target_key:
        raise ValueError("missing_project_id")
    target_scope = UserMemoryScope(target_kind, target_key if target_kind == "project" else "")
    if target_scope.identity == source_scope.identity:
        return
    result = living_user.profile_store.correct(
        path,
        record.value,
        evidence_ids=(f"memory_scope_move_{int(time.time() * 1000)}",),
        scope=target_scope,
        confidence=max(0.95, float(record.confidence)),
    )
    if not getattr(result, "changed", False):
        raise RuntimeError("scope_move_rejected")
    living_user.profile_store.forget(path, scope=source_scope, hard=False, reason="scope_changed")


def _explanation_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        raw = value.to_dict()
    elif is_dataclass(value):
        raw = asdict(value)
    elif hasattr(value, "__dict__"):
        raw = dict(value.__dict__)
    else:
        raw = {"detail": str(value)}
    safe = _json_safe(raw)
    # Chuẩn hóa tên field cho UI; panel không cần biết class Python phía sau.
    sources = safe.get("sources") if isinstance(safe, dict) else []
    return {
        "path": str(safe.get("path") or "") if isinstance(safe, dict) else "",
        "value": safe.get("value") if isinstance(safe, dict) else None,
        "confidence": safe.get("confidence", 0.0) if isinstance(safe, dict) else 0.0,
        "explicitness": str(safe.get("explicitness") or "") if isinstance(safe, dict) else "",
        "note": str(safe.get("note") or safe.get("detail") or "") if isinstance(safe, dict) else str(value),
        "sources": sources if isinstance(sources, list) else [],
    }


def _compact_action_rows(value: Any, kind: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value[:limit]:
        if not isinstance(raw, Mapping):
            continue
        scope = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
        common = {
            "id": str(raw.get("id") or ""),
            "status": str(raw.get("status") or ""),
            "scope": {"kind": str(scope.get("kind") or "global"), "key": str(scope.get("key") or "")},
        }
        if kind == "goal":
            common.update({
                "title": str(raw.get("title") or "")[:240],
                "description": str(raw.get("description") or "")[:360],
                "next_actions": [str(x)[:180] for x in list(raw.get("next_actions") or [])[:6]],
            })
        elif kind == "commitment":
            common.update({
                "actor": str(raw.get("actor") or "")[:80],
                "action": str(raw.get("action") or "")[:360],
            })
        else:
            common.update({
                "trigger": str(raw.get("trigger") or "")[:240],
                "steps": [str(x)[:180] for x in list(raw.get("steps") or [])[:8]],
            })
        rows.append(common)
    return rows


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _category_for_path(path: str) -> str:
    root = str(path or "").split(".", 1)[0]
    return {
        "user": "about",
        "identity": "about",
        "communication": "communication",
        "preferences": "preferences",
        "preference": "preferences",
        "projects": "projects",
        "goals": "projects",
        "technical": "workflow",
        "workflow": "workflow",
        "constraints": "workflow",
        "relationship": "interaction",
    }.get(root, "other")


def _humanize_path(path: str) -> str:
    aliases = {
        "user.name": "Tên của bạn",
        "user.nickname": "Cách bạn muốn được gọi",
        "identity.gender": "Giới tính",
        "communication.language": "Ngôn ngữ giao tiếp",
        "communication.response_style": "Cách bạn muốn ERIS trả lời",
        "technical.skill_level": "Mức độ kỹ thuật",
        "technical.architecture_preference": "Ưu tiên kiến trúc",
        "workflow.delivery_preference": "Cách bạn muốn nhận kết quả",
    }
    if path in aliases:
        return aliases[path]
    tail = str(path or "").split(".")[-1].replace("_", " ").strip()
    return tail[:1].upper() + tail[1:] if tail else path


def _scope_label(kind: str, key: str) -> str:
    if kind == "project":
        return f"Chỉ dự án {key}" if key else "Theo dự án"
    if kind == "session":
        return "Chỉ phiên hiện tại"
    if kind == "temporary":
        return "Tạm thời"
    return "Mọi cuộc trò chuyện"


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    mapping = {
        "missing_path": "Thiếu đường dẫn memory.",
        "memory_not_found": "Không tìm thấy memory này.",
        "missing_project_id": "Cần nhập mã dự án trước khi đổi phạm vi.",
        "unsupported_scope": "Panel hiện chỉ hỗ trợ phạm vi toàn cục hoặc theo dự án.",
    }
    return mapping.get(text, f"Không thể xử lý memory: {text[:180]}")


__all__ = [
    "MemoryPanelResult",
    "build_memory_panel_snapshot",
    "handle_memory_panel_request",
]
