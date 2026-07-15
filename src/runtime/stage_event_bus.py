# -*- coding: utf-8 -*-
"""stage_event_bus.py — cầu gửi/nhận event protocol qua transport hiện có."""

from __future__ import annotations

import os
from collections import deque
from typing import Any, Mapping

from runtime.stage_protocol import StageInboundEvent, StageProtocolEvent


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

    def emit(self, event: StageProtocolEvent) -> bool:
        if not stage_protocol_enabled():
            return False
        payload = event.to_payload()
        self.recent_outbound.append(payload)
        try:
            self.transport.send_json(payload)
            return True
        except Exception as exc:
            if self.logger is not None:
                try:
                    self.logger.debug("[stage-protocol] send failed: %s", exc)
                except Exception:
                    pass
            return False

    def remember_inbound(self, payload: Mapping[str, Any]) -> StageInboundEvent:
        event = StageInboundEvent.from_payload(payload)
        self.recent_inbound.append(event.to_meta())
        return event


__all__ = ["StageEventBus", "stage_protocol_enabled"]
