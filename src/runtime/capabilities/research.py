# -*- coding: utf-8 -*-
"""Data-only research capability boundary for ConversationKernel V12."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import uuid


@dataclass(frozen=True, slots=True)
class ResearchResult:
    status: str
    topic: str = ""
    summary: str = ""
    evidence_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    result_id: str = field(default_factory=lambda: f"research:{uuid.uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "topic": self.topic,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
            "result_id": self.result_id,
        }


class ResearchCapability:
    def __init__(self) -> None:
        self._last_result: ResearchResult | None = None

    def result(
        self,
        *,
        topic: str,
        summary: str = "",
        status: str = "completed",
        evidence_refs: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        result_id: str = "",
    ) -> ResearchResult:
        item = ResearchResult(
            status=str(status or "completed")[:80],
            topic=str(topic or "")[:2000],
            summary=str(summary or "")[:16000],
            evidence_refs=tuple(str(ref)[:1000] for ref in evidence_refs[:32]),
            metadata=dict(metadata or {}),
            result_id=str(result_id or "")[:180] or f"research:{uuid.uuid4().hex}",
        )
        self._last_result = item
        return item

    def snapshot(self) -> ResearchResult | None:
        return self._last_result


__all__ = ["ResearchCapability", "ResearchResult"]
