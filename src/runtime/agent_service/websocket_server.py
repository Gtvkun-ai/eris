# -*- coding: utf-8 -*-
"""Loopback WebSocket service cho Eris VS Code extension.

Security boundary: chỉ bind 127.0.0.1 và bắt buộc token handshake ở message đầu.
Webview không kết nối thẳng vào service; Node extension giữ socket và forward UI.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from runtime.agent_harness.event_bus import AgentEventBus
from runtime.agent_harness.task_store import AgentTaskStore

from .protocol import project_agent_event


def default_discovery_path() -> Path:
    explicit = str(os.getenv("ERIS_AGENT_SERVICE_DISCOVERY", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / ".eris" / "agent_service.json").resolve()


@dataclass
class _Client:
    websocket: Any
    session_id: str
    client_name: str
    capabilities: set[str] = field(default_factory=set)
    send_lock: threading.RLock = field(default_factory=threading.RLock)


class AgentWebSocketService:
    """Threaded WS gateway; callbacks giữ service độc lập khỏi RuntimeCoordinator."""

    def __init__(
        self,
        *,
        store: AgentTaskStore,
        event_bus: AgentEventBus,
        start_task: Callable[..., dict[str, Any]],
        resume_task: Callable[..., dict[str, Any]],
        control_task: Callable[..., dict[str, Any]] | None = None,
        capability_catalog: Callable[[], dict[str, Any]] | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        discovery_path: str | os.PathLike[str] | None = None,
        logger: Any = None,
    ) -> None:
        self.store = store
        self.event_bus = event_bus
        self.start_task = start_task
        self.resume_task = resume_task
        self.control_task = control_task
        self.capability_catalog = capability_catalog
        self.host = "127.0.0.1" if str(host or "").strip() not in {"127.0.0.1", "localhost", "::1"} else str(host)
        env_port = str(os.getenv("ERIS_AGENT_WS_PORT", "") or "").strip()
        self.port = int(port if port is not None else (env_port or 0))
        self.discovery_path = Path(discovery_path).expanduser().resolve() if discovery_path else default_discovery_path()
        self.logger = logger
        self.token = secrets.token_urlsafe(32)
        self._clients: dict[int, _Client] = {}
        self._clients_lock = threading.RLock()
        self._server = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        try:
            from websockets.sync.server import serve
        except Exception as exc:
            self._log("warning", "[agent-ws] websockets unavailable: %s", exc)
            return False

        ready = threading.Event()
        failure: list[Exception] = []

        def _run() -> None:
            try:
                with serve(
                    self._handle_connection,
                    self.host,
                    self.port,
                    open_timeout=5,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2 * 1024 * 1024,
                ) as server:
                    self._server = server
                    sock = getattr(server, "socket", None)
                    if sock is not None:
                        try:
                            self.port = int(sock.getsockname()[1])
                        except Exception:
                            pass
                    self._write_discovery()
                    self.event_bus.add_listener(self._on_agent_event)
                    self._running.set()
                    ready.set()
                    server.serve_forever()
            except Exception as exc:
                failure.append(exc)
                ready.set()
                self._log("warning", "[agent-ws] server failed: %s", exc)
            finally:
                self._running.clear()
                self.event_bus.remove_listener(self._on_agent_event)
                self._server = None
                self._remove_discovery_if_owned()

        self._thread = threading.Thread(target=_run, name="eris-agent-ws", daemon=True)
        self._thread.start()
        ready.wait(timeout=5.0)
        if failure or not self._running.is_set():
            return False
        self._log("info", "[agent-ws] listening ws://%s:%s token=discovery-file", self.host, self.port)
        return True

    def stop(self) -> None:
        server = self._server
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
        self._running.clear()
        self._remove_discovery_if_owned()

    @property
    def endpoint(self) -> str:
        return f"ws://{self.host}:{self.port}/agent"

    def _handle_connection(self, websocket: Any) -> None:
        client: _Client | None = None
        try:
            first = websocket.recv(timeout=8.0)
            hello = self._decode(first)
            if str(hello.get("type", "") or "") != "session.hello" or not secrets.compare_digest(
                str(hello.get("token", "") or ""), self.token
            ):
                websocket.send(json.dumps({"type": "error", "code": "auth_failed"}))
                websocket.close(code=1008, reason="auth_failed")
                return

            session_id = str(hello.get("sessionId", "") or "").strip() or f"session_{secrets.token_hex(6)}"
            caps = hello.get("capabilities") if isinstance(hello.get("capabilities"), list) else []
            client = _Client(
                websocket=websocket,
                session_id=session_id,
                client_name=str(hello.get("client", "eris-client") or "eris-client")[:120],
                capabilities={str(item).strip() for item in caps if str(item).strip()},
            )
            with self._clients_lock:
                self._clients[id(websocket)] = client
            self._send(client, {
                "type": "session.ready",
                "protocol": "eris.ide.v2",
                "sessionId": session_id,
                "endpoint": self.endpoint,
                "serverTime": time.time(),
                "capabilities": self._catalog(),
                # Client restart vẫn nhìn thấy task đang pause/interrupt nhờ projection
                # này; không cần worker cũ sống hay reconstruct UI bằng polling.
                "tasks": self.store.list_tasks(session_id=session_id, limit=24, event_limit=0),
            })
            self._replay(client, int(hello.get("lastEventSeq", 0) or 0))

            for raw in websocket:
                message = self._decode(raw)
                self._handle_message(client, message)
        except Exception as exc:
            self._log("debug", "[agent-ws] client disconnected/error: %s", exc)
        finally:
            if client is not None:
                with self._clients_lock:
                    self._clients.pop(id(client.websocket), None)

    def _handle_message(self, client: _Client, message: dict[str, Any]) -> None:
        kind = str(message.get("type", "") or "")
        if kind == "ping":
            self._send(client, {"type": "pong", "timestamp": time.time()})
            return
        if kind == "event.replay":
            self._replay(client, int(message.get("lastEventSeq", 0) or 0))
            return
        if kind == "message.user":
            content = str(message.get("content", "") or "").strip()
            if not content:
                self._send(client, {"type": "error", "code": "message_empty"})
                return
            thread_id = str(message.get("threadId", "") or "").strip() or client.session_id
            context = message.get("context") if isinstance(message.get("context"), dict) else {}
            context = dict(context)
            context["client"] = {
                "name": client.client_name,
                "sessionId": client.session_id,
                "capabilities": sorted(client.capabilities),
            }

            # Một chat thread chỉ có một task active. Tin nhắn mới trong lúc graph
            # đang chờ trở thành resume/directive thay vì tạo graph thứ hai đè lên
            # cùng checkpoint namespace. Đây là khác biệt giữa hội thoại thật và
            # một nút "run agent" khoác áo chat.
            active = self.store.latest_task_for_thread(
                thread_id,
                session_id=client.session_id,
                statuses={"queued", "running", "paused", "waiting_user", "waiting_permission"},
                event_limit=0,
            )
            if active is not None:
                task_id = str(active.get("task_id", "") or "")
                active_status = str(active.get("status", "") or "").strip().lower()
                if active_status in {"waiting_user", "waiting_permission"}:
                    result = self.resume_task(
                        task_id,
                        response={
                            "choiceId": "other",
                            "value": content,
                            "text": content,
                            "source": "vscode_chat",
                            # User có thể vừa sửa file trong lúc graph đang pause. Resume
                            # phải mang context mới, không tái dùng snapshot đã già.
                            "ideContext": context,
                        },
                        source="vscode",
                    )
                elif active_status == "paused":
                    result = self.resume_task(
                        task_id,
                        response=None,
                        source="vscode",
                        directive=content,
                        ide_context=context,
                    )
                elif callable(self.control_task):
                    result = self.control_task(
                        task_id,
                        action="directive",
                        text=content,
                        source="vscode",
                        ide_context=context,
                    )
                else:
                    result = {"status": "busy", "reason": "active_task_without_control_plane"}
                self._send(client, {
                    "type": "message.accepted",
                    "protocol": "eris.ide.v2",
                    "sessionId": client.session_id,
                    "threadId": thread_id,
                    "taskId": task_id,
                    "status": str(result.get("status", "") or ""),
                    "reason": str(result.get("reason", "") or ""),
                    "continued": True,
                })
                return

            started = self.start_task(
                content,
                thread_id=thread_id,
                session_id=client.session_id,
                task_mode=str(message.get("taskMode", "execute") or "execute"),
                workspace_ref=str(message.get("workspaceRef", "") or ""),
                ide_context=context,
                source="vscode",
            )
            self._send(client, {
                "type": "message.accepted",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "threadId": thread_id,
                "taskId": str(started.get("task_id", "") or ""),
                "status": str(started.get("status", "") or ""),
                "reason": str(started.get("reason", "") or ""),
                "continued": False,
            })
            return
        if kind == "interrupt.resolve":
            task_id = str(message.get("taskId", "") or "").strip()
            if not task_id:
                self._send(client, {"type": "error", "code": "task_id_required"})
                return
            response = message.get("response")
            resumed = self.resume_task(task_id, response=response, source="vscode")
            self._send(client, {
                "type": "interrupt.accepted",
                "protocol": "eris.ide.v2",
                "taskId": task_id,
                "status": str(resumed.get("status", "") or ""),
            })
            return
        if kind == "task.control" and callable(self.control_task):
            task_id = str(message.get("taskId", "") or "").strip()
            action = str(message.get("action", "") or "").strip().lower()
            ide_context = message.get("context") if isinstance(message.get("context"), dict) else {}
            if ide_context:
                ide_context = dict(ide_context)
                ide_context["client"] = {
                    "name": client.client_name,
                    "sessionId": client.session_id,
                    "capabilities": sorted(client.capabilities),
                }
            result = self.control_task(
                task_id,
                action=action,
                text=str(message.get("text", "") or ""),
                checkpoint_id=str(message.get("checkpointId", "") or ""),
                source="vscode",
                ide_context=ide_context,
            )
            self._send(client, {"type": "task.control.ack", "taskId": task_id, "action": action, **dict(result or {})})
            return
        self._send(client, {"type": "error", "code": "unsupported_type", "messageType": kind})

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        for packet in project_agent_event(event):
            self._broadcast(packet)

    def _replay(self, client: _Client, last_seq: int) -> None:
        events = self.store.events_since(last_seq, limit=1000)
        delivered_seq = last_seq
        for event in events:
            event_session = str(event.get("session_id", "") or "")
            # Replay phải có cùng boundary với live broadcast. Nếu không, một IDE
            # session reconnect có thể nhìn thấy task riêng của session khác.
            if event_session and event_session != client.session_id:
                continue
            delivered_seq = max(delivered_seq, int(event.get("seq", 0) or 0))
            for packet in project_agent_event(event):
                self._send(client, packet)
        self._send(client, {
            "type": "event.replay.end",
            "protocol": "eris.ide.v2",
            "lastEventSeq": delivered_seq,
        })

    def _broadcast(self, packet: dict[str, Any]) -> None:
        target_session = str(packet.get("sessionId", "") or "")
        with self._clients_lock:
            clients = list(self._clients.values())
        for client in clients:
            # Event có session_id thì chỉ trả đúng IDE session; legacy task không có
            # session vẫn broadcast để debug/migration không biến mất khỏi panel.
            if target_session and client.session_id != target_session:
                continue
            self._send(client, packet)

    def _send(self, client: _Client, payload: dict[str, Any]) -> bool:
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            with client.send_lock:
                client.websocket.send(raw)
            return True
        except Exception as exc:
            self._log("debug", "[agent-ws] send failed: %s", exc)
            return False

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(str(raw or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("invalid_ws_envelope")
        return payload

    def _catalog(self) -> dict[str, Any]:
        if callable(self.capability_catalog):
            try:
                payload = self.capability_catalog()
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        return {"brain": [], "protocol": ["message.user", "interrupt.resolve", "event.replay", "task.control"]}

    def _write_discovery(self) -> None:
        self.discovery_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "protocol": "eris.ide.v2",
            "endpoint": self.endpoint,
            "token": self.token,
            "pid": os.getpid(),
            "updatedAt": time.time(),
        }
        tmp = self.discovery_path.with_suffix(self.discovery_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.discovery_path)
        try:
            os.chmod(self.discovery_path, 0o600)
        except OSError:
            pass

    def _remove_discovery_if_owned(self) -> None:
        try:
            if not self.discovery_path.exists():
                return
            payload = json.loads(self.discovery_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and secrets.compare_digest(str(payload.get("token", "") or ""), self.token):
                self.discovery_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _log(self, level: str, message: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None)
        if callable(fn):
            fn(message, *args)


__all__ = ["AgentWebSocketService", "default_discovery_path"]
