# -*- coding: utf-8 -*-
"""Domain adapters for the engagement kernel.

The kernel manages lifecycle and attention. Adapters own domain state, lifecycle
signals and their small planner projection. Adding a new long-running activity
should add an adapter, not another ``if kind == ...`` to the coordinator.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from .contracts import (
    Engagement,
    EngagementEvent,
    LifecycleSignal,
    LifecycleStatus,
    PlannerProjection,
)


def _compact(value: Any, limit: int = 220) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _recent(state: Mapping[str, Any], text: str, *, limit: int = 8) -> list[str]:
    items = [str(item) for item in tuple(state.get("recent_progress", ()) or ()) if str(item).strip()]
    if text:
        items.append(_compact(text, 180))
    return list(dict.fromkeys(items))[-limit:]


def _status(payload: Mapping[str, Any]) -> str:
    return _compact(
        payload.get("status") or payload.get("state") or payload.get("result") or payload.get("outcome"),
        80,
    ).lower()


def _ends_with(kind: str, values: tuple[str, ...]) -> bool:
    return any(kind == item or kind.endswith(f".{item}") for item in values)


class EngagementAdapter(Protocol):
    adapter_id: str

    def initial_state(self, objective: str, *, metadata: Mapping[str, Any] | None = None) -> Mapping[str, Any]: ...

    def reduce(self, state: Mapping[str, Any], event: EngagementEvent) -> Mapping[str, Any]: ...

    def project(self, engagement: Engagement, *, now: float) -> PlannerProjection: ...

    def accepts_evidence(self, kind: str, *, source: str, payload: Mapping[str, Any]) -> bool: ...

    def signal_importance(self, event: EngagementEvent) -> float: ...

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None: ...


class GenericEngagementAdapter:
    adapter_id = "generic"
    summary_label = "Shared activity"
    expected_events = ("user progress", "activity change", "user request", "completion")

    _GENERIC_COMPLETION_EVENTS = {
        "task.completed",
        "session.completed",
        "session.ended",
        "routine.completed",
        "game.completed",
        "game.ended",
        "game.over",
    }

    def initial_state(self, objective: str, *, metadata: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        metadata = dict(metadata or {})
        return {
            "summary": _compact(objective, 300),
            "recent_progress": [],
            "next_expected_events": list(self.expected_events),
            "waiting_for_user": False,
            "metadata": metadata,
        }

    def accepts_evidence(self, kind: str, *, source: str, payload: Mapping[str, Any]) -> bool:
        del source, payload
        return bool(str(kind or "").strip())

    def signal_importance(self, event: EngagementEvent) -> float:
        kind = str(event.kind or "").strip().lower()
        fixed = {
            "domain.progress": 0.72,
            "task.progress": 0.68,
            "activity.changed": 0.52,
            "engagement.resumed": 0.40,
            "engagement.started": 0.35,
            "engagement.waiting": 0.50,
            "engagement.paused": 0.62,
            "engagement.completed": 0.95,
            "engagement.cancelled": 0.95,
        }
        if kind in fixed:
            return fixed[kind]
        if event.source == "domain" and kind not in {"assistant.spoke", "user.message_received"}:
            return 0.72
        return 0.0

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None:
        del state
        kind = str(event.kind or "").strip().lower()
        if kind.startswith("engagement."):
            return None
        if kind in self._GENERIC_COMPLETION_EVENTS:
            return LifecycleSignal(LifecycleStatus.COMPLETED, "terminal_domain_event", kind)
        if _ends_with(kind, ("cancelled", "canceled", "aborted")):
            return LifecycleSignal(LifecycleStatus.CANCELLED, "domain_cancelled", kind)
        if kind in {"task.waiting", "session.waiting", "task.blocked", "session.blocked"}:
            return LifecycleSignal(LifecycleStatus.WAITING, "domain_waiting", kind)
        if kind in {"task.resumed", "session.resumed"} and engagement.lifecycle in {
            LifecycleStatus.WAITING,
            LifecycleStatus.PAUSED,
        }:
            return LifecycleSignal(LifecycleStatus.ACTIVE, "domain_resumed", kind)
        return None

    def reduce(self, state: Mapping[str, Any], event: EngagementEvent) -> Mapping[str, Any]:
        data = dict(state or {})
        payload = dict(event.payload or {})
        kind = event.kind
        detail = _compact(payload.get("detail") or payload.get("text") or payload.get("event"), 220)
        if kind == "user.message_received":
            data["last_user_message"] = detail
            data["waiting_for_user"] = False
            data["recent_progress"] = _recent(data, f"User: {detail}" if detail else "User continued the activity")
        elif kind == "assistant.spoke":
            data["last_assistant_message"] = detail
            data["recent_progress"] = _recent(data, f"ERIS: {detail}" if detail else "ERIS responded")
        elif kind in {"activity.changed", "domain.progress", "task.progress"} or event.source == "domain":
            data["last_activity_event"] = detail or kind
            data["recent_progress"] = _recent(data, detail or kind)
        elif kind == "engagement.waiting":
            data["waiting_for_user"] = True
            data["recent_progress"] = _recent(data, detail or "Engagement waiting")
        elif kind == "engagement.paused":
            data["waiting_for_user"] = False
            data["recent_progress"] = _recent(data, detail or "Engagement paused")
        elif kind in {"engagement.resumed", "engagement.started"}:
            data["waiting_for_user"] = False
            data["recent_progress"] = _recent(data, detail or kind.replace("engagement.", "Engagement "))
        elif kind in {"engagement.completed", "engagement.cancelled"}:
            data["waiting_for_user"] = False
            data["recent_progress"] = _recent(data, detail or kind.replace("engagement.", "Engagement "))
        for key in (
            "fen", "pgn", "move_number", "file", "test_status", "step", "progress",
            "result", "status", "state", "outcome", "error", "url", "artifact",
            "mode", "full_assistance", "side_to_move", "last_move_uci",
            "last_move_san", "evaluation_cp", "evaluation_label",
            "suggested_move_uci", "suggested_move_san", "confidence",
            "evaluation_swing_cp", "move_quality", "hint_focus",
        ):
            if key in payload:
                data[key] = payload[key]
        return data

    def _state_summary(self, engagement: Engagement) -> str:
        state = engagement.domain_state
        return _compact(state.get("summary") or engagement.objective, 360)

    def project(self, engagement: Engagement, *, now: float) -> PlannerProjection:
        state = engagement.domain_state
        constraints = tuple(
            [f"Allowed: {item}" for item in engagement.contract.allowed_actions]
            + [f"Forbidden: {item}" for item in engagement.contract.forbidden_actions]
        )
        return PlannerProjection(
            engagement_id=engagement.engagement_id,
            kind=engagement.kind,
            objective=engagement.objective,
            lifecycle=engagement.lifecycle.value,
            focus=engagement.focus.value,
            priority=engagement.priority,
            role=engagement.contract.role,
            initiative=engagement.contract.initiative.value,
            feedback_style=engagement.contract.feedback_style,
            current_state_summary=self._state_summary(engagement),
            recent_progress=tuple(str(item) for item in tuple(state.get("recent_progress", ()) or ())[-6:]),
            next_expected_events=tuple(
                str(item) for item in tuple(state.get("next_expected_events", self.expected_events) or self.expected_events)[:8]
            ),
            interaction_constraints=constraints[:12],
            age_seconds=max(0.0, now - engagement.started_at),
            seconds_since_progress=max(0.0, now - engagement.last_progress_at),
            evidence_binding=engagement.evidence_binding.to_dict(),
            last_event_kind=engagement.last_event_kind,
            lifecycle_changed_at=engagement.lifecycle_changed_at,
            last_event_log_seq=engagement.last_event_log_seq,
        )


class ChessCompanionAdapter(GenericEngagementAdapter):
    adapter_id = "chess"
    summary_label = "Chess game"
    expected_events = ("board position changed", "move played", "hint request", "game ended")

    def accepts_evidence(self, kind: str, *, source: str, payload: Mapping[str, Any]) -> bool:
        del source, payload
        return str(kind or "").strip().lower().startswith("chess.")

    def signal_importance(self, event: EngagementEvent) -> float:
        kind = str(event.kind or "").strip().lower()
        if kind == "chess.game_started":
            return 0.78
        if kind == "chess.move_played":
            return 0.94
        if kind == "chess.position_changed":
            return 0.82
        if kind in {"chess.game_over", "chess.game.ended", "chess.game.completed"}:
            return 0.99
        return super().signal_importance(event)

    def project(self, engagement: Engagement, *, now: float) -> PlannerProjection:
        base = super().project(engagement, now=now)
        state = engagement.domain_state
        # All modes (analysis, bot, private, live) now receive full assistance.
        # The only exception is UNKNOWN pages which send full_assistance=False.
        full = bool(state.get("full_assistance", True))
        dynamic = (
            "May evaluate the position, tease mistakes, offer hints, and occasionally state the suggested move directly."
            if full else
            "Unknown page: cannot confirm game context — only react socially, do not suggest moves or evaluate."
        )
        constraints = tuple(base.interaction_constraints) + (dynamic,)
        return PlannerProjection(
            engagement_id=base.engagement_id, kind=base.kind, objective=base.objective,
            lifecycle=base.lifecycle, focus=base.focus, priority=base.priority, role=base.role,
            initiative=base.initiative, feedback_style=base.feedback_style,
            current_state_summary=base.current_state_summary, recent_progress=base.recent_progress,
            next_expected_events=base.next_expected_events, interaction_constraints=constraints[:12],
            age_seconds=base.age_seconds, seconds_since_progress=base.seconds_since_progress,
            evidence_binding=base.evidence_binding, last_event_kind=base.last_event_kind,
            lifecycle_changed_at=base.lifecycle_changed_at, last_event_log_seq=base.last_event_log_seq,
            resume_focus=base.resume_focus,
        )

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None:
        kind = str(event.kind or "").strip().lower()
        if kind in {"chess.game_over", "chess.game.ended", "chess.game.completed"}:
            return LifecycleSignal(LifecycleStatus.COMPLETED, "chess_game_finished", _status(event.payload) or kind)
        return super().lifecycle_signal(engagement, event, state)

    def _state_summary(self, engagement: Engagement) -> str:
        state = engagement.domain_state
        pieces = [engagement.objective]
        if state.get("mode"):
            pieces.append(f"mode={_compact(state.get('mode'), 32)}")
        if state.get("move_number") is not None:
            pieces.append(f"move {state.get('move_number')}")
        if state.get("side_to_move"):
            pieces.append(f"to_move={_compact(state.get('side_to_move'), 16)}")
        if state.get("last_move_san") or state.get("last_move_uci"):
            pieces.append(f"last={_compact(state.get('last_move_san') or state.get('last_move_uci'), 24)}")
        if state.get("evaluation_label"):
            pieces.append(f"evaluation={_compact(state.get('evaluation_label'), 40)}")
        if state.get("move_quality"):
            pieces.append(f"move_quality={_compact(state.get('move_quality'), 24)}")
        if state.get("hint_focus"):
            pieces.append(f"hint_focus={_compact(state.get('hint_focus'), 32)}")
        if state.get("suggested_move_san") or state.get("suggested_move_uci"):
            pieces.append(f"suggestion={_compact(state.get('suggested_move_san') or state.get('suggested_move_uci'), 24)}")
        if state.get("fen"):
            pieces.append(f"FEN={_compact(state.get('fen'), 120)}")
        if state.get("result"):
            pieces.append(f"result={_compact(state.get('result'), 40)}")
        return "; ".join(piece for piece in pieces if piece)


class CodingCompanionAdapter(GenericEngagementAdapter):
    adapter_id = "coding"
    summary_label = "Coding session"
    expected_events = ("file changed", "tests completed", "error appeared", "user asks for review")

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None:
        kind = str(event.kind or "").strip().lower()
        if kind in {"coding.session.completed", "coding.session.ended", "task.completed"}:
            return LifecycleSignal(LifecycleStatus.COMPLETED, "coding_session_finished", kind)
        return super().lifecycle_signal(engagement, event, state)

    def _state_summary(self, engagement: Engagement) -> str:
        state = engagement.domain_state
        pieces = [engagement.objective]
        if state.get("file"):
            pieces.append(f"file={_compact(state.get('file'), 120)}")
        if state.get("test_status"):
            pieces.append(f"tests={_compact(state.get('test_status'), 80)}")
        return "; ".join(piece for piece in pieces if piece)


class GuidedRoutineAdapter(GenericEngagementAdapter):
    adapter_id = "guided_routine"
    summary_label = "Guided routine"
    expected_events = ("step completed", "user asks for help", "pause", "routine completed")

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None:
        kind = str(event.kind or "").strip().lower()
        if kind in {
            "routine.completed", "workout.completed", "study.completed", "cooking.completed", "task.completed",
        }:
            return LifecycleSignal(LifecycleStatus.COMPLETED, "guided_routine_finished", kind)
        if kind in {"routine.waiting", "step.waiting", "step.blocked"}:
            return LifecycleSignal(LifecycleStatus.WAITING, "guided_routine_waiting", kind)
        return super().lifecycle_signal(engagement, event, state)

    def _state_summary(self, engagement: Engagement) -> str:
        state = engagement.domain_state
        pieces = [engagement.objective]
        if state.get("step") is not None:
            pieces.append(f"current step={state.get('step')}")
        if state.get("progress") is not None:
            pieces.append(f"progress={state.get('progress')}")
        return "; ".join(piece for piece in pieces if piece)


class MonitoringAdapter(GenericEngagementAdapter):
    adapter_id = "monitoring"
    summary_label = "Background monitor"
    expected_events = ("watched state changed", "success", "failure", "monitor stopped")

    def accepts_evidence(self, kind: str, *, source: str, payload: Mapping[str, Any]) -> bool:
        normalized = str(kind or "").strip().lower()
        if source == "activity_session" and normalized == "activity.changed":
            return True  # Router still requires an exact binding for background monitors.
        return normalized.startswith(("build.", "deployment.", "download.", "render.", "monitor.")) or normalized in {
            "domain.progress", "task.progress", "engagement.completed", "engagement.cancelled",
        }

    def signal_importance(self, event: EngagementEvent) -> float:
        normalized = str(event.kind or "").strip().lower()
        if normalized.startswith(("build.", "deployment.", "download.", "render.", "monitor.")):
            return 0.96 if _ends_with(normalized, ("completed", "succeeded", "failed", "cancelled", "canceled")) else 0.82
        return super().signal_importance(event)

    def lifecycle_signal(
        self,
        engagement: Engagement,
        event: EngagementEvent,
        state: Mapping[str, Any],
    ) -> LifecycleSignal | None:
        del state
        kind = str(event.kind or "").strip().lower()
        if kind.startswith("engagement."):
            return None
        watched = kind.startswith(("build.", "deployment.", "download.", "render.", "monitor.")) or kind in {
            "domain.progress", "task.progress",
        }
        if not watched:
            return super().lifecycle_signal(engagement, event, {})
        status = _status(event.payload)
        if _ends_with(kind, ("cancelled", "canceled", "aborted")) or status in {"cancelled", "canceled", "aborted"}:
            return LifecycleSignal(LifecycleStatus.CANCELLED, "monitor_cancelled", status or kind)
        if _ends_with(kind, ("completed", "succeeded", "failed", "finished", "done")) or status in {
            "success", "succeeded", "completed", "complete", "done", "failed", "failure", "error",
        }:
            return LifecycleSignal(LifecycleStatus.COMPLETED, "monitor_terminal_state", status or kind)
        if _ends_with(kind, ("queued", "pending", "started", "running", "waiting")) or status in {
            "queued", "pending", "started", "running", "waiting",
        }:
            return LifecycleSignal(LifecycleStatus.WAITING, "monitor_in_progress", status or kind)
        return None


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, EngagementAdapter] = {}
        for adapter in (
            GenericEngagementAdapter(),
            ChessCompanionAdapter(),
            CodingCompanionAdapter(),
            GuidedRoutineAdapter(),
            MonitoringAdapter(),
        ):
            self.register(adapter)

    def register(self, adapter: EngagementAdapter) -> None:
        adapter_id = _compact(getattr(adapter, "adapter_id", ""), 80)
        if not adapter_id:
            raise ValueError("adapter_id is required")
        self._adapters[adapter_id] = adapter

    def get(self, adapter_id: str) -> EngagementAdapter:
        return self._adapters.get(str(adapter_id or "").strip(), self._adapters["generic"])

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


__all__ = [
    "AdapterRegistry",
    "ChessCompanionAdapter",
    "CodingCompanionAdapter",
    "EngagementAdapter",
    "GenericEngagementAdapter",
    "GuidedRoutineAdapter",
    "MonitoringAdapter",
]
