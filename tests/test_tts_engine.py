import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.tts_engine import _synthesize_wav

class FakeGenaiClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.models = MagicMock()

class TtsEngineTests(unittest.TestCase):
    @patch("runtime.tts_engine._get_api_key")
    @patch("google.genai.Client")
    def test_synthesize_wav_retries_on_rate_limit(self, mock_client_cls, mock_get_api_key):
        with patch("llm.key_pool.get_key_pool") as mock_get_key_pool:
            # Setup key pool mock
            mock_pool = MagicMock()
            mock_pool.size = 3
            mock_pool.current_index = 0
            
            # When pool.rotate() is called, increment current_index
            def fake_rotate():
                mock_pool.current_index += 1
                return True
            mock_pool.rotate.side_effect = fake_rotate
            mock_get_key_pool.return_value = mock_pool

            # Setup API keys returned for each rotation
            mock_get_api_key.side_effect = ["key0", "key1", "key2"]

            # genai.Client mock behavior
            client_instances = []
            def create_fake_client(api_key):
                c = FakeGenaiClient(api_key)
                client_instances.append(c)
                
                # First client (key0) fails with 429
                # Second client (key1) succeeds and returns PCM data
                if api_key == "key0":
                    exc = RuntimeError("429 RESOURCE_EXHAUSTED: Quota exceeded")
                    c.models.generate_content.side_effect = exc
                else:
                    # Mock success response
                    mock_part = MagicMock()
                    mock_part.inline_data.data = b"\x00\x00" * 48000 # dummy PCM mono 16-bit
                    mock_cand = MagicMock()
                    mock_cand.content.parts = [mock_part]
                    mock_resp = MagicMock()
                    mock_resp.candidates = [mock_cand]
                    c.models.generate_content.return_value = mock_resp
                return c

            mock_client_cls.side_effect = create_fake_client

            # Call the target function
            wav_bytes = _synthesize_wav("Hello Eris", "Aoede", "gemini-3.1-flash-tts-preview")

            # Verify calls and rotations
            self.assertIsNotNone(wav_bytes)
            self.assertEqual(len(client_instances), 2)  # Should have created 2 clients (key0, key1)
            self.assertEqual(client_instances[0].api_key, "key0")
            self.assertEqual(client_instances[1].api_key, "key1")
            mock_pool.mark_dead.assert_called_once_with(seconds=60.0)
            mock_pool.rotate.assert_called_once()

    @patch("runtime.tts_engine._get_api_key")
    @patch("runtime.tts_engine._synthesize_wav")
    @patch("runtime.tts_engine._play_wav_bytes")
    def test_speak_calls_on_start_play(self, mock_play, mock_synthesize, mock_get_api_key):
        from runtime.tts_engine import TtsEngine
        mock_get_api_key.return_value = "dummy_key"
        mock_synthesize.return_value = b"dummy_wav"

        with patch("runtime.tts_engine._enabled", return_value=True):
            engine = TtsEngine()
            self.assertTrue(engine._ok)
            
            callback_called = MagicMock()
            
            engine.speak("Hello", on_start_play=callback_called)
            
            import time
            start_time = time.time()
            while not callback_called.called and time.time() - start_time < 3.0:
                time.sleep(0.05)
                
            callback_called.assert_called_once()
            mock_play.assert_called_once_with(b"dummy_wav", engine._worker._current_stop)
            
            engine.shutdown()

if __name__ == "__main__":
    unittest.main()
