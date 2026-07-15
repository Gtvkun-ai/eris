import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "training")))

from full_train_dataset import build_text_dataset


class FakeTokenizer:
    def apply_chat_template(
        self,
        messages,
        tokenize=False,
        add_generation_prompt=False,
    ):
        return "\n".join(f"{message['role']}: {message['content']}" for message in messages)


class FullTrainDatasetTests(unittest.TestCase):
    def test_build_text_dataset_handles_mixed_context_shapes(self):
        rows = [
            {
                "conversations": [
                    {"role": "user", "content": "xin chao"},
                    {"role": "assistant", "content": "chao ban"},
                ],
                "machine_context": {
                    "time": "12:00",
                    "idle_seconds": 5,
                    "recent_events": ["opened_editor", {"kind": "traceback"}],
                },
            },
            {
                "conversations": [
                    {"role": "system", "content": "base system"},
                    {"role": "user", "content": {"task": "open github"}},
                    {"role": "assistant", "content": "toi da gui yeu cau"},
                ],
                "action_context": {
                    "action_name": "open_url",
                    "action_input": {"url": "https://github.com"},
                    "result": {
                        "success": True,
                        "message": "ok",
                        "data": {"url": "https://github.com"},
                    },
                },
            },
            {
                "conversations": [
                    {"role": "user"},
                ]
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_path = Path(temp_dir) / "dataset.jsonl"
            dataset_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            dataset, report = build_text_dataset(dataset_path, FakeTokenizer())

        self.assertEqual(len(dataset), 2)
        self.assertEqual(report["total_rows"], 3)
        self.assertEqual(report["loaded_rows"], 2)
        self.assertEqual(report["skipped_rows"], 1)
        self.assertEqual(report["examples"][0]["line"], 3)
        self.assertIn("Machine context observed", dataset[0]["text"])
        self.assertIn("traceback", dataset[0]["text"])
        self.assertIn("Action execution context", dataset[1]["text"])
        self.assertIn('{"task": "open github"}', dataset[1]["text"])


if __name__ == "__main__":
    unittest.main()
