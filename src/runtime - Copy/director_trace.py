# -*- coding: utf-8 -*-
"""Trace có cấu trúc cho pipeline Director.

Mục tiêu của file này không phải dựng thêm một hệ logging thần bí. Nó gom
những dữ kiện cần để trả lời câu hỏi rất thực dụng: model đã sinh bao nhiêu
candidate, câu nào được chọn, vì sao bị sửa/chặn, và nội dung cuối có được
commit hay không.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True, slots=True)
class DirectorTrace:
    trace_id: str
    channel: str
    scene_mode: str
    created_at_ms: int = field(default_factory=_now_ms)
    completed_at_ms: int = 0
    candidate_count: int = 0
    selected_candidate: str = ""
    selected_index: int = -1
    authority_result: tuple[str, ...] = ()
    score: Mapping[str, Any] = field(default_factory=dict)
    repair_action: str = "keep"
    generation_latency_ms: int = 0
    finalized_text: str = ""
    should_speak: bool = False
    memory_committed: bool = False
    notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authority_result"] = list(self.authority_result)
        payload["notes"] = list(self.notes)
        payload["score"] = dict(self.score)
        return payload


class DirectorTraceStore:
    """Kho trace ngắn hạn, có thể ghi JSONL nếu runtime bật đường dẫn.

    Store giữ số lượng bản ghi hữu hạn để không biến debug thành một dạng rác
    thải công nghiệp. Ghi file là best-effort; lỗi telemetry không được phép làm
    chết một lượt chat.
    """

    def __init__(self, *, max_items: int = 256, jsonl_path: str | Path | None = None) -> None:
        self.max_items = max(16, int(max_items))
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self._items: dict[str, DirectorTrace] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def put(self, trace: DirectorTrace) -> DirectorTrace:
        with self._lock:
            if trace.trace_id not in self._items:
                self._order.append(trace.trace_id)
            self._items[trace.trace_id] = trace
            while len(self._order) > self.max_items:
                old_id = self._order.pop(0)
                self._items.pop(old_id, None)
        self._append_jsonl(trace)
        return trace

    def get(self, trace_id: str) -> DirectorTrace | None:
        with self._lock:
            return self._items.get(str(trace_id or ""))

    def latest(self) -> DirectorTrace | None:
        with self._lock:
            if not self._order:
                return None
            return self._items.get(self._order[-1])

    def mark_committed(self, trace_id: str, *, memory_committed: bool) -> DirectorTrace | None:
        with self._lock:
            current = self._items.get(str(trace_id or ""))
            if current is None:
                return None
            updated = replace(current, memory_committed=bool(memory_committed))
            self._items[current.trace_id] = updated
        self._append_jsonl(updated)
        return updated

    def _append_jsonl(self, trace: DirectorTrace) -> None:
        if self.jsonl_path is None:
            return
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace.to_payload(), ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            # Telemetry không có quyền làm hỏng hội thoại. Một nguyên tắc rất cơ
            # bản, nhưng phần mềm thường cần được nhắc như trẻ con trước ổ điện.
            return


__all__ = ["DirectorTrace", "DirectorTraceStore"]
