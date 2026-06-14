import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm import dds
from llm.dds import WorkerSpec, distill_block, distill_blocks_parallel, extract_text, run_workers


class _FakeClient:
    """Trả về một câu rút gọn ngắn, đếm số lần được gọi."""

    def __init__(self, reply="- gọn 1\n- gọn 2"):
        self.calls = 0
        self.reply = reply

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": self.reply}}]}


class _BoomClient:
    def create_chat_completion(self, **kwargs):
        raise RuntimeError("boom")


class ExtractTextTests(unittest.TestCase):
    def test_openai_shape(self):
        self.assertEqual(extract_text({"choices": [{"message": {"content": " hi "}}]}), "hi")

    def test_gemini_shape(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
        self.assertEqual(extract_text(payload), "a\nb")

    def test_garbage(self):
        self.assertEqual(extract_text(None), "")


class DistillBlockTests(unittest.TestCase):
    def test_short_block_not_distilled(self):
        client = _FakeClient()
        out = distill_block(client, label="x", text="short", min_chars_to_distill=400)
        self.assertEqual(out, "short")
        self.assertEqual(client.calls, 0)

    def test_long_block_distilled(self):
        client = _FakeClient()
        long_text = "câu rất dài lặp lại nhiều. " * 60
        out = distill_block(client, label="mem", text=long_text, min_chars_to_distill=400)
        self.assertEqual(client.calls, 1)
        self.assertLess(len(out), len(long_text))
        self.assertIn("gọn", out)

    def test_failure_returns_original(self):
        long_text = "x" * 1000
        out = distill_block(_BoomClient(), label="mem", text=long_text, min_chars_to_distill=400)
        self.assertEqual(out, long_text)

    def test_distilled_rejected_if_not_smaller(self):
        # Worker "nở" ngữ cảnh → giữ gốc.
        big_reply = "y" * 5000
        client = _FakeClient(reply=big_reply)
        long_text = "z" * 1000
        out = distill_block(client, label="mem", text=long_text, min_chars_to_distill=400)
        self.assertEqual(out, long_text)


class RunWorkersTests(unittest.TestCase):
    def test_parallel_results_and_failures(self):
        specs = [
            WorkerSpec("ok", lambda: "done"),
            WorkerSpec("empty", lambda: ""),
            WorkerSpec("boom", lambda: (_ for _ in ()).throw(ValueError("x"))),
        ]
        results = run_workers(specs, provider="gemini", max_workers=3)
        self.assertTrue(results["ok"].ok)
        self.assertEqual(results["ok"].text, "done")
        self.assertFalse(results["empty"].ok)
        self.assertFalse(results["boom"].ok)


class DistillBlocksParallelTests(unittest.TestCase):
    def test_only_big_blocks_distilled(self):
        client = _FakeClient()
        blocks = {
            "small": "tiny",
            "big": "câu dài lặp. " * 80,
        }
        out = distill_blocks_parallel(client, blocks, min_chars_to_distill=400)
        self.assertEqual(out["small"], "tiny")
        self.assertIn("gọn", out["big"])
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
