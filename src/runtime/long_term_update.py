# -*- coding: utf-8 -*-
"""Canonical Dream -> Long-Term Update orchestration."""
from __future__ import annotations
from typing import Any
from memory.dream_scheduler import DreamScheduler, DreamConsolidationEngine, DreamScheduleDecision


class LongTermUpdateEngine:
    def __init__(self, *, scheduler: DreamScheduler | None = None, consolidator: DreamConsolidationEngine | None = None) -> None:
        self.scheduler = scheduler or DreamScheduler()
        self.consolidator = consolidator or DreamConsolidationEngine()

    def prepare(self, frame: Any) -> tuple[DreamScheduleDecision, list[Any]]:
        decision = self.scheduler.evaluate(frame)
        requests = self.consolidator.build_requests(frame, decision)
        metadata = getattr(frame, "metadata", None)
        if isinstance(metadata, dict):
            metadata["dream_schedule"] = decision.to_dict()
            metadata["long_term_update_requests"] = len(requests)
        existing = {
            (str(getattr(item, "target", "") or ""), repr(getattr(item, "content", None)))
            for item in list(getattr(frame, "commit_requests", []) or [])
        }
        added: list[Any] = []
        for request in requests:
            key = (str(getattr(request, "target", "") or ""), repr(getattr(request, "content", None)))
            if key in existing:
                continue
            try:
                frame.add_commit_request(request, actor="dream_consolidation")
                added.append(request)
                existing.add(key)
            except Exception:
                try:
                    frame.commit_requests.append(request)
                    added.append(request)
                    existing.add(key)
                except Exception:
                    pass
        if isinstance(metadata, dict):
            metadata["long_term_update_requests"] = len(added)
        return decision, added


__all__ = ["LongTermUpdateEngine"]
