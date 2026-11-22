"""Regression: SDK start() non-blocking used to close asyncio loop prematurely."""
import asyncio
import sys
import threading
import time
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from runtime.live.connector import TikTokLiveConnector

class FakeTikTokClient:
    instances=[]
    def __init__(self,unique_id):
        self.unique_id=unique_id
        self.events={}
        self._ended=None
        self.connected=False
        self.instances.append(self)
    def add_listener(self, t, cb): self.events[t]=cb
    async def connect(self):
        self.connected=True
        await self.events[ConnectEvent](SimpleNamespace())
        self._ended=asyncio.Event()
        await self._ended.wait()
    async def disconnect(self):
        if self._ended: self._ended.set()

class CommentEvent: pass
class GiftEvent: pass
class LikeEvent: pass
class FollowEvent: pass
class ConnectEvent: pass
class DisconnectEvent: pass
class LiveEndEvent: pass

class ConnectorTests(unittest.TestCase):
    def test_client_event_loop_lives_until_disconnect(self):
        fakepkg=types.ModuleType('TikTokLive')
        fakepkg.TikTokLiveClient=FakeTikTokClient
        fakemod=types.ModuleType('TikTokLive.events')
        for cls in [CommentEvent,GiftEvent,LikeEvent,FollowEvent,ConnectEvent,DisconnectEvent,LiveEndEvent]:
            setattr(fakemod,cls.__name__,cls)
        runtime=SimpleNamespace(counters=SimpleNamespace(errors=0), ingest=lambda e,kind: True)
        with patch.dict(sys.modules, {'TikTokLive':fakepkg,'TikTokLive.events':fakemod}):
            c=TikTokLiveConnector(runtime,unique_id='@example')
            c.start()
            for _ in range(100):
                if c.connection_state=='connected':break
                time.sleep(.01)
            self.assertEqual(c.connection_state,'connected')
            self.assertTrue(c._thread.is_alive())
            self.assertEqual(FakeTikTokClient.instances[-1].unique_id,'@example')
            c.stop()
            c._thread.join(timeout=2)
            self.assertFalse(c._thread.is_alive())
            self.assertEqual(c.connection_state,'disconnected')
            self.assertEqual(runtime.counters.errors,0)

if __name__=='__main__':unittest.main()
