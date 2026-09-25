"""Fail-closed boundary for model-generated pedagogical plans."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from runtime.pedagogical_contracts import MisconceptionHypothesis, TeachingConcept, TeachingPlan


_FORBIDDEN_PLAN_KEYS = frozenset(
    {
        "assistant_reply", "chain_of_thought", "completion_claim", "cot", "public_reply",
        "public_text", "public_utterance", "reasoning", "speech_text", "utterance",
    }
)
_MAX_CONTEXT_KEYS = 16
_MAX_CONTEXT_ITEMS = 12
_MAX_CONTEXT_TEXT = 1200
_MAX_CONTEXT_DEPTH = 3


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_CONTEXT_DEPTH:
        return str(value or "")[:_MAX_CONTEXT_TEXT]
    if isinstance(value, Mapping):
        return {
            str(key)[:120]: _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:_MAX_CONTEXT_KEYS]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in value[:_MAX_CONTEXT_ITEMS]]
    if isinstance(value, str):
        return value[:_MAX_CONTEXT_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_CONTEXT_TEXT]


def _contains_forbidden_fields(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key or "").strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in _FORBIDDEN_PLAN_KEYS or _contains_forbidden_fields(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_fields(item) for item in value)
    return False


def _clean_text(value: Any, *, limit: int = 420) -> str:
    return str(value or "").strip()[:limit]


def _stable_id(prefix: str, *parts: Any) -> str:
    material = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _unique_concept_id(raw_id: Any, item: Mapping[str, Any], index: int, used: set[str]) -> str:
    candidate = _clean_text(raw_id, limit=120)
    if not candidate or candidate in used:
        candidate = _stable_id("concept", index, item.get("objective", ""), item.get("description", ""))
    while candidate in used:
        candidate = _stable_id("concept", candidate, index)
    used.add(candidate)
    return candidate


class TeachingPlanBuilder:
    """Turns one explicit structured planning result into a bounded typed plan."""

    def __init__(self, router: Any) -> None:
        self.router = router

    def build(self, request_context: Mapping[str, Any]) -> TeachingPlan | None:
        if not isinstance(request_context, Mapping) or request_context.get("explicit_plan_request") is not True:
            return None
        planner = getattr(self.router, "plan_teaching_episode", None)
        if not callable(planner):
            return None
        bounded_context = _bounded_value(request_context)
        try:
            payload = planner(request_context=bounded_context)
        except Exception:
            return None
        if not isinstance(payload, Mapping) or _contains_forbidden_fields(payload):
            return None
        return self._normalize(payload)

    @staticmethod
    def _normalize(payload: Mapping[str, Any]) -> TeachingPlan | None:
        global_goal = _clean_text(payload.get("global_goal"))
        raw_evidence = payload.get("success_evidence")
        success_evidence = tuple(
            text
            for text in (_clean_text(item, limit=240) for item in raw_evidence[:16])
            if text
        ) if isinstance(raw_evidence, (list, tuple)) else ()
        raw_concepts = payload.get("concepts")
        if not global_goal or not success_evidence or not isinstance(raw_concepts, (list, tuple)):
            return None

        prepared: list[tuple[str, str, str, tuple[str, ...]]] = []
        used_ids: set[str] = set()
        for index, raw in enumerate(raw_concepts[:8]):
            if not isinstance(raw, Mapping):
                continue
            objective = _clean_text(raw.get("objective"))
            description = _clean_text(raw.get("description"))
            if not objective or not description:
                continue
            concept_id = _unique_concept_id(raw.get("id", raw.get("concept_id", "")), raw, index, used_ids)
            raw_prerequisites = raw.get("prerequisite_ids", raw.get("prerequisites", ()))
            prerequisites = tuple(
                item
                for item in (_clean_text(value, limit=120) for value in raw_prerequisites[:16])
                if item
            ) if isinstance(raw_prerequisites, (list, tuple)) else ()
            prepared.append((concept_id, description, objective, prerequisites))
        if len(prepared) < 3:
            return None

        valid_ids = {item[0] for item in prepared}
        concepts_by_id = {
            concept_id: TeachingConcept(
                concept_id=concept_id,
                description=description,
                objective=objective,
                prerequisites=tuple(
                    prerequisite
                    for prerequisite in dict.fromkeys(prerequisites)
                    if prerequisite in valid_ids and prerequisite != concept_id
                ),
            )
            for concept_id, description, objective, prerequisites in prepared
        }
        ordered: list[TeachingConcept] = []
        resolved: set[str] = set()
        remaining = [item[0] for item in prepared]
        while remaining:
            ready = next(
                (concept_id for concept_id in remaining if set(concepts_by_id[concept_id].prerequisites) <= resolved),
                None,
            )
            if ready is None:
                return None
            ordered.append(concepts_by_id[ready])
            resolved.add(ready)
            remaining.remove(ready)

        raw_hypotheses = payload.get("misconception_hypotheses", ())
        hypotheses: list[MisconceptionHypothesis] = []
        if isinstance(raw_hypotheses, (list, tuple)):
            for index, raw in enumerate(raw_hypotheses[:16]):
                if not isinstance(raw, Mapping):
                    continue
                description = _clean_text(raw.get("description"))
                if not description:
                    continue
                concept_id = _clean_text(raw.get("concept_id"), limit=120)
                if concept_id not in valid_ids:
                    concept_id = ""
                hypothesis_id = _clean_text(raw.get("id", raw.get("hypothesis_id", "")), limit=120)
                hypotheses.append(
                    MisconceptionHypothesis(
                        hypothesis_id=hypothesis_id or _stable_id("misconception", index, description),
                        description=description,
                        concept_id=concept_id,
                        confidence=raw.get("confidence", 0.0),
                    )
                )

        edges = tuple(
            (prerequisite, concept.concept_id)
            for concept in ordered
            for prerequisite in concept.prerequisites
        )
        try:
            return TeachingPlan(
                global_goal=global_goal,
                concepts=tuple(ordered),
                prerequisite_edges=edges,
                success_evidence=success_evidence,
                misconception_hypotheses=tuple(hypotheses),
                example_policy=_clean_text(payload.get("example_policy"), limit=240) or "allowed",
            )
        except (TypeError, ValueError):
            return None


__all__ = ["TeachingPlanBuilder"]
