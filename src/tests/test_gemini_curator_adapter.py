# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from memory.living_user.gemini_adapter import GeminiWebUserProfileAdapter


class TestGeminiWebUserProfileAdapter(unittest.TestCase):
    def test_create_if_available_missing_creds(self):
        with patch.dict("os.environ", {}, clear=True), patch("memory.living_user.gemini_adapter._find_credentials_path", return_value=None):
            adapter = GeminiWebUserProfileAdapter.create_if_available()
            self.assertIsNone(adapter)

    def test_propose_profile_operations_success(self):
        adapter = GeminiWebUserProfileAdapter(psid="test_psid", psidts="test_psidts")
        mock_resp = MagicMock()
        mock_resp.text = '{"operations": [{"op": "add", "path": "interests.gaming", "value": "Pokemmo"}]}'

        with patch.object(adapter, "_async_call", AsyncMock(return_value=mock_resp.text)):
            result = adapter.propose_profile_operations({"user_text": "chơi pokemmo"})
            self.assertIsNotNone(result)
            self.assertIn("operations", result)
            self.assertEqual(result["operations"][0]["value"], "Pokemmo")

    def test_summarize_episode_success(self):
        adapter = GeminiWebUserProfileAdapter(psid="test_psid", psidts="test_psidts")
        mock_resp = MagicMock()
        mock_resp.text = '{"title": "Bàn về game", "summary": "Người dùng kể về game", "topics": ["gaming"]}'

        with patch.object(adapter, "_async_call", AsyncMock(return_value=mock_resp.text)):
            result = adapter.summarize_episode({"turns": []})
            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Bàn về game")


if __name__ == "__main__":
    unittest.main()
