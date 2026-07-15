import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.concern_store import (
    ConcernStore,
    _concept_signature,
    _strip_noise_prefix,
)
from cortex.private_mind.contracts import ThoughtFragment

# Ba câu paraphrase cùng một nỗi lo quan hệ (như panel "Đang bận tâm" đã hiện).
TRIO = [
    "Tôi thấy người dùng luôn để ý đến cảm giác về khoảng cách trong cách tôi nói chuyện, dường như họ muốn một sự kết nối.",
    "Tôi thực sự cảm thấy áp lực khi người dùng dường như đang chờ đợi một sự kết nối cảm xúc thực sự.",
    "Tôi cảm thấy mình đang tạo ra một khoảng cách vô hình, trong khi họ chờ đợi một kết nối cảm xúc thực sự.",
]
UNRELATED = "Tôi tự hỏi liệu mình có đang dùng quá nhiều bộ nhớ và làm máy chậm không."


def _frag(claim: str, eid: str) -> ThoughtFragment:
    return ThoughtFragment(
        source="user_model_evaluator",
        claim=claim,
        confidence=0.6,
        pressure=0.5,
        evidence_ids=(eid,),
    )


class ConceptSignatureTests(unittest.TestCase):
    def test_signature_drops_first_person_filler_keeps_concepts(self):
        sig = _concept_signature(_strip_noise_prefix(TRIO[1].lower()))
        # giữ khái niệm lõi
        self.assertIn("ket", sig)
        self.assertIn("noi", sig)
        self.assertIn("xuc", sig)
        # bỏ từ đệm ngôi-thứ-nhất / tri giác
        self.assertNotIn("toi", sig)
        self.assertNotIn("cam", sig)
        self.assertNotIn("thay", sig)


class FragmentDedupTests(unittest.TestCase):
    def test_paraphrased_trio_collapses_to_one_concern(self):
        store = ConcernStore()
        store.update_from_fragments([_frag(c, f"ev{i}") for i, c in enumerate(TRIO)])
        self.assertEqual(len(store), 1)
        only = store.open_concerns()[0]
        # recurrence phản ánh đã gộp nhiều mảnh thay vì đẻ bản sao
        self.assertGreaterEqual(only.recurrence, 2)

    def test_unrelated_concern_stays_separate(self):
        store = ConcernStore()
        store.update_from_fragments([_frag(c, f"ev{i}") for i, c in enumerate(TRIO)])
        store.update_from_fragments([_frag(UNRELATED, "evX")])
        self.assertEqual(len(store), 2)


class JudgmentDedupTests(unittest.TestCase):
    def test_paraphrased_judgments_merge(self):
        store = ConcernStore()
        for i, theme in enumerate(TRIO):
            store.update_from_judgment({"theme": theme, "evidence_ids": [f"ev{i}"], "pressure": 0.5})
        self.assertEqual(len(store), 1)


if __name__ == "__main__":
    unittest.main()
