# -*- coding: utf-8 -*-
"""Model router cho observer và intention planner của kiến trúc C."""

from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from typing import Any, Mapping, Sequence

from actions.contracts import VALID_SYSTEM_ACTIONS

from .contracts import CognitiveObservation, IntentionPlan
from .discovery import DiscoveryPlan
from .identity import CONFLICT_TEMPLATES, DEFAULT_DEFENSES, DEFAULT_EMERGENT_VALUES, DEFAULT_MOTIVES, DEFAULT_RELATIONSHIP, DEFAULT_VALUES




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
        "consequence",
        "trait_signals",
        "identity_signals",
        "active_motives",
        "activated_defenses",
        "active_conflict",
        "value_choice",
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
        if name not in {"self_interpretation", "trait_signals", "identity_signals", "active_motives", "activated_defenses", "active_conflict", "value_choice"}
    ],
    "properties": {
        name: value
        for name, value in COGNITIVE_OBSERVATION_SCHEMA["properties"].items()
        if name not in {"self_interpretation", "trait_signals", "identity_signals", "active_motives", "activated_defenses", "active_conflict", "value_choice"}
    },
}

PERSONALITY_REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "self_interpretation", "trait_signals", "identity_signals",
        "active_motives", "activated_defenses", "active_conflict",
        "value_choice", "notes"
    ],
    "properties": {
        "self_interpretation": COGNITIVE_OBSERVATION_SCHEMA["properties"]["self_interpretation"],
        "trait_signals": COGNITIVE_OBSERVATION_SCHEMA["properties"]["trait_signals"],
        "identity_signals": COGNITIVE_OBSERVATION_SCHEMA["properties"]["identity_signals"],
        "active_motives": COGNITIVE_OBSERVATION_SCHEMA["properties"]["active_motives"],
        "activated_defenses": COGNITIVE_OBSERVATION_SCHEMA["properties"]["activated_defenses"],
        "active_conflict": COGNITIVE_OBSERVATION_SCHEMA["properties"]["active_conflict"],
        "value_choice": COGNITIVE_OBSERVATION_SCHEMA["properties"]["value_choice"],
        "notes": {"type": "string"},
    },
}




PUBLIC_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "should_speak", "performance_hint"],
    "properties": {
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
    try:
        value = json.loads(raw)
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return dict(value) if isinstance(value, Mapping) else {}
        except Exception:
            return {}


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
        policy = self.budget_policy
        if policy is not None and callable(getattr(policy, "run_queued", None)):
            return policy.run_queued(
                tier,
                func,
                reason=reason,
                priority=priority,
            )
        return func()

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
    ) -> dict[str, Any]:
        if client is None:
            return {}
        model_name = str(getattr(client, "model_name", "") or "")
        strict = model_name.startswith("openai/gpt-oss-")
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
                )

            raw = self._run_inference(
                "subconscious_4b",
                invoke,
                reason=name,
                priority=45 if "deep" in name else 35,
            )
            return _json(_content(raw))
        except Exception as exc:  # noqa: BLE001
            if self.logger is not None:
                try:
                    self.logger.debug("[ai runtime model] %s failed model=%s: %s", name, model_name, exc)
                except Exception:
                    pass
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
            "Nếu Current grounding có reference_repair_contract, đó là ưu tiên cao nhất của lượt: trả lời đúng cụm user đang hỏi "
            "trong câu ERIS ngay trước đó, xác nhận hoặc sửa nghĩa đen trước rồi mới thêm cá tính. Mẫu 'X là bạn/em á?' thường là "
            "câu hỏi định danh về X vừa được ERIS nói, không phải user đặt biệt danh mới. Không tự đánh giá user, không đảo chủ thể, "
            "không phát minh một premise khác để né câu hỏi. "
            "Memory chỉ là continuity, không chứng minh hiện tại. Grounding là nguồn thật cho màn hình/file/tool. "
            "Planner đã sở hữu tool intent; bạn không chọn, đổi hay claim tool đã thành công. "
            "performance_hint chỉ là một preset sân khấu ngắn, không viết stage direction vào text. Return JSON only."
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
        use_escalation: bool = False,
        reasoning_effort: str | None = None,
        allow_fallback: bool = False,
        language_hint: str = "vi",
        planned_intention: IntentionPlan | None = None,
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
            model_name = str(getattr(target, "model_name", "") or "")
            strict = model_name.startswith("openai/gpt-oss-")
            try:
                def invoke() -> Any:
                    return target.create_chat_completion(
                        messages=messages,
                        temperature=0.48,
                        frequency_penalty=0.0,
                        presence_penalty=0.0,
                        max_tokens=900 if reasoning_effort else 620,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "eris_public_reply",
                                "strict": strict,
                                "schema": PUBLIC_REPLY_SCHEMA,
                            },
                        },
                        reasoning_effort=reasoning_effort,
                    )

                raw = self._run_inference(
                    "main_cognition",
                    invoke,
                    reason="architecture_c_public_reply",
                    priority=100,
                )
                return _json(_content(raw))
            except Exception as exc:  # noqa: BLE001
                if self.logger is not None:
                    try:
                        self.logger.debug("[ai public reply] model=%s failed: %s", model_name, exc)
                    except Exception:
                        pass
                return {}

        payload = call(client)
        if not payload and allow_fallback:
            fallback = getattr(self.llm_service, "fallback_client", None) or getattr(self.llm_service, "style_client", None)
            if fallback is not client:
                payload = call(fallback)
        if not payload:
            return {}
        # Parser/Decision cũ vẫn nhận envelope đầy đủ, nhưng main model không phải sinh
        # các field sân khấu cơ học ấy nữa.
        return self._compat_public_envelope(
            payload,
            tool_intent=planned_intention.tool_intent if planned_intention is not None else "",
            tool_input=planned_intention.tool_input if planned_intention is not None else "",
        )

    @staticmethod
    def _compat_public_envelope(
        payload: Mapping[str, Any],
        *,
        tool_intent: str = "",
        tool_input: str = "",
    ) -> dict[str, Any]:
        return {
            "text": str(payload.get("text", "") or ""),
            "should_speak": bool(payload.get("should_speak", True)),
            "system_action": str(tool_intent or ""),
            "action_input": str(tool_input or ""),
            "performance_hint": str(payload.get("performance_hint", "neutral") or "neutral"),
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
            "Nếu không có evidence hay open loop, vẫn viết một persona_opening có nét: ấm kín, hơi khô, tò mò hoặc trêu nhẹ; "
            "không được bịa fact bên ngoài để tạo cảm giác thông minh. "
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
            model_name = str(getattr(target, "model_name", "") or "")
            strict = model_name.startswith("openai/gpt-oss-")
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
                    try:
                        self.logger.debug("[ai autonomous reply] model=%s failed: %s", model_name, exc)
                    except Exception:
                        pass
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
            "Chửi trong banter không mặc định hostility. Ẩn dụ không phải hành động vật lý. "
            "assistant_fault_probability chỉ cao khi câu ERIS hiện tại thật sự né, sai, hoặc trả lệch. "
            "Nếu event_kind là autonomous hoặc startup thì không có user move: đặt relational/familiarity/closeness/rupture delta về 0, repair_needed=false; "
            "chỉ đánh giá continuity, appraisal, open loop, consequence và chất lượng câu public. "
            "memory_candidate chỉ ghi điều có ích lâu dài, không lưu mọi lời khen hay phỏng đoán. "
            "Mọi delta nằm trong [-1,1] chỉ thể hiện hướng và độ mạnh tương đối; runtime sẽ clamp hậu quả. "
            + extra +
            "Evidence chỉ lấy từ public text, recent history và mechanical outcomes được cung cấp."
        )

    @staticmethod
    def _current_user_move_hint(user_text: str) -> str:
        """Neo rất mỏng cho observer, không thay thế semantic model.

        Mục tiêu chỉ là ngăn model nhỏ bám một frame cũ qua nhiều lượt. Taxonomy
        cố ý thô và ưu tiên `unknown` hơn việc đóng kịch tâm lý.
        """

        text = " ".join(str(user_text or "").casefold().split())
        if not text:
            return "none"
        if any(
            marker in text
            for marker in (
                "là bạn á", "là em á", "là bạn hả", "là em hả", "có phải bạn", "có phải em",
                "ý em là gì", "ý bạn là gì", "cái đó là gì", "cái này là gì", "tức là sao", "sao cơ",
            )
        ):
            return "reference_clarification"
        if any(
            marker in text
            for marker in (
                "là em nghĩ tôi sẽ", "là bạn nghĩ tôi sẽ", "ý em là tôi", "ý bạn là tôi",
                "em đang nghĩ tôi", "bạn đang nghĩ tôi",
            )
        ):
            return "correction"
        technical = (
            "code", "repo", "log", "bug", "lỗi", "file", "tts", "api", "runtime",
            "godot", "fix", "sửa", "debug", "panel", "model",
        )
        if any(token in text for token in technical):
            return "technical_request"
        if any(token in text for token in ("không phải", "ý tôi là", "tôi nói là", "sai rồi", "hiểu sai", "đọc lại")):
            return "correction"
        if any(token in text for token in ("chán", "tệ", "máy quá", "cứng quá", "nhạt", "phèn", "không hay")):
            return "style_criticism"
        if any(token in text for token in ("sến", "tình cảm", "ngọt", "dịu", "cộc lốc", "nói gọn", "nói thẳng")):
            return "style_request"
        if any(token in text for token in ("muốn tui quen", "muốn tôi quen", "thích tui", "thích tôi", "yêu tui", "yêu tôi")):
            return "request_reciprocity"
        if any(token in text for token in ("hả", "hong", "không")) and any(
            token in text for token in ("bạn muốn", "em muốn", "bạn thích", "em thích", "bạn nhớ", "em nhớ")
        ):
            return "request_reciprocity"
        if any(token in text for token in ("haha", "lmao", ":))", "=))", "khịa", "trêu")):
            return "play_bid"
        return "unknown"

    @staticmethod
    def _should_reflect_personality(observation: CognitiveObservation) -> bool:
        """Không gọi self-reflection cho mọi tiếng động xã hội.

        Reflection chỉ đáng chạy khi observation đủ chắc và có novelty, relational
        delta, repair, memory hoặc consequence thật. Nhờ vậy một frame observer sai
        không được trang điểm thành ba trait signal rồi ghi vào personality.
        """

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
        return (
            "Bạn là self-reflection lane của ERIS sau khi một observer khách quan đã ghi sự kiện. "
            "Bạn không viết lời public và không thay đổi observation khách quan. Bạn đứng từ góc nhìn ERIS để tạo một self_interpretation có thể sai, "
            "tự vệ, tò mò, cay đi, dịu lại hoặc mâu thuẫn. Đây là câu chuyện ERIS tự kể, không phải fact bí mật về user. "
            "Personality là quỹ đạo mở, không có đích tốt lên được định sẵn. Không dùng nhãn typology hoặc tên emergent-form trên panel làm nguyên nhân. "
            "Đề xuất trait_signals từ personality hiện tại + lựa chọn của ERIS + consequence thật. Trait có thể tăng hoặc giảm theo cả hướng tích hợp lẫn méo đi. "
            "Đồng thời đọc Identity Kernel hiện tại để trả active_motives, activated_defenses, active_conflict và value_choice. "
            "identity_signals chỉ đề xuất drift cho value, motive, defense, belief, relationship, emergent_value hoặc imprint; không tạo nhãn nhân vật. "
            "Value chỉ dịch khi ERIS thật sự chọn nó và chấp nhận một cái giá; emergent value cần lựa chọn lặp lại; belief có thể sai và phải có evidence. "
            "Defense là cách bảo vệ bản thân vừa được dùng, không phải lỗi đạo đức. Conflict phải giữ residue của phía không được chọn. "
            f"Key value hợp lệ: {allowed_values}. Key motive hợp lệ: {allowed_motives}. "
            f"Key defense hợp lệ: {allowed_defenses}. Key emergent_value hợp lệ: {allowed_emergent}. "
            f"Key relationship hợp lệ: {allowed_relationship}. Belief key phải bắt đầu bằng self., user. hoặc world.; imprint key là theme ngắn dạng snake_case. "
            "Mood là phản ứng nhanh; temperament là chiến lược/khuynh hướng được củng cố; core chỉ cho milestone hiếm và phải cực kỳ chắc. "
            "Các dimension như resentment, distrust, possessiveness, control_seeking, emotional_dependency, hostile_humor và boundary_pressure là hợp lệ, "
            "nhưng chỉ phát signal khi observation, self-interpretation và consequence thực sự hỗ trợ. "
            "Với autonomous/startup, stable trait chỉ được đề xuất nếu chính ERIS đã chọn hành động và consequence có evidence rõ. "
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
            reasoning_effort=(
                "medium" if deep else "low"
            ) if str(getattr(client, "model_name", "")).startswith("openai/gpt-oss-") else None,
        )
        if not reflected:
            return observation
        merged = observation.to_dict()
        merged["self_interpretation"] = reflected.get("self_interpretation", {})
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
            source=f"{observation.source}+self_reflection",
            latency_ms=observation.latency_ms + (time.perf_counter() - started) * 1000.0,
        )

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
    ) -> CognitiveObservation:
        payload = {
            "turn_id": turn_id,
            "turn_seq": turn_seq,
            "event_kind": str(event_kind or "chat"),
            "user_text": user_text,
            "assistant_text": assistant_text,
            "recent_public_history": list(recent_history)[-4:],
            "mechanical_outcomes": list(mechanical_outcomes)[-6:],
            "current_state_summary": dict(state_summary or {}),
            "current_turn_anchor": {
                "user_move_hint": self._current_user_move_hint(user_text),
                "rule": "classify current user_text first; history is continuity only",
            },
        }
        started = time.perf_counter()
        primary_payload = self._call(
            self.observer_client,
            system=self._observer_prompt(deep=False),
            payload=payload,
            schema=OBJECTIVE_OBSERVATION_SCHEMA,
            name="eris_cognitive_observation",
            max_tokens=650,
            reasoning_effort="low" if str(getattr(self.observer_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
        )
        source = "groq_observer"
        if not primary_payload and self.fallback_client is not None:
            primary_payload = self._call(
                self.fallback_client,
                system=self._observer_prompt(deep=False),
                payload=payload,
                schema=OBJECTIVE_OBSERVATION_SCHEMA,
                name="eris_cognitive_observation",
                max_tokens=650,
            )
            source = "groq_observer_fallback"
        primary = CognitiveObservation.from_mapping(
            primary_payload,
            turn_id=turn_id,
            turn_seq=turn_seq,
            source=source,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        importance = max(
            primary.assistant_fault_probability,
            abs(primary.rupture_delta),
            abs(primary.boundary_delta),
            0.8 if primary.repair_needed else 0.0,
        )
        if (
            self.deep_client is not None
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
                reasoning_effort="medium" if str(getattr(self.deep_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
            )
            deep = CognitiveObservation.from_mapping(
                deep_payload,
                turn_id=turn_id,
                turn_seq=turn_seq,
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
            "hoặc một fact ngách cần kiểm chứng trước khi ERIS mang về khoe. "
            "lane=fresh_curiosity chỉ khi chủ đề thật sự có freshness_required hoặc verification_required; "
            "kiến thức phổ thông ổn định phải lane=none và needs_external=false. "
            "lane=user_environment không được dùng web để đo nhiệt độ phòng, vị trí chính xác, app đang mở hay trạng thái máy; "
            "những thứ đó chỉ hợp lệ khi snapshot.environment cho biết sensor/telemetry hoặc location setting thật có sẵn. "
            "Thời tiết ngoài trời có thể cần search mới nếu có location setting; tuyệt đối không gọi nó là nhiệt độ trong phòng. "
            "vietnam_local_signal có thể chọn tin lạ hoặc lá cải đang lan truyền, nhưng reason phải yêu cầu gắn nhãn nguồn yếu/chưa kiểm chứng. "
            "Không suy ra sở thích User chỉ từ một từ khóa. Không tạo tin giả, không chọn chủ đề câu khách chỉ vì dễ gây sốc. "
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
            reasoning_effort="low" if str(getattr(self.observer_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
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
            "Nếu mơ hồ, để tool rỗng và ghi điều cần thận trọng trong notes."
            " Nếu snapshot.reference_repair.active=true, bắt buộc strategy=direct_repair, tool rỗng, và topic phải yêu cầu "
            "trả lời nghĩa đen của cụm trong previous_assistant_text trước. Không hiểu câu hỏi định danh thành biệt danh, banter hay đánh giá user."
        )

    def plan_chat(self, snapshot: Mapping[str, Any]) -> IntentionPlan:
        payload = self._call(
            self.observer_client or self.deep_client,
            system=self._chat_planner_prompt(),
            payload=snapshot,
            schema=INTENTION_PLAN_SCHEMA,
            name="eris_chat_intention",
            max_tokens=460,
            reasoning_effort="low" if str(getattr(self.observer_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
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
            "Bạn là intention planner của ERIS, không phải người viết câu public. "
            "Từ snapshot đã cho, gồm cả identity, personality và strategy history hiện tại, quyết định ERIS có một lý do đủ giá trị để chủ động nói hay không. "
            "Nếu nói, chọn strategy và value_focus rõ. Khi snapshot.discovery.ready_to_share có artifact thật, "
            "có thể dùng strategy=share_discovery; khi current_activity có id/status thật, có thể dùng update_own_activity. "
            "Không phát minh discovery hay activity chỉ để lấp im lặng. "
            "Không ép ERIS về một phiên bản tốt hơn; chỉ dùng quỹ đạo hiện tại để chọn ý định hợp lý. "
            "Mặc định autonomous thường là im lặng. Riêng khi snapshot.event_kind=startup và "
            "startup_opening_required=true, phải speak=true và chọn một route mở đầu rõ ràng. Các motive khác gồm: repair_previous_miss, "
            "important_open_loop, meaningful_environment_change, useful_followup, grounded_curiosity, "
            "hoặc user_force_speak khi snapshot.event_kind=force_speak và user đã yêu cầu hiện diện rõ ràng. "
            "Ở startup, chọn theo thứ tự: strong_opening_anchor => grounded_environment_opening; runtime_evidence có nghĩa => "
            "grounded_runtime_opening; open_loops/recent history/latest observation thật => continuity_opening; nếu tất cả đều rỗng "
            "=> persona_opening. Persona opening không cần external evidence nhưng chỉ được nói về thái độ/sự hiện diện của ERIS. "
            "Topic phải chỉ rõ source; không được suy từ chữ startup/runtime/telemetry rằng user đang định thay đổi hay bắt đầu việc gì. "
            "runtime_metadata như process/window title, DEBUG label, foreground, PID, backend không đủ làm grounded_runtime_opening. "
            "Nếu có suy đoán về mood/intent, đó chỉ là low-risk hypothesis có căn cứ và cho phép user sửa. "
            "Không tạo câu thoại; topic chỉ là nội dung cần nói. Không bịa screen fact. "
            "intrusion_risk cao nếu user vừa bận, vừa chat, hoặc motive chỉ là boredom/silence. "
            "tool_intent để trống trừ khi snapshot có một tác vụ runtime rõ ràng."
        )

    def plan_autonomous(self, snapshot: Mapping[str, Any]) -> IntentionPlan:
        payload = self._call(
            self.observer_client or self.deep_client,
            system=self._planner_prompt(),
            payload=snapshot,
            schema=INTENTION_PLAN_SCHEMA,
            name="eris_autonomous_intention",
            max_tokens=420,
            reasoning_effort="low" if str(getattr(self.observer_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
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
]
