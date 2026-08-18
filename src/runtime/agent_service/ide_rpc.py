# -*- coding: utf-8 -*-
"""RPC bridge đồng bộ từ LangGraph sang VS Code Extension.

Tool node của LangGraph đang chạy ở worker Python đồng bộ, còn VS Code là một
process khác. Broker này biến một lời gọi ``ide.get*`` thành event có ``requestId``
rồi chờ đúng response từ extension. Không polling snapshot, không cho Webview quyền
file trực tiếp, và không trộn response giữa hai task/session.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from runtime.agent_harness.event_bus import AgentEventBus


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class IdeRpcBroker:
    """Request/response broker nhỏ cho semantic IDE context."""

    def __init__(self, event_bus: AgentEventBus, *, logger: Any = None, default_timeout: float = 4.0) -> None:
        self.event_bus = event_bus
        self.logger = logger
        self.default_timeout = max(0.5, float(default_timeout or 4.0))
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}

    def request(
        self,
        task_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        method = str(method or "").strip()
        if not task_id or not method:
            raise RuntimeError("ide_rpc_requires_task_and_method")
        request_id = f"ide_rpc_{uuid.uuid4().hex[:14]}"
        pending = _Pending()
        with self._lock:
            self._pending[request_id] = pending
        try:
            emitted = self.event_bus.emit(
                task_id,
                "ide_request",
                actor="executor",
                summary=f"VS Code context: {method}",
                importance=0.34,
                data={
                    "requestId": request_id,
                    "method": method,
                    "params": dict(params or {}),
                },
            )
            if emitted is None:
                raise RuntimeError("ide_rpc_task_not_found")
            wait_for = max(0.25, float(timeout if timeout is not None else self.default_timeout))
            if not pending.event.wait(wait_for):
                raise TimeoutError(f"ide_rpc_timeout:{method}:{wait_for:.1f}s")
            result = dict(pending.result or {})
            if not bool(result.get("success", False)):
                raise RuntimeError(str(result.get("error", "ide_rpc_failed") or "ide_rpc_failed"))
            return {
                "success": True,
                "status": "observed",
                "message": f"VS Code trả context {method}.",
                "data": result.get("data") if isinstance(result.get("data"), dict) else {"value": result.get("data")},
            }
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def resolve(self, request_id: str, *, success: bool, data: Any = None, error: str = "") -> bool:
        request_id = str(request_id or "").strip()
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return False
            pending.result = {
                "success": bool(success),
                "data": data,
                "error": str(error or "")[:1600],
                "receivedAt": time.time(),
            }
            pending.event.set()
            return True

    def cancel_all(self, reason: str = "service_shutdown") -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.result = {"success": False, "error": str(reason or "service_shutdown")}
            item.event.set()


__all__ = ["IdeRpcBroker"]
