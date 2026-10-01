# -*- coding: utf-8 -*-
"""Boundary V12 cho coding/research work runtime.

Work capability có thể checkpoint, gọi tool và xin permission, nhưng kết quả chỉ
trả về RootAgent. Không method nào ở đây phát lời trực tiếp ra UI/TTS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class WorkResult:
    status: str
    summary: str = ""
    artifact_refs: tuple[str, ...] = ()
    needs_permission: bool = False
    permission_request: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "artifact_refs": list(self.artifact_refs),
            "needs_permission": self.needs_permission,
            "permission_request": dict(self.permission_request or {}),
            "metadata": dict(self.metadata or {}),
        }


class WorkCapability:
    def __init__(self, harness: Any | None, *, logger: Any = None) -> None:
        self.harness = harness
        self.logger = logger

    def snapshot(self) -> WorkResult:
        if self.harness is None:
            return WorkResult(status="unavailable")
        snapshot = getattr(self.harness, "snapshot", None)
        if not callable(snapshot):
            return WorkResult(status="ready")
        try:
            raw = snapshot()
            return WorkResult(status="ready", metadata=dict(raw) if isinstance(raw, Mapping) else {})
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[work-capability-v12] snapshot degraded: %s", exc)
            return WorkResult(status="degraded")

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["WorkCapability", "WorkResult"]
