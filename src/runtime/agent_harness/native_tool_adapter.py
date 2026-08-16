# -*- coding: utf-8 -*-
"""Adapter nối capability thật của Eris vào Unified Agent Harness.

LangGraph/Gemini chỉ nhìn thấy schema có cấu trúc. Mọi side effect vẫn đi qua
ActionExecutor -> Subject Core/SandboxWorld hiện hữu, vì bypass lớp quyền chỉ để
agent trông "xịn" là cách rất nhanh để biến xịn thành tai nạn.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from actions.capability_registry import (
    capability_definition,
    capability_input_schema,
    iter_public_capabilities,
)


class NativeCapabilityToolAdapter:
    def __init__(self, action_executor: Any) -> None:
        self.action_executor = action_executor

    def live_ids(self) -> tuple[str, ...]:
        return tuple(
            cap.id
            for cap in iter_public_capabilities(include_unavailable=False)
            if cap.callable
        )

    def agent_ids(self) -> tuple[str, ...]:
        """Capabilities safe to mount even when availability changes at runtime.

        Project/workspace tools are unavailable before a workspace is activated,
        but that is a transient state. Hiding their schemas forever at boot would
        make the new agent beautifully incapable of coding, which is impressive
        in the wrong direction.
        """
        result: list[str] = []
        for cap in iter_public_capabilities(include_unavailable=True):
            if not cap.callable:
                continue
            if cap.live_available or cap.id.startswith("project_") or cap.id.startswith("workspace_"):
                result.append(cap.id)
        return tuple(result)

    def tool_specs(self, capability_ids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
        allowed = set(capability_ids or self.agent_ids())
        resolved_caps = {cap.id: cap for cap in iter_public_capabilities(include_unavailable=True)}
        specs: dict[str, dict[str, Any]] = {}
        for cap_id in allowed:
            cap = capability_definition(cap_id)
            if cap is None or not cap.callable:
                continue
            dynamic_project = cap.id.startswith("project_") or cap.id.startswith("workspace_")
            if not cap.live_available and not dynamic_project:
                continue
            try:
                from actions.capability_runtime import capability_runtime_reason
                health_reason = capability_runtime_reason(cap.id)
            except Exception:
                health_reason = "runtime_snapshot_unavailable"
            effect = str(cap.effect or "inspect").lower()
            if cap.id == "project_execute_task":
                estimated_time = "minutes"
            elif cap.id in {"project_run_tests", "project_run_command", "project_package_patch"}:
                estimated_time = "seconds to minutes"
            elif cap.id.startswith("project_") or cap.id.startswith("workspace_"):
                estimated_time = "1-10s"
            else:
                estimated_time = "<3s" if effect in {"observe", "inspect", "read"} else "<10s"
            specs[cap.id] = {
                "name": cap.id,
                "description": cap.description_vi,
                "input_schema": capability_input_schema(cap.id),
                "effect": cap.effect,
                "risk_level": cap.risk_level,
                "available": bool(getattr(resolved_caps.get(cap.id), "live_available", cap.live_available)),
                "health_reason": health_reason,
                "workspace_required": cap.id.startswith("project_"),
                "estimated_time": estimated_time,
                "reversible": effect in {"observe", "inspect", "read"} or cap.id in {
                    "project_apply_patch", "project_rollback", "copy_text", "set_volume", "play_pause_media",
                },
            }
        return specs

    def registry(self, capability_ids: Iterable[str] | None = None) -> dict[str, Callable[..., Any]]:
        ids = tuple(capability_ids or self.agent_ids())
        return {cap_id: self._make_callable(cap_id) for cap_id in ids}

    def _make_callable(self, capability_id: str) -> Callable[..., Any]:
        def invoke(**arguments: Any) -> dict[str, Any]:
            execute = getattr(self.action_executor, "execute_capability", None)
            if not callable(execute):
                raise RuntimeError("action_executor_missing_execute_capability")
            result = execute(capability_id, arguments)
            status = getattr(result, "status", "")
            status_value = getattr(status, "value", status)
            return {
                "capability": capability_id,
                "success": bool(getattr(result, "success", False)),
                "status": str(status_value or ""),
                "message": str(getattr(result, "message", "") or ""),
                "data": dict(getattr(result, "data", {}) or {}),
                "evidence": list(getattr(result, "evidence", ()) or ()),
                "error_kind": str(getattr(result, "error_kind", "") or ""),
                "observer_reason": str(getattr(result, "observer_reason", "") or ""),
            }

        invoke.__name__ = capability_id
        invoke.__doc__ = (capability_definition(capability_id).description_vi if capability_definition(capability_id) else capability_id)
        return invoke


__all__ = ["NativeCapabilityToolAdapter"]
