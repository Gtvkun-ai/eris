# -*- coding: utf-8 -*-
"""Canonical execution observer for speech/body/system/memory actions."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import ExecutionReport


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


class V3ExecutionEngine:
    module_name = "execution_layer"

    def planned(self, frame: Any) -> ExecutionReport:
        agency = _get(frame, "agency", None)
        modality = _get(frame, "modality", None)
        body = _get(modality, "body_plan", None)
        return ExecutionReport(
            status="planned",
            speech_executed=False,
            body_executed=False,
            system_action_executed=False,
            memory_commit_deferred=True,
            details={
                "agency_intent": str(_get(agency, "intent", "observe") or "observe"),
                "body_action": str(_get(body, "action", "none") or "none"),
                "system_action": str(_get(modality, "system_action", "") or ""),
            },
        )

    def observe(self, frame: Any, decision: Any = None, *, execution_result: Any = None) -> ExecutionReport:
        text = str(_get(decision, "text", "") or "").strip()
        should_speak = bool(_get(decision, "should_speak", bool(text)))
        body_action = str(_get(_get(frame, "body_plan", None), "action", "none") or "none")
        system_action = str(_get(decision, "system_action", "") or _get(_get(frame, "modality", None), "system_action", "") or "")
        success = _get(execution_result, "success", None)
        if success is None:
            success = _get(execution_result, "ok", None)
        status = "completed"
        if success is False:
            status = "failed"
        elif execution_result is None and system_action:
            status = "deferred"
        details = {
            "speech_text_length": len(text),
            "body_action": body_action,
            "system_action": system_action,
            "execution_result": repr(execution_result)[:600] if execution_result is not None else "",
        }
        return ExecutionReport(
            status=status,
            speech_executed=bool(should_speak and text),
            body_executed=body_action not in {"", "none"},
            system_action_executed=bool(system_action and success is not False and execution_result is not None),
            memory_commit_deferred=True,
            details=details,
        )


__all__ = ["V3ExecutionEngine"]
