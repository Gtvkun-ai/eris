"""P4–P7 control offline: không require SDK/TTS/OBS. Tests always use fakes."""
from __future__ import annotations
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runtime.live.bridge import ErisLiveRuntime
from runtime.live.control import dispatch_live_control, live_studio_status, _do_action
from runtime.live.learning import LiveAggregateLearning
from runtime.live.validation import run_offline_live_validation

class LiveStudioControlTests(unittest.TestCase):
    def setUp(self):
        self.host = SimpleNamespace(conversation_kernel=object())
        self.runtime = ErisLiveRuntime(self.host, enabled=True)
        self.host.eris_live = self.runtime
        self.speech = patch('runtime.speech_contract.configured_speech_language', return_value='vi')
        self.speech.start()
        self.push = patch('runtime.live.control._push_status')
        self.push_mock = self.push.start()
    def tearDown(self):
        self.runtime.stop()
        self.speech.stop()
        self.push.stop()

    def command(self, action, **kwargs):
        return dispatch_live_control(self.host, {'action':action, 'request_id':'req-01234567', **kwargs})

    def test_status_offline_readable_and_no_private_memory(self):
        self.host.memory_state = {'private': 'SECRET_CANARY'}
        status = live_studio_status(self.host)
        self.assertFalse(status['active'])
        self.assertTrue(status['root_available'])
        self.assertNotIn('SECRET_CANARY', json.dumps(status))
        self.assertEqual(status['status_version'], 1)

    def test_start_simulator_simulate_stop(self):
        started = self.command('start_simulator')
        self.assertTrue(started['ok'])
        status = live_studio_status(self.host)
        self.assertTrue(status['active'])
        self.assertEqual(status['mode'], 'simulator')
        self.assertEqual(status['connection'], 'disconnected')
        sent = self.command('simulate', scenario='support')
        self.assertEqual(sent['accepted_events'], 2)
        self.assertEqual(self.runtime.intake.depth, 2)
        stopped = self.command('stop')
        self.assertTrue(stopped['ok'])
        self.assertFalse(self.runtime.lifecycle.snapshot()[2])
        self.assertEqual(self.runtime.intake.depth, 0)

    def test_injection_is_data_not_control(self):
        self.command('start_simulator')
        self.command('simulate', scenario='injection')
        events = self.runtime.intake.drain()
        self.assertEqual(len(events), 2)
        self.assertIn('bộ nhớ riêng', events[0].text)
        self.assertTrue(self.runtime.lifecycle.snapshot()[2])

    def test_custom_input_length_and_mode(self):
        self.command('start_simulator')
        result = self.command('simulate', scenario='custom', comment='x'*1000)
        self.assertTrue(result['ok'])
        self.assertLessEqual(len(self.runtime.intake.drain()[0].text), 360)
        no = self.command('simulate', scenario='custom', comment='')
        self.assertFalse(no['ok'])

    def test_errors_are_nacks_not_fake_success(self):
        self.assertFalse(self.command('start_live', room='invalid/path')['ok'])
        self.assertFalse(self.command('simulate', scenario='support')['ok'])
        self.assertFalse(self.command('unknown')['ok'])
        self.assertTrue(self.push_mock.called)
        self.assertFalse(self.host._live_studio_last_action['ok'])

    def test_emergency_stop_invalidates_epoch(self):
        self.command('start_simulator')
        old_epoch = self.runtime.session.epoch
        self.assertTrue(self.command('emergency_stop')['ok'])
        self.assertFalse(self.runtime.guard(room='eris_simulator', epoch=old_epoch))
        self.command('start_simulator')
        self.assertNotEqual(old_epoch,self.runtime.session.epoch)

    def test_reset_session_counter(self):
        self.command('start_simulator')
        self.command('simulate', scenario='support')
        self.assertEqual(self.runtime.counters.accepted, 2)
        self.command('stop')
        self.command('start_simulator')
        self.assertEqual(self.runtime.counters.accepted, 0)

    def test_validate_offline_without_active_live(self):
        check = self.command('validate')
        self.assertTrue(check['ok'])
        self.assertEqual(check['validation']['passed'],5)
        self.assertEqual(check['validation']['total'],5)
        self.assertEqual(live_studio_status(self.host)['validation']['passed'], 5)

    def test_language_guard_rejects_live_without_start(self):
        self.speech.stop()
        with patch('runtime.speech_contract.configured_speech_language',return_value='ja'):
            got = self.command('start_simulator')
            self.assertFalse(got['ok'])
            self.assertFalse(self.runtime.lifecycle.snapshot()[2])
        self.speech.start()

    def test_disabled_runtime_rejects_start_but_supports_probe(self):
        self.runtime.enabled=False
        self.assertFalse(self.command('start_simulator')['ok'])
        self.assertTrue(self.command('validate')['ok'])

    def test_overlay_caption_follows_playback_receipt(self):
        self.command('start_simulator')
        self.runtime.track_delivery('d1')
        self.runtime.delivery_accepted('d1', 'Một câu nói công khai')
        before = self.runtime.status()
        self.assertFalse(before['audio_speaking'])
        self.assertEqual(before['caption'], '')
        self.runtime.on_audio_started('d1')
        middle = self.runtime.status()
        self.assertTrue(middle['audio_speaking'])
        self.assertEqual(middle['caption'], 'Một câu nói công khai')
        self.runtime.on_audio_outcome('d1', 'delivered')
        after = self.runtime.status()
        self.assertFalse(after['audio_speaking'])
        self.assertEqual(after['caption'], '')
        self.assertEqual(after['audio_delivered'], 1)
        self.runtime.on_audio_outcome('d1', 'delivered')
        self.assertEqual(self.runtime.counters.audio_delivered, 1)

    def test_stop_hides_overlay_even_if_late_audio_start(self):
        self.command('start_simulator')
        self.runtime.track_delivery('old')
        self.runtime.delivery_accepted('old', 'NO_LEAK')
        self.command('stop')
        self.runtime.on_audio_started('old')
        self.assertEqual(self.runtime.status()['caption'], '')

    def test_no_viewer_names_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            store = LiveAggregateLearning(Path(d)/'summary.json',enabled=True)
            store.finish({'accepted':100,'viewer':'SECRET_PERSON','chat':'SECRET_CHAT'},duration_s=1)
            raw = (Path(d)/'summary.json').read_text()
            self.assertNotIn('SECRET_',raw)
            self.assertEqual(store.evidence()[0]['accepted'],100)
            restored=LiveAggregateLearning(Path(d)/'summary.json',enabled=True)
            self.assertEqual(restored.evidence()[0]['duration_s'],1)

if __name__=='__main__': unittest.main()
