# -*- coding: utf-8 -*-
"""Conversation Trajectory V75 cho ERIS.

Module này giữ *quỹ đạo chủ đề* giữa chat công khai, seed worker và autonomous
cognition. Nó cố ý tách ba thứ vốn rất dễ bị trộn lẫn:

1. pending_question: ERIS đang chờ user trả lời một câu hỏi cụ thể hay không;
2. topic trajectory: semantic spine đang sống, kể cả sau khi câu hỏi đã được trả lời;
3. development policy: autonomous nên HOLD/DEEPEN/CONNECT/BRANCH hay thật sự SHIFT.

Điểm chính của V75: một user turn mới sẽ giải quyết pending question cũ nhưng KHÔNG
xóa chủ đề. Nhờ vậy state không còn giữ kiểu open-loop "user may respond..." sau
khi user đã trả lời, trong khi seed/autonomous vẫn có một anchor để tiếp tục đào sâu.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import re
import time
from typing import Any, Mapping, Sequence


TRAJECTORY_SCHEMA = "eris.conversation_trajectory.v75"
_ALLOWED_DEVELOPMENT = {"hold", "deepen", "connect", "branch", "shift"}


def _compact(value: Any, limit: int = 520) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(0.0, min(1.0, number))


def _tokens(text: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\u00c0-\u024f\u1e00-\u1eff]+", str(text or "").casefold())
        if len(token) >= 3
    }


def _similarity(left: Any, right: Any) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _topic_id(text: str, *, salt: Any = "") -> str:
    raw = f"{_compact(text, 1200)}|{salt}|{time.time_ns()}"
    return "topic_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


_EXPLICIT_SHIFT_RE = re.compile(
    r"(?:\b(?:đổi|chuyển)\s+(?:chủ đề|đề tài|chuyện|cái khác)\b"
    r"|\b(?:nói|bàn)\s+(?:chuyện|cái|chủ đề)\s+khác\b"
    r"|\b(?:change|switch)\s+(?:the\s+)?topic\b|\bmove\s+on\b)",
    re.IGNORECASE,
)

_EXPLICIT_CLOSE_RE = re.compile(
    r"(?:\b(?:bỏ|cho qua|khép|dừng|thôi)\s+(?:qua\s+)?(?:vụ|chuyện|chủ đề|cái)?\s*(?:này|đó|ấy)?\b"
    r"|\bđừng nhắc(?: lại)? nữa\b|\bkhông bàn(?: nữa)?\b|\blet(?:'s| us)\s+(?:leave|drop)\s+(?:that|it)\b)",
    re.IGNORECASE,
)

_CONTINUATION_CUES = (
    "câu đó", "câu này", "lúc nãy", "vừa nãy", "ý đó", "ý này", "vậy", "thế",
    "sao em", "sao bạn", "còn em", "còn bạn", "nếu vậy", "như vậy", "ý em",
    "that question", "what you said", "you said", "then what", "in that case",
)

_QUESTION_ACTS = {
    "user_probe", "ask_genuine_question", "casual_curiosity", "followup_reminder",
    "relationship_continuity_bid", "contextual_question", "question",
}

_SHIFT_ACTS = {"independent_topic_shift", "topic_shift", "shift_topic"}


@dataclass(frozen=True, slots=True)
class ConversationTrajectory:
    revision: int = 0
    updated_at: float = 0.0
    topic_id: str = ""
    root_focus: str = ""
    current_focus: str = ""
    parent_focuses: tuple[str, ...] = ()
    last_user_text: str = ""
    last_assistant_text: str = ""
    last_user_turn_ref: str = ""
    last_assistant_turn_ref: str = ""
    last_user_turn_index: int = 0
    last_assistant_turn_index: int = 0
    depth: int = 0
    momentum: float = 0.0
    user_engagement: float = 0.0
    active: bool = False
    closed: bool = False
    development_mode: str = "hold"
    pending_question_id: str = ""
    pending_question_text: str = ""
    pending_question_turn_index: int = 0
    awaiting_user_answer: bool = False
    last_resolved_question_id: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TRAJECTORY_SCHEMA,
            "revision": int(self.revision),
            "updated_at": float(self.updated_at),
            "topic_id": self.topic_id,
            "root_focus": _compact(self.root_focus, 520),
            "current_focus": _compact(self.current_focus, 720),
            "parent_focuses": [_compact(item, 360) for item in self.parent_focuses[-6:]],
            "last_user_text": _compact(self.last_user_text, 720),
            "last_assistant_text": _compact(self.last_assistant_text, 900),
            "last_user_turn_ref": self.last_user_turn_ref,
            "last_assistant_turn_ref": self.last_assistant_turn_ref,
            "last_user_turn_index": int(self.last_user_turn_index),
            "last_assistant_turn_index": int(self.last_assistant_turn_index),
            "depth": int(self.depth),
            "momentum": round(_clamp01(self.momentum), 4),
            "user_engagement": round(_clamp01(self.user_engagement), 4),
            "active": bool(self.active),
            "closed": bool(self.closed),
            "development_mode": self.development_mode if self.development_mode in _ALLOWED_DEVELOPMENT else "hold",
            "pending_question_id": self.pending_question_id,
            "pending_question_text": _compact(self.pending_question_text, 520),
            "pending_question_turn_index": int(self.pending_question_turn_index),
            "awaiting_user_answer": bool(self.awaiting_user_answer),
            "last_resolved_question_id": self.last_resolved_question_id,
            "source_refs": list(self.source_refs[-12:]),
        }

    def seed_context(self) -> dict[str, Any]:
        """Projection nhỏ cho associative worker, không phải prompt public."""
        if not self.active or self.closed or not self.topic_id or not self.current_focus:
            return {}
        return {
            "schema": TRAJECTORY_SCHEMA,
            "revision": int(self.revision),
            "active": bool(self.active),
            "closed": bool(self.closed),
            "topic_id": self.topic_id,
            "root_focus": _compact(self.root_focus, 420),
            "current_focus": _compact(self.current_focus, 620),
            "parent_focuses": [_compact(item, 280) for item in self.parent_focuses[-4:]],
            "last_assistant_extension": _compact(self.last_assistant_text, 520),
            "depth": int(self.depth),
            "momentum": round(_clamp01(self.momentum), 4),
            "user_engagement": round(_clamp01(self.user_engagement), 4),
            "development_mode": self.development_mode,
            "awaiting_user_answer": bool(self.awaiting_user_answer),
            "pending_question_id": self.pending_question_id,
            "source_refs": list(self.source_refs[-10:]),
            "rule": (
                "Develop this same semantic spine. Prefer deepen/connect/branch over unrelated novelty. "
                "Do not treat ERIS public wording as factual evidence."
            ),
        }


class ConversationTrajectoryRuntime:
    """Session-local topic trajectory shared by chat, seed and autonomous lanes."""

    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self._state = ConversationTrajectory(updated_at=time.time())

    def snapshot(self, *, now: float | None = None) -> ConversationTrajectory:
        current = float(now if now is not None else time.time())
        state = self._state
        if not state.active or state.closed:
            return state
        age = max(0.0, current - state.updated_at)
        # Chủ đề không chết ngay chỉ vì có một khoảng im lặng. Momentum giảm chậm,
        # đủ để autonomous còn tiếp tục suy nghĩ vài phút nhưng không bám cả buổi.
        decay = 0.5 ** (age / 420.0)
        momentum = _clamp01(state.momentum * decay)
        if abs(momentum - state.momentum) > 0.015:
            state = replace(state, momentum=momentum)
            self._state = state
        return state

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot().to_dict()

    def seed_context(self) -> dict[str, Any]:
        return self.snapshot().seed_context()

    def prime_from_history(
        self,
        recent_history: Sequence[Mapping[str, Any]],
        *,
        now: float | None = None,
    ) -> ConversationTrajectory:
        current = float(now if now is not None else time.time())
        user_turns = []
        assistant_turns = []
        for item in recent_history[-10:]:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role", "") or "").casefold()
            text = _compact(item.get("content", item.get("text", "")), 900)
            if not text:
                continue
            if role in {"user", "human"}:
                user_turns.append(text)
            elif role == "assistant":
                assistant_turns.append(text)
        if not user_turns:
            return self._state
        latest = user_turns[-1]
        root = user_turns[max(0, len(user_turns) - 3)]
        self._state = ConversationTrajectory(
            revision=self._state.revision + 1,
            updated_at=current,
            topic_id=_topic_id(root, salt="startup"),
            root_focus=root,
            current_focus=latest,
            parent_focuses=tuple(user_turns[-4:-1]),
            last_user_text=latest,
            last_assistant_text=assistant_turns[-1] if assistant_turns else "",
            depth=max(0, len(user_turns[-4:]) - 1),
            momentum=0.56,
            user_engagement=0.58,
            active=True,
            closed=False,
            development_mode="connect" if len(user_turns) > 1 else "deepen",
            source_refs=("startup:trajectory_prime",),
        )
        self._log("startup_prime")
        return self._state

    def observe_user_turn(
        self,
        user_text: Any,
        *,
        turn_ref: str = "",
        turn_index: int = 0,
        previous_assistant_text: Any = "",
        now: float | None = None,
    ) -> ConversationTrajectory:
        current = float(now if now is not None else time.time())
        text = _compact(user_text, 1000)
        if not text:
            return self._state
        prior = self.snapshot(now=current)
        previous = _compact(previous_assistant_text or prior.last_assistant_text, 1000)
        explicit_close = bool(_EXPLICIT_CLOSE_RE.search(text))
        explicit_shift = bool(_EXPLICIT_SHIFT_RE.search(text))

        resolved_id = prior.pending_question_id if prior.awaiting_user_answer else prior.last_resolved_question_id
        refs = list(prior.source_refs)
        if turn_ref:
            refs.append(str(turn_ref))

        if explicit_close:
            self._state = replace(
                prior,
                revision=prior.revision + 1,
                updated_at=current,
                last_user_text=text,
                last_user_turn_ref=str(turn_ref or ""),
                last_user_turn_index=max(0, int(turn_index or 0)),
                current_focus=text,
                momentum=0.08,
                active=False,
                closed=True,
                development_mode="hold",
                awaiting_user_answer=False,
                pending_question_id="",
                pending_question_text="",
                pending_question_turn_index=0,
                last_resolved_question_id=resolved_id,
                source_refs=tuple(dict.fromkeys(refs))[-12:],
            )
            self._log("user_close")
            return self._state

        if explicit_shift or not prior.active or prior.closed or not prior.topic_id:
            topic_id = _topic_id(text, salt=turn_ref or turn_index)
            root = text
            parents: tuple[str, ...] = ()
            depth = 0
            mode = "deepen"
            momentum = 0.70
        else:
            topic_id = prior.topic_id
            root = prior.root_focus or text
            continuity = max(
                _similarity(text, prior.current_focus),
                _similarity(text, previous),
                0.62 if any(cue in text.casefold() for cue in _CONTINUATION_CUES) else 0.0,
            )
            # Low lexical overlap is often a legitimate semantic branch. Keep one
            # topic_id unless user explicitly shifts; branch is precisely what lets
            # "habit -> self -> continuity of identity" remain one conversation arc.
            mode = "deepen" if continuity >= 0.22 else "branch"
            parents_list = [*prior.parent_focuses]
            if prior.current_focus and prior.current_focus != text:
                parents_list.append(prior.current_focus)
            parents = tuple(dict.fromkeys(item for item in parents_list if item))[-6:]
            depth = min(12, prior.depth + (1 if text != prior.current_focus else 0))
            momentum = _clamp01(max(0.58, prior.momentum * 0.90) + 0.10 + 0.10 * continuity)

        engagement = _clamp01(
            0.48
            + min(0.24, len(_tokens(text)) / 70.0)
            + (0.10 if "?" in text else 0.0)
            + (0.08 if prior.awaiting_user_answer else 0.0)
        )
        self._state = ConversationTrajectory(
            revision=prior.revision + 1,
            updated_at=current,
            topic_id=topic_id,
            root_focus=root,
            current_focus=text,
            parent_focuses=parents,
            last_user_text=text,
            last_assistant_text=previous or prior.last_assistant_text,
            last_user_turn_ref=str(turn_ref or ""),
            last_assistant_turn_ref=prior.last_assistant_turn_ref,
            last_user_turn_index=max(0, int(turn_index or 0)),
            last_assistant_turn_index=prior.last_assistant_turn_index,
            depth=depth,
            momentum=momentum,
            user_engagement=engagement,
            active=True,
            closed=False,
            development_mode=mode,
            pending_question_id="",
            pending_question_text="",
            pending_question_turn_index=0,
            awaiting_user_answer=False,
            last_resolved_question_id=resolved_id,
            source_refs=tuple(dict.fromkeys(refs))[-12:],
        )
        self._log("user_turn")
        return self._state

    def observe_assistant_commit(
        self,
        assistant_text: Any,
        *,
        turn_ref: str = "",
        turn_index: int = 0,
        speech_act: str = "",
        now: float | None = None,
    ) -> ConversationTrajectory:
        current = float(now if now is not None else time.time())
        text = _compact(assistant_text, 1200)
        if not text:
            return self._state
        prior = self.snapshot(now=current)
        act = str(speech_act or "").strip().casefold()
        asks = bool("?" in text or act in _QUESTION_ACTS)
        shifts = bool(act in _SHIFT_ACTS or _EXPLICIT_SHIFT_RE.search(text))
        refs = list(prior.source_refs)
        if turn_ref:
            refs.append(str(turn_ref))

        if shifts and prior.active:
            parents = tuple(dict.fromkeys((*prior.parent_focuses, prior.current_focus)))[-6:]
            next_mode = "branch"
            next_momentum = max(0.44, prior.momentum * 0.72)
        else:
            parents = prior.parent_focuses
            next_mode = "connect" if prior.active else "hold"
            next_momentum = _clamp01(max(prior.momentum, 0.42) + (0.04 if prior.active else 0.0))

        qid = ""
        if asks:
            qid = f"question:{turn_ref or turn_index or prior.revision + 1}"
        self._state = replace(
            prior,
            revision=prior.revision + 1,
            updated_at=current,
            last_assistant_text=text,
            last_assistant_turn_ref=str(turn_ref or ""),
            last_assistant_turn_index=max(0, int(turn_index or 0)),
            parent_focuses=parents,
            momentum=next_momentum,
            development_mode=next_mode,
            pending_question_id=qid,
            pending_question_text=text if asks else "",
            pending_question_turn_index=max(0, int(turn_index or 0)) if asks else 0,
            awaiting_user_answer=asks,
            source_refs=tuple(dict.fromkeys(refs))[-12:],
        )
        self._log("assistant_commit")
        return self._state

    def _log(self, reason: str) -> None:
        fn = getattr(self.logger, "info", None) if self.logger is not None else None
        if not callable(fn):
            return
        state = self._state
        try:
            fn(
                "[conversation trajectory v75] reason=%s rev=%s topic=%s depth=%s momentum=%.2f mode=%s awaiting=%s focus=%s",
                reason,
                state.revision,
                state.topic_id or "none",
                state.depth,
                state.momentum,
                state.development_mode,
                int(state.awaiting_user_answer),
                _compact(state.current_focus, 120) or "none",
            )
        except Exception:
            pass


def ensure_conversation_trajectory_runtime(host: Any) -> ConversationTrajectoryRuntime:
    runtime = getattr(host, "conversation_trajectory_runtime", None)
    if isinstance(runtime, ConversationTrajectoryRuntime):
        return runtime
    runtime = ConversationTrajectoryRuntime(logger=getattr(host, "logger", None))
    setattr(host, "conversation_trajectory_runtime", runtime)
    return runtime


__all__ = [
    "TRAJECTORY_SCHEMA",
    "ConversationTrajectory",
    "ConversationTrajectoryRuntime",
    "ensure_conversation_trajectory_runtime",
]
