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
            "schema": "eris.autonomous.trace.v4",
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
            # Chuỗi event công khai. Chỉ ID/enum, không ghi raw prompt/private text.
            "trace_id", "stage", "owner", "candidate_source", "candidate_kind",
            "governor_action", "surface_status", "tts_event", "outcome",
            "turn_id", "generation_epoch", "claim_token", "idempotency_key",
            "anchor", "action", "candidate", "speech_intent_owner",
        }
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
            elif isinstance(value, (list, tuple)):
                clean[key] = [str(item)[:80] for item in value[:8]]
            elif isinstance(value, Mapping):
                # Chỉ giữ metadata phẳng đã allow-list; tuyệt đối không serialize
                # toàn candidate/blackboard vì trace không phải bãi rác prompt.
                clean[key] = {
                    str(k)[:48]: str(v)[:120]
                    for k, v in list(value.items())[:12]
                    if isinstance(v, (str, int, float, bool)) or v is None
                }
        return clean


_GLOBAL_TRACE_STORE: AutonomousTraceStore | None = None
_GLOBAL_TRACE_LOCK = threading.RLock()


def autonomous_trace_store(*, logger: Any | None = None) -> AutonomousTraceStore:
    """Một store dùng chung để mọi stage ghi cùng trace_id."""
    global _GLOBAL_TRACE_STORE
    with _GLOBAL_TRACE_LOCK:
        if _GLOBAL_TRACE_STORE is None:
            _GLOBAL_TRACE_STORE = AutonomousTraceStore(logger=logger)
        elif logger is not None and _GLOBAL_TRACE_STORE.logger is None:
            _GLOBAL_TRACE_STORE.logger = logger
        return _GLOBAL_TRACE_STORE


def append_autonomous_trace(event: str, payload: Mapping[str, Any] | None = None, *, logger: Any | None = None) -> None:
    try:
        from runtime.architecture_flags import event_trace_enabled
        if not event_trace_enabled():
            return
    except Exception:
        pass
    autonomous_trace_store(logger=logger).append(event, payload)


__all__ = ["AutonomousTraceStore", "autonomous_trace_store", "append_autonomous_trace"]
