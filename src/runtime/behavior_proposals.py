# -*- coding: utf-8 -*-
"""Typed non-public behavior proposals.

Observer/seed/environment lanes may propose.  They never publish.  A proposal
whose kind is ``speak`` is rejected unless it is submitted by the executive
public authority.  Existing ExecutiveCortex remains the sole public governor;
this bus makes the boundary explicit for new shared-world components.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class BehaviorProposal:
    proposal_id: str
    created_at: float
    source: str
    kind: str
    subject: str
    payload: Mapping[str, Any]
    confidence: float = 0.5
    public: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "created_at": self.created_at,
            "source": self.source,
            "kind": self.kind,
            "subject": self.subject,
            "payload": dict(self.payload),
            "confidence": round(self.confidence, 3),
            "public": self.public,
        }


class ProposalBus:
    PUBLIC_AUTHORITY = "executive_governor"

    def __init__(self, *, clock: Callable[[], float] = time.time, max_items: int = 256) -> None:
        self.clock = clock
        self._items: deque[BehaviorProposal] = deque(maxlen=max(64, int(max_items)))
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        source: str,
        kind: str,
        subject: str = "",
        payload: Mapping[str, Any] | None = None,
        confidence: float = 0.5,
        public: bool = False,
    ) -> BehaviorProposal:
        normalized_source = str(source or "runtime")[:96]
        normalized_kind = str(kind or "observe")[:96]
        if public or normalized_kind == "speak":
            if normalized_source != self.PUBLIC_AUTHORITY:
                raise PermissionError("only executive_governor may submit public/speak proposals")
        proposal = BehaviorProposal(
            proposal_id=f"proposal:{uuid.uuid4().hex[:16]}",
            created_at=float(self.clock()),
            source=normalized_source,
            kind=normalized_kind,
            subject=str(subject or "")[:320],
            payload=dict(payload or {}),
            confidence=max(0.0, min(1.0, float(confidence))),
            public=bool(public),
        )
        with self._lock:
            self._items.append(proposal)
        return proposal

    def tail(self, limit: int = 32) -> tuple[BehaviorProposal, ...]:
        with self._lock:
            items = tuple(self._items)
        return items[-max(1, int(limit)) :]


def ensure_proposal_bus(host: Any) -> ProposalBus:
    existing = getattr(host, "behavior_proposal_bus", None)
    if isinstance(existing, ProposalBus):
        return existing
    bus = ProposalBus()
    try:
        setattr(host, "behavior_proposal_bus", bus)
    except Exception:
        pass
    return bus


__all__ = ["BehaviorProposal", "ProposalBus", "ensure_proposal_bus"]
