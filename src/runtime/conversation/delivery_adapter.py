# -*- coding: utf-8 -*-
"""The single high-level adapter allowed to commit and publish assistant speech."""
from __future__ import annotations

import json
import threading
from typing import Any

from .kernel import KernelTurn
from .writer import RenderedConversationMove


class RuntimeConversationDeliveryAdapter:
    def __init__(self, host: Any) -> None:
        self.host = host
        self._lock = threading.RLock()
        self._started: set[str] = set()

    def deliver(
        self,
        *,
        turn: KernelTurn,
        rendered: RenderedConversationMove,
        delivery_id: str,
    ) -> None:
        did = str(delivery_id or "")[:180]
        if not did:
            raise ValueError("delivery_id_required")
        with self._lock:
            if did in self._started:
                return
            self._started.add(did)

        payload = dict(rendered.metadata.get("provider_payload", {}) or {})
        payload["text"] = rendered.surface.display_text
        if rendered.surface.speech_text:
            payload["speech_text"] = rendered.surface.speech_text
        parser = getattr(self.host, "parser", None)
        parse = getattr(parser, "parse", None)
        if not callable(parse):
            raise RuntimeError("public_decision_parser_unavailable")
        raw = json.dumps(payload, ensure_ascii=False)
        try:
            decision = parse(raw, user_hint=str(rendered.metadata.get("user_text", "") or ""))
        except TypeError:
            decision = parse(raw)

        decision.text = rendered.surface.display_text
        decision.speech_text = rendered.surface.speech_text
        decision.display_language = rendered.surface.language
        decision.should_speak = bool(rendered.surface.display_text.strip())
        decision.utterance_turn_id = did
        if not str(getattr(decision, "delivery_hint", "") or "").strip():
            decision.delivery_hint = turn.move.delivery
        decision.performance_context = dict(getattr(decision, "performance_context", {}) or {})
        decision.performance_context.update({
            "conversation_session_id": turn.session_id,
            "conversation_generation": turn.generation,
            "conversation_run_id": turn.run_id,
            "conversation_move_id": turn.move.move_id,
        })

        stage = getattr(self.host, "ai_stage_planner", None)
        apply_stage = getattr(stage, "apply", None)
        if callable(apply_stage):
            try:
                state_runtime = getattr(self.host, "ai_state_reducer", None)
                snapshot = getattr(state_runtime, "snapshot", None)
                state = snapshot() if callable(snapshot) else None
                apply_stage(decision, turn.move.delivery or "neutral", state=state, channel=self._channel_for(rendered))
            except Exception as exc:
                self._log("debug", "[conversation-v12] stage projection degraded: %s", exc)

        display_text = str(rendered.surface.display_text or "").strip()
        if not display_text:
            raise RuntimeError("public_delivery_empty")
        memory_text = display_text
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER

            surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(display_text)
            display_text = surfaces.display_text
            memory_text = surfaces.memory_text
            decision.text = display_text
        except Exception as exc:
            self._log("debug", "[conversation-v12] surface commit degraded: %s", exc)

        if memory_text:
            append_history = getattr(self.host, "_append_chat_history", None)
            if callable(append_history):
                append_history("assistant", memory_text, invalid=False)
        ledger_factory = getattr(self.host, "_ensure_session_turn_ledger", None)
        if callable(ledger_factory):
            ledger_factory().record_assistant(
                display_text,
                meta={
                    "schema": "eris.conversation_delivery.v12",
                    "channel": self._channel_for(rendered),
                    "delivery_id": did,
                    "generation": turn.generation,
                    "run_id": turn.run_id,
                    "next_conversation_move": turn.move.to_dict(),
                },
            )

        self.host.last_text = display_text
        self.host.last_chat_answer = display_text
        apply_position = getattr(self.host, "_apply_position_update", None)
        if callable(apply_position):
            apply_position(decision)
        send = getattr(self.host, "_send_decision_to_body", None)
        if not callable(send):
            raise RuntimeError("public_transport_unavailable")
        send(decision, channel=self._channel_for(rendered))

    @staticmethod
    def _channel_for(rendered: RenderedConversationMove) -> str:
        return "chat" if str(rendered.metadata.get("event_kind", "")) == "user_turn" else "autonomous"

    def _log(self, level: str, message: str, *args: Any) -> None:
        logger = getattr(self.host, "logger", None)
        method = getattr(logger, level, None) if logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = ["RuntimeConversationDeliveryAdapter"]
