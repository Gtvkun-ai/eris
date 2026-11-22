"""P6 offline readiness probe. Không kết nối provider, không gọi LLM/TTS.

Mỗi probe chạy trên object riêng, không chạm vào live session thật.
Đây KHÔNG phải kiểm thử OBS/TikTok ngoài đời.
"""
from __future__ import annotations
import time
from .contracts import LiveCounters, LiveEvent
from .intake import BoundedLiveIntake
from .batcher import LiveBatcher
from .lifecycle import LiveLifecycle


def run_offline_live_validation() -> dict:
    findings: list[dict] = []
    def probe(name: str, action) -> None:
        try:
            action()
            findings.append({'name': name, 'ok': True})
        except Exception as exc:
            findings.append({'name': name, 'ok': False, 'reason': str(exc)[:90]})

    def flood():
        counters = LiveCounters()
        intake = BoundedLiveIntake(capacity=128, ttl_seconds=20, counters=counters)
        now = time.time()
        for n in range(1000):
            intake.offer(LiveEvent(str(n), 'sim', 1, 'comment', now,
                                   'test', 'test', f'comment-{n}'), now=now)
        assert intake.depth <= 128 and counters.overflow == 872
        assert len(intake.drain(now=now)) == 128

    def dedup():
        intake = BoundedLiveIntake()
        now = time.time()
        event = LiveEvent('same', 'sim', 1, 'like', now)
        assert intake.offer(event, now=now)
        assert not intake.offer(event, now=now)
        assert intake.counters.duplicate == 1

    def gift():
        batcher = LiveBatcher()
        now = time.time()
        events = [LiveEvent(f'g{n}', 'sim', 1, 'gift', now,
                            'viewer', 'viewer', '', 'rose', n, n < 50)
                  for n in (1, 5, 20, 50)]
        got = batcher.build(events, now=now)
        assert len(got.gifts) == 1 and got.gifts[0]['count'] == 50

    def lifecycle():
        lc = LiveLifecycle()
        epoch = lc.start('sim')
        assert lc.valid('sim', epoch)
        lc.stop()
        assert not lc.valid('sim', epoch)
        another = lc.start('sim')
        assert another != epoch and not lc.valid('sim', epoch)

    def no_raw_memory():
        from .learning import LiveAggregateLearning
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as d:
            p = Path(d) / 'aggregate.json'
            ledger = LiveAggregateLearning(p, enabled=True)
            ledger.finish({'accepted': 10, 'viewer':'SENSITIVE_CANARY',
                           'raw_chat':'PRIVATE_CANARY'}, duration_s=55)
            raw = p.read_text(encoding='utf-8')
            assert 'SENSITIVE_CANARY' not in raw and 'PRIVATE_CANARY' not in raw
            assert ledger.evidence()[0]['accepted'] == 10

    for key, fn in (('bounded_1000_events', flood), ('duplicate_filter', dedup),
                    ('gift_streak', gift), ('stale_room_epoch', lifecycle),
                    ('privacy_aggregate', no_raw_memory)):
        probe(key, fn)
    return {'passed': sum(x['ok'] for x in findings), 'total': len(findings),
            'findings': findings, 'scope': 'offline_only_no_real_tiktok_obs'}
