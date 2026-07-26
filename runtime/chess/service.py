# -*- coding: utf-8 -*-
"""Chess.com bridge service wired to the durable engagement runtime."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from runtime.engagements import EvidenceBinding
from runtime.subsystem_health import FailureKind, SubsystemHealthRegistry

from .contracts import BoardSnapshot, ChessObservation
from .tracker import ChessGameTracker


class ChessCompanionService:
    def __init__(
        self,
        engagement_runtime,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str = "",
        analysis_depth: int = 2,
        direct_move_rate: float = 0.18,
        max_body_bytes: int = 65536,
        logger: Any | None = None,
        health_registry: SubsystemHealthRegistry | None = None,
        clock=None,
    ) -> None:
        self.engagement_runtime = engagement_runtime
        self.host = str(host or "127.0.0.1")
        self.port = int(port)
        self.token = str(token or "")
        self.max_body_bytes = max(1024, int(max_body_bytes))
        self.logger = logger
        self.health_registry = health_registry
        self.clock = clock or time.time
        self.tracker = ChessGameTracker(depth=analysis_depth, direct_move_rate=direct_move_rate)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> "ChessCompanionService":
        with self._lock:
            if self.running:
                return self
            service = self

            class Handler(BaseHTTPRequestHandler):
                server_version = "ERISChessBridge/1.0"

                def log_message(self, fmt, *args):
                    if service.logger is not None:
                        try:
                            service.logger.debug("[chess-bridge] " + fmt, *args)
                        except (AttributeError, TypeError, ValueError, RuntimeError):
                            pass

                def _headers(self, status: int = 200):
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "https://www.chess.com")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Eris-Bridge-Token")
                    self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                    self.end_headers()

                def _json(self, payload: Mapping[str, Any], status: int = 200):
                    self._headers(status)
                    self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

                def do_OPTIONS(self):
                    self._headers(204)

                def do_GET(self):
                    if self.path.rstrip("/") in {"", "/health", "/v1/chess/health"}:
                        self._json(service.diagnostics())
                    else:
                        self._json({"ok": False, "error": "not_found"}, 404)

                def do_POST(self):
                    if self.path.rstrip("/") != "/v1/chess/snapshot":
                        self._json({"ok": False, "error": "not_found"}, 404)
                        return
                    if service.token and self.headers.get("X-Eris-Bridge-Token", "") != service.token:
                        self._json({"ok": False, "error": "unauthorized"}, 401)
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0") or 0)
                    except ValueError:
                        self._json({"ok": False, "error": "invalid_length"}, 400)
                        return
                    if length <= 0 or length > service.max_body_bytes:
                        self._json({"ok": False, "error": "body_size"}, 413)
                        return
                    try:
                        payload = json.loads(self.rfile.read(length).decode("utf-8"))
                        if not isinstance(payload, Mapping):
                            raise ValueError("payload must be an object")
                        observation = service.handle_snapshot(payload)
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        service._failure(exc, degraded=False)
                        self._json({"ok": False, "error": str(exc)[:160]}, 400)
                        return
                    except (OSError, RuntimeError, KeyError, AttributeError) as exc:
                        service._failure(exc, degraded=True)
                        self._json({"ok": False, "error": "bridge_failure"}, 500)
                        return
                    self._json({"ok": True, "observation": observation.to_event_payload()})

            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
            self.port = int(self._server.server_address[1])
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="eris-chess-bridge",
                daemon=True,
            )
            self._thread.start()
            self._success({"host": self.host, "port": self.port})
            return self

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if self.health_registry is not None:
            self.health_registry.mark_stopped("chess.bridge")

    shutdown = stop
    close = stop

    def handle_snapshot(self, payload: Mapping[str, Any]) -> ChessObservation:
        snapshot = BoardSnapshot.from_mapping(payload)
        observation = self.tracker.observe(snapshot)
        now = snapshot.captured_at or float(self.clock())
        binding = EvidenceBinding(
            app="chess.com",
            surface_key=f"chess.com:{snapshot.game_id}",
            resource_id=f"chess:{snapshot.platform}:{snapshot.game_id}",
            tags=("chess", snapshot.platform, observation.mode.value),
        )
        engagement = self.engagement_runtime.ensure_profile(
            "chess",
            objective="Đồng hành cùng người dùng trong ván cờ hiện tại",
            binding=binding,
            now=now,
            source="chess_bridge",
        )
        kind = "chess.game_started" if observation.game_started else "chess.position_changed"
        if observation.last_move_uci:
            kind = "chess.move_played"
        if observation.game_over:
            kind = "chess.game_over"
        self.engagement_runtime.emit_domain_event(
            kind,
            payload=observation.to_event_payload(),
            engagement_id=engagement.engagement_id,
            binding=binding,
            evidence_refs=(f"chesscom:{snapshot.game_id}:{snapshot.ply}",),
            now=now,
        )
        self._success({"game_id": snapshot.game_id, "mode": observation.mode.value, "event": kind})
        return observation

    def diagnostics(self) -> dict[str, Any]:
        return {
            "ok": True,
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "token_required": bool(self.token),
        }

    def _success(self, details: Mapping[str, Any]) -> None:
        if self.health_registry is not None:
            self.health_registry.record_success("chess.bridge", details=dict(details))

    def _failure(self, exc: BaseException, *, degraded: bool) -> None:
        if self.health_registry is not None:
            self.health_registry.record_failure(
                "chess.bridge",
                exc,
                kind=FailureKind.INVALID_EXTERNAL_DATA if not degraded else FailureKind.PROGRAMMER_ERROR,
                degraded=degraded,
            )
        if self.logger is not None:
            try:
                self.logger.warning("[chess-bridge] %s", exc)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass


__all__ = ["ChessCompanionService"]
