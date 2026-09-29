# -*- coding: utf-8 -*-
"""State dài hạn cho *nhịp tiết lộ* của foreground conversation.

Module này KHÔNG tự nói và cũng không tự chạy autonomous follow-up. Nó chỉ nhớ:
- thread nào đang được đào sâu;
- những nhánh ERIS đã nói;
- những nhánh ERIS biết nhưng cố tình giữ lại;
- móc nối nào hợp lý nếu user muốn tiếp tục.

Điểm quan trọng: ``deferred_threads`` không phải backlog bắt buộc phải xổ ra.
User có thể đổi hướng bất cứ lúc nào; TurnAgentLoop sẽ re-plan dựa trên turn mới.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping

try:
    from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
except Exception:  # pragma: no cover - giữ package importable khi runtime tối giản
    SQLiteAtomicStateStore = Any  # type: ignore[misc,assignment]


def _compact(value: Any, limit: int = 420) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _items(value: Any, limit: int = 12) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    out: list[str] = []
    for item in value:
        text = _compact(item, 360)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


@dataclass(frozen=True, slots=True)
class DisclosureArcState:
    """Snapshot nhỏ, audit được; tuyệt đối không chứa chain-of-thought."""

    session_id: str = "default"
    topic: str = ""
    active_thread: str = ""
    discussed_threads: tuple[str, ...] = ()
    deferred_threads: tuple[str, ...] = ()
    continuation_anchor: str = ""
    next_if_continue: str = ""
    speech_goal: str = ""
    planned_threads: tuple[str, ...] = ()
    next_intent: str = ""
    continuation_mode: str = "none"
    resume_reason: str = ""
    plan_status: str = "ready"
    version: int = 0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.disclosure_arc.v1",
            "session_id": self.session_id,
            "topic": self.topic,
            "active_thread": self.active_thread,
            "discussed_threads": list(self.discussed_threads),
            "deferred_threads": list(self.deferred_threads),
            "continuation_anchor": self.continuation_anchor,
            "next_if_continue": self.next_if_continue,
            "speech_goal": self.speech_goal,
            "planned_threads": list(self.planned_threads),
            "next_intent": self.next_intent,
            "continuation_mode": self.continuation_mode,
            "resume_reason": self.resume_reason,
            "plan_status": self.plan_status,
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None, *, session_id: str = "default") -> "DisclosureArcState":
        data = raw if isinstance(raw, Mapping) else {}
        return cls(
            session_id=_compact(data.get("session_id", session_id), 180) or session_id,
            topic=_compact(data.get("topic"), 500),
            active_thread=_compact(data.get("active_thread"), 360),
            discussed_threads=_items(data.get("discussed_threads"), 16),
            deferred_threads=_items(data.get("deferred_threads"), 16),
            continuation_anchor=_compact(data.get("continuation_anchor"), 500),
            next_if_continue=_compact(data.get("next_if_continue"), 500),
            speech_goal=_compact(data.get("speech_goal"), 700),
            planned_threads=_items(data.get("planned_threads"), 16),
            next_intent=_compact(data.get("next_intent"), 600),
            continuation_mode=_compact(data.get("continuation_mode"), 40) or "none",
            resume_reason=_compact(data.get("resume_reason"), 240),
            plan_status=_compact(data.get("plan_status"), 40) or "ready",
            version=max(0, int(data.get("version", 0) or 0)),
            updated_at=max(0.0, float(data.get("updated_at", 0.0) or 0.0)),
        )


class DisclosureArcLedger:
    """Ledger per-session với memory fallback và optional SQLite CAS store.

    Trong pytest/default tối giản, memory fallback đủ để test deterministic.
    Khi ERIS có ``SQLiteAtomicStateStore``, cùng state này sống qua restart.
    """

    def __init__(self, *, atomic_store: SQLiteAtomicStateStore | None = None, logger: Any = None) -> None:
        self.atomic_store = atomic_store
        self.logger = logger
        self._memory: dict[str, DisclosureArcState] = {}

    @staticmethod
    def _key(session_id: str) -> str:
        safe = _compact(session_id, 180) or "default"
        return f"eris.agent_disclosure:{safe}"

    def load(self, session_id: str) -> DisclosureArcState:
        sid = _compact(session_id, 180) or "default"
        if self.atomic_store is None:
            return self._memory.get(sid, DisclosureArcState(session_id=sid))
        try:
            record = self.atomic_store.ensure(self._key(sid), DisclosureArcState(session_id=sid).to_dict())
            return DisclosureArcState.from_mapping(record.payload, session_id=sid)
        except Exception as exc:  # noqa: BLE001
            self._log("debug", "[agent-disclosure] durable load degraded: %s", exc)
            return self._memory.get(sid, DisclosureArcState(session_id=sid))

    def commit(
        self,
        session_id: str,
        *,
        topic: str,
        active_thread: str,
        discussed_threads: tuple[str, ...],
        deferred_threads: tuple[str, ...],
        continuation_anchor: str,
        next_if_continue: str,
        speech_goal: str = "",
        planned_threads: tuple[str, ...] = (),
        next_intent: str = "",
        continuation_mode: str = "none",
        resume_reason: str = "",
        plan_status: str = "ready",
        now: float | None = None,
    ) -> DisclosureArcState:
        prior = self.load(session_id)
        ts = float(now if now is not None else time.time())
        discussed = _items((*prior.discussed_threads, *discussed_threads), 16)
        state = DisclosureArcState(
            session_id=prior.session_id,
            topic=_compact(topic, 500) or prior.topic,
            active_thread=_compact(active_thread, 360) or prior.active_thread,
            discussed_threads=discussed,
            deferred_threads=_items(deferred_threads, 16),
            continuation_anchor=_compact(continuation_anchor, 500),
            next_if_continue=_compact(next_if_continue, 500),
            speech_goal=_compact(speech_goal, 700) or prior.speech_goal,
            planned_threads=_items(planned_threads, 16),
            next_intent=_compact(next_intent, 600),
            continuation_mode=_compact(continuation_mode, 40) or "none",
            resume_reason=_compact(resume_reason, 240),
            plan_status=_compact(plan_status, 40) or "ready",
            version=prior.version + 1,
            updated_at=ts,
        )
        self._memory[state.session_id] = state
        if self.atomic_store is not None:
            try:
                key = self._key(state.session_id)
                for _ in range(3):
                    record = self.atomic_store.ensure(key, prior.to_dict())
                    committed = self.atomic_store.compare_and_swap(
                        key,
                        expected_revision=record.revision,
                        payload=state.to_dict(),
                    )
                    if committed is not None:
                        break
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[agent-disclosure] durable commit degraded: %s", exc)
        return state

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["DisclosureArcLedger", "DisclosureArcState"]
