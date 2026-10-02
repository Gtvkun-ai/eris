# -*- coding: utf-8 -*-
"""Adapter from a root-owned move to the existing model surface writer."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .contracts import ConversationEvent
from .delivery import SurfaceEnvelope
from .kernel import KernelTurn
from .writer import RenderedConversationMove


class RuntimeConversationWriter:
    def __init__(self, host: Any) -> None:
        self.host = host

    def realize(
        self,
        *,
        turn: KernelTurn,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        runtime_context: Mapping[str, Any],
    ) -> RenderedConversationMove:
        router = getattr(self.host, "ai_model_router", None)
        generate = getattr(router, "generate_public_reply", None)
        if not callable(generate):
            raise RuntimeError("public_writer_unavailable")

        move_payload = turn.move.to_dict()
        root_context = (
            "ROOT_CONVERSATION_MOVE_V12: "
            + json.dumps(move_payload, ensure_ascii=False, separators=(",", ":"))
            + ". Realize only this move. Do not add a topic, question, teaching step, "
              "future thread, or continuation. The `after` field is lifecycle metadata."
        )
        prior_discourse = str(runtime_context.get("discourse_context", "") or "").strip()
        discourse_context = "\n\n".join(part for part in (prior_discourse, root_context) if part)
        payload = generate(
            chat_history=tuple(recent_history),
            user_text=str(event.text or ""),
            memory_context=str(runtime_context.get("memory_context", "") or ""),
            grounding_context=str(runtime_context.get("grounding_context", "") or ""),
            relationship_context=str(runtime_context.get("relationship_context", "") or ""),
            personality_context=str(runtime_context.get("personality_context", "") or ""),
            interrupt_context=str(runtime_context.get("interrupt_context", "") or ""),
            engagement_context=str(runtime_context.get("engagement_context", "") or ""),
            routing_context=str(runtime_context.get("routing_context", "") or ""),
            discourse_context=discourse_context,
            use_escalation=bool(runtime_context.get("use_escalation", False)),
            reasoning_effort=runtime_context.get("reasoning_effort"),
            thinking_mode=runtime_context.get("thinking_mode"),
            allow_fallback=bool(runtime_context.get("allow_fallback", False)),
            language_hint=str(runtime_context.get("language_hint", "vi") or "vi"),
            speech_language_hint=str(runtime_context.get("speech_language_hint", "ja") or "ja"),
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("public_writer_invalid_payload")
        display_text = str(payload.get("text", "") or "").strip()
        if not display_text:
            raise RuntimeError("public_writer_empty")
        speech_text = str(payload.get("speech_text", "") or "").strip()
        display_language = str(
            payload.get("display_language", runtime_context.get("language_hint", "vi")) or "vi"
        ).strip()
        return RenderedConversationMove(
            surface=SurfaceEnvelope(
                display_text=display_text,
                speech_text=speech_text,
                language=display_language,
                alignment_safe=bool(payload.get("alignment_safe", False)),
                metadata=dict(payload),
            ),
            decision_payload=move_payload,
            metadata={
                "writer": "runtime_model_router",
                "event_kind": event.kind,
                "user_text": event.text,
                "provider_payload": dict(payload),
            },
        )


__all__ = ["RuntimeConversationWriter"]
