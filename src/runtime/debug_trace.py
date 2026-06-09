# -*- coding: utf-8 -*-
"""
runtime/debug_trace.py

Debug Output Standard cho ERIS V3.

Vấn đề kinh điển: pipeline chạy, module nào cũng có, nhưng khi hỏi "sao nó
chọn nói/im/body_only?" thì câu trả lời là 400 dòng stack trace như tụng kinh.

File này xuất MỖI cycle một JSON ngắn, đọc được bằng mắt người:

    {
      "frame_id": "...",
      "budget": "normal",
      "dominant_focus": "user asks what to build next for V3",
      "selected_evidence": ["user_request"],
      "working_memory": ["V3 roadmap", "Phase 0", "Phase 1"],
      "workspace": ["..."],
      "speech_opportunity": "direct_answer",
      "permission": {"public_sayable": true, "max_intensity": 0.55},
      "final_action": "technical_diagnosis"
    }

Nguyên tắc:
    - Không sửa frame. Chỉ đọc. Validator vừa chẩn đoán vừa mổ là y học của bug.
    - Duck-typing mạnh: đọc được cả CognitiveFrame V3 (core) lẫn frame cũ
      (cortex/contracts) mà không cần biết trước loại nào.
    - Không bao giờ ném exception ra runtime. Trace lỗi cũng phải đọc được.
"""

from __future__ import annotations

import json
from typing import Any, Optional


# ======================================================================
# Helpers duck-typing
# ======================================================================

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first_get(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        value = _get(obj, name, None)
        if value is not None:
            return value
    return default


def _shorten(text: Any, max_len: int = 120) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _round(value: Any, digits: int = 3) -> Optional[float]:
    try:
        return round(float(value), digits)
    except Exception:
        return None


# ======================================================================
# Extractors theo từng slot
# ======================================================================

def _extract_budget(frame: Any) -> str:
    return str(_first_get(frame, ("budget_mode", "budget"), "unknown"))


def _extract_evidence_ids(frame: Any, limit: int = 8) -> list[str]:
    evidence = _get(frame, "evidence", []) or []
    ids: list[str] = []
    for item in evidence:
        eid = _get(item, "id", None)
        if eid:
            ids.append(str(eid))
        if len(ids) >= limit:
            break
    return ids


def _extract_dominant_focus(frame: Any) -> Optional[str]:
    """Lấy dominant focus từ salience (V3) hoặc broadcast (frame cũ)."""

    salience = _get(frame, "salience", None)
    if salience is not None:
        focus = _first_get(salience, ("dominant_focus", "dominant_focus_text"), None)
        if focus:
            return _shorten(focus)

    # frame cũ: broadcast.content / broadcast.label
    broadcast = _get(frame, "broadcast", None)
    if broadcast is not None:
        content = _first_get(broadcast, ("content", "label"), None)
        if content:
            return _shorten(content)

    # fallback: evidence mạnh nhất nếu frame hỗ trợ
    strongest = getattr(frame, "strongest_evidence", None)
    if callable(strongest):
        try:
            top = strongest(limit=1)
            if top:
                return _shorten(_get(top[0], "claim", ""))
        except Exception:
            pass
    return None


def _extract_selected_evidence(frame: Any, limit: int = 6) -> list[str]:
    """Evidence mà attention thực sự chọn broadcast (không phải toàn bộ)."""

    salience = _get(frame, "salience", None)
    if salience is not None:
        ids = _get(salience, "selected_evidence_ids", None)
        if ids:
            return [str(x) for x in ids][:limit]
    return _extract_evidence_ids(frame, limit=limit)


def _extract_working_memory(frame: Any, limit: int = 7) -> list[str]:
    wm = _get(frame, "working_memory", None)
    if wm is None:
        return []
    slots = _first_get(wm, ("active_slots", "workspace_candidates", "slots"), []) or []
    out: list[str] = []
    for slot in slots:
        label = _first_get(slot, ("name", "kind", "content"), None)
        content = _get(slot, "content", None)
        text = content if content else label
        if text:
            out.append(_shorten(text, 80))
        if len(out) >= limit:
            break
    return out


def _extract_workspace(frame: Any, limit: int = 6) -> list[str]:
    ws = _get(frame, "workspace", None)
    if ws is None:
        return []
    items = _first_get(ws, ("broadcast_items", "items", "active_slots"), []) or []
    out: list[str] = []
    for item in items:
        text = _first_get(item, ("content", "label", "name"), None)
        if text:
            out.append(_shorten(text, 80))
        if len(out) >= limit:
            break
    return out


def _extract_permission(frame: Any) -> Optional[dict[str, Any]]:
    permission = _get(frame, "permission", None)
    if permission is None:
        return None
    public_sayable = _first_get(permission, ("public_sayable", "sayable", "can_speak"), None)
    max_intensity = _first_get(permission, ("max_intensity", "intensity_cap"), None)
    out: dict[str, Any] = {}
    if public_sayable is not None:
        out["public_sayable"] = bool(public_sayable)
    if max_intensity is not None:
        out["max_intensity"] = _round(max_intensity)
    return out or None


def _extract_speech_opportunity(frame: Any) -> Optional[str]:
    opp = _get(frame, "speech_opportunity", None)
    if opp is not None:
        text = _first_get(opp, ("mode", "kind", "label"), None)
        if text:
            return str(text)
        if isinstance(opp, str):
            return opp
    return None


def _extract_final_action(frame: Any) -> Optional[str]:
    """Hành động cuối: đọc từ frame V3 (execution/outcome) hoặc frame cũ (final_decision/action_plan)."""

    # frame cũ
    final_decision = _get(frame, "final_decision", None)
    if isinstance(final_decision, dict):
        action = final_decision.get("parse_mode") or final_decision.get("intent") or final_decision.get("action")
        if action:
            return str(action)

    action_plan = _get(frame, "action_plan", None)
    if action_plan is not None:
        action = _first_get(action_plan, ("speech_intent", "speech_act", "system_action"), None)
        if action:
            return str(action)

    # frame V3
    execution = _get(frame, "execution", None)
    if execution is not None:
        action = _first_get(execution, ("action", "kind", "mode"), None)
        if action:
            return str(action)

    outcome = _get(frame, "outcome", None)
    if outcome is not None:
        action = _first_get(outcome, ("action", "result", "kind"), None)
        if action:
            return str(action)
    return None


def _extract_module_confidences(frame: Any) -> dict[str, float]:
    reports = _get(frame, "module_reports", None)
    out: dict[str, float] = {}
    if isinstance(reports, dict):
        for name, report in reports.items():
            conf = _round(_get(report, "confidence", None))
            if conf is not None:
                out[str(name)] = conf
    return out


# ======================================================================
# API chính
# ======================================================================

def render_frame_trace(frame: Any) -> dict[str, Any]:
    """Trả về dict trace ngắn, đọc được bằng mắt người, cho một cycle."""

    try:
        trace: dict[str, Any] = {
            "frame_id": str(_first_get(frame, ("frame_id", "cycle_id"), "unknown")),
            "channel": str(_get(frame, "channel", "unknown")),
            "status": str(_get(frame, "status", "")) or None,
            "budget": _extract_budget(frame),
            "dominant_focus": _extract_dominant_focus(frame),
            "selected_evidence": _extract_selected_evidence(frame),
            "evidence_count": len(_get(frame, "evidence", []) or []),
            "working_memory": _extract_working_memory(frame),
            "workspace": _extract_workspace(frame),
            "speech_opportunity": _extract_speech_opportunity(frame),
            "permission": _extract_permission(frame),
            "final_action": _extract_final_action(frame),
            "module_confidence": _extract_module_confidences(frame),
            "warnings": [str(w) for w in (_get(frame, "warnings", []) or [])][:8],
        }
        # Bỏ key None/empty để JSON gọn, dễ đọc.
        return {k: v for k, v in trace.items() if v not in (None, [], {}, "")}
    except Exception as exc:  # trace không bao giờ được làm chết runtime
        return {
            "frame_id": str(_first_get(frame, ("frame_id", "cycle_id"), "unknown")),
            "debug_trace_error": repr(exc),
        }


def render_frame_trace_json(frame: Any, *, indent: int = 2) -> str:
    """Trace dạng JSON string UTF-8 friendly."""

    return json.dumps(render_frame_trace(frame), ensure_ascii=False, indent=indent, default=str)


def render_trace_line(frame: Any) -> str:
    """Một dòng tóm tắt cực ngắn cho log stream."""

    t = render_frame_trace(frame)
    return (
        f"[{t.get('frame_id', '?')}] "
        f"budget={t.get('budget', '?')} "
        f"focus={t.get('dominant_focus', '-')!r} "
        f"action={t.get('final_action', '-')}"
    )


def attach_trace_to_frame(frame: Any) -> dict[str, Any]:
    """Tạo trace và gắn vào frame.debug_notes/metadata nếu frame hỗ trợ.

    Trả về dict trace để caller dùng tiếp (vd ghi log).
    """

    trace = render_frame_trace(frame)
    metadata = _get(frame, "metadata", None)
    if isinstance(metadata, dict):
        metadata["debug_trace"] = trace
    add_debug_note = getattr(frame, "add_debug_note", None)
    if callable(add_debug_note):
        try:
            add_debug_note(render_trace_line(frame), actor="debug_trace")
        except Exception:
            pass
    return trace


__all__ = [
    "render_frame_trace",
    "render_frame_trace_json",
    "render_trace_line",
    "attach_trace_to_frame",
]
