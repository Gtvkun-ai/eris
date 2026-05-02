import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

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
    def test_memory_state_keeps_four_memory_types_separate(self):
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
            state = store.update_norms(state, _snapshot())
            store.save_state(state)

            loaded = store.load_state()
            context = store.render_context(loaded, snapshot=_snapshot())

            self.assertEqual(len(loaded.working), 1)
            self.assertEqual(len(loaded.episodic), 1)
            self.assertEqual(loaded.semantic[0].text, "User prefers explicit memory architecture.")
            self.assertEqual(loaded.norm.observations, 1)
            self.assertIn("working_memory", context)
            self.assertIn("episodic_memory", context)
            self.assertIn("semantic_user_memory", context)
            self.assertIn("norm_memory", context)

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


if __name__ == "__main__":
    unittest.main()
