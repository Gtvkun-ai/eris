# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Các hằng số và lớp dữ liệu liên quan đến action.
VALID_SYSTEM_ACTION_LIST = (
    "get_local_time",
    "get_now_playing",
    "focus_window",
    "open_url",
    "set_volume",
    "play_pause_media",
    "copy_text",
    "launch_app",
    "search_web",
    "get_weather",
)

VALID_SYSTEM_ACTIONS = set(VALID_SYSTEM_ACTION_LIST)


class ActionExecutionStatus(str, Enum):
    FAILED = "failed"
    DISPATCHED = "dispatched"
    OBSERVED = "observed"


_OBSERVED_ACTIONS = {"get_local_time", "get_now_playing", "search_web", "get_weather"}


@dataclass(slots=True)
class ActionExecutionResult:
    action_name: str
    action_input: str = ""
    success: bool = False
    message: str = ""
    data: dict[str, str] = field(default_factory=dict)
    status: ActionExecutionStatus | str = ""
    dispatched: bool = False
    observed: bool = False
    evidence: tuple[str, ...] = ()
    error_kind: str = ""

    def __post_init__(self) -> None:
        try:
            status = ActionExecutionStatus(self.status) if self.status else None
        except (ValueError, TypeError):
            status = None
        if status is None:
            if not self.success:
                status = ActionExecutionStatus.FAILED
            elif self.action_name in _OBSERVED_ACTIONS:
                status = ActionExecutionStatus.OBSERVED
            else:
                status = ActionExecutionStatus.DISPATCHED
        self.status = status
        self.dispatched = bool(self.dispatched or status in {ActionExecutionStatus.DISPATCHED, ActionExecutionStatus.OBSERVED})
        self.observed = bool(self.observed or status == ActionExecutionStatus.OBSERVED)
        if self.success and not self.evidence:
            if self.observed:
                self.evidence = (f"observer:{self.action_name}",)
            elif self.dispatched:
                self.evidence = (f"dispatch:{self.action_name}",)

    @property
    def confirmed(self) -> bool:
        return bool(self.success and self.observed)

    @property
    def public_mode(self) -> str:
        if not self.success:
            return "failed"
        return "observed_success" if self.observed else "request_sent"

    def to_public_meta(self) -> dict[str, Any]:
        return {
            "action_name": self.action_name,
            "action_input": self.action_input,
            "success": bool(self.success),
            "status": self.status.value if isinstance(self.status, ActionExecutionStatus) else str(self.status),
            "public_mode": self.public_mode,
            "dispatched": bool(self.dispatched),
            "observed": bool(self.observed),
            "evidence": list(self.evidence),
            "error_kind": self.error_kind,
        }


__all__ = [
    "ActionExecutionResult", "ActionExecutionStatus",
    "VALID_SYSTEM_ACTION_LIST", "VALID_SYSTEM_ACTIONS",
]
