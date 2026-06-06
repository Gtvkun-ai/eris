# -*- coding: utf-8 -*-
"""Runtime adapter Phase 0 cho subconscious blackboard/synthesizer.

File này chưa cắm sâu vào coordinator. Nó là một adapter nhỏ để runtime có thể:
1. Nhận fragment từ worker.
2. Decay Blackboard.
3. Chạy Synthesizer.
4. Expose `subconscious_seed` tương thích SurfaceArbiter hiện tại.

Lý do không cắm thẳng vào coordinator trong Phase 0: giảm rủi ro phá wake gate,
presence, thought_stream. Làm móng trước, không dựng tầng 15 rồi ngạc nhiên vì
nhà nghiêng. Nhân loại đã thử nhiều lần, kết quả không đẹp.
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

    def to_dict(self) -> dict[str, object]:
        return {
            "submitted_count": int(self.submitted_count),
            "expired_ids": list(self.expired_ids),
            "thought_object": self.thought_object.to_dict() if self.thought_object else None,
            "surface_seed": self.surface_seed,
        }


class SubconsciousLoop:
    """Vòng nền tối thiểu cho Phase 0.

    Loop này chưa tự quyết định nói. Nó chỉ sinh `ThoughtObject` và surface_seed.
    SurfaceArbiter/Permission/SpeechCore vẫn là cổng public. Nói cách khác: có ý
    nghĩ không đồng nghĩa được quyền nói. Kỳ lạ là điều này cũng áp dụng cho người.
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
        )
        self.subconscious_report: dict[str, object] | None = None
        self.subconscious_seed: dict[str, object] | None = None

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
        """Chạy một lượt worker -> blackboard -> synthesizer."""

        current = now_timestamp() if now is None else float(now)
        context = WorkerContext(
            frame=frame,
            snapshot=snapshot,
            memory_packet=memory_packet,
            relation=relation,
            internal_state=internal_state,
            now=current,
        )
        submitted = self._run_workers(context, after_synthesis=False)

        expired = self.blackboard.decay(now=current)
        thought_object = self.synthesizer.synthesize_from_blackboard(self.blackboard, now=current)

        # Phase 2: một số worker, đặc biệt RehearsalAgent, cần ThoughtObject đã qua
        # cổ chai để mô phỏng say/delay/body_only/store/suppress. Chạy chúng sau
        # synthesis rồi synthesize lại nếu có fragment mới. Không làm vậy thì rehearsal
        # chỉ đang diễn nháp trên không khí, nghe giống họp kiến trúc nhưng ít hữu ích.
        if thought_object is not None:
            post_context = WorkerContext(
                frame=frame,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                thought_object=thought_object,
                now=current,
            )
            post_submitted = self._run_workers(post_context, after_synthesis=True)
            submitted += post_submitted
            if post_submitted:
                thought_object = self.synthesizer.synthesize_from_blackboard(self.blackboard, now=current)

        surface_seed = thought_object.to_surface_seed() if thought_object and thought_object.should_surface else None
        self.subconscious_seed = surface_seed
        self.subconscious_report = self.synthesizer.last_report.to_dict()
        self.last_tick = SubconsciousTickResult(
            submitted_count=submitted,
            expired_ids=expired,
            thought_object=thought_object,
            surface_seed=surface_seed,
        )
        return self.last_tick

    def _run_workers(self, context: WorkerContext, *, after_synthesis: bool) -> int:
        """Chạy nhóm worker phù hợp với pass hiện tại và submit fragment.

        Worker lỗi bị cô lập. Phase 5 MetaAudit có thể ghi lỗi chi tiết hơn; ở đây
        ưu tiên không để một worker bẩn làm rơi toàn bộ runtime.
        """

        submitted = 0
        for worker in self.workers:
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
