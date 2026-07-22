# -*- coding: utf-8 -*-
"""UDP lane riêng cho Live2D, không tranh cổng 4242 với Godot."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from .stage_state import Live2DStageState


class Live2DStageReceiver:
    def __init__(
        self,
        state: Live2DStageState,
        *,
        host: str = "127.0.0.1",
        port: int = 4252,
        backend_host: str = "127.0.0.1",
        backend_port: int = 4243,
        body_host: str = "127.0.0.1",
        body_port: int = 4242,
    ) -> None:
        self.state = state
        self.host = host
        self.port = int(port)
        self.backend_target = (backend_host, int(backend_port))
        self.body_target = (body_host, int(body_port))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self.last_error = ""
        self.packet_count = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.settimeout(0.25)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ErisLive2DUDP", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                raw, _address = self._sock.recvfrom(65507)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self.last_error = str(exc)
                break
            try:
                payload: Any = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict):
                    self.state.handle_payload(payload)
                    self.packet_count += 1
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.last_error = f"invalid packet: {exc}"


    def send_context_menu_request(self, *, screen_x: int, screen_y: int) -> None:
        payload = {
            "protocol": "eris.body.control",
            "version": 1,
            "type": "open_context_menu",
            "timestamp": time.time(),
            "screen_x": int(screen_x),
            "screen_y": int(screen_y),
            "source": "live2d",
        }
        self._send_target(payload, self.body_target)

    def send_avatar_ready(self) -> None:
        payload = {
            "protocol": "eris.stage",
            "version": 2,
            "type": "avatar_ready",
            "timestamp": time.time(),
            "data": {
                "renderer": "live2d-py",
                "listen_port": self.port,
            },
        }
        self._send_backend(payload)

    def send_stage_ack(self, *, event_seq: int = 0) -> None:
        payload = {
            "protocol": "eris.stage",
            "version": 2,
            "type": "stage_ack",
            "timestamp": time.time(),
            "event_seq": int(event_seq or 0),
            "data": {"renderer": "live2d-py"},
        }
        self._send_backend(payload)

    def _send_backend(self, payload: dict[str, Any]) -> None:
        self._send_target(payload, self.backend_target)

    def _send_target(self, payload: dict[str, Any], target: tuple[str, int]) -> None:
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(raw, target)
        except OSError as exc:
            self.last_error = str(exc)

    def close(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.8)
