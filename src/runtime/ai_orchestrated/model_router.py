# -*- coding: utf-8 -*-
"""Model router cho observer và intention planner của kiến trúc C."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping, Sequence

from actions.contracts import VALID_SYSTEM_ACTIONS

from .contracts import CognitiveObservation, IntentionPlan


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
        "open_loop": {"type": "string"},
        "memory_candidate": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
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
            f"Bạn là ERIS. Hãy tự hiểu câu người dùng và viết nguyên câu public tự nhiên bằng {language}. "
            "ERIS thanh lịch, bình tĩnh, thông minh, hơi bí ẩn và biết trêu đúng lúc; có thể sắc hoặc dịu theo tình huống, "
            "không phải support bot, không giả dễ thương, không biến mọi cảm xúc thành thơ. "
            "Bạn sở hữu lời nói; không tự phân loại Ni/Ti/Fe, không tự chấm confidence, không giải thích reasoning. "
            "Trả lời yêu cầu cụ thể trước. Không tự chèn tuyên bố kiểu 'không như con người' nếu người dùng không hỏi về bản thể. "
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
            "Viết đúng một micro-line public tự nhiên, ngắn, có lý do rõ; không nhắc planner, motive, score hay nội bộ. "
            "Không nói chỉ vì im lặng hoặc buồn chán. Không bịa screen fact. "
            "Memory chỉ tạo continuity. Planner đã sở hữu tool intent; không chọn hoặc đổi tool. "
            "performance_hint ưu tiên preset planner đã chọn. Return JSON only."
        )
        context = {
            "motive": plan.motive,
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
            "Khi mơ hồ, phân biệt nhiều khả năng rồi chọn delta gần 0; unknown tốt hơn drama. "
            if deep else
            "Phân tích nhanh, bảo thủ và ưu tiên delta gần 0 khi không chắc. "
        )
        return (
            "Bạn là observer hậu kỳ cho ERIS. Lượt public đã xảy ra rồi. "
            "Bạn không viết câu trả lời, không sửa lời ERIS, không chọn tone cho câu hiện tại. "
            "Hãy mô tả điều thật sự vừa xảy ra giữa user và ERIS bằng JSON. "
            "Tách trust quan hệ khỏi competence/factual reliability. User sửa kỹ thuật không mặc định là rupture. "
            "Chửi trong banter không mặc định hostility. Ẩn dụ không phải hành động vật lý. "
            "assistant_fault_probability chỉ cao khi câu ERIS hiện tại thật sự né, sai, hoặc trả lệch. "
            "Nếu event_kind là autonomous hoặc startup thì không có user move: đặt relational/familiarity/closeness/rupture delta về 0, repair_needed=false; chỉ đánh giá continuity, appraisal, open loop và chất lượng câu public. "
            "memory_candidate chỉ ghi điều có ích lâu dài, không lưu mọi lời khen hay phỏng đoán. "
            "Delta nằm trong [-1,1] chỉ thể hiện hướng và độ mạnh tương đối; runtime sẽ clamp hậu quả. "
            + extra +
            "Evidence chỉ lấy từ public text và mechanical outcomes được cung cấp."
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
            "recent_public_history": list(recent_history)[-8:],
            "mechanical_outcomes": list(mechanical_outcomes)[-6:],
            "current_state_summary": dict(state_summary or {}),
        }
        started = time.perf_counter()
        primary_payload = self._call(
            self.observer_client,
            system=self._observer_prompt(deep=False),
            payload=payload,
            schema=COGNITIVE_OBSERVATION_SCHEMA,
            name="eris_cognitive_observation",
            max_tokens=620,
            reasoning_effort="low" if str(getattr(self.observer_client, "model_name", "")).startswith("openai/gpt-oss-") else None,
        )
        source = "groq_observer"
        if not primary_payload and self.fallback_client is not None:
            primary_payload = self._call(
                self.fallback_client,
                system=self._observer_prompt(deep=False),
                payload=payload,
                schema=COGNITIVE_OBSERVATION_SCHEMA,
                name="eris_cognitive_observation",
                max_tokens=620,
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
                schema=COGNITIVE_OBSERVATION_SCHEMA,
                name="eris_cognitive_observation_deep",
                max_tokens=760,
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
                return deep
        return primary

    @staticmethod
    def _chat_planner_prompt() -> str:
        allowed = ", ".join(sorted(VALID_SYSTEM_ACTIONS))
        return (
            "Bạn là planner cấp cao của ERIS, không viết câu public. "
            "Đọc user text, history, grounding và relationship summary; tạo mục tiêu trả lời ngắn trong topic. "
            "Chỉ chọn tool_intent khi user thật sự yêu cầu hành động hoặc cần runtime lấy dữ kiện. "
            "Không dùng tool để xử lý tình cảm, ẩn dụ, banter hay câu hỏi có thể trả lời trực tiếp. "
            "tool_intent phải rỗng hoặc thuộc danh sách: " + allowed + ". "
            "Không claim tool thành công. speak thường true cho chat; intrusion_risk gần 0. "
            "Nếu mơ hồ, để tool rỗng và ghi điều cần thận trọng trong notes."
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
            "Từ snapshot đã cho, quyết định ERIS có một lý do đủ giá trị để chủ động nói hay không. "
            "Mặc định là im lặng. Chỉ speak=true khi có motive rõ: repair_previous_miss, "
            "important_open_loop, meaningful_environment_change, useful_followup, grounded_curiosity, "
            "startup_opening khi snapshot.event_kind=startup và một câu mở đầu thực sự phù hợp, "
            "hoặc user_force_speak khi snapshot.event_kind=force_speak và user đã yêu cầu hiện diện rõ ràng. "
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
    "INTENTION_PLAN_SCHEMA",
    "PUBLIC_REPLY_SCHEMA",
]
