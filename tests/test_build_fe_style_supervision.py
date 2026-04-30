import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_fe_style_supervision import build_record


class BuildFeStyleSupervisionTests(unittest.TestCase):
    def test_build_record_emits_short_style_tags(self):
        record = build_record(
            Path("persona_general_chat.jsonl"),
            7,
            {
                "tone": "cold_soft",
                "warmth": "mid",
                "stance": "grounded",
                "attachment": "guarded",
                "arc": "quiet_observation",
            },
            [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "xin chao"},
                {"role": "assistant", "content": "chao ngai"},
            ],
        )

        self.assertEqual(record["source_line"], 7)
        self.assertEqual(record["knowledge_context"]["style_source"], "persona_general_chat")
        self.assertEqual(
            record["knowledge_context"]["style_tags"],
            [
                "tone=cold_soft",
                "warmth=mid",
                "stance=grounded",
                "attachment=guarded",
                "arc=quiet_observation",
                "continuity=hold_tone",
            ],
        )


if __name__ == "__main__":
    unittest.main()
