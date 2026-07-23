# -*- coding: utf-8 -*-
"""Bounded shadow evaluation for legacy discourse/semantic classifiers.

PDF annotation, pages 12-13 and 19
----------------------------------
During migration the old deterministic specialists may run only as a shadow
observer.  They never rewrite the model-owned semantic frame or public text.
This module runs that comparison outside the public critical path, keeps only
the newest waiting task, and emits disagreement telemetry suitable for canary
analysis.
"""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _compact(value: Any) -> str:
    return str(value or "").strip().lower()


def _relation_family(value: Any) -> str:
    text = _compact(value)
    if text.startswith("continuation_") or text in {"continue_assistant_move", "clarify_assistant_statement"}:
        return "continuation"
    if "repair" in text or "feedback" in text or "criticism" in text or "challenge_assistant" in text:
        return "repair"
    if "relational" in text or "closeness" in text:
        return "relational"
    if text in {"close_topic", "topic_close"}:
        return "close"
    if text in {"new_or_direct_turn", "new_topic", "direct_turn"}:
        return "new"
    return text or "unknown"


def _act_family(value: Any) -> str:
    text = _compact(value)
    if text in {"relational_check_in", "closeness_bid", "relational_bid"}:
        return "relational"
    if text in {"greeting", "salutation"}:
        return "greeting"
    if text in {"question", "clarification_request", "challenge_relevance"}:
        return "question"
    if text in {"style_criticism", "correction_or_challenge", "repair_request"}:
        return "repair"
    if text in {"action_request", "tool_request"}:
        return "action"
    if text in {"continuation_bid", "continue"}:
        return "continuation"
    return text or "unknown"


def compare_semantic_authorities(
    primary_frame: Mapping[str, Any] | None,
    legacy_brief: Any,
) -> dict[str, Any]:
    """Compare authorities without declaring the legacy classifier correct.

    The output is telemetry, not a veto.  Family normalization avoids counting
    harmless schema-name differences as semantic failures.
    """

    frame = dict(primary_frame or {})
    legacy = (
        legacy_brief.to_dict()
        if callable(getattr(legacy_brief, "to_dict", None))
        else dict(legacy_brief or {})
    )
    primary_relation = _relation_family(frame.get("discourse_relation"))
    legacy_relation = _relation_family(legacy.get("discourse_relation"))
    primary_act = _act_family(frame.get("user_act"))
    legacy_act = _act_family(legacy.get("user_act"))
    primary_owner = _compact(frame.get("ambiguity_owner")) or "unknown"
    legacy_owner = _compact(legacy.get("ambiguity_owner")) or "unknown"

    dimensions = {
        "discourse_relation": primary_relation == legacy_relation,
        "user_act": primary_act == legacy_act,
        "ambiguity_owner": primary_owner == legacy_owner,
    }
    disagreements = tuple(name for name, agrees in dimensions.items() if not agrees)
    agreement_score = sum(1 for value in dimensions.values() if value) / max(1, len(dimensions))
    return {
        "agreement": not disagreements,
        "agreement_score": round(agreement_score, 4),
        "disagreements": disagreements,
        "primary": {
            "discourse_relation": primary_relation,
            "user_act": primary_act,
            "ambiguity_owner": primary_owner,
            "target": _compact(frame.get("target")) or "unknown",
            "tool_intent": _compact(frame.get("tool_intent")) or "none",
        },
        "legacy": {
            "discourse_relation": legacy_relation,
            "user_act": legacy_act,
            "ambiguity_owner": legacy_owner,
            "needs_deep_inference": bool(legacy.get("needs_deep_inference", False)),
            "conflicts": tuple(legacy.get("conflicts", ()) or ())[:8],
        },
    }


@dataclass(slots=True)
class _ShadowTask:
    cognition: Any
    primary_frame: dict[str, Any]
    kwargs: dict[str, Any]


class SemanticShadowRunner:
    """One-worker, latest-only shadow queue.

    A burst of chat turns may not create an unbounded pile of regex work merely
    for telemetry.  When one task is already waiting, the newer task replaces
    it.  Humanity has invented enough queues that grow forever.
    """

    def __init__(self) -> None:
        self.enabled = _env_bool("ERIS_SEMANTIC_SHADOW_ENABLED", True)
        self._queue: queue.Queue[_ShadowTask | None] = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            name="eris-semantic-shadow",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        *,
        cognition: Any,
        primary_frame: Mapping[str, Any],
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
    ) -> bool:
        if not self.enabled or cognition is None or self._closed.is_set():
            return False
        task = _ShadowTask(
            cognition=cognition,
            primary_frame=dict(primary_frame or {}),
            kwargs={
                "user_text": user_text,
                "recent_history": tuple(recent_history or ()),
                "turn_id": turn_id,
                "turn_seq": int(turn_seq),
                "grounding_context": grounding_context,
                "relationship_summary": relationship_summary,
                "personality_summary": personality_summary,
                "memory_available": bool(memory_available),
                "interrupt_context": interrupt_context,
                "metadata": dict(metadata or {}),
            },
        )
        coalesced = False
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            try:
                self._queue.get_nowait()
                coalesced = True
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(task)
            except queue.Full:
                return False
        if coalesced:
            self._metric("semantic_shadow_coalesced_total")
        self._metric("semantic_shadow_submitted_total")
        return True

    def _worker(self) -> None:
        while not self._closed.is_set():
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if task is None:
                return
            try:
                brief = task.cognition.analyze(**task.kwargs)
                comparison = compare_semantic_authorities(task.primary_frame, brief)
                self._record(comparison, task.kwargs)
            except Exception as exc:  # shadow telemetry must never affect chat
                self._metric("semantic_shadow_failed_total", reason=type(exc).__name__)

    def _record(self, comparison: Mapping[str, Any], kwargs: Mapping[str, Any]) -> None:
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            score = float(comparison.get("agreement_score", 0.0) or 0.0)
            GLOBAL_OBSERVABILITY.observe("semantic_shadow_agreement_score", score)
            GLOBAL_OBSERVABILITY.increment(
                "semantic_shadow_evaluated_total",
                tags={"agreement": str(bool(comparison.get("agreement", False))).lower()},
            )
            for dimension in tuple(comparison.get("disagreements", ()) or ()):
                GLOBAL_OBSERVABILITY.increment(
                    "semantic_shadow_disagreement_total",
                    tags={"dimension": str(dimension)},
                )
            GLOBAL_OBSERVABILITY.log(
                "semantic_shadow_comparison",
                tags={"agreement": str(bool(comparison.get("agreement", False))).lower()},
                fields={
                    "turn_seq": int(kwargs.get("turn_seq", 0) or 0),
                    "comparison": dict(comparison),
                },
            )
        except Exception:
            pass

    @staticmethod
    def _metric(name: str, *, reason: str = "") -> None:
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            tags = {"reason": reason} if reason else None
            GLOBAL_OBSERVABILITY.increment(name, tags=tags)
        except Exception:
            pass

    def shutdown(self) -> None:
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=0.5)


GLOBAL_SEMANTIC_SHADOW_RUNNER = SemanticShadowRunner()


__all__ = [
    "GLOBAL_SEMANTIC_SHADOW_RUNNER",
    "SemanticShadowRunner",
    "compare_semantic_authorities",
]
