# -*- coding: utf-8 -*-
"""Single tool boundary for ERIS RootAgent V13.

Pipeline: live inventory -> discover -> describe exact JSON schema -> validate ->
execute using the EXISTING sandbox-backed ActionExecutor -> normalized result.
Domain intelligence tools use the same boundary but never bypass ActionExecutor
for OS/project side effects. Discover/describe do not execute anything.

This is deliberately NOT a second planner, skill prompt injector, fallback
executor, or capability routing by keywords. Root alone selects which tool to
run; selection is constrained mechanically at execution time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
import json

from actions.capability_registry import (
    capability_input_schema,
    iter_public_capabilities,
    validate_capability_arguments,
)


@dataclass(frozen=True, slots=True)
class DomainTool:
    id: str
    description: str
    schema: Mapping[str, Any]
    execute: Callable[[Mapping[str, Any], Any, Sequence[Mapping[str, Any]]], Mapping[str, Any]]
    available: Callable[[], bool]
    group: str = "intelligence"
    risk: str = "low"


class ToolGateway:
    """Fail-closed, exact-ID tool bridge scoped to one live ERIS host.

    An absent runtime-status record is NOT an implicit authorization. Callers
    may supply a snapshot provider for deterministic tests, otherwise use the
    existing runtime health service. A returned `started` is never `success`.
    """

    def __init__(
        self,
        executor: Any | None,
        *,
        domain_tools: Sequence[DomainTool] = (),
        status_provider: Callable[[], Mapping[str, Any]] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.executor = executor
        self.logger = logger
        ids = [tool.id for tool in domain_tools]
        if len(set(ids)) != len(ids) or any(not x or "." not in x for x in ids):
            raise ValueError("domain_tool_ids_must_be_unique_and_namespaced")
        self._domain = {tool.id: tool for tool in domain_tools}
        if status_provider is None:
            from actions.capability_runtime import runtime_capability_snapshot
            status_provider = lambda: runtime_capability_snapshot(refresh=True)
        self._status_provider = status_provider

    def _inventory(self) -> dict[str, dict[str, Any]]:
        statuses: Mapping[str, Any] = {}
        try:
            raw = self._status_provider()
            statuses = raw.get("statuses", {}) if isinstance(raw, Mapping) else {}
        except Exception:
            statuses = {}
        items: dict[str, dict[str, Any]] = {}
        if self.executor is not None and callable(getattr(self.executor, "execute_capability", None)):
            for cap in iter_public_capabilities(include_unavailable=True):
                state = statuses.get(cap.id) if isinstance(statuses, Mapping) else None
                if not cap.callable or cap.exposure == "compatibility" or not isinstance(state, Mapping):
                    continue
                if not bool(state.get("available", False)):
                    continue
                items[cap.id] = {
                    "id": cap.id,
                    "name": cap.public_name_vi,
                    "description": cap.description_vi,
                    "group": cap.visible_in_ui_group,
                    "effect": cap.effect,
                    "risk": cap.risk_level,
                    "schema": capability_input_schema(cap.id),
                    "domain": False,
                }
        for tool in self._domain.values():
            try:
                online = bool(tool.available())
            except Exception:
                online = False
            if online:
                items[tool.id] = {
                    "id": tool.id,
                    "name": tool.id,
                    "description": tool.description,
                    "group": tool.group,
                    "effect": "intelligence",
                    "risk": tool.risk,
                    "schema": dict(tool.schema),
                    "domain": True,
                }
        return items

    @staticmethod
    def _public(item: Mapping[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in ("id", "name", "description", "group", "effect", "risk")}

    def overview(self) -> dict[str, Any]:
        """Small, live preview in EACH Root model turn, with no authority to call."""
        items = self._inventory()
        groups: dict[str, int] = {}
        for item in items.values():
            groups[item["group"]] = groups.get(item["group"], 0) + 1
        return {"available_count": len(items), "groups": groups,
                "discovery": "Use kind=tool_discover to search; then tool_describe; then tool_call."}

    def discover(self, query: str = "", group: str = "", limit: int = 12) -> dict[str, Any]:
        items = self._inventory()
        query = " ".join(str(query or "").lower().split())[:240]
        group = str(group or "").strip().lower()[:64]
        candidates = [item for item in items.values() if not group or item["group"] == group]
        if query:
            # Lexical retrieval only (NOT semantic routing); Root chooses a tool.
            terms = tuple(dict.fromkeys(query.split()))
            def score(item: Mapping[str, Any]) -> int:
                name = (item["id"] + " " + item["name"]).lower()
                description = (item["description"] + " " + item["group"]).lower()
                return sum(4 * (term in name) + (term in description) for term in terms)
            candidates.sort(key=lambda item: (-score(item), item["id"]))
            candidates = [item for item in candidates if score(item) > 0]
        else:
            candidates.sort(key=lambda item: (item["group"], item["id"]))
        limit = max(1, min(25, int(limit or 12)))
        return {"status": "ok", "total_matches": len(candidates),
                "tools": [self._public(item) for item in candidates[:limit]],
                "hint": "Choose an exact ID; call tool_describe to get its parameter schema."}

    def describe(self, tool_id: str) -> dict[str, Any]:
        tool_id = str(tool_id or "").strip()
        item = self._inventory().get(tool_id)
        if item is None:
            return {"status": "unavailable", "tool_id": tool_id, "reason": "tool_not_live_or_not_registered"}
        return {"status": "ok", "tool": self._public(item), "input_schema": item["schema"]}

    def call(
        self, tool_id: str, arguments: Mapping[str, Any] | None,
        *, event: Any = None, recent_history: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        tool_id = str(tool_id or "").strip()
        item = self._inventory().get(tool_id)  # TOCTOU: recheck availability before execution.
        if item is None:
            return {"status": "unavailable", "tool_id": tool_id, "reason": "tool_not_live_or_not_registered"}
        if not isinstance(arguments, Mapping):
            return {"status": "invalid", "tool_id": tool_id, "reason": "arguments_must_be_object"}
        args = dict(arguments)
        try:
            # Exact schema validation is mechanical; no invented argument coercion.
            if item["domain"]:
                ok, reason = _validate_domain(item["schema"], args)
            else:
                ok, reason = validate_capability_arguments(tool_id, args)
            if not ok:
                return {"status": "invalid", "tool_id": tool_id, "reason": str(reason)[:300]}
            if item["domain"]:
                raw = self._domain[tool_id].execute(args, event, recent_history)
                if not isinstance(raw, Mapping):
                    return {"status": "failed", "tool_id": tool_id, "reason": "untyped_domain_result"}
                outcome = dict(raw)
                # Domain starts are asynchronous requests, not completed actions.
                outcome.setdefault("status", "unknown")
                outcome["tool_id"] = tool_id
                return _bounded(outcome)
            result = self.executor.execute_capability(tool_id, args)
            status = getattr(result, "status", "")
            status = str(getattr(status, "value", status) or "").lower()
            success = bool(getattr(result, "success", False))
            # A dispatched side effect is NOT an observed completion. Preserve
            # distinction for writer evidence and anti-fabrication checks.
            if not success:
                normalized = "failed"
            elif bool(getattr(result, "observed", False)) or status == "observed":
                normalized = "completed"
            else:
                normalized = "dispatched"
            public_meta = getattr(result, "to_public_meta", None)
            return _bounded({
                "status": normalized,
                "tool_id": tool_id,
                "success": success,
                "observed": normalized == "completed",
                "message": str(getattr(result, "message", "") or "")[:10000],
                "data": dict(getattr(result, "data", {}) or {}),
                "evidence": list(getattr(result, "evidence", ()) or ())[:32],
                "error_kind": str(getattr(result, "error_kind", "") or "")[:240],
                "public_meta": public_meta() if callable(public_meta) else {},
            })
        except Exception as exc:  # noqa: BLE001
            if self.logger is not None:
                log = getattr(self.logger, "warning", None)
                if callable(log):
                    log("[tool-gateway] tool=%s failed: %s", tool_id, type(exc).__name__)
            return {"status": "failed", "tool_id": tool_id, "reason": type(exc).__name__}


def _validate_domain(schema: Mapping[str, Any], args: Mapping[str, Any]) -> tuple[bool, str]:
    if schema.get("type") != "object":
        return False, "invalid_domain_schema"
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(props, Mapping):
        return False, "invalid_domain_schema"
    for key in required:
        if key not in args:
            return False, "missing_required:" + str(key)
    if not schema.get("additionalProperties", False):
        extra = args.keys() - props.keys()
        if extra:
            return False, "unknown_argument:" + sorted(extra)[0]
    for key, value in args.items():
        typ = props.get(key, {}).get("type") if isinstance(props.get(key), Mapping) else None
        if typ == "string" and not isinstance(value, str):
            return False, "expected_string:" + key
        if typ == "boolean" and not isinstance(value, bool):
            return False, "expected_boolean:" + key
        if typ == "integer" and (type(value) is not int):
            return False, "expected_integer:" + key
        if isinstance(value, str) and len(value) > 24000:
            return False, "argument_too_long:" + key
        if isinstance(props.get(key), Mapping) and "enum" in props[key] and value not in props[key]["enum"]:
            return False, "invalid_enum:" + key
    return True, ""


def _bounded(value: Mapping[str, Any]) -> dict[str, Any]:
    """Use a JSON round trip to isolate mutable backend state and cap huge output."""
    try:
        result = json.dumps(value, ensure_ascii=False, default=str)
        if len(result) > 24000:
            # Do not promote a truncated payload to completed: supporting
            # evidence might have been cut off. Force an explicit retry/summary.
            return {"status": "truncated", "tool_id": value.get("tool_id", ""),
                    "preview": result[:12000], "truncated": True}
        return json.loads(result)
    except (TypeError, ValueError):
        return {"status": "failed", "reason": "unserializable_result"}
