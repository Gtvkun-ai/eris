"""Episodic Memory: chuyện cụ thể đã xảy ra.

Episodic không phải semantic fact. Nó giữ cảnh, lượt, outcome, evidence và độ nổi bật.
Một câu user sửa sai hôm nay là episode. Một fact ổn định chỉ lên semantic sau khi commit phù hợp.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def compact_text(value: Any, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def atomic_write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.{int(time.time()*1000)}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)


@dataclass(slots=True)
class EpisodicMemoryItem:
    id: str
    timestamp: str
    frame_id: str = ""
    summary: str = ""
    scene: str = ""
    user_input: str = ""
    eris_action: str = ""
    outcome: str = ""
    confidence: float = 0.65
    salience: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    decay_policy: str = "normal"
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "frame_id": self.frame_id,
            "summary": self.summary,
            "scene": self.scene,
            "user_input": self.user_input,
            "eris_action": self.eris_action,
            "outcome": self.outcome,
            "confidence": round(float(self.confidence), 4),
            "salience": round(float(self.salience), 4),
            "evidence_ids": list(self.evidence_ids),
            "tags": list(self.tags),
            "decay_policy": self.decay_policy,
            "access_count": int(self.access_count),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpisodicMemoryItem":
        return cls(
            id=str(data.get("id") or f"epi_{uuid.uuid4().hex[:12]}"),
            timestamp=str(data.get("timestamp") or iso_now()),
            frame_id=str(data.get("frame_id") or ""),
            summary=compact_text(data.get("summary") or ""),
            scene=compact_text(data.get("scene") or ""),
            user_input=compact_text(data.get("user_input") or "", limit=500),
            eris_action=compact_text(data.get("eris_action") or ""),
            outcome=compact_text(data.get("outcome") or ""),
            confidence=clamp01(float(data.get("confidence", 0.65) or 0.65)),
            salience=clamp01(float(data.get("salience", 0.0) or 0.0)),
            evidence_ids=[str(item) for item in data.get("evidence_ids") or [] if str(item).strip()],
            tags=[str(item) for item in data.get("tags") or [] if str(item).strip()],
            decay_policy=str(data.get("decay_policy") or "normal"),
            access_count=int(data.get("access_count", 0) or 0),
            metadata=dict(data.get("metadata") or {}),
        )

    def recall_line(self) -> str:
        parts = [self.summary, self.outcome]
        return compact_text(" -> ".join(part for part in parts if part), limit=280)


class EpisodicMemoryStore:
    def __init__(self, path: str, *, max_items: int = 200):
        self.path = path
        self.max_items = max(20, int(max_items))

    def load(self) -> list[EpisodicMemoryItem]:
        if not os.path.isfile(self.path) or os.path.getsize(self.path) <= 0:
            return []
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        raw_items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            return []
        return [EpisodicMemoryItem.from_dict(item) for item in raw_items if isinstance(item, dict)]

    def save(self, items: list[EpisodicMemoryItem]) -> None:
        items = self._trim(items)
        atomic_write_json(self.path, {"version": 1, "items": [item.to_dict() for item in items]})

    def apply_commit(self, request: Any, *, frame: Any = None) -> EpisodicMemoryItem | None:
        content = compact_text(getattr(request, "content", "") or "", limit=600)
        if not content:
            return None
        item = EpisodicMemoryItem(
            id=f"epi_{uuid.uuid4().hex[:12]}",
            timestamp=iso_now(),
            frame_id=str(getattr(frame, "frame_id", "") or getattr(request, "frame_id", "") or ""),
            summary=content,
            scene=compact_text(getattr(request, "reason", "") or "", limit=280),
            confidence=clamp01(float(getattr(request, "confidence", 0.65) or 0.65)),
            salience=clamp01(float(getattr(request, "salience", 0.0) or 0.0)),
            evidence_ids=[str(eid) for eid in getattr(request, "evidence_ids", []) or [] if str(eid).strip()],
            tags=["commit", str(getattr(request, "target", "episodic_memory") or "episodic_memory")],
            decay_policy=str(getattr(request, "decay_policy", "normal") or "normal"),
        )
        items = self.load()
        items.append(item)
        self.save(items)
        return item

    def recall(self, query: str = "", *, limit: int = 6) -> list[EpisodicMemoryItem]:
        items = self.load()
        tokens = set(compact_text(query, limit=300).lower().split())
        if not tokens:
            return items[-limit:]
        scored: list[tuple[float, EpisodicMemoryItem]] = []
        for item in items:
            hay = f"{item.summary} {item.scene} {item.user_input} {item.outcome} {' '.join(item.tags)}".lower()
            overlap = sum(1 for token in tokens if token in hay)
            if overlap:
                score = overlap + item.salience + item.confidence * 0.2
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _trim(self, items: list[EpisodicMemoryItem]) -> list[EpisodicMemoryItem]:
        def weight(item: EpisodicMemoryItem) -> tuple[float, str]:
            decay_bonus = {"slow": 0.25, "none": 0.4, "normal": 0.0, "fast": -0.2, "session_only": -0.5}.get(item.decay_policy, 0.0)
            return (item.confidence + item.salience + decay_bonus, item.timestamp)

        items.sort(key=weight, reverse=True)
        return items[: self.max_items]
