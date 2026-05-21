import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.event_semantics import (
    EventEmbeddingCache,
    EventSemanticProfiler,
    should_embed_event,
    symbolic_tags_for_event,
)
from cortex.social_presence import SocialPresenceDetector


class _BatchEmbeddingProvider:
    def __init__(self):
        self.calls = 0

    def embed_events(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "godot" in lowered or "build" in lowered:
                vectors.append((0.9, 0.1, 0.0))
            else:
                vectors.append((0.0, 0.9, 0.1))
        return vectors


class _FailingEmbeddingProvider:
    def embed_events(self, texts):
        raise RuntimeError("embedding backend unavailable")


class EventSemanticsTests(unittest.TestCase):
    def test_primitive_events_do_not_embed(self):
        self.assertFalse(should_embed_event("mouse_move"))
        self.assertFalse(should_embed_event("click"))
        self.assertFalse(should_embed_event("key_press"))
        self.assertTrue(should_embed_event("rapid alt-tab between Godot and VSCode after error"))

    def test_symbolic_tags_are_fast_presence_features(self):
        tags = symbolic_tags_for_event("rapid alt-tab between Godot and VSCode after error")

        self.assertIn("window_switch", tags)
        self.assertIn("restless", tags)
        self.assertIn("coding", tags)
        self.assertIn("build_error", tags)

    def test_background_embedding_uses_batch_cache_and_clusters(self):
        provider = _BatchEmbeddingProvider()
        profiler = EventSemanticProfiler(embedding_provider=provider)
        events = (
            "rapid alt-tab between Godot and VSCode after error",
            "opened Godot error panel after failed build",
        )

        first = profiler.profile_events(events, allow_embedding=True)
        second = profiler.profile_events(events, allow_embedding=True)

        self.assertEqual(provider.calls, 1)
        self.assertTrue(all(profile.embedding for profile in first))
        self.assertTrue(all(profile.cluster_id for profile in first))
        self.assertEqual(first[0].cluster_id, first[1].cluster_id)
        self.assertEqual(second[0].cluster_id, first[0].cluster_id)

    def test_embedding_failure_falls_back_to_symbolic_profile(self):
        profiler = EventSemanticProfiler(embedding_provider=_FailingEmbeddingProvider())

        profile = profiler.profile_event(
            "opened YouTube after build failure",
            allow_embedding=True,
        )

        self.assertIn("build_error", profile.symbolic_tags)
        self.assertEqual(profile.embedding, ())
        self.assertEqual(profile.cluster_id, "")

    def test_detector_uses_cached_cluster_without_realtime_embedding_call(self):
        provider = _BatchEmbeddingProvider()
        cache = EventEmbeddingCache()
        profiler = EventSemanticProfiler(embedding_cache=cache, embedding_provider=provider)
        detector = SocialPresenceDetector(semantic_profiler=profiler)
        detector.learn_event_patterns(("editing same C# file for 12 minutes",))

        provider.calls = 0
        snapshot = SimpleNamespace(
            idle_seconds=20.0,
            active_window_kind="coding",
            recent_events=("editing same C# file for 12 minutes",),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="steady",
            ),
        )

        event = detector.detect(channel="autonomous", snapshot=snapshot)

        self.assertEqual(provider.calls, 0)
        self.assertTrue(event.present)
        self.assertTrue(any(item.startswith("event_cluster=") for item in event.evidence))

    def test_detector_stabilizes_taxonomy_after_repeated_focus(self):
        detector = SocialPresenceDetector()
        snapshot = SimpleNamespace(
            idle_seconds=4.0,
            active_window_kind="coding",
            recent_events=("editing same C# file for 12 minutes",),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="steady",
            ),
        )
        state = SimpleNamespace(last_focus_kind="coding", last_social_presence_present=False)

        first = detector.detect(channel="autonomous", snapshot=snapshot, internal_state=state)
        second = detector.detect(channel="autonomous", snapshot=snapshot, internal_state=state)

        self.assertTrue(first.present)
        self.assertEqual(first.kind, "ambient_co_presence")
        self.assertEqual(second.kind, "focused_co_presence")
        self.assertEqual(len(second.presence_vector), 8)
        self.assertGreater(second.stability, first.stability)

    def test_hysteresis_keeps_recent_presence_on_weak_followup(self):
        detector = SocialPresenceDetector()
        snapshot = SimpleNamespace(
            idle_seconds=200.0,
            active_window_kind="coding",
            recent_events=(),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="steady",
            ),
        )
        state = SimpleNamespace(last_focus_kind="coding", last_social_presence_present=True)

        event = detector.detect(channel="autonomous", snapshot=snapshot, internal_state=state)

        self.assertTrue(event.present)
        self.assertGreaterEqual(event.confidence, 0.30)
        self.assertLess(event.confidence, 0.38)

    def test_absence_kind_requires_stable_fading_signal(self):
        detector = SocialPresenceDetector()
        snapshot = SimpleNamespace(
            idle_seconds=1200.0,
            active_window_kind="general",
            recent_events=(),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="zero",
                focus_pattern="absent",
            ),
        )
        state = SimpleNamespace(last_focus_kind="coding", last_social_presence_present=False)

        first = detector.detect(channel="autonomous", snapshot=snapshot, internal_state=state)
        second = detector.detect(channel="autonomous", snapshot=snapshot, internal_state=state)

        self.assertFalse(first.present)
        self.assertEqual(first.kind, "ambient_presence_below_threshold")
        self.assertFalse(second.present)
        self.assertEqual(second.kind, "presence_absent_or_fading")


if __name__ == "__main__":
    unittest.main()
