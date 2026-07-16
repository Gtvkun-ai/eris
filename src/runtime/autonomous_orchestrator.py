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
from runtime.autonomous_debug_snapshot import AutonomousDebugSnapshotStore
from runtime.autonomous_long_run_audit import AutonomousLongRunAudit
from runtime.autonomous_policy_resolver import AutonomousPolicyDecision, AutonomousPolicyResolver
from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
from runtime.autonomous_audience_feedback import (
    AudienceFeedbackDirective,
    AudienceOutcome,
    AutonomousAudienceFeedbackLoop,
)
from runtime.autonomous_scene_runtime import AutonomousSceneRuntime, SceneRuntimeState
from runtime.autonomous_speak_gate import AutonomousSpeakPermissionGate, SpeakPermit
from runtime.autonomous_session_director import AutonomousSessionDirector, SessionDirective
from runtime.autonomous_show_arc import AutonomousShowArcDirector, ShowArcDirective
from runtime.autonomous_stage_presets import AutonomousStagePreset, AutonomousStagePresetResolver


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
    session_directive: SessionDirective | None = None
    show_arc_directive: ShowArcDirective | None = None
    stage_preset: AutonomousStagePreset | None = None
    audience_feedback: AudienceFeedbackDirective | None = None
    policy_decision: AutonomousPolicyDecision | None = None
    architecture_version: str = AUTONOMOUS_STAGE_ARCHITECTURE_VERSION
    cycle_id: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "evaluated_at_ms": self.evaluated_at_ms,
            "scene": self.scene.to_payload(),
            "opportunities": [item.to_payload() for item in self.opportunities],
            "selected_opportunity": self.selected_opportunity.to_payload() if self.selected_opportunity else None,
            "permit": self.permit.to_payload(),
            "session_directive": self.session_directive.to_payload() if self.session_directive else None,
            "show_arc_directive": self.show_arc_directive.to_payload() if self.show_arc_directive else None,
            "stage_preset": self.stage_preset.to_payload() if self.stage_preset else None,
            "audience_feedback": self.audience_feedback.to_payload() if self.audience_feedback else None,
            "policy_decision": self.policy_decision.to_payload() if self.policy_decision else None,
            "architecture_version": self.architecture_version,
            "cycle_id": self.cycle_id,
        }


class AutonomousPerformerOrchestrator:
    def __init__(self, *, logger: Any = None, observability: Any = None) -> None:
        self.logger = logger
        self.observability = observability
        self.scene_runtime = AutonomousSceneRuntime()
        self.detector = AutonomousOpportunityDetector()
        self.speak_gate = AutonomousSpeakPermissionGate()
        self.session_director = AutonomousSessionDirector()
        self.show_arc_director = AutonomousShowArcDirector()
        self.stage_preset_resolver = AutonomousStagePresetResolver()
        self.audience_feedback_loop = AutonomousAudienceFeedbackLoop()
        # Phase 6: một resolver duy nhất hợp nhất quyền nói, audit dài hạn phát
        # hiện spam/permit ma, còn debug store giải thích quyết định mà không lưu text.
        self.policy_resolver = AutonomousPolicyResolver()
        self.long_run_audit = AutonomousLongRunAudit()
        self.debug_store = AutonomousDebugSnapshotStore()
        self.last_plan: AutonomousPlan | None = None
        # Phase 7: opportunity bị defer trong post-chat grace được giữ tới khi
        # eligible; không chết sau 12–15 giây rồi biến mất khỏi lịch sử.
        self._pending_opportunities: dict[str, AutonomousOpportunity] = {}

    def evaluate(
        self,
        *,
        signal_snapshot: Any,
        observer_frame: Any = None,
        signal_diff: Any = None,
        user_context: Any = None,
        wake_decision: Any = None,
        now_ms: int | None = None,
        cycle_id: str = "",
        runtime_policy: dict[str, Any] | None = None,
    ) -> AutonomousPlan:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        scene = self.scene_runtime.update(
            signal_snapshot=signal_snapshot,
            observer_frame=observer_frame,
            now_ms=now,
        )
        # Đóng pending feedback đã hết hạn trước khi chấm lượt mới.
        self.observe_audience(channel="autonomous", now_ms=now)
        stage_preset = self.stage_preset_resolver.resolve(
            scene=scene,
            signal_snapshot=signal_snapshot,
        )
        if not _enabled():
            permit = SpeakPermit(False, "suppress", 0, 0, "autonomous_stage_disabled", 0, 1.0)
            directive = self.session_director.direct(scene=scene, opportunities=(), now_ms=now)
            show_arc = self.show_arc_director.direct(
                scene=scene, opportunity=None, session_directive=directive, now_ms=now
            )
            audience_feedback = self.audience_feedback_loop.directive(now_ms=now)
            policy_decision = self.policy_resolver.resolve(
                base_permit=permit,
                opportunity=None,
                stage_preset=stage_preset,
                session_director=self.session_director,
                session_directive=directive,
                audience_feedback_loop=self.audience_feedback_loop,
                audience_directive=audience_feedback,
                runtime_policy=runtime_policy,
                now_ms=now,
            )
            plan = AutonomousPlan(
                scene=scene,
                opportunities=(),
                selected_opportunity=None,
                permit=policy_decision.permit,
                evaluated_at_ms=now,
                enabled=False,
                session_directive=directive,
                show_arc_directive=show_arc,
                stage_preset=stage_preset,
                audience_feedback=audience_feedback,
                policy_decision=policy_decision,
                cycle_id=str(cycle_id or ""),
            )
            self.last_plan = plan
            self._track_plan(plan)
            return plan

        opportunities = self.detector.detect(
            scene=scene,
            signal_snapshot=signal_snapshot,
            observer_frame=observer_frame,
            signal_diff=signal_diff,
            wake_decision=wake_decision,
            now_ms=now,
        )
        opportunities = self._merge_pending_opportunities(
            opportunities,
            scene=scene,
            now_ms=now,
            runtime_policy=runtime_policy,
        )
        eligible_opportunities = self.stage_preset_resolver.selectable_opportunities(
            opportunities,
            stage_preset,
        )
        # Phase 5: phản hồi sau act chỉ được hạ/đổi thứ tự cơ hội, không tự
        # sinh cơ hội mới. Nhờ vậy một lần user cười không biến thành giấy phép
        # để Eris nói tiếp như người vừa phát hiện nút phát lại.
        eligible_opportunities = self.audience_feedback_loop.adjust_opportunities(
            eligible_opportunities, now_ms=now
        )
        directive = self.session_director.direct(
            scene=scene,
            opportunities=eligible_opportunities,
            now_ms=now,
        )
        selected = next(
            (item for item in eligible_opportunities if item.opportunity_id == directive.selected_opportunity_id),
            None,
        )
        show_arc = self.show_arc_director.direct(
            scene=scene,
            opportunity=selected,
            session_directive=directive,
            now_ms=now,
        )
        base_permit = self.speak_gate.evaluate(
            selected,
            scene=scene,
            user_context=user_context,
            wake_decision=wake_decision,
            stage_preset=stage_preset,
            now_ms=now,
        )
        audience_feedback = self.audience_feedback_loop.directive(
            opportunity=selected, now_ms=now
        )
        policy_decision = self.policy_resolver.resolve(
            base_permit=base_permit,
            opportunity=selected,
            stage_preset=stage_preset,
            session_director=self.session_director,
            session_directive=directive,
            audience_feedback_loop=self.audience_feedback_loop,
            audience_directive=audience_feedback,
            runtime_policy=runtime_policy,
            now_ms=now,
        )
        plan = AutonomousPlan(
            scene=scene,
            opportunities=opportunities,
            selected_opportunity=selected,
            permit=policy_decision.permit,
            evaluated_at_ms=now,
            session_directive=directive,
            show_arc_directive=show_arc,
            stage_preset=stage_preset,
            audience_feedback=audience_feedback,
            policy_decision=policy_decision,
            cycle_id=str(cycle_id or ""),
        )
        self.last_plan = plan
        self._track_plan(plan)
        return plan

    def _merge_pending_opportunities(
        self,
        fresh: tuple[AutonomousOpportunity, ...],
        *,
        scene: SceneRuntimeState,
        now_ms: int,
        runtime_policy: dict[str, Any] | None,
    ) -> tuple[AutonomousOpportunity, ...]:
        """Giữ opportunity qua post-chat grace và dedupe transition mới nhất."""
        blocked_until = int((runtime_policy or {}).get("presence_blocked_until_ms", 0) or 0)
        # Dọn item đã hết hạn. Pending chỉ hết hạn sau cửa eligible của chính nó.
        for opp_id, item in list(self._pending_opportunities.items()):
            if now_ms >= int(item.expires_at_ms or 0):
                self._pending_opportunities.pop(opp_id, None)

        for item in fresh:
            current = item
            is_emergency = item.kind == "new_error" and float(item.urgency or 0.0) >= 0.92
            if blocked_until > now_ms and not is_emergency:
                ttl = max(1_000, int(item.expires_at_ms - item.created_at_ms))
                current = replace(
                    item,
                    eligible_after_ms=blocked_until,
                    expires_at_ms=blocked_until + ttl,
                    status="pending",
                )
            # Scene transition chỉ giữ bản mới nhất. Không xếp hàng đọc biên bản
            # mọi cửa sổ user đã lướt qua trong lúc grace.
            if current.kind == "scene_transition":
                for old_id, old in list(self._pending_opportunities.items()):
                    if old.kind == "scene_transition" and old_id != current.opportunity_id:
                        self._pending_opportunities.pop(old_id, None)
            self._pending_opportunities[current.opportunity_id] = current

        merged: list[AutonomousOpportunity] = []
        for item in self._pending_opportunities.values():
            if item.scene_mode != scene.name and item.kind not in {"scene_transition", "return_after_idle"}:
                continue
            if int(item.eligible_after_ms or 0) <= now_ms and item.status == "pending":
                item = replace(item, status="eligible")
                self._pending_opportunities[item.opportunity_id] = item
            merged.append(item)
        merged.sort(
            key=lambda item: (
                int(item.eligible_after_ms or 0) <= now_ms,
                item.strength + item.urgency * 0.25 + item.novelty * 0.15,
            ),
            reverse=True,
        )
        return tuple(merged)

    def cancel_plan(self, plan: AutonomousPlan | None, *, reason: str = "cancelled") -> None:
        """Không consume opportunity khi user chen vào hoặc stage/TTS lỗi."""
        current = plan or self.last_plan
        if current is None or current.selected_opportunity is None:
            return
        # Opportunity lỗi hệ thống vẫn được giữ nếu chưa hết hạn; vòng sau có thể
        # thử lại. User chat mới thì bỏ transition cũ vì scene xã hội đã thay đổi.
        if reason in {"cancelled_by_user", "enter_chat_mode", "scene_changed"}:
            self._pending_opportunities.pop(current.selected_opportunity.opportunity_id, None)

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

    def observe_audience(
        self,
        *,
        channel: str = "",
        user_text: str = "",
        signal_snapshot: Any = None,
        observer_frame: Any = None,
        now_ms: int | None = None,
    ) -> AudienceOutcome | None:
        """Đóng outcome của act gần nhất bằng tín hiệu hành vi quan sát được.

        Chat được xử lý cả khi coordinator không chạy một lượt autonomous mới.
        Với tick nền, scene state hiện tại đủ để kết luận continued_focus/ignored
        sau khi cửa sổ phản hồi hết hạn.
        """
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        scene = self.scene_runtime.state if getattr(self.scene_runtime, "_initialized", False) else None
        outcome = self.audience_feedback_loop.observe(
            channel=channel,
            user_text=user_text,
            scene=scene,
            now_ms=now,
        )
        observer = self.observability
        if outcome is not None and observer is not None and callable(getattr(observer, "record_autonomous_feedback", None)):
            try:
                observer.record_autonomous_feedback(
                    outcome=outcome,
                    directive=self.audience_feedback_loop.directive(now_ms=now),
                )
            except Exception:
                pass
        return outcome

    def mark_spoken(
        self,
        plan: AutonomousPlan | None = None,
        *,
        at_ms: int | None = None,
        intent: str = "",
        hook_id: str = "",
        text: str = "",
    ) -> None:
        current = plan or self.last_plan
        if current is None or current.selected_opportunity is None:
            return
        kind = current.selected_opportunity.kind
        self._pending_opportunities.pop(current.selected_opportunity.opportunity_id, None)
        self.speak_gate.record_spoken(kind=kind, at_ms=at_ms)
        self.session_director.record_spoken(
            kind=kind,
            intent=intent,
            hook_id=hook_id,
            at_ms=at_ms,
        )
        self.show_arc_director.record_spoken(
            text=text,
            opportunity=current.selected_opportunity,
            directive=current.show_arc_directive,
            intent=intent,
            hook_id=hook_id,
            at_ms=at_ms,
        )
        self.audience_feedback_loop.record_act(
            opportunity=current.selected_opportunity,
            scene_mode=current.scene.name,
            text=text,
            intent=intent,
            hook_id=hook_id,
            at_ms=at_ms,
        )
        self.long_run_audit.record_commit(current, at_ms=at_ms)
        self.debug_store.record_commit(
            current,
            intent=intent,
            hook_id=hook_id,
            at_ms=at_ms,
        )
        observer = self.observability
        if observer is not None and callable(getattr(observer, "record_autonomous_commit", None)):
            try:
                observer.record_autonomous_commit(
                    plan=current,
                    intent=intent,
                    hook_id=hook_id,
                    session_snapshot=self.session_director.snapshot(now_ms=at_ms),
                    show_arc_snapshot=self.show_arc_director.snapshot(now_ms=at_ms),
                    audience_feedback_snapshot=self.audience_feedback_loop.snapshot(now_ms=at_ms),
                )
            except Exception:
                pass

    def debug_snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Trả snapshot an toàn cho panel/debug API, không chứa câu user/assistant."""
        audit_snapshot = self.long_run_audit.snapshot(now_ms=now_ms)
        return self.debug_store.snapshot(audit_snapshot=audit_snapshot, now_ms=now_ms)

    def _track_plan(self, plan: AutonomousPlan) -> None:
        self.long_run_audit.observe_plan(plan, now_ms=plan.evaluated_at_ms)
        audit_snapshot = self.long_run_audit.snapshot(now_ms=plan.evaluated_at_ms)
        self.debug_store.record_plan(
            plan,
            policy_decision=plan.policy_decision,
            audit_snapshot=audit_snapshot,
        )
        self._record_plan(plan, audit_snapshot=audit_snapshot)

    def _record_plan(self, plan: AutonomousPlan, *, audit_snapshot: Any = None) -> None:
        observer = self.observability
        if observer is None:
            return
        try:
            recorder = getattr(observer, "record_autonomous_plan", None)
            if callable(recorder):
                recorder(plan)
            audit_recorder = getattr(observer, "record_autonomous_audit", None)
            if callable(audit_recorder) and audit_snapshot is not None:
                audit_recorder(audit_snapshot)
        except Exception:
            # Observability không được phép chặn một tick autonomous.
            pass


__all__ = ["AutonomousPerformerOrchestrator", "AutonomousPlan"]
