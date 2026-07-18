# -*- coding: utf-8 -*-
"""Intention planner cho autonomous và action routing cấp cao."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import IntentionPlan, StateEvent


class IntentionPlanner:
    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger

    def plan_chat(self, snapshot: Mapping[str, Any], *, turn_seq: int) -> IntentionPlan:
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
