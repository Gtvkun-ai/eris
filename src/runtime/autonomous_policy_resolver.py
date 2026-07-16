# -*- coding: utf-8 -*-
"""autonomous_policy_resolver.py - một quyền quyết định cuối cho autonomous.

Phase 7 đưa post-chat grace, pending opportunity và các guard runtime vào cùng
một resolver. Sau khi resolver trả ``final_authority=True``, tầng sau chỉ được hạ
cấp vì lỗi hệ thống cứng (user chat mới, shutdown, TTS/stage failure), không được
lặng lẽ log ``permit=True`` rồi chặn bằng một policy mềm khác.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_speak_gate import SpeakPermit
from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION


_HARD_BLOCK_REASONS = {
    "autonomous_stage_disabled",
    "no_opportunity",
    "opportunity_expired",
    "opportunity_pending",
    "post_chat_grace_pending",
    "user_is_typing",
    "focus_interrupt_cost_high",
    "hourly_speech_budget_exhausted",
}


def _permit_payload(permit: SpeakPermit) -> dict[str, Any]:
    return {
        "allowed": bool(permit.allowed),
        "mode": str(permit.mode or "suppress"),
        "max_words": int(permit.max_words or 0),
        "max_duration_ms": int(permit.max_duration_ms or 0),
        "cooldown_after_ms": int(permit.cooldown_after_ms or 0),
        "confidence": float(permit.confidence or 0.0),
        "reason": str(permit.reason or ""),
        "defer_until_ms": int(permit.defer_until_ms or 0),
        "final_authority": bool(permit.final_authority),
    }


def _get(mapping: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    return mapping.get(key, default) if isinstance(mapping, Mapping) else default


@dataclass(frozen=True, slots=True)
class PolicyStep:
    policy: str
    changed: bool
    before: dict[str, Any]
    after: dict[str, Any]
    note: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AutonomousPolicyDecision:
    version: str
    permit: SpeakPermit
    steps: tuple[PolicyStep, ...]
    blockers: tuple[str, ...]
    conflict_flags: tuple[str, ...]
    emergency_override: bool
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "permit": self.permit.to_payload(),
            "steps": [step.to_payload() for step in self.steps],
            "blockers": list(self.blockers),
            "conflict_flags": list(self.conflict_flags),
            "emergency_override": self.emergency_override,
            "reason": self.reason,
        }


class AutonomousPolicyResolver:
    VERSION = "autonomous_policy_resolver.v2"

    def resolve(
        self,
        *,
        base_permit: SpeakPermit,
        opportunity: AutonomousOpportunity | None,
        stage_preset: Any = None,
        session_director: Any = None,
        session_directive: Any = None,
        audience_feedback_loop: Any = None,
        audience_directive: Any = None,
        runtime_policy: Mapping[str, Any] | None = None,
        now_ms: int | None = None,
    ) -> AutonomousPolicyDecision:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        steps: list[PolicyStep] = []
        blockers: list[str] = []
        conflicts: list[str] = []
        original = base_permit
        current = base_permit

        steps.append(PolicyStep(
            policy="speak_gate", changed=False,
            before=_permit_payload(base_permit), after=_permit_payload(base_permit),
            note="base_decision",
        ))

        # Runtime policy được áp trước cadence/feedback để telemetry không nói
        # permit=True trong lúc post-chat grace chắc chắn sẽ chặn nó ở tầng sau.
        current = self._apply_runtime_authority(
            current=current,
            opportunity=opportunity,
            runtime_policy=runtime_policy,
            now_ms=now,
            steps=steps,
        )

        base_reason = str(current.reason or "")
        hard_blocked = (not current.allowed) and any(token in base_reason for token in _HARD_BLOCK_REASONS)
        if not current.allowed:
            blockers.append(base_reason or "base_gate_denied")

        current = self._apply_policy(
            policy="session_director", current=current,
            applier=getattr(session_director, "apply_to_permit", None),
            args=(session_directive,), kwargs={"opportunity": opportunity},
            steps=steps, conflicts=conflicts,
        )
        current = self._apply_policy(
            policy="audience_feedback", current=current,
            applier=getattr(audience_feedback_loop, "apply_to_permit", None),
            args=(audience_directive,), kwargs={"opportunity": opportunity},
            steps=steps, conflicts=conflicts,
        )

        if hard_blocked and current.allowed:
            conflicts.append("hard_gate_reopened_by_downstream_policy")
            current = original if not original.allowed else current

        current = self._final_clamp(
            current=current, original=original, stage_preset=stage_preset,
            session_directive=session_directive, audience_directive=audience_directive,
            steps=steps, conflicts=conflicts,
        )
        before_final_permit = current
        current = SpeakPermit(
            allowed=current.allowed,
            mode=current.mode,
            max_words=current.max_words,
            max_duration_ms=current.max_duration_ms,
            reason=current.reason,
            cooldown_after_ms=current.cooldown_after_ms,
            confidence=current.confidence,
            defer_until_ms=current.defer_until_ms,
            final_authority=True,
        )
        steps.append(PolicyStep(
            policy="final_authority",
            changed=current != before_final_permit,
            before=_permit_payload(before_final_permit),
            after=_permit_payload(current),
            note="single_public_speech_authority",
        ))

        if not current.allowed:
            blockers.append(str(current.reason or "policy_denied"))
        blockers = list(dict.fromkeys(item for item in blockers if item))
        conflicts = list(dict.fromkeys(item for item in conflicts if item))

        kind = str(getattr(opportunity, "kind", "") or "")
        urgency = float(getattr(opportunity, "urgency", 0.0) or 0.0)
        emergency_override = bool(kind == "new_error" and urgency >= 0.88 and current.allowed)
        reason = (
            f"final={current.mode};allowed={str(bool(current.allowed)).lower()};"
            f"steps={len(steps)};blockers={','.join(blockers) or 'none'};"
            f"conflicts={','.join(conflicts) or 'none'}"
        )
        return AutonomousPolicyDecision(
            version=AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
            permit=current,
            steps=tuple(steps),
            blockers=tuple(blockers),
            conflict_flags=tuple(conflicts),
            emergency_override=emergency_override,
            reason=reason,
        )

    @staticmethod
    def _apply_runtime_authority(
        *,
        current: SpeakPermit,
        opportunity: AutonomousOpportunity | None,
        runtime_policy: Mapping[str, Any] | None,
        now_ms: int,
        steps: list[PolicyStep],
    ) -> SpeakPermit:
        before = current
        blocked_until_ms = int(_get(runtime_policy, "presence_blocked_until_ms", 0) or 0)
        user_typing = bool(_get(runtime_policy, "user_typing", False))
        hard_cancel = str(_get(runtime_policy, "hard_cancel_reason", "") or "")
        emergency = bool(
            opportunity is not None
            and opportunity.kind == "new_error"
            and float(opportunity.urgency or 0.0) >= 0.92
        )
        after = before
        note = "runtime_clear"
        if hard_cancel:
            after = SpeakPermit(False, "suppress", 0, 0, hard_cancel, 0, 1.0, None, False)
            note = hard_cancel
        elif user_typing and not emergency:
            after = SpeakPermit(False, "body_only", 0, 0, "user_is_typing", 0, 0.98, None, False)
            note = "user_is_typing"
        elif blocked_until_ms > now_ms and not emergency:
            after = SpeakPermit(
                False, "body_only", 0, 0, "post_chat_grace_pending", 0, 0.98,
                blocked_until_ms, False,
            )
            note = f"defer_until={blocked_until_ms}"
        steps.append(PolicyStep(
            policy="runtime_authority",
            changed=after != before,
            before=_permit_payload(before),
            after=_permit_payload(after),
            note=note,
        ))
        return after

    @staticmethod
    def _apply_policy(
        *, policy: str, current: SpeakPermit, applier: Any,
        args: tuple[Any, ...], kwargs: dict[str, Any],
        steps: list[PolicyStep], conflicts: list[str],
    ) -> SpeakPermit:
        before = current
        if not callable(applier) or not args or args[0] is None:
            steps.append(PolicyStep(policy, False, _permit_payload(before), _permit_payload(before), "policy_unavailable"))
            return before
        try:
            after = applier(before, *args, **kwargs)
        except Exception as exc:
            conflicts.append(f"{policy}_error:{type(exc).__name__}")
            steps.append(PolicyStep(policy, False, _permit_payload(before), _permit_payload(before), f"error:{type(exc).__name__}"))
            return before
        if not isinstance(after, SpeakPermit):
            conflicts.append(f"{policy}_returned_invalid_permit")
            after = before
        if not before.allowed and after.allowed:
            conflicts.append(f"{policy}_attempted_to_reopen_denied_permit")
            after = before
        steps.append(PolicyStep(policy, after != before, _permit_payload(before), _permit_payload(after), str(after.reason or "")))
        return after

    @staticmethod
    def _final_clamp(
        *, current: SpeakPermit, original: SpeakPermit, stage_preset: Any,
        session_directive: Any, audience_directive: Any,
        steps: list[PolicyStep], conflicts: list[str],
    ) -> SpeakPermit:
        if not current.allowed:
            return current
        word_caps = [max(1, int(original.max_words or 1))]
        duration_caps = [max(500, int(original.max_duration_ms or 500))]
        for obj, field, target in (
            (stage_preset, "max_words", word_caps),
            (session_directive, "max_words_cap", word_caps),
            (audience_directive, "max_words_cap", word_caps),
            (stage_preset, "max_duration_ms", duration_caps),
        ):
            try:
                value = int(getattr(obj, field, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                target.append(value)
        before = current
        words = max(1, min([int(current.max_words or 1), *word_caps]))
        duration = max(500, min([int(current.max_duration_ms or 500), *duration_caps]))
        cooldown = max(int(original.cooldown_after_ms or 0), int(current.cooldown_after_ms or 0))
        after = SpeakPermit(
            True, current.mode, words, duration, current.reason, cooldown,
            current.confidence, current.defer_until_ms, False,
        )
        steps.append(PolicyStep(
            "final_budget_clamp", after != before,
            _permit_payload(before), _permit_payload(after),
            "monotonic_budget_and_cooldown",
        ))
        return after


__all__ = ["AutonomousPolicyDecision", "AutonomousPolicyResolver", "PolicyStep"]
