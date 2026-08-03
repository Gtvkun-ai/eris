# -*- coding: utf-8 -*-
"""Lịch sử theo session và cooldown cho Opening Director.

Mặc định không lưu raw OCR, URL hay nội dung riêng tư. History chỉ giữ fingerprint
hành vi và outcome. Có adapter JSON tùy chọn để crash/restart không biến Eris
thành người kể đúng một câu đùa mỗi sáng rồi quên sạch vào chiều.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .opening_contracts import OPENING_HISTORY_SCHEMA, OpeningPlan, compact


def normalize_surface(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def surface_hash(text: str) -> str:
    normalized = normalize_surface(text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def semantic_overlap(left: str, right: str) -> float:
    """Fallback deterministic khi embedding backend không có trong CI."""

    a = {token for token in normalize_surface(left).split() if len(token) > 1}
    b = {token for token in normalize_surface(right).split() if len(token) > 1}
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


@dataclass(frozen=True, slots=True)
class OpeningHistoryRecord:
    session_id: str
    plan_id: str
    encounter_kind: str
    move_family: str
    beat_shape: str
    hook_source: str
    hook_subject_class: str
    surface_hash: str
    semantic_fingerprint: str
    reaction: str = "unknown"
    boundary: bool = False
    question_ignored: bool = False
    created_at: float = 0.0
    schema: str = OPENING_HISTORY_SCHEMA

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "OpeningHistoryRecord | None":
        data = payload or {}
        plan_id = compact(data.get("plan_id", ""), 120)
        if not plan_id:
            return None
        return cls(
            session_id=compact(data.get("session_id", "runtime"), 120) or "runtime",
            plan_id=plan_id,
            encounter_kind=compact(data.get("encounter_kind", "plain_return"), 64).lower(),
            move_family=compact(data.get("move_family", "simple_recognition"), 80).lower(),
            beat_shape=compact(data.get("beat_shape", "recognition"), 120).lower(),
            hook_source=compact(data.get("hook_source", "none"), 32).lower(),
            hook_subject_class=compact(data.get("hook_subject_class", "none"), 80).lower(),
            surface_hash=compact(data.get("surface_hash", ""), 100),
            semantic_fingerprint=compact(data.get("semantic_fingerprint", ""), 200).lower(),
            reaction=compact(data.get("reaction", "unknown"), 80).lower(),
            boundary=bool(data.get("boundary", False)),
            question_ignored=bool(data.get("question_ignored", False)),
            created_at=max(0.0, float(data.get("created_at", 0.0) or 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpeningHistoryStore:
    """Store nhỏ, thread-safe; persistence chỉ chứa metadata đã redaction."""

    def __init__(
        self,
        *,
        records: Sequence[Mapping[str, Any] | OpeningHistoryRecord] = (),
        path: str | Path | None = None,
        max_records: int = 120,
    ) -> None:
        self._lock = threading.RLock()
        self._path = Path(path) if path else None
        self._max_records = max(20, min(1000, int(max_records)))
        self._records: list[OpeningHistoryRecord] = []
        for raw in records:
            item = raw if isinstance(raw, OpeningHistoryRecord) else OpeningHistoryRecord.from_mapping(raw)
            if item is not None:
                self._records.append(item)
        if self._path and self._path.exists():
            self._load()
        self._records = self._records[-self._max_records :]

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, list):
            return
        loaded = [OpeningHistoryRecord.from_mapping(item) for item in data if isinstance(item, Mapping)]
        self._records = [item for item in loaded if item is not None][-self._max_records :]

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([item.to_dict() for item in self._records], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self._path)

    def snapshot(self, *, limit: int = 40) -> tuple[OpeningHistoryRecord, ...]:
        with self._lock:
            return tuple(self._records[-max(1, int(limit)) :])

    def recent_moves_payload(self) -> dict[str, list[str]]:
        records = self.snapshot(limit=40)
        return {
            "opening_move_families": [item.move_family for item in records],
            "recent_hook_sources": [item.hook_source for item in records],
            "recent_surface_hashes": [item.surface_hash for item in records if item.surface_hash],
            "recent_beat_shapes": [item.beat_shape for item in records],
        }

    def append_plan(
        self,
        plan: OpeningPlan,
        *,
        session_id: str,
        display_text: str,
        hook_subject_class: str = "none",
        reaction: str = "unknown",
        boundary: bool = False,
        question_ignored: bool = False,
        now: float | None = None,
    ) -> OpeningHistoryRecord:
        record = OpeningHistoryRecord(
            session_id=compact(session_id, 120) or "runtime",
            plan_id=plan.plan_id,
            encounter_kind=plan.encounter.kind,
            move_family=plan.comedic_move.family,
            beat_shape=plan.beat_shape,
            hook_source=plan.hook.source if plan.hook.decision == "use" else "none",
            hook_subject_class=compact(hook_subject_class, 80).lower() or "none",
            surface_hash=surface_hash(display_text),
            semantic_fingerprint=(
                f"{plan.comedic_move.family}|"
                f"{plan.hook.source if plan.hook.decision == 'use' else 'none'}|"
                f"{'question' if plan.reply_bearing else 'no_question'}|{plan.beat_shape}"
            ),
            reaction=compact(reaction, 80).lower() or "unknown",
            boundary=bool(boundary),
            question_ignored=bool(question_ignored),
            created_at=float(now if now is not None else time.time()),
        )
        with self._lock:
            # Idempotency theo plan_id giữ restart/retry không ghi đôi.
            self._records = [item for item in self._records if item.plan_id != record.plan_id]
            self._records.append(record)
            self._records = self._records[-self._max_records :]
            self._persist()
        return record

    def note_reaction(
        self,
        plan_id: str,
        *,
        reaction: str,
        boundary: bool = False,
        question_ignored: bool = False,
    ) -> bool:
        target = compact(plan_id, 120)
        with self._lock:
            changed = False
            updated: list[OpeningHistoryRecord] = []
            for item in self._records:
                if item.plan_id == target:
                    item = OpeningHistoryRecord(
                        **{
                            **item.to_dict(),
                            "reaction": compact(reaction, 80).lower() or "unknown",
                            "boundary": bool(boundary),
                            "question_ignored": bool(question_ignored),
                        }
                    )
                    changed = True
                updated.append(item)
            if changed:
                self._records = updated
                self._persist()
            return changed

    def move_on_cooldown(self, family: str, *, sessions: int) -> bool:
        if sessions <= 0:
            return False
        recent = self.snapshot(limit=sessions)
        return any(item.move_family == str(family or "").strip().lower() for item in recent)

    def beat_shape_on_cooldown(self, shape: str, *, sessions: int = 3) -> bool:
        recent = self.snapshot(limit=sessions)
        return any(item.beat_shape == str(shape or "").strip().lower() for item in recent)

    def hook_source_repeated(self, source: str, *, maximum_consecutive: int = 2) -> bool:
        source = str(source or "none").strip().lower()
        recent = self.snapshot(limit=maximum_consecutive)
        return len(recent) >= maximum_consecutive and all(item.hook_source == source for item in recent)

    def question_temporarily_blocked(self) -> bool:
        # Hai câu hỏi opening bị bỏ qua gần nhau thì khóa ba startup kế tiếp.
        recent = self.snapshot(limit=5)
        ignored_positions = [index for index, item in enumerate(recent) if item.question_ignored]
        if len(ignored_positions) < 2:
            return False
        last_two = ignored_positions[-2:]
        return last_two[-1] >= len(recent) - 4

    def exact_duplicate(self, text: str, *, sessions: int = 30) -> bool:
        digest = surface_hash(text)
        return any(item.surface_hash == digest for item in self.snapshot(limit=sessions))

    def semantic_duplicate(self, fingerprint: str, *, sessions: int = 12) -> bool:
        normalized = compact(fingerprint, 200).lower()
        return any(item.semantic_fingerprint == normalized for item in self.snapshot(limit=sessions))


__all__ = [
    "OpeningHistoryRecord",
    "OpeningHistoryStore",
    "normalize_surface",
    "semantic_overlap",
    "surface_hash",
]
