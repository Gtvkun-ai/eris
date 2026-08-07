# -*- coding: utf-8 -*-
"""Một vòng deliberation duy nhất cho chat, autonomous và runtime action.

MindLoop là coordinator, không phải một bộ não mới. Subject Core giữ state và luật
nhân quả; Executive chọn/commit; cognitive adapter thực hiện yêu cầu xem lại;
MindLoop chỉ bảo đảm thứ tự, ngân sách và điều kiện dừng. Nhờ đó không còn ba bản
sao của cùng một nghi thức nằm rải trong ingress, runtime và self-turn pipeline.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Callable, Coroutine, Mapping, Protocol

from cortex.subject.contracts import (
    MindDecision,
    SubjectDeliberationFrame,
    SubjectExecutiveCommit,
    WorldObservation,
)
from cortex.subject.deliberation import CognitiveRequestKind
from cortex.subject.service import SubjectService
from runtime.subject_cognition import BoundedSubjectCognition, SubjectCognitionPort


class DeliberationState(StrEnum):
    PREPARED = "prepared"
    REVISED = "revised"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class DeliberationSession:
    session_id: str
    frame: SubjectDeliberationFrame
    state: DeliberationState
    mode: str
    user_text: str
    snapshot: Mapping[str, Any]
    review_count: int = 0
    max_reviews: int = 1

    @property
    def can_review(self) -> bool:
        return self.state in {DeliberationState.PREPARED, DeliberationState.REVISED} and self.review_count < self.max_reviews


class SubjectExecutivePort(Protocol):
    @property
    def enabled(self) -> bool: ...

    def commit_subject_frame(
        self,
        frame: SubjectDeliberationFrame,
        *,
        user_text: str = "",
        snapshot: dict[str, Any] | None = None,
        mode: str = "runtime",
    ) -> SubjectExecutiveCommit | None: ...


class FallbackSubjectExecutive:
    """Executive adapter deterministic dành cho test/caller độc lập.

    Fallback vẫn tạo một commit thật và để authorship ghi đúng source. Nó không
    nằm trong SubjectService, nên production không có cửa finalize thiếu Executive.
    """

    enabled = True

    def __init__(
        self,
        service: SubjectService,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._service = service
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def commit_subject_frame(
        self,
        frame: SubjectDeliberationFrame,
        *,
        user_text: str = "",
        snapshot: dict[str, Any] | None = None,
        mode: str = "runtime",
    ) -> SubjectExecutiveCommit:
        selected = self._service.arbiter.select_default(
            frame.coalitions,
            temperature=self._service.config.default_temperature,
        )
        return SubjectExecutiveCommit(
            commit_id=f"fallback-commit:{self._id_factory()}",
            frame_id=frame.frame_id,
            selected_coalition_id=selected.coalition_id,
            selected_proposal_ref=selected.primary_proposal_ref,
            semantic_commitments=(f"thực hiện coalition đã được chọn cho {mode}",),
            cognitive_requests=(),
            reason="no external Executive was available; deterministic fallback adapter committed",
            confidence=0.0,
            review_conditions=(),
            created_at=self._clock(),
            source="fallback_subject_executive",
        )


class MindLoop:
    """Coordinator duy nhất của một phiên deliberation."""

    def __init__(
        self,
        *,
        subject: SubjectService,
        executive_provider: Callable[[], SubjectExecutivePort | None] | None = None,
        cognition: SubjectCognitionPort | None = None,
        fallback_executive: SubjectExecutivePort | None = None,
        max_reviews: int = 1,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.subject = subject
        self._executive_provider = executive_provider or (lambda: None)
        self._cognition = cognition or BoundedSubjectCognition()
        self._fallback = fallback_executive or FallbackSubjectExecutive(subject)
        self._max_reviews = max(0, int(max_reviews))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def _executive_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Bổ sung self-model dẫn xuất cho Executive mà không sửa frame causal.

        Self-model là một view của cùng Subject Core, không phải evidence mới và
        không được phép tạo coalition/action ngoài frame. Nó giúp Executive biết
        lựa chọn hiện tại nằm ở đâu trong continuity/value/competence của chính Eris.
        """
        payload = dict(snapshot or {})
        self_view = getattr(self.subject, "self_view", None)
        if callable(self_view):
            try:
                candidate = self_view()
                if isinstance(candidate, Mapping):
                    payload["subject_self"] = dict(candidate)
            except Exception:
                pass
        return payload

    def _executive(self, override: SubjectExecutivePort | None = None) -> SubjectExecutivePort:
        candidate = override or self._executive_provider()
        if candidate is not None and bool(getattr(candidate, "enabled", True)):
            return candidate
        return self._fallback

    async def prepare(
        self,
        observation: WorldObservation,
        *,
        mode: str,
        user_text: str = "",
        snapshot: Mapping[str, Any] | None = None,
    ) -> DeliberationSession:
        frame = await self.subject.prepare_deliberation(observation)
        return DeliberationSession(
            session_id=f"mind-loop:{self._id_factory()}",
            frame=frame,
            state=DeliberationState.PREPARED,
            mode=str(mode or "runtime"),
            user_text=str(user_text or ""),
            snapshot=dict(snapshot or {}),
            max_reviews=self._max_reviews,
        )

    async def deliberate(
        self,
        observation: WorldObservation,
        *,
        mode: str,
        user_text: str = "",
        snapshot: Mapping[str, Any] | None = None,
        executive: SubjectExecutivePort | None = None,
    ) -> MindDecision:
        session = await self.prepare(
            observation,
            mode=mode,
            user_text=user_text,
            snapshot=snapshot,
        )
        return await self.complete(session, executive=executive)

    async def complete(
        self,
        session: DeliberationSession,
        *,
        executive: SubjectExecutivePort | None = None,
        initial_commit: SubjectExecutiveCommit | None = None,
        commit_provider: Callable[[SubjectDeliberationFrame, str], SubjectExecutiveCommit | None] | None = None,
    ) -> MindDecision:
        if session.state not in {DeliberationState.PREPARED, DeliberationState.REVISED}:
            raise ValueError(f"cannot complete deliberation from state {session.state}")
        controller = self._executive(executive)
        current = session
        commit = initial_commit

        while True:
            if commit is None:
                step_mode = current.mode if current.review_count == 0 else f"{current.mode}_review"
                if commit_provider is not None:
                    commit = commit_provider(current.frame, step_mode)
                else:
                    commit = controller.commit_subject_frame(
                        current.frame,
                        user_text=current.user_text,
                        snapshot=self._executive_snapshot(current.snapshot),
                        mode=step_mode,
                    )
            if commit is None:
                await self.abandon(current, reason="executive_returned_no_commit")
                raise RuntimeError("Executive did not commit a prepared deliberation frame")

            requests = CognitiveRequestKind.normalize_many(commit.cognitive_requests)
            if requests and current.can_review:
                findings = self._cognition.execute(current.frame, requests)
                revised = await self.subject.integrate_cognitive_results(current.frame, findings)
                current = replace(
                    current,
                    frame=revised,
                    state=DeliberationState.REVISED,
                    review_count=current.review_count + 1,
                )
                commit = None
                continue

            decision = await self.subject.finalize_deliberation(current.frame, commit)
            return decision

    async def abandon(self, session: DeliberationSession, *, reason: str) -> None:
        if session.state in {DeliberationState.COMMITTED, DeliberationState.ABANDONED}:
            return
        await self.subject.abandon_deliberation(session.frame, reason=reason)

    @staticmethod
    def run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
        """Chạy coroutine từ runtime đồng bộ, kể cả khi caller đang có event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: list[Any] = []
        error: list[BaseException] = []

        def worker() -> None:
            try:
                result.append(asyncio.run(coro))
            except BaseException as exc:  # chuyển nguyên lỗi về caller thread
                error.append(exc)

        thread = threading.Thread(target=worker, name="eris-mind-loop", daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result[0]

    def prepare_sync(self, *args: Any, **kwargs: Any) -> DeliberationSession:
        return self.run_sync(self.prepare(*args, **kwargs))

    def deliberate_sync(self, *args: Any, **kwargs: Any) -> MindDecision:
        return self.run_sync(self.deliberate(*args, **kwargs))

    def complete_sync(self, *args: Any, **kwargs: Any) -> MindDecision:
        return self.run_sync(self.complete(*args, **kwargs))

    def abandon_sync(self, *args: Any, **kwargs: Any) -> None:
        self.run_sync(self.abandon(*args, **kwargs))


__all__ = [
    "DeliberationSession",
    "DeliberationState",
    "FallbackSubjectExecutive",
    "MindLoop",
    "SubjectExecutivePort",
]
