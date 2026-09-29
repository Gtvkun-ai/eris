# -*- coding: utf-8 -*-
"""Durable lifecycle cho kế hoạch nói dài hạn do **root agent** sở hữu.

Boundary quan trọng của V8:

- Agent quyết định semantic: nói gì bây giờ, giữ thread nào, yield user hay
  auto-continue, và nếu auto-continue thì muốn nghỉ bao lâu.
- Runtime KHÔNG chọn nội dung, KHÔNG biến planned thread thành câu public,
  KHÔNG phát lại một câu đã cache.
- Runtime chỉ giữ snapshot nguyên vẹn, đánh dấu lifecycle delivery/audio và khi
  đúng hạn thì đánh thức TurnAgentLoop để agent *quyết định lại*.

State này cố ý chỉ chứa public-safe planning data. Không lưu chain-of-thought.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Any, Mapping

from .contracts import ConversationSpeechPlan, SpeechContinuationMode

try:
    from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
except Exception:  # pragma: no cover
    SQLiteAtomicStateStore = Any  # type: ignore[misc,assignment]


def _clean(value: Any, limit: int = 800) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


@dataclass(frozen=True, slots=True)
class SpeechPlanSnapshot:
    """Snapshot lifecycle quanh đúng kế hoạch agent đã commit."""

    session_id: str = "default"
    plan: ConversationSpeechPlan = ConversationSpeechPlan()
    status: str = "idle"
    last_turn_id: str = ""
    last_public_text: str = ""
    due_at: float = 0.0
    claim_token: str = ""
    version: int = 0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.agent_speech_plan.v1",
            "session_id": self.session_id,
            "plan": self.plan.to_dict(),
            "status": self.status,
            "last_turn_id": self.last_turn_id,
            "last_public_text": self.last_public_text,
            "due_at": round(max(0.0, self.due_at), 3),
            "claim_token": self.claim_token,
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None, *, session_id: str) -> "SpeechPlanSnapshot":
        data = raw if isinstance(raw, Mapping) else {}
        try:
            due = max(0.0, float(data.get("due_at", 0.0) or 0.0))
        except (TypeError, ValueError):
            due = 0.0
        try:
            updated = max(0.0, float(data.get("updated_at", 0.0) or 0.0))
        except (TypeError, ValueError):
            updated = 0.0
        return cls(
            session_id=_clean(data.get("session_id", session_id), 180) or session_id,
            plan=ConversationSpeechPlan.from_mapping(
                data.get("plan") if isinstance(data.get("plan"), Mapping) else None
            ),
            status=_clean(data.get("status"), 80) or "idle",
            last_turn_id=_clean(data.get("last_turn_id"), 180),
            last_public_text=_clean(data.get("last_public_text"), 4000),
            due_at=due,
            claim_token=_clean(data.get("claim_token"), 180),
            version=max(0, int(data.get("version", 0) or 0)),
            updated_at=updated,
        )

    @property
    def auto_continue_due(self) -> bool:
        return bool(
            self.status == "auto_continue_scheduled"
            and self.plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE
            and self.due_at > 0.0
            and self.due_at <= time.time()
        )


class SpeechPlanLedger:
    """Persist exact agent-authored plan; runtime chỉ mutate lifecycle fields.

    Mọi mutation dùng transaction khi có SQLite store để concurrent foreground /
    autonomous wake không ghi đè semantic plan của nhau bằng stale snapshot.
    """

    def __init__(self, *, atomic_store: SQLiteAtomicStateStore | None = None, logger: Any = None) -> None:
        self.atomic_store = atomic_store
        self.logger = logger
        self._memory: dict[str, SpeechPlanSnapshot] = {}

    @staticmethod
    def _sid(session_id: str) -> str:
        return _clean(session_id, 180) or "default"

    @classmethod
    def _key(cls, session_id: str) -> str:
        return f"eris.agent_speech_plan:{cls._sid(session_id)}"

    def load(self, session_id: str) -> SpeechPlanSnapshot:
        sid = self._sid(session_id)
        if self.atomic_store is None:
            return self._memory.get(sid, SpeechPlanSnapshot(session_id=sid))
        try:
            record = self.atomic_store.ensure(self._key(sid), SpeechPlanSnapshot(session_id=sid).to_dict())
            snap = SpeechPlanSnapshot.from_mapping(record.payload, session_id=sid)
            self._memory[sid] = snap
            return snap
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[agent-speech-plan] durable load degraded: %s", exc)
            return self._memory.get(sid, SpeechPlanSnapshot(session_id=sid))

    def _mutate(self, session_id: str, fn) -> SpeechPlanSnapshot:
        sid = self._sid(session_id)
        now = time.time()
        if self.atomic_store is None:
            prior = self._memory.get(sid, SpeechPlanSnapshot(session_id=sid))
            state = fn(prior, now)
            state = replace(state, version=prior.version + 1, updated_at=now)
            self._memory[sid] = state
            return state
        try:
            key = self._key(sid)
            with self.atomic_store.transaction(key, SpeechPlanSnapshot(session_id=sid).to_dict()) as tx:
                prior = SpeechPlanSnapshot.from_mapping(tx.payload, session_id=sid)
                state = fn(prior, now)
                state = replace(state, version=prior.version + 1, updated_at=now)
                tx.stage(state.to_dict())
            self._memory[sid] = state
            return state
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[agent-speech-plan] durable mutation degraded: %s", exc)
            prior = self._memory.get(sid, SpeechPlanSnapshot(session_id=sid))
            state = fn(prior, now)
            state = replace(state, version=prior.version + 1, updated_at=now)
            self._memory[sid] = state
            return state

    def commit_agent_plan(
        self,
        session_id: str,
        *,
        plan: ConversationSpeechPlan,
        turn_id: str,
    ) -> SpeechPlanSnapshot:
        """Lưu nguyên snapshot semantic mới nhất của agent, không merge heuristic."""
        return self._mutate(
            session_id,
            lambda prior, now: SpeechPlanSnapshot(
                session_id=prior.session_id,
                plan=plan,
                status="planned" if plan.owns_future_turn else "idle",
                last_turn_id=_clean(turn_id, 180),
                last_public_text=prior.last_public_text,
                due_at=0.0,
                claim_token="",
                version=prior.version,
                updated_at=now,
            ),
        )

    def note_public_delivery(self, session_id: str, *, turn_id: str, public_text: str) -> SpeechPlanSnapshot:
        """Receipt delivery. Text chỉ để resume context; không được dùng để replay."""
        def update(prior: SpeechPlanSnapshot, now: float) -> SpeechPlanSnapshot:
            status = "delivered_waiting_audio" if prior.plan.owns_future_turn else "idle"
            return replace(
                prior,
                status=status,
                last_turn_id=_clean(turn_id, 180) or prior.last_turn_id,
                last_public_text=_clean(public_text, 4000),
                due_at=0.0,
                claim_token="",
            )
        return self._mutate(session_id, update)

    def note_audio_finished(self, session_id: str, *, now: float | None = None) -> SpeechPlanSnapshot:
        ts = float(now if now is not None else time.time())
        def update(prior: SpeechPlanSnapshot, _clock: float) -> SpeechPlanSnapshot:
            mode = prior.plan.continuation_mode
            if mode == SpeechContinuationMode.YIELD_USER:
                return replace(prior, status="waiting_user", due_at=0.0, claim_token="")
            if mode == SpeechContinuationMode.AUTO_CONTINUE:
                pause = max(0.0, float(prior.plan.pause_seconds))
                return replace(prior, status="auto_continue_scheduled", due_at=ts + pause, claim_token="")
            return replace(prior, status="idle", due_at=0.0, claim_token="")
        return self._mutate(session_id, update)

    def note_user_turn(self, session_id: str) -> SpeechPlanSnapshot:
        """User luôn thắng auto-continuation; semantic plan vẫn giữ để agent đọc lại."""
        def update(prior: SpeechPlanSnapshot, now: float) -> SpeechPlanSnapshot:
            return replace(prior, status="user_replied", due_at=0.0, claim_token="")
        return self._mutate(session_id, update)

    def claim_auto_continue(self, session_id: str, *, token: str, now: float | None = None) -> SpeechPlanSnapshot | None:
        ts = float(now if now is not None else time.time())
        claimed: SpeechPlanSnapshot | None = None
        def update(prior: SpeechPlanSnapshot, _clock: float) -> SpeechPlanSnapshot:
            nonlocal claimed
            if not (
                prior.status == "auto_continue_scheduled"
                and prior.plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE
                and prior.due_at > 0.0
                and prior.due_at <= ts
            ):
                return prior
            claimed = replace(prior, status="claimed", due_at=0.0, claim_token=_clean(token, 180))
            return claimed
        state = self._mutate(session_id, update)
        return state if claimed is not None else None

    def release_claim(self, session_id: str, *, token: str, retry_seconds: float = 0.5) -> SpeechPlanSnapshot:
        """Nếu wake chưa thể materialize, trả quyền về lịch cũ mà không sửa plan."""
        def update(prior: SpeechPlanSnapshot, now: float) -> SpeechPlanSnapshot:
            if prior.status != "claimed" or prior.claim_token != _clean(token, 180):
                return prior
            if prior.plan.continuation_mode != SpeechContinuationMode.AUTO_CONTINUE:
                return replace(prior, status="idle", claim_token="", due_at=0.0)
            return replace(
                prior,
                status="auto_continue_scheduled",
                claim_token="",
                due_at=now + max(0.1, float(retry_seconds)),
            )
        return self._mutate(session_id, update)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["SpeechPlanLedger", "SpeechPlanSnapshot"]
