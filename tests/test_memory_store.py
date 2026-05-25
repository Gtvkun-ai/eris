import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import PersistentInternalState
from memory import MemoryStore


def _snapshot(
    *,
    kind="coding",
    app="Visual Studio Code",
    focus="coding workspace",
    idle=2.0,
    windows=("Visual Studio Code",),
    tabs=(),
    pattern="deep",
):
    return SimpleNamespace(
        active_window_kind=kind,
        active_app=app,
        active_window=app,
        focus_summary=focus,
        idle_seconds=idle,
        open_windows=windows,
        browser_tabs=tabs,
        user_signals=SimpleNamespace(focus_pattern=pattern),
    )


class MemoryStoreTests(unittest.TestCase):
    def test_memory_state_keeps_memory_types_separate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            store = MemoryStore(path, max_items=30)
            state = store.load_state()

            state = store.remember_cycle(
                state,
                cycle_id="chat-1",
                channel="chat",
                timestamp="2026-05-01T10:00:00+0700",
                seen=("VS Code is active",),
                said="Tach memory thanh bon loai.",
                outcome="json",
                salience=0.72,
                tags=("user_requested",),
                semantic_fact="User prefers explicit memory architecture.",
            )
            state = store.remember_relationship_reflection(
                state,
                "Ngài thích giọng lạnh nhẹ, nhưng không thích báo cáo telemetry.",
                pattern="style_preference",
                timestamp="2026-05-01T10:00:00+0700",
            )
            state = store.update_norms(state, _snapshot())
            store.save_state(state)

            loaded = store.load_state()
            context = store.render_context(loaded, snapshot=_snapshot())

            self.assertEqual(len(loaded.working), 1)
            self.assertEqual(len(loaded.episodic), 1)
            self.assertEqual(loaded.semantic[0].text, "User prefers explicit memory architecture.")
            self.assertEqual(loaded.relationship[0].pattern, "style_preference")
            self.assertEqual(loaded.norm.observations, 1)
            self.assertIn("working_memory", context)
            self.assertIn("episodic_memory", context)
            self.assertIn("semantic_user_memory", context)
            self.assertIn("relationship_memory", context)
            self.assertIn("procedural_memory", context)
            self.assertIn("norm_memory", context)
            self.assertIn("not current screen evidence", context)

    def test_relationship_memory_dedupes_and_appears_in_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(os.path.join(tmpdir, "memory.json"), max_items=30)
            state = store.load_state()

            for _ in range(2):
                state = store.remember_relationship_reflection(
                    state,
                    "Khi thiếu screen signal, ERIS nên hỏi lại hoặc mở một câu tò mò, không giả vờ thấy gì.",
                    pattern="no_screen_signal_social_fallback",
                    evidence=("force_speak",),
                )

            recalled = store.recall_texts(state)

            self.assertEqual(len(state.relationship), 1)
            self.assertEqual(state.relationship[0].observations, 2)
            self.assertTrue(any(item.startswith("relationship/no_screen_signal") for item in recalled))

    def test_norm_memory_compares_new_scene_to_prior_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(os.path.join(tmpdir, "memory.json"), max_items=30)
            state = store.load_state()

            for _ in range(6):
                state = store.update_norms(state, _snapshot())

            unusual = _snapshot(
                kind="entertainment",
                app="YouTube - Brave",
                focus="watching video",
                idle=820.0,
                windows=("Brave",),
                tabs=("YouTube", "Music"),
                pattern="drifting",
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


if __name__ == "__main__":
    unittest.main()
