# -*- coding: utf-8 -*-
"""Typed normalization for the public-turn social plan.

The model appraises every public turn, but operational identifiers, clocks,
leases and retry state remain runtime-owned.  Keeping those responsibilities
separate prevents the model from accidentally inventing a scheduler and then
asking the runtime to pretend it is infrastructure.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


SOCIAL_PLAN_SCHEMA_VERSION = "eris.social_plan.v1"


def _compact(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _strings(value: Any, *, limit: int, item_limit: int = 96) -> list[str]:
    return [
        item
        for item in (_compact(raw, item_limit) for raw in _sequence(value)[:limit])
        if item
    ]


def empty_afterbeat() -> dict[str, Any]:
    return {
        "decision": "none",
        "role": "afterthought",
        "objective": "",
        "pause_class": "short",
        "tone": "neutral",
        "confidence": 0.0,
    }


def empty_exposure() -> dict[str, Any]:
    return {
        "decision": "none",
        "kind": "none",
        "level": 0.0,
        "expects_reaction": False,
        "reaction_window_class": "short",
        "expected_responses": [],
        "silence_hypotheses": [],
        "recovery_style": "none",
        "confidence": 0.0,
    }


def empty_agenda_update() -> dict[str, Any]:
    return {
        "decision": "none",
        "goal_type": "none",
        "objective": "",
        "desired_user_state": "",
        "strategy": "",
        "horizon": "session",
        "success_signals": [],
        "stop_signals": [],
        "salience": 0.0,
        "evidence_refs": [],
    }


def empty_conversation_arc() -> dict[str, Any]:
    return {
        "decision": "none",
        "goal": "",
        "beats": [],
        "confidence": 0.0,
    }


def empty_social_plan() -> dict[str, Any]:
    return {
        "afterbeat": empty_afterbeat(),
        "exposure": empty_exposure(),
        "agenda_update": empty_agenda_update(),
        "conversation_arc": empty_conversation_arc(),
    }


def normalize_afterbeat(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    result = empty_afterbeat()
    decision = _compact(data.get("decision", "none"), 24).lower() or "none"
    result["decision"] = decision if decision in {"none", "reserve"} else "none"
    role = _compact(data.get("role", "afterthought"), 32).lower() or "afterthought"
    allowed_roles = {"punchline", "reveal", "soften", "reconsider", "afterthought"}
    result["role"] = role if role in allowed_roles else "afterthought"
    result["objective"] = _compact(data.get("objective", ""), 320)
    pause_class = _compact(data.get("pause_class", "short"), 24).lower() or "short"
    result["pause_class"] = pause_class if pause_class in {"micro", "short", "held"} else "short"
    result["tone"] = _compact(data.get("tone", "neutral"), 48).lower() or "neutral"
    result["confidence"] = _clamp01(data.get("confidence", 0.0))
    if result["decision"] == "reserve" and not result["objective"]:
        result["decision"] = "none"
    return result


def normalize_exposure(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    result = empty_exposure()
    decision = _compact(data.get("decision", "none"), 24).lower() or "none"
    result["decision"] = decision if decision in {"none", "open"} else "none"
    kind = _compact(data.get("kind", "none"), 48).lower() or "none"
    allowed_kinds = {
        "none", "playful_vulnerability", "flirt_risk", "tease_risk",
        "self_disclosure", "social_invitation", "face_risk",
    }
    result["kind"] = kind if kind in allowed_kinds else "none"
    result["level"] = _clamp01(data.get("level", 0.0))
    result["expects_reaction"] = bool(data.get("expects_reaction", False))
    window = _compact(data.get("reaction_window_class", "short"), 24).lower() or "short"
    result["reaction_window_class"] = window if window in {"micro", "short", "held"} else "short"
    result["expected_responses"] = _strings(data.get("expected_responses"), limit=6)
    result["silence_hypotheses"] = _strings(data.get("silence_hypotheses"), limit=4, item_limit=120)
    result["recovery_style"] = _compact(data.get("recovery_style", "none"), 64).lower() or "none"
    result["confidence"] = _clamp01(data.get("confidence", 0.0))
    if result["decision"] == "open" and (result["kind"] == "none" or not result["expects_reaction"]):
        result["decision"] = "none"
    return result


def normalize_agenda_update(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    result = empty_agenda_update()
    decision = _compact(data.get("decision", "none"), 24).lower() or "none"
    allowed_decisions = {"none", "open", "update", "advance", "pause", "close"}
    result["decision"] = decision if decision in allowed_decisions else "none"
    goal_type = _compact(data.get("goal_type", "none"), 48).lower() or "none"
    allowed_goal_types = {
        "none", "build_shared_bit", "deepen_topic", "invite_story",
        "story_continuation", "warm_presence", "callback", "repair",
        "change_mood", "comfortable_silence", "learn_preference",
    }
    result["goal_type"] = goal_type if goal_type in allowed_goal_types else "none"
    result["objective"] = _compact(data.get("objective", ""), 420)
    result["desired_user_state"] = _compact(data.get("desired_user_state", ""), 160)
    result["strategy"] = _compact(data.get("strategy", ""), 220)
    horizon = _compact(data.get("horizon", "session"), 24).lower() or "session"
    result["horizon"] = horizon if horizon in {"turn", "session", "cross_session"} else "session"
    result["success_signals"] = _strings(data.get("success_signals"), limit=8, item_limit=120)
    result["stop_signals"] = _strings(data.get("stop_signals"), limit=8, item_limit=120)
    result["salience"] = _clamp01(data.get("salience", 0.0))
    result["evidence_refs"] = _strings(data.get("evidence_refs"), limit=6, item_limit=140)
    if result["decision"] in {"open", "update", "advance"} and (
        result["goal_type"] == "none" or not result["objective"]
    ):
        result["decision"] = "none"
    return result


def normalize_conversation_arc(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    result = empty_conversation_arc()
    decision = _compact(data.get("decision", "none"), 24).lower() or "none"
    result["decision"] = decision if decision in {"none", "schedule"} else "none"
    result["goal"] = _compact(data.get("goal", ""), 420)
    beats: list[dict[str, Any]] = []
    for raw in _sequence(data.get("beats"))[:3]:
        if not isinstance(raw, Mapping):
            continue
        objective = _compact(raw.get("objective", ""), 360)
        if not objective:
            continue
        role = _compact(raw.get("role", "callback"), 40).lower() or "callback"
        if role not in {"callback", "reveal", "punchline", "escalate", "soften", "reconsider", "return_to_goal", "afterthought"}:
            role = "callback"
        beats.append({
            "role": role,
            "objective": objective,
            "condition": _compact(raw.get("condition", "when_context_still_supports_it"), 220),
            "tone": _compact(raw.get("tone", "neutral"), 48).lower() or "neutral",
        })
    result["beats"] = beats
    result["confidence"] = _clamp01(data.get("confidence", 0.0))
    if result["decision"] == "schedule" and (not result["goal"] or not beats):
        result["decision"] = "none"
    return result


def normalize_social_plan(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    data = payload or {}
    result = empty_social_plan()
    result["afterbeat"] = normalize_afterbeat(data.get("afterbeat") if isinstance(data.get("afterbeat"), Mapping) else None)
    result["exposure"] = normalize_exposure(data.get("exposure") if isinstance(data.get("exposure"), Mapping) else None)
    result["agenda_update"] = normalize_agenda_update(data.get("agenda_update") if isinstance(data.get("agenda_update"), Mapping) else None)
    arc_payload = data.get("conversation_arc") if isinstance(data.get("conversation_arc"), Mapping) else None
    result["conversation_arc"] = normalize_conversation_arc(arc_payload)
    return deepcopy(result)


__all__ = [
    "SOCIAL_PLAN_SCHEMA_VERSION",
    "empty_afterbeat",
    "empty_agenda_update",
    "empty_conversation_arc",
    "empty_exposure",
    "empty_social_plan",
    "normalize_afterbeat",
    "normalize_agenda_update",
    "normalize_conversation_arc",
    "normalize_exposure",
    "normalize_social_plan",
]
