"""Eris Cline Bridge Client

Python client gọi cline-bridge HTTP server.
Eris Brain dùng class này để delegate CodingTask sang Cline SDK,
thay vì tự chạy graph_builder.py agent loop.

Phase A: shadow mode — chạy song song với agent loop cũ để so sánh.
Phase C+: replace agent loop hoàn toàn.

Usage:
    bridge = ClineBridgeClient()
    if bridge.is_available():
        result = await bridge.run_task_async(
            task_id="task_abc123",
            goal="fix bug X in module Y",
            workspace_path="/path/to/repo",
            task_mode="inspect",
            repo_context=repository_context.summarize(),
        )
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Event callback type: nhận Eris WS event dict
EventCallback = Callable[[dict[str, Any]], None]


class ClineBridgeClient:
    """HTTP client cho cline-bridge sidecar.

    Tự động start bridge process nếu chưa chạy.
    Thread-safe: nhiều task có thể chạy song song.
    """

    DEFAULT_PORT = 7832
    BRIDGE_READY_TIMEOUT = 30.0  # seconds

    def __init__(
        self,
        port: int | None = None,
        bridge_dir: str | None = None,
        auto_start: bool = True,
    ) -> None:
        self.port = port or int(os.environ.get("ERIS_BRIDGE_PORT", str(self.DEFAULT_PORT)))
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.token = os.environ.get("ERIS_BRIDGE_TOKEN", "")

        # Resolve cline-bridge directory
        if bridge_dir:
            self.bridge_dir = Path(bridge_dir)
        else:
            # Mặc định: <eris_root>/cline-bridge
            self_dir = Path(__file__).resolve().parents[3]  # src/runtime/agent_harness → eris root
            self.bridge_dir = self_dir / "cline-bridge"

        self._process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._available: bool | None = None  # None = chưa check

        if auto_start:
            self._ensure_started()

    # ─── Availability ──────────────────────────────────────────

    def is_available(self) -> bool:
        """Kiểm tra bridge có sẵn sàng nhận task không."""
        if self._available is True:
            return True
        try:
            response = self._get("/health", timeout=2.0)
            if response and response.get("status") == "ok":
                self._available = True
                return True
        except Exception:
            pass
        self._available = False
        return False

    # ─── Task Management ───────────────────────────────────────

    def start_task(
        self,
        *,
        task_id: str,
        goal: str,
        workspace_path: str,
        task_mode: str = "execute",
        repo_context: dict[str, Any] | None = None,
        memory_context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Gửi task sang bridge (non-blocking, trả về ngay).

        Returns:
            {"task_id": str, "status": "running"} nếu thành công
            {"status": "unavailable", "reason": str} nếu bridge không sẵn
        """
        if not self.is_available():
            return {"status": "unavailable", "reason": "bridge_not_available", "task_id": task_id}

        payload: dict[str, Any] = {
            "task_id": task_id,
            "goal": goal,
            "workspace_path": workspace_path,
            "task_mode": task_mode,
        }
        if repo_context:
            payload["repo_context"] = repo_context
        if memory_context:
            payload["memory_context"] = memory_context
        if model:
            payload["model"] = model

        try:
            result = self._post("/task", payload, timeout=10.0)
            return result or {"status": "unavailable", "reason": "empty_response", "task_id": task_id}
        except Exception as exc:
            logger.warning("[cline-bridge] start_task failed task=%s error=%s", task_id, exc)
            return {"status": "failed", "reason": str(exc), "task_id": task_id}

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Poll trạng thái task + recent events."""
        try:
            return self._get(f"/task/{task_id}", timeout=5.0)
        except Exception:
            return None

    def stop_task(self, task_id: str) -> dict[str, Any]:
        """Dừng task đang chạy."""
        try:
            result = self._post(f"/task/{task_id}/control", {"action": "stop"}, timeout=5.0)
            return result or {}
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

    def run_task_shadow(
        self,
        *,
        task_id: str,
        goal: str,
        workspace_path: str,
        task_mode: str = "execute",
        repo_context: dict[str, Any] | None = None,
        on_event: EventCallback | None = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Chạy task qua Cline bridge và poll cho đến khi xong.

        Shadow mode: dùng để so sánh với agent loop cũ.
        Blocking (chạy trong thread riêng nếu không muốn block).

        Returns CodingTaskResult dict.
        """
        start_result = self.start_task(
            task_id=task_id,
            goal=goal,
            workspace_path=workspace_path,
            task_mode=task_mode,
            repo_context=repo_context,
        )
        if start_result.get("status") not in ("running", "started"):
            return start_result

        seen_events: set[str] = set()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            status_resp = self.get_task_status(task_id)
            if not status_resp:
                continue

            # Relay new events
            if on_event:
                for event in status_resp.get("recent_events", []):
                    eid = str(event.get("eventId", ""))
                    if eid and eid not in seen_events:
                        seen_events.add(eid)
                        try:
                            on_event(event)
                        except Exception as exc:
                            logger.debug("[cline-bridge] on_event callback error: %s", exc)

            task_status = status_resp.get("status", "running")
            if task_status in ("completed", "failed", "stopped"):
                return status_resp.get("result") or status_resp

        return {"task_id": task_id, "status": "timeout", "reason": f"exceeded {timeout}s"}

    # ─── Process Management ────────────────────────────────────

    def _ensure_started(self) -> None:
        """Start cline-bridge process nếu chưa chạy và bridge_dir tồn tại."""
        if not self.bridge_dir.exists():
            logger.debug("[cline-bridge] bridge_dir not found: %s — skipping auto-start", self.bridge_dir)
            return

        dist_main = self.bridge_dir / "dist" / "bridge.js"
        if not dist_main.exists():
            logger.debug("[cline-bridge] dist/bridge.js not built yet — skipping auto-start")
            return

        # Check nếu đã có process đang nghe
        if self.is_available():
            logger.debug("[cline-bridge] already running on port %d", self.port)
            return

        with self._process_lock:
            if self._process and self._process.poll() is None:
                return  # đã start bởi thread khác

            env = {**os.environ, "ERIS_BRIDGE_PORT": str(self.port)}
            try:
                self._process = subprocess.Popen(
                    ["node", str(dist_main)],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(self.bridge_dir),
                )
                # Chờ bridge ready (đọc _bridge_ready từ stdout)
                self._wait_for_ready()
                logger.info("[cline-bridge] started pid=%d port=%d", self._process.pid, self.port)
            except FileNotFoundError:
                logger.debug("[cline-bridge] node not found — bridge unavailable")
            except Exception as exc:
                logger.debug("[cline-bridge] start failed: %s", exc)

    def _wait_for_ready(self) -> None:
        """Đọc stdout của bridge process cho đến khi thấy _bridge_ready signal."""
        if not self._process or not self._process.stdout:
            return
        deadline = time.monotonic() + self.BRIDGE_READY_TIMEOUT
        while time.monotonic() < deadline:
            line = self._process.stdout.readline()
            if not line:
                break
            try:
                data = json.loads(line.decode("utf-8", errors="replace").strip())
                if data.get("_bridge_ready"):
                    self._available = True
                    return
            except Exception:
                pass

    def stop_process(self) -> None:
        """Dừng bridge process (graceful)."""
        with self._process_lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                self._process = None
                self._available = None

    # ─── HTTP helpers ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, path: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
        import urllib.request
        url = self.base_url + path
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]

    def _post(self, path: str, body: dict[str, Any], *, timeout: float = 10.0) -> dict[str, Any] | None:
        import urllib.request
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
