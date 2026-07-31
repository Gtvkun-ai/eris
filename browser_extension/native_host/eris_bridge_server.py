#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ERIS Browser Bridge — Local HTTP Server.

Extension gửi POST JSON → server này → ghi browser_dom_state.json.
Không cần native messaging, không cần registry.

Chạy:
    python eris_bridge_server.py
    (hoặc ERIS tự start khi khởi động)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


PORT = 7422
OUTPUT = Path(os.environ.get("LOCALAPPDATA", "")) / "ERIS" / "browser_dom_state.json"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


class BridgeHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """CORS preflight cho extension."""
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/update":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
            if "timestamp" not in data:
                data["timestamp"] = time.time()
            atomic_write(OUTPUT, json.dumps(data, ensure_ascii=False, indent=2))
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as exc:
            self.send_response(500)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())

    def do_GET(self) -> None:
        """Health check + state read."""
        if self.path == "/health":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"service":"eris_bridge"}')
        elif self.path == "/state":
            # Trả về nội dung browser_dom_state.json để popup đọc trực tiếp
            try:
                if OUTPUT.exists():
                    content = OUTPUT.read_bytes()
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.send_response(204)  # No Content
                    self._cors()
                    self.end_headers()
            except Exception as exc:
                self.send_response(500)
                self._cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        # Chỉ log lỗi, bỏ qua 200 OK để không spam
        if args and str(args[1]) not in ("200", "204"):
            sys.stderr.write(f"[ERIS Bridge] {self.address_string()} - {format % args}\n")


def main() -> None:
    server = HTTPServer(("127.0.0.1", PORT), BridgeHandler)
    print(f"[ERIS Bridge] HTTP server ready on http://127.0.0.1:{PORT}", flush=True)
    print(f"[ERIS Bridge] Writing to: {OUTPUT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ERIS Bridge] Stopped.", flush=True)


if __name__ == "__main__":
    main()
