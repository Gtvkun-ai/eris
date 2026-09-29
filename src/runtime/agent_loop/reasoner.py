# -*- coding: utf-8 -*-
"""Model-backed reasoner cho mỗi vòng của foreground agent loop."""
from __future__ import annotations

import os
from typing import Any, Mapping, Protocol, Sequence

from .contracts import TurnDecision


AGENT_TURN_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "situation_summary", "objective", "task_shape", "active_roles",
        "work_items", "completed_items", "remaining_items", "uncertainties",
        "next_action", "progress", "uncertainty", "completion_candidate",
        "requires_user_response", "tutor_response_relation", "response_mode",
        "disclosure_mode", "speech_budget", "continuation", "dialogue_beats",
        "style_notes", "decision_summary",
    ],
    "properties": {
        "situation_summary": {"type": "string"},
        "objective": {"type": "string"},
        "task_shape": {
            "type": "string",
            "enum": ["conversation", "analysis", "creation", "action", "learning", "research", "coding"],
        },
        "active_roles": {
            "type": "array",
            "items": {"type": "string", "enum": ["general", "companion", "tutor", "coding", "research", "creator", "critic"]},
            "maxItems": 5,
        },
        "work_items": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "completed_items": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "remaining_items": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "uncertainties": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "next_action": {
            "type": "string",
            "enum": ["analyze", "decompose", "verify", "compose", "wait_user", "complete"],
        },
        "progress": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "uncertainty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "completion_candidate": {"type": "boolean"},
        "requires_user_response": {"type": "boolean"},
        "tutor_response_relation": {
            "type": "string",
            "enum": ["none", "answer", "clarification", "interrupt"],
        },
        "response_mode": {"type": "string", "enum": ["brief", "normal", "deep", "progressive"]},
        "disclosure_mode": {
            "type": "string",
            "enum": ["conversational", "deep_dialogue", "report"],
        },
        "speech_budget": {
            "type": "object",
            "additionalProperties": False,
            "required": ["max_beats"],
            "properties": {
                "target_words": {"type": "integer", "minimum": 20, "maximum": 1200},
                "hard_max_words": {"type": "integer", "minimum": 30, "maximum": 1800},
                "max_beats": {"type": "integer", "minimum": 1, "maximum": 8},
                "target_seconds": {"type": "number", "minimum": 5.0, "maximum": 180.0},
                "hard_max_seconds": {"type": "number", "minimum": 8.0, "maximum": 240.0},
            },
        },
        "continuation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["active_thread", "deferred_threads", "continuation_anchor", "next_if_continue"],
            "properties": {
                "active_thread": {"type": "string"},
                "deferred_threads": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                "continuation_anchor": {"type": "string"},
                "next_if_continue": {"type": "string"},
            },
        },
        "dialogue_beats": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind", "proposition", "communicative_goal", "relation_to_previous",
                    "detail_level", "needs_example", "say_now",
                ],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "frame", "finding", "explanation", "contrast", "example",
                            "correction", "uncertainty", "decision", "synthesis", "question", "handoff",
                        ],
                    },
                    "proposition": {"type": "string"},
                    "communicative_goal": {"type": "string"},
                    "relation_to_previous": {"type": "string"},
                    "detail_level": {"type": "string", "enum": ["brief", "normal", "deep"]},
                    "needs_example": {"type": "boolean"},
                    "say_now": {"type": "boolean"},
                },
            },
        },
        "style_notes": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "decision_summary": {"type": "string"},
    },
}


class TurnReasoner(Protocol):
    def decide(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
        state: Mapping[str, Any],
        runtime_context: Mapping[str, Any],
    ) -> TurnDecision:
        ...


class DeterministicFallbackTurnReasoner:
    """Fallback typed tối thiểu để *mọi* foreground turn vẫn có root loop.

    Đây không giả vờ reasoning bằng regex. Nó chỉ bảo đảm kiến trúc không rơi
    ngược về pipeline planner->writer legacy khi model router đang unavailable.
    """

    def decide(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
        state: Mapping[str, Any],
        runtime_context: Mapping[str, Any],
    ) -> TurnDecision:
        return heuristic_fallback_decision(user_text, state=state, runtime_context=runtime_context)


class RuntimeModelTurnReasoner:
    """Dùng structured worker sẵn có; worker không có quyền public trực tiếp."""

    def __init__(self, router: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.logger = logger

    def decide(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
        state: Mapping[str, Any],
        runtime_context: Mapping[str, Any],
    ) -> TurnDecision:
        # Root TurnAgentLoop nên ưu tiên worker ``executive`` đúng nghĩa.
        # Trước V4 đoạn này lấy ``deep_client`` (social critic) trước, nên ownership
        # bị mờ: executive loop có thể đang dùng một role worker khác chỉ vì nó
        # "sâu" hơn. Fallback vẫn giữ để rollout không làm chat chết nếu executive
        # worker chưa được cấu hình.
        client = (
            getattr(self.router, "executive_client", None)
            or getattr(self.router, "deep_client", None)
            or getattr(self.router, "seed_client", None)
            or getattr(self.router, "surface_client", None)
            or getattr(getattr(self.router, "llm_service", None), "client", None)
        )
        invoke = getattr(self.router, "invoke_structured_worker", None)
        if client is None or not callable(invoke):
            return heuristic_fallback_decision(user_text, state=state, runtime_context=runtime_context)
        payload = {
            "current_user_turn": str(user_text or "")[:12000],
            "recent_public_history": [
                {"role": str(item.get("role", ""))[:30], "content": str(item.get("content", ""))[:2500]}
                for item in recent_history[-8:]
                if isinstance(item, Mapping)
            ],
            "agent_turn_state": dict(state),
            "runtime_context": _bounded_runtime_context(runtime_context),
        }
        try:
            raw = invoke(
                client,
                system=(
                    "Bạn là ERIS Turn Executive worker. Trả JSON typed, không viết câu public hoàn chỉnh và "
                    "không xuất chain-of-thought. Mỗi user turn luôn là một agent run. Hãy cập nhật ba kế hoạch "
                    "độc lập: (1) cognitive plan: cần hiểu gì, (2) execution plan: còn việc gì phải làm, "
                    "(3) discourse plan: nên chia cách nói ra thành những DialogueBeat nào. "
                    "Câu đơn giản được COMPLETE ngay sau một vòng. Yêu cầu phân tích sâu phải DECOMPOSE thành "
                    "các phần nhỏ, VERIFY coverage/mâu thuẫn rồi mới COMPLETE. Nếu cần chờ user thật sự thì WAIT_USER. "
                    "Tutor/coding/research/companion chỉ là role được kích hoạt, không phải root loop riêng. "
                    "Nếu runtime_context.tutor_role cho thấy tutor đang chờ câu trả lời, hãy phân loại user turn bằng "
                    "tutor_response_relation=answer|clarification|interrupt|none; chỉ 'answer' mới được semantic assessor chấm. "
                    "DialogueBeat phải tự nhiên như người nói. Quan trọng: cognitive coverage KHÔNG đồng nghĩa public disclosure. "
                    "Hãy chọn disclosure_mode: conversational cho hỏi đáp khám phá bình thường, deep_dialogue khi user muốn đào sâu "
                    "nhưng vẫn đang đối thoại, report chỉ khi user thật sự yêu cầu một câu trả lời đầy đủ/báo cáo. "
                    "Trong conversational mode thường chỉ nói 1-2 ý, giữ các ý còn lại trong continuation.deferred_threads. "
                    "continuation_anchor là ý mở tự nhiên cho lượt sau, không phải câu hỏi generic kiểu 'bạn có muốn biết thêm không'. "
                    "Nếu runtime_context.voice_mode=true, điều khiển nhịp bằng số DialogueBeat được reveal (thường 1 beat ở conversational mode) để người nghe có cơ hội chen vào. Không dùng word/time hard cap và không yêu cầu writer nén câu. "
                    "Không biến mọi beat thành heading, không nhắc lại cùng một ý. "
                    "decision_summary chỉ ghi lý do vận hành cực ngắn như 'còn thiếu ví dụ và verification'; "
                    "không ghi quá trình suy luận nội bộ chi tiết."
                ),
                payload=payload,
                schema=AGENT_TURN_DECISION_SCHEMA,
                name="eris_agent_turn_executive",
                max_tokens=1450,
                reasoning_effort="medium",
                # ``subconscious_4b`` chỉ là legacy tier để caller/scheduler cũ
                # vẫn tương thích. Cognitive role thật của request được khai báo
                # riêng; backend/resource_class sẽ được router đọc từ DS2API client.
                inference_tier="subconscious_4b",
                cognitive_lane="turn_executive",
                priority=68,
                timeout_seconds=_worker_timeout_seconds(),
            )
            if isinstance(raw, Mapping) and raw:
                return TurnDecision.from_mapping(raw)
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[agent-turn] model reasoner degraded: %s", exc)
        return heuristic_fallback_decision(user_text, state=state, runtime_context=runtime_context)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


def _worker_timeout_seconds() -> float:
    """Kế thừa deadline foreground, trừ khi worker có cấu hình riêng."""
    foreground_raw = str(
        os.getenv("ERIS_FOREGROUND_HARD_DEADLINE_SEC", "90.0") or "90.0"
    ).strip()
    try:
        foreground_timeout = float(foreground_raw)
    except (TypeError, ValueError):
        foreground_timeout = 90.0
    raw = str(
        os.getenv("ERIS_AGENT_TURN_WORKER_TIMEOUT_SEC", str(foreground_timeout))
        or str(foreground_timeout)
    ).strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = foreground_timeout
    return max(2.0, value)


def _bounded_runtime_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Giữ context typed đủ sâu cho role coordination nhưng vẫn bounded."""
    allow = {
        "agent_execution_route", "teaching_active", "explicit_tool_route",
        "conversation_status", "previous_public_excerpt", "requested_depth",
        "voice_mode", "tts_speed", "disclosure_arc", "tutor_role",
    }

    def bounded(value: Any, *, depth: int = 0) -> Any:
        if depth >= 3:
            return str(value)[:700]
        if isinstance(value, Mapping):
            return {
                str(k)[:80]: bounded(v, depth=depth + 1)
                for k, v in list(value.items())[:16]
            }
        if isinstance(value, (list, tuple)):
            return [bounded(item, depth=depth + 1) for item in value[:12]]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        if value is None:
            return None
        return str(value)[:1400]

    return {key: bounded(context.get(key)) for key in allow if key in context}


def heuristic_fallback_decision(
    user_text: str,
    *,
    state: Mapping[str, Any],
    runtime_context: Mapping[str, Any],
) -> TurnDecision:
    """Fallback bảo thủ khi worker không dùng được.

    Đây không cố giả semantic intelligence bằng regex. Nó chỉ đảm bảo mọi turn
    vẫn có typed loop contract và writer nhận được nhịp nói tối thiểu.
    """
    text = " ".join(str(user_text or "").strip().split())
    iteration = int(state.get("iteration", 0) or 0)
    action = "complete" if iteration >= 0 else "analyze"
    role = "coding" if str(runtime_context.get("agent_execution_route", "")).lower() not in {"", "none", "{}"} else "general"
    raw = {
        "situation_summary": "Cần phản hồi trực tiếp lượt user hiện tại bằng thông tin đã được runtime grounding.",
        "objective": text[:700] or "Duy trì cuộc hội thoại tự nhiên.",
        "task_shape": "conversation",
        "active_roles": [role],
        "work_items": ["trả lời yêu cầu hiện tại"],
        "completed_items": ["đã xác định yêu cầu trực tiếp"],
        "remaining_items": [],
        "uncertainties": [],
        "next_action": action,
        "progress": 1.0,
        "uncertainty": 0.35,
        "completion_candidate": True,
        "requires_user_response": False,
        "tutor_response_relation": "none",
        "response_mode": "normal",
        "disclosure_mode": "conversational",
        "speech_budget": {"max_beats": 2},
        "continuation": {
            "active_thread": "", "deferred_threads": [], "continuation_anchor": "", "next_if_continue": ""
        },
        "dialogue_beats": [{
            "kind": "explanation",
            "proposition": "Trả lời thẳng yêu cầu hiện tại, ưu tiên ý quan trọng trước rồi mới mở rộng khi cần.",
            "communicative_goal": "đáp ứng user mà không dump cấu trúc máy móc",
            "relation_to_previous": "continue",
            "detail_level": "normal",
            "needs_example": False,
            "say_now": True,
        }],
        "style_notes": ["nói tự nhiên", "không lộ chain-of-thought", "không lặp ý"],
        "decision_summary": "fallback typed plan vì semantic worker không khả dụng",
    }
    return TurnDecision.from_mapping(raw)


__all__ = [
    "AGENT_TURN_DECISION_SCHEMA",
    "DeterministicFallbackTurnReasoner",
    "RuntimeModelTurnReasoner",
    "TurnReasoner",
    "heuristic_fallback_decision",
]
