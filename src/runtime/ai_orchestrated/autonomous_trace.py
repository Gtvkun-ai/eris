# -*- coding: utf-8 -*-
"""Trace JSONL nhỏ cho autonomous replay/debug.

Cố ý không ghi OCR text hay private context. Chỉ ghi semantic key, attention trigger, delta và
hash/event key để có thể replay nhịp mà không biến log thành kho rò rỉ màn hình.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from runtime.workspace_manager import default_eris_home


class AutonomousTraceStore:
    def __init__(self, *, path: Path | None = None, logger: Any | None = None) -> None:
        self.path = path or (default_eris_home() / "logs" / "autonomous_trace.jsonl")
        self.logger = logger
        self._lock = threading.RLock()

    def append(self, event: str, payload: Mapping[str, Any] | None = None, *, now: float | None = None) -> None:
        record = {
            "schema": "eris.autonomous.trace.v3",
            "at": float(time.time() if now is None else now),
            "event": str(event or "unknown")[:80],
            **self._sanitize(payload or {}),
        }
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        except Exception as exc:
            if self.logger is not None:
                try:
                    self.logger.debug("[autonomous trace] write failed: %s", exc)
                except Exception:
                    pass

    def recent(self, *, limit: int = 80) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]
        except Exception:
            return []
        output: list[dict[str, Any]] = []
        for line in lines:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                output.append(item)
        return output

    def _sanitize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "turn_seq", "semantic_signature", "turn_kind", "speech_act", "importance",
            "intrusion_risk", "confidence", "screen_delta", "activity_session_id",
            "mechanical_event_keys", "discourse_mode", "reply_expected", "initiative_reason",
            "trigger_reason", "has_public_seed", "result", "body_only", "evidence_count",
            "reason", "activity_kind", "motion_hint",
        }
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
            elif isinstance(value, (list, tuple)):
                clean[key] = [str(item)[:80] for item in value[:8]]
        return clean


__all__ = ["AutonomousTraceStore"]
