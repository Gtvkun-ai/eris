"""Epoch lease: stop/reconnect hủy hiệu lực kết quả Root cũ."""
from __future__ import annotations
from threading import RLock

class LiveLifecycle:
    def __init__(self) -> None:
        self._lock = RLock()
        self._epoch = 0
        self._room = ''
        self._active = False

    def start(self, room_id: str) -> int:
        room = str(room_id or '').strip()[:80]
        if not room:
            raise ValueError('live_room_required')
        with self._lock:
            self._epoch += 1
            self._room = room
            self._active = True
            return self._epoch

    def stop(self) -> int:
        with self._lock:
            self._epoch += 1
            self._active = False
            self._room = ''
            return self._epoch

    def valid(self, room: str, epoch: int) -> bool:
        with self._lock:
            return self._active and self._room == room and self._epoch == epoch

    def snapshot(self) -> tuple[str, int, bool]:
        with self._lock:
            return self._room, self._epoch, self._active
