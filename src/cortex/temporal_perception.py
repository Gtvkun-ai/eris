# -*- coding: utf-8 -*-
"""Temporal Perception engine for the canonical V3 pipeline.

This module owns time meaning instead of scraping a couple of debug strings.
It keeps a bounded per-session trace so recurrence, rhythm, unfinished pressure,
and repetition fatigue are based on actual recent turns. No database cosplay is
required for a five-turn rhythm window.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import re
import time
from typing import Any

from runtime.canonical_cognition import TemporalFrame


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


def _fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    normalized = re.sub(r"[^\w\s]", "", normalized, flags=re.UNICODE)
    return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()[:12] if normalized else ""


class TemporalPerceptionEngine:
    module_name = "temporal_perception"

    def __init__(self, *, history_size: int = 16) -> None:
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=max(4, history_size)))

    def evaluate(self, frame: Any, *, idle_seconds: float | None = None, legacy_frame: Any = None) -> TemporalFrame:
        now = float(_get(frame, "timestamp", time.time()) or time.time())
        session_id = str(_get(frame, "session_id", "") or "default")
        text = str(_get(frame, "user_text", "") or "").strip()
        fingerprint = _fingerprint(text)
        history = self._history[session_id]

        evidence_times = []
        for ev in list(_get(frame, "evidence", []) or []):
            try:
                evidence_times.append(float(_get(ev, "timestamp", now) or now))
            except Exception:
                continue
        duration_seconds = max(0.0, now - min(evidence_times)) if evidence_times else 0.0
        idle = max(0.0, float(idle_seconds or 0.0))

        exact_repeat_count = sum(1 for item in history if fingerprint and item.get("fingerprint") == fingerprint)
        lexical_repeat = 0.0
        if text and history:
            current_tokens = set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))
            for item in list(history)[-5:]:
                previous = set(item.get("tokens") or ())
                if current_tokens and previous:
                    lexical_repeat = max(lexical_repeat, len(current_tokens & previous) / max(1, len(current_tokens | previous)))
        recurrence = _clamp(max(exact_repeat_count / 3.0, lexical_repeat))

        correction_markers = ("không phải", "ý tôi", "sai", "chưa làm", "vẫn thiếu", "not what i meant")
        escalation_markers = ("lại", "bao lần", "vẫn", "dcm", "đcm", "wtf")
        lowered = text.lower()
        corrected = any(marker in lowered for marker in correction_markers)
        escalating = corrected or (recurrence > 0.55 and any(marker in lowered for marker in escalation_markers))

        if idle >= 90:
            rhythm = "idle"
        elif escalating:
            rhythm = "escalating"
        elif recurrence >= 0.58:
            rhythm = "repetitive"
        elif len(text) >= 260 or str(_get(frame, "budget_mode", "")) == "deep":
            rhythm = "focused"
        elif history and idle >= 25:
            rhythm = "cooling"
        else:
            rhythm = "focused"

        turn_count = len(history) + 1
        recent_deep = sum(1 for item in list(history)[-5:] if item.get("deep"))
        if turn_count <= 2:
            arc = "opening"
        elif idle > 300 and turn_count > 3:
            arc = "closing"
        elif recent_deep >= 2 or len(text) > 320:
            arc = "deep_work"
        elif turn_count >= 12 and (idle > 45 or recurrence > 0.45):
            arc = "fatigue"
        else:
            arc = "building"

        unfinished = _clamp(0.75 if corrected else (0.45 if recurrence > 0.5 else 0.0))
        meaning_debt = _clamp((0.65 if corrected else 0.0) + recurrence * 0.25)
        repetition_fatigue = _clamp(recurrence * (0.55 + min(turn_count, 12) / 24.0))

        history.append({
            "timestamp": now,
            "fingerprint": fingerprint,
            "tokens": tuple(re.findall(r"\w+", lowered, flags=re.UNICODE)),
            "deep": len(text) > 260 or str(_get(frame, "budget_mode", "")) == "deep",
            "correction": corrected,
        })

        return TemporalFrame(
            recency=_clamp(1.0 - min(duration_seconds, 300.0) / 300.0),
            duration=_clamp(duration_seconds / 300.0),
            rhythm=rhythm,  # type: ignore[arg-type]
            recurrence=recurrence,
            session_arc=arc,  # type: ignore[arg-type]
            unfinished_time_pressure=unfinished,
            meaning_debt=meaning_debt,
            waiting_pressure=_clamp(idle / 600.0),
            repetition_fatigue=repetition_fatigue,
        )


__all__ = ["TemporalPerceptionEngine"]
