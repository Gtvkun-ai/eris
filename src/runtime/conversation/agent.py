# -*- coding: utf-8 -*-
"""RootAgent V12: model chỉ cần finalize một NextConversationMove.

Không còn giant planning form. Capability/domain context có thể rất giàu, nhưng
protocol public cuối cùng vẫn chỉ có intent/say/delivery/after.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .contracts import (
    ConversationAfter,
    ConversationDecision,
    ConversationEvent,
    NextConversationMove,
    NoReply,
)


NEXT_MOVE_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "intent", "say", "delivery", "after"],
            "properties": {
                "kind": {"type": "string", "enum": ["move"]},
                "intent": {"type": "string"},
                "say": {"type": "string"},
                "delivery": {"type": "string"},
                "after": {"type": "string", "enum": ["wait_user", "may_continue", "continue_self"]},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "reason"],
            "properties": {
                "kind": {"type": "string", "enum": ["no_reply"]},
                "reason": {"type": "string"},
            },
        },
    ],
}


class RootAgent(Protocol):
    def decide(
        self,
        *,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        note: str,
        runtime_context: Mapping[str, Any],
    ) -> ConversationDecision:
        ...


class DeterministicRootAgent:
    """Fail-soft contract, không giả làm reasoning engine."""

    def decide(self, *, event: ConversationEvent, recent_history: Sequence[Mapping[str, Any]], note: str,
               runtime_context: Mapping[str, Any]) -> ConversationDecision:
        del recent_history, note
        if event.kind != "user_turn":
            return NoReply(reason="root_model_unavailable")
        tutor = runtime_context.get("tutor_capability") or runtime_context.get("tutor_role")
        if isinstance(tutor, Mapping) and bool(tutor.get("waiting_for_user")):
            directive = tutor.get("directive") if isinstance(tutor.get("directive"), Mapping) else {}
            move = directive.get("move") if isinstance(directive, Mapping) and isinstance(directive.get("move"), Mapping) else {}
            goal = str(move.get("instruction") or move.get("prompt") or move.get("kind") or "thực hiện teaching move đang chờ")
            return NextConversationMove(
                intent="Tiếp tục teaching move hiện tại mà không tự trả lời thay người học.",
                say=goal,
                delivery="rõ ràng, kiên nhẫn",
                after=ConversationAfter.WAIT_USER,
            )
        return NextConversationMove(
            intent="Phản hồi trực tiếp lượt user hiện tại.",
            say=("Trả lời trực tiếp và hữu ích cho nội dung này: " + str(event.text or "")[:1800]),
            delivery="tự nhiên",
            after=ConversationAfter.WAIT_USER,
        )


class RuntimeModelRootAgent:
    def __init__(self, router: Any, *, logger: Any = None) -> None:
        self.router = router
        self.logger = logger

    def decide(self, *, event: ConversationEvent, recent_history: Sequence[Mapping[str, Any]], note: str,
               runtime_context: Mapping[str, Any]) -> ConversationDecision:
        client = (
            getattr(self.router, "executive_client", None)
            or getattr(self.router, "deep_client", None)
            or getattr(self.router, "seed_client", None)
            or getattr(self.router, "surface_client", None)
            or getattr(getattr(self.router, "llm_service", None), "client", None)
        )
        invoke = getattr(self.router, "invoke_structured_worker", None)
        if client is None or not callable(invoke):
            return DeterministicRootAgent().decide(
                event=event, recent_history=recent_history, note=note,
                runtime_context=runtime_context,
            )
        payload = {
            "event": {
                "event_id": event.event_id,
                "kind": event.kind,
                "text": str(event.text or "")[:12000],
                "generation": event.generation,
                "metadata": dict(event.metadata),
            },
            "recent_public_history": [
                {"role": str(x.get("role", ""))[:24], "content": str(x.get("content", ""))[:2600]}
                for x in recent_history[-10:] if isinstance(x, Mapping)
            ],
            "conversation_note": str(note or "")[:8000],
            "runtime_context": _bounded_context(runtime_context),
        }
        system = (
            "Bạn là Root Agent của Eris. Bạn là semantic authority duy nhất cho lời public. "
            "Hãy trả đúng MỘT ConversationDecision. Nếu không có gì đáng nói, trả kind=no_reply và reason ngắn. "
            "Nếu cần nói, trả kind=move cùng intent, say, delivery, after. "
            "intent mô tả điều Eris đang muốn làm; say mô tả nội dung writer cần truyền đạt, không phải script; "
            "delivery là mô tả tự nhiên ngắn về cách thể hiện; after chỉ là wait_user|may_continue|continue_self. "
            "Không tạo floor, beat, speech budget, max_sentences, desired_shape, disclosure mode hay thread scheduler. "
            "Runtime phía dưới không được lựa ý thay bạn, vì vậy say phải đủ nội dung để writer trả lời đúng. "
            "Nếu có tutor/coding/research context, dùng nó như evidence/advice; capability không được nói thay bạn. "
            "Với event continuation/autonomous/opening, tự đánh giá lại và chọn no_reply nếu không còn giá trị; không buộc phải nói. "
            "wait_user là mặc định khi câu hiện tại đã hoàn chỉnh hoặc cần user phản hồi. may_continue chỉ dùng khi còn đà "
            "nhưng không hứa sẽ nói tiếp. continue_self chỉ dùng khi thật sự cần một lượt cognition kế tiếp sau delivery. "
            "Không xuất chain-of-thought."
        )
        try:
            raw = invoke(
                client,
                system=system,
                payload=payload,
                schema=NEXT_MOVE_SCHEMA,
                name="eris_root_conversation_move_v12",
                max_tokens=650,
                reasoning_effort="medium",
                inference_tier="subconscious_4b",
                cognitive_lane="root_conversation",
                priority=70,
            )
            if isinstance(raw, Mapping):
                kind = str(raw.get("kind", "") or "").strip().lower()
                if kind == "no_reply":
                    return NoReply.from_mapping(raw)
                if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say"))):
                    return NextConversationMove.from_mapping(raw)
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[conversation-v12] root model degraded: %s", exc)
        return DeterministicRootAgent().decide(
            event=event, recent_history=recent_history, note=note,
            runtime_context=runtime_context,
        )

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


def _bounded_context(context: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "agent_execution_route", "teaching_active", "explicit_tool_route", "conversation_status",
        "affective_voice_state", "engagement_context", "personality_summary", "relationship_summary",
        "previous_public_excerpt", "tutor_capability", "tutor_role", "work_capability", "research_capability",
    )
    out: dict[str, Any] = {}
    for key in allowed:
        if key in context:
            value = context[key]
            if isinstance(value, Mapping):
                out[key] = dict(value)
            elif isinstance(value, (str, int, float, bool, list, tuple)) or value is None:
                out[key] = value
    return out


__all__ = ["DeterministicRootAgent", "NEXT_MOVE_SCHEMA", "RootAgent", "RuntimeModelRootAgent"]
