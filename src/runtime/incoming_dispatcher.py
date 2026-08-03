# -*- coding: utf-8 -*-
"""Table-driven inbound protocol dispatcher.

The dispatcher owns protocol mechanics only. Domain handlers remain on the
coordinator-facing mixins, preserving the public runtime API while preventing
``RuntimeCoordinator`` from becoming a 7,000-line switch statement with moods.
"""
from __future__ import annotations
from core.di import resolve_dependency

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from runtime.policy_settings import ProtocolSettings
from runtime.stage_protocol import is_stage_inbound_type
from runtime.subsystem_health import FailureKind


@dataclass(frozen=True, slots=True)
class MessageDispatchResult:
    message_type: str
    handled: bool
    reason: str = ""


class IncomingMessageDispatcher:
    def __init__(
        self,
        owner: Any,
        *,
        settings: ProtocolSettings | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.owner = owner
        self.settings = resolve_dependency(settings, ProtocolSettings.load)
        self.clock = clock or time.time
        self._handled = 0
        self._unknown = 0
        self._invalid = 0

    def dispatch(self, message: Mapping[str, Any] | Any) -> MessageDispatchResult:
        if not isinstance(message, Mapping):
            self._invalid += 1
            error = TypeError("incoming message must be a mapping")
            self._record_failure(error, reason="invalid_message_envelope")
            if self.settings.reject_non_mapping:
                return MessageDispatchResult("", False, "invalid_message_envelope")
            message = {}

        msg = dict(message)
        raw_type = str(msg.get("type", "") or "").strip()
        msg_type = raw_type[: self.settings.max_message_type_chars]
        if raw_type != msg_type:
            self._invalid += 1
            self._record_failure(ValueError("incoming message type too long"), reason="message_type_too_long")
            return MessageDispatchResult(msg_type, False, "message_type_too_long")
        if not msg_type:
            self._invalid += 1
            return MessageDispatchResult("", False, "missing_message_type")

        if self._maintenance_blocks(msg_type):
            self.owner._send_runtime_json(
                {
                    "type": "maintenance_busy",
                    "parse_mode": "maintenance_busy",
                    "should_speak": False,
                    "maintenance_busy": {"message": "Brain đang bảo trì; lượt mới chưa được nhận."},
                },
                channel="maintenance",
            )
            return self._success(msg_type, reason="maintenance_busy")

        if is_stage_inbound_type(msg_type):
            self.owner._handle_stage_inbound_event(msg)
            return self._success(msg_type, reason="stage")

        handler = self._routes().get(msg_type)
        if handler is None:
            self._unknown += 1
            logger = getattr(self.owner, "logger", None)
            method = getattr(logger, "debug", None)
            if callable(method):
                method("[incoming] ignored unknown msg_type=%s", msg_type)
            return MessageDispatchResult(msg_type, False, "unknown_message_type")

        try:
            handler(msg)
        except Exception as exc:
            self._record_failure(exc, reason=f"handler_failed:{msg_type}")
            raise
        return self._success(msg_type)

    def snapshot(self) -> dict[str, int]:
        return {"handled": self._handled, "unknown": self._unknown, "invalid": self._invalid}

    def _routes(self) -> dict[str, Callable[[dict[str, Any]], None]]:
        owner = self.owner
        return {
            "panel_state_ack": owner._handle_panel_state_ack,
            "memory_panel_request": getattr(owner, "_handle_memory_panel_request", lambda _msg: None),
            "phase7_validation_control": owner._handle_phase7_validation_control,
            "chat_start": lambda _msg: owner._enter_chat_cycle(),
            "chat": self._handle_chat,
            "force_speak": self._handle_force_speak,
            "anchor_control": owner._handle_anchor_control,
            "identity_control": getattr(owner, "_handle_identity_control", lambda _msg: None),
            "depth_control": owner._handle_depth_control,
            "settings_update": owner._handle_settings_update,
            "settings_health": lambda _msg: owner._handle_settings_health(),
            "settings_connection_test": owner._handle_settings_connection_test,
            "maintenance_catalog": owner._handle_maintenance_catalog,
            "maintenance_request": owner._handle_maintenance_request,
            "maintenance_execute": owner._handle_maintenance_request,
            "debug_command": owner._handle_debug_command,
            "chat_end": lambda _msg: owner._end_chat_cycle(),
        }

    def _handle_chat(self, msg: dict[str, Any]) -> None:
        owner = self.owner
        user_text = str(msg.get("message", "") or "").strip()
        try:
            timestamp = float(msg.get("timestamp") or self.clock())
        except (TypeError, ValueError):
            timestamp = float(self.clock())
        owner._capture_speech_interrupt_for_user(user_text, timestamp=timestamp)
        owner._supersede_tts_for_new_user_turn("user_chat_supersede")
        owner._run_chat_cycle(user_text, user_timestamp=timestamp)

    def _handle_force_speak(self, _msg: dict[str, Any]) -> None:
        self.owner._supersede_tts_for_new_user_turn("user_force_speak")
        self.owner._handle_force_speak_request()

    def _maintenance_blocks(self, msg_type: str) -> bool:
        return bool(getattr(self.owner, "_maintenance_in_progress", False)) and msg_type in {
            "chat", "chat_start", "force_speak",
        }

    def _success(self, msg_type: str, *, reason: str = "") -> MessageDispatchResult:
        self._handled += 1
        registry = getattr(self.owner, "subsystem_health_registry", None)
        if registry is not None and (self._handled == 1 or self._handled % 64 == 0):
            registry.record_success(
                "runtime.protocol.inbound",
                details={"message_type": msg_type, **self.snapshot()},
            )
        return MessageDispatchResult(msg_type, True, reason)

    def _record_failure(self, error: BaseException, *, reason: str) -> None:
        registry = getattr(self.owner, "subsystem_health_registry", None)
        if registry is not None:
            registry.record_failure(
                "runtime.protocol.inbound",
                error,
                kind=FailureKind.INVALID_EXTERNAL_DATA,
                degraded=True,
                reason=reason,
                details=self.snapshot(),
            )


__all__ = ["IncomingMessageDispatcher", "MessageDispatchResult"]
