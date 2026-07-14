# -*- coding: utf-8 -*-
"""Đối tượng kết quả duy nhất của DirectorGenerationPipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from domain import Decision
from runtime.director_context import DirectorContext
from runtime.performance_contract import DirectorContract, PerformanceContext
from runtime.stage_scorer import CandidateUtterance, StageScore
from runtime.director_trace import DirectorTrace


@dataclass(frozen=True, slots=True)
class FinalDecision:
    """Snapshot bất biến của quyết định cuối trước commit.

    Từ thời điểm đối tượng này được tạo, nội dung public đã qua candidate
    selection, authority gate, scorer và repair. Coordinator chỉ còn việc commit
    rồi phát, không tổ chức thêm một cuộc họp chấm điểm ở cửa sau.
    """

    decision: Decision
    director_context: DirectorContext
    performance_context: PerformanceContext
    director_contract: DirectorContract
    selected_candidate: CandidateUtterance
    stage_score: StageScore
    repair_payload: Mapping[str, Any]
    trace: DirectorTrace

    def to_decision(self) -> Decision:
        """Trả một bản copy để caller không sửa snapshot nằm trong trace."""

        copied = replace(self.decision)
        copied.director_meta = dict(self.decision.director_meta or {})
        return copied

    def compact_meta(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace.trace_id,
            "director": self.director_context.compact_payload(),
            "performance_context": self.performance_context.to_payload(),
            "director_contract": self.director_contract.to_payload(),
            "selected_candidate": self.selected_candidate.to_payload(),
            "stage_score": self.stage_score.to_payload(),
            "scene_repair": dict(self.repair_payload),
        }


__all__ = ["FinalDecision"]
