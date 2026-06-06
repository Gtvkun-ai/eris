# -*- coding: utf-8 -*-
"""Base contract cho các subconscious worker Phase sau.

Phase 0 chưa triển khai 15 worker. File này chỉ cung cấp lớp nền để Phase 1+
không mỗi worker tự chế một kiểu output. Một contract nhỏ hôm nay cứu được nhiều
file `if hasattr(...)` ngày mai. Loài người gọi đó là tiến bộ, hoặc ít nhất là
bớt tự hại.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from .thought_fragment import ThoughtFragment


@dataclass(slots=True, frozen=True)
class WorkerContext:
    """Context tối thiểu worker được phép nhìn.

    Phase sau có thể mở rộng, nhưng nên giữ nguyên nguyên tắc: worker đọc context
    đã chọn lọc, không tự bốc toàn bộ runtime raw state.
    """

    frame: Any = None
    snapshot: Any = None
    memory_packet: Any = None
    relation: Any = None
    internal_state: Any = None
    now: float = 0.0


class SubconsciousWorker(Protocol):
    """Interface tối thiểu cho worker nền."""

    name: str

    def run(self, context: WorkerContext) -> Iterable[ThoughtFragment | Mapping[str, Any]]:
        """Trả các ThoughtFragment hoặc dict có thể convert thành ThoughtFragment."""


class RuleBasedWorker:
    """Base class tiện dụng cho worker deterministic.

    Worker con chỉ cần override `build_fragments`. Base này đảm bảo output luôn là
    tuple, giúp loop xử lý đồng nhất.
    """

    name = "rule_based_worker"

    def run(self, context: WorkerContext) -> tuple[ThoughtFragment | Mapping[str, Any], ...]:
        return tuple(self.build_fragments(context) or ())

    def build_fragments(self, context: WorkerContext) -> Iterable[ThoughtFragment | Mapping[str, Any]]:
        return ()
