import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from memory.memory_cognition import MemoryCognitionCore


def commit_request(**overrides):
    payload = {
        "target": "semantic_memory",
        "content": "User prefers concise technical answers.",
        "confidence": 0.82,
        "evidence_ids": ["ev1"],
        "permission_required": True,
        "storage_permission": True,
        "decay_policy": "normal",
        "reason": "unit test",
        "metadata": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class MemoryCommitProtocolTests(unittest.TestCase):
    def test_storage_permission_false_does_not_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            decision = core.commit(commit_request(storage_permission=False))
            packet = core.retrieve("concise technical answers")

            self.assertEqual(decision.outcome, "rejected")
            self.assertEqual(decision.reason, "storage_permission_false")
            self.assertEqual(packet.semantic, [])

    def test_low_confidence_rejects_or_tentative_by_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            rejected = core.commit(commit_request(confidence=0.20))
            tentative = core.commit(
                commit_request(
                    content="User may prefer answer-first wording.",
                    confidence=0.50,
                    evidence_ids=["ev2"],
                )
            )
            packet = core.retrieve("answer first wording")

            self.assertEqual(rejected.outcome, "rejected")
            self.assertTrue(rejected.reason.startswith("confidence_below_floor"))
            self.assertEqual(tentative.outcome, "tentative")
            self.assertTrue(any("tentative" in item for item in packet.semantic))

    def test_missing_evidence_rejects_except_session_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            missing = core.commit(commit_request(evidence_ids=[]))
            session_only = core.commit(
                commit_request(
                    content="Session-only note without durable evidence.",
                    evidence_ids=[],
                    decay_policy="session_only",
                    confidence=0.70,
                )
            )

            self.assertEqual(missing.outcome, "rejected")
            self.assertEqual(missing.reason, "missing_evidence_ids")
            self.assertIn(session_only.outcome, {"accepted", "tentative"})

    def test_user_correction_can_be_stored_in_repair_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            decision = core.commit(
                commit_request(
                    target="repair_memory",
                    content=(
                        "failure_type: misread\n"
                        "wrong_assumption: ERIS inferred the user wanted explanation only\n"
                        "user_correction: user asked for tests to be created\n"
                        "repair_strategy: create the requested files first"
                    ),
                    confidence=0.72,
                    evidence_ids=["ev_correction"],
                    reason="user correction",
                )
            )
            packet = core.retrieve("tests created misread correction")

            self.assertEqual(decision.outcome, "accepted")
            self.assertTrue(any("misread" in item or "tests" in item for item in packet.repair))

    def test_private_sensitive_evidence_is_not_raw_stored_without_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            decision = core.commit(
                commit_request(
                    target="event_ledger",
                    content="sensitive raw OCR payload",
                    confidence=0.95,
                    evidence_ids=["ev_sensitive"],
                    storage_permission=False,
                    permission_required=False,
                    metadata={
                        "privacy_level": "sensitive",
                        "raw_or_inferred": "raw",
                    },
                )
            )
            packet = core.retrieve("sensitive raw OCR payload")

            self.assertEqual(decision.outcome, "rejected")
            self.assertEqual(packet.episodic, [])
            self.assertEqual(packet.semantic, [])

    def test_memory_core_is_the_only_store_entrypoint_used_by_commit_protocol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)

            original_apply = core.semantic.apply_commit

            def forbid_direct_store_call(_request):
                raise AssertionError("direct semantic store call")

            core.semantic.apply_commit = forbid_direct_store_call
            with self.assertRaises(AssertionError):
                core.semantic.apply_commit(commit_request())

            core.semantic.apply_commit = original_apply
            decision = core.commit(commit_request(content="Protocol stores through MemoryCognitionCore.", evidence_ids=["ev3"]))

            self.assertEqual(decision.outcome, "accepted")


if __name__ == "__main__":
    unittest.main()
