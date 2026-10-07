# -*- coding: utf-8 -*-
"""The single high-level adapter allowed to commit and publish assistant speech."""
from __future__ import annotations

import json
import threading
from typing import Any

from .kernel import KernelTurn
from .writer import RenderedConversationMove
from runtime.json_boundary import public_payload


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
                self._log("warning", "[delivery-adapter] deliver() called twice for same did=%s — idempotency guard fired, skipping body send", did)
                return
            self._started.add(did)

        # Writer giữ typed objects (_typed_semantic_frame, SemanticFrame, ...) để
        # cognition nội bộ dùng lại. Parser/body là JSON boundary nên phải hạ domain
        # object về primitive và bỏ cache _typed_* trước json.dumps.
        payload = public_payload(rendered.metadata.get("provider_payload", {}) or {})
        payload["text"] = rendered.surface.display_text
        if rendered.surface.speech_text:
            payload["speech_text"] = rendered.surface.speech_text
        parser = getattr(self.host, "parser", None)
        parse = getattr(parser, "parse", None)
        if not callable(parse):
            self._log("warning", "[delivery-adapter] parser unavailable, cannot deliver did=%s", did)
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
        channel = self._channel_for(rendered)
        event_kind = str(rendered.metadata.get("event_kind", "") or "")
        semantic_owner = "shared" if channel == "chat" else "eris"
        trigger_owner = "user" if channel == "chat" else (
            "external" if event_kind in {"work_result", "research_result", "tool_result"} else "eris"
        )
        decision.performance_context.update({
            "conversation_session_id": turn.session_id,
            "conversation_generation": turn.generation,
            "conversation_run_id": turn.run_id,
            "conversation_move_id": turn.move.move_id,
            # Cùng một id phải đi xuyên public commit -> TTS -> outcome để trace
            # không còn kết thúc bằng semantic/trigger=unknown.
            "event_trace_id": did,
            "public_intent_owner": "conversation_root_agent_v12",
            "semantic_owner": semantic_owner,
            "trigger_owner": trigger_owner,
        })

        causal_receipt = None
        try:
            from runtime.public_causal_receipt import build_public_causal_receipt

            causal_receipt = build_public_causal_receipt(
                channel=channel,
                semantic_owner=semantic_owner,
                trigger_owner=trigger_owner,
                source_kind="conversation_kernel_v12",
                source_ref=turn.move.move_id,
                motive=turn.move.intent,
                why_now=event_kind or "conversation_event",
                user_triggered=(channel == "chat"),
                confidence=1.0,
            )
            decision.performance_context["public_causal_receipt"] = causal_receipt.to_dict()
        except Exception as exc:
            self._log("debug", "[conversation-v12] causal receipt degraded: %s", exc)

        stage = getattr(self.host, "ai_stage_planner", None)
        apply_stage = getattr(stage, "apply", None)
        if callable(apply_stage):
            try:
                state_runtime = getattr(self.host, "ai_state_reducer", None)
                snapshot = getattr(state_runtime, "snapshot", None)
                state = snapshot() if callable(snapshot) else None
                apply_stage(decision, turn.move.delivery or "neutral", state=state, channel=channel)
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

        # Defense-in-depth: writer đã có một grounding rewrite pass. Nếu câu sau
        # rewrite vẫn claim sensor/action không có evidence thì không được commit
        # false public history.
        engine = rendered.metadata.get("source_grounding_engine")
        report = rendered.metadata.get("source_grounding_report")
        if engine is not None and report is not None:
            try:
                from runtime.grounding_surface_gate import evaluate_grounded_surface
                verdict = evaluate_grounded_surface(engine, display_text, report=report, channel=channel)
                if not bool(getattr(verdict, "allowed", True)):
                    raise RuntimeError("public_grounding_gate_blocked")
            except RuntimeError:
                raise
            except Exception as exc:
                self._log("debug", "[conversation-v12] grounding defense degraded: %s", exc)

        apply_position = getattr(self.host, "_apply_position_update", None)
        if callable(apply_position):
            apply_position(decision)
        send = getattr(self.host, "_send_decision_to_body", None)
        if not callable(send):
            self._log("warning", "[delivery-adapter] _send_decision_to_body not available on host, cannot deliver did=%s", did)
            raise RuntimeError("public_transport_unavailable")
        accepted = send(decision, channel=channel)
        # Runtime production trả bool; test/adapter cũ trả None và được coi là
        # accepted để giữ compatibility. False nghĩa stage ownership đã suppress.
        if accepted is False:
            raise RuntimeError("public_transport_suppressed")

        # Chỉ từ đây trở xuống mới là PUBLIC COMMIT thật. Trước điểm này tuyệt
        # đối không append history/ledger hay update self-state.
        assistant_turn = None
        if memory_text:
            append_history = getattr(self.host, "_append_chat_history", None)
            if callable(append_history):
                append_history("assistant", memory_text, invalid=False)
        ledger_factory = getattr(self.host, "_ensure_session_turn_ledger", None)
        if callable(ledger_factory):
            assistant_turn = ledger_factory().record_assistant(
                display_text,
                meta={
                    "schema": "eris.conversation_delivery.v12",
                    "channel": channel,
                    "delivery_id": did,
                    "generation": turn.generation,
                    "run_id": turn.run_id,
                    "next_conversation_move": turn.move.to_dict(),
                },
            )

        self.host.last_text = display_text
        self.host.last_chat_answer = display_text

        # Gắn capability invocation vào đúng delivery để terminal TTS receipt
        # chỉ commit domain state của capability thực sự được gọi ở lượt này.
        try:
            pending = getattr(self.host, "_v12_delivery_capabilities", None)
            if not isinstance(pending, dict):
                pending = {}
                self.host._v12_delivery_capabilities = pending
            pending[did] = {
                "capabilities": tuple(str(x) for x in tuple(rendered.metadata.get("root_capabilities_used", ()) or ()) if str(x)),
                "session_id": turn.session_id,
                "generation": turn.generation,
                "move_id": turn.move.move_id,
            }
            if len(pending) > 128:
                for stale in list(pending)[:-128]:
                    pending.pop(stale, None)
        except Exception as exc:
            self._log("debug", "[conversation-v12] capability receipt registration degraded: %s", exc)

        try:
            from runtime.ai_orchestrated.autonomous_trace import append_public_turn_trace
            append_public_turn_trace("conversation_move", {
                "trace_id": did,
                "turn_id": did,
                "channel": channel,
                "semantic_owner": semantic_owner,
                "trigger_owner": trigger_owner,
                "source_kind": "conversation_kernel_v12",
                "source_ref": turn.move.move_id,
                "goal_state": turn.move.intent,
                "proposal_source": "root_agent",
                "proposal_kind": "next_conversation_move",
                "authority_action": "commit",
                "authority_reason": "root_agent_finalized_move",
                "authority_owner": "conversation_root_agent_v12",
                "motive": turn.move.intent,
                "public_committed": True,
            }, logger=getattr(self.host, "logger", None))
        except Exception as exc:
            self._log("debug", "[conversation-v12] public trace provenance degraded: %s", exc)

        try:
            from runtime.conversation.observation_bridge import ensure_conversation_observation_bridge
            history = tuple(getattr(self.host, "chat_history", ()) or ())[-12:]
            ensure_conversation_observation_bridge(self.host).observe_assistant_commit(
                memory_text or display_text,
                turn_ref=did,
                turn_index=int(getattr(assistant_turn, "index", 0) or 0),
                speech_act=str(getattr(decision, "speech_act", "") or turn.move.intent or "public_commit"),
                event_kind=event_kind or channel,
                causal_receipt=causal_receipt,
                recent_history=tuple(item for item in history if isinstance(item, dict)),
                user_text=str(rendered.metadata.get("user_text", "") or ""),
            )
        except Exception as exc:
            self._log("debug", "[conversation-v12] observation write-back degraded: %s", exc)

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
