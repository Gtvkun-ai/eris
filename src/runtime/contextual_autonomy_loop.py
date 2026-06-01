# -*- coding: utf-8 -*-
"""
src/runtime/contextual_autonomy_loop.py
======================================

Adaptive heartbeat cho 3-tier autonomy.

Module này gom các mảnh:
- UserContextStream       (tầng cảm giác / 0.6B + rules)
- EndogenousDriveEngine   (nhịp nội sinh)
- InternalAgendaStack     (agenda nội bộ)
- DaydreamConsolidator    (4B khi có trigger thật)
- ModelBudgetPolicy       (veto tài nguyên)
- AutonomousWakeGovernor  (quyết định mức thức)

Nó KHÔNG thay thế toàn bộ RuntimeCoordinator ngay lập tức. Nó là backbone sạch để coordinator
có thể gọi từng tick. Vâng, tiến hóa có kiểm soát, không phải ném repo xuống vực rồi gọi đó là refactor.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

try:
    from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket, DaydreamResult
    from cortex.endogenous_drive import EndogenousDriveEngine, RollingInternalState
    from cortex.internal_agenda import InternalAgendaStack
    from cortex.observer_contracts import ObserverFrame, SignalDiff, SignalSnapshot
    from cortex.user_context_stream import RollingUserContext, UserContextStream
except Exception:  # pragma: no cover
    from src.cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket, DaydreamResult  # type: ignore
    from src.cortex.endogenous_drive import EndogenousDriveEngine, RollingInternalState  # type: ignore
    from src.cortex.internal_agenda import InternalAgendaStack  # type: ignore
    from src.cortex.observer_contracts import ObserverFrame, SignalDiff, SignalSnapshot  # type: ignore
    from src.cortex.user_context_stream import RollingUserContext, UserContextStream  # type: ignore

try:
    from runtime.autonomous_wake_governor import AutonomousWakeGovernor, WakeDecision
    from runtime.model_budget_policy import ModelBudgetPolicy, ResourceSnapshot
except Exception:  # pragma: no cover
    from .autonomous_wake_governor import AutonomousWakeGovernor, WakeDecision  # type: ignore
    from .model_budget_policy import ModelBudgetPolicy, ResourceSnapshot  # type: ignore


@dataclass(slots=True)
class ContextualAutonomyLoopConfig:
    min_heartbeat_seconds: float = 2.0
    max_heartbeat_seconds: float = 90.0
    active_heartbeat_seconds: float = 5.0
    observe_heartbeat_seconds: float = 15.0
    sleep_heartbeat_seconds: float = 45.0


@dataclass(slots=True)
class AutonomyLoopTickResult:
    user_context: RollingUserContext
    internal_state: RollingInternalState
    wake_decision: WakeDecision
    daydream_result: DaydreamResult | None = None
    resource_snapshot: ResourceSnapshot | None = None
    next_heartbeat_seconds: float = 30.0
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_context": self.user_context.to_dict(),
            "internal_state": self.internal_state.to_dict(),
            "wake_decision": self.wake_decision.to_dict(),
            "daydream_result": self.daydream_result.to_dict() if self.daydream_result else None,
            "resource_snapshot": self.resource_snapshot.to_dict() if self.resource_snapshot else None,
            "next_heartbeat_seconds": self.next_heartbeat_seconds,
            "debug": self.debug,
        }


class ContextualAutonomyLoop:
    """Backbone điều phối 3 tầng, gọi được từ coordinator."""

    def __init__(
        self,
        *,
        user_context_stream: UserContextStream | None = None,
        endogenous_drive: EndogenousDriveEngine | None = None,
        agenda_stack: InternalAgendaStack | None = None,
        daydream: DaydreamConsolidator | None = None,
        budget_policy: ModelBudgetPolicy | None = None,
        wake_governor: AutonomousWakeGovernor | None = None,
        config: ContextualAutonomyLoopConfig | None = None,
        logger: Any = None,
    ) -> None:
        self.user_context_stream = user_context_stream or UserContextStream()
        self.endogenous_drive = endogenous_drive or EndogenousDriveEngine()
        self.agenda_stack = agenda_stack or InternalAgendaStack()
        self.daydream = daydream or DaydreamConsolidator()
        self.budget_policy = budget_policy or ModelBudgetPolicy()
        self.wake_governor = wake_governor or AutonomousWakeGovernor()
        self.config = config or ContextualAutonomyLoopConfig()
        self.logger = logger
        self.last_tick: AutonomyLoopTickResult | None = None

    def tick(
        self,
        *,
        signal_snapshot: SignalSnapshot | Mapping[str, Any] | None = None,
        signal_diff: SignalDiff | None = None,
        observer_frame: ObserverFrame | None = None,
        base_internal_state: Any = None,
        memory_packets: Iterable[DaydreamPacket] = (),
        user_text: str = "",
        channel: str = "autonomous",
        autonomous_silent_cycles: int = 0,
    ) -> AutonomyLoopTickResult:
        snapshot = signal_snapshot if isinstance(signal_snapshot, SignalSnapshot) else SignalSnapshot.from_mapping(signal_snapshot or {})
        user_context = self.user_context_stream.update(
            signal_snapshot=snapshot,
            signal_diff=signal_diff,
            observer_frame=observer_frame,
            user_text=user_text,
            channel=channel,
        )
        internal_state = self.endogenous_drive.update(
            user_context=user_context,
            base_internal_state=base_internal_state,
            agenda_stack=self.agenda_stack,
        )
        resource = self.budget_policy.capture(active_app=snapshot.active_app, active_window_title=snapshot.active_window_title)
        wake = self.wake_governor.decide(
            user_context=user_context,
            internal_state=internal_state,
            agenda_stack=self.agenda_stack,
            budget_policy=self.budget_policy,
            resource_snapshot=resource,
            autonomous_silent_cycles=autonomous_silent_cycles,
        )
        daydream_result = None
        trigger, trigger_reason = self.daydream.should_trigger(user_context=user_context, internal_state=internal_state)
        if trigger and wake.should_run_daydream:
            try:
                daydream_result = self.budget_policy.run_queued(
                    "subconscious_4b",
                    self.daydream.consolidate,
                    memory_packets,
                    reason=f"daydream:{trigger_reason}",
                    priority=10,
                    timeout_seconds=0.5,
                    resource_snapshot=resource,
                    agenda_stack=self.agenda_stack,
                    context={
                        "trigger": trigger_reason,
                        "user_context": user_context.prompt_hint(),
                        "wake_level": wake.level,
                    },
                )
            except Exception as exc:
                budget = self.budget_policy.can_run("subconscious_4b", resource_snapshot=resource, reason=trigger_reason)
                self.agenda_stack.add(
                    kind="resource_guard",
                    summary=f"Daydream consolidation bị hoãn bởi scheduler/budget: {getattr(exc, 'args', [''])[0] or budget.reason}",
                    evidence_ids=("model_budget_policy",),
                    pressure=0.42,
                    urgency=0.22,
                    confidence=0.8,
                    speech_value=0.0,
                    source="contextual_autonomy_loop",
                    ttl_seconds=900,
                    payload={"budget": budget.to_dict(), "scheduler_error": str(exc)},
                )
        next_heartbeat = self.next_sleep_seconds(wake)
        result = AutonomyLoopTickResult(
            user_context=user_context,
            internal_state=internal_state,
            wake_decision=wake,
            daydream_result=daydream_result,
            resource_snapshot=resource,
            next_heartbeat_seconds=next_heartbeat,
            debug={"daydream_trigger": trigger, "daydream_trigger_reason": trigger_reason},
        )
        self.last_tick = result
        return result

    def next_sleep_seconds(self, decision: WakeDecision) -> float:
        level = decision.level
        if level in {"wake_main_cognition", "call_vision_compressor", "micro_presence"}:
            base = self.config.active_heartbeat_seconds
        elif level in {"observe_only", "think_only"}:
            base = self.config.observe_heartbeat_seconds
        else:
            base = self.config.sleep_heartbeat_seconds
        # Khi interrupt cost cao thì kéo heartbeat ra, tránh nhìn user như camera an ninh uống cà phê.
        stretched = base * (1.0 + max(0.0, decision.interrupt_cost - 0.35))
        return max(self.config.min_heartbeat_seconds, min(self.config.max_heartbeat_seconds, stretched))
