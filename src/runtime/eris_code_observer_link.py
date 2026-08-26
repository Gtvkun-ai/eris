# -*- coding: utf-8 -*-
"""Optional, read-only Eris Desktop -> Eris Code context bridge.

This bridge is intentionally tiny and disabled by default.  It never owns a
coding task, starts GitPilot, or accepts mutation/approval commands.  Eris Code
must remain fully functional when this service does not exist.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


class ErisCodeObserverLink:
    def __init__(
        self,
        context_provider: Callable[[str], dict[str, Any]],
        *,
        host: str = "127.0.0.1",
        port: int = 8767,
        logger: Any = None,
    ) -> None:
        self.context_provider = context_provider
        self.host = host
        self.port = int(port)
        self.logger = logger
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._server is not None:
            return True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ErisLink/1"

            def log_message(self, fmt: str, *args: Any) -> None:
                if owner.logger is not None:
                    debug = getattr(owner.logger, "debug", None)
                    if callable(debug):
                        debug("[eris-link] " + fmt, *args)

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send(200, {"ok": True, "protocol": "eris.link.v1"})
                    return
                if parsed.path != "/v1/context":
                    self._send(404, {"error": "not_found"})
                    return
                workspace = str(parse_qs(parsed.query).get("workspace", [""])[0] or "").strip()
                try:
                    payload = owner.context_provider(workspace)
                    self._send(200, payload)
                except Exception as exc:  # fail closed: no internal traceback/secret payload
                    self._send(500, {"protocol": "eris.link.v1", "error": type(exc).__name__})

            def do_POST(self) -> None:  # noqa: N802
                # Read-only boundary. No task control, approvals, terminal or file mutation.
                self._send(405, {"error": "read_only"})

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            if self.logger is not None:
                warn = getattr(self.logger, "warning", None)
                if callable(warn):
                    warn("[eris-link] observer bridge unavailable: %s", exc)
            self._server = None
            return False
        self._thread = threading.Thread(target=self._server.serve_forever, name="eris-code-observer-link", daemon=True)
        self._thread.start()
        if self.logger is not None:
            info = getattr(self.logger, "info", None)
            if callable(info):
                info("[eris-link] read-only observer bridge listening http://%s:%s", self.host, self.port)
        return True

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)


def build_observer_context(host: Any, workspace: str) -> dict[str, Any]:
    """Build a compact evidence packet; no coding instruction or secret config."""
    now = time.time()
    workspace_path = Path(workspace).expanduser() if workspace else None
    project = workspace_path.name if workspace_path else ""

    environment: dict[str, Any] = {}
    try:
        from runtime.environment_awareness import ensure_environment_awareness_hub
        environment = ensure_environment_awareness_hub(host).snapshot(now=now).to_dict(now=now)
    except Exception:
        environment = {}

    memory_items: list[str] = []
    if project:
        recall = getattr(getattr(host, "memory_core", None), "recall", None)
        if callable(recall):
            try:
                packet = recall(f"project {project} coding conventions recent decisions")
                for name in ("procedural", "semantic", "episodic", "repair"):
                    for item in tuple(getattr(packet, name, ()) or ()):
                        text = " ".join(str(item or "").split())
                        if text and text not in memory_items:
                            memory_items.append(text[:360])
                        if len(memory_items) >= 12:
                            break
                    if len(memory_items) >= 12:
                        break
            except Exception:
                pass

    return {
        "protocol": "eris.link.v1",
        "role": "observer",
        "project": project,
        "workspace": str(workspace_path) if workspace_path else "",
        "updated_at": now,
        "environment": environment,
        "project_memory": memory_items,
        "authority": {
            "coding_owner": False,
            "task_control": False,
            "tool_approval": False,
            "workspace_mutation": False,
        },
    }


def observer_link_enabled() -> bool:
    return str(os.environ.get("ERIS_CODE_OBSERVER_LINK_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["ErisCodeObserverLink", "build_observer_context", "observer_link_enabled"]
