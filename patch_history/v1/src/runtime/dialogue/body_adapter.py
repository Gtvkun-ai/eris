# -*- coding: utf-8 -*-
"""Typed Subject Core performance frame for Godot/Live2D transport."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .contracts import PerformanceIntent, SpeechChunk


@dataclass(frozen=True, slots=True)
class BodyDeliveryReceipt:
    plan_id: str
    sequence: int
    status: str
    sync_error_ms: int = 0
    evidence_refs: tuple[str, ...] = ()


class SubjectPerformanceBodyAdapter:
    PROTOCOL = "eris.subject.performance"
    SCHEMA_VERSION = 1

    def __init__(self, transport: Callable[[Mapping[str, Any]], Any]) -> None:
        self._transport = transport

    async def send_performance(
        self,
        *,
        plan_id: str,
        chunk: SpeechChunk,
        performance: PerformanceIntent,
    ) -> BodyDeliveryReceipt:
        frame = {
            "protocol": self.PROTOCOL,
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": plan_id,
            "decision_id": "",
            "delivery_id": "",
            "sequence": chunk.sequence,
            "energy": max(0.0, min(1.0, performance.energy)),
            "pace": max(0.0, min(1.0, performance.pace)),
            "vulnerability": max(0.0, min(1.0, performance.vulnerability)),
            "restraint": max(0.0, min(1.0, performance.restraint)),
            "gaze_target": performance.gaze_target,
            "body_cues": list(tuple(dict.fromkeys((*performance.body_cues, *chunk.body_cue_refs)))),
        }
        result = self._transport(frame)
        if inspect.isawaitable(result):
            result = await result
        result = dict(result or {})
        return BodyDeliveryReceipt(
            plan_id=plan_id,
            sequence=chunk.sequence,
            status=str(result.get("status") or "sent"),
            sync_error_ms=int(result.get("sync_error_ms") or 0),
            evidence_refs=tuple(str(item) for item in result.get("evidence_refs", ())),
        )
