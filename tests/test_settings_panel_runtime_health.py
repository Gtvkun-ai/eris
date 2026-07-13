import io
import os
import time
import unittest
import wave
from unittest.mock import patch

from llm.key_pool import ApiKeyPool
from runtime import tts_engine


class KeyPoolHealthSnapshotTests(unittest.TestCase):
    def test_snapshot_does_not_expose_keys_and_marks_cooldown(self):
        pool = ApiKeyPool(["secret-key-a", "secret-key-b"])
        first = pool.acquire()
        self.assertIsNotNone(first)
        pool.mark_dead(seconds=3, lease=first, reason="test")

        snapshot = pool.health_snapshot()

        self.assertEqual(snapshot["size"], 2)
        self.assertEqual(len(snapshot["keys"]), 2)
        self.assertNotIn("secret-key-a", repr(snapshot))
        self.assertEqual(snapshot["keys"][0]["status"], "cooldown")
        self.assertGreater(snapshot["keys"][0]["cooldown_ms"], 0)


class TtsSettingsHelpersTests(unittest.TestCase):
    @staticmethod
    def _wav(sample: int = 12000, count: int = 32) -> bytes:
        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(int(sample).to_bytes(2, "little", signed=True) * count)
        return out.getvalue()

    def test_output_volume_scales_pcm16(self):
        with patch.dict(os.environ, {"ERIS_TTS_VOLUME": "0.50"}, clear=False):
            result = tts_engine._apply_output_volume(self._wav())
        with wave.open(io.BytesIO(result), "rb") as wf:
            sample = int.from_bytes(wf.readframes(1), "little", signed=True)
        self.assertTrue(5900 <= sample <= 6100)

    def test_speed_setting_changes_prompt_directive(self):
        with patch.dict(os.environ, {"ERIS_TTS_SPEED": "1.15"}, clear=False):
            self.assertIn("brisk", tts_engine._pace_directive())
        with patch.dict(os.environ, {"ERIS_TTS_SPEED": "0.85"}, clear=False):
            self.assertIn("slower", tts_engine._pace_directive())


if __name__ == "__main__":
    unittest.main()
