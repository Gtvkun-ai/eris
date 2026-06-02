import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import PersistentInternalState
from cortex.agent_mind_persistence import agent_mind_path_for_memory_core
from cortex.agent_state_stack import build_agent_state_stack
from memory.memory_cognition import MemoryCognitionCore


def request(**overrides):
    payload = {
        "target": "semantic_memory",
        "content": {"fact": "User prefers explicit memory architecture.", "source": "explicit_user_statement"},
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
                core.commit(request(target="semantic_memory", content={"fact": "User prefers explicit memory architecture.", "source": "explicit_user_statement"})),
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

    def test_semantic_memory_dedupes_repeated_commit_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            content = {"fact": "User likes concise replies.", "source": "explicit_user_statement"}

            core.commit(request(content=content))
            core.commit(request(content=content))
            loaded = core.load()

            self.assertEqual(len(loaded["semantic_memory"]), 1)
            self.assertEqual(loaded["semantic_memory"][0]["claim"], "User likes concise replies.")

    def test_render_context_loads_semantic_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.commit(
                request(
                    content={"fact": "User prefers stable memory.", "source": "explicit_user_statement"},
                )
            )

            context = core.render_context("stable memory")

            self.assertIn("semantic_memory", context)
            self.assertIn("stable memory", context)

    def test_internal_state_round_trips_through_active_state_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            state = PersistentInternalState(
                attachment=0.64,
                silence_pressure=0.58,
                social_pressure=0.41,
                curiosity_pressure=0.32,
                restraint_pressure=0.23,
                cycle_count=7,
                recent_notes=("continuity",),
            )
            core.save({"active_state": {"metadata": {"internal_state": state.to_dict()}}})

            loaded_payload = core.load()["active_state"]["metadata"]["internal_state"]
            loaded = PersistentInternalState.from_dict(loaded_payload)

            self.assertEqual(loaded.cycle_count, 7)
            self.assertAlmostEqual(loaded.attachment, 0.64, places=2)
            self.assertAlmostEqual(loaded.silence_pressure, 0.58, places=2)
            self.assertAlmostEqual(loaded.social_pressure, 0.41, places=2)
            self.assertAlmostEqual(loaded.curiosity_pressure, 0.32, places=2)
            self.assertAlmostEqual(loaded.restraint_pressure, 0.23, places=2)
            self.assertEqual(loaded.recent_notes, ("continuity",))

    def test_missing_internal_state_field_loads_default_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            loaded = core.load()
            state = PersistentInternalState.from_dict(
                loaded["active_state"].get("metadata", {}).get("internal_state", {})
            )

            self.assertEqual(state.cycle_count, 0)
            default_state = PersistentInternalState()
            self.assertEqual(state.social_pressure, default_state.social_pressure)
            self.assertEqual(state.restraint_pressure, default_state.restraint_pressure)

    def test_active_memory_resonance_separates_silent_bias_from_surface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.commit(
                request(
                    target="relational_memory",
                    content={"pattern": "grounded_style", "text": "User dislikes fake output and prefers direct grounded analysis."},
                )
            )
            core.commit(
                request(
                    target="procedural_memory",
                    content={"trigger": "post_generation_guard", "rule": "When output is being squeezed by a guard, inspect post-generation filters first."},
                )
            )

            report = core.recall("output bi guard bop, dung sua prompt voi")
            context = report.render_prompt_context()

            self.assertGreater(report.score, 0.0)
            self.assertIn(report.dominant_layer, {"procedural", "relational", "relationship"})
            self.assertGreater(report.attention_bias, 0.0)
            self.assertIn("silent cognitive bias", context)
            self.assertIn("not treat it as current screen evidence", context)
            self.assertTrue(report.to_attention_lines())

    def test_experiential_association_tracks_cognition_tension_and_loops(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.commit(
                request(
                    target="episodic_memory",
                    content={"scene": ["chat", "experiential association"], "eris_action": "wire the inner trace", "outcome": "inner_trace"},
                )
            )

            packet = core.recall("experiential association")
            context = core.render_context("experiential association")

            self.assertTrue(packet.episodic)
            self.assertIn("episodic_memory", context)
            self.assertIn("experiential", context.lower())

    def test_emotional_residue_memory_tracks_aftertaste_not_just_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.commit(
                request(
                    target="affective_residue_memory",
                    content={"stance": "silent_residue", "residue_strength": 0.64, "text": "Godot stayed open through a long quiet night."},
                )
            )

            loaded = core.load()
            context = core.render_context("Godot quiet night residue")
            report = core.recall("Godot quiet night residue")

            self.assertTrue(loaded["affective_residue_memory"])
            self.assertIn("silent_residue", str(loaded["affective_residue_memory"][0]))
            self.assertIn("affective_residue_memory", context)
            self.assertTrue(any(item.layer == "affective_residue" for item in report.activations))

    def test_agent_mind_store_lives_under_memory_core_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)

            expected = agent_mind_path_for_memory_core(tmpdir)

            self.assertEqual(core.agent_mind.path, expected)
            self.assertTrue(expected.exists())
            self.assertIn("agent_mind", core.load())

    def test_save_can_round_trip_agent_mind_snapshot_through_memory_core(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            snapshot = core.load()
            snapshot["agent_mind"]["last_feedback_events"] = [
                {
                    "ts": 123.0,
                    "text": "debug that first",
                    "sentiment": "positive",
                    "topics": ["technical_help"],
                    "speech_act": "practical_help",
                    "selected_impulse": "technical_help_impulse",
                    "markers": ["feedback.technical_help"],
                }
            ]

            core.save(snapshot)
            loaded = core.load()

            self.assertEqual(len(loaded["agent_mind"]["last_feedback_events"]), 1)
            self.assertEqual(loaded["agent_mind"]["last_feedback_events"][0]["markers"], ["feedback.technical_help"])

    def test_agent_state_stack_prefers_explicit_agent_mind_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(tmpdir)
            core.agent_mind.preferences["short_resonant_line"].strength = 0.91
            core.agent_mind.save()

            stack = build_agent_state_stack(
                snapshot=SimpleNamespace(
                    active_window_title="parser traceback",
                    active_app="VS Code",
                    focus_kind_hint="code",
                    idle_seconds=3,
                ),
                agent_mind=core.agent_mind,
            )

            self.assertIs(stack.habits.agent_mind, core.agent_mind)
            self.assertAlmostEqual(stack.preferences.short_resonant_line, 0.91, places=2)


if __name__ == "__main__":
    unittest.main()
