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

            deviations = store.compare_to_norms(state, unusual)
            rendered = store.render_context(state, snapshot=unusual)

            self.assertTrue(deviations)
            self.assertTrue(any(item.feature == "active_window_kind" for item in deviations))
            self.assertIn("deviation", rendered)
            self.assertIn("baseline", rendered)
            self.assertIn("current=entertainment", rendered)

    def test_legacy_list_file_loads_as_semantic_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('["User likes concise replies.", "User likes concise replies."]')

            store = MemoryStore(path)
            state = store.load_state()

            self.assertEqual([item.text for item in state.semantic], ["User likes concise replies."])
            self.assertEqual(store.load(), ["User likes concise replies."])

    def test_memory_state_loads_utf8_bom_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            with open(path, "w", encoding="utf-8-sig") as handle:
                handle.write('{"version":4,"semantic":[{"text":"User prefers stable memory."}]}')

            store = MemoryStore(path)
            state = store.load_state()

            self.assertEqual([item.text for item in state.semantic], ["User prefers stable memory."])

    def test_internal_state_round_trips_through_memory_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            store = MemoryStore(path)
            state = store.load_state()
            state.internal_state = PersistentInternalState(
                attachment=0.64,
                silence_pressure=0.58,
                social_pressure=0.41,
                curiosity_pressure=0.32,
                restraint_pressure=0.23,
                cycle_count=7,
                recent_notes=("continuity",),
            )
            store.save_state(state)

            loaded = store.load_state()

            self.assertEqual(loaded.internal_state.cycle_count, 7)
            self.assertAlmostEqual(loaded.internal_state.attachment, 0.64, places=2)
            self.assertAlmostEqual(loaded.internal_state.silence_pressure, 0.58, places=2)
            self.assertAlmostEqual(loaded.internal_state.social_pressure, 0.41, places=2)
            self.assertAlmostEqual(loaded.internal_state.curiosity_pressure, 0.32, places=2)
            self.assertAlmostEqual(loaded.internal_state.restraint_pressure, 0.23, places=2)
            self.assertEqual(loaded.internal_state.recent_notes, ("continuity",))

    def test_missing_internal_state_field_loads_default_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"version":3,"working":[],"episodic":[],"semantic":[],"relationship":[],"norm":{}}')

            store = MemoryStore(path)
            state = store.load_state()

            self.assertEqual(state.version, 4)
            self.assertEqual(state.internal_state.cycle_count, 0)
            default_state = PersistentInternalState()
            self.assertEqual(state.internal_state.social_pressure, default_state.social_pressure)
            self.assertEqual(state.internal_state.restraint_pressure, default_state.restraint_pressure)

    def test_active_memory_resonance_separates_silent_bias_from_surface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(os.path.join(tmpdir, "memory.json"), max_items=30)
            state = store.load_state()
            state = store.remember_relationship_reflection(
                state,
                "User dislikes fake output and prefers direct grounded analysis.",
                pattern="grounded_style",
                evidence=("bad fake output",),
            )
            state = store.remember_procedural_rule(
                state,
                "When output is being squeezed by a guard, inspect post-generation filters first.",
                trigger="post_generation_guard",
            )

            report = store.activate_memory_resonance(
                state,
                user_text="output bi guard bop, dung sua prompt voi",
                channel="chat",
            )
            context = report.render_prompt_context()

            self.assertGreater(report.score, 0.0)
            self.assertIn(report.dominant_layer, {"procedural", "relationship"})
            self.assertGreater(report.attention_bias, 0.0)
            self.assertIn("silent cognitive bias", context)
            self.assertIn("not treat it as current screen evidence", context)
            self.assertTrue(report.to_attention_lines())

    def test_experiential_association_tracks_cognition_tension_and_loops(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(os.path.join(tmpdir, "memory.json"), max_items=30)
            state = store.load_state()

            state = store.remember_cycle(
                state,
                cycle_id="chat-42",
                channel="chat",
                timestamp="2026-05-10T21:00:00+0700",
                seen=("Experiential association architecture",),
                said="wire the inner trace",
                outcome="inner_trace",
                salience=0.74,
                tags=("cognitive_momentum",),
                experience_cues=("A", "experiential association"),
                cognition_state="channel=chat; self=engaged; thought=input_disturbance",
                tension=0.81,
                pull_direction="cognitive_momentum:attention:experiential association",
                unresolved_loop="loop_1:experiential association",
                thought_id="thought_1",
                associations=("memory_resonance:A",),
                momentum_score=0.77,
            )
            store.save_state(state)

            loaded = store.load_state()
            matches = store.query_experiential_associations(loaded, "A")
            recalled = store.recall_texts(loaded)
            context = store.render_context(loaded)

            self.assertTrue(matches)
            self.assertIn("channel=chat", matches[0].cognition_states[0])
            self.assertIn("high_unresolved_tension", matches[0].tension_labels)
            self.assertIn("cognitive_momentum:attention", matches[0].pull_directions[0])
            self.assertIn("loop_1", matches[0].unresolved_loops[0])
            self.assertTrue(any(item.startswith("experiential/") for item in recalled))
            self.assertIn("experiential_association_network", context)

    def test_emotional_residue_memory_tracks_aftertaste_not_just_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(os.path.join(tmpdir, "memory.json"), max_items=30)
            state = store.load_state()

            state = store.remember_cycle(
                state,
                cycle_id="auto-9",
                channel="autonomous",
                timestamp="2026-05-13T01:40:00+0700",
                seen=("Godot stayed open through a long quiet night",),
                said="",
                outcome="no_speech",
                salience=0.72,
                tags=("silent", "godot"),
                cognition_state="channel=autonomous; desire=silence_pull",
                tension=0.62,
                unresolved_loop="unfinished:voice_distillation",
            )
            store.save_state(state)

            loaded = store.load_state()
            recalled = store.recall_texts(loaded)
            context = store.render_context(loaded)
            report = store.activate_memory_resonance(
                loaded,
                user_text="Godot quiet night residue",
                channel="chat",
            )

            self.assertTrue(loaded.emotional_residue)
            self.assertIn(loaded.emotional_residue[0].residue_type, {"silent_residue", "godot_recurrence"})
            self.assertTrue(any(item.startswith("emotional_residue/") for item in recalled))
            self.assertIn("emotional_residue_memory", context)
            self.assertTrue(any(item.layer == "emotional_residue" for item in report.activations))
            loaded = core.load()
            self.assertEqual(loaded["active_state"]["metadata"]["internal_state"]["cycle_count"], 7)
            self.assertEqual(loaded["active_state"]["metadata"]["internal_state"]["last_channel"], "chat")


if __name__ == "__main__":
    unittest.main()
