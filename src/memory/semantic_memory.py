"""Semantic Memory: fact ổn định, sở thích, kiến thức đã đủ bằng chứng.

Semantic chỉ nên nhận commit có confidence và evidence đủ rõ. Không lấy một câu đùa làm chân lý,
vì hệ thống nhớ sai rất tự tin là một cảnh tượng tẻ nhạt nhưng nguy hiểm.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

SemanticDomain = Literal["user", "self", "world", "technical", "project", "relationship", "unknown"]


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def compact_text(value: Any, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def dedupe_key(text: str) -> str:
    text = compact_text(text, limit=400).lower()
    text = re.sub(r"[^0-9a-zA-Z_\u00C0-\u1EF9]+", " ", text)
    return " ".join(text.split())[:220]


def atomic_write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.{int(time.time()*1000)}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)


@dataclass(slots=True)
class SemanticMemoryItem:
    id: str
    claim: str
    domain: SemanticDomain = "unknown"
    confidence: float = 0.70
    source: str = "commit"
    evidence_ids: list[str] = field(default_factory=list)
    observations: int = 1
    status: str = "active"  # active/tentative/contradicted/rejected
    first_seen_at: str = ""
    updated_at: str = ""
    decay_policy: str = "slow"
    contradiction_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "domain": self.domain,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence_ids": list(self.evidence_ids),
            "observations": int(self.observations),
            "status": self.status,
            "first_seen_at": self.first_seen_at,
            "updated_at": self.updated_at,
            "decay_policy": self.decay_policy,
            "contradiction_ids": list(self.contradiction_ids),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticMemoryItem":
        return cls(
            id=str(data.get("id") or f"sem_{uuid.uuid4().hex[:12]}"),
            claim=compact_text(data.get("claim") or data.get("text") or "", limit=420),
            domain=str(data.get("domain") or "unknown"),  # type: ignore[arg-type]
            confidence=clamp01(float(data.get("confidence", 0.70) or 0.70)),
            source=str(data.get("source") or "commit"),
            evidence_ids=[str(item) for item in data.get("evidence_ids") or data.get("source_ids") or [] if str(item).strip()],
            observations=int(data.get("observations", 1) or 1),
            status=str(data.get("status") or "active"),
            first_seen_at=str(data.get("first_seen_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            decay_policy=str(data.get("decay_policy") or "slow"),
            contradiction_ids=[str(item) for item in data.get("contradiction_ids") or [] if str(item).strip()],
            tags=[str(item) for item in data.get("tags") or [] if str(item).strip()],
            metadata=dict(data.get("metadata") or {}),
        )

    def recall_line(self) -> str:
        return compact_text(f"{self.domain}: {self.claim} (confidence={self.confidence:.2f}, status={self.status})", limit=300)


class SemanticMemoryStore:
    def __init__(self, path: str, *, max_items: int = 300):
        self.path = path
        self.max_items = max(30, int(max_items))

    def load(self) -> list[SemanticMemoryItem]:
        if not os.path.isfile(self.path) or os.path.getsize(self.path) <= 0:
            return []
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        raw_items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            return []
        return [SemanticMemoryItem.from_dict(item) for item in raw_items if isinstance(item, dict)]

    def save(self, items: list[SemanticMemoryItem]) -> None:
        items.sort(key=lambda item: (item.status == "active", item.confidence, item.observations, item.updated_at), reverse=True)
        atomic_write_json(self.path, {"version": 1, "items": [item.to_dict() for item in items[: self.max_items]]})

    def apply_commit(self, request: Any) -> SemanticMemoryItem | None:
        claim = compact_text(getattr(request, "content", "") or "", limit=420)
        if not claim:
            return None
        now = iso_now()
        confidence = clamp01(float(getattr(request, "confidence", 0.70) or 0.70))
        evidence_ids = [str(item) for item in getattr(request, "evidence_ids", []) or [] if str(item).strip()]
        domain = self._infer_domain(claim, getattr(request, "target", ""))
        status = "active" if confidence >= 0.72 else "tentative"
        items = self.load()
        key = dedupe_key(claim)
        for item in items:
            if dedupe_key(item.claim) == key:
                item.observations += 1
                item.confidence = clamp01(max(item.confidence, confidence) + min(0.06, item.observations * 0.01))
                item.updated_at = now
                item.status = "active" if item.confidence >= 0.72 else item.status
                item.evidence_ids = list(dict.fromkeys([*item.evidence_ids, *evidence_ids]))[-10:]
                self.save(items)
                return item
        item = SemanticMemoryItem(
            id=f"sem_{uuid.uuid4().hex[:12]}",
            claim=claim,
            domain=domain,
            confidence=confidence,
            source="state_commit",
            evidence_ids=evidence_ids,
            observations=1,
            status=status,
            first_seen_at=now,
            updated_at=now,
            decay_policy=str(getattr(request, "decay_policy", "slow") or "slow"),
            tags=["commit"],
            metadata={"reason": compact_text(getattr(request, "reason", "") or "", limit=260)},
        )
        items.append(item)
        self.save(items)
        return item

    def recall(self, query: str = "", *, limit: int = 8) -> list[SemanticMemoryItem]:
        items = [item for item in self.load() if item.status in {"active", "tentative"}]
        tokens = set(dedupe_key(query).split())
        if not tokens:
            return items[:limit]
        scored: list[tuple[float, SemanticMemoryItem]] = []
        for item in items:
            hay = dedupe_key(" ".join((item.claim, item.domain, " ".join(item.tags))))
            overlap = len(tokens & set(hay.split()))
            if overlap:
                scored.append((overlap + item.confidence + min(0.2, item.observations * 0.02), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _infer_domain(self, claim: str, target: Any) -> SemanticDomain:
        lowered = claim.lower()
        if "user" in lowered or "người dùng" in lowered or "ngài" in lowered:
            return "user"
        if "eris" in lowered or "self" in lowered:
            return "self"
        if "project" in lowered or "eris" in lowered or "pipeline" in lowered:
            return "project"
        if str(target or "") == "belief_core":
            return "world"
        return "unknown"
