# -*- coding: utf-8 -*-
"""Cortex heartbeat không có quyền phát ngôn.

Module cũ ``ContextualAutonomyLoop`` trộn ba việc: cập nhật state nội sinh, chạy
consolidation và quyết định Eris có được nói hay không. Architecture C chỉ cần
hai việc đầu. ``CortexAttentionSignal`` bên dưới là dữ liệu attention/resource
cho planner, tuyệt đối không có semantic veto hay ``should_speak`` authority.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket, DaydreamResult
from cortex.endogenous_drive import EndogenousDriveEngine, RollingInternalState
from cortex.internal_agenda import InternalAgendaStack
from cortex.observer_contracts import ObserverFrame, SignalDiff, SignalSnapshot
from cortex.user_context_stream import RollingUserContext, UserContextStream
from runtime.model_budget_policy import ModelBudgetPolicy, ResourceSnapshot


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class CortexAttentionSignal:
    """Signal số học cho attention, không phải quyết định public turn."""

    level: str = "quiet"
    external_pressure: float = 0.0
    internal_drive: float = 0.0
    interrupt_cost: float = 0.0
    resource_caution: float = 0.0
    vision_refresh_recommended: bool = False
    consolidation_allowed: bool = False
    budget_reason: str = ""
    reason: str = ""
    confidence: float = 1.0
    debug: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["semantic_authority"] = "none"
        return payload


@dataclass(slots=True)
class CortexRuntimeTick:
    user_context: RollingUserContext
    internal_state: RollingInternalState
    attention: CortexAttentionSignal
    daydream_result: DaydreamResult | None = None
    resource_snapshot: ResourceSnapshot | None = None
    next_heartbeat_seconds: float = 30.0
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_context": self.user_context.to_dict(),
            "internal_state": self.internal_state.to_dict(),
            "attention": self.attention.to_dict(),
            "daydream_result": self.daydream_result.to_dict() if self.daydream_result else None,
            "resource_snapshot": self.resource_snapshot.to_dict() if self.resource_snapshot else None,
            "next_heartbeat_seconds": self.next_heartbeat_seconds,
            "debug": dict(self.debug),
        }


class CortexRuntime:
    """Cập nhật context/drive/consolidation; main planner tự quyết định lời nói."""

    def __init__(
        self,
        *,
        user_context_stream: UserContextStream | None = None,
        endogenous_drive: EndogenousDriveEngine | None = None,
        agenda_stack: InternalAgendaStack | None = None,
        daydream: DaydreamConsolidator | None = None,
        budget_policy: ModelBudgetPolicy | None = None,
        agent_mind: Any = None,
        logger: Any = None,
    ) -> None:
        self.user_context_stream = user_context_stream or UserContextStream()
        self.endogenous_drive = endogenous_drive or EndogenousDriveEngine()
        self.agenda_stack = agenda_stack or InternalAgendaStack()
        self.daydream = daydream or DaydreamConsolidator()
        self.budget_policy = budget_policy or ModelBudgetPolicy()
        self.agent_mind = agent_mind
        self.logger = logger
        self.last_tick: CortexRuntimeTick | None = None
        self._growth_consolidator = None

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
        **_: Any,
    ) -> CortexRuntimeTick:
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
        resource = self.budget_policy.capture(
            active_app=snapshot.active_app,
            active_window_title=snapshot.active_window_title,
        )
        attention = self._build_attention(user_context, internal_state, observer_frame, resource)
        trigger, trigger_reason = self.daydream.should_trigger(
            user_context=user_context,
            internal_state=internal_state,
        )
        daydream_result = None
        if trigger and attention.consolidation_allowed:
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
                        "attention_level": attention.level,
                    },
                )
            except Exception as exc:
                self.agenda_stack.add(
                    kind="resource_guard",
                    summary=f"Daydream consolidation bị hoãn bởi scheduler/budget: {exc}",
                    evidence_ids=("model_budget_policy",),
                    pressure=0.42,
                    urgency=0.22,
                    confidence=0.8,
                    speech_value=0.0,
                    source="cortex_runtime",
                    ttl_seconds=900,
                    payload={"scheduler_error": str(exc)},
                )
        self._maybe_run_growth(trigger=trigger, attention=attention)
        next_heartbeat = self._next_heartbeat(attention)
        result = CortexRuntimeTick(
            user_context=user_context,
            internal_state=internal_state,
            attention=attention,
            daydream_result=daydream_result,
            resource_snapshot=resource,
            next_heartbeat_seconds=next_heartbeat,
            debug={"daydream_trigger": trigger, "daydream_trigger_reason": trigger_reason},
        )
        self.last_tick = result
        return result

    def _build_attention(
        self,
        user_context: Any,
        internal_state: Any,
        observer_frame: Any,
        resource: ResourceSnapshot,
    ) -> CortexAttentionSignal:
        external = max(
            _clamp01(getattr(user_context, "novelty", 0.0)),
            _clamp01(getattr(observer_frame, "novelty", 0.0)),
            _clamp01(getattr(observer_frame, "possible_error", 0.0)),
        )
        internal = _clamp01(getattr(internal_state, "internal_drive", 0.0))
        interrupt = _clamp01(getattr(user_context, "interrupt_cost", 0.0))
        caution = _clamp01(getattr(internal_state, "resource_caution", 0.0))
        budget = self.budget_policy.can_run(
            "subconscious_4b",
            resource_snapshot=resource,
            reason="cortex_consolidation",
        )
        vision_hint = bool(
            getattr(observer_frame, "recommended_action", "") == "call_vision_compressor"
            or getattr(observer_frame, "should_request_vision", False)
        )
        pressure = max(external, internal)
        level = "active" if pressure >= 0.72 else "observe" if pressure >= 0.38 else "quiet"
        return CortexAttentionSignal(
            level=level,
            external_pressure=external,
            internal_drive=internal,
            interrupt_cost=interrupt,
            resource_caution=caution,
            vision_refresh_recommended=vision_hint,
            consolidation_allowed=bool(getattr(budget, "allowed", False) and interrupt < 0.72),
            budget_reason=str(getattr(budget, "reason", "") or ""),
            reason="attention_snapshot",
            debug={"observer_available": observer_frame is not None},
        )

    @staticmethod
    def _next_heartbeat(attention: CortexAttentionSignal) -> float:
        base = 5.0 if attention.level == "active" else 15.0 if attention.level == "observe" else 45.0
        return max(2.0, min(90.0, base * (1.0 + max(0.0, attention.interrupt_cost - 0.35))))

    def _maybe_run_growth(self, *, trigger: bool, attention: CortexAttentionSignal) -> None:
        try:
            from cortex.development_system import development_growth_enabled, get_default_development_system
            if not development_growth_enabled() or not trigger or not attention.consolidation_allowed:
                return
            from cortex.agent_mind_persistence import get_default_agent_mind_store
            from cortex.growth_consolidator import GrowthConsolidator
            from cortex.growth_evidence import observations_from_feedback
            store = self.agent_mind or get_default_agent_mind_store()
            store.reload_if_changed()
            observations, allowed = observations_from_feedback(store.last_feedback_events)
            if not observations:
                return
            system = get_default_development_system()
            system.profile.reload_if_changed()
            if self._growth_consolidator is None:
                self._growth_consolidator = GrowthConsolidator()
            system.tick(
                consolidator=self._growth_consolidator,
                observations=observations,
                allowed_evidence_ids=allowed,
                idle_pressure=1.0,
                budget_allows=True,
                user_interacting_high_risk=attention.interrupt_cost >= 0.72,
            )
        except Exception:
            # Growth là lane nền; lỗi của nó không được hạ runtime chính.
            pass


__all__ = ["CortexAttentionSignal", "CortexRuntime", "CortexRuntimeTick"]
