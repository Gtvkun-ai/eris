# -*- coding: utf-8 -*-
"""Typed contracts cho root foreground AgentLoop của Eris.

V11 giữ core nhỏ và thêm đúng một projection turn-taking do agent sở hữu:

1. ``CognitivePlan``      — agent cần hiểu gì.
2. ``ExecutionPlan``      — agent còn phải làm gì.
3. ``ConversationSpeechPlan`` — agent muốn cuộc nói chuyện đi đâu tiếp.
4. ``DiscoursePlan.public_beats`` — những ý agent đã quyết định nói *ngay lượt này*.
5. ``TurnProjection`` — agent muốn giữ/nhường/open floor ra sao ở ranh giới lượt nói.

Runtime không sở hữu pacing semantic, không chọn beat, không rút gọn lời writer và
không lưu một ``DisclosureArc`` thứ hai. Những API V6–V9 chỉ được hỗ trợ ở rìa
parser khi cần đọc payload cũ; chúng không còn là state authority của hot path.

Các object ở đây là planning artifact public-safe, không lưu chain-of-thought.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence


def _clean(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _tuple_text(
    values: Sequence[Any] | None,
    *,
    limit: int = 8,
    item_limit: int = 500,
) -> tuple[str, ...]:
    out: list[str] = []
    for item in values or ():
        text = _clean(item, item_limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


class TurnAction(str, Enum):
    """Hành động nhận thức tiếp theo của root agent."""

    ANALYZE = "analyze"
    DECOMPOSE = "decompose"
    VERIFY = "verify"
    COMPOSE = "compose"
    WAIT_USER = "wait_user"
    COMPLETE = "complete"


class BeatKind(str, Enum):
    """Vai trò giao tiếp của một ý public, không phải heading bắt buộc."""

    FRAME = "frame"
    FINDING = "finding"
    EXPLANATION = "explanation"
    CONTRAST = "contrast"
    EXAMPLE = "example"
    CORRECTION = "correction"
    UNCERTAINTY = "uncertainty"
    DECISION = "decision"
    SYNTHESIS = "synthesis"
    QUESTION = "question"
    HANDOFF = "handoff"


class SpeechContinuationMode(str, Enum):
    """Sau khi phát xong lời hiện tại, lifecycle tiếp theo là gì.

    ``NONE``
        Không có lời hứa continuation nào.
    ``YIELD_USER``
        Agent chủ động nhường floor. Runtime chỉ giữ SpeechPlan và chờ user.
    ``AUTO_CONTINUE``
        Agent muốn được đánh thức lại sau audio/pause. Runtime chỉ *wake agent*;
        tuyệt đối không phát thread/text cache thay agent.
    """

    NONE = "none"
    YIELD_USER = "yield_user"
    AUTO_CONTINUE = "auto_continue"


class TurnFloor(str, Enum):
    """Cách root agent muốn quản lý lượt nói *sau câu hiện tại*.

    ``HOLD``
        Eris muốn người dùng cảm nhận rằng mình chưa nói xong và có khả năng
        sẽ nói tiếp ngay sau một nhịp. Runtime chỉ biểu diễn tín hiệu này bằng
        body/UI; runtime không tự tạo câu tiếp theo.
    ``YIELD``
        Eris chủ động nhường lượt cho user.
    ``OPEN``
        Eris không giữ cũng không ép nhường floor; user có thể chen vào tự nhiên.
    """

    HOLD = "hold"
    YIELD = "yield"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class TurnProjection:
    """Projection public-safe do **root AgentLoop** tự chọn cho turn-taking.

    Đây không phải speech plan dài hạn và cũng không phải lời thoại. Nó chỉ cho
    body/UI biết agent muốn *trông như thế nào* ở ranh giới lượt nói.

    ``continuation_feel`` là tín hiệu trình diễn nhẹ cho avatar (thinking/eager/
    soft/playful/neutral). Runtime được phép map tín hiệu này sang pose Live2D,
    nhưng không được suy ra nội dung hay tự quyết continuation.

    ``verbal_bridge_hint`` chỉ là gợi ý cho writer về nhịp kết câu. Writer có thể
    hiện thực tự nhiên nếu phù hợp với public_beats; runtime tuyệt đối không chèn
    câu, dấu ba chấm hay filler thay writer.
    """

    floor: TurnFloor = TurnFloor.OPEN
    continuation_feel: str = "neutral"
    verbal_bridge_hint: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "TurnProjection":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            floor = TurnFloor(str(data.get("floor", "open") or "open").strip().lower())
        except ValueError:
            floor = TurnFloor.OPEN
        feel = _clean(data.get("continuation_feel"), 40).lower() or "neutral"
        if feel not in {"neutral", "thinking", "eager", "soft", "playful"}:
            feel = "neutral"
        return cls(
            floor=floor,
            continuation_feel=feel,
            verbal_bridge_hint=_clean(data.get("verbal_bridge_hint"), 320),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "floor": self.floor.value,
            "continuation_feel": self.continuation_feel,
            "verbal_bridge_hint": self.verbal_bridge_hint,
        }


class ResponseRelation(str, Enum):
    """Quan hệ user turn với pending tutor interaction trước đó."""

    NONE = "none"
    ANSWER = "answer"
    CLARIFICATION = "clarification"
    INTERRUPT = "interrupt"


@dataclass(frozen=True, slots=True)
class DialogueBeat:
    """Một ý mà root agent đã quyết định public ở *lượt hiện tại*.

    V10 không còn ``say_now``. Nếu một ý chưa nên nói thì nó không thuộc
    ``DiscoursePlan.public_beats``; agent ghi hướng đó vào ``planned_threads`` của
    ``ConversationSpeechPlan``. Nhờ vậy không còn trạng thái nửa-public nửa-held.
    """

    kind: BeatKind = BeatKind.EXPLANATION
    proposition: str = ""
    communicative_goal: str = ""
    relation_to_previous: str = "continue"
    detail_level: str = "normal"
    needs_example: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "DialogueBeat":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            kind = BeatKind(str(data.get("kind", "explanation") or "explanation").strip().lower())
        except ValueError:
            kind = BeatKind.EXPLANATION
        return cls(
            kind=kind,
            proposition=_clean(data.get("proposition"), 900),
            communicative_goal=_clean(data.get("communicative_goal"), 500),
            relation_to_previous=_clean(data.get("relation_to_previous"), 80) or "continue",
            detail_level=_clean(data.get("detail_level"), 40) or "normal",
            needs_example=bool(data.get("needs_example", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "proposition": self.proposition,
            "communicative_goal": self.communicative_goal,
            "relation_to_previous": self.relation_to_previous,
            "detail_level": self.detail_level,
            "needs_example": self.needs_example,
        }


@dataclass(frozen=True, slots=True)
class CognitivePlan:
    """Những gì Eris cần hiểu/giữ để xử lý turn hiện tại."""

    situation_summary: str = ""
    objective: str = ""
    task_shape: str = "conversation"
    active_roles: tuple[str, ...] = ()
    work_items: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "situation_summary": self.situation_summary,
            "objective": self.objective,
            "task_shape": self.task_shape,
            "active_roles": list(self.active_roles),
            "work_items": list(self.work_items),
            "uncertainties": list(self.uncertainties),
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Checklist công việc trước khi agent được coi là hoàn thành turn."""

    completed_items: tuple[str, ...] = ()
    remaining_items: tuple[str, ...] = ()
    external_action_needed: bool = False
    external_action_status: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_items": list(self.completed_items),
            "remaining_items": list(self.remaining_items),
            "external_action_needed": self.external_action_needed,
            "external_action_status": self.external_action_status,
        }


@dataclass(frozen=True, slots=True)
class ConversationSpeechPlan:
    """Kế hoạch hội thoại dài hạn do **root AgentLoop** tự lập.

    Đây không phải script và không phải quota lời nói. ``desired_shape`` có thể là
    "một câu ngắn rồi nhường user", nhưng cũng có thể là "một nerd burst dài,
    nối tự nhiên nhiều liên hệ". Runtime không diễn giải field này thành word cap,
    seconds cap hay số beat.

    ``planned_threads`` là hướng agent còn muốn giữ trong đầu. Runtime chỉ persist
    và đưa nguyên snapshot về agent ở turn/wake sau; runtime không chọn thread để
    nói và không biến ``next_intent`` thành public text.
    """

    plan_id: str = ""
    topic: str = ""
    conversation_goal: str = ""
    current_thread: str = ""
    discussed: tuple[str, ...] = ()
    planned_threads: tuple[str, ...] = ()
    next_intent: str = ""
    desired_shape: str = ""
    continuation_mode: SpeechContinuationMode = SpeechContinuationMode.NONE
    resume_trigger: str = ""
    pause_seconds: float = 0.0

    @property
    def owns_future_turn(self) -> bool:
        return self.continuation_mode in {
            SpeechContinuationMode.YIELD_USER,
            SpeechContinuationMode.AUTO_CONTINUE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "topic": self.topic,
            "conversation_goal": self.conversation_goal,
            "current_thread": self.current_thread,
            "discussed": list(self.discussed),
            "planned_threads": list(self.planned_threads),
            "next_intent": self.next_intent,
            "desired_shape": self.desired_shape,
            "continuation_mode": self.continuation_mode.value,
            "resume_trigger": self.resume_trigger,
            "pause_seconds": round(max(0.0, float(self.pause_seconds)), 3),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ConversationSpeechPlan":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            mode = SpeechContinuationMode(
                str(data.get("continuation_mode", "none") or "none").strip().lower()
            )
        except ValueError:
            mode = SpeechContinuationMode.NONE
        try:
            pause = max(0.0, float(data.get("pause_seconds", 0.0) or 0.0))
        except (TypeError, ValueError):
            pause = 0.0

        # Adapter đọc payload V7/V9: floor_intent không còn là state authority.
        # Nếu payload cũ nói yield/probe nhưng quên continuation_mode, ta chỉ migrate
        # lifecycle sang YIELD_USER; không mang enum legacy vào core V10.
        legacy_floor = str(data.get("floor_intent", "") or "").strip().lower()
        resume_trigger = _clean(data.get("resume_trigger"), 120)
        if mode == SpeechContinuationMode.NONE and legacy_floor in {"yield", "probe"}:
            mode = SpeechContinuationMode.YIELD_USER
            resume_trigger = resume_trigger or "user_reply"

        return cls(
            plan_id=_clean(data.get("plan_id"), 180),
            topic=_clean(data.get("topic"), 500),
            conversation_goal=_clean(data.get("conversation_goal"), 700),
            current_thread=_clean(data.get("current_thread"), 420),
            discussed=_tuple_text(
                data.get("discussed") if isinstance(data.get("discussed"), Sequence) else (),
                limit=16,
                item_limit=360,
            ),
            planned_threads=_tuple_text(
                data.get("planned_threads") if isinstance(data.get("planned_threads"), Sequence) else (),
                limit=16,
                item_limit=420,
            ),
            next_intent=_clean(data.get("next_intent"), 700),
            desired_shape=_clean(data.get("desired_shape"), 900),
            continuation_mode=mode,
            resume_trigger=resume_trigger,
            pause_seconds=pause,
        )


@dataclass(frozen=True, slots=True)
class DiscoursePlan:
    """Những semantic beat **được nói ngay turn này**.

    Không có held beat, disclosure mode hay speech budget trong core. Agent muốn
    giữ một hướng cho tương lai thì ghi vào ``ConversationSpeechPlan``.
    """

    public_beats: tuple[DialogueBeat, ...] = ()
    style_notes: tuple[str, ...] = ()
    user_response_required: bool = False

    @property
    def beats(self) -> tuple[DialogueBeat, ...]:
        """Read-only compatibility alias cho consumer V9 chưa đổi tên field."""
        return self.public_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_beats": [beat.to_dict() for beat in self.public_beats],
            "style_notes": list(self.style_notes),
            "user_response_required": self.user_response_required,
        }


@dataclass(frozen=True, slots=True)
class LoopBudget:
    """Ngân sách *reasoning loop*, không phải ngân sách lời nói."""

    soft_iterations: int = 2
    hard_iterations: int = 5
    stall_limit: int = 2
    max_wall_seconds: float = 12.0

    def normalized(self) -> "LoopBudget":
        soft = max(1, min(6, int(self.soft_iterations)))
        hard = max(soft, min(10, int(self.hard_iterations)))
        return replace(
            self,
            soft_iterations=soft,
            hard_iterations=hard,
            stall_limit=max(1, min(4, int(self.stall_limit))),
            max_wall_seconds=max(3.0, min(30.0, float(self.max_wall_seconds))),
        )


@dataclass(frozen=True, slots=True)
class TurnDecision:
    """Typed kết luận của một iteration; không chứa chain-of-thought."""

    action: TurnAction = TurnAction.COMPLETE
    cognitive: CognitivePlan = field(default_factory=CognitivePlan)
    discourse: DiscoursePlan = field(default_factory=DiscoursePlan)
    speech_plan: ConversationSpeechPlan = field(default_factory=ConversationSpeechPlan)
    turn_projection: TurnProjection = field(default_factory=TurnProjection)
    completed_items: tuple[str, ...] = ()
    remaining_items: tuple[str, ...] = ()
    progress: float = 0.0
    uncertainty: float = 0.0
    completion_candidate: bool = False
    requires_user_response: bool = False
    tutor_response_relation: ResponseRelation = ResponseRelation.NONE
    decision_summary: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "TurnDecision":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            action = TurnAction(str(data.get("next_action", "complete") or "complete").strip().lower())
        except ValueError:
            action = TurnAction.COMPLETE

        roles = _tuple_text(data.get("active_roles") if isinstance(data.get("active_roles"), Sequence) else ())
        work_items = _tuple_text(data.get("work_items") if isinstance(data.get("work_items"), Sequence) else ())
        uncertainties = _tuple_text(
            data.get("uncertainties") if isinstance(data.get("uncertainties"), Sequence) else (),
            limit=6,
        )

        # V10 schema dùng public_beats. Khi đọc payload V7–V9, chỉ migrate những
        # dialogue_beat có say_now != false. Đây là adapter input, không phải runtime
        # policy và không tạo thêm held-state trong core.
        beats_raw = data.get("public_beats")
        if not isinstance(beats_raw, Sequence):
            legacy = data.get("dialogue_beats")
            if isinstance(legacy, Sequence):
                beats_raw = [
                    item for item in legacy
                    if isinstance(item, Mapping) and bool(item.get("say_now", True))
                ]
            else:
                beats_raw = ()
        public_beats = tuple(
            beat
            for beat in (
                DialogueBeat.from_mapping(item)
                for item in beats_raw
                if isinstance(item, Mapping)
            )
            if beat.proposition
        )[:24]

        cognitive = CognitivePlan(
            situation_summary=_clean(data.get("situation_summary"), 1200),
            objective=_clean(data.get("objective"), 800),
            task_shape=_clean(data.get("task_shape"), 80) or "conversation",
            active_roles=roles,
            work_items=work_items,
            uncertainties=uncertainties,
        )
        discourse = DiscoursePlan(
            public_beats=public_beats,
            style_notes=_tuple_text(
                data.get("style_notes") if isinstance(data.get("style_notes"), Sequence) else (),
                limit=8,
                item_limit=240,
            ),
            user_response_required=bool(data.get("requires_user_response", False)),
        )

        speech_plan = ConversationSpeechPlan.from_mapping(
            data.get("speech_plan") if isinstance(data.get("speech_plan"), Mapping) else None
        )
        # Migrate continuation legacy nếu speech_plan mới chưa mang thông tin tương lai.
        continuation = data.get("continuation") if isinstance(data.get("continuation"), Mapping) else {}
        if continuation and not speech_plan.planned_threads and not speech_plan.next_intent:
            speech_plan = replace(
                speech_plan,
                current_thread=speech_plan.current_thread or _clean(continuation.get("active_thread"), 420),
                planned_threads=_tuple_text(
                    continuation.get("deferred_threads")
                    if isinstance(continuation.get("deferred_threads"), Sequence)
                    else (),
                    limit=16,
                    item_limit=420,
                ),
                next_intent=_clean(continuation.get("next_if_continue"), 700),
            )

        raw_projection = data.get("turn_projection") if isinstance(data.get("turn_projection"), Mapping) else None
        turn_projection = TurnProjection.from_mapping(raw_projection)
        # Migration input-only: payload V10 trở về trước chưa có TurnProjection.
        # Nếu turn đã tuyên bố cần user response/yield lifecycle, map sang YIELD
        # một lần ở parser để core V11 không phải giữ heuristic compatibility.
        if raw_projection is None and (
            bool(data.get("requires_user_response", False))
            or speech_plan.continuation_mode == SpeechContinuationMode.YIELD_USER
        ):
            turn_projection = TurnProjection(floor=TurnFloor.YIELD)

        try:
            progress = min(1.0, max(0.0, float(data.get("progress", 0.0) or 0.0)))
        except (TypeError, ValueError):
            progress = 0.0
        try:
            uncertainty = min(1.0, max(0.0, float(data.get("uncertainty", 0.0) or 0.0)))
        except (TypeError, ValueError):
            uncertainty = 0.0
        try:
            tutor_relation = ResponseRelation(
                str(data.get("tutor_response_relation", "none") or "none").strip().lower()
            )
        except ValueError:
            tutor_relation = ResponseRelation.NONE

        return cls(
            action=action,
            cognitive=cognitive,
            discourse=discourse,
            speech_plan=speech_plan,
            turn_projection=turn_projection,
            completed_items=_tuple_text(
                data.get("completed_items") if isinstance(data.get("completed_items"), Sequence) else ()
            ),
            remaining_items=_tuple_text(
                data.get("remaining_items") if isinstance(data.get("remaining_items"), Sequence) else ()
            ),
            progress=progress,
            uncertainty=uncertainty,
            completion_candidate=bool(data.get("completion_candidate", False)),
            requires_user_response=bool(data.get("requires_user_response", False)),
            tutor_response_relation=tutor_relation,
            decision_summary=_clean(data.get("decision_summary"), 500),
        )


@dataclass(frozen=True, slots=True)
class AgentTurnState:
    turn_id: str
    user_text: str
    session_id: str = "default"
    iteration: int = 0
    cognitive: CognitivePlan = field(default_factory=CognitivePlan)
    execution: ExecutionPlan = field(default_factory=ExecutionPlan)
    discourse: DiscoursePlan = field(default_factory=DiscoursePlan)
    speech_plan: ConversationSpeechPlan = field(default_factory=ConversationSpeechPlan)
    turn_projection: TurnProjection = field(default_factory=TurnProjection)
    progress: float = 0.0
    uncertainty: float = 1.0
    stall_count: int = 0
    status: str = "running"
    decision_summaries: tuple[str, ...] = ()

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "iteration": self.iteration,
            "cognitive_plan": self.cognitive.to_dict(),
            "execution_plan": self.execution.to_dict(),
            "discourse_plan": self.discourse.to_dict(),
            "conversation_speech_plan": self.speech_plan.to_dict(),
            "turn_projection": self.turn_projection.to_dict(),
            "progress": round(self.progress, 3),
            "uncertainty": round(self.uncertainty, 3),
            "stall_count": self.stall_count,
            "status": self.status,
            "recent_decision_summaries": list(self.decision_summaries[-3:]),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "eris.agent_turn.v11", **self.to_model_dict()}


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    state: AgentTurnState
    completion_reason: str = ""
    model_iterations: int = 0
    degraded: bool = False

    @property
    def should_wait_user(self) -> bool:
        return self.state.status == "waiting_user"

    @property
    def reserves_user_floor(self) -> bool:
        """True chỉ khi chính agent/tutor đã nhường floor cho user."""
        return bool(
            self.state.discourse.user_response_required
            or self.state.speech_plan.continuation_mode == SpeechContinuationMode.YIELD_USER
        )

    @property
    def owns_continuation(self) -> bool:
        return self.state.speech_plan.owns_future_turn

    @property
    def holds_floor(self) -> bool:
        return self.state.turn_projection.floor == TurnFloor.HOLD

    @property
    def yields_floor(self) -> bool:
        return self.state.turn_projection.floor == TurnFloor.YIELD

    def to_dict(self) -> dict[str, Any]:
        payload = self.state.to_dict()
        payload.update(
            {
                "completion_reason": self.completion_reason,
                "model_iterations": self.model_iterations,
                "degraded": self.degraded,
            }
        )
        return payload


__all__ = [
    "AgentTurnResult",
    "AgentTurnState",
    "BeatKind",
    "CognitivePlan",
    "ConversationSpeechPlan",
    "DialogueBeat",
    "DiscoursePlan",
    "ExecutionPlan",
    "LoopBudget",
    "ResponseRelation",
    "SpeechContinuationMode",
    "TurnFloor",
    "TurnProjection",
    "TurnAction",
    "TurnDecision",
]
