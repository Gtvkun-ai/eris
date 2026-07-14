# -*- coding: utf-8 -*-
"""Per-cycle liveliness tracking and observability for the autonomous loop.

Each idle cycle emits one ``DecisionRecord`` so that "alive" is measurable from
logs and regressions are diagnosable. The tracker keeps a bounded ring buffer
and computes window metrics (distinct grounded lines, grounded proportion,
sub-interval coverage, single-line repeat) over a reference window.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time

from cortex.banned_filler import normalize_banned

GROUNDED_SOURCES = frozenset(
    {"vision_fact", "memory_resonance", "thought_stream", "muse"}
)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    cycle_id: str
    emitted_kind: str = "silence"          # grounded_line | body_only | silence
    seed_source: str = "none"              # vision_fact | memory_resonance | ... | none
    seed_confidence: float = 0.0           # 0.0..1.0
    candidate_count: int = 0               # >= 0
    grounding_evidence: tuple[str, ...] = ()
    no_seed_reason: str = ""               # enum value, "" if a seed was selected
    repeat_rejection: str = ""             # reason + family/fingerprint, "" if none
    ambient_suppression: str = ""          # "cooldown=Ns" / "muse_exempt", "" if none
    text: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def is_grounded(self) -> bool:
        return self.emitted_kind == "grounded_line" and self.seed_source in GROUNDED_SOURCES


@dataclass(frozen=True, slots=True)
class LivelinessMetrics:
    total_lines: int
    grounded_lines: int
    distinct_grounded_count: int
    grounded_proportion: float
    max_subinterval_gap_sec: float
    single_line_max_repeat: int


class LivelinessTracker:
    """Bounded ring buffer of per-cycle decisions with window metrics."""

    def __init__(self, *, retention: int = 100) -> None:
        self.retention = max(1, int(retention or 100))
        self._records: deque[DecisionRecord] = deque(maxlen=self.retention)

    def record(self, rec: DecisionRecord) -> None:
        self._records.append(rec)

    def recent(self, n: int | None = None) -> tuple[DecisionRecord, ...]:
        items = tuple(self._records)
        if n is None:
            return items
        return items[-int(n):] if n > 0 else ()

    def for_cycle(self, cycle_id: str) -> tuple[DecisionRecord, ...]:
        return tuple(r for r in self._records if r.cycle_id == cycle_id)

    def window_metrics(self, *, window_sec: float = 3600.0, now: float | None = None) -> LivelinessMetrics:
        current = time.time() if now is None else now
        window = [r for r in self._records if (current - r.timestamp) <= window_sec]
        spoken = [r for r in window if r.emitted_kind == "grounded_line" and r.text.strip()]
        grounded = [r for r in spoken if r.is_grounded]

        # Distinct grounded lines by normalized text.
        distinct = {normalize_banned(r.text) for r in grounded if r.text.strip()}

        # Single-line max repeat across all spoken lines.
        counts: dict[str, int] = {}
        for r in spoken:
            key = normalize_banned(r.text)
            counts[key] = counts.get(key, 0) + 1
        single_line_max_repeat = max(counts.values()) if counts else 0

        # Max gap between consecutive grounded lines within the window.
        gap = 0.0
        grounded_sorted = sorted(grounded, key=lambda r: r.timestamp)
        if grounded_sorted:
            prev = grounded_sorted[0].timestamp
            for r in grounded_sorted[1:]:
                gap = max(gap, r.timestamp - prev)
                prev = r.timestamp

        total = len(spoken)
        proportion = (len(grounded) / total) if total else 0.0
        return LivelinessMetrics(
            total_lines=total,
            grounded_lines=len(grounded),
            distinct_grounded_count=len(distinct),
            grounded_proportion=proportion,
            max_subinterval_gap_sec=gap,
            single_line_max_repeat=single_line_max_repeat,
        )
