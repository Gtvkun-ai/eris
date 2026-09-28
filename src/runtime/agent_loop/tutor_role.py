# -*- coding: utf-8 -*-
"""Adapter để TutorExecutive trở thành *role* bên trong TurnAgentLoop.

Mục tiêu kiến trúc:
- TurnAgentLoop là root loop duy nhất của foreground chat.
- TutorExecutive không tự public text và không tự tạo một vòng hội thoại riêng.
- Tutor chỉ đóng góp: assessment (nếu user đang trả lời bài trước) + TeachingMove kế tiếp.
- ConversationDirector vẫn có quyền quyết turn hiện tại nói bao nhiêu rồi dừng.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import ResponseRelation, TurnDecision


@dataclass(frozen=True, slots=True)
class TutorRoleContribution:
    """Projection bounded cho root agent loop/writer; không lộ hypothesis thô."""

    active: bool = False
    response_relation: str = "none"
    assessment: Mapping[str, Any] | None = None
    directive: Mapping[str, Any] | None = None
    waiting_for_user: bool = False
    changed_this_iteration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "response_relation": self.response_relation,
            "assessment": dict(self.assessment or {}),
            "directive": dict(self.directive or {}),
            "waiting_for_user": self.waiting_for_user,
        }


class TutorRoleCoordinator:
    """Điều phối bridge giữa generic agent loop và TutorExecutive.

    Một tutor decision chỉ được tạo tối đa một lần cho mỗi user turn. Điều này
    tránh bug agent loop có 3 iteration -> TutorExecutive vô tình tăng turn_count
    3 lần hoặc tạo 3 TeachingMove cho cùng một câu user.
    """

    def __init__(self, executive: Any | None, *, logger: Any = None) -> None:
        self.executive = executive
        self.logger = logger
        self._turn_id = ""
        self._assessment_done = False
        self._planned = False
        self._last_decision = None
        self._pending_previous = False
        self._last_contribution = TutorRoleContribution()

    def begin_turn(
        self,
        *,
        turn_id: str,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
    ) -> TutorRoleContribution:
        self._turn_id = str(turn_id or "")
        self._assessment_done = False
        self._planned = False
        self._last_decision = None
        self._pending_previous = False

        if self.executive is None:
            self._last_contribution = TutorRoleContribution()
            return self._last_contribution

        snapshot = self._safe_snapshot()
        state = snapshot.get("state", {}) if isinstance(snapshot, Mapping) else {}
        learning = snapshot.get("learning", {}) if isinstance(snapshot, Mapping) else {}
        active_path = learning.get("active_path_id") if isinstance(learning, Mapping) else None
        last_move = state.get("last_move") if isinstance(state, Mapping) else None
        pending = bool(isinstance(last_move, Mapping) and last_move.get("requires_user_response"))
        self._pending_previous = pending
        active = bool(active_path or pending)

        # Nếu không có pending question, tutor có thể lập move ngay để root agent
        # nhìn thấy pedagogical contract từ iteration đầu tiên.
        directive = None
        if pending and isinstance(last_move, Mapping):
            # Root semantic executive cần biết *move nào* đang chờ response để
            # phân biệt answer / clarification / interrupt. Đây chỉ là projection
            # semantic của move trước, không phải một lệnh dạy mới.
            directive = {
                "schema": "eris.tutor.pending_move.v1",
                "move": dict(last_move),
                "delivered_text": str(state.get("last_delivery_text", "") or "")[:1600],
                "delivery_constraints": {
                    "requires_user_response": True,
                    "max_sentences": int(last_move.get("max_sentences", 1) or 1),
                },
                "pending_previous_move": True,
            }
        elif active:
            directive = self._plan_once(
                user_text=user_text,
                turn_id=turn_id,
                recent_history=recent_history,
            )

        self._last_contribution = TutorRoleContribution(
            active=active,
            response_relation="none",
            assessment=None,
            directive=directive,
            waiting_for_user=bool(_requires_response(directive)),
            changed_this_iteration=bool(directive),
        )
        return self._last_contribution

    def apply_root_decision(
        self,
        decision: TurnDecision,
        *,
        user_text: str,
        turn_id: str,
        recent_history: Sequence[Mapping[str, Any]],
    ) -> TutorRoleContribution:
        """Cho root executive quyền phân loại user response trước khi tutor chấm."""
        if self.executive is None:
            return TutorRoleContribution()

        relation = decision.tutor_response_relation
        previous = self._last_contribution
        assessment_payload = previous.assessment
        directive = previous.directive
        changed = False

        if relation == ResponseRelation.ANSWER and not self._assessment_done:
            self._assessment_done = True
            try:
                assessment = self.executive.observe_response(
                    user_text,
                    turn_id=turn_id,
                    recent_history=recent_history,
                )
                assessment_payload = assessment.to_dict() if assessment is not None else None
                changed = assessment is not None
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[agent-tutor-role] assessment degraded: %s", exc)

            # Sau khi assessment xong mới được xin teaching move tiếp theo.
            self._pending_previous = False
            self._planned = False
            directive = self._plan_once(
                user_text=user_text,
                turn_id=turn_id,
                recent_history=recent_history,
            )
            changed = bool(directive) or changed

        elif relation == ResponseRelation.INTERRUPT:
            # User đổi chủ đề: không chấm và không tự kéo lesson trở lại. Quan trọng
            # hơn, clear pending move ở TutorExecutive để turn *sau* cũng không chấm
            # nhầm câu mới theo câu hỏi cũ. Đây là yield thật, không chỉ local flag.
            self._pending_previous = False
            directive = None
            changed = previous.directive is not None
            suspend = getattr(self.executive, "suspend_pending_move", None)
            if callable(suspend):
                try:
                    suspend(reason="user_interrupt")
                except Exception as exc:  # noqa: BLE001
                    self._log("debug", "[agent-tutor-role] suspend pending degraded: %s", exc)

        elif relation == ResponseRelation.CLARIFICATION:
            # User đang hỏi lại chính câu tutor. Giữ previous move làm context, nhưng
            # không biến clarification thành learning evidence và không advance KP.
            directive = previous.directive

        elif relation == ResponseRelation.NONE and not self._planned and not self._pending_previous:
            # Learning path có thể vừa active trong cùng turn bởi runtime khác.
            directive = self._plan_once(
                user_text=user_text,
                turn_id=turn_id,
                recent_history=recent_history,
            )
            changed = bool(directive)

        contribution = TutorRoleContribution(
            active=bool(previous.active or directive or assessment_payload),
            response_relation=relation.value,
            assessment=assessment_payload,
            directive=directive,
            waiting_for_user=bool(_requires_response(directive)),
            changed_this_iteration=changed,
        )
        self._last_contribution = contribution
        return contribution

    def commit_public_delivery(self, *, successful: bool, public_text: str = "") -> None:
        """Receipt boundary: chỉ public text thật sự thành công mới note_taught/advance."""
        if self.executive is None or self._last_decision is None:
            return
        try:
            self.executive.commit_delivery(
                self._last_decision,
                successful=successful,
                public_text=public_text,
            )
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[agent-tutor-role] delivery commit degraded: %s", exc)

    def _plan_once(
        self,
        *,
        user_text: str,
        turn_id: str,
        recent_history: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        if self._planned or self.executive is None:
            return self._last_decision.to_writer_context() if self._last_decision is not None else None
        self._planned = True
        try:
            decision = self.executive.plan_next_move(
                user_text,
                turn_id=turn_id,
                recent_history=recent_history,
            )
            self._last_decision = decision
            return decision.to_writer_context() if decision is not None else None
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[agent-tutor-role] planning degraded: %s", exc)
            return None

    def _safe_snapshot(self) -> Mapping[str, Any]:
        try:
            raw = self.executive.snapshot()
            return raw if isinstance(raw, Mapping) else {}
        except Exception:
            return {}

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


def _requires_response(directive: Mapping[str, Any] | None) -> bool:
    if not isinstance(directive, Mapping):
        return False
    constraints = directive.get("delivery_constraints")
    if isinstance(constraints, Mapping):
        return bool(constraints.get("requires_user_response"))
    move = directive.get("move")
    return bool(move.get("requires_user_response")) if isinstance(move, Mapping) else False


__all__ = ["TutorRoleContribution", "TutorRoleCoordinator"]
