"""Cơ học gộp live events; không quyết định ai xứng đáng được trả lời."""
from __future__ import annotations
import time
from .contracts import LiveBatch, LiveEvent

class LiveBatcher:
    def __init__(self, *, max_comments: int = 12, max_gifts: int = 12) -> None:
        self.max_comments = max(1, min(30, max_comments))
        self.max_gifts = max(1, min(30, max_gifts))
        self._streaks: dict[tuple[str, str], tuple[int, float, str]] = {}
        self._recent_comments: dict[tuple[str, str], float] = {}

    def reset(self) -> None:
        self._streaks.clear()
        self._recent_comments.clear()

    def build(self, events: list[LiveEvent], *, now: float | None = None) -> LiveBatch | None:
        if not events:
            return None
        now = time.time() if now is None else now
        # Cả batch cùng room/epoch. Không ghép hai phòng khi connector reconnect.
        room_id, epoch = events[-1].room_id, events[-1].room_epoch
        comments: list[dict] = []
        gifts: list[dict] = []
        likes, follows = 0, 0
        for event in events:
            if (event.room_id, event.room_epoch) != (room_id, epoch):
                continue
            if event.kind == 'comment':
                if not event.text:
                    continue
                key = (event.viewer_id, event.text.casefold())
                last = self._recent_comments.get(key)
                if last is not None and event.occurred_at - last < 6.0:
                    continue
                self._recent_comments[key] = event.occurred_at
                comments.append({'viewer': event.viewer_name or event.viewer_id,
                                 'text': event.text})
                if len(comments) > self.max_comments:
                    comments.pop(0)
            elif event.kind == 'like':
                likes += max(1, event.count)
            elif event.kind == 'follow':
                follows += 1
            elif event.kind == 'gift':
                key = (event.viewer_id, event.gift_id)
                if event.streaking is True:
                    old = self._streaks.get(key)
                    if old is None or event.count >= old[0]:
                        self._streaks[key] = (event.count, now, event.viewer_name)
                    continue
                # TikTok sends cumulative repeat_count for streak gifts; final
                # count is a snapshot, NOT the sum of all intermediate events.
                pending = self._streaks.pop(key, None)
                count = max(event.count, pending[0] if pending is not None else 0)
                gifts.append({'viewer': event.viewer_name or event.viewer_id,
                              'gift': event.gift_id, 'count': count})
                if len(gifts) > self.max_gifts:
                    gifts.pop(0)
        # Streak mất packet kết thúc được bỏ sau timeout thay vì bịa totals.
        self._streaks = {key: value for key, value in self._streaks.items()
                         if now - value[1] < 60.0}
        if len(self._recent_comments) > 2048:
            self._recent_comments = {k: v for k, v in self._recent_comments.items()
                                     if now - v < 6.0}
        return LiveBatch(room_id=room_id, room_epoch=epoch, emitted_at=now,
                         comments=tuple(comments), gifts=tuple(gifts),
                         likes=likes, follows=follows, received=len(events))
