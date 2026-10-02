# -*- coding: utf-8 -*-
"""Intention planner cho autonomous và action routing cấp cao."""

from __future__ import annotations

from typing import Any, Mapping

from semantic_authority import SemanticAuthorityPolicy

from .contracts import IntentionPlan, StateEvent


class IntentionPlanner:
    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger

    def plan_chat(self, snapshot: Mapping[str, Any], *, turn_seq: int) -> IntentionPlan:
        semantic_policy = SemanticAuthorityPolicy.from_runtime()

        # Semantic intention planner này vẫn local cho normal chat: nó không còn
        # là nơi "suy nghĩ một lần rồi writer nói luôn". Foreground cognitive /
        # execution / discourse planning hiện thuộc ConversationKernel root và có thể
        # chạy nhiều vòng trước khi tới đây. Giữ IntentionPlanner local giúp nó
        # chỉ làm compatibility projection, tránh tạo thêm semantic authority.
        agent_turn = snapshot.get("agent_turn") if isinstance(snapshot.get("agent_turn"), Mapping) else None
        needs_tool_planner = bool(snapshot.get("explicit_tool_route", False))
        if agent_turn is not None:
            # RootAgent là semantic owner của foreground planning.
            # IntentionPlan chỉ còn là projection tương thích cho downstream cũ;
            # tuyệt đối không gọi thêm một planner model để diễn giải lại objective.
            cognitive = agent_turn.get("cognitive_plan") if isinstance(agent_turn.get("cognitive_plan"), Mapping) else {}
            discourse = agent_turn.get("discourse_plan") if isinstance(agent_turn.get("discourse_plan"), Mapping) else {}
            objective = str(cognitive.get("objective", "") or "").strip()
            response_mode = str(discourse.get("response_mode", "normal") or "normal").strip().lower()
            plan = IntentionPlan.from_mapping(
                {
                    "speak": True,
                    "motive": "respond_to_user",
                    "strategy": "agent_turn_owned",
                    "value_focus": "continuity",
                    "topic": objective or "Answer the current user according to the unified agent turn contract.",
                    "importance": 0.78,
                    "intrusion_risk": 0.0,
                    "confidence": 0.86,
                    "performance_hint": "neutral",
                    "tool_intent": "",
                    "tool_input": "",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "chat_response",
                        "speech_act": "agent_turn_owned",
                        "subject_key": "current_user_turn",
                        "evidence_scope": "user_message_plus_recent_history",
                        "continuation_key": str((discourse.get("continuation") or {}).get("active_thread", "") if isinstance(discourse.get("continuation"), Mapping) else ""),
                    },
                    "activity": {
                        "activity_kind": "unknown", "phase": response_mode or "normal", "event": "",
                        "event_key": "none", "confidence": 0.0, "evidence_refs": [],
                    },
                    "notes": "compat_projection:unified_agent_turn_v3",
                },
                channel="chat",
            )
        elif semantic_policy.primary_model_first and not needs_tool_planner:
            plan = IntentionPlan.from_mapping(
                {
                    "speak": True,
                    "motive": "respond_to_user",
                    "strategy": "direct_answer",
                    "value_focus": "continuity",
                    "topic": "Let the main semantic authority answer the current user directly and naturally.",
                    "importance": 0.72,
                    "intrusion_risk": 0.0,
                    "confidence": 0.78,
                    "performance_hint": "neutral",
                    "tool_intent": "",
                    "tool_input": "",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "chat_response",
                        "speech_act": "model_owned",
                        "subject_key": "current_user_turn",
                        "evidence_scope": "user_message_plus_recent_history",
                        "continuation_key": "none",
                    },
                    "activity": {
                        "activity_kind": "unknown", "phase": "unknown", "event": "",
                        "event_key": "none", "confidence": 0.0, "evidence_refs": [],
                    },
                    "notes": "local_planner:semantic_authority_single_call",
                },
                channel="chat",
            )
        else:
            try:
                plan = self.router.plan_chat(snapshot)
            except Exception as exc:  # noqa: BLE001
                self._log("warning", "[chat intention planner] failed: %s", exc)
                plan = IntentionPlan.from_mapping(
                    {
                        "speak": True,
                        "motive": "respond_to_user",
                        "strategy": "direct_answer",
                        "value_focus": "",
                        "topic": "Answer the current user directly and naturally.",
                        "importance": 0.70,
                        "intrusion_risk": 0.0,
                        "confidence": 0.50,
                        "performance_hint": "neutral",
                        "tool_intent": "",
                        "tool_input": "",
                        "evidence_refs": [],
                        "notes": f"planner_error:{type(exc).__name__}",
                    },
                    channel="chat",
                )
        self.reducer.submit(
            StateEvent.from_intention(
                plan,
                turn_seq=turn_seq,
                base_version=self.reducer.snapshot().version,
            )
        )
        return plan

    def plan_autonomous(self, snapshot: Mapping[str, Any], *, turn_seq: int = 0) -> IntentionPlan:
        try:
            plan = self.router.plan_autonomous(snapshot)
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[intention planner] failed: %s", exc)
            plan = IntentionPlan.silence(channel="autonomous", reason=f"planner_error:{type(exc).__name__}")
        self.reducer.submit(
            StateEvent.from_intention(
                plan,
                turn_seq=turn_seq,
                base_version=self.reducer.snapshot().version,
            )
        )
        return plan

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["IntentionPlanner"]
