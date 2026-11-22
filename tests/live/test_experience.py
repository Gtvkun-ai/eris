"""P3 nhận diện tương tác SAU audio_done, không suy ra chân lý từ likes."""
import time
import unittest
from runtime.live.experience import LiveExperienceLedger
from runtime.live.contracts import LiveBatch

class ExperienceTests(unittest.TestCase):
    def test_reception_only_after_delivered(self):
        ledger=LiveExperienceLedger()
        current=time.time()
        batch=LiveBatch('r',1,current,comments=({'viewer':'x','text':'hello'},),likes=10)
        ledger.observe_batch(batch)
        self.assertEqual(ledger.public_summary(),())
        ledger.delivered('del1',now=current-1)
        ledger.observe_batch(batch)
        summary=ledger.public_summary()[0]
        self.assertEqual(summary['comments_after'],1)
        self.assertEqual(summary['likes_after'],10)
        self.assertNotIn('viewer',str(summary))
        self.assertNotIn('hello',str(summary))

    def test_expired_reaction_does_not_mutate(self):
        ledger=LiveExperienceLedger(window_seconds=10)
        now=time.time()
        ledger.delivered('del1',now=now-50)
        ledger.observe_batch(LiveBatch('r',1,now,likes=999))
        self.assertEqual(ledger.public_summary()[0]['likes_after'],0)

if __name__=='__main__':unittest.main()
