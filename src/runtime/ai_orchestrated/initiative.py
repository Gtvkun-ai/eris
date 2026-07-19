# -*- coding: utf-8 -*-
"""Ngân sách chủ động cho Architecture C.

Không quyết định Eris nói gì. Nó chỉ ngăn autonomous biến mọi curiosity thành
thông báo, đồng thời lưu lý do cho panel/debug.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from runtime.workspace_manager import default_eris_home


def _setting(name: str, default: Any) -> Any:
    try:
        from runtime.runtime_settings_store import runtime_setting
        return runtime_setting("initiative", name, default=default)
    except Exception:
        return os.getenv("ERIS_INITIATIVE_" + name.upper(), default)


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "bật", "bat"}


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return number if number == number else default


@dataclass(frozen=True, slots=True)
class InitiativeEvent:
    timestamp: float
    channel: str
    motive: str
    strategy: str
    importance: float
    topic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InitiativeState:
    version: int = 0
    events: tuple[InitiativeEvent, ...] = ()
    last_decision: Mapping[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "InitiativeState":
        data = payload or {}
        events: list[InitiativeEvent] = []
        raw = data.get("events", ())
        if isinstance(raw, (list, tuple)):
            for item in raw[-48:]:
                if not isinstance(item, Mapping):
                    continue
                events.append(
                    InitiativeEvent(
                        timestamp=max(0.0, _as_float(item.get("timestamp"), 0.0)),
                        channel=str(item.get("channel", "autonomous") or "autonomous")[:40],
                        motive=str(item.get("motive", "") or "")[:100],
                        strategy=str(item.get("strategy", "") or "")[:100],
                        importance=max(0.0, min(1.0, _as_float(item.get("importance"), 0.0))),
                        topic=str(item.get("topic", "") or "")[:260],
                    )
                )
        return cls(
            version=max(0, int(data.get("version", 0) or 0)),
            events=tuple(events),
            last_decision=dict(data.get("last_decision", {})) if isinstance(data.get("last_decision"), Mapping) else {},
            updated_at=max(0.0, _as_float(data.get("updated_at"), 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.initiative.v1",
            "version": self.version,
            "events": [item.to_dict() for item in self.events],
            "last_decision": dict(self.last_decision),
            "updated_at": self.updated_at,
        }


class InitiativeController:
    def __init__(self, *, state_path: Path | None = None, logger: Any | None = None) -> None:
        self.logger = logger
        self._path = state_path or (default_eris_home() / "state" / "initiative_state.json")
        self._lock = threading.RLock()
        self._state = self._load()

    def evaluate(
        self,
        plan: Any,
        *,
        now: float | None = None,
        user_busy: bool = False,
        seconds_since_user: float = 0.0,
    ) -> tuple[bool, str]:
        now = float(now if now is not None else time.time())
        if not _as_bool(_setting("enabled", True), True):
            return self._remember(False, "initiative_disabled", plan, now)

        importance = max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0)))
        intrusion = max(0.0, min(1.0, _as_float(getattr(plan, "intrusion_risk", 0.0), 0.0)))
        strategy = str(getattr(plan, "strategy", "") or "").strip().lower()
        motive = str(getattr(plan, "motive", "") or "").strip().lower()

        if user_busy and importance < 0.82:
            return self._remember(False, "user_busy", plan, now)
        min_user_silence = max(30.0, _as_float(_setting("minimum_user_silence_seconds", 150.0), 150.0))
        if seconds_since_user > 0.0 and seconds_since_user < min_user_silence and importance < 0.78:
            return self._remember(False, "user_recently_active", plan, now)
        if importance < intrusion + max(0.05, _as_float(_setting("importance_margin", 0.12), 0.12)):
            return self._remember(False, "intrusion_outweighs_value", plan, now)

        with self._lock:
            events = tuple(item for item in self._state.events if now - item.timestamp <= 3600.0)
        hourly_budget = max(0, int(_as_float(_setting("hourly_budget", 2), 2)))
        if hourly_budget >= 0 and len(events) >= hourly_budget:
            return self._remember(False, "hourly_budget_exhausted", plan, now)

        min_interval = max(60.0, _as_float(_setting("minimum_interval_seconds", 1200.0), 1200.0))
        if events and now - events[-1].timestamp < min_interval:
            # Discovery có thể đáng kể hơn activity update, nhưng vẫn không được
            # xuyên cooldown với một mẩu fact vụn.
            if not (strategy == "share_discovery" and importance >= 0.78):
                return self._remember(False, "minimum_interval", plan, now)

        if strategy == "update_own_activity":
            activity_interval = max(min_interval, _as_float(_setting("activity_update_cooldown_seconds", 2700.0), 2700.0))
            last_activity = next((item for item in reversed(events) if item.strategy == "update_own_activity"), None)
            if last_activity is not None and now - last_activity.timestamp < activity_interval:
                return self._remember(False, "activity_update_cooldown", plan, now)

        if motive in {"presence_ping", "status_ping", "companionship_ping"} and importance < 0.72:
            return self._remember(False, "low_value_presence_ping", plan, now)
        return self._remember(True, "allowed", plan, now)

    def record_spoken(self, plan: Any, *, now: float | None = None, channel: str = "autonomous") -> None:
        now = float(now if now is not None else time.time())
        event = InitiativeEvent(
            timestamp=now,
            channel=str(channel or "autonomous")[:40],
            motive=str(getattr(plan, "motive", "") or "")[:100],
            strategy=str(getattr(plan, "strategy", "") or "")[:100],
            importance=max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0))),
            topic=str(getattr(plan, "topic", "") or "")[:260],
        )
        with self._lock:
            events = [item for item in self._state.events if now - item.timestamp <= 24 * 3600.0]
            events.append(event)
            self._state = replace(self._state, version=self._state.version + 1, events=tuple(events[-48:]), updated_at=now)
            self._persist_locked()

    def panel_view(self, *, now: float | None = None) -> dict[str, Any]:
        now = float(now if now is not None else time.time())
        with self._lock:
            state = self._state
            recent_hour = [item for item in state.events if now - item.timestamp <= 3600.0]
            last = state.events[-1].to_dict() if state.events else {}
            return {
                "schema": "eris.initiative.v1",
                "enabled": _as_bool(_setting("enabled", True), True),
                "hourly_budget": max(0, int(_as_float(_setting("hourly_budget", 2), 2))),
                "used_last_hour": len(recent_hour),
                "minimum_interval_seconds": max(60.0, _as_float(_setting("minimum_interval_seconds", 1200.0), 1200.0)),
                "last_spoken": last,
                "last_decision": dict(state.last_decision),
                "version": state.version,
            }

    def reset(self) -> None:
        with self._lock:
            self._state = InitiativeState(version=self._state.version + 1, updated_at=time.time())
            self._persist_locked()

    def _remember(self, allowed: bool, reason: str, plan: Any, now: float) -> tuple[bool, str]:
        payload = {
            "allowed": bool(allowed),
            "reason": reason,
            "at": now,
            "motive": str(getattr(plan, "motive", "") or "")[:100],
            "strategy": str(getattr(plan, "strategy", "") or "")[:100],
            "importance": max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0))),
            "intrusion_risk": max(0.0, min(1.0, _as_float(getattr(plan, "intrusion_risk", 0.0), 0.0))),
        }
        with self._lock:
            self._state = replace(self._state, version=self._state.version + 1, last_decision=payload, updated_at=now)
            self._persist_locked()
        return allowed, reason

    def _load(self) -> InitiativeState:
        try:
            if self._path.exists():
                return InitiativeState.from_mapping(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception as exc:
            self._log("warning", "[initiative] load failed: %s", exc)
        return InitiativeState()

    def _persist_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as exc:
            self._log("warning", "[initiative] persist failed: %s", exc)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["InitiativeController", "InitiativeEvent", "InitiativeState"]
