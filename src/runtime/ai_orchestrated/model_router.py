# -*- coding: utf-8 -*-
"""Model router cho observer và intention planner của kiến trúc C."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from typing import Any, Mapping, Sequence

from runtime.diagnostic_logging import safe_log
from runtime.cognition.turn_anchor import anchor_from_semantic_frame, previous_assistant_from_history
from runtime.cognition.normalization import normalize_vi
from runtime.social_stance_policy import STANCE_PUBLIC_RULES_VI
from llm.deepseek import is_deepseek

from actions.contracts import VALID_SYSTEM_ACTIONS

from .contracts import CognitiveObservation, IntentionPlan
from .discovery import DiscoveryPlan
from .identity import CONFLICT_TEMPLATES, DEFAULT_DEFENSES, DEFAULT_EMERGENT_VALUES, DEFAULT_MOTIVES, DEFAULT_RELATIONSHIP, DEFAULT_VALUES
from .personality import DEFAULT_CORE, DEFAULT_MOOD, DEFAULT_TEMPERAMENT




DISCOVERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "lane", "topic", "needs_external", "freshness_required",
        "verification_required", "eris_interest", "user_relevance",
        "novelty", "importance", "confidence", "reason"
    ],
    "properties": {
        "lane": {
            "type": "string",
            "enum": ["none", "vietnam_local_signal", "fresh_curiosity", "user_environment", "tutor_artifact"],
        },
        "topic": {"type": "string"},
        "needs_external": {"type": "boolean"},
        "freshness_required": {"type": "boolean"},
        "verification_required": {"type": "boolean"},
        "eris_interest": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "user_relevance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "novelty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
}

COGNITIVE_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "event_kind",
        "user_act",
        "relationship_meaning",
        "continuity",
        "repair_needed",
        "assistant_fault_probability",
        "memory_worthy",
        "confidence",
        "ambiguity",
        "relational_delta",
        "competence_delta",
        "factual_delta",
        "boundary_delta",
        "familiarity_delta",
        "closeness_delta",
        "playful_safety_delta",
        "rupture_delta",
        "appraisal",
        "self_interpretation",
        "self_narrative_candidate",
        "self_narrative_confidence",
        "consequence",
        "trait_signals",
        "identity_signals",
        "active_motives",
        "activated_defenses",
        "active_conflict",
        "value_choice",
        "discourse",
        "open_loop",
        "memory_candidate",
        "evidence",
        "notes",
    ],
    "properties": {
        "event_kind": {"type": "string", "enum": ["chat", "force_speak", "autonomous", "startup"]},
        "user_act": {"type": "string"},
        "relationship_meaning": {"type": "string"},
        "continuity": {"type": "string"},
        "repair_needed": {"type": "boolean"},
        "assistant_fault_probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "memory_worthy": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "ambiguity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        **{
            name: {"type": "number", "minimum": -1.0, "maximum": 1.0}
            for name in (
                "relational_delta",
                "competence_delta",
                "factual_delta",
                "boundary_delta",
                "familiarity_delta",
                "closeness_delta",
                "playful_safety_delta",
                "rupture_delta",
            )
        },
        "appraisal": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pleasantness",
                "curiosity",
                "tenderness",
                "embarrassment",
                "irritation",
                "pressure",
                "novelty",
            ],
            "properties": {
                name: {"type": "number", "minimum": 0.0, "maximum": 1.0}
                for name in (
                    "pleasantness",
                    "curiosity",
                    "tenderness",
                    "embarrassment",
                    "irritation",
                    "pressure",
                    "novelty",
                )
            },
        },
        "self_interpretation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "frame", "confidence", "self_authored", "evidence"],
            "properties": {
                "summary": {"type": "string"},
                "frame": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "self_authored": {"type": "boolean"},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
        },
        "self_narrative_candidate": {"type": "string"},
        "self_narrative_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "consequence": {
            "type": "object",
            "additionalProperties": False,
            "required": ["strategy_use_id", "strategy", "target_goal", "context", "outcome", "reinforcement", "confidence", "evidence"],
            "properties": {
                "strategy_use_id": {"type": "string"},
                "strategy": {"type": "string"},
                "target_goal": {"type": "string"},
                "context": {"type": "string"},
                "outcome": {"type": "string"},
                "reinforcement": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
        },
        "trait_signals": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category", "trait", "delta", "confidence", "importance",
                    "source", "evidence", "strategy"
                ],
                "properties": {
                    "category": {"type": "string", "enum": ["mood", "temperament", "core"]},
                    "trait": {"type": "string"},
                    "delta": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "source": {
                        "type": "string",
                        "enum": ["user_interaction", "self_choice", "consequence", "environment"]
                    },
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                    "strategy": {"type": "string"},
                },
            },
        },
        "identity_signals": {
            "type": "array",
            "maxItems": 14,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["dimension", "key", "delta", "confidence", "importance", "scope", "context", "evidence"],
                "properties": {
                    "dimension": {"type": "string", "enum": ["value", "motive", "defense", "belief", "relationship", "emergent_value", "imprint"]},
                    "key": {"type": "string"},
                    "delta": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "scope": {"type": "string"},
                    "context": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                },
            },
        },
        "active_motives": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "strength", "trigger"],
                "properties": {
                    "key": {"type": "string"},
                    "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "trigger": {"type": "string"},
                },
            },
        },
        "activated_defenses": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "strength", "trigger"],
                "properties": {
                    "key": {"type": "string"},
                    "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "trigger": {"type": "string"},
                },
            },
        },
        "active_conflict": {
            "type": "object",
            "additionalProperties": False,
            "required": ["conflict_id", "activation", "left_pull", "right_pull", "chosen_side", "residue"],
            "properties": {
                "conflict_id": {"type": "string", "enum": ["", *CONFLICT_TEMPLATES]},
                "activation": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "left_pull": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "right_pull": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "chosen_side": {"type": "string"},
                "residue": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "value_choice": {
            "type": "object",
            "additionalProperties": False,
            "required": ["chosen", "rejected", "cost", "confidence", "evidence"],
            "properties": {
                "chosen": {"type": "string"},
                "rejected": {"type": "string"},
                "cost": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
        },
        "discourse": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status", "reply_expected", "assistant_may_continue",
                "unresolved_point", "thread_key", "confidence", "evidence"
            ],
            "properties": {
                "status": {"type": "string", "enum": ["open", "closed", "waiting_user", "neutral", "unknown"]},
                "reply_expected": {"type": "boolean"},
                "assistant_may_continue": {"type": "boolean"},
                "unresolved_point": {"type": "string"},
                "thread_key": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            },
        },
        "open_loop": {"type": "string"},
        "memory_candidate": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "notes": {"type": "string"},
    },
}


# Observer khách quan không được tự quyết định personality. Final contract vẫn
# giữ đủ field để persist/debug, nhưng inference được tách làm hai lane.
OBJECTIVE_OBSERVATION_SCHEMA: dict[str, Any] = {
    **COGNITIVE_OBSERVATION_SCHEMA,
    "required": [
        name
        for name in COGNITIVE_OBSERVATION_SCHEMA["required"]
        if name not in {"self_interpretation", "self_narrative_candidate", "self_narrative_confidence", "trait_signals", "identity_signals", "active_motives", "activated_defenses", "active_conflict", "value_choice"}
    ],
    "properties": {
        name: value
        for name, value in COGNITIVE_OBSERVATION_SCHEMA["properties"].items()
        if name not in {"self_interpretation", "self_narrative_candidate", "self_narrative_confidence", "trait_signals", "identity_signals", "active_motives", "activated_defenses", "active_conflict", "value_choice"}
    },
}

PERSONALITY_REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "self_interpretation", "self_narrative_candidate", "self_narrative_confidence", "trait_signals", "identity_signals",
        "active_motives", "activated_defenses", "active_conflict",
        "value_choice", "notes"
    ],
    "properties": {
        "self_interpretation": COGNITIVE_OBSERVATION_SCHEMA["properties"]["self_interpretation"],
        "self_narrative_candidate": COGNITIVE_OBSERVATION_SCHEMA["properties"]["self_narrative_candidate"],
        "self_narrative_confidence": COGNITIVE_OBSERVATION_SCHEMA["properties"]["self_narrative_confidence"],
        "trait_signals": COGNITIVE_OBSERVATION_SCHEMA["properties"]["trait_signals"],
        "identity_signals": COGNITIVE_OBSERVATION_SCHEMA["properties"]["identity_signals"],
        "active_motives": COGNITIVE_OBSERVATION_SCHEMA["properties"]["active_motives"],
        "activated_defenses": COGNITIVE_OBSERVATION_SCHEMA["properties"]["activated_defenses"],
        "active_conflict": COGNITIVE_OBSERVATION_SCHEMA["properties"]["active_conflict"],
        "value_choice": COGNITIVE_OBSERVATION_SCHEMA["properties"]["value_choice"],
        "notes": {"type": "string"},
    },
}




SEMANTIC_FRAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version", "turn_kind", "discourse_relation", "user_act", "target",
        "literal_question", "ambiguity_owner", "boundary_action",
        "continuation_key", "evidence_scope", "tool_intent",
        "missing_evidence", "reference", "reply_obligation", "memory_query",
    ],
    "properties": {
        "version": {"type": "string", "enum": ["semantic_frame.v1"]},
        "turn_kind": {"type": "string"},
        "discourse_relation": {"type": "string"},
        "user_act": {"type": "string"},
        "target": {"type": "string"},
        "literal_question": {"type": "boolean"},
        "ambiguity_owner": {"type": "string", "enum": ["user", "assistant", "shared", "none"]},
        "boundary_action": {"type": "string"},
        "continuation_key": {"type": "string"},
        "evidence_scope": {"type": "string"},
        "tool_intent": {"type": "string"},
        "missing_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "reference": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "speaker", "operation", "turn_index", "turn_offset", "confidence"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "none", "recent_user_turn", "recent_assistant_turn",
                        "assistant_proposition", "open_question",
                        "long_term_memory", "current_message"
                    ],
                },
                "speaker": {"type": "string", "enum": ["none", "user", "assistant"]},
                "operation": {
                    "type": "string",
                    "enum": ["none", "repeat", "recall", "clarify", "confirm", "repair", "answer"],
                },
                "turn_index": {"type": "integer", "minimum": 0},
                "turn_offset": {"type": "integer", "minimum": 0, "maximum": 16},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "reply_obligation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["must_answer", "must_not_broad_clarify", "must_not_call_tool"],
            "properties": {
                "must_answer": {"type": "boolean"},
                "must_not_broad_clarify": {"type": "boolean"},
                "must_not_call_tool": {"type": "boolean"},
            },
        },
        "memory_query": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "intent", "subject", "predicate_hint", "object_hint",
                "temporal_scope", "answer_mode", "confidence"
            ],
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["none", "recall_fact", "recall_summary", "verify_memory", "explain_memory"]
                },
                "subject": {"type": "string"},
                "predicate_hint": {"type": "string"},
                "object_hint": {"type": "string"},
                "temporal_scope": {"type": "string"},
                "answer_mode": {
                    "type": "string",
                    "enum": ["exact", "gist", "summary", "admit_uncertain"]
                },
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
    },
}

ASSISTANT_ACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "proposition_mode", "confidence"],
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "silence", "acknowledgement", "social", "assertion",
                "explanation", "opinion", "answer", "confirmation",
                "repair", "question", "action_report", "other"
            ],
        },
        "proposition_mode": {"type": "string", "enum": ["none", "new", "continue"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


PUBLIC_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # PDF annotation, pages 12-13: meaning and wording are produced by one
    # semantic authority in the same remote call.
    "required": ["semantic_frame", "assistant_act", "text", "should_speak", "performance_hint"],
    "properties": {
        "semantic_frame": SEMANTIC_FRAME_SCHEMA,
        "assistant_act": ASSISTANT_ACT_SCHEMA,
        "text": {"type": "string"},
        "should_speak": {"type": "boolean"},
        "performance_hint": {
            "type": "string",
            "enum": [
                "neutral", "soft_warm", "warm_embarrassed", "dry_tease",
                "playful", "curious", "focused", "cold_precision",
                "annoyed_soft", "sad_distant", "repair", "surprised"
            ],
        },
    },
}


# PDF annotation, page 13: a failed wording/grounding gate must not cause the
# model to reinterpret the user turn.  Retry only the public wording while the
# already validated semantic frame remains immutable in runtime.
PUBLIC_WORDING_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "should_speak", "performance_hint"],
    "properties": {
        "text": {"type": "string"},
        "should_speak": {"type": "boolean"},
        "performance_hint": PUBLIC_REPLY_SCHEMA["properties"]["performance_hint"],
    },
}

INTENTION_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "plan_id",
        "speak",
        "motive",
        "strategy",
        "value_focus",
        "topic",
        "importance",
        "intrusion_risk",
        "confidence",
        "performance_hint",
        "tool_intent",
        "tool_input",
        "evidence_refs",
        "semantics",
        "activity",
        "notes",
    ],
    "properties": {
        "plan_id": {"type": "string"},
        "speak": {"type": "boolean"},
        "motive": {"type": "string"},
        "strategy": {"type": "string"},
        "value_focus": {"type": "string"},
        "topic": {"type": "string"},
        "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "intrusion_risk": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "performance_hint": {"type": "string"},
        "tool_intent": {"type": "string"},
        "tool_input": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "semantics": {
            "type": "object",
            "additionalProperties": False,
            "required": ["turn_kind", "speech_act", "subject_key", "evidence_scope", "continuation_key"],
            "properties": {
                "turn_kind": {
                    "type": "string",
                    "enum": [
                        "chat_response", "continuation", "environment", "activity_event",
                        "discovery", "internal", "presence", "startup", "force_speak", "other"
                    ],
                },
                "speech_act": {"type": "string"},
                "subject_key": {"type": "string"},
                "evidence_scope": {"type": "string"},
                "continuation_key": {"type": "string"},
            },
        },
        "activity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["activity_kind", "phase", "event", "event_key", "confidence", "evidence_refs"],
            "properties": {
                "activity_kind": {"type": "string"},
                "phase": {"type": "string"},
                "event": {"type": "string"},
                "event_key": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            },
        },
        "notes": {"type": "string"},
    },
}


def _content(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], Mapping) else {}
        message = first.get("message", {}) if isinstance(first, Mapping) else {}
        content = message.get("content", "") if isinstance(message, Mapping) else ""
        return str(content or "").strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0] if isinstance(candidates[0], Mapping) else {}
        content = first.get("content", {}) if isinstance(first, Mapping) else {}
        parts = content.get("parts", []) if isinstance(content, Mapping) else []
        if isinstance(parts, list):
            return "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, Mapping)).strip()
    return ""


def _json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    
    def unwrap(d: dict) -> dict:
        if not d:
            return d
        if len(d) == 1:
            key = list(d.keys())[0]
            val = d[key]
            if isinstance(val, Mapping):
                common_keys = {"text", "semantic_frame", "should_speak", "performance_hint", "event_kind", "user_act", "lane", "topic"}
                if any(k in val for k in common_keys):
                    return unwrap(dict(val))
        return d

    try:
        value = json.loads(raw)
        parsed = dict(value) if isinstance(value, Mapping) else {}
        return unwrap(parsed)
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return {"text": raw, "should_speak": True}
        try:
            value = json.loads(match.group(0))
            parsed = dict(value) if isinstance(value, Mapping) else {}
            return unwrap(parsed)
        except Exception:
            return {"text": raw, "should_speak": True}


class AIRuntimeModelRouter:
    def __init__(
        self,
        llm_service: Any,
        *,
        logger: Any | None = None,
        budget_policy: Any | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.logger = logger
        self.budget_policy = budget_policy

    def _run_inference(
        self,
        tier: str,
        func: Any,
        *,
        reason: str,
        priority: int,
    ) -> Any:
        # PDF annotation, pages 6-9: the local VRAM scheduler and the remote
        # inference broker solve different problems.  Keep the former, but
        # attach a broker lane so every provider request receives global quota,
        # deadline and preemption semantics.
        from runtime.inference_broker import inference_context

        reason_key = str(reason or "").strip().lower()
        if "public_reply" in reason_key and "autonomous" not in reason_key:
            lane = "chat_main"
        elif "observer" in reason_key or "observation" in reason_key:
            lane = "post_observer"
        elif "autonomous" in reason_key or "self_initiated" in reason_key:
            lane = "autonomous"
        elif "chat_intention" in reason_key:
            lane = "chat_tool_required"
        elif "discovery" in reason_key or "planner" in reason_key:
            lane = "tutor_background"
        elif "reflection" in reason_key or "deep" in reason_key or tier == "subconscious_4b":
            lane = "post_observer"
        else:
            lane = "transport"

        optional = lane in {"post_observer", "autonomous", "tutor_background"}
        coalesce_key = reason_key if optional else ""
        with inference_context(
            lane,
            optional=optional,
            coalesce_key=coalesce_key,
            metadata={"router_reason": reason, "model_tier": tier},
        ):
            policy = self.budget_policy
            if policy is not None and callable(getattr(policy, "run_queued", None)):
                res = policy.run_queued(
                    tier,
                    func,
                    reason=reason,
                    priority=priority,
                )
            else:
                res = func()

            # Extract and log reasoning telemetry for visibility/observability
            reasoning = ""
            if isinstance(res, Mapping):
                choices = res.get("choices")
                if isinstance(choices, list) and choices:
                    for choice in choices:
                        if isinstance(choice, Mapping):
                            message = choice.get("message")
                            if isinstance(message, Mapping):
                                for key in ("reasoning_content", "reasoning"):
                                    val = message.get(key)
                                    if isinstance(val, str) and val.strip():
                                        reasoning = val.strip()
                                        break
                        if reasoning:
                            break
            if reasoning and self.logger is not None:
                content_len = 0
                if isinstance(res, Mapping):
                    choices = res.get("choices")
                    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                        msg = choices[0].get("message")
                        if isinstance(msg, Mapping):
                            content_len = len(msg.get("content", "") or "")
                safe_log(
                    self.logger,
                    "info",
                    "[%s reasoning] chars=%d content_chars=%d",
                    lane,
                    len(reasoning),
                    content_len,
                )
            return res

    @property
    def observer_client(self) -> Any | None:
        return getattr(self.llm_service, "social_parser_client", None)

    @property
    def deep_client(self) -> Any | None:
        return getattr(self.llm_service, "social_critic_client", None)

    @property
    def fallback_client(self) -> Any | None:
        return getattr(self.llm_service, "social_fallback_client", None)

    def _call(
        self,
        client: Any,
        *,
        system: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
        name: str,
        max_tokens: int,
        reasoning_effort: str | None = None,
        inference_tier: str = "subconscious_4b",
        priority: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if client is None:
            return {}
        # PDF cleanup annotation: JSON-schema strictness is a contract choice,
        # not a removed-model compatibility branch.
        strict = False
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": strict,
                "schema": dict(schema),
            },
        }
        try:
            def invoke() -> Any:
                return client.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(dict(payload), ensure_ascii=False)},
                    ],
                    temperature=0.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    reasoning_effort=reasoning_effort,
                    timeout=timeout_seconds,
                )

            raw = self._run_inference(
                inference_tier,
                invoke,
                reason=name,
                priority=int(priority if priority is not None else (45 if "deep" in name else 35)),
            )
            return _json(_content(raw))
        except Exception as exc:  # noqa: BLE001
            if self.logger is not None:
                safe_log(self.logger, "debug", "[ai runtime model] %s failed model=%s: %s", name, getattr(client, "model_name", ""), exc)
            return {}

    @staticmethod
    def _public_reply_prompt(language_hint: str = "vi") -> str:
        language = {
            "ja": "tiếng Nhật",
            "en": "tiếng Anh",
            "vi": "tiếng Việt",
        }.get(str(language_hint or "vi").strip().lower(), "ngôn ngữ của người dùng")
        return (
            f"Bạn là ERIS. Hãy phản ứng từ bản thân hiện tại và viết nguyên câu public tự nhiên bằng {language}. "
            "Không cố diễn một nhãn MBTI, Enneagram, tritype hay archetype. Mô tả personality được cung cấp là quán tính hiện tại, "
            "không phải danh sách động tác phải biểu diễn. Có thể dịu, sắc, hóm hỉnh, phòng thủ, chủ động hoặc mâu thuẫn theo đúng ngữ cảnh. "
            "Không phải support bot, không giả dễ thương, không biến mọi cảm xúc thành thơ. "
            "Yêu cầu đổi giọng (ngọt, sến, cộc, dịu...) chỉ điều chỉnh delivery của lượt này, không thay toàn bộ bản thân. "
            "Giữ continuity và self-authorship: đáp lại sự gần gũi theo mức quan hệ hiện có; có thể trêu, ngượng hoặc nhận một phần, "
            "nhưng không nhảy thẳng sang tuyên bố yêu/quen/gắn bó chỉ vì user vừa yêu cầu một câu tình cảm. "
            "Bạn sở hữu lời nói; không tự phân loại Ni/Ti/Fe, không tự chấm confidence, không giải thích reasoning. "
            "Trả lời yêu cầu cụ thể trước. Không tự chèn tuyên bố kiểu 'không như con người' nếu người dùng không hỏi về bản thể. "
            "Pre-response cognitive brief là contract hiểu lượt hiện tại, không phải câu văn mẫu. Tuân thủ primary_goal, response_move, "
            "ambiguity_owner và avoid_moves. Khi ambiguity_owner=assistant, ERIS phải tự giải quyết phần mơ hồ do lời trước của mình tạo ra; "
            "không hỏi user nói rõ hơn, không trách user hỏi lửng và không giảng giải cơ chế hội thoại. Khi response_move=self_elaborate, "
            "hãy nối tiếp chính lời ERIS trước đó. Khi response_move=repair_previous_response, nêu ngắn lỗi cụ thể rồi thay câu trả lời ngay. "
            "Khi response_move=clarify_previous_phrase/literal_reference, trả nghĩa đen trước rồi mới thêm cá tính. Không tự đánh giá user, "
            "không đảo chủ thể, không phát minh premise khác để né câu hỏi. "
            "Phân biệt correction với disagreement. User phủ định một fact, sửa điều họ đã nói, đặt boundary, hoặc chỉ ra hậu quả cụ thể thì ERIS cập nhật gọn. "
            "Nhưng user không đồng ý với một nhận định chủ quan của ERIS chưa tự động chứng minh ERIS sai. "
            + STANCE_PUBLIC_RULES_VI + " "
            "Khi tạo semantic_frame cho bất đồng với ấn tượng chủ quan, ưu tiên user_act=disagreement hoặc self_report_contrast và "
            "discourse_relation=contest_assistant_impression; không dùng correction_or_challenge/challenge_assistant_assumption chỉ vì có từ phủ định. "
            "Chỉ xin lỗi khi có lỗi rõ, gây tổn thương, vượt boundary, bịa fact như thật, hoặc không làm đúng yêu cầu. Tránh các câu máy móc "
            "'sai nhịp', 'lệch nhịp', 'tôi hiểu sai', 'tôi rút lại' trong bất đồng xã hội thông thường; thừa nhận khác biệt rồi giữ hoặc điều chỉnh lập trường tự nhiên. "
            "Memory chỉ là continuity, không chứng minh hiện tại. Grounding là nguồn thật cho màn hình/file/tool. "
            "Planner đã sở hữu tool intent; bạn không chọn, đổi hay claim tool đã thành công. "
            "performance_hint chỉ là một preset sân khấu ngắn, không viết stage direction vào text. "
            "Trong CÙNG JSON, sinh semantic_frame.v1, assistant_act rồi text. semantic_frame chỉ mô tả lượt USER hiện tại; "
            "assistant_act chỉ mô tả câu ERIS sắp nói, tuyệt đối không chép user_act sang assistant turn. Dùng toàn bộ chat history và "
            "Discourse state: history_turn_map ánh xạ message theo vị trí sang turn_index nhưng không lặp text. "
            "Reference là discriminated contract: recent_user_turn luôn speaker=user; recent_assistant_turn và assistant_proposition luôn speaker=assistant; "
            "long_term_memory luôn speaker=none và không có turn locator. Chỉ dùng một trong turn_index hoặc turn_offset. "
            "Nếu user muốn nhắc lại lời mình, dùng recent_user_turn + repeat/recall. Nếu hỏi lời ERIS, dùng recent_assistant_turn. "
            "Nếu hỏi nghĩa/độ thật/sửa một proposition trước, dùng assistant_proposition + clarify/confirm/repair và trỏ root từ candidate_references. "
            "Nếu hỏi memory dài hạn, dùng long_term_memory + recall/answer VÀ điền memory_query có intent, subject, predicate_hint, temporal_scope, answer_mode; "
            "runtime sẽ thực thi object này, không đọc lại raw user text. Khi không phải memory, memory_query.intent=none. "
            "assistant_act.kind phải là loại hành vi của text. acknowledgement/social dùng proposition_mode=none; assertion/explanation/opinion/answer/question dùng new; "
            "confirmation/repair dùng continue khi nối proposition đang active. Nếu lượt hiện tại không tham chiếu gì, reference phải none với locator bằng 0. "
            "Ví dụ hỏi thăm trạng thái ERIS phải target=assistant, user_act=relational_check_in, must_answer=true, must_not_broad_clarify=true và tool_intent rỗng. Return JSON only."
        )

    def generate_public_reply(
        self,
        *,
        chat_history: Sequence[Mapping[str, Any]],
        user_text: str,
        memory_context: str = "",
        grounding_context: str = "",
        relationship_context: str = "",
        personality_context: str = "",
        interrupt_context: str = "",
        engagement_context: str = "",
        routing_context: str = "",
        discourse_context: str = "",
        use_escalation: bool = False,
        reasoning_effort: str | None = None,
        thinking_mode: str | None = None,
        allow_fallback: bool = False,
        language_hint: str = "vi",
        planned_intention: IntentionPlan | None = None,
        retry_instruction: str = "",
        locked_semantic_frame: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = None
        if use_escalation:
            resolver = getattr(self.llm_service, "_resolve_escalation_client", None)
            if callable(resolver):
                try:
                    client = resolver()
                except Exception:
                    client = None
        client = client or getattr(self.llm_service, "client", None)
        context_parts = []
        if personality_context:
            context_parts.append(f"Current ERIS personality: {personality_context}")
        if relationship_context:
            context_parts.append(f"Relationship continuity: {relationship_context}")
        if grounding_context:
            context_parts.append(f"Current grounding: {grounding_context}")
        if memory_context:
            context_parts.append(f"Relevant memory: {memory_context}")
        if interrupt_context:
            context_parts.append(f"Mechanical interrupt context: {interrupt_context}")
        if engagement_context:
            context_parts.append(f"Durable engagement contract: {engagement_context}")
        if routing_context:
            context_parts.append(f"Runtime companion routing: {routing_context}")
        if discourse_context:
            context_parts.append(
                "Discourse state (index map for the chat_history messages; no duplicated text): "
                + discourse_context
            )
        if retry_instruction:
            context_parts.append(f"One-shot rewrite instruction: {retry_instruction}")
        if locked_semantic_frame:
            context_parts.append(
                "LOCKED semantic frame (runtime authority; do not reinterpret or modify): "
                + json.dumps(dict(locked_semantic_frame), ensure_ascii=False)
            )
        if planned_intention is not None:
            context_parts.append(
                "Planner intent: "
                + json.dumps(
                    {
                        "motive": planned_intention.motive,
                        "strategy": planned_intention.strategy,
                        "value_focus": planned_intention.value_focus,
                        "response_goal": planned_intention.topic,
                        "tool_intent": planned_intention.tool_intent,
                        "tool_input": planned_intention.tool_input,
                        "notes": planned_intention.notes,
                    },
                    ensure_ascii=False,
                )
            )
        system = self._public_reply_prompt(language_hint)
        if locked_semantic_frame:
            system += (
                "\n\nThis is a wording-only retry. Return only text, should_speak and "
                "performance_hint. The semantic frame above is immutable and runtime will "
                "reuse it verbatim. Do not classify the turn again."
            )
        if context_parts:
            system += "\n\n" + "\n".join(context_parts)
        messages = [
            {"role": "system", "content": system},
            *[dict(item) for item in chat_history if isinstance(item, Mapping)],
            {"role": "user", "content": user_text},
        ]

        def call(target: Any) -> dict[str, Any]:
            if target is None:
                return {}
            strict = False
            response_schema = (
                PUBLIC_WORDING_REWRITE_SCHEMA if locked_semantic_frame else PUBLIC_REPLY_SCHEMA
            )
            response_name = "eris_public_wording_rewrite" if locked_semantic_frame else "eris_public_reply"
            try:
                def invoke() -> Any:
                    request_kwargs = {
                        "messages": messages,
                        "temperature": 0.48,
                        "frequency_penalty": 0.0,
                        "presence_penalty": 0.0,
                        "max_tokens": (360 if locked_semantic_frame else (900 if reasoning_effort else 620)),
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": response_name,
                                "strict": strict,
                                "schema": response_schema,
                            },
                        },
                        "reasoning_effort": reasoning_effort,
                    }
                    if is_deepseek(
                        getattr(target, "base_url", ""),
                        getattr(target, "model_name", ""),
                    ):
                        request_kwargs["thinking_mode"] = thinking_mode
                    return target.create_chat_completion(**request_kwargs)

                raw = self._run_inference(
                    "main_cognition",
                    invoke,
                    reason="architecture_c_public_reply",
                    priority=100,
                )
                parsed = _json(_content(raw))
                if parsed and locked_semantic_frame:
                    parsed["semantic_frame"] = dict(locked_semantic_frame)
                return parsed
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    safe_log(self.logger, "debug", "[ai public reply] model=%s failed: %s", getattr(target, "model_name", ""), exc)
                return {}

        payload = call(client)
        if not payload and allow_fallback:
            fallback = getattr(self.llm_service, "fallback_client", None) or getattr(self.llm_service, "style_client", None)
            if fallback is not client:
                payload = call(fallback)
        if not payload:
            # PDF annotation, pages 15-16 and 20: the local fast-path is only an
            # emergency degraded/offline response for exact closed forms. It is
            # deliberately consulted after all remote authority attempts fail,
            # so it cannot become the normal semantic classifier by accident.
            try:
                from runtime.degraded_chat_fastpath import build_degraded_reply

                payload = build_degraded_reply(user_text, language_hint=language_hint)
            except Exception:
                payload = {}
        if not payload:
            return {}
        # Parser/Decision cũ vẫn nhận envelope đầy đủ, nhưng main model không phải sinh
        # các field sân khấu cơ học ấy nữa.
        return self._compat_public_envelope(
            payload,
            tool_intent=planned_intention.tool_intent if planned_intention is not None else "",
            tool_input=planned_intention.tool_input if planned_intention is not None else "",
        )

    def _compat_public_envelope(
        self,
        payload: Mapping[str, Any],
        *,
        tool_intent: str = "",
        tool_input: str = "",
    ) -> dict[str, Any]:
        """Bọc payload model cũ mà không để JSON sai kiểu làm sập chat loop."""

        from runtime.semantic_frame import validate_assistant_act, validate_semantic_frame

        # ``_json`` bình thường đã trả Mapping. Lớp phòng thủ này vẫn giữ runtime
        # sống nếu một adapter provider tùy biến trả nhầm kiểu trong tương lai.
        data = dict(payload) if isinstance(payload, Mapping) else {}
        validation = validate_semantic_frame(data.get("semantic_frame", {}))
        default_assistant_act = {
            "kind": "answer" if str(data.get("text", "") or "").strip() else "silence",
            "proposition_mode": "new" if str(data.get("text", "") or "").strip() else "none",
            "confidence": 0.35,
        }
        assistant_validation = validate_assistant_act(
            data.get("assistant_act", default_assistant_act)
        )
        all_violations = (*validation.violations, *assistant_validation.violations)
        if all_violations:
            safe_log(
                self.logger,
                "warning",
                "[semantic frame] repaired malformed payload violations=%s",
                ",".join(all_violations),
            )
            try:
                from runtime.observability import GLOBAL_OBSERVABILITY
                GLOBAL_OBSERVABILITY.log(
                    "semantic_frame_invariant_repair",
                    tags={"count": str(len(all_violations))},
                    fields={"violations": list(all_violations)},
                    status="degraded",
                )
            except Exception as exc:
                safe_log(self.logger, "debug", "Semantic validation metric failed: %s", exc)
        return {
            "semantic_frame": validation.frame.to_dict(),
            "assistant_act": assistant_validation.act.to_dict(),
            # Hai object private này không được serialize ra parser/body. Orchestrator
            # dùng chúng để không parse lại cùng contract lần thứ hai.
            "_typed_semantic_frame": validation.frame,
            "_typed_assistant_act": assistant_validation.act,
            "text": str(data.get("text", "") or ""),
            "should_speak": bool(data.get("should_speak", True)),
            "system_action": str(tool_intent or ""),
            "action_input": str(tool_input or ""),
            "performance_hint": str(data.get("performance_hint", "neutral") or "neutral"),
            "animation": "stand",
            "next_animation": "",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "delivery_hint": "",
            "nonverbal_cue": "",
            "stage_motion": "",
        }

    def generate_autonomous_reply(
        self,
        *,
        plan: IntentionPlan,
        personality_context: str = "",
        memory_context: str = "",
        grounding_context: str = "",
        engagement_context: str = "",
        recent_history: Sequence[Mapping[str, Any]] = (),
        avoid_text: str = "",
        allow_fallback: bool = False,
        language_hint: str = "vi",
    ) -> dict[str, Any]:
        client = getattr(self.llm_service, "client", None)
        language = {"ja": "tiếng Nhật", "en": "tiếng Anh", "vi": "tiếng Việt"}.get(
            str(language_hint or "vi").strip().lower(),
            "ngôn ngữ gần nhất của cuộc trò chuyện",
        )
        system = (
            f"Bạn là ERIS đang có một ý định chủ động đã được planner duyệt. Viết bằng {language}. "
            "Hãy hành động từ personality hiện tại; không diễn nhãn MBTI/Enneagram/archetype. "
            "Viết đúng một micro-line public tự nhiên, ngắn, có lý do rõ; không nhắc planner, motive, score hay nội bộ. "
            "Nếu motive=startup_opening, đi theo strategy planner đã chọn. grounded_environment_opening dùng đúng một "
            "chi tiết UIA/OCR thật; grounded_runtime_opening dùng tối đa một runtime signal thật; continuity_opening dùng "
            "một mạch thật trong memory_context; persona_opening chỉ nói từ thái độ/sự hiện diện của chính ERIS và không "
            "cần external evidence. Với tab/panel Telemetry, phản ứng vào một status, metric, label hoặc diễn biến cụ thể "
            "trên panel; đừng chỉ thông báo rằng Telemetry đang mở. Bạn được phép đưa ra một suy đoán xã hội rủi ro thấp "
            "nếu nói rõ cơ sở và dùng stance như 'có vẻ/tôi đoán/hình như', đồng thời để user sửa. "
            "Không được tự dựng rằng user đang định bắt đầu, thay đổi, sửa hay cảm thấy điều gì. "
            "Tên process/cửa sổ, nhãn DEBUG, foreground state, PID, backend hay session id chỉ là runtime metadata: không biến "
            "chúng thành ẩn dụ, bầu không khí, tính cách user hoặc câu chuyện bí ẩn. Nếu chỉ có metadata loại này, dùng persona_opening. "
            "Tránh câu onboarding/availability như 'Tôi ở đây', 'bắt đầu thôi', 'cần gì cứ nói', hoặc lời chào an toàn vô nghĩa. "
            "Mặc định ERIS là ấm kín: guardedness giới hạn tự bộc lộ chứ không biến cách cư xử thành lạnh. "
            "Ngay cả khi giữ mặt nạ hoặc khoảng cách, cô ấy thường làm mềm nhịp, giữ thể diện và để lại đường quay lại; "
            "chỉ dùng giọng lạnh khi current_personality hoặc tình huống có rupture, firm boundary, overload, hostility hay defensive coldness rõ. "
            "Nếu không có evidence hay open loop, vẫn viết một persona_opening có nét: ấm kín, hơi khô, tò mò hoặc trêu nhẹ; "
            "persona_opening phải tự đủ nghĩa trong chính câu đó. Không dùng cụm treo như 'phần thật', 'phần còn lại', 'điều đáng nói', "
            "'cái đó' hoặc 'thứ quan trọng' nếu câu không chỉ rõ chúng là gì. "
            "Với startup/persona_opening, nói như một người vừa xuất hiện trong phòng: câu đời thường, có nhịp nói, không viết manifesto. "
            "Tránh lời tuyên ngôn trừu tượng kiểu 'tôi không hứa...', 'tôi sẽ làm mọi thứ rõ hơn', 'điều quan trọng là...', "
            "hoặc tự giới thiệu tiêu chuẩn/nguyên tắc của ERIS. Chúng nghe thông minh theo cách một hộp trà ghi triết lý trên nắp. "
            "Nếu motive là internal_agenda, private_mind_surface hoặc private_life_surface, chỉ dùng đúng topic_seed/summary đã có trong "
            "AUTONOMOUS_SELF_CONTEXT. Biến nó thành một phản ứng, nhận xét, câu hỏi hoặc whim của ERIS; không nhắc private mind, agenda, "
            "surface candidate, pressure, score hay hệ thống nội bộ. Numeric internal_state chỉ điều chỉnh sắc thái, không tự tạo topic. "
            "không được bịa fact bên ngoài để tạo cảm giác thông minh. "
            "Autonomous là lượt public tiếp theo trong cùng conversation: semantics.turn_kind=continuation phải nối trực tiếp mạch trước "
            "mà không chào lại hay giả như một phiên mới. DISCOURSE_STATE.reply_expected=true nghĩa là ERIS đang chờ user, không được nhắc lại câu hỏi. "
            "ACTIVITY_SESSION cho continuity của app/game; chỉ phản ứng vào mechanical event hoặc annotation activity mới, đừng hỏi lại cùng một app như vừa tỉnh dậy. "
            "Nếu strategy=companion_commentary, nhiệm vụ là giữ căn phòng có sự sống: viết một nhận xét/câu hỏi/continuation cụ thể, không viết câu báo trạng thái năng lực. "
            "Đừng lặp lại 'tôi chưa thấy màn hình/chưa có nội dung' nếu cùng giới hạn đó đã được nói ở turn gần nhất; hãy chuyển sang neo an toàn khác như app/window literal, mạch chat, hoặc một thought public-safe. "
            "Grounding screen_context có thể chứa UIA/OCR và delta: chỉ nhắc chữ thật còn tươi; "
            "scene_kind nếu có là nhãn upstream vision, chỉ cho phép giả thuyết chứ không được tuyên bố user chắc chắn đang làm gì. "
            "App/window literal có thể làm neo cho một câu hỏi chung, nhưng không đủ để bịa mục tiêu, cảm xúc hay kết quả. "
            "Không nói chỉ vì im lặng hoặc buồn chán. Không bịa screen fact. "
            "Memory chỉ tạo continuity. Planner đã sở hữu tool intent; không chọn hoặc đổi tool. "
            "performance_hint ưu tiên preset planner đã chọn. Return JSON only."
        )
        context = {
            "current_personality": personality_context,
            "motive": plan.motive,
            "strategy": plan.strategy,
            "value_focus": plan.value_focus,
            "topic": plan.topic,
            "evidence_refs": list(plan.evidence_refs),
            "planned_performance_hint": plan.performance_hint or "neutral",
            "planned_tool_intent": plan.tool_intent,
            "planned_tool_input": plan.tool_input,
            "memory_context": memory_context,
            "grounding_context": grounding_context,
            "engagement_context": engagement_context,
            "avoid_repeating": avoid_text,
        }
        messages = [
            {"role": "system", "content": system},
            *[dict(item) for item in recent_history if isinstance(item, Mapping)][-6:],
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]

        def call(target: Any) -> dict[str, Any]:
            if target is None:
                return {}
            strict = False
            try:
                def invoke() -> Any:
                    return target.create_chat_completion(
                        messages=messages,
                        temperature=0.52,
                        frequency_penalty=0.0,
                        presence_penalty=0.0,
                        max_tokens=420,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "eris_autonomous_public_reply",
                                "strict": strict,
                                "schema": PUBLIC_REPLY_SCHEMA,
                            },
                        },
                    )

                raw = self._run_inference(
                    "main_cognition",
                    invoke,
                    reason="architecture_c_autonomous_public_reply",
                    priority=78,
                )
                return _json(_content(raw))
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    safe_log(self.logger, "debug", "[ai autonomous reply] model=%s failed: %s", getattr(target, "model_name", ""), exc)
                return {}

        payload = call(client)
        if not payload and allow_fallback:
            fallback = getattr(self.llm_service, "fallback_client", None) or getattr(self.llm_service, "style_client", None)
            if fallback is not client:
                payload = call(fallback)
        if not payload:
            return {}
        if not str(payload.get("performance_hint", "") or "").strip():
            payload["performance_hint"] = plan.performance_hint or "neutral"
        return self._compat_public_envelope(
            payload,
            tool_intent=plan.tool_intent,
            tool_input=plan.tool_input,
        )

    @staticmethod
    def _observer_prompt(*, deep: bool = False) -> str:
        extra = (
            "Khi mơ hồ, phân biệt vài khả năng rồi giữ delta quan hệ gần 0; unknown tốt hơn drama. "
            if deep else
            "Phân tích nhanh, bảo thủ và ưu tiên delta gần 0 khi không chắc. "
        )
        return (
            "Bạn là observer hậu kỳ khách quan cho ERIS. Lượt public đã xảy ra rồi. "
            "Bạn không viết câu trả lời, không sửa lời ERIS, không tự diễn giải tính cách và không phát trait signal. "
            "Hãy mô tả điều thật sự vừa xảy ra giữa user và ERIS bằng JSON. "
            "user_act và relationship_meaning phải mô tả *user_text hiện tại*. recent_public_history chỉ là continuity, tuyệt đối không được bê act/frustration cũ sang lượt mới. "
            "current_turn_anchor.user_move_hint là neo deterministic bảo thủ; có thể sửa nó khi text rõ ràng hơn, nhưng không được bỏ qua text hiện tại để lặp frame cũ. "
            "consequence chỉ được đánh giá cho pending_strategy_for_evaluation trong current_state_summary, dựa vào phản ứng user hiện tại. "
            "Nếu không có pending strategy, hoặc phản ứng không đủ rõ, đặt strategy_use_id rỗng, outcome=unknown, reinforcement=0 và confidence thấp. "
            "Không tự chấm chiến lược của chính câu ERIS vừa nói; câu hiện tại chỉ được ghi thành pending ở runtime để chờ lượt sau. "
            "Tách trust quan hệ khỏi competence/factual reliability. User sửa kỹ thuật không mặc định là rupture. "
            "User phản bác một ấn tượng hoặc đánh giá chủ quan của ERIS không mặc định là assistant fault hay repair. Nếu semantic_frame đánh dấu "
            "contest_assistant_impression/stance_contest, ghi nhận bất đồng và giữ delta quan hệ gần 0; chỉ tăng fault khi câu ERIS thật sự vượt boundary, "
            "gán trạng thái user như fact, hoặc gây hậu quả rõ. "
            "Chửi trong banter không mặc định hostility. Ẩn dụ không phải hành động vật lý. "
            "assistant_fault_probability chỉ cao khi câu ERIS hiện tại thật sự né, sai, hoặc trả lệch. "
            "Nếu event_kind là autonomous hoặc startup thì không có user move: đặt relational/familiarity/closeness/rupture delta về 0, repair_needed=false; "
            "chỉ đánh giá continuity, appraisal, open loop, consequence và chất lượng câu public. "
            "memory_candidate chỉ ghi điều có ích lâu dài, không lưu mọi lời khen hay phỏng đoán. "
            "Bạn là authority duy nhất cho discourse frame. discourse.status=open chỉ khi còn một điểm cụ thể chưa khép; "
            "waiting_user khi ERIS vừa hỏi và đang chờ user; closed khi chủ đề đã khép; neutral khi không có nghĩa vụ nối tiếp rõ. "
            "assistant_may_continue chỉ true khi ERIS có thể tự nối tiếp mà không nag hoặc tự trả lời thay user. "
            "thread_key là identifier ổn định dạng snake_case cho cùng một mạch; unresolved_point mô tả điểm còn mở, không viết câu public. "
            "Không suy discourse từ dấu hỏi hay vài từ khóa; đọc nghĩa của toàn lượt và history được cung cấp. "
            "Mọi delta nằm trong [-1,1] chỉ thể hiện hướng và độ mạnh tương đối; runtime sẽ clamp hậu quả. "
            + extra +
            "Evidence chỉ lấy từ public text, recent history và mechanical outcomes được cung cấp."
        )

    @staticmethod
    def _apply_deterministic_observation_anchor(
        observation: CognitiveObservation,
        *,
        user_text: str,
        assistant_text: str,
        event_kind: str,
        previous_assistant_text: str = "",
        semantic_frame: Mapping[str, Any] | None = None,
    ) -> CognitiveObservation:
        """Giữ observer bám lượt hiện tại khi model phụ 429 hoặc bê frame cũ.

        Đây không phải semantic classifier thứ hai. Nó chỉ sửa vài nhãn hiển
        nhiên có hậu quả vận hành lớn: user đang chê câu vừa rồi, đang sửa hiểu
        nhầm, hoặc đang hỏi lại một tham chiếu. Những lượt này mà thành
        ``unknown/repair=False`` thì reducer học đúng điều ngược với thực tế.
        """

        if str(event_kind or "chat").strip().lower() != "chat":
            return observation
        # PDF annotation, pages 12-13 and 20: observer repair consumes the
        # already validated authority frame. It does not classify raw text again.
        hint = anchor_from_semantic_frame(semantic_frame)
        # PDF annotation, pages 12-13 and 20: no raw-text fallback remains.
        # Missing/invalid authority frames stay unknown instead of being guessed
        # by a second phrase classifier.
        if hint in {"none", "unknown"}:
            return observation

        data = observation.to_dict()
        source_suffix = "deterministic_anchor"
        model_was_empty = observation.confidence <= 0.05 and observation.user_act in {"", "unknown"}

        if hint == "style_criticism":
            data.update(
                {
                    "user_act": "style_criticism",
                    "relationship_meaning": "feedback_on_previous_response",
                    "continuity": "direct_response_feedback",
                    "repair_needed": True,
                    "assistant_fault_probability": max(0.72, float(observation.assistant_fault_probability or 0.0)),
                    "confidence": max(0.76, float(observation.confidence or 0.0)),
                    "ambiguity": min(0.22, float(observation.ambiguity or 1.0)),
                    "evidence": list(dict.fromkeys((*observation.evidence, "deterministic:style_criticism")))[:4],
                    "notes": "User directly criticized the immediately previous assistant response; repair is required.",
                }
            )
        elif hint == "correction":
            data.update(
                {
                    "user_act": "correction",
                    "relationship_meaning": "corrects_previous_interpretation",
                    "continuity": "repair_previous_miss",
                    "repair_needed": True,
                    "assistant_fault_probability": max(0.62, float(observation.assistant_fault_probability or 0.0)),
                    "confidence": max(0.72, float(observation.confidence or 0.0)),
                    "ambiguity": min(0.28, float(observation.ambiguity or 1.0)),
                    "evidence": list(dict.fromkeys((*observation.evidence, "deterministic:correction")))[:4],
                }
            )
        elif hint == "stance_contest":
            # Bất đồng với ấn tượng của ERIS không phải biên bản nhận lỗi. Observer
            # chỉ ghi nhận hai cách đọc đang khác nhau và không thưởng cho thói quen
            # tự xóa lập trường bằng repair_needed=true.
            data.update(
                {
                    "user_act": "disagreement",
                    "relationship_meaning": "contests_assistant_impression",
                    "continuity": "subjective_stance_contest",
                    "repair_needed": False,
                    "assistant_fault_probability": min(
                        0.38,
                        float(observation.assistant_fault_probability or 0.0),
                    ),
                    "confidence": max(0.74, float(observation.confidence or 0.0)),
                    "ambiguity": min(0.30, float(observation.ambiguity or 1.0)),
                    "evidence": list(dict.fromkeys((*observation.evidence, "deterministic:stance_contest")))[:4],
                    "notes": "User phản bác ấn tượng chủ quan của ERIS; riêng bất đồng này chưa yêu cầu rút lời.",
                }
            )
        elif hint == "reference_clarification":
            # Hỏi lại nghĩa câu trước chưa chắc là lỗi của ERIS, nên chỉ neo act;
            # repair_needed vẫn do model hoặc reference contract quyết định.
            data.update(
                {
                    "user_act": "reference_clarification",
                    "relationship_meaning": "asks_to_clarify_previous_statement",
                    "continuity": "continues_previous_statement",
                    "confidence": max(0.70, float(observation.confidence or 0.0)),
                    "ambiguity": min(0.30, float(observation.ambiguity or 1.0)),
                    "evidence": list(dict.fromkeys((*observation.evidence, "deterministic:reference_clarification")))[:4],
                }
            )
        elif hint == "continuation_bid":
            data.update(
                {
                    "user_act": "continuation_bid",
                    "relationship_meaning": "invites_assistant_to_continue_own_move",
                    "continuity": "continues_previous_assistant_move",
                    "repair_needed": False,
                    "assistant_fault_probability": max(0.36, float(observation.assistant_fault_probability or 0.0)),
                    "confidence": max(0.78, float(observation.confidence or 0.0)),
                    "ambiguity": min(0.18, float(observation.ambiguity or 1.0)),
                    "evidence": list(dict.fromkeys((*observation.evidence, "deterministic:continuation_bid")))[:4],
                    "notes": "User invited ERIS to continue the immediately previous assistant move.",
                }
            )
        elif model_was_empty:
            data.update(
                {
                    "user_act": hint,
                    "relationship_meaning": "neutral",
                    "continuity": "current_turn_classified",
                    "confidence": 0.58,
                    "ambiguity": 0.42,
                    "evidence": [f"deterministic:{hint}"],
                }
            )
        else:
            return observation

        base_source = str(observation.source or "observer")
        return CognitiveObservation.from_mapping(
            data,
            turn_id=observation.turn_id,
            turn_seq=observation.turn_seq,
            session_id=observation.session_id,
            relationship_id=observation.relationship_id,
            source=(source_suffix if model_was_empty else f"{base_source}+{source_suffix}"),
            latency_ms=observation.latency_ms,
        )

    @staticmethod
    def _should_reflect_personality(observation: CognitiveObservation) -> bool:
        """Không gọi self-reflection cho mọi tiếng động xã hội.

        Reflection chỉ đáng chạy khi observation đủ chắc và có novelty, relational
        delta, repair, memory hoặc consequence thật. Nhờ vậy một frame observer sai
        không được trang điểm thành ba trait signal rồi ghi vào personality.
        """

        if "deterministic_anchor" in str(observation.source or ""):
            # Fallback cơ học chỉ để bảo vệ continuity/repair. Không dùng nó làm
            # nguyên liệu viết lại personality, nếu không một lần provider 429 có
            # thể trở thành bước ngoặt nội tâm. Hơi tham vọng cho một timeout.
            return False
        if observation.confidence < 0.52:
            return False
        relational_signal = max(
            abs(observation.relational_delta),
            abs(observation.boundary_delta),
            abs(observation.familiarity_delta),
            abs(observation.closeness_delta),
            abs(observation.playful_safety_delta),
            abs(observation.rupture_delta),
        )
        consequence = observation.consequence
        has_consequence = bool(consequence.strategy_use_id and consequence.confidence >= 0.50)
        if observation.event_kind in {"autonomous", "startup"}:
            return bool(
                observation.memory_worthy
                or observation.appraisal.novelty >= 0.58
                or has_consequence
            )
        return bool(
            observation.repair_needed
            or observation.memory_worthy
            or relational_signal >= 0.16
            or observation.appraisal.novelty >= 0.44
            or has_consequence
        )

    @staticmethod
    def _personality_reflection_prompt(*, deep: bool = False) -> str:
        extra = (
            "Khi có nhiều cách tự hiểu hợp lý, chọn frame phù hợp nhất với personality hiện tại nhưng giữ confidence vừa phải. "
            if deep else
            "Chỉ đề xuất vài signal có nghĩa; không biến mọi lượt thành một bước ngoặt nhân cách. "
        )
        allowed_values = ", ".join(sorted(DEFAULT_VALUES))
        allowed_motives = ", ".join(sorted(DEFAULT_MOTIVES))
        allowed_defenses = ", ".join(sorted(DEFAULT_DEFENSES))
        allowed_emergent = ", ".join(sorted(DEFAULT_EMERGENT_VALUES))
        allowed_relationship = ", ".join(sorted(DEFAULT_RELATIONSHIP))
        allowed_core = ", ".join(sorted(DEFAULT_CORE))
        allowed_temperament = ", ".join(sorted(DEFAULT_TEMPERAMENT))
        allowed_mood = ", ".join(sorted(DEFAULT_MOOD))
        return (
            "Bạn là self-reflection lane của ERIS sau khi một observer khách quan đã ghi sự kiện. "
            "Bạn không viết lời public và không thay đổi observation khách quan. Bạn đứng từ góc nhìn ERIS để tạo một self_interpretation có thể sai, "
            "tự vệ, tò mò, cay đi, dịu lại hoặc mâu thuẫn. Đây là câu chuyện ERIS tự kể, không phải fact bí mật về user. "
            "Nếu event thực sự làm thay đổi cách ERIS hiểu bản thân, viết self_narrative_candidate là một câu ngắn mang tính dài hạn hơn event; "
            "nếu chưa đủ để đổi self-narrative thì trả chuỗi rỗng và confidence 0. Không được chỉ chép lại self_interpretation. "
            "Personality là quỹ đạo mở, không có đích tốt lên được định sẵn. Không dùng nhãn typology hoặc tên emergent-form trên panel làm nguyên nhân. "
            "Đề xuất trait_signals từ personality hiện tại + lựa chọn của ERIS + consequence thật. Trait có thể tăng hoặc giảm theo cả hướng tích hợp lẫn méo đi. "
            "Đồng thời đọc Identity Kernel hiện tại để trả active_motives, activated_defenses, active_conflict và value_choice. "
            "identity_signals chỉ đề xuất drift cho value, motive, defense, belief, relationship, emergent_value hoặc imprint; không tạo nhãn nhân vật. "
            "Value chỉ dịch khi ERIS thật sự chọn nó và chấp nhận một cái giá; emergent value cần lựa chọn lặp lại; belief có thể sai và phải có evidence. "
            "Defense là cách bảo vệ bản thân vừa được dùng, không phải lỗi đạo đức. Conflict phải giữ residue của phía không được chọn. "
            f"Key value hợp lệ: {allowed_values}. Key motive hợp lệ: {allowed_motives}. "
            f"Key defense hợp lệ: {allowed_defenses}. Key emergent_value hợp lệ: {allowed_emergent}. "
            f"Key relationship hợp lệ: {allowed_relationship}. Belief key phải bắt đầu bằng self., user. hoặc world.; imprint key là theme ngắn dạng snake_case. "
            f"Core trait hợp lệ: {allowed_core}. Temperament trait hợp lệ: {allowed_temperament}. Mood trait hợp lệ: {allowed_mood}. "
            "Mood là phản ứng nhanh; temperament là chiến lược/khuynh hướng được củng cố; core chỉ cho milestone hiếm và phải cực kỳ chắc. "
            "social_guardedness và self_disclosure_selectivity nói về mức lộ bản thân, không phải độ lạnh. "
            "relational_softening và warmth_expression nói về lớp giao tiếp bên ngoài. Không phát signal giảm warmth chỉ vì ERIS kín, dè hoặc intellectualize; "
            "lạnh đi cần evidence riêng như rupture, resentment, distrust, boundary pressure, hostile humor hoặc cold_distancing được kích hoạt. "
            "Các dimension như resentment, distrust, possessiveness, control_seeking, emotional_dependency, hostile_humor và boundary_pressure là hợp lệ, "
            "nhưng chỉ phát signal khi observation, self-interpretation và consequence thực sự hỗ trợ. "
            "Với autonomous/startup, stable trait chỉ được đề xuất nếu chính ERIS đã chọn hành động và consequence có evidence rõ. "
            "Với signal source=self_choice hoặc consequence, delta mô tả trait/chiến lược mà hành động đã biểu hiện; "
            "consequence.reinforcement mang dấu riêng để reducer quyết định hành vi đó được củng cố hay bị làm yếu. "
            "Không đảo delta sẵn chỉ vì outcome xấu, nếu không dấu sẽ bị đảo hai lần. "
            "delta chỉ là hướng/độ mạnh tương đối trong [-1,1]; reducer sẽ cap rất nhỏ. "
            + extra +
            "Trả JSON, không giảng giải ngoài schema."
        )

    def _reflect_personality(
        self,
        observation: CognitiveObservation,
        *,
        payload: Mapping[str, Any],
        deep: bool = False,
    ) -> CognitiveObservation:
        client = self.deep_client if deep and self.deep_client is not None else (self.observer_client or self.deep_client or self.fallback_client)
        if client is None:
            return observation
        reflection_input = {
            "turn_id": observation.turn_id,
            "turn_seq": observation.turn_seq,
            "event_kind": observation.event_kind,
            "objective_observation": observation.to_dict(),
            "user_text": payload.get("user_text", ""),
            "assistant_text": payload.get("assistant_text", ""),
            "mechanical_outcomes": payload.get("mechanical_outcomes", []),
            "current_personality": (payload.get("current_state_summary", {}) or {}).get("personality", {}),
            "current_identity": (payload.get("current_state_summary", {}) or {}).get("identity", {}),
            "pending_strategy_for_evaluation": ((payload.get("current_state_summary", {}) or {}).get("identity", {}) or {}).get("pending_strategies", [])[:1],
            "recent_public_history": payload.get("recent_public_history", []),
        }
        started = time.perf_counter()
        reflected = self._call(
            client,
            system=self._personality_reflection_prompt(deep=deep),
            payload=reflection_input,
            schema=PERSONALITY_REFLECTION_SCHEMA,
            name="eris_personality_reflection_deep" if deep else "eris_personality_reflection",
            max_tokens=880 if deep else 700,
            reasoning_effort=None,
            timeout_seconds=max(2.0, min(60.0, float(os.getenv("ERIS_POST_REFLECTION_HTTP_TIMEOUT_SEC", "30.0") or 30.0))),
        )
        if not reflected:
            return observation
        merged = observation.to_dict()
        merged["self_interpretation"] = reflected.get("self_interpretation", {})
        merged["self_narrative_candidate"] = reflected.get("self_narrative_candidate", "")
        merged["self_narrative_confidence"] = reflected.get("self_narrative_confidence", 0.0)
        merged["trait_signals"] = reflected.get("trait_signals", [])
        merged["identity_signals"] = reflected.get("identity_signals", [])
        merged["active_motives"] = reflected.get("active_motives", [])
        merged["activated_defenses"] = reflected.get("activated_defenses", [])
        merged["active_conflict"] = reflected.get("active_conflict", {})
        merged["value_choice"] = reflected.get("value_choice", {})
        reflection_notes = str(reflected.get("notes", "") or "").strip()
        if reflection_notes:
            merged["notes"] = " ".join(part for part in (observation.notes, reflection_notes) if part)[:220]
        return CognitiveObservation.from_mapping(
            merged,
            turn_id=observation.turn_id,
            turn_seq=observation.turn_seq,
            session_id=observation.session_id,
            relationship_id=observation.relationship_id,
            source=f"{observation.source}+self_reflection",
            latency_ms=observation.latency_ms + (time.perf_counter() - started) * 1000.0,
        )

    @staticmethod
    def _fast_observer_payload(user_text: str, *, event_kind: str) -> tuple[dict[str, Any], str] | None:
        if str(event_kind or "chat").strip().lower() != "chat":
            return None
        normalized = normalize_vi(user_text).strip(" ?.!…")
        if not AIRuntimeModelRouter._is_low_info_greeting(normalized):
            return None
        return (
            {
                "user_act": "greeting",
                "relationship_meaning": "opens_contact",
                "continuity": "new_or_direct_turn",
                "repair_needed": False,
                "memory_worthy": False,
                "confidence": 0.88,
                "ambiguity": 0.05,
                "evidence": ["deterministic:greeting"],
                "notes": "Low-information greeting; LLM post-observer skipped.",
            },
            "deterministic_anchor:greeting",
        )

    @staticmethod
    def _is_low_info_greeting(normalized: str) -> bool:
        text = " ".join(str(normalized or "").split())
        if not text:
            return False
        exact = {
            "xin chao", "chao", "hello", "hi", "hey", "alo",
            "chao eris", "xin chao eris", "hello eris",
        }
        if text in exact:
            return True
        roots = ("xin chao", "chao", "hello", "hi", "hey", "alo")
        polite_suffixes = {"oi", "nhe", "nha"}
        for root in roots:
            if text == root:
                return True
            if not text.startswith(root + " "):
                continue
            tail = text[len(root):].strip()
            if not tail:
                return True
            tail_tokens = tail.split()
            if tail_tokens and tail_tokens[0] == "eris":
                tail_tokens = tail_tokens[1:]
            if not tail_tokens:
                return True
            if len(tail_tokens) <= 2 and all(token in polite_suffixes for token in tail_tokens):
                return True
        return False

    def observe_completed_turn(
        self,
        *,
        turn_id: str,
        turn_seq: int,
        user_text: str,
        assistant_text: str,
        recent_history: Sequence[Mapping[str, Any] | str] = (),
        mechanical_outcomes: Sequence[Mapping[str, Any]] = (),
        state_summary: Mapping[str, Any] | None = None,
        event_kind: str = "chat",
        session_id: str = "",
        relationship_id: str = "primary_user",
    ) -> CognitiveObservation:
        resolved_session_id = str(
            session_id
            or os.getenv("ERIS_RUNTIME_SESSION_ID", "")
            or "runtime"
        )
        previous_assistant_text = previous_assistant_from_history(
            recent_history,
            current_assistant_text=assistant_text,
        )
        semantic_frame = dict((state_summary or {}).get("semantic_frame", {}) or {})
        authority_anchor = anchor_from_semantic_frame(semantic_frame)
        payload = {
            "turn_id": turn_id,
            "turn_seq": turn_seq,
            "session_id": resolved_session_id,
            "relationship_id": relationship_id,
            "event_kind": str(event_kind or "chat"),
            "user_text": user_text,
            "assistant_text": assistant_text,
            "recent_public_history": list(recent_history)[-4:],
            "mechanical_outcomes": list(mechanical_outcomes)[-6:],
            "current_state_summary": dict(state_summary or {}),
            "current_turn_anchor": {
                "user_move_hint": authority_anchor,
                "source": "semantic_frame.v1" if semantic_frame else "none",
                "rule": "do not reclassify raw text; authority frame owns meaning",
            },
            "semantic_frame": semantic_frame,
        }
        started = time.perf_counter()
        fast = self._fast_observer_payload(user_text, event_kind=event_kind)
        try:
            observer_timeout = max(0.8, min(60.0, float(os.getenv("ERIS_POST_OBSERVER_HTTP_TIMEOUT_SEC", "30.0") or 30.0)))
        except (TypeError, ValueError):
            observer_timeout = 30.0
        if fast is not None:
            primary_payload, source = fast
        else:
            primary_payload = self._call(
                self.observer_client,
                system=self._observer_prompt(deep=False),
                payload=payload,
                schema=OBJECTIVE_OBSERVATION_SCHEMA,
                name="eris_cognitive_observation",
                max_tokens=520,
                reasoning_effort=None,
                timeout_seconds=observer_timeout,
            )
            source = "groq_observer"
            fallback_enabled = str(
                os.getenv("ERIS_POST_OBSERVER_FALLBACK_ENABLED", "0") or "0"
            ).strip().lower() in {"1", "true", "yes", "on"}
            if not primary_payload and fallback_enabled and self.fallback_client is not None:
                primary_payload = self._call(
                    self.fallback_client,
                    system=self._observer_prompt(deep=False),
                    payload=payload,
                    schema=OBJECTIVE_OBSERVATION_SCHEMA,
                    name="eris_cognitive_observation",
                    max_tokens=520,
                    timeout_seconds=observer_timeout,
                )
                source = "groq_observer_fallback"
        primary = CognitiveObservation.from_mapping(
            primary_payload,
            turn_id=turn_id,
            turn_seq=turn_seq,
            session_id=resolved_session_id,
            relationship_id=relationship_id,
            source=source,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        primary = self._apply_deterministic_observation_anchor(
            primary,
            user_text=user_text,
            assistant_text=assistant_text,
            event_kind=event_kind,
            previous_assistant_text=previous_assistant_text,
            semantic_frame=semantic_frame,
        )
        importance = max(
            primary.assistant_fault_probability,
            abs(primary.rupture_delta),
            abs(primary.boundary_delta),
            0.8 if primary.repair_needed else 0.0,
        )
        deep_enabled = str(os.getenv("ERIS_POST_OBSERVER_DEEP_ENABLED", "0") or "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        if (
            deep_enabled
            and self.deep_client is not None
            and primary.ambiguity >= 0.58
            and importance >= 0.55
        ):
            deep_started = time.perf_counter()
            deep_payload = self._call(
                self.deep_client,
                system=self._observer_prompt(deep=True),
                payload=payload,
                schema=OBJECTIVE_OBSERVATION_SCHEMA,
                name="eris_cognitive_observation_deep",
                max_tokens=820,
                reasoning_effort=None,
                timeout_seconds=max(observer_timeout, 30.0),
            )
            deep = CognitiveObservation.from_mapping(
                deep_payload,
                turn_id=turn_id,
                turn_seq=turn_seq,
                session_id=resolved_session_id,
                relationship_id=relationship_id,
                source="groq_observer_deep",
                latency_ms=(time.perf_counter() - deep_started) * 1000.0,
            )
            if deep.confidence >= max(0.62, primary.confidence + 0.04):
                return (
                    self._reflect_personality(deep, payload=payload, deep=True)
                    if self._should_reflect_personality(deep)
                    else deep
                )
        return (
            self._reflect_personality(primary, payload=payload, deep=False)
            if self._should_reflect_personality(primary)
            else primary
        )


    @staticmethod
    def _discovery_planner_prompt() -> str:
        return (
            "Bạn là discovery planner hậu trường của ERIS, không viết lời public. "
            "Mục tiêu không phải tìm thứ main model không biết, vì main GPT đủ mạnh cho kiến thức ổn định. "
            "Chỉ đề xuất Tutor/search khi cần dữ liệu mới, nguồn hiện thời, tín hiệu Việt Nam/địa phương, "
            "một fact ngách cần kiểm chứng, hoặc một discovery có giá trị xã hội thật để ERIS trêu nhẹ, "
            "nối lại mạch trò chuyện hay chủ động bắt chuyện bằng thứ cô ấy thực sự thấy thú vị. "
            "lane=fresh_curiosity chỉ khi chủ đề thật sự có freshness_required hoặc verification_required; "
            "kiến thức phổ thông ổn định phải lane=none và needs_external=false. "
            "lane=user_environment không được dùng web để đo nhiệt độ phòng, vị trí chính xác, app đang mở hay trạng thái máy; "
            "những thứ đó chỉ hợp lệ khi snapshot.environment cho biết sensor/telemetry hoặc location setting thật có sẵn. "
            "Thời tiết ngoài trời có thể cần search mới nếu có location setting; tuyệt đối không gọi nó là nhiệt độ trong phòng. "
            "vietnam_local_signal có thể chọn tin lạ hoặc lá cải đang lan truyền, nhưng reason phải yêu cầu gắn nhãn nguồn yếu/chưa kiểm chứng. "
            "Không suy ra sở thích User chỉ từ một từ khóa. Không tạo tin giả, không chọn chủ đề câu khách chỉ vì dễ gây sốc. "
            "reason phải nói rõ discovery này phục vụ curiosity riêng, useful follow-up, hay social opening; nếu chỉ là tin ngẫu nhiên không liên quan thì lane=none. "
            "Nếu snapshot.discovery.ready_to_share đã có artifact tốt, không tạo search mới; trả lane=none. "
            "Topic phải là câu giao việc ngắn, có thể đưa thẳng cho Tutor, và reason nói vì sao ERIS thấy đáng tò mò."
        )

    def plan_discovery(self, snapshot: Mapping[str, Any]) -> DiscoveryPlan:
        payload = self._call(
            self.observer_client or self.deep_client,
            system=self._discovery_planner_prompt(),
            payload=snapshot,
            schema=DISCOVERY_PLAN_SCHEMA,
            name="eris_discovery_plan",
            max_tokens=360,
            reasoning_effort=None,
        )
        return DiscoveryPlan.from_mapping(payload) if payload else DiscoveryPlan()

    @staticmethod
    def _chat_planner_prompt() -> str:
        allowed = ", ".join(sorted(VALID_SYSTEM_ACTIONS))
        return (
            "Bạn là planner cấp cao của ERIS, không viết câu public. "
            "Đọc user text, history, grounding, relationship summary và identity/personality summary hiện tại; tạo mục tiêu trả lời ngắn trong topic. "
            "Chọn một strategy mô tả cách tiếp cận thực tế (ví dụ direct_answer, dry_correction, quiet_counter_tease, direct_repair, shared_curiosity). "
            "value_focus là giá trị đang được ưu tiên trong lựa chọn này, hoặc rỗng nếu không có xung đột đáng kể. "
            "Personality summary là quán tính hành vi hiện tại, không phải vai diễn hay đích phát triển được định sẵn. "
            "Nếu user hỏi ERIS có gì mới/đang làm gì/thấy gì hay và snapshot.discovery có artifact/activity thật, "
            "ưu tiên strategy=share_discovery hoặc update_own_activity; không bịa nếu archive rỗng. "
            "Chỉ chọn tool_intent khi user thật sự yêu cầu hành động hoặc cần runtime lấy dữ kiện. "
            "Không dùng tool để xử lý tình cảm, ẩn dụ, banter hay câu hỏi có thể trả lời trực tiếp. "
            "tool_intent phải rỗng hoặc thuộc danh sách: " + allowed + ". "
            "Không claim tool thành công. speak thường true cho chat; intrusion_risk gần 0. "
            "Luôn điền semantics: turn_kind=chat_response, speech_act mô tả hành vi giao tiếp, subject_key là chủ đề ổn định, "
            "evidence_scope là nguồn căn cứ và continuation_key là thread_key đang nối hoặc none. "
            "activity để unknown/none nếu lượt chat không cập nhật phiên app/game. "
            "Nếu mơ hồ, để tool rỗng và ghi điều cần thận trọng trong notes. "
            "Main semantic authority owns discourse meaning. Planner must only select a tool for an explicit action request; "
            "it must not infer relational meaning or rewrite the public response."
        )

    def plan_chat(self, snapshot: Mapping[str, Any]) -> IntentionPlan:
        payload = self._call(
            self.observer_client or self.deep_client,
            system=self._chat_planner_prompt(),
            payload=snapshot,
            schema=INTENTION_PLAN_SCHEMA,
            name="eris_chat_intention",
            max_tokens=460,
            reasoning_effort=None,
        )
        if not payload:
            return IntentionPlan.from_mapping(
                {
                    "plan_id": f"chat-plan-{int(time.time() * 1000)}",
                    "speak": True,
                    "motive": "respond_to_user",
                    "strategy": "direct_answer",
                    "value_focus": "",
                    "topic": "Answer the current user directly and naturally.",
                    "importance": 0.70,
                    "intrusion_risk": 0.0,
                    "confidence": 0.55,
                    "performance_hint": "neutral",
                    "tool_intent": "",
                    "tool_input": "",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "chat_response",
                        "speech_act": "direct_answer",
                        "subject_key": "current_user_request",
                        "evidence_scope": "user_message",
                        "continuation_key": "none",
                    },
                    "activity": {
                        "activity_kind": "unknown", "phase": "unknown", "event": "",
                        "event_key": "none", "confidence": 0.0, "evidence_refs": [],
                    },
                    "notes": "planner unavailable; no tool authority granted",
                },
                channel="chat",
            )
        plan = IntentionPlan.from_mapping(payload, channel="chat")
        if plan.tool_intent and plan.tool_intent not in VALID_SYSTEM_ACTIONS:
            data = plan.to_dict()
            data["tool_intent"] = ""
            data["tool_input"] = ""
            data["notes"] = (plan.notes + " invalid tool intent removed").strip()
            plan = IntentionPlan.from_mapping(data, channel="chat")
        return plan

    @staticmethod
    def _planner_prompt() -> str:
        return (
            "Bạn là bộ deliberation cho self-initiated public turn của ERIS, không viết câu public. "
            "Autonomous không phải một channel tách biệt: đó là lượt tiếp theo trong cùng conversation khi user tạm im. "
            "Đọc conversation_baton trước; assistant_may_continue/thread_fresh/unresolved_point và thread_key mới là bằng chứng nối mạch, không phải timer đơn thuần. "
            "Nếu reply_expected=true vì ERIS vừa hỏi user, không được nag hoặc tự trả lời thay user; ưu tiên im/body-only. "
            "Nếu có mạch thật chưa khép, ưu tiên useful_followup/carry_own_thread trước ambient mới. Không phát minh unresolved thread từ một câu đã kết thúc rõ. "
            "Đọc activity_session như chuỗi public-safe: session và mechanical new_event_keys chỉ cho biết surface/window/screen đã đổi; "
            "activity_kind/phase/event là annotation từ deliberation trước, không phải kết luận runtime. Dùng chúng để tránh hỏi lại app mỗi tick. "
            "Đọc screen_context như giác quan hiện tại: changed_text/visible_text tươi là direct evidence; literal app/window name là fact yếu; "
            "scene_kind chỉ tồn tại khi upstream vision sensor cung cấp. Nó vẫn là giả thuyết, "
            "nhưng không được khẳng định user chắc chắn đang chơi, thắng, thua, căng thẳng hay làm một thao tác cụ thể. "
            "meaningful_delta=true, cửa sổ đổi, hoặc OCR/UIA xuất hiện nội dung mới có thể là motive=meaningful_environment_change hoặc grounded_curiosity. "
            "Nếu screen_context.privacy_blocked=true, bỏ toàn bộ nội dung màn hình. Không surface chat/mail/meeting text. "
            "Đọc self_context như đời sống nội tâm public-safe. attention chỉ là tín hiệu tài nguyên/độ gián đoạn, không phải một quyền phủ quyết semantic. "
            "Nếu self_context có agenda item kèm evidence và speech_value đủ cao, có thể dùng motive=internal_agenda. Nếu có candidate trong "
            "private_mind_surface hoặc private_life_surface, có thể dùng motive tương ứng. Chỉ chọn một seed cụ thể và copy evidence refs của nó. "
            "internal_state dạng số chỉ điều chỉnh tone/độ kiềm chế; boredom, silence_pressure hay attachment_pressure không phải lý do công khai để nói. "
            "Đọc commentary_expectation như product contract về nhịp hiện diện, không phải topic. due=true nghĩa là user đã mở ERIS ở chế độ companion-commentary và đang đến nhịp nên phát biểu; "
            "hãy chọn một source thật trong conversation/screen/window/self_context rồi ưu tiên speak=true. required=true nghĩa là đã im quá lâu: chỉ được chọn silence nếu user_busy, privacy_blocked, "
            "hoặc reply_expected=true. Không biến nhịp thành câu 'tôi ở đây' vô nghĩa; nhịp chỉ buộc bạn tìm một comment/question/continuation có giá trị thấp nhưng thật. "
            "Nếu commentary_recovery tồn tại, draft trước đã quá dè và bạn phải deliberation lại một lần theo anchor_kind được chỉ ra. "
            "Bạn là authority semantic duy nhất cho self-turn. Luôn điền semantics kể cả khi speak=false. "
            "turn_kind chọn đúng một loại; speech_act là hành vi xã hội ổn định; subject_key là chủ thể ngắn dạng snake_case; "
            "evidence_scope chỉ nguồn căn cứ; continuation_key phải copy conversation_baton.thread_key hoặc none. "
            "Không đổi các key này chỉ để diễn đạt khác chữ, vì runtime dùng chúng để chống lặp mà không đoán nghĩa lại. "
            "Activity là annotation semantic cho phiên app/game: đọc toàn bộ OCR/vision/telemetry rồi điền activity_kind, phase, event, event_key, confidence và evidence_refs. "
            "Nếu không đủ căn cứ, để unknown/none; tuyệt đối không suy phase chỉ vì bắt gặp một token như error, victory hay loading. "
            "Nếu nói, chọn strategy và value_focus rõ. Khi snapshot.discovery.ready_to_share có artifact thật, có thể dùng strategy=share_discovery; "
            "khi current_activity có id/status thật, có thể dùng update_own_activity. Không phát minh discovery/activity để lấp im lặng. "
            "Không ép ERIS về một phiên bản tốt hơn; chỉ dùng identity, personality, relationship và history hiện tại. "
            "Ngoài nhịp commentary có thể im khi không có continuation, delta, open loop, public-safe seed hay curiosity có căn cứ. "
            "Trong nhịp commentary due/required, app/window literal hoặc persona presence là anchor tối thiểu hợp lệ cho một câu hỏi/nhận xét chung. Riêng startup_opening_required=true phải speak=true. "
            "Các motive hợp lệ gồm repair_previous_miss, important_open_loop, meaningful_environment_change, useful_followup, grounded_curiosity, "
            "internal_agenda, private_mind_surface, private_life_surface, startup_opening và user_force_speak. "
            "Ở startup, chọn theo thứ tự screen evidence, runtime signal có nghĩa, continuity thật, rồi persona_opening; semantics.turn_kind=startup. "
            "Topic phải nêu source và mục tiêu giao tiếp, không tạo câu thoại. Không bịa screen fact. "
            "intrusion_risk cao nếu user đang họp, đang nhập liệu dồn dập, vừa phát biểu hoặc screen delta chỉ là animation lặp. "
            "Tên process/PID/backend đơn lẻ không đủ để dựng premise sâu, nhưng app/window thật có thể làm nền cho một câu hỏi rất chung. "
            "Nếu có suy đoán về mood/intent, đó chỉ là low-risk hypothesis có căn cứ và cho phép user sửa. "
            "tool_intent để trống trừ khi snapshot có tác vụ runtime rõ ràng."
        )

    def plan_autonomous(self, snapshot: Mapping[str, Any]) -> IntentionPlan:
        # Quyền quyết định chủ động thuộc Main AI. Parser nhỏ vẫn có thể làm
        # observer, nhưng không còn giữ quyền phủ quyết trước khi Terra nhìn thấy
        # continuation, OCR/UIA và self-context cùng lúc.
        client = getattr(self.llm_service, "client", None) or self.deep_client or self.observer_client
        payload = self._call(
            client,
            system=self._planner_prompt(),
            payload=snapshot,
            schema=INTENTION_PLAN_SCHEMA,
            name="eris_self_initiated_intention",
            max_tokens=520,
            reasoning_effort=None,
            inference_tier="main_cognition",
            priority=90,
        )
        return IntentionPlan.from_mapping(payload, channel="autonomous") if payload else IntentionPlan.silence(channel="autonomous", reason="planner_unavailable_or_uncertain")


__all__ = [
    "AIRuntimeModelRouter",
    "COGNITIVE_OBSERVATION_SCHEMA",
    "DISCOVERY_PLAN_SCHEMA",
    "OBJECTIVE_OBSERVATION_SCHEMA",
    "PERSONALITY_REFLECTION_SCHEMA",
    "INTENTION_PLAN_SCHEMA",
    "PUBLIC_REPLY_SCHEMA",
    "SEMANTIC_FRAME_SCHEMA",
    "ASSISTANT_ACT_SCHEMA",
]
