# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from core.cognition import CognitiveEvidence, CognitiveFrame
from .normalization import compact


class CognitiveFrameBuilder:
    """Chuẩn hóa input thành một frame bất biến cho mọi specialist."""

    def build(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any] | str],
        turn_id: str,
        turn_seq: int,
        grounding_context: str = "",
        relationship_summary: str = "",
        personality_summary: str = "",
        memory_available: bool = False,
        interrupt_context: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> CognitiveFrame:
        trace_id = f"cognition:{turn_id or turn_seq}:{int(time.time() * 1000)}"
        evidence: list[CognitiveEvidence] = []
        history = list(recent_history)[-12:]
        for offset, item in enumerate(history):
            if isinstance(item, Mapping):
                role = compact(item.get("role", ""), 30).lower()
                text = compact(item.get("content", ""), 1200)
            else:
                role = "unknown"
                text = compact(item, 1200)
            if not text:
                continue
            evidence.append(
                CognitiveEvidence(
                    id=f"history:{offset}:{role or 'unknown'}",
                    source="public_history",
                    role=role,
                    text=text,
                    turn_index=offset,
                    reliability=1.0,
                    freshness=max(0.35, 1.0 - (len(history) - offset - 1) * 0.08),
                )
            )
        evidence.append(
            CognitiveEvidence(
                id="turn:user_text",
                source="user_text",
                role="user",
                text=compact(user_text, 1600),
                turn_index=len(history),
            )
        )
        if grounding_context:
            evidence.append(
                CognitiveEvidence(
                    id="runtime:grounding",
                    source="grounding",
                    text=compact(grounding_context, 1800),
                    reliability=0.95,
                )
            )
        return CognitiveFrame(
            trace_id=trace_id,
            turn_id=turn_id,
            turn_seq=max(0, int(turn_seq or 0)),
            user_text=compact(user_text, 1600),
            evidence=tuple(evidence),
            grounding_context=compact(grounding_context, 2200),
            relationship_summary=compact(relationship_summary, 800),
            personality_summary=compact(personality_summary, 1000),
            memory_available=bool(memory_available),
            interrupt_context=compact(interrupt_context, 800),
            metadata=dict(metadata or {}),
        )
