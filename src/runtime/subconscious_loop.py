# -*- coding: utf-8 -*-
"""Runtime adapter cho subconscious blackboard/synthesizer.

Phase 0 dựng ThoughtFragment/Blackboard/Synthesizer.
Phase 1-4 thêm worker nội tâm nền.
Phase 5 thêm MetaAudit có quyền dọn Blackboard.
Phase 6 thêm BeliefMutation proposal + commit gate có rollback.
Phase 7 thêm ShadowAccumulator chạy sau synthesis và vẫn phải qua audit.

File này vẫn chưa cắm sâu vào coordinator. Nó là adapter an toàn để test từng phase
trước khi nối vào wake/presence pipeline. Làm khác đi thì nhanh hơn khoảng 20 phút
và mất 2 ngày debug, một giao dịch rất loài người.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from cortex.subconscious import (
    ConsciousSynthesizer,
    SubconsciousBlackboard,
    ThoughtFragment,
    ThoughtObject,
    WorkerContext,
)
from cortex.subconscious.worker_base import SubconsciousWorker
from cortex.subconscious.thought_fragment import now_timestamp


@dataclass(slots=True, frozen=True)
class SubconsciousTickResult:
    """Kết quả một tick subconscious."""

    submitted_count: int
    expired_ids: tuple[str, ...]
    thought_object: ThoughtObject | None
    surface_seed: dict[str, object] | None
    audit_report: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "submitted_count": int(self.submitted_count),
            "expired_ids": list(self.expired_ids),
            "thought_object": self.thought_object.to_dict() if self.thought_object else None,
            "surface_seed": self.surface_seed,
            "audit_report": self.audit_report,
        }


class SubconsciousLoop:
    """Vòng nền tối thiểu cho worker subconscious.

    Loop này không tự quyết định nói. Nó sinh `ThoughtObject`, `surface_seed`, và
    `audit_report`. SurfaceArbiter/Permission/SpeechCore vẫn là cổng public. Có
    áp lực nội tâm không đồng nghĩa được quyền nói. Một nguyên tắc kỳ lạ nhưng hữu
    ích, ước gì group chat cũng có.
    """

    def __init__(
        self,
        *,
        blackboard: SubconsciousBlackboard | None = None,
        synthesizer: ConsciousSynthesizer | None = None,
        workers: Iterable[SubconsciousWorker] = (),
    ) -> None:
        self.blackboard = blackboard or SubconsciousBlackboard()
        self.synthesizer = synthesizer or ConsciousSynthesizer()
        self.workers = tuple(workers or ())
        self.last_tick = SubconsciousTickResult(
            submitted_count=0,
            expired_ids=(),
            thought_object=None,
            surface_seed=None,
            audit_report=None,
        )
        self.subconscious_report: dict[str, object] | None = None
        self.subconscious_seed: dict[str, object] | None = None
        self.audit_report: dict[str, object] | None = None

    def submit(self, fragment: ThoughtFragment | Mapping[str, Any]) -> ThoughtFragment:
        """Submit thủ công một fragment vào Blackboard."""

        return self.blackboard.submit(fragment)

    def tick(
        self,
        *,
        frame: Any = None,
        snapshot: Any = None,
        memory_packet: Any = None,
        relation: Any = None,
        internal_state: Any = None,
        now: float | None = None,
    ) -> SubconsciousTickResult:
        """Chạy một lượt worker -> audit -> synthesizer -> post-worker -> audit."""

        current = now_timestamp() if now is None else float(now)
        context = WorkerContext(
            frame=frame,
            snapshot=snapshot,
            memory_packet=memory_packet,
            relation=relation,
            internal_state=internal_state,
            audit_report=self.audit_report,
            now=current,
        )
        submitted = self._run_workers(context, after_synthesis=False)

        expired = self.blackboard.decay(now=current)
        audit_report = self._run_audit_workers(
            self._context_with_snapshot(
                frame=frame,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                thought_object=None,
                audit_report=self.audit_report,
                now=current,
            )
        )
        self.audit_report = audit_report or self.audit_report

        thought_object = self.synthesizer.synthesize_from_blackboard(self.blackboard, now=current)

        # Phase 2/7: một số worker, đặc biệt RehearsalAgent và ShadowAccumulator,
        # cần ThoughtObject đã qua cổ chai + snapshot Blackboard. Chạy chúng sau
        # synthesis rồi audit lại trước khi synthesize lần cuối.
        if thought_object is not None:
            post_context = self._context_with_snapshot(
                frame=frame,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                thought_object=thought_object,
                audit_report=self.audit_report,
                now=current,
            )
            post_submitted = self._run_workers(post_context, after_synthesis=True)
            submitted += post_submitted
            if post_submitted:
                post_audit_report = self._run_audit_workers(
                    self._context_with_snapshot(
                        frame=frame,
                        snapshot=snapshot,
                        memory_packet=memory_packet,
                        relation=relation,
                        internal_state=internal_state,
                        thought_object=thought_object,
                        audit_report=self.audit_report,
                        now=current,
                    )
                )
                self.audit_report = post_audit_report or self.audit_report
                thought_object = self.synthesizer.synthesize_from_blackboard(self.blackboard, now=current)

        surface_seed = thought_object.to_surface_seed() if thought_object and thought_object.should_surface else None
        self.subconscious_seed = surface_seed
        self.subconscious_report = self.synthesizer.last_report.to_dict()
        self.last_tick = SubconsciousTickResult(
            submitted_count=submitted,
            expired_ids=expired,
            thought_object=thought_object,
            surface_seed=surface_seed,
            audit_report=self.audit_report,
        )
        return self.last_tick

    def _context_with_snapshot(
        self,
        *,
        frame: Any,
        snapshot: Any,
        memory_packet: Any,
        relation: Any,
        internal_state: Any,
        thought_object: Any,
        audit_report: Any,
        now: float,
    ) -> WorkerContext:
        """Tạo WorkerContext có snapshot Blackboard bất biến."""

        return WorkerContext(
            frame=frame,
            snapshot=snapshot,
            memory_packet=memory_packet,
            relation=relation,
            internal_state=internal_state,
            thought_object=thought_object,
            blackboard_snapshot=self.blackboard.snapshot(now=now),
            audit_report=audit_report,
            now=now,
        )

    def _run_workers(self, context: WorkerContext, *, after_synthesis: bool) -> int:
        """Chạy nhóm worker phù hợp với pass hiện tại và submit fragment.

        Worker lỗi bị cô lập. MetaAudit sẽ bắt rác nhận thức, còn loop runtime không
        nên chết vì một worker bẩn. Đó là lý tưởng thấp, nhưng chạy được.
        """

        submitted = 0
        for worker in self.workers:
            if bool(getattr(worker, "audit_blackboard_worker", False)):
                continue
            wants_post = bool(getattr(worker, "run_after_synthesis", False))
            if wants_post != bool(after_synthesis):
                continue
            try:
                fragments = tuple(worker.run(context) or ())
            except Exception:
                continue
            for fragment in fragments:
                try:
                    self.blackboard.submit(fragment)
                except Exception:
                    continue
                submitted += 1
        return submitted

    def _run_audit_workers(self, context: WorkerContext) -> dict[str, object] | None:
        """Chạy các worker audit có quyền mutate Blackboard."""

        merged: dict[str, object] | None = None
        for worker in self.workers:
            if not bool(getattr(worker, "audit_blackboard_worker", False)):
                continue
            audit = getattr(worker, "audit_blackboard", None)
            if not callable(audit):
                continue
            try:
                result = audit(self.blackboard, context.blackboard_snapshot, context)
            except Exception:
                continue
            to_dict = getattr(result, "to_dict", None)
            payload = to_dict() if callable(to_dict) else result
            if isinstance(payload, dict):
                merged = payload if merged is None else {**merged, **payload}
        return merged
