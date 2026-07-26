# -*- coding: utf-8 -*-
"""stage_event_bus.py — cầu gửi/nhận event protocol qua transport hiện có."""

from __future__ import annotations

import os
from collections import deque
from typing import Any, Mapping

from runtime.stage_protocol import StageInboundEvent, StageProtocolEvent
from runtime.stage_session_runtime import StageSessionRuntime


def stage_protocol_enabled() -> bool:
    """Bật event protocol mới mà vẫn giữ payload legacy.

    Mặc định bật vì payload mới có `type` rõ ràng; frontend cũ có thể bỏ qua.
    Nếu client cũ quá nhạy với message lạ, đặt ERIS_STAGE_PROTOCOL=0.
    """

    from runtime.runtime_settings_store import runtime_bool
    return runtime_bool("stage", "protocol_enabled", default=True)


class StageEventBus:
    """Gửi event sân khấu qua `transport.send_json`.

    Bus này cố ý mỏng: không queue retry, không block, không tự diễn giải event.
    Coordinator vẫn là nơi quyết định cancel TTS hay chạy chat cycle.
    """

    def __init__(self, *, transport: Any, logger: Any = None, max_recent: int = 60) -> None:
        self.transport = transport
        self.logger = logger
        self.recent_outbound: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_recent)))
        self.recent_inbound: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_recent)))
        self.session = StageSessionRuntime(max_replay=max(80, int(max_recent) * 3))

    def emit(self, event: StageProtocolEvent) -> bool:
        if not stage_protocol_enabled():
            return False
        prepared = self.session.prepare(event)
        payload = prepared.to_payload()
        self.recent_outbound.append(payload)
        try:
            self.transport.send_json(payload)
            self.session.record_sent(payload, success=True)
            return True
        except Exception as exc:
            self.session.record_sent(payload, success=False)
            if self.logger is not None:
                try:
                    self.logger.debug("[stage-protocol] send failed: %s", exc)
                except (AttributeError, TypeError, ValueError):
                    pass
            return False

    def remember_inbound(self, payload: Mapping[str, Any]) -> StageInboundEvent:
        event = StageInboundEvent.from_payload(payload)
        self.recent_inbound.append(event.to_meta())
        self.session.observe_inbound(payload)
        return event

    def replay_after(self, event_seq: int) -> tuple[dict[str, Any], ...]:
        """Trả replay payload cho frontend mới; không tự gửi lại qua UDP."""
        return self.session.replay_after(event_seq)

    def session_snapshot(self) -> dict[str, Any]:
        return self.session.snapshot()


__all__ = ["StageEventBus", "stage_protocol_enabled"]
