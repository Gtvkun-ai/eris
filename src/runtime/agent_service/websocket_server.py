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
        ide_rpc: Any = None,
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
        self.ide_rpc = ide_rpc
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
        # Đánh thức mọi live IDE RPC đang chờ để shutdown không phải ngồi hết timeout.
        broker = getattr(self, "ide_rpc", None)
        cancel_all = getattr(broker, "cancel_all", None)
        if callable(cancel_all):
            try:
                cancel_all("agent_service_stopped")
            except Exception:
                pass
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
        if kind == "session.create":
            thread_id = str(message.get("threadId", "") or "").strip() or f"thread_{secrets.token_hex(8)}"
            self._send(client, {
                "type": "session.created",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "threadId": thread_id,
                "timestamp": time.time(),
            })
            return
        if kind == "task.list":
            self._send(client, {
                "type": "task.list",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "tasks": self.store.list_tasks(session_id=client.session_id, limit=50, event_limit=0),
            })
            return
        if kind == "task.get":
            task_id = str(message.get("taskId", "") or "").strip()
            task = self._task_for_client(client, task_id, event_limit=240)
            if task is None:
                self._send(client, {"type": "error", "code": "task_not_found", "taskId": task_id})
                return
            self._send(client, {
                "type": "task.detail",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "task": task,
            })
            return
        if kind == "thread.history":
            thread_id = str(message.get("threadId", "") or "").strip()
            tasks = self.store.tasks_for_thread(
                thread_id, session_id=client.session_id, limit=40, event_limit=240
            )
            packets: list[dict[str, Any]] = []
            for task in tasks:
                task_id = str(task.get("task_id", "") or "")
                task_thread = str(task.get("thread_id", "") or "")
                task_session = str(task.get("session_id", "") or "")
                for event in task.get("events", []) or []:
                    if not isinstance(event, dict):
                        continue
                    envelope = dict(event)
                    envelope["task_id"] = task_id
                    envelope["thread_id"] = task_thread
                    envelope["session_id"] = task_session
                    packets.extend(project_agent_event(envelope))
            packets.sort(key=lambda item: (float(item.get("timestamp", 0.0) or 0.0), int(item.get("seq", 0) or 0)))
            self._send(client, {
                "type": "thread.history",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "threadId": thread_id,
                "tasks": [{k: v for k, v in task.items() if k != "events"} for task in tasks],
                "events": packets[-700:],
            })
            return
        if kind == "message.user":
            content = str(message.get("content", "") or "").strip()
            if not content:
                self._send(client, {"type": "error", "code": "message_empty"})
                return
            thread_id = str(message.get("threadId", "") or "").strip() or client.session_id
            context = self._with_client_context(client, message.get("context"))
            autopilot = bool(message.get("autopilot", True))
            raw_attachments = context.get("attachments") if isinstance(context.get("attachments"), list) else []
            public_attachments = [
                {
                    "id": str(item.get("id", "") or "")[:120],
                    "kind": str(item.get("kind", "file") or "file")[:24],
                    "name": str(item.get("name", "attachment") or "attachment")[:240],
                    "mime": str(item.get("mime", "") or "")[:120],
                    "size": int(item.get("size", 0) or 0),
                    "relativePath": str(item.get("relativePath", "") or "")[:600],
                }
                for item in raw_attachments[:8] if isinstance(item, dict)
            ]

            # Một chat thread chỉ có một task active. Tin nhắn mới trong lúc graph
            # đang chờ trở thành resume/directive thay vì tạo graph thứ hai đè lên
            # cùng checkpoint namespace.
            active = self.store.latest_task_for_thread(
                thread_id,
                session_id=client.session_id,
                statuses={"queued", "running", "paused", "waiting_user", "waiting_permission"},
                event_limit=0,
            )
            if active is not None:
                task_id = str(active.get("task_id", "") or "")
                active_status = str(active.get("status", "") or "").strip().lower()
                self.event_bus.emit(
                    task_id,
                    "user_message",
                    actor="user",
                    summary=content[:1200],
                    importance=0.72,
                    data={"content": content[:8000], "source": "vscode", "attachments": public_attachments},
                )
                if active_status in {"waiting_user", "waiting_permission"}:
                    result = self.resume_task(
                        task_id,
                        response={
                            "choiceId": "other",
                            "value": content,
                            "text": content,
                            "source": "vscode_chat",
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
                    # control_agent_task tự phân biệt worker đang sống hay task running
                    # mồ côi sau restart; trường hợp sau sẽ recover LangGraph checkpoint.
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
                autopilot=autopilot,
                workspace_ref=str(message.get("workspaceRef", "") or ""),
                model=str(context.get("webaiModel", "") or context.get("model", "") or ""),
                ide_context=context,
                source="vscode",
            )
            task_id = str(started.get("task_id", "") or "")
            # start_task reserve task đồng bộ trước khi worker chạy; nếu backend cũ
            # chưa tự ghi user_message thì gateway ghi để history vẫn đầy đủ.
            if task_id:
                recent = self.store.get_task(task_id, event_limit=8) or {}
                has_user = any(str(item.get("type", "") or "") == "user_message" for item in recent.get("events", []) or [])
                if not has_user:
                    self.event_bus.emit(
                        task_id, "user_message", actor="user", summary=content[:1200], importance=0.72,
                        data={"content": content[:8000], "source": "vscode", "attachments": public_attachments},
                    )
            self._send(client, {
                "type": "message.accepted",
                "protocol": "eris.ide.v2",
                "sessionId": client.session_id,
                "threadId": thread_id,
                "taskId": task_id,
                "status": str(started.get("status", "") or ""),
                "reason": str(started.get("reason", "") or ""),
                "continued": False,
            })
            return
        if kind == "interrupt.resolve":
            task_id = str(message.get("taskId", "") or "").strip()
            task = self._task_for_client(client, task_id, event_limit=0)
            if task is None:
                self._send(client, {"type": "error", "code": "task_not_found", "taskId": task_id})
                return
            response = message.get("response")
            if isinstance(response, dict):
                response = dict(response)
                ide_context = response.get("ideContext")
                if isinstance(ide_context, dict):
                    response["ideContext"] = self._with_client_context(client, ide_context)
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
            if self._task_for_client(client, task_id, event_limit=0) is None:
                self._send(client, {"type": "error", "code": "task_not_found", "taskId": task_id})
                return
            action = str(message.get("action", "") or "").strip().lower()
            ide_context = self._with_client_context(client, message.get("context"))
            result = self.control_task(
                task_id,
                action=action,
                text=str(message.get("text", "") or ""),
                checkpoint_id=str(message.get("checkpointId", "") or ""),
                change_set_id=str(message.get("changeSetId", "") or ""),
                source="vscode",
                ide_context=ide_context,
            )
            self._send(client, {"type": "task.control.ack", "taskId": task_id, "action": action, **dict(result or {})})
            return
        if kind == "editor.command.result":
            task_id = str(message.get("taskId", "") or "").strip()
            if self._task_for_client(client, task_id, event_limit=0) is None:
                return
            success = bool(message.get("success", False))
            command = str(message.get("command", "") or "")
            self.event_bus.emit(
                task_id,
                "editor_result",
                actor="vscode",
                summary=(f"VS Code đã thực hiện {command}." if success else f"VS Code không thực hiện được {command}."),
                importance=0.38 if success else 0.72,
                data={
                    "requestId": str(message.get("requestId", "") or ""),
                    "command": command,
                    "success": success,
                    "message": str(message.get("message", "") or "")[:1200],
                },
            )
            return
        if kind == "ide.response":
            task_id = str(message.get("taskId", "") or "").strip()
            if self._task_for_client(client, task_id, event_limit=0) is None:
                return
            request_id = str(message.get("requestId", "") or "").strip()
            success = bool(message.get("success", False))
            broker = self.ide_rpc
            resolved = bool(
                broker is not None
                and callable(getattr(broker, "resolve", None))
                and broker.resolve(
                    request_id,
                    success=success,
                    data=message.get("data"),
                    error=str(message.get("error", "") or ""),
                )
            )
            if resolved:
                self.event_bus.emit(
                    task_id,
                    "ide_response",
                    actor="vscode",
                    summary=("VS Code đã trả semantic context." if success else "VS Code không trả được semantic context."),
                    importance=0.24 if success else 0.62,
                    data={
                        "requestId": request_id,
                        "method": str(message.get("method", "") or "")[:120],
                        "success": success,
                    },
                )
            return
        if kind == "editor.document.saved":
            path_str = str(message.get("path", "") or "").strip()
            content = str(message.get("content", "") or "")
            if path_str and content:
                def _update_index() -> None:
                    try:
                        from runtime.agent_harness.semantic_indexer import SemanticIndexer
                        from pathlib import Path
                        workspace_root = Path(path_str).parent
                        while workspace_root.parent != workspace_root:
                            if (workspace_root / ".git").exists() or (workspace_root / ".eris").exists() or (workspace_root / "package.json").exists():
                                break
                            workspace_root = workspace_root.parent
                        
                        indexer = SemanticIndexer(str(workspace_root))
                        try:
                            rel = Path(path_str).relative_to(workspace_root)
                            indexer.update_file(str(rel).replace("\\", "/"), content)
                        except ValueError:
                            pass
                    except Exception as e:
                        self._log("warning", "[agent-ws] Lỗi khi update semantic index: %s", e)
                threading.Thread(target=_update_index, daemon=True).start()
            return

        self._send(client, {"type": "error", "code": "unsupported_type", "messageType": kind})

    def _with_client_context(self, client: _Client, raw: Any) -> dict[str, Any]:
        context = dict(raw) if isinstance(raw, dict) else {}
        context["client"] = {
            "name": client.client_name,
            "sessionId": client.session_id,
            "capabilities": sorted(client.capabilities),
        }
        return context

    def _task_for_client(self, client: _Client, task_id: str, *, event_limit: int = 0) -> dict[str, Any] | None:
        """Enforce session boundary cho read/control, không chỉ cho broadcast/replay."""
        task_id = str(task_id or "").strip()
        if not task_id:
            return None
        task = self.store.get_task(task_id, event_limit=event_limit)
        if task is None:
            return None
        owner = str(task.get("session_id", "") or "")
        if owner and owner != client.session_id:
            return None
        return task

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        for packet in project_agent_event(event):
            self._broadcast(packet)

    def _replay(self, client: _Client, last_seq: int) -> None:
        # Cursor phải tiến qua *mọi* event đã scan, kể cả event thuộc session khác.
        # Nếu chỉ tăng khi event được gửi, 1000 event của session B có thể làm
        # session A reconnect mãi ở cùng một cửa sổ và không bao giờ tới event mới.
        cursor = max(0, int(last_seq or 0))
        scanned = 0
        while scanned < 10_000:
            events = self.store.events_since(cursor, limit=1000)
            if not events:
                break
            for event in events:
                cursor = max(cursor, int(event.get("seq", 0) or 0))
                event_session = str(event.get("session_id", "") or "")
                # Replay có cùng session boundary với live broadcast. Legacy task
                # chưa có session_id vẫn được thấy để migration không mất dữ liệu.
                if event_session and event_session != client.session_id:
                    continue
                # RPC/editor command là request side-effect theo thời điểm thật.
                # Replay chúng sau reconnect có thể mở file lần hai hoặc trả lời một
                # requestId mà broker cũ đã chết. State/message/artifact vẫn replay.
                if str(event.get("type", "") or "") in {"ide_request", "editor_command"}:
                    continue
                for packet in project_agent_event(event):
                    self._send(client, packet)
            scanned += len(events)
            if len(events) < 1000:
                break
        self._send(client, {
            "type": "event.replay.end",
            "protocol": "eris.ide.v2",
            "seq": cursor,
            "lastEventSeq": cursor,
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
        return {
            "brain": [],
            "protocol": [
                "session.create", "message.user", "interrupt.resolve", "event.replay",
                "task.control", "task.list", "task.get", "thread.history", "editor.command.result", "ide.response",
            ],
        }

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
