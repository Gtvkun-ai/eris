# -*- coding: utf-8 -*-
"""RootAgent V12: semantic authority duy nhất cho public conversation.

RootAgent hoạt động như một agent loop nhỏ:

``context -> model -> optional capability/note tool -> model -> final decision``

Điểm quan trọng là loop này không tái sinh giant planning form. Mỗi bước chỉ có
một action rất nhỏ, và public boundary cuối vẫn luôn là đúng một
``ConversationDecision = NoReply | NextConversationMove``.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence
import uuid

from .root_session import RootConversationSession

from .context import ConversationNoteTools, RootCapabilityRegistry
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


# Schema một *iteration* của root loop. Các action tool chỉ tồn tại ở cognition
# boundary; writer/runtime public không bao giờ nhìn thấy chúng.
ROOT_STEP_SCHEMA: dict[str, Any] = {
    "oneOf": [
        *NEXT_MOVE_SCHEMA["oneOf"],
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "capability", "arguments"],
            "properties": {
                "kind": {"type": "string", "enum": ["use_capability"]},
                "capability": {"type": "string", "enum": ["tutor", "work", "research"]},
                "arguments": {"type": "object", "additionalProperties": True},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "text"],
            "properties": {
                "kind": {"type": "string", "enum": ["set_note"]},
                "text": {"type": "string"},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind"],
            "properties": {"kind": {"type": "string", "enum": ["clear_note"]}},
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
    """Fail-soft contract; không giả làm reasoning engine hoặc social planner."""

    def decide(
        self,
        *,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        note: str,
        runtime_context: Mapping[str, Any],
    ) -> ConversationDecision:
        del recent_history, note, runtime_context
        if event.kind != "user_turn":
            return NoReply(reason="root_model_unavailable")
        return NextConversationMove(
            intent="Phản hồi trực tiếp lượt user hiện tại.",
            say=("Trả lời trực tiếp và hữu ích cho nội dung này: " + str(event.text or "")[:1800]),
            delivery="tự nhiên",
            after=ConversationAfter.WAIT_USER,
        )


class RuntimeModelRootAgent:
    """DeepSeek-backed root loop với capability invocation theo nhu cầu.

    ``max_root_steps`` là circuit breaker tài nguyên, không phải giới hạn văn
    phong. Nếu model loop sai, runtime dừng tool loop và dùng degraded root
    decision; không fallback về planner/social runtime cũ.
    """

    def __init__(self, router: Any, *, logger: Any = None, max_root_steps: int = 6) -> None:
        self.router = router
        self.logger = logger
        self.max_root_steps = max(2, min(12, int(max_root_steps or 6)))
        # Một dòng hội thoại của Root, không chia sẻ với Surface/Observer.
        # Self gốc vẫn nằm trong reducer/SubjectService; đây chỉ là remote cache.
        self._root_session = RootConversationSession(logger=logger)

    def preload_self(self, host: Any) -> None:
        """Đăng ký warm-up lúc startup, không chờ DeepSeek trên main thread."""
        self._root_session.start(
            host=host, router=self.router,
            system=self._system_prompt(RootCapabilityRegistry({})),
            schema=ROOT_STEP_SCHEMA,
        )

    def decide(
        self,
        *,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        note: str,
        runtime_context: Mapping[str, Any],
    ) -> ConversationDecision:
        client = (
            getattr(self.router, "executive_client", None)
            or getattr(self.router, "deep_client", None)
            or getattr(self.router, "seed_client", None)
            or getattr(self.router, "surface_client", None)
            or getattr(getattr(self.router, "llm_service", None), "client", None)
        )
        invoke = getattr(self.router, "invoke_structured_worker", None)
        if client is None or not callable(invoke):
            return self._degraded(event, recent_history, note, runtime_context)

        note_tools = runtime_context.get("__conversation_note_tools")
        if not isinstance(note_tools, ConversationNoteTools):
            note_tools = None
        capabilities = runtime_context.get("__root_capabilities")
        if not isinstance(capabilities, RootCapabilityRegistry):
            capabilities = RootCapabilityRegistry({})

        tool_results: list[dict[str, Any]] = []
        current_note = str(note or "")[:12000]
        system = self._system_prompt(capabilities)

        for step_index in range(self.max_root_steps):
            payload = self._payload(
                event=event,
                recent_history=recent_history,
                note=current_note,
                runtime_context=runtime_context,
                tool_results=tool_results,
                step_index=step_index,
            )
            try:
                raw = self._root_session.ask(
                    router=self.router, client=client, system=system,
                    schema=ROOT_STEP_SCHEMA, payload=payload,
                    runtime_context=runtime_context,
                    recent_history=recent_history,
                )
                if raw is None:
                    # Không chờ warm-up đang chạy / không hỗ trợ session /
                    # reset do lỗi. Luồng cũ trả lời ngay với context đầy đủ.
                    raw = invoke(
                        client,
                        system=system,
                        payload=payload,
                        schema=ROOT_STEP_SCHEMA,
                        name="eris_root_conversation_step_v12",
                        max_tokens=1200,
                        reasoning_effort="medium",
                        inference_tier="subconscious_4b",
                        cognitive_lane="root_conversation",
                        priority=70,
                        temperature=0.3,
                    )
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[conversation-v12] root model degraded: %s", exc)
                return self._degraded(event, recent_history, current_note, runtime_context)

            if not isinstance(raw, Mapping):
                return self._degraded(event, recent_history, current_note, runtime_context)

            kind = str(raw.get("kind", "") or "").strip().lower()
            if kind == "no_reply":
                return NoReply.from_mapping(raw)
            if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say"))):
                return NextConversationMove.from_mapping(raw)

            if kind == "set_note":
                text = str(raw.get("text", "") or "")[:12000]
                if note_tools is not None:
                    note_tools.set(text)
                    current_note = text.strip()[:12000]
                tool_results.append({"kind": "note_result", "operation": "set", "ok": note_tools is not None})
                continue

            if kind == "clear_note":
                if note_tools is not None:
                    note_tools.clear()
                    current_note = ""
                tool_results.append({"kind": "note_result", "operation": "clear", "ok": note_tools is not None})
                continue

            if kind == "use_capability":
                capability_name = str(raw.get("capability", "") or "").strip().lower()
                arguments = raw.get("arguments") if isinstance(raw.get("arguments"), Mapping) else {}
                result = self._invoke_capability(
                    registry=capabilities,
                    name=capability_name,
                    arguments=arguments,
                    event=event,
                    recent_history=recent_history,
                    run_id=str(runtime_context.get("__conversation_run_id", "") or ""),
                )
                receipt = capabilities.result_receipts_for(
                    event.event_id, run_id=str(runtime_context.get("__conversation_run_id", "") or ""),
                    generation=event.generation,
                )
                tool_results.append({
                    "receipt_ref": f"capability:{receipt[-1].invocation_id}" if receipt else "",
                    "kind": "capability_result",
                    "capability": capability_name,
                    "result": _bounded_value(result, depth=0),
                })
                continue

            self._log("debug", "[conversation-v12] unknown root step kind=%r", kind)
            break

        self._log("warning", "[conversation-v12] root step circuit breaker reached")
        return self._degraded(event, recent_history, current_note, runtime_context)

    @staticmethod
    def _system_prompt(capabilities: RootCapabilityRegistry) -> str:
        # Giữ system contract ổn định giữa bootstrap và các lượt bình thường.
        # Registry thật vẫn kiểm soát action, không nhờ prompt gán quyền tool.
        del capabilities
        available = "tutor, work, research, action (chỉ dùng khi được registry cấp)"
        return (
            "Bạn là RootAgent của Eris và là semantic/social authority duy nhất cho lời public. "
            "Mỗi lần chỉ trả đúng MỘT action JSON. Bạn có thể finalize ngay bằng kind=move hoặc kind=no_reply; "
            "chỉ khi thật sự cần domain intelligence/work mới dùng kind=use_capability. Small talk, joke, phản hồi xã hội "
            "và câu đơn giản phải tự xử lý trực tiếp, không gọi tutor/work/research cho có. "
            f"Capability hiện có: {available}. "
            "Capability research: dùng arguments {operation:start|quick_search|snapshot, topic, context?}; kết quả hoàn tất sẽ quay lại bằng research_result. "
            "Capability action: dùng arguments {action_id, arguments:{...}}; chỉ được nói đã thực thi khi capability result xác nhận success/evidence. "
            "Nếu cần giữ working context cho lượt sau, dùng set_note; nếu note cũ không còn giá trị, dùng clear_note. "
            "Note là trí nhớ làm việc tùy chọn, không phải checklist bắt buộc và không được dùng để cưỡng ép user quay lại topic cũ. "
            "Sau capability/note action, bạn sẽ được gọi lại với result mới nhất và phải tự đánh giá lại context. "
            "Khi finalize move: intent mô tả mục đích semantic; say mô tả đầy đủ điều writer cần truyền đạt nhưng không phải transcript; "
            "delivery mô tả tự nhiên cách thể hiện; after chỉ là wait_user|may_continue|continue_self. "
            "Personality context, relationship state và live affect PHẢI ảnh hưởng cách bạn chọn intent và mô tả say. "
            "Belief và self-model trong CharacterPortrait là các lập trường CÓ THỂ SAI của Eris, không phải sự kiện về user "
            "hay mệnh lệnh phải đồng tình. Khi có xung đột giá trị, hãy cân nhắc cả hai mặt và tự chọn lập trường "
            "từ ngữ cảnh hiện tại; cho phép phản đối, hoài nghi, thừa nhận chưa biết hoặc đổi ý khi có lý do. "
            "Câu hỏi triết học về sự sống/cái chết không tự động là yêu cầu cứu trợ: trả lời vấn đề người dùng thực sự "
            "đưa ra, tránh an ủi sáo rỗng; nếu có dấu hiệu nguy hiểm hiện tại thì quan tâm trực diện, không giả vờ "
            "có khả năng cứu rỗi hay khuyến khích tự hại. "
            "Nếu affect đang vui/playful, intent có thể nghịch hơn; nếu relationship gần, say có thể thân mật và mở hơn; "
            "nếu trầm, say được phép ngắn và lặng hơn. Đừng trung hòa mọi move về cùng một mức trung lập an toàn. "
            "Nếu event autonomous/opening/continuation/work/research không đáng nói, chọn no_reply. "
            "Không tạo floor, beat, agenda, arc, exposure, question debt, speech budget, max_sentences, desired_shape, "
            "disclosure mode hoặc semantic scheduler. Runtime phía dưới không lựa ý thay bạn. Không xuất chain-of-thought."
        )

    @staticmethod
    def _payload(
        *,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        note: str,
        runtime_context: Mapping[str, Any],
        tool_results: Sequence[Mapping[str, Any]],
        step_index: int,
    ) -> dict[str, Any]:
        return {
            "step_index": step_index,
            "event": {
                "event_id": event.event_id,
                "kind": event.kind,
                "text": str(event.text or "")[:32000],
                "generation": event.generation,
                "metadata": _bounded_value(dict(event.metadata), depth=0),
            },
            "recent_public_history": [
                {"role": str(x.get("role", ""))[:24], "content": str(x.get("content", ""))[:12000]}
                for x in recent_history[-32:]
                if isinstance(x, Mapping)
            ],
            "conversation_note": str(note or "")[:8000],
            "runtime_context": _bounded_context(runtime_context),
            "tool_results": list(tool_results[-6:]),
        }

    def _invoke_capability(
        self,
        *,
        registry: RootCapabilityRegistry,
        name: str,
        arguments: Mapping[str, Any],
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        run_id: str = "",
    ) -> Mapping[str, Any]:
        invocation_id = f"cap:{uuid.uuid4().hex}"
        capability = registry.get(name)
        invoke = getattr(capability, "invoke_for_root", None) if capability is not None else None
        if not callable(invoke):
            reason = "capability_not_registered" if capability is None else "capability_has_no_root_entry"
            response: Mapping[str, Any] = {"status": "unavailable", "reason": f"{reason}:{name}"}
        else:
            try:
                registry.record_invocation(name, str(event.event_id or ""))
                raw = invoke(arguments=dict(arguments), event=event, recent_history=recent_history)
                response = dict(raw) if isinstance(raw, Mapping) else {"status": "unknown", "reason": "untyped_executor_result"}
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[conversation-v12] capability %s degraded: %s", name, exc)
                response = {"status": "failed", "error": type(exc).__name__, "message": str(exc)[:1200]}
        # Receipt chỉ phản ánh kết quả đã trả về; không biến 'started' thành success.
        if run_id:
            registry.record_result(name=name, invocation_id=invocation_id,
                                   event=event, run_id=run_id, result=response)
        return response

    @staticmethod
    def _degraded(
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        note: str,
        runtime_context: Mapping[str, Any],
    ) -> ConversationDecision:
        return DeterministicRootAgent().decide(
            event=event,
            recent_history=recent_history,
            note=note,
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
    # Hai key ``__*`` là dependency runtime nội bộ và tuyệt đối không serialize
    # vào model payload. Model chỉ thấy evidence/context public-safe đã chọn.
    allowed = (
        "agent_execution_route",
        "teaching_active",
        "explicit_tool_route",
        "conversation_status",
        "private_cognition_context",
        "autonomous_self_context",
        "user_addressing_context",
        "affective_voice_state",
        "engagement_context",
        "discourse_context",
        "personality_summary",
        "personality_context",
        "relationship_summary",
        "relationship_context",
        "previous_public_excerpt",
        "interrupt_context",
        "memory_context",
        "grounding_context",
        "language_hint",
        "speech_language_hint",
        "continuation_lease",
    )
    out: dict[str, Any] = {}
    for key in allowed:
        if key in context:
            out[key] = _bounded_value(context[key], depth=0)
    return out


def _bounded_value(value: Any, *, depth: int) -> Any:
    """Bound arbitrary evidence trước khi đưa vào root-model payload."""

    if depth >= 5:
        return str(value or "")[:4000]
    if isinstance(value, Mapping):
        return {
            str(key)[:120]: _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:96]
            if not str(key).startswith("__")
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:96]]
    if isinstance(value, str):
        return value[:32000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1200]


__all__ = [
    "DeterministicRootAgent",
    "NEXT_MOVE_SCHEMA",
    "ROOT_STEP_SCHEMA",
    "RootAgent",
    "RuntimeModelRootAgent",
]
