# -*- coding: utf-8 -*-
"""Typed contracts cho foreground agent loop của ERIS.

Mục tiêu của package này không phải lưu chain-of-thought. Runtime chỉ giữ những
kết luận vận hành có thể audit: ERIS đang cố đạt mục tiêu gì, còn thiếu phần nào,
vai trò nào đang hoạt động, và public response nên được chia thành những nhịp
(DialogueBeat) nào.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence


def _clean(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _tuple_text(values: Sequence[Any] | None, *, limit: int = 8, item_limit: int = 500) -> tuple[str, ...]:
    out: list[str] = []
    for item in values or ():
        text = _clean(item, item_limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


class TurnAction(str, Enum):
    """Hành động nhận thức tiếp theo, không phải raw model reasoning."""

    ANALYZE = "analyze"
    DECOMPOSE = "decompose"
    VERIFY = "verify"
    COMPOSE = "compose"
    WAIT_USER = "wait_user"
    COMPLETE = "complete"


class BeatKind(str, Enum):
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


class DisclosureMode(str, Enum):
    """Nhịp tiết lộ thông tin ra public surface.

    CONVERSATIONAL: nói ít, giữ phần còn lại cho lượt sau.
    DEEP_DIALOGUE: nói vài nhịp liên quan rồi dừng ở breakpoint tự nhiên.
    REPORT: user thật sự yêu cầu một câu trả lời gần như đầy đủ trong một turn.
    """

    CONVERSATIONAL = "conversational"
    DEEP_DIALOGUE = "deep_dialogue"
    REPORT = "report"


class SpeechContinuationMode(str, Enum):
    """Agent quyết định vòng nói sẽ tiếp tục thế nào sau khi audio kết thúc.

    NONE:
        Không có continuation đã cam kết. Turn kết thúc bình thường.
    YIELD_USER:
        Agent chủ động nhường lượt cho user. Runtime chỉ giữ plan để turn sau
        agent đọc lại; runtime KHÔNG tự phát tiếp.
    AUTO_CONTINUE:
        Agent chủ động muốn tiếp tục sau một nhịp nghỉ. Runtime chỉ đặt wake-up
        cơ học rồi gọi LẠI TurnAgentLoop; không được phát câu đã cache.
    """

    NONE = "none"
    YIELD_USER = "yield_user"
    AUTO_CONTINUE = "auto_continue"


class ResponseRelation(str, Enum):
    """Quan hệ của user turn hiện tại với câu hỏi tutor trước đó.

    Giá trị này do semantic executive đề xuất. Runtime dùng nó để quyết có được
    chấm câu user như learning evidence hay phải coi đó là clarification/interrupt.
    """

    NONE = "none"
    ANSWER = "answer"
    CLARIFICATION = "clarification"
    INTERRUPT = "interrupt"


@dataclass(frozen=True, slots=True)
class DialogueBeat:
    """Một nhịp giao tiếp có mục đích, không đồng nghĩa một heading/paragraph."""

    kind: BeatKind = BeatKind.EXPLANATION
    proposition: str = ""
    communicative_goal: str = ""
    relation_to_previous: str = "continue"
    detail_level: str = "normal"
    needs_example: bool = False
    say_now: bool = True

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
            say_now=bool(data.get("say_now", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "proposition": self.proposition,
            "communicative_goal": self.communicative_goal,
            "relation_to_previous": self.relation_to_previous,
            "detail_level": self.detail_level,
            "needs_example": self.needs_example,
            "say_now": self.say_now,
        }


@dataclass(frozen=True, slots=True)
class CognitivePlan:
    """Những gì ERIS cần hiểu/giữ trong đầu để xử lý turn này."""

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
    """Công việc còn phải làm trước khi public response được coi là đủ."""

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
class TurnSpeechBudget:
    """Metadata/gợi ý do *agent executive* có thể dùng khi tự lập discourse plan.

    Từ V7 runtime không dùng object này để chọn beat, cắt beat hay cắt public text.
    Các field được giữ chủ yếu để tương thích schema/telemetry. Chính agent loop
    nhìn ``voice_mode`` + ngữ cảnh rồi quyết ``DialogueBeat.say_now`` và
    ``continuation.deferred_threads``.
    """

    target_words: int = 110
    hard_max_words: int = 180
    max_beats: int = 2
    target_seconds: float = 24.0
    hard_max_seconds: float = 36.0

    def normalized(self) -> "TurnSpeechBudget":
        # Không đặt upper cap cho lời nói. Các giá trị này chỉ là guidance/telemetry.
        # ``max_beats`` vẫn là số beat ConversationDirector muốn *reveal* trong
        # lượt này; nó không giới hạn số câu/từ mà writer dùng để diễn đạt beat.
        target = max(1, int(self.target_words))
        hard = max(target, int(self.hard_max_words))
        beats = max(1, int(self.max_beats))
        seconds = max(0.1, float(self.target_seconds))
        hard_seconds = max(seconds, float(self.hard_max_seconds))
        return replace(
            self,
            target_words=target,
            hard_max_words=hard,
            max_beats=beats,
            target_seconds=seconds,
            hard_max_seconds=hard_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {
            "target_words": item.target_words,
            "hard_max_words": item.hard_max_words,
            "max_beats": item.max_beats,
            "target_seconds": round(item.target_seconds, 1),
            "hard_max_seconds": round(item.hard_max_seconds, 1),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "TurnSpeechBudget":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            return cls(
                target_words=int(data.get("target_words", 110) or 110),
                hard_max_words=int(data.get("hard_max_words", 180) or 180),
                max_beats=int(data.get("max_beats", 2) or 2),
                target_seconds=float(data.get("target_seconds", 24.0) or 24.0),
                hard_max_seconds=float(
                    data.get("hard_max_seconds", float(data.get("target_seconds", 24.0) or 24.0) * 1.5)
                    or 36.0
                ),
            ).normalized()
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True, slots=True)
class ContinuationPlan:
    """Kế hoạch tiếp tục *qua lượt chat sau*.

    ``deferred_threads`` là thông tin ERIS biết nhưng chủ động chưa nói. Nó là
    cơ chế chống information dump: deferred != forgotten.
    """

    active_thread: str = ""
    deferred_threads: tuple[str, ...] = ()
    continuation_anchor: str = ""
    next_if_continue: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_thread": self.active_thread,
            "deferred_threads": list(self.deferred_threads),
            "continuation_anchor": self.continuation_anchor,
            "next_if_continue": self.next_if_continue,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ContinuationPlan":
        data = raw if isinstance(raw, Mapping) else {}
        return cls(
            active_thread=_clean(data.get("active_thread"), 300),
            deferred_threads=_tuple_text(
                data.get("deferred_threads") if isinstance(data.get("deferred_threads"), Sequence) else (),
                limit=10,
                item_limit=360,
            ),
            continuation_anchor=_clean(data.get("continuation_anchor"), 420),
            next_if_continue=_clean(data.get("next_if_continue"), 420),
        )


@dataclass(frozen=True, slots=True)
class ConversationSpeechPlan:
    """Kế hoạch nói dài hạn do **root agent** tự lập.

    Đây là planning artifact public-safe, KHÔNG phải chain-of-thought và cũng
    KHÔNG phải câu thoại đã viết sẵn. Runtime chỉ được persist lifecycle rồi đưa
    nguyên snapshot lại cho AgentLoop khi user trả lời hoặc khi agent đã tự chọn
    ``AUTO_CONTINUE``.

    Runtime tuyệt đối không được nhìn ``planned_threads`` / ``next_intent`` rồi
    tự materialize thành lời nói.
    """

    plan_id: str = ""
    topic: str = ""
    conversation_goal: str = ""
    current_thread: str = ""
    discussed: tuple[str, ...] = ()
    planned_threads: tuple[str, ...] = ()
    next_intent: str = ""
    continuation_mode: SpeechContinuationMode = SpeechContinuationMode.NONE
    resume_trigger: str = ""
    pause_seconds: float = 0.0

    @property
    def owns_future_turn(self) -> bool:
        """True khi chính agent đã cam kết còn lifecycle continuation."""
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
            pause = max(0.0, min(30.0, float(data.get("pause_seconds", 0.0) or 0.0)))
        except (TypeError, ValueError):
            pause = 0.0
        return cls(
            plan_id=_clean(data.get("plan_id"), 180),
            topic=_clean(data.get("topic"), 500),
            conversation_goal=_clean(data.get("conversation_goal"), 700),
            current_thread=_clean(data.get("current_thread"), 420),
            discussed=_tuple_text(
                data.get("discussed") if isinstance(data.get("discussed"), Sequence) else (),
                limit=16, item_limit=360,
            ),
            planned_threads=_tuple_text(
                data.get("planned_threads") if isinstance(data.get("planned_threads"), Sequence) else (),
                limit=16, item_limit=420,
            ),
            next_intent=_clean(data.get("next_intent"), 700),
            continuation_mode=mode,
            resume_trigger=_clean(data.get("resume_trigger"), 120),
            pause_seconds=pause,
        )


@dataclass(frozen=True, slots=True)
class DiscoursePlan:
    """Kế hoạch nói ra ngoài do root agent executive sở hữu.

    ``DialogueBeat.say_now`` là quyết định semantic của agent: beat nào được nói
    ở turn hiện tại. ``continuation.deferred_threads`` cũng do agent tự chọn.
    Runtime chỉ project đúng quyết định này cho writer, không tự giới hạn 1-2 beat.
    """

    response_mode: str = "normal"
    disclosure_mode: DisclosureMode = DisclosureMode.CONVERSATIONAL
    beats: tuple[DialogueBeat, ...] = ()
    style_notes: tuple[str, ...] = ()
    user_response_required: bool = False
    speech_budget: TurnSpeechBudget = field(default_factory=TurnSpeechBudget)
    continuation: ContinuationPlan = field(default_factory=ContinuationPlan)
    speech_plan: ConversationSpeechPlan = field(default_factory=ConversationSpeechPlan)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_mode": self.response_mode,
            "disclosure_mode": self.disclosure_mode.value,
            "beats": [beat.to_dict() for beat in self.beats],
            "style_notes": list(self.style_notes),
            "user_response_required": self.user_response_required,
            "speech_budget": self.speech_budget.to_dict(),
            "continuation": self.continuation.to_dict(),
            "speech_plan": self.speech_plan.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LoopBudget:
    """Ngân sách adaptive: câu đơn giản dừng sớm, bài sâu mới được mở rộng."""

    soft_iterations: int = 2
    hard_iterations: int = 5
    max_beats: int = 8
    stall_limit: int = 2
    max_wall_seconds: float = 12.0

    def normalized(self) -> "LoopBudget":
        soft = max(1, min(6, int(self.soft_iterations)))
        hard = max(soft, min(10, int(self.hard_iterations)))
        return replace(
            self,
            soft_iterations=soft,
            hard_iterations=hard,
            max_beats=max(2, min(12, int(self.max_beats))),
            stall_limit=max(1, min(4, int(self.stall_limit))),
            max_wall_seconds=max(3.0, min(30.0, float(self.max_wall_seconds))),
        )


@dataclass(frozen=True, slots=True)
class TurnDecision:
    """Kết luận typed của một vòng model worker.

    ``decision_summary`` chỉ là rationale vận hành ngắn (ví dụ "còn thiếu ví dụ
    và kiểm tra mâu thuẫn"), tuyệt đối không yêu cầu hay lưu chain-of-thought.
    """

    action: TurnAction = TurnAction.COMPLETE
    cognitive: CognitivePlan = field(default_factory=CognitivePlan)
    discourse: DiscoursePlan = field(default_factory=DiscoursePlan)
    speech_plan: ConversationSpeechPlan = field(default_factory=ConversationSpeechPlan)
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
        uncertainties = _tuple_text(data.get("uncertainties") if isinstance(data.get("uncertainties"), Sequence) else (), limit=6)
        beats_raw = data.get("dialogue_beats") if isinstance(data.get("dialogue_beats"), Sequence) else ()
        beats = tuple(
            beat for beat in (DialogueBeat.from_mapping(item) for item in beats_raw if isinstance(item, Mapping))
            if beat.proposition
        )[:8]
        cognitive = CognitivePlan(
            situation_summary=_clean(data.get("situation_summary"), 1200),
            objective=_clean(data.get("objective"), 800),
            task_shape=_clean(data.get("task_shape"), 80) or "conversation",
            active_roles=roles,
            work_items=work_items,
            uncertainties=uncertainties,
        )
        raw_disclosure = str(data.get("disclosure_mode", "") or "").strip().lower()
        if not raw_disclosure:
            raw_disclosure = (
                "deep_dialogue"
                if str(data.get("response_mode", "") or "").strip().lower() in {"deep", "progressive"}
                else "conversational"
            )
        try:
            disclosure_mode = DisclosureMode(raw_disclosure)
        except ValueError:
            disclosure_mode = DisclosureMode.CONVERSATIONAL
        speech_raw = data.get("speech_budget") if isinstance(data.get("speech_budget"), Mapping) else None
        if speech_raw is None:
            speech_budget = (
                TurnSpeechBudget(target_words=280, hard_max_words=440, max_beats=3, target_seconds=65.0)
                if disclosure_mode == DisclosureMode.DEEP_DIALOGUE
                else TurnSpeechBudget(target_words=700, hard_max_words=1200, max_beats=6, target_seconds=150.0)
                if disclosure_mode == DisclosureMode.REPORT
                else TurnSpeechBudget()
            )
        else:
            speech_budget = TurnSpeechBudget.from_mapping(speech_raw)
        discourse = DiscoursePlan(
            response_mode=_clean(data.get("response_mode"), 40) or "normal",
            disclosure_mode=disclosure_mode,
            beats=beats,
            style_notes=_tuple_text(data.get("style_notes") if isinstance(data.get("style_notes"), Sequence) else (), limit=8, item_limit=240),
            user_response_required=bool(data.get("requires_user_response", False)),
            speech_budget=speech_budget,
            continuation=ContinuationPlan.from_mapping(
                data.get("continuation") if isinstance(data.get("continuation"), Mapping) else None
            ),
            speech_plan=ConversationSpeechPlan.from_mapping(
                data.get("speech_plan") if isinstance(data.get("speech_plan"), Mapping) else None
            ),
        )
        speech_plan = ConversationSpeechPlan.from_mapping(
            data.get("speech_plan") if isinstance(data.get("speech_plan"), Mapping) else None
        )
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
            completed_items=_tuple_text(data.get("completed_items") if isinstance(data.get("completed_items"), Sequence) else ()),
            remaining_items=_tuple_text(data.get("remaining_items") if isinstance(data.get("remaining_items"), Sequence) else ()),
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
    progress: float = 0.0
    uncertainty: float = 1.0
    stall_count: int = 0
    status: str = "running"
    decision_summaries: tuple[str, ...] = ()

    def to_model_dict(self) -> dict[str, Any]:
        """Projection an toàn cho vòng model kế tiếp; không có hidden reasoning."""
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "iteration": self.iteration,
            "cognitive_plan": self.cognitive.to_dict(),
            "execution_plan": self.execution.to_dict(),
            "discourse_plan": self.discourse.to_dict(),
            "conversation_speech_plan": self.speech_plan.to_dict(),
            "progress": round(self.progress, 3),
            "uncertainty": round(self.uncertainty, 3),
            "stall_count": self.stall_count,
            "status": self.status,
            "recent_decision_summaries": list(self.decision_summaries[-3:]),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.agent_turn.v8",
            **self.to_model_dict(),
        }


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
        """True khi AGENT đã chủ động nhường nhịp cho user.

        Compatibility: V7 plan cũ chưa có speech_plan authority; khi mode=NONE
        nhưng continuation.deferred_threads có dữ liệu, coi đó là legacy yield.
        Runtime không tự sinh deferred thread mới.
        """
        discourse = self.state.discourse
        progressive_mode = discourse.disclosure_mode in {
            DisclosureMode.CONVERSATIONAL,
            DisclosureMode.DEEP_DIALOGUE,
        }
        mode = self.state.speech_plan.continuation_mode
        legacy_yield = bool(
            mode == SpeechContinuationMode.NONE
            and discourse.continuation.deferred_threads
        )
        return bool(
            progressive_mode
            and (
                discourse.user_response_required
                or mode == SpeechContinuationMode.YIELD_USER
                or legacy_yield
            )
        )

    @property
    def owns_continuation(self) -> bool:
        return self.state.speech_plan.owns_future_turn

    def to_dict(self) -> dict[str, Any]:
        payload = self.state.to_dict()
        payload.update({
            "completion_reason": self.completion_reason,
            "model_iterations": self.model_iterations,
            "degraded": self.degraded,
        })
        return payload


__all__ = [
    "AgentTurnResult",
    "AgentTurnState",
    "BeatKind",
    "CognitivePlan",
    "DialogueBeat",
    "DisclosureMode",
    "ContinuationPlan",
    "ConversationSpeechPlan",
    "DiscoursePlan",
    "ExecutionPlan",
    "LoopBudget",
    "ResponseRelation",
    "SpeechContinuationMode",
    "TurnSpeechBudget",
    "TurnAction",
    "TurnDecision",
]
