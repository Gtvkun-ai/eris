"""TikTokLive transport tuỳ chọn; không gọi LLM hoặc TTS trong event callback.

Các phiên bản TikTokLive khác nhau ở start() (có thể trả Task). Giữ
asyncio loop sống bằng connect() chặn hoặc await returned task, tránh lỗi
asyncio.run(...) đóng loop ngay sau khi vừa kết nối.
"""
from __future__ import annotations
import asyncio
import inspect
import threading
from typing import Any

class TikTokLiveConnector:
    def __init__(self, runtime: Any, *, unique_id: str) -> None:
        self.runtime = runtime
        self.unique_id = unique_id.strip().lstrip('@')
        if not self.unique_id:
            raise ValueError('tiktok_unique_id_required')
        self.connection_state = 'disconnected'
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._halt.clear()
        self.connection_state = 'connecting'
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='ErisTikTokConnector')
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        self.connection_state = 'stopping'
        loop, client = self._loop, self._client
        if loop is not None and loop.is_running() and client is not None:
            disconnect = getattr(client, 'disconnect', None)
            if callable(disconnect):
                try:
                    task = disconnect()
                    if inspect.isawaitable(task):
                        asyncio.run_coroutine_threadsafe(task, loop)
                except RuntimeError:
                    pass

    def _run(self) -> None:
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import (CommentEvent, GiftEvent, LikeEvent,
                                           FollowEvent, ConnectEvent, DisconnectEvent)
            try:
                from TikTokLive.events import LiveEndEvent
            except ImportError:
                LiveEndEvent = None
        except ImportError:
            self.connection_state = 'sdk_missing'
            self.runtime.counters.errors += 1
            return
        delay = 5
        while not self._halt.is_set():
            async def connect() -> None:
                client = TikTokLiveClient(unique_id='@' + self.unique_id)
                self._client = client
                self._loop = asyncio.get_running_loop()
                for event_type, kind in ((CommentEvent, 'comment'), (GiftEvent, 'gift'),
                                         (LikeEvent, 'like'), (FollowEvent, 'follow')):
                    async def handler(event, _kind=kind):
                        if not self._halt.is_set():
                            self.runtime.ingest(event, kind=_kind)
                    client.add_listener(event_type, handler)
                async def on_connected(_event):
                    self.connection_state = 'connected'
                async def on_disconnected(_event):
                    self.connection_state = 'disconnected'
                client.add_listener(ConnectEvent, on_connected)
                client.add_listener(DisconnectEvent, on_disconnected)
                if LiveEndEvent is not None:
                    async def ended(_event):
                        if not self._halt.is_set():
                            self.runtime.ingest({'event_id': 'live-ended'}, kind='room_end')
                            self._halt.set()
                    client.add_listener(LiveEndEvent, ended)
                # connect() là blocking future theo stable library. Không để
                # asyncio.run() đóng loop khi start() chỉ tạo background Task.
                blocking = getattr(client, 'connect', None)
                if callable(blocking):
                    await blocking()
                else:
                    result = await client.start()
                    if inspect.isawaitable(result):
                        await result
            self.connection_state = 'connecting'
            try:
                asyncio.run(connect())
                delay = 5
            except Exception:
                self.connection_state = 'reconnecting'
                self.runtime.counters.errors += 1
            finally:
                self._client, self._loop = None, None
            if self._halt.wait(delay):
                break
            delay = min(60, delay * 2)
        self.connection_state = 'disconnected'

__all__ = ['TikTokLiveConnector']
