# -*- coding: utf-8 -*-
"""Gemma Executive Cortex: one semantic authority between cognition and runtime.

DeepSeek workers expose typed affordances and own public wording. Runtime owns
availability, permission, concurrency, validation, and execution evidence.
Gemma alone chooses conversational trajectory, exact affordance IDs, semantic
capability shortlists, and exact capability IDs.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from actions.capability_registry import (
    validate_capability_arguments,
    validate_arguments_against_schema,
)

from .affordance import ExecutiveAffordance
from .executive_tools import (
    ExecutiveTool,
    build_capability_index,
    catalog_index,
    filter_executive_tools,
    retrieve_executive_tools,
    select_tools_by_id,
)

_DEFAULT_FILTER_EXECUTIVE_TOOLS = filter_executive_tools
_DEFAULT_RETRIEVE_EXECUTIVE_TOOLS = retrieve_executive_tools

_ACTIONS = {
    "silence",
    "body_only",
    "select_affordance",
    "discover_capabilities",
    "shortlist_capabilities",
    "invoke_capability",
    "speak_from_capability",
    "select_capability",
}
_EFFECTS = {"observe", "read", "write", "control", "inspect", "communicate"}
_RISKS = {"none", "low", "medium", "high"}
_REVIEW_EVENT_KINDS = {
    "user_turn",
    "affordance_changed",
    "seed_available",
    "scene_delta",
    "activity_event",
    "followup_due",
    "open_discourse",
    "discovery_ready",
    "attention_pressure",
    "structured_due",
    "force",
}


_REVIEW_CONDITION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "minimum_strength"],
    "properties": {
        "kind": {"type": "string", "enum": sorted(_REVIEW_EVENT_KINDS)},
        "minimum_strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

EXECUTIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action", "affordance_id", "semantic_target", "speech_act", "tone",
        "capability_goal", "required_effect", "maximum_risk", "capability_domain",
        "capability_ids", "capability_id", "capability_arguments", "reply_baton",
        "phase", "trajectory", "reconsider_on", "review_after_seconds", "reason",
        "confidence", "intrusion_risk",
    ],
    "properties": {
        "action": {"type": "string", "enum": sorted(_ACTIONS)},
        "affordance_id": {"type": "string"},
        "semantic_target": {"type": "string"},
        "speech_act": {"type": "string"},
        "tone": {"type": "string"},
        "capability_goal": {"type": "string"},
        "required_effect": {"type": "string", "enum": sorted(_EFFECTS | {""})},
        "maximum_risk": {"type": "string", "enum": sorted(_RISKS)},
        "capability_domain": {"type": "string"},
        "capability_ids": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "capability_id": {"type": "string"},
        "capability_arguments": {"type": "object"},
        "reply_baton": {"type": "string", "enum": ["preserve", "release_optional"]},
        "phase": {"type": "string"},
        "trajectory": {"type": "string"},
        "reconsider_on": {
            "type": "array",
            "items": _REVIEW_CONDITION_SCHEMA,
            "maxItems": 12,
        },
        "review_after_seconds": {"type": "number", "minimum": 0.0, "maximum": 3600.0},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "intrusion_risk": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _compact(value: Any, limit: int = 800) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _clean_ids(value: Any, *, limit: int = 6) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    output: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = _compact(raw, 140)
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
        if len(output) >= limit:
            break
    return tuple(output)


@dataclass(frozen=True, slots=True)
class ReviewCondition:
    kind: str
    minimum_strength: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ReviewCondition | None":
        if not isinstance(value, Mapping):
            return None
        kind = str(value.get("kind", "") or "").strip().lower()
        if kind not in _REVIEW_EVENT_KINDS:
            return None
        return cls(kind=kind, minimum_strength=_clamp01(value.get("minimum_strength", 0.0)))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "minimum_strength": self.minimum_strength}


@dataclass(frozen=True, slots=True)
class ExecutiveEvent:
    kind: str
    strength: float
    source: str
    revision: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ExecutiveEvent | None":
        if not isinstance(value, Mapping):
            return None
        kind = str(value.get("kind", "") or "").strip().lower()
        if kind not in _REVIEW_EVENT_KINDS:
            return None
        try:
            revision = max(0, int(value.get("revision", 0) or 0))
        except (TypeError, ValueError):
            revision = 0
        metadata = value.get("metadata", {})
        return cls(
            kind=kind,
            strength=_clamp01(value.get("strength", 0.0)),
            source=_compact(value.get("source", "runtime"), 120) or "runtime",
            revision=revision,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "strength": self.strength,
            "source": self.source,
            "revision": self.revision,
            "metadata": dict(self.metadata),
        }


def _clean_conditions(value: Any) -> tuple[ReviewCondition, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    output: list[ReviewCondition] = []
    seen: set[str] = set()
    for raw in value:
        if isinstance(raw, str):
            raw_kind = raw.strip().lower()
            condition = ReviewCondition(raw_kind, 0.0) if raw_kind in _REVIEW_EVENT_KINDS else None
        else:
            condition = ReviewCondition.from_mapping(raw if isinstance(raw, Mapping) else None)
        if condition is None or condition.kind in seen:
            continue
        seen.add(condition.kind)
        output.append(condition)
    return tuple(output)


_DEFAULT_REVIEW_CONDITIONS = (
    ReviewCondition("affordance_changed", 0.50),
    ReviewCondition("seed_available", 0.48),
    ReviewCondition("scene_delta", 0.55),
    ReviewCondition("activity_event", 0.55),
    ReviewCondition("followup_due", 0.75),
    ReviewCondition("open_discourse", 0.60),
    ReviewCondition("discovery_ready", 0.70),
    ReviewCondition("attention_pressure", 0.58),
    ReviewCondition("structured_due", 0.70),
    ReviewCondition("force", 0.0),
)


@dataclass(frozen=True, slots=True)
class ExecutiveState:
    revision: int = 0
    phase: str = "unresolved"
    trajectory: str = "observe_before_acting"
    reconsider_on: tuple[ReviewCondition, ...] = _DEFAULT_REVIEW_CONDITIONS
    review_due_at: float = 0.0
    preferred_lane: str = ""
    retry_not_before: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        now: float | None = None,
        maximum_age_seconds: float = 21600.0,
    ) -> "ExecutiveState":
        """Restore a runtime-clock state mapping. Legacy v1 persistence used this basis."""
        if not isinstance(value, Mapping):
            return cls()
        current = time.time() if now is None else float(now)
        try:
            updated_at = max(0.0, float(value.get("updated_at", 0.0) or 0.0))
        except (TypeError, ValueError):
            updated_at = 0.0
        if updated_at and current - updated_at > max(300.0, float(maximum_age_seconds)):
            return cls()
        try:
            revision = max(0, int(value.get("revision", 0) or 0))
        except (TypeError, ValueError):
            revision = 0
        try:
            review_due_at = max(0.0, float(value.get("review_due_at", 0.0) or 0.0))
        except (TypeError, ValueError):
            review_due_at = 0.0
        conditions = _clean_conditions(value.get("reconsider_on", ())) or _DEFAULT_REVIEW_CONDITIONS
        return cls(
            revision=revision,
            phase=_compact(value.get("phase", "unresolved"), 100).lower() or "unresolved",
            trajectory=_compact(value.get("trajectory", "observe_before_acting"), 220) or "observe_before_acting",
            reconsider_on=conditions,
            review_due_at=review_due_at,
            preferred_lane=_compact(value.get("preferred_lane", ""), 100).lower(),
            retry_not_before=0.0,
            updated_at=updated_at,
        )

    @classmethod
    def from_persisted_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        runtime_now: float,
        wall_now: float,
        maximum_age_seconds: float = 21600.0,
    ) -> "ExecutiveState":
        """Restore wall-clock persistence into the current runtime clock domain."""
        if not isinstance(value, Mapping):
            return cls()
        if str(value.get("schema", "") or "") != "eris.executive_state.v2":
            return cls.from_mapping(value, now=runtime_now, maximum_age_seconds=maximum_age_seconds)
        try:
            updated_wall = max(0.0, float(value.get("updated_at_wallclock", 0.0) or 0.0))
        except (TypeError, ValueError):
            updated_wall = 0.0
        age = max(0.0, wall_now - updated_wall) if updated_wall else 0.0
        if updated_wall and age > max(300.0, float(maximum_age_seconds)):
            return cls()
        try:
            due_wall = max(0.0, float(value.get("review_due_wallclock", 0.0) or 0.0))
        except (TypeError, ValueError):
            due_wall = 0.0
        if due_wall:
            review_due_at = runtime_now + max(0.0, due_wall - wall_now)
            if due_wall <= wall_now:
                review_due_at = runtime_now
        else:
            review_due_at = 0.0
        runtime_mapping = dict(value)
        runtime_mapping["updated_at"] = max(0.0, runtime_now - age) if updated_wall else 0.0
        runtime_mapping["review_due_at"] = review_due_at
        return cls.from_mapping(runtime_mapping, now=runtime_now, maximum_age_seconds=maximum_age_seconds)

    def to_dict(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        return {
            "revision": self.revision,
            "phase": self.phase,
            "trajectory": self.trajectory,
            "reconsider_on": [item.to_dict() for item in self.reconsider_on],
            "review_due_in_seconds": max(0.0, self.review_due_at - current) if self.review_due_at else 0.0,
            "preferred_lane": self.preferred_lane,
            "retry_in_seconds": max(0.0, self.retry_not_before - current) if self.retry_not_before else 0.0,
            "updated_at": self.updated_at,
        }

    def to_persisted_dict(self, *, runtime_now: float, wall_now: float) -> dict[str, Any]:
        review_remaining = max(0.0, self.review_due_at - runtime_now) if self.review_due_at else 0.0
        age = max(0.0, runtime_now - self.updated_at) if self.updated_at else 0.0
        return {
            "schema": "eris.executive_state.v2",
            "revision": self.revision,
            "phase": self.phase,
            "trajectory": self.trajectory,
            "reconsider_on": [item.to_dict() for item in self.reconsider_on],
            "review_due_wallclock": wall_now + review_remaining if self.review_due_at else 0.0,
            "preferred_lane": self.preferred_lane,
            "updated_at_wallclock": max(0.0, wall_now - age) if self.updated_at else 0.0,
        }


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    action: str = "unavailable"
    affordance_id: str = ""
    semantic_target: str = ""
    speech_act: str = ""
    tone: str = ""
    capability_goal: str = ""
    required_effect: str = ""
    maximum_risk: str = "low"
    capability_domain: str = ""
    capability_ids: tuple[str, ...] = ()
    capability_id: str = ""
    capability_arguments: Mapping[str, Any] = field(default_factory=dict)
    reply_baton: str = "preserve"
    phase: str = ""
    trajectory: str = ""
    reconsider_on: tuple[ReviewCondition, ...] = ()
    review_after_seconds: float = 0.0
    reason: str = "executive_unavailable"
    confidence: float = 0.0
    intrusion_risk: float = 0.0
    capability_result: Mapping[str, Any] | None = None

    @classmethod
    def parse(cls, value: Mapping[str, Any] | None) -> "ExecutiveDecision | None":
        if not isinstance(value, Mapping) or "action" not in value:
            return None
        action = str(value.get("action", "") or "").strip().lower()
        if action not in _ACTIONS:
            return None
        effect = str(value.get("required_effect", "") or "").strip().lower()
        if effect not in (_EFFECTS | {""}):
            return None
        risk = str(value.get("maximum_risk", "low") or "low").strip().lower()
        if risk not in _RISKS:
            return None
        arguments = value.get("capability_arguments", {})
        if not isinstance(arguments, Mapping):
            return None
        try:
            review_after = float(value.get("review_after_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        return cls(
            action=action,
            affordance_id=_compact(value.get("affordance_id", ""), 220),
            semantic_target=_compact(value.get("semantic_target", ""), 1600),
            speech_act=_compact(value.get("speech_act", ""), 100).lower(),
            tone=_compact(value.get("tone", ""), 100).lower(),
            capability_goal=_compact(value.get("capability_goal", ""), 800),
            required_effect=effect,
            maximum_risk=risk,
            capability_domain=_compact(value.get("capability_domain", ""), 80).lower(),
            capability_ids=_clean_ids(value.get("capability_ids", ())),
            capability_id=_compact(value.get("capability_id", ""), 140),
            capability_arguments=dict(arguments),
            reply_baton=(
                "release_optional"
                if str(value.get("reply_baton", "preserve") or "preserve").strip().lower()
                == "release_optional"
                else "preserve"
            ),
            phase=_compact(value.get("phase", ""), 100).lower(),
            trajectory=_compact(value.get("trajectory", ""), 220),
            reconsider_on=_clean_conditions(value.get("reconsider_on", ())),
            review_after_seconds=max(0.0, min(3600.0, review_after)),
            reason=_compact(value.get("reason", "executive_decision"), 360) or "executive_decision",
            confidence=_clamp01(value.get("confidence", 0.0)),
            intrusion_risk=_clamp01(value.get("intrusion_risk", 0.0)),
        )

    @classmethod
    def unavailable(cls, reason: str) -> "ExecutiveDecision":
        return cls(action="unavailable", reason=_compact(reason, 300) or "executive_unavailable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.executive_decision.v4",
            "action": self.action,
            "affordance_id": self.affordance_id,
            "semantic_target": self.semantic_target,
            "speech_act": self.speech_act,
            "tone": self.tone,
            "capability_goal": self.capability_goal,
            "required_effect": self.required_effect,
            "maximum_risk": self.maximum_risk,
            "capability_domain": self.capability_domain,
            "capability_ids": list(self.capability_ids),
            "capability_id": self.capability_id,
            "capability_arguments": dict(self.capability_arguments),
            "reply_baton": self.reply_baton,
            "phase": self.phase,
            "trajectory": self.trajectory,
            "reconsider_on": [item.to_dict() for item in self.reconsider_on],
            "review_after_seconds": self.review_after_seconds,
            "reason": self.reason,
            "confidence": self.confidence,
            "intrusion_risk": self.intrusion_risk,
            "capability_result": dict(self.capability_result or {}),
        }


@dataclass(frozen=True, slots=True)
class InteractiveExecutiveDirective:
    status: str = "none"
    capability_id: str = ""
    capability_arguments: Mapping[str, Any] = field(default_factory=dict)
    semantic_goal: str = ""
    reason: str = "no_runtime_capability_needed"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.interactive_executive_directive.v3",
            "status": self.status,
            "capability_id": self.capability_id,
            "capability_arguments": dict(self.capability_arguments),
            "semantic_goal": self.semantic_goal,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ExecutiveOutcome:
    candidate: Any | None
    selected_affordance_id: str
    action: str
    reason: str
    decision: ExecutiveDecision


def may_release_optional_reply_baton(blackboard: Any, decision: ExecutiveDecision) -> bool:
    followup_state = str(getattr(blackboard, "followup_state", "none") or "none").lower()
    return bool(
        decision.reply_baton == "release_optional"
        and bool(getattr(blackboard, "reply_expected", False))
        and not bool(getattr(blackboard, "engagement_active", False))
        and not bool(getattr(blackboard, "engagement_required", False))
        and followup_state in {"none", "waiting", "reminder_due", "abandoned"}
        and decision.confidence >= 0.60
        and decision.intrusion_risk <= 0.35
    )


class ExecutiveCortex:
    """Stateful Gemma policy layer for conversational trajectory."""

    def __init__(
        self,
        owner: Any,
        client: Any,
        *,
        invoke_structured: Any,
        logger: Any | None = None,
        initial_state: Mapping[str, Any] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.time,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.owner = owner
        self.client = client
        self.invoke_structured = invoke_structured
        self.logger = logger
        self._clock = clock
        self._wall_clock = wall_clock
        self._persist = persist
        self._state_lock = threading.RLock()
        self._state = ExecutiveState.from_persisted_mapping(
            initial_state, runtime_now=self._clock(), wall_now=self._wall_clock()
        )

    @property
    def enabled(self) -> bool:
        return bool(_flag("ERIS_EXECUTIVE_CORTEX_ENABLED", True) and self.client is not None)

    @property
    def state(self) -> ExecutiveState:
        with self._state_lock:
            return self._state

    def should_reconsider(
        self,
        events: Sequence[ExecutiveEvent | Mapping[str, Any]],
        *,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Apply Gemma policy to scored runtime facts without renaming their meaning."""
        current_time = self._clock() if now is None else float(now)
        normalized: list[ExecutiveEvent] = []
        for raw in events:
            if isinstance(raw, ExecutiveEvent):
                event = raw
            elif isinstance(raw, str):
                raw_kind = raw.strip().lower()
                event = ExecutiveEvent(raw_kind, 1.0, "runtime") if raw_kind in _REVIEW_EVENT_KINDS else None
            else:
                event = ExecutiveEvent.from_mapping(raw)
            if isinstance(event, ExecutiveEvent):
                normalized.append(event)
        if any(item.kind == "force" for item in normalized):
            return True, "executive_policy:force"
        state = self.state
        if state.retry_not_before and current_time < state.retry_not_before:
            return False, "executive_policy:failure_backoff"
        if state.review_due_at and current_time >= state.review_due_at:
            return True, "executive_policy:timer"
        if state.revision == 0:
            return (bool(normalized), "executive_policy:initial_event" if normalized else "executive_policy:no_event")
        strengths: dict[str, float] = {}
        for event in normalized:
            strengths[event.kind] = max(strengths.get(event.kind, 0.0), event.strength)
        for condition in state.reconsider_on:
            if strengths.get(condition.kind, -1.0) >= condition.minimum_strength:
                return True, f"executive_policy:{condition.kind}:{strengths[condition.kind]:.2f}"
        return False, "executive_policy:waiting"

    @staticmethod
    def _system_prompt(*, stage: str) -> str:
        stage_rule = {
            "initial": (
                "No capability schemas are supplied. If runtime capability may help, choose discover_capabilities "
                "with a semantic capability_goal, one required_effect, optional domain, and risk ceiling."
            ),
            "capability_shortlist": (
                "Compact live capability cards are supplied without input schemas. Semantically shortlist up to six "
                "exact capability_ids that best satisfy capability_goal. Return shortlist_capabilities. Never invent an ID."
            ),
            "capabilities": (
                "Full schemas are supplied only for Gemma-shortlisted live capabilities. Select exactly one offered "
                "capability_id and provide capability_arguments matching its input_schema, or choose a non-tool action."
            ),
            "result": (
                "A verified capability result is supplied. Do not request another capability. Choose silence, body_only, "
                "select_affordance, or speak_from_capability."
            ),
            "interactive_initial": (
                "This is a direct user turn. Decide only whether runtime capability discovery is needed. Choose "
                "discover_capabilities or silence. Do not answer the user."
            ),
            "interactive_shortlist": (
                "Compact live capability cards are supplied for a direct user turn. Semantically shortlist up to six exact "
                "capability_ids. Return shortlist_capabilities or silence."
            ),
            "interactive_capabilities": (
                "Full schemas are supplied only for shortlisted capabilities. Choose select_capability with one exact "
                "offered capability_id and schema-valid capability_arguments, or silence."
            ),
        }[stage]
        return (
            "You are ERIS Executive Cortex. DeepSeek owns observation, private reflection, seed generation and public "
            "wording. Runtime owns availability, permission, argument validation, execution, concurrency and evidence. "
            "You are the only semantic authority for conversational trajectory and capability choice. Silence is a first-class "
            "action. Under social ambiguity prefer reversible low-pressure moves. An optional invitation is weak evidence, "
            "not user debt. semantic_target is a meaning brief, never final wording. Every autonomous final decision must issue a real "
            "review policy: reconsider_on contains {kind, minimum_strength} conditions over runtime event envelopes; "
            "review_after_seconds is an optional timer, "
            "zero for event-only policy. Do not use free-text timing instructions. " + stage_rule + " Return exactly one JSON object."
        )

    def _candidate_capabilities(
        self,
        *,
        required_effect: str,
        maximum_risk: str,
        domain: str,
    ) -> tuple[ExecutiveTool, ...]:
        """Use V54 hard filtering, while honoring an injected V53 facade."""
        retrieve_overridden = retrieve_executive_tools is not _DEFAULT_RETRIEVE_EXECUTIVE_TOOLS
        filter_overridden = filter_executive_tools is not _DEFAULT_FILTER_EXECUTIVE_TOOLS
        if retrieve_overridden and not filter_overridden:
            return retrieve_executive_tools(
                self.owner,
                required_effect=required_effect,
                maximum_risk=maximum_risk,
                domain=domain,
                include_unavailable=False,
                refresh=False,
            )
        return filter_executive_tools(
            self.owner,
            required_effect=required_effect,
            maximum_risk=maximum_risk,
            domain=domain,
            include_unavailable=False,
            refresh=False,
        )

    def plan_interactive(self, user_text: str, *, snapshot: Mapping[str, Any] | None = None) -> InteractiveExecutiveDirective:
        if not self.enabled:
            return InteractiveExecutiveDirective(status="unavailable", reason="executive_disabled")
        index = build_capability_index(self.owner, refresh=True)
        decision = self._decide_interactive(
            user_text, snapshot=snapshot, stage="interactive_initial",
            capability_index=index.to_dict(), candidate_tools=(), offered_tools=(),
        )
        if decision is None:
            return InteractiveExecutiveDirective(status="unavailable", reason="interactive_executive_failure")
        if decision.action != "discover_capabilities":
            return InteractiveExecutiveDirective(
                status="none", semantic_goal=decision.semantic_target,
                reason=decision.reason, confidence=decision.confidence,
            )
        candidates = self._candidate_capabilities(
            required_effect=decision.required_effect,
            maximum_risk=decision.maximum_risk,
            domain=decision.capability_domain,
        )
        offered = self._semantic_shortlist_interactive(
            user_text, snapshot=snapshot, index=index.to_dict(), candidates=candidates,
        )
        if not offered:
            return InteractiveExecutiveDirective(status="none", reason="no_matching_live_capability")
        selected = self._decide_interactive(
            user_text, snapshot=snapshot, stage="interactive_capabilities",
            capability_index=index.to_dict(), candidate_tools=(), offered_tools=offered,
        )
        if selected is None:
            return InteractiveExecutiveDirective(status="unavailable", reason="interactive_capability_selection_failure")
        if selected.action != "select_capability":
            return InteractiveExecutiveDirective(
                status="none", semantic_goal=selected.semantic_target,
                reason=selected.reason, confidence=selected.confidence,
            )
        tool = catalog_index(offered).get(selected.capability_id)
        if tool is None or not tool.available:
            return InteractiveExecutiveDirective(
                status="unavailable", semantic_goal=selected.semantic_target,
                reason="interactive_capability_not_offered", confidence=selected.confidence,
            )
        selected_arguments = dict(selected.capability_arguments)
        valid, argument_reason = validate_arguments_against_schema(
            selected_arguments, tool.input_schema, capability_id=tool.capability_id
        )
        if not valid:
            return InteractiveExecutiveDirective(
                status="unavailable", semantic_goal=selected.semantic_target,
                reason=f"interactive_capability_arguments_invalid:{argument_reason}", confidence=selected.confidence,
            )
        return InteractiveExecutiveDirective(
            status="selected",
            capability_id=tool.capability_id,
            capability_arguments=selected_arguments,
            semantic_goal=selected.semantic_target or selected.capability_goal,
            reason=selected.reason,
            confidence=selected.confidence,
        )

    def _semantic_shortlist_interactive(
        self,
        user_text: str,
        *,
        snapshot: Mapping[str, Any] | None,
        index: Mapping[str, Any],
        candidates: Sequence[ExecutiveTool],
    ) -> tuple[ExecutiveTool, ...]:
        if len(candidates) <= 6:
            return tuple(candidates)
        decision = self._decide_interactive(
            user_text, snapshot=snapshot, stage="interactive_shortlist",
            capability_index=index, candidate_tools=candidates, offered_tools=(),
        )
        if decision is None or decision.action != "shortlist_capabilities":
            return ()
        return select_tools_by_id(candidates, decision.capability_ids, max_items=6)

    def _decide_interactive(
        self,
        user_text: str,
        *,
        snapshot: Mapping[str, Any] | None,
        stage: str,
        capability_index: Mapping[str, Any],
        candidate_tools: Sequence[ExecutiveTool],
        offered_tools: Sequence[ExecutiveTool],
    ) -> ExecutiveDecision | None:
        source = snapshot or {}
        payload = {
            "executive_state": self.state.to_dict(),
            "user_text": str(user_text or ""),
            "recent_public_history": list(source.get("recent_public_history", ()))[-8:],
            "relationship": source.get("relationship_summary", source.get("relationship", {})),
            "grounding_context": _compact(source.get("grounding_context", ""), 1800),
            "capability_index": dict(capability_index),
            "capability_candidates": [item.to_card() for item in candidate_tools],
            "offered_capabilities": [item.to_dict() for item in offered_tools],
            "contract": {
                "authority": "direct_chat_exact_capability_only",
                "public_wording_owner": "deepseek_public_reply",
                "execution_owner": "runtime",
                "stage": stage,
            },
        }
        return self._invoke(stage=stage, payload=payload, priority=96, max_tokens=420)

    def deliberate(
        self,
        blackboard: Any,
        affordances: Sequence[ExecutiveAffordance],
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> ExecutiveOutcome:
        options = tuple(item for item in affordances if isinstance(item, ExecutiveAffordance) and item.available)
        if not self.enabled:
            decision = ExecutiveDecision.unavailable("executive_disabled")
            return ExecutiveOutcome(None, "", "silence", decision.reason, decision)

        capability_index = build_capability_index(self.owner, refresh=True)
        decision = self._decide(
            blackboard, options, snapshot=snapshot, stage="initial",
            capability_index=capability_index.to_dict(), candidate_tools=(), offered_tools=(), capability_result=None,
        )
        if decision is None:
            unavailable = ExecutiveDecision.unavailable("executive_model_or_schema_failure")
            return ExecutiveOutcome(None, "", "silence", unavailable.reason, unavailable)

        offered: tuple[ExecutiveTool, ...] = ()
        if decision.action == "discover_capabilities":
            candidates = self._candidate_capabilities(
                required_effect=decision.required_effect,
                maximum_risk=decision.maximum_risk,
                domain=decision.capability_domain,
            )
            offered = self._semantic_shortlist(
                blackboard, options, snapshot=snapshot, capability_index=capability_index.to_dict(), candidates=candidates,
            )
            if not offered:
                silent = replace(decision, action="silence", reason="no_matching_live_capability")
                self._update_state(silent)
                return ExecutiveOutcome(None, "", "silence", silent.reason, silent)
            decision = self._decide(
                blackboard, options, snapshot=snapshot, stage="capabilities",
                capability_index=capability_index.to_dict(), candidate_tools=(), offered_tools=offered, capability_result=None,
            )
            if decision is None:
                unavailable = ExecutiveDecision.unavailable("executive_capability_selection_failure")
                return ExecutiveOutcome(None, "", "silence", unavailable.reason, unavailable)

        if decision.action == "invoke_capability":
            result = self._execute_exact_capability(decision, offered)
            if result is None:
                rejected = replace(decision, action="silence", reason="executive_capability_rejected")
                self._update_state(rejected)
                return ExecutiveOutcome(None, "", "silence", rejected.reason, rejected)
            decision = self._decide(
                blackboard, options, snapshot=snapshot, stage="result",
                capability_index=capability_index.to_dict(), candidate_tools=(), offered_tools=offered,
                capability_result=result,
            )
            if decision is None:
                unavailable = ExecutiveDecision.unavailable("executive_result_deliberation_failure")
                return ExecutiveOutcome(None, "", "silence", unavailable.reason, unavailable)
            decision = replace(decision, capability_result=result)

        self._update_state(decision)
        if decision.action == "body_only":
            return ExecutiveOutcome(None, "", "body_only", decision.reason, decision)
        if decision.action in {
            "silence", "discover_capabilities", "shortlist_capabilities", "invoke_capability", "select_capability"
        }:
            return ExecutiveOutcome(None, "", "silence", decision.reason, replace(decision, action="silence"))
        if decision.action == "speak_from_capability":
            candidate = self._candidate_from_capability(decision)
            if candidate is None:
                silent = replace(decision, action="silence", reason="capability_result_not_grounded")
                return ExecutiveOutcome(None, "", "silence", silent.reason, silent)
            return ExecutiveOutcome(candidate, "", "use_candidate", decision.reason, decision)

        selected = next((item for item in options if item.affordance_id == decision.affordance_id), None)
        if selected is None:
            silent = replace(decision, action="silence", reason="selected_affordance_not_offered")
            return ExecutiveOutcome(None, decision.affordance_id, "silence", silent.reason, silent)
        candidate = self._rewrite_candidate(selected.candidate, decision)
        return ExecutiveOutcome(candidate, selected.affordance_id, "use_candidate", decision.reason, decision)

    def _semantic_shortlist(
        self,
        blackboard: Any,
        affordances: Sequence[ExecutiveAffordance],
        *,
        snapshot: Mapping[str, Any] | None,
        capability_index: Mapping[str, Any],
        candidates: Sequence[ExecutiveTool],
    ) -> tuple[ExecutiveTool, ...]:
        if len(candidates) <= 6:
            return tuple(candidates)
        decision = self._decide(
            blackboard, affordances, snapshot=snapshot, stage="capability_shortlist",
            capability_index=capability_index, candidate_tools=candidates, offered_tools=(), capability_result=None,
        )
        if decision is None or decision.action != "shortlist_capabilities":
            return ()
        return select_tools_by_id(candidates, decision.capability_ids, max_items=6)

    def _decide(
        self,
        blackboard: Any,
        affordances: Sequence[ExecutiveAffordance],
        *,
        snapshot: Mapping[str, Any] | None,
        stage: str,
        capability_index: Mapping[str, Any],
        candidate_tools: Sequence[ExecutiveTool],
        offered_tools: Sequence[ExecutiveTool],
        capability_result: Mapping[str, Any] | None,
    ) -> ExecutiveDecision | None:
        public_view = blackboard.public_view() if callable(getattr(blackboard, "public_view", None)) else {}
        source = snapshot or {}
        payload = {
            "executive_state": self.state.to_dict(),
            "blackboard": public_view,
            "affordances": [item.to_card() for item in affordances],
            "recent_public_history": list(source.get("recent_public_history", ()))[-8:],
            "deepseek_lane_digests": {
                "observer": source.get("observer_frame", source.get("last_observer_frame", {})),
                "inner": source.get("self_context", {}),
                "relationship": source.get("relationship", {}),
                "recent_self_turn_semantics": list(source.get("recent_self_turn_semantics", ()))[-6:],
                "shared_semantic_context": source.get("shared_semantic_context", {}),
            },
            "capability_index": dict(capability_index),
            "capability_candidates": [item.to_card() for item in candidate_tools],
            "offered_capabilities": [item.to_dict() for item in offered_tools],
            "verified_capability_result": dict(capability_result or {}),
            "contract": {
                "authority": "trajectory_affordance_semantic_shortlist_and_exact_capability",
                "surface_owner": "deepseek_surface",
                "runtime_owner": "availability_permission_argument_validation_execution_concurrency",
                "stage": stage,
            },
        }
        return self._invoke(stage=stage, payload=payload, priority=58, max_tokens=500)

    def _invoke(self, *, stage: str, payload: Mapping[str, Any], priority: int, max_tokens: int) -> ExecutiveDecision | None:
        try:
            raw = self.invoke_structured(
                self.client,
                system=self._system_prompt(stage=stage),
                payload=payload,
                schema=EXECUTIVE_SCHEMA,
                name=f"eris_gemma_executive_{stage}",
                max_tokens=max_tokens,
                reasoning_effort="medium",
                inference_tier="main_cognition",
                priority=priority,
                timeout_seconds=float(os.getenv("ERIS_EXECUTIVE_TIMEOUT_S", "18") or 18),
            )
        except Exception as exc:
            self._log("warning", "[executive] model call failed stage=%s: %s", stage, exc)
            self._set_failure_backoff()
            return None
        decision = ExecutiveDecision.parse(raw)
        if decision is None:
            self._log("warning", "[executive] invalid response stage=%s", stage)
            self._set_failure_backoff()
            return None
        self._log(
            "info",
            "[executive] stage=%s action=%s affordance=%s capability=%s confidence=%.2f risk=%.2f reason=%s",
            stage, decision.action, decision.affordance_id or "none", decision.capability_id or "none",
            decision.confidence, decision.intrusion_risk, decision.reason,
        )
        return decision

    def _execute_exact_capability(
        self,
        decision: ExecutiveDecision,
        offered: Sequence[ExecutiveTool],
    ) -> Mapping[str, Any] | None:
        tool = catalog_index(offered).get(decision.capability_id)
        if tool is None or not tool.available or not tool.auto_callable:
            self._log(
                "warning", "[executive] rejected capability=%s offered=%s auto_callable=%s",
                decision.capability_id, bool(tool), bool(tool and tool.auto_callable),
            )
            return None

        arguments = dict(decision.capability_arguments)
        valid, reason = validate_capability_arguments(tool.capability_id, arguments)
        if not valid:
            valid, reason = validate_arguments_against_schema(
                arguments, tool.input_schema, capability_id=tool.capability_id
            )
        if not valid:
            self._log("warning", "[executive] invalid arguments capability=%s reason=%s", tool.capability_id, reason)
            return None

        executor = getattr(self.owner, "action_executor", None)
        if executor is None:
            return None
        try:
            execute_typed = getattr(executor, "execute_capability", None)
            if not callable(execute_typed):
                self._log("warning", "[executive] typed execution boundary unavailable")
                return None
            result = execute_typed(tool.capability_id, arguments)
        except Exception as exc:
            self._log("warning", "[executive] capability=%s failed: %s", tool.capability_id, exc)
            return None
        recorder = getattr(self.owner, "_record_tool_grounding", None)
        if callable(recorder):
            try:
                recorder(result, action_name=tool.capability_id)
            except Exception:
                pass
        return {
            "capability_id": tool.capability_id,
            "arguments": arguments,
            "effect": tool.effect,
            "success": bool(getattr(result, "success", False)),
            "observed": bool(getattr(result, "observed", False)),
            "status": str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", "")) or ""),
            "message": _compact(getattr(result, "message", ""), 1600),
            "data": dict(getattr(result, "data", {}) or {}),
            "evidence": list(getattr(result, "evidence", ()) or ()),
            "error_kind": str(getattr(result, "error_kind", "") or ""),
        }

    def _update_state(self, decision: ExecutiveDecision) -> None:
        if decision.action == "unavailable":
            return
        now = self._clock()
        with self._state_lock:
            current = self._state
            preferred = ""
            if decision.affordance_id:
                preferred = decision.affordance_id.split(":", 1)[0]
            elif decision.capability_id or decision.capability_ids:
                preferred = "capability"
            conditions = decision.reconsider_on or current.reconsider_on
            due_at = now + decision.review_after_seconds if decision.review_after_seconds > 0 else 0.0
            self._state = ExecutiveState(
                revision=current.revision + 1,
                phase=decision.phase or current.phase,
                trajectory=decision.trajectory or current.trajectory,
                reconsider_on=conditions,
                review_due_at=due_at,
                preferred_lane=preferred or current.preferred_lane,
                retry_not_before=0.0,
                updated_at=now,
            )
            persisted = self._state.to_persisted_dict(
                runtime_now=now, wall_now=self._wall_clock()
            )
        if callable(self._persist):
            try:
                self._persist(persisted)
            except Exception as exc:
                self._log("warning", "[executive] state persistence failed: %s", exc)

    def _set_failure_backoff(self) -> None:
        try:
            seconds = max(5.0, min(300.0, float(
                os.getenv("ERIS_EXECUTIVE_FAILURE_BACKOFF_S", "30") or 30.0
            )))
        except (TypeError, ValueError):
            seconds = 30.0
        with self._state_lock:
            self._state = replace(self._state, retry_not_before=self._clock() + seconds)

    def materialize_candidate(self, candidate: Any, decision: ExecutiveDecision) -> Any:
        return self._rewrite_candidate(candidate, decision)

    @staticmethod
    def _rewrite_candidate(candidate: Any, decision: ExecutiveDecision) -> Any:
        changes: dict[str, Any] = {}
        if decision.semantic_target:
            changes["topic"] = decision.semantic_target
        if decision.speech_act:
            changes["speech_act"] = decision.speech_act
        if decision.tone:
            changes["tone"] = decision.tone
        changes["reason"] = _compact(
            f"gemma_executive:{decision.reason}; upstream={getattr(candidate, 'reason', '')}", 300
        )
        changes["source"] = f"gemma_executive:{getattr(candidate, 'source', 'affordance')}"
        try:
            return replace(candidate, **changes)
        except Exception:
            return candidate

    @staticmethod
    def _candidate_from_capability(decision: ExecutiveDecision) -> Any | None:
        result = decision.capability_result or {}
        if not bool(result.get("success")) or not bool(result.get("observed")):
            return None
        target = decision.semantic_target or str(result.get("message", "") or "")
        if not target:
            return None
        try:
            from .social_initiative import SocialSpeechCandidate

            capability_id = str(result.get("capability_id", "") or "runtime_capability")
            return SocialSpeechCandidate(
                decision="candidate",
                kind="grounded_tool_finding",
                topic=target,
                speech_act=decision.speech_act or "share_grounded_runtime_finding",
                anchor_type="runtime_capability",
                anchor_id=f"executive_capability:{capability_id}",
                evidence_refs=tuple(str(item) for item in result.get("evidence", ()) if str(item or "").strip()),
                requires_grounding=False,
                confidence=max(0.45, decision.confidence),
                relevance=max(0.45, 1.0 - decision.intrusion_risk),
                urgency=0.2,
                tone=decision.tone or "matter_of_fact_warm",
                reason=f"gemma_executive:verified_capability:{capability_id}:{decision.reason}",
                source="gemma_executive_capability",
            )
        except Exception:
            return None

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = [
    "EXECUTIVE_SCHEMA",
    "ExecutiveCortex",
    "ExecutiveDecision",
    "ExecutiveEvent",
    "ExecutiveOutcome",
    "ExecutiveState",
    "ReviewCondition",
    "InteractiveExecutiveDirective",
    "may_release_optional_reply_baton",
]
