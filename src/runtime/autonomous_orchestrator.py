# -*- coding: utf-8 -*-
"""autonomous_orchestrator.py - nối scene, opportunity và quyền nói.

Đây là tầng ra quyết định trước main cognition. Nó không viết câu và không gọi
TTS. Kết quả là ``AutonomousPlan`` nhỏ để:
- WakeGovernor được promote/demote có lý do;
- Director biết vì sao autonomous đang mở miệng;
- StageFrameBuilder dựng PerformanceAct đúng cơ hội;
- telemetry giải thích được vì sao Eris nói hoặc im.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, replace
from typing import Any

from runtime.autonomous_opportunity import AutonomousOpportunity, AutonomousOpportunityDetector
from runtime.autonomous_scene_runtime import AutonomousSceneRuntime, SceneRuntimeState
from runtime.autonomous_speak_gate import AutonomousSpeakPermissionGate, SpeakPermit


def _enabled() -> bool:
    return os.environ.get("ERIS_AUTONOMOUS_STAGE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AutonomousPlan:
    scene: SceneRuntimeState
    opportunities: tuple[AutonomousOpportunity, ...]
    selected_opportunity: AutonomousOpportunity | None
    permit: SpeakPermit
    evaluated_at_ms: int
    enabled: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "evaluated_at_ms": self.evaluated_at_ms,
            "scene": self.scene.to_payload(),
            "opportunities": [item.to_payload() for item in self.opportunities],
            "selected_opportunity": self.selected_opportunity.to_payload() if self.selected_opportunity else None,
            "permit": self.permit.to_payload(),
        }


class AutonomousPerformerOrchestrator:
    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self.scene_runtime = AutonomousSceneRuntime()
        self.detector = AutonomousOpportunityDetector()
        self.speak_gate = AutonomousSpeakPermissionGate()
        self.last_plan: AutonomousPlan | None = None

    def evaluate(
        self,
        *,
        signal_snapshot: Any,
        observer_frame: Any = None,
        signal_diff: Any = None,
        user_context: Any = None,
        wake_decision: Any = None,
        now_ms: int | None = None,
    ) -> AutonomousPlan:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        scene = self.scene_runtime.update(
            signal_snapshot=signal_snapshot,
            observer_frame=observer_frame,
            now_ms=now,
        )
        if not _enabled():
            permit = SpeakPermit(False, "suppress", 0, 0, "autonomous_stage_disabled", 0, 1.0)
            plan = AutonomousPlan(scene, (), None, permit, now, enabled=False)
            self.last_plan = plan
            return plan

        opportunities = self.detector.detect(
            scene=scene,
            signal_snapshot=signal_snapshot,
            observer_frame=observer_frame,
            signal_diff=signal_diff,
            wake_decision=wake_decision,
            now_ms=now,
        )
        selected = opportunities[0] if opportunities else None
        permit = self.speak_gate.evaluate(
            selected,
            scene=scene,
            user_context=user_context,
            wake_decision=wake_decision,
            now_ms=now,
        )
        plan = AutonomousPlan(scene, opportunities, selected, permit, now)
        self.last_plan = plan
        return plan

    def refine_wake_decision(self, wake_decision: Any, plan: AutonomousPlan) -> Any:
        """Ghép gate mới vào WakeDecision mà không đổi public contract của governor."""
        if wake_decision is None:
            return wake_decision
        debug = dict(getattr(wake_decision, "debug", {}) or {})
        debug["autonomous_stage_plan"] = plan.to_payload()
        selected = plan.selected_opportunity
        permit = plan.permit
        level = str(getattr(wake_decision, "level", "sleep") or "sleep")
        should_speak = bool(getattr(wake_decision, "should_speak", False))
        should_wake_main = bool(getattr(wake_decision, "should_wake_main", False))
        reason = str(getattr(wake_decision, "reason", "") or "")

        if permit.allowed and permit.mode in {"short_reply", "full_line"} and selected is not None:
            # SpeakGate đã chứng minh có một lý do sân khấu đủ mạnh. Vì pipeline
            # hiện tại chỉ sinh câu động ở main cognition, permit này phải mở main
            # đúng một lượt. Cooldown/opportunity expiry giữ nó khỏi biến thành
            # timer gọi LLM liên tục. Đây là wake có điều kiện, không phải nói vì
            # silence debt.
            level = "wake_main_cognition"
            should_speak = True
            should_wake_main = True
            reason = f"autonomous_opportunity:{selected.kind}"
            debug["autonomous_speak_budget_words"] = permit.max_words
            debug["autonomous_speak_budget_ms"] = permit.max_duration_ms
        elif should_speak:
            # Governor muốn nói nhưng SpeakGate thấy chen lời không đáng. Giữ think
            # nếu cognition nội bộ còn giá trị, còn không lùi về observe_only.
            should_speak = False
            should_wake_main = False
            level = "think_only" if bool(getattr(wake_decision, "should_run_daydream", False)) else "observe_only"
            reason = f"autonomous_speak_gate:{permit.reason}"

        try:
            return replace(
                wake_decision,
                level=level,
                should_speak=should_speak,
                should_wake_main=should_wake_main,
                reason=reason,
                debug=debug,
            )
        except TypeError:
            # Fallback cho fake object trong test/plugin cũ.
            setattr(wake_decision, "level", level)
            setattr(wake_decision, "should_speak", should_speak)
            setattr(wake_decision, "should_wake_main", should_wake_main)
            setattr(wake_decision, "reason", reason)
            setattr(wake_decision, "debug", debug)
            return wake_decision

    def mark_spoken(self, plan: AutonomousPlan | None = None, *, at_ms: int | None = None) -> None:
        current = plan or self.last_plan
        if current is None or current.selected_opportunity is None:
            return
        self.speak_gate.record_spoken(kind=current.selected_opportunity.kind, at_ms=at_ms)


__all__ = ["AutonomousPerformerOrchestrator", "AutonomousPlan"]
