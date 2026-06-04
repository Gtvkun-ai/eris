import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.vision_semantic_compressor import VisionCompressorConfig, VisionSemanticCompressor


class VisionSemanticCompressorNoFallbackTests(unittest.TestCase):
    def test_no_fallback_mode_raises_instead_of_ocr_only_note(self):
        os.environ["ERIS_NO_FALLBACK_MODE"] = "1"
        try:
            compressor = VisionSemanticCompressor(
                VisionCompressorConfig(enabled=True, model="qwen3.5-4b-vision"),
                ollama_client=None,
            )
            with self.assertRaises(RuntimeError) as ctx:
                compressor.compress(image_data_uri="", ocr_text="Traceback visible")
            self.assertIn("no_fallback_vision", str(ctx.exception))
        finally:
            os.environ.pop("ERIS_NO_FALLBACK_MODE", None)


if __name__ == "__main__":
    unittest.main()
