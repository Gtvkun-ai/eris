# -*- coding: utf-8 -*-
"""
src/runtime/autonomous_wake_governor.py
=======================================

Wake Governor - trọng tài quyết định mức độ thức của ERIS.

Kết quả KHÔNG phải nói/không nói.
Kết quả là mức thức:
- sleep
- observe_only
- think_only
- micro_presence
- call_vision_compressor
- wake_main_cognition

Năm trụ cột:
1. ExternalPressure
2. InternalDrive
3. ComputeBudget
4. Permission / interrupt cost
5. SpeechValue

Tức là ERIS có thể thấy thứ thú vị, rất muốn nói, nhưng vẫn im vì user đang deep focus.
Lạ thay, đó gọi là biết điều.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

try:
    from cortex.user_context_stream import RollingUserContext
    from cortex.endogenous_drive import RollingInternalState
    from cortex.internal_agenda import InternalAgendaStack
except Exception:  # pragma: no cover
    from src.cortex.user_context_stream import RollingUserContext  # type: ignore
    from src.cortex.endogenous_drive import RollingInternalState  # type: ignore
    from src.cortex.internal_agenda import InternalAgendaStack  # type: ignore

try:
    from runtime.model_budget_policy import BudgetDecision, ModelBudgetPolicy, ResourceSnapshot
except Exception:  # pragma: no cover
    from .model_budget_policy import BudgetDecision, ModelBudgetPolicy, ResourceSnapshot  # type: ignore

WakeLevel = Literal[
    "sleep",
    "observe_only",
    "think_only",
    "micro_presence",
    "call_vision_compressor",
    "wake_main_cognition",
]


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    if math.isnan(n) or math.isinf(n):
        n = default
    return max(0.0, min(1.0, n))


@dataclass(slots=True)
class WakeDecision:
    level: WakeLevel
    should_speak: bool
    should_call_vision: bool
    should_wake_main: bool
    should_run_daydream: bool
    reason: str
    confidence: float
    external_pressure: float = 0.0
    internal_drive: float = 0.0
    compute_budget: float = 1.0
    permission: float = 1.0
    speech_value: float = 0.0
    interrupt_cost: float = 0.0
    budget_reason: str = ""
    selected_agenda_ids: tuple[str, ...] = ()
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WakeGovernorConfig:
    observe_threshold: float = 0.18
    think_threshold: float = 0.38
    micro_presence_threshold: float = 0.54
    vision_threshold: float = 0.66
    main_threshold: float = 0.78
    max_interrupt_for_speech: float = 0.58
    max_interrupt_for_main: float = 0.42
    min_speech_value: float = 0.34


class AutonomousWakeGovernor:
    """Trọng tài wake state."""

    def __init__(self, config: WakeGovernorConfig | None = None) -> None:
        self.config = config or WakeGovernorConfig()
        self.last_decision = WakeDecision(
            level="sleep",
            should_speak=False,
            should_call_vision=False,
            should_wake_main=False,
            should_run_daydream=False,
            reason="init",
            confidence=0.0,
        )

    def decide(
        self,
        *,
        user_context: RollingUserContext,
        internal_state: RollingInternalState,
        agenda_stack: InternalAgendaStack | None = None,
        budget_policy: ModelBudgetPolicy | None = None,
        resource_snapshot: ResourceSnapshot | None = None,
        autonomous_silent_cycles: int = 0,
        now: float | None = None,
    ) -> WakeDecision:
        del now
        external_pressure = _clamp01(getattr(user_context, "external_pressure", 0.0))
        internal_drive = _clamp01(getattr(internal_state, "internal_drive", 0.0))
        interrupt_cost = _clamp01(getattr(user_context, "interrupt_cost", 0.0))
        permission = _clamp01(1.0 - interrupt_cost)
        idle_seconds = max(0.0, float(getattr(user_context, "idle_seconds", 0.0) or 0.0))
        silence_debt = _clamp01(max(0, int(autonomous_silent_cycles or 0)) / 12.0)
        top_agenda = agenda_stack.top_items(limit=3) if agenda_stack is not None else []
        agenda_pressure = agenda_stack.pressure() if agenda_stack is not None else 0.0
        agenda_speech = max((item.speech_value for item in top_agenda), default=0.0)
        speech_value = _clamp01(
            0.36 * external_pressure
            + 0.24 * agenda_speech
            + 0.18 * internal_drive
            + 0.12 * _clamp01(getattr(user_context, "possible_error", 0.0))
            + 0.10 * _clamp01(getattr(user_context, "user_presence", 0.0))
            + silence_debt * 0.25
        )

        score = _clamp01(
            0.34 * external_pressure
            + 0.25 * internal_drive
            + 0.19 * permission
            + 0.15 * speech_value
            + 0.07 * agenda_pressure
        )

        budget_4b = self._budget(budget_policy, "subconscious_4b", resource_snapshot, "wake_governor_4b")
        budget_main = self._budget(budget_policy, "main_cognition", resource_snapshot, "wake_governor_main")
        budget_vision = self._budget(budget_policy, "vision_compressor", resource_snapshot, "wake_governor_vision")
        compute_budget = 1.0

        should_run_daydream = bool(
            getattr(internal_state, "consolidation_pressure", 0.0) >= 0.65 or getattr(internal_state, "insight_pressure", 0.0) >= 0.70
        )
        wants_vision = str(getattr(user_context, "recommended_action", "")) == "call_vision_compressor" or external_pressure >= self.config.vision_threshold
        wants_main = str(getattr(user_context, "recommended_action", "")) == "wake_main_cognition" or score >= self.config.main_threshold
        budget_reason = budget_main.reason if wants_main else (budget_vision.reason if wants_vision else budget_4b.reason)

        level: WakeLevel = "sleep"
        reason = "below_observe_threshold"
        should_speak = False
        should_call_vision = False
        should_wake_main = False

        if score >= self.config.observe_threshold:
            level = "observe_only"
            reason = "observe_threshold"
        if score >= self.config.think_threshold or should_run_daydream:
            level = "think_only"
            reason = "think_or_daydream_pressure"
        if wants_vision and permission >= 0.35:
            level = "call_vision_compressor"
            should_call_vision = True
            reason = "vision_needed"
        if (
            score >= self.config.micro_presence_threshold
            and speech_value >= self.config.min_speech_value
            and interrupt_cost <= self.config.max_interrupt_for_speech
        ):
            level = "micro_presence"
            should_speak = True
            reason = "micro_presence_value_ok"
        if wants_main:
            if interrupt_cost <= self.config.max_interrupt_for_main and speech_value >= self.config.min_speech_value:
                level = "wake_main_cognition"
                should_wake_main = True
                should_speak = True
                reason = "main_wake_allowed"
            elif interrupt_cost <= self.config.max_interrupt_for_speech and speech_value >= self.config.min_speech_value:
                level = "micro_presence"
                should_speak = True
                reason = "main_interrupt_degraded_to_micro_presence"
            else:
                level = "think_only" if should_run_daydream or internal_drive >= self.config.think_threshold else "observe_only"
                reason = "main_wake_vetoed_or_interrupt_cost_high"

        decision = WakeDecision(
            level=level,
            should_speak=should_speak,
            should_call_vision=should_call_vision,
            should_wake_main=should_wake_main,
            should_run_daydream=should_run_daydream,
            reason=reason,
            confidence=_clamp01(0.42 + abs(score - self.config.think_threshold) * 0.50),
            external_pressure=external_pressure,
            internal_drive=internal_drive,
            compute_budget=compute_budget,
            permission=permission,
            speech_value=speech_value,
            interrupt_cost=interrupt_cost,
            budget_reason=budget_reason,
            selected_agenda_ids=tuple(item.id for item in top_agenda),
            debug={
                "score": score,
                "agenda_pressure": agenda_pressure,
                "autonomous_silent_cycles": int(autonomous_silent_cycles or 0),
                "silence_debt": silence_debt,
                "silence_debt_weight": 0.25,
                "budget_4b": budget_4b.to_dict(),
                "budget_main": budget_main.to_dict(),
                "budget_vision": budget_vision.to_dict(),
            },
        )
        self.last_decision = decision
        return decision

    def _budget(self, policy: ModelBudgetPolicy | None, tier: str, snapshot: ResourceSnapshot | None, reason: str) -> BudgetDecision:
        if policy is None:
            snap = snapshot or ResourceSnapshot()
            return BudgetDecision("allow", True, tier, "no_budget_policy", snap)  # type: ignore[arg-type]
        return policy.can_run(tier, resource_snapshot=snapshot, reason=reason)  # type: ignore[arg-type]
