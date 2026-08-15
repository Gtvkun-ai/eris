# -*- coding: utf-8 -*-
"""Typed Agent Console event bus.

Events are persisted first and then mirrored over the existing Brain -> Body UDP
lane (4242).  The UI never scrapes stdout/log text; it renders these typed events.
"""
from __future__ import annotations

import json
import socket
from typing import Any

from .task_store import AgentTaskStore


class AgentEventBus:
    def __init__(
        self,
        store: AgentTaskStore | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 4242,
        logger: Any = None,
    ) -> None:
        self.store = store or AgentTaskStore()
        self.target = (host, int(port))
        self.logger = logger
        self._listeners: list[Any] = []

    def add_listener(self, callback: Any) -> None:
        if callable(callback) and callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Any) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def emit(
        self,
        task_id: str,
        event_type: str,
        *,
        actor: str = "system",
        summary: str = "",
        detail: str = "",
        step: int | None = None,
        importance: float = 0.5,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        event = self.store.append_event(
            task_id,
            event_type,
            actor=actor,
            summary=summary,
            detail=detail,
            step=step,
            importance=importance,
            data=data,
        )
        if event is None:
            return None
        task = self.store.get_task(task_id, event_limit=0) or {"task_id": task_id}
        packet = {
            "type": "agent_event",
            "parse_mode": "agent_event",
            "should_speak": False,
            "agent": {
                "version": "agent_console.v1",
                "task": task,
                "event": event,
            },
        }
        self._send(packet)
        listener_event = dict(event)
        listener_event["task_id"] = task_id
        for callback in tuple(self._listeners):
            try:
                callback(dict(listener_event))
            except Exception as exc:
                log = getattr(self.logger, "debug", None)
                if callable(log):
                    log("[agent-console] event listener failed: %s", exc)
        return event

    def send_snapshot(self, *, selected_task_id: str = "", request_id: str = "") -> None:
        packet = {
            "type": "agent_console_ack",
            "parse_mode": "agent_console_ack",
            "should_speak": False,
            "request_id": request_id,
            "status": "ok",
            "message": "Agent Console đã đồng bộ.",
            "agent_console": self.store.snapshot(selected_task_id=selected_task_id),
        }
        self._send(packet)

    def _send(self, payload: dict[str, Any]) -> bool:
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(raw) > 65507:
                raise ValueError(f"agent event payload exceeds UDP datagram limit: {len(raw)}")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(raw, self.target)
            return True
        except (OSError, TypeError, ValueError) as exc:
            log = getattr(self.logger, "debug", None)
            if callable(log):
                log("[agent-console] event send failed: %s", exc)
            return False


__all__ = ["AgentEventBus"]
