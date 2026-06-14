import os
import sys
import json
import unittest

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.service import LlmService


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.reason = "Server Error"
        self.url = "http://test"
        self.text = '{"error":"boom"}'


class _Failing5xxClient:
    """Client luôn ném 500 → kiểm thử degrade không-crash."""

    base_url = "https://api.groq.com/openai/v1"
    model_name = "qwen/qwen3-32b"

    def __init__(self):
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        raise requests.HTTPError("500 Server Error", response=_Resp(500))


class _DistillClient:
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    model_name = "gemma-4-26b-a4b-it"

    def __init__(self):
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": "- ý chính 1\n- ý chính 2"}}]}


class DegradeTests(unittest.TestCase):
    def test_5xx_degrades_to_fallback_not_crash(self):
        client = _Failing5xxClient()
        svc = LlmService(client)
        raw = svc._complete_decision(
            messages=[{"role": "user", "content": "hi"}],
            channel="chat",
            require_text=False,
        )
        payload = json.loads(raw)
        # Không raise; trả payload degrade có dấu service_error để downstream biết.
        self.assertIn("service_error", payload.get("reasoning_tags", []))
        self.assertTrue(payload.get("should_speak"))
        self.assertGreaterEqual(client.calls, 2)  # gọi đầu + retry 5xx


class DDSDistillIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._prev_cap = os.environ.get("ERIS_LLM_PROMPT_HARD_CAP_TOKENS")
        os.environ["ERIS_LLM_PROMPT_HARD_CAP_TOKENS"] = "800"

    def tearDown(self):
        if self._prev_cap is None:
            os.environ.pop("ERIS_LLM_PROMPT_HARD_CAP_TOKENS", None)
        else:
            os.environ["ERIS_LLM_PROMPT_HARD_CAP_TOKENS"] = self._prev_cap

    def test_oversized_block_is_distilled(self):
        main = _Failing5xxClient()  # provider=groq cho hard-cap nhỏ
        distiller = _DistillClient()
        svc = LlmService(main, style_client=distiller)
        big = "ngữ cảnh rất dài lặp đi lặp lại. " * 200
        out = svc._maybe_distill_blocks({"memory_context": big}, channel="chat")
        self.assertLess(len(out["memory_context"]), len(big))
        self.assertEqual(distiller.calls, 1)

    def test_small_block_not_distilled(self):
        main = _Failing5xxClient()
        distiller = _DistillClient()
        svc = LlmService(main, style_client=distiller)
        out = svc._maybe_distill_blocks({"memory_context": "ngắn"}, channel="chat")
        self.assertEqual(out["memory_context"], "ngắn")
        self.assertEqual(distiller.calls, 0)


if __name__ == "__main__":
    unittest.main()
