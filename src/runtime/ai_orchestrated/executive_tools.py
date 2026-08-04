# -*- coding: utf-8 -*-
"""Live tool catalog for the Gemma Executive Cortex.

The catalog is built from contracts already registered by the runtime.  It does
not contain Vietnamese keyword markers and it does not try to predict every way
a user may describe an action.  The executive model receives affordances with
availability, permission and risk, then chooses by meaning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from actions.capability_registry import iter_public_capabilities
from actions.capability_runtime import refresh_runtime_capabilities, runtime_capability_snapshot


@dataclass(frozen=True, slots=True)
class ExecutiveTool:
    name: str
    title: str
    description: str
    available: bool
    availability_reason: str
    risk: str
    permission_mode: str
    auto_callable: bool
    input_schema: Mapping[str, Any]
    source: str = "capability_registry"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_schema"] = dict(self.input_schema)
        return payload


def _contract_metadata(capability_id: str) -> tuple[str, str, str]:
    """Return risk, permission and source from the strongest live contract."""

    try:
        from runtime.internal_cognitive_capabilities import COGNITIVE_CAPABILITY_CONTRACTS

        contract = COGNITIVE_CAPABILITY_CONTRACTS.get(capability_id)
        if contract is not None:
            permission = getattr(contract.permission_mode, "value", contract.permission_mode)
            return "low", str(permission or "read_only_auto"), "internal_cognitive_contract"
    except Exception:
        pass
    try:
        from runtime.environment_capabilities import ENVIRONMENT_CAPABILITY_CONTRACTS

        contract = ENVIRONMENT_CAPABILITY_CONTRACTS.get(capability_id)
        if contract is not None:
            return "low", str(contract.permission_mode or "read_only_auto"), "environment_contract"
    except Exception:
        pass
    try:
        from runtime.project_operations import PROJECT_CAPABILITY_CONTRACTS

        contract = PROJECT_CAPABILITY_CONTRACTS.get(capability_id)
        if contract is not None:
            return (
                str(contract.risk_level or "medium"),
                str(contract.permission_mode or "autonomous_project_scope"),
                "project_contract",
            )
    except Exception:
        pass
    return "low", "runtime_policy", "capability_registry"


def _auto_callable(*, available: bool, risk: str, permission_mode: str) -> bool:
    if not available:
        return False
    permission = str(permission_mode or "").strip().lower()
    risk_key = str(risk or "").strip().lower()
    return permission in {"read_only_auto", "read_only", "auto_read"} and risk_key in {"", "none", "low"}


def build_live_executive_tool_catalog(
    owner: Any | None,
    *,
    include_unavailable: bool = True,
    max_items: int = 64,
    refresh: bool = True,
) -> tuple[ExecutiveTool, ...]:
    """Build tool schemas from the living runtime, not from lexical markers."""

    try:
        if refresh:
            refresh_runtime_capabilities(owner=owner)
        snapshot = runtime_capability_snapshot(refresh=False)
    except Exception:
        snapshot = {"statuses": {}}
    statuses = snapshot.get("statuses", {}) if isinstance(snapshot, Mapping) else {}
    output: list[ExecutiveTool] = []
    for definition in iter_public_capabilities(include_unavailable=True):
        status = statuses.get(definition.id, {}) if isinstance(statuses, Mapping) else {}
        if isinstance(status, Mapping):
            available = bool(status.get("available", definition.live_available))
            reason = str(status.get("reason", "") or "")
        else:
            available = bool(definition.live_available)
            reason = ""
        if not include_unavailable and not available:
            continue
        contract_risk, permission_mode, source = _contract_metadata(definition.id)
        risk = str(contract_risk or definition.risk_level or "low")
        tool = ExecutiveTool(
            name=definition.id,
            title=definition.public_name_vi,
            description=definition.description_vi,
            available=available,
            availability_reason=reason,
            risk=risk,
            permission_mode=permission_mode,
            auto_callable=_auto_callable(
                available=available,
                risk=risk,
                permission_mode=permission_mode,
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action_input": {
                        "type": "string",
                        "description": "Typed input passed to the registered runtime handler. Empty is allowed when the tool needs no target.",
                    }
                },
                "required": ["action_input"],
            },
            source=source,
        )
        output.append(tool)
        if len(output) >= max(1, int(max_items)):
            break
    return tuple(output)


def catalog_index(catalog: tuple[ExecutiveTool, ...]) -> dict[str, ExecutiveTool]:
    return {item.name: item for item in catalog}


__all__ = ["ExecutiveTool", "build_live_executive_tool_catalog", "catalog_index"]
