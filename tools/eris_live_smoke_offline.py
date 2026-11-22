# -*- coding: utf-8 -*-
"""Chạy: PYTHONPATH=src python tools/eris_live_smoke_offline.py
Không có TikTok, LLM, OBS hay token request.
"""
from __future__ import annotations
import time
from types import SimpleNamespace
from runtime.live.contracts import LiveEvent
from runtime.live.intake import BoundedLiveIntake
from runtime.live.batcher import LiveBatcher

now = time.time()
queue = BoundedLiveIntake(capacity=64)
for i in range(1000):
    queue.offer(LiveEvent(str(i), 'offline', 1, 'comment', now,
                          'mockviewer', 'mockviewer', f'comment {i}'))
print('[Eris Live offline] Bounded queue:', queue.depth, '/64',
      '| overflow:', queue.counters.overflow)
queue.clear()
events = [LiveEvent(str(i), 'offline', 1, 'gift', now, 'viewer', 'viewer',
                    gift_id='rose', count=count, streaking=streaking)
          for i, (count, streaking) in enumerate(
              [(1, True), (5, True), (20, True), (50, True), (50, False)])]
for event in events:
    queue.offer(event)
batch = LiveBatcher().build(queue.drain())
print('[Eris Live offline] Gift streak expected 50 ->', batch.gifts)
print('[Eris Live offline] Succeeded. No model/provider calls were made.')
