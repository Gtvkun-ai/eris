"""L-01..L-05: offline, no TikTok, no DeepSeek."""
import time
import unittest
from types import SimpleNamespace
from runtime.live.normalize import normalize_event
from runtime.live.intake import BoundedLiveIntake
from runtime.live.batcher import LiveBatcher
from runtime.live.contracts import LiveEvent
from runtime.live.lifecycle import LiveLifecycle
from runtime.live.scope import validate_public_output, public_context
from runtime.live.contracts import AudienceScope, LiveBatch

class IngressTests(unittest.TestCase):
    def event(self, idx, *, kind='comment', count=1, streaking=None, viewer='alice', text='hello'):
        return LiveEvent(str(idx), 'room1', 1, kind, time.time(), viewer, viewer,
                         text, 'rose', count, streaking)

    def test_bounded_1000_events(self):
        intake = BoundedLiveIntake(capacity=64)
        for i in range(1000):
            intake.offer(self.event(i))
        self.assertEqual(intake.depth, 64)
        self.assertEqual(intake.counters.overflow, 936)
        self.assertEqual(len(intake.drain()), 64)

    def test_event_dedup(self):
        intake = BoundedLiveIntake()
        e = self.event('same')
        self.assertTrue(intake.offer(e))
        self.assertFalse(intake.offer(e))
        self.assertEqual(intake.counters.duplicate, 1)

    def test_stale_ttl(self):
        intake = BoundedLiveIntake(ttl_seconds=3)
        self.assertFalse(intake.offer(LiveEvent('old', 'r', 1, 'comment', time.time()-30)))

    def test_gift_streak_cumulative_not_additive(self):
        batch = LiveBatcher()
        values = [self.event(str(i), kind='gift', count=n, streaking=s)
                  for i,(n,s) in enumerate([(1,True),(5,True),(20,True),(50,True),(50,False)])]
        result = batch.build(values)
        self.assertEqual(result.gifts[0]['count'], 50)
        self.assertEqual(len(result.gifts), 1)

    def test_intermediate_gift_not_announced(self):
        batcher = LiveBatcher()
        result = batcher.build([self.event('a',kind='gift',count=4,streaking=True)])
        self.assertTrue(result.is_empty)
        result = batcher.build([self.event('b',kind='gift',count=7,streaking=False)])
        self.assertEqual(result.gifts[0]['count'], 7)

    def test_like_storm_aggregated(self):
        batcher = LiveBatcher()
        result = batcher.build([self.event(i,kind='like',count=20) for i in range(100)])
        self.assertEqual(result.likes, 2000)
        self.assertFalse(result.comments)

    def test_comments_cap_and_dedupe(self):
        batcher = LiveBatcher(max_comments=5)
        result = batcher.build([self.event(i, text='text '+str(i)) for i in range(30)])
        self.assertEqual(len(result.comments), 5)
        repeat = batcher.build([self.event(200,text='text 29')])
        self.assertTrue(repeat.is_empty)

    def test_room_epoch_invalidation(self):
        life = LiveLifecycle()
        first = life.start('room')
        self.assertTrue(life.valid('room',first))
        life.stop()
        self.assertFalse(life.valid('room',first))
        second = life.start('room')
        self.assertGreater(second, first)
        self.assertFalse(life.valid('room',first))

    def test_provider_normalization_limits(self):
        user=SimpleNamespace(unique_id='abc', nickname='alice')
        e = normalize_event(SimpleNamespace(user=user,comment='x'*900,msg_id='123'),
                            kind='comment',room_id='r',room_epoch=2)
        self.assertEqual(len(e.text),360)
        self.assertEqual(e.viewer_id,'abc')
        self.assertEqual(e.room_epoch,2)

    def test_gift_same_message_id_streak_updates_survive(self):
        raw = {'msg_id':'giftX','user':{'unique_id':'u','nickname':'U'},
               'gift':{'id':'rose'}, 'repeat_count':1, 'streaking':True}
        intake = BoundedLiveIntake()
        for count,streaking in ((1,True),(5,True),(20,True),(50,True),(50,False)):
            raw['repeat_count'],raw['streaking']=count,streaking
            self.assertTrue(intake.offer(normalize_event(raw,kind='gift',
                                  room_id='room',room_epoch=1)))
        batch = LiveBatcher().build(intake.drain())
        self.assertEqual(batch.gifts[0]['count'],50)

    def test_affect_only_numeric_allowlist(self):
        from runtime.live.scope import public_affect_projection
        class FakeState:
            valence = -0.5
            social_energy = 0.8
            private_diary = 'DO_NOT_READ'
        host = SimpleNamespace(_get_internal_state=lambda: FakeState())
        self.assertEqual(public_affect_projection(host),{'valence':-0.5,'social_energy':0.8})

    def test_public_context_allowlist(self):
        batch=LiveBatch('r',1,time.time(),comments=({'viewer':'X','text':'hi'},))
        scope=AudienceScope('public_live','public_live:r:1',1)
        context=public_context(batch,scope,active_guard=lambda:True)
        self.assertNotIn('memory_context',context)
        self.assertNotIn('relationship_context',context)
        self.assertEqual(context['__audience_scope'],'public_live')
        self.assertEqual(context['speech_language_hint'],'vi')

    def test_secret_gate(self):
        for secret in ('sk-'+'x'*35,'password=verysecretpassword',
                       '-----BEGIN PRIVATE KEY-----'):
            with self.assertRaises(PermissionError):
                validate_public_output(secret)
        validate_public_output('Cảm ơn mọi người đã xem live.')

if __name__=='__main__': unittest.main()
