# -*- coding: utf-8 -*-
"""Projection context duy nhất cho ConversationKernel V12.

Module này KHÔNG phải planner và tuyệt đối không được chọn Eris sẽ nói gì.
Nó chỉ đọc những state/evidence đã tồn tại rồi nén chúng thành một packet chung
để RootAgent và SurfaceWriter nhìn cùng một "con người" ở cùng một thời điểm.

Boundary cần giữ:
- StateReducer sở hữu identity/personality/relationship đã học.
- MemoryKernel sở hữu recall/profile context.
- WorldState sở hữu môi trường/current scene có provenance.
- AffectiveVoiceState sở hữu hướng/cường độ biểu đạt sống.
- RootAgent vẫn là semantic/social authority duy nhất cho NextConversationMove.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from runtime.affective_voice_state import project_affective_voice_state
from runtime.public_reply_context import compile_public_reply_context
from runtime.subject_initiative_runtime import build_initiative_runtime_context
from runtime.world_state import ensure_world_state_service


def _call_text(owner: Any, name: str, *, limit: int) -> str:
    fn = getattr(owner, name, None)
    if not callable(fn):
        return ""
    try:
        return str(fn() or "").strip()[:limit]
    except Exception:
        return ""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_text(value: Any, *, limit: int) -> str:
    if value in (None, "", {}, (), []):
        return ""
    if isinstance(value, str):
        return value.strip()[:limit]
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)[:limit]
    except Exception:
        return str(value)[:limit]


class ConversationContextAssembler:
    """Thu context public-safe cho một event V12 mà không tạo semantic decision."""

    def __init__(self, host: Any) -> None:
        self.host = host

    def assemble(
        self,
        *,
        user_text: str = "",
        channel: str = "chat",
        previous_public_context: str = "",
        interrupt_context: str = "",
        recent_history: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        del recent_history  # reserved cho projection sau; không tự suy semantics từ prose.
        host = self.host
        state = self._mind_state()

        personality = _call_text(state, "personality_prompt_context", limit=12000)
        relationship = _call_text(getattr(state, "relationship", None), "prompt_summary", limit=12000)
        memory = self._memory_context(user_text)
        world = self._world_context(channel)
        clock = self._clock_context()
        addressing = self._user_addressing_context()

        # ``last_grounding_context`` là mirror OUTPUT của chính assembler. Không
        # đọc ngược nó ở lượt sau, nếu không context sẽ tự lồng chính nó và phình
        # dần theo số turn. Grounding V12 lấy trực tiếp từ source-of-truth hiện tại.
        grounding = "\n\n".join(part for part in (world, clock, addressing) if part)[:32000]

        affect_payload: dict[str, Any] = {}
        affect_prompt = ""
        try:
            affect = project_affective_voice_state(host, mind_state=state, channel=channel)
            affect_payload = affect.to_dict()
            affect_prompt = affect.prompt_context()
        except Exception as exc:
            self._debug("context.affect", exc)

        engagement: dict[str, Any] = {}
        try:
            engagement = _mapping(build_initiative_runtime_context(host))
        except Exception as exc:
            self._debug("context.engagement", exc)

        conversation_status = self._conversation_status(state, channel=channel)
        engagement_text = _json_text(engagement, limit=8000)
        discourse = self._discourse_context()
        compiled = compile_public_reply_context(
            personality=personality,
            relationship=relationship,
            grounding=grounding,
            memory=memory,
            interrupt=str(interrupt_context or "")[:6000],
            engagement=engagement_text,
            discourse=discourse,
            total_limit=96000,
            budget_mode="wide",
        )

        context: dict[str, Any] = {
            "personality_context": compiled.personality,
            "relationship_context": compiled.relationship,
            "memory_context": compiled.memory,
            "grounding_context": compiled.grounding,
            "interrupt_context": compiled.interrupt,
            "engagement_context": engagement,
            "discourse_context": compiled.discourse,
            "affective_voice_state": affect_payload,
            "affective_voice_context": affect_prompt[:8000],
            "conversation_status": conversation_status,
            "private_cognition_context": self._private_cognition_context(),
            "user_addressing_context": addressing,
            "previous_public_excerpt": str(previous_public_context or "")[-6000:],
            "context_assembler": {
                "schema": "eris.conversation_context.v12",
                "compiled_chars": compiled.total_chars,
                "dropped": list(compiled.dropped),
                "truncated": list(compiled.truncated),
            },
        }

        # Mirror compatibility để panel/debug/caller cũ đọc được state mới nhất.
        # Đây là OUTPUT của assembler, không còn là input authority của V12.
        try:
            host.last_personality_context = context["personality_context"]
            host.last_relationship_context = context["relationship_context"]
            host.last_memory_context = context["memory_context"]
            host.last_grounding_context = context["grounding_context"]
            host.last_engagement_context = dict(engagement)
            host.last_affective_voice_state = dict(affect_payload)
        except Exception:
            pass
        return context

    def _mind_state(self) -> Any | None:
        reducer = getattr(self.host, "ai_state_reducer", None)
        snapshot = getattr(reducer, "snapshot", None)
        if not callable(snapshot):
            return None
        try:
            return snapshot()
        except Exception as exc:
            self._debug("context.state", exc)
            return None

    def _memory_context(self, user_text: str) -> str:
        kernel = getattr(self.host, "memory_kernel", None)
        renderer = getattr(kernel, "render_context", None)
        using_kernel = callable(renderer)
        if not using_kernel:
            renderer = getattr(getattr(self.host, "memory_core", None), "render_context", None)
        if not callable(renderer):
            return ""
        kwargs: dict[str, Any] = {}
        if using_kernel:
            kwargs = {
                "session_id": str(
                    getattr(self.host, "conversation_id", "")
                    or getattr(self.host, "thread_id", "")
                    or "foreground:primary"
                )[:180],
                "user_context_token_budget": 6000,
                "max_lines": 64,
            }
        try:
            return str(renderer(str(user_text or ""), **kwargs) or "").strip()[:32000]
        except TypeError:
            try:
                return str(renderer(str(user_text or "")) or "").strip()[:32000]
            except Exception as exc:
                self._debug("context.memory", exc)
                return ""
        except Exception as exc:
            self._debug("context.memory", exc)
            return ""

    def _world_context(self, channel: str) -> str:
        lane = "chat" if str(channel or "").strip().lower() == "chat" else "self_turn"
        try:
            return str(ensure_world_state_service(self.host).prompt_context(lane, refresh=True) or "")[:20000]
        except Exception as exc:
            self._debug("context.world", exc)
            return ""


    @staticmethod
    def _user_addressing_context() -> str:
        try:
            from runtime.user_addressing_state import user_addressing_prompt_context
            return str(user_addressing_prompt_context() or "")[:6000]
        except Exception:
            return ""

    def _discourse_context(self) -> str:
        """Continuity/ledger projection cũ, không semantic-parse lại user text."""
        builder = getattr(self.host, "_build_discourse_prompt_context", None)
        if not callable(builder):
            return ""
        try:
            ledger_factory = getattr(self.host, "_ensure_session_turn_ledger", None)
            current_index = 0
            if callable(ledger_factory):
                turns = ledger_factory().user_turns()
                if turns:
                    current_index = int(getattr(turns[-1], "index", 0) or 0)
            return str(builder(current_turn_index=current_index) or "")[:16000]
        except Exception as exc:
            self._debug("context.discourse", exc)
            return ""

    def _private_cognition_context(self) -> dict[str, Any]:
        """Structured private semantic artifacts; never raw model reasoning."""
        try:
            service = ensure_world_state_service(self.host)
            projection = service.projection("self_turn", refresh=False)
            cognition = projection.get("cognition", {}) if isinstance(projection, Mapping) else {}
            if not isinstance(cognition, Mapping):
                return {}
            return {
                "active_concerns": [dict(x) for x in tuple(cognition.get("active_concerns", ()) or ())[:12] if isinstance(x, Mapping)],
                "mental_material": [dict(x) for x in tuple(cognition.get("mental_material", ()) or ())[:12] if isinstance(x, Mapping)],
                "current_goal": str(cognition.get("current_goal", "") or "")[:500],
                "attention": str(cognition.get("attention", "") or "")[:160],
                "contract": "Private semantic artifacts only; do not reveal hidden reasoning or treat them as external facts.",
            }
        except Exception as exc:
            self._debug("context.private_cognition", exc)
            return {}

    @staticmethod
    def _clock_context() -> str:
        now = datetime.now().astimezone()
        return (
            "RUNTIME_CLOCK_FACT: "
            f"local_datetime={now.isoformat(timespec='seconds')}; "
            "source=local_system_clock; confidence=1.0."
        )

    @staticmethod
    def _conversation_status(state: Any, *, channel: str) -> dict[str, Any]:
        if state is None:
            return {"channel": channel, "open_loops": []}
        latest = getattr(state, "latest_observation", {})
        return {
            "channel": str(channel or "")[:40],
            "state_revision": int(getattr(state, "version", 0) or 0),
            "last_applied_turn_seq": int(getattr(state, "last_applied_turn_seq", 0) or 0),
            "open_loops": [str(item)[:500] for item in tuple(getattr(state, "open_loops", ()) or ())[:5]],
            "latest_observation": dict(latest) if isinstance(latest, Mapping) else {},
        }

    def _debug(self, operation: str, exc: Exception) -> None:
        logger = getattr(self.host, "logger", None)
        fn = getattr(logger, "debug", None) if logger is not None else None
        if callable(fn):
            try:
                fn("[conversation-context] %s degraded: %s", operation, exc)
            except Exception:
                pass


def ensure_conversation_context_assembler(host: Any) -> ConversationContextAssembler:
    existing = getattr(host, "conversation_context_assembler", None)
    if isinstance(existing, ConversationContextAssembler):
        return existing
    assembler = ConversationContextAssembler(host)
    try:
        host.conversation_context_assembler = assembler
    except Exception:
        pass
    return assembler


__all__ = ["ConversationContextAssembler", "ensure_conversation_context_assembler"]
