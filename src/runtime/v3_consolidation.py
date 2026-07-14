# -*- coding: utf-8 -*-
"""Bridge từ canonical V3 frame sang DaydreamConsolidation production."""

from __future__ import annotations

import hashlib
from typing import Any

from cortex.daydream_consolidation import DaydreamPacket
from .social_outcome_appraisal import social_score


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _evidence_ids(frame: Any) -> tuple[str, ...]:
    ids = []
    for item in (_get(frame, "evidence", []) or []):
        value = _get(item, "id", _get(item, "evidence_id", ""))
        if value:
            ids.append(str(value))
    return tuple(dict.fromkeys(ids))[:12]


def build_v3_daydream_packets(frame: Any, *, limit: int = 12) -> tuple[DaydreamPacket, ...]:
    if frame is None:
        return ()
    frame_id = str(_get(frame, "frame_id", "v3") or "v3")
    base_evidence = _evidence_ids(frame)
    packets: list[DaydreamPacket] = []
    seen: set[str] = set()

    def add(kind: str, text: Any, evidence_ids=(), confidence: float = 0.55, importance: float = 0.55, metadata=None) -> None:
        value = " ".join(str(text or "").split()).strip()
        evidence = tuple(str(x) for x in (evidence_ids or base_evidence) if str(x).strip())[:12]
        if not value or not evidence or value in seen or len(packets) >= limit:
            return
        seen.add(value)
        digest = hashlib.sha1(f"{frame_id}:{kind}:{value}".encode("utf-8")).hexdigest()[:12]
        packets.append(DaydreamPacket(
            id=f"v3:{kind}:{digest}",
            kind=kind,  # type: ignore[arg-type]
            text=value[:1000],
            evidence_ids=evidence,
            confidence=confidence,
            importance=importance,
            metadata={"source": "v3_cognitive_frame", "frame_id": frame_id, **dict(metadata or {})},
        ))

    memory = _get(frame, "memory_packet", None)
    for text in (_get(memory, "semantic", []) or [])[:4]:
        add("semantic", text, confidence=0.62, importance=0.60)
    for text in (_get(memory, "episodic", []) or [])[:3]:
        add("episodic", text, confidence=0.58, importance=0.55)
    for text in (_get(memory, "relational", []) or [])[:2]:
        add("relational", text, confidence=0.58, importance=0.62)

    belief = _get(frame, "belief", None)
    for item in (_get(belief, "candidate_beliefs", []) or [])[:4]:
        add(
            "semantic",
            _get(item, "claim", ""),
            evidence_ids=_get(item, "source_ids", ()) or base_evidence,
            confidence=min(0.72, float(_get(item, "confidence", 0.55) or 0.55)),
            importance=0.60,
            metadata={"belief_status": str(_get(item, "status", "tentative") or "tentative")},
        )
    for question in (_get(belief, "open_questions", []) or [])[:3]:
        add("unresolved", question, confidence=0.52, importance=0.68)

    observation = _get(frame, "self_observation", None)
    for adjustment in (_get(observation, "next_time_adjustment", []) or [])[:4]:
        add("repair", adjustment, confidence=0.72, importance=0.80)

    outcome = _get(frame, "outcome", None)
    correction = str(_get(outcome, "correction_excerpt", _get(outcome, "correction_text", "")) or "").strip()
    correction_pressure = social_score(outcome, "correction_pressure")
    if correction and correction_pressure >= 0.52:
        add(
            "repair",
            correction,
            confidence=min(0.84, 0.48 + correction_pressure * 0.36),
            importance=0.70 + correction_pressure * 0.20,
            metadata={"correction_pressure": round(correction_pressure, 4), "social_claim": "unconfirmed"},
        )

    return tuple(packets[:limit])


__all__ = ["build_v3_daydream_packets"]
