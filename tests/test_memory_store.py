import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from memory import MemoryCognitionCore


def request(**overrides):
    payload = {
        "target": "semantic_memory",
        "content": "User prefers explicit memory architecture.",
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


class MemoryCognitionCoreFacadeTests(unittest.TestCase):
    def test_commit_routes_only_through_state_commit_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)

            decisions = [
                core.commit(request(target="event_ledger", content="turn happened", confidence=0.95)),
                core.commit(request(target="episodic_memory", content={"scene": ["chat"], "eris_action": "answered", "outcome": "ok"})),
                core.commit(request(target="semantic_memory", content={"fact": "User prefers explicit memory architecture."})),
                core.commit(request(target="relational_memory", content={"pattern": "style_preference", "text": "User prefers grounded directness."})),
                core.commit(request(target="affective_residue_memory", content={"stance": "repair_residue", "residue_strength": 0.64})),
                core.commit(request(target="procedural_memory", content={"trigger": "technical_task", "rule": "Answer first, then explain."})),
                core.commit(request(target="repair_memory", content={"failure_type": "misread", "wrong_assumption": "overread user mood", "repair_strategy": "ask less, ground more"})),
                core.commit(request(target="active_state", content={"active_task": "memory facade migration"}, decay_policy="session_only")),
            ]

            self.assertTrue(all(item.outcome in {"accepted", "tentative"} for item in decisions))
            loaded = core.load()
            self.assertTrue(loaded["event_ledger"])
            self.assertTrue(loaded["episodic_memory"])
            self.assertTrue(loaded["semantic_memory"])
            self.assertTrue(loaded["relational_memory"])
            self.assertTrue(loaded["affective_residue_memory"])
            self.assertTrue(loaded["procedural_memory"])
            self.assertTrue(loaded["repair_memory"])
            self.assertEqual(loaded["active_state"]["active_task"], "memory facade migration")

    def test_permission_gate_rejects_unapproved_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            decision = core.commit(request(storage_permission=False))

            self.assertEqual(decision.outcome, "rejected")
            self.assertEqual(decision.reason, "storage_permission_false")
            self.assertFalse(core.load()["semantic_memory"])

    def test_recall_and_render_context_are_facade_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.commit(request(target="procedural_memory", content={"trigger": "technical_task", "rule": "Answer first, then explain."}))
            core.commit(request(target="relational_memory", content={"pattern": "grounded_style", "text": "User dislikes fake output."}))

            packet = core.recall("technical fake output", max_items=8)
            context = core.render_context("technical fake output")

            self.assertTrue(packet.procedural)
            self.assertTrue(packet.relational)
            self.assertGreater(packet.score, 0.0)
            self.assertIn("procedural_memory", context)
            self.assertIn("active_memory_resonance", context)
            self.assertTrue(packet.to_attention_lines())

    def test_save_load_preserves_active_internal_state_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.save(
                {
                    "active_state": {"metadata": {}},
                    "internal_state": {"cycle_count": 7, "last_channel": "chat"},
                }
            )

            loaded = core.load()
            self.assertEqual(loaded["active_state"]["metadata"]["internal_state"]["cycle_count"], 7)
            self.assertEqual(loaded["active_state"]["metadata"]["internal_state"]["last_channel"], "chat")


if __name__ == "__main__":
    unittest.main()
