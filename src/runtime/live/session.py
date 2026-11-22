"""Lịch sử công khai ở RAM; KHÔNG đọc/ghi chat_history, diary hoặc owner memory."""
from __future__ import annotations
from dataclasses import dataclass, field
from threading import RLock
from hashlib import blake2s

@dataclass(slots=True)
class LiveSession:
    room_id: str
    epoch: int
    _history: list[dict] = field(default_factory=list)
    _pending: dict[str, str] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    @property
    def session_id(self) -> str:
        opaque = blake2s(self.room_id.encode('utf-8'), digest_size=12).hexdigest()
        return f'public_live:{opaque}:{self.epoch}'

    def history(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(dict(x) for x in self._history[-24:])

    def add_observation(self, text: str) -> None:
        with self._lock:
            self._history.append({'role': 'user', 'content': str(text)[:1300], 'kind': 'live_snapshot'})
            self._history = self._history[-48:]

    def accepted(self, delivery_id: str, text: str) -> None:
        with self._lock:
            self._pending[delivery_id] = str(text)[:1200]
            if len(self._pending) > 64:
                self._pending.pop(next(iter(self._pending)))

    def finish(self, delivery_id: str, *, delivered: bool) -> None:
        with self._lock:
            text = self._pending.pop(delivery_id, None)
            if delivered and text:
                self._history.append({'role': 'assistant', 'content': text,
                                      'delivery_id': delivery_id, 'delivery_status': 'delivered'})
                self._history = self._history[-48:]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._pending.clear()
