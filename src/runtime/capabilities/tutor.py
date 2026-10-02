# -*- coding: utf-8 -*-
"""TutorCapability V12.

TutorExecutive vẫn giữ intelligence sư phạm/mastery/evidence, nhưng adapter này
chỉ trả *advice/evidence* cho RootAgent. Nó không có API phát public text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime.conversation.contracts import DeliveryReceipt


@dataclass(frozen=True, slots=True)
class TutorAdvice:
    active: bool = False
    assessment: Mapping[str, Any] | None = None
    teaching_move: Mapping[str, Any] | None = None
    expects_learner_response: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "assessment": dict(self.assessment or {}),
            "teaching_move": dict(self.teaching_move or {}),
            "expects_learner_response": self.expects_learner_response,
        }


class TutorCapability:
    def __init__(self, executive: Any | None, *, logger: Any = None) -> None:
        self.executive = executive
        self.logger = logger
        self._last_decision = None

    def advise(self, *, user_text: str, turn_id: str,
               recent_history: Sequence[Mapping[str, Any]] = (),
               response_to_previous: bool = False) -> TutorAdvice:
        if self.executive is None:
            return TutorAdvice()
        assessment = None
        try:
            if response_to_previous:
                assessment_obj = self.executive.observe_response(
                    user_text, turn_id=turn_id, recent_history=recent_history
                )
                assessment = assessment_obj.to_dict() if assessment_obj is not None else None
            decision = self.executive.plan_next_move(
                user_text, turn_id=turn_id, recent_history=recent_history
            )
            self._last_decision = decision
            if decision is None:
                return TutorAdvice(active=bool(assessment), assessment=assessment)
            writer_context = decision.to_writer_context()
            move = writer_context.get("move") if isinstance(writer_context, Mapping) else None
            constraints = writer_context.get("delivery_constraints") if isinstance(writer_context, Mapping) else None
            expects = bool(constraints.get("requires_user_response")) if isinstance(constraints, Mapping) else False
            return TutorAdvice(
                active=True,
                assessment=assessment,
                teaching_move=dict(move or {}) if isinstance(move, Mapping) else {},
                expects_learner_response=expects,
            )
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[tutor-capability-v12] degraded: %s", exc)
            return TutorAdvice(active=bool(assessment), assessment=assessment)

    def observe_delivery_receipt(self, receipt: DeliveryReceipt) -> None:
        if self.executive is None or self._last_decision is None:
            return
        try:
            self.executive.commit_delivery(
                self._last_decision, successful=bool(receipt.successful)
            )
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[tutor-capability-v12] receipt degraded: %s", exc)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["TutorAdvice", "TutorCapability"]
