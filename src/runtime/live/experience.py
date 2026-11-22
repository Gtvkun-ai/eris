"""P3 tối thiểu: evidence sau audio_done, không thưởng/phạt theo quà.

Chỉ nhớ thống kê tổng hợp trong RAM; không lưu viewer identity hoặc raw chat.
Đây không phải bộ điều khiển persona, không tự chỉnh Identity/Affect.
"""
from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
import time
from .contracts import LiveBatch

@dataclass(slots=True)
class LiveReactionWindow:
    delivery_id: str
    delivered_at: float
    comments_after: int = 0
    likes_after: int = 0
    gift_events_after: int = 0
    follows_after: int = 0

class LiveExperienceLedger:
    def __init__(self, *, window_seconds: float = 30.0) -> None:
        self.window_seconds = max(5.0, min(120.0, float(window_seconds)))
        self._lock = RLock()
        self._recent: list[LiveReactionWindow] = []

    def clear(self) -> None:
        with self._lock:
            self._recent.clear()

    def delivered(self, did: str, *, now: float | None = None) -> None:
        if not did:
            return
        when = time.time() if now is None else float(now)
        with self._lock:
            if any(x.delivery_id == did for x in self._recent):
                return
            self._recent.append(LiveReactionWindow(did, when))
            self._recent = self._recent[-16:]

    def observe_batch(self, batch: LiveBatch) -> None:
        with self._lock:
            candidates = [x for x in self._recent
                          if 0 <= batch.emitted_at - x.delivered_at <= self.window_seconds]
            if not candidates:
                return
            # Chỉ ghi vào lời gần nhất. Không khẳng định reaction là do câu nói.
            target = candidates[-1]
            target.comments_after += len(batch.comments)
            target.likes_after += max(0, batch.likes)
            target.gift_events_after += len(batch.gifts)
            target.follows_after += max(0, batch.follows)

    def public_summary(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple({
                'comments_after': x.comments_after,
                'likes_after': x.likes_after,
                'gift_events_after': x.gift_events_after,
                'follows_after': x.follows_after,
                'note': 'observed_after_delivery_not_proven_causal_feedback',
            } for x in self._recent[-3:])
