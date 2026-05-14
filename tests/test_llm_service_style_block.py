import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.service import LlmService


class LlmServiceStyleBlockTests(unittest.TestCase):
    def test_fe_context_does_not_replace_base_persona_prompt(self):
        service = LlmService(client=None)

        style_block = service._build_style_block(
            fe_context="style_tags: tone=cold_soft, warmth=mid, stance=grounded",
            appraisal_context="appraisal: low risk",
            internal_state_context="identity_core: continuity",
        )

        self.assertIn("Persona target: INFJ 5w4 594", style_block)
        self.assertIn("style_tags: tone=cold_soft", style_block)
        self.assertIn("appraisal: low risk", style_block)
        self.assertIn("identity_core: continuity", style_block)


if __name__ == "__main__":
    unittest.main()
