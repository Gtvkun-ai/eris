import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.appraisal import AppraisalEngine
from cortex.contracts import CognitiveBroadcast
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.attention_salience import DEFAULT_STANDING_STAKES, StandingStakes


class AppraisalEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AppraisalEngine()

    def test_protective_mode_and_persistent_guard_build_protective_appraisal(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="system",
                protectiveness=0.78,
                irritation=0.24,
                confidence=0.68,
                arousal=0.52,
            ),
            ni_report=SimpleNamespace(drift_score=0.12, confidence=0.70, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="resource_guard"),
            fe_plan=SimpleNamespace(
                intent_label="ordinary_dialogue",
                session_arc="quiet_observation",
                warmth_level=0.18,
                sarcasm_level=0.16,
            ),
            broadcast=CognitiveBroadcast(label="resource_pressure", score=0.84),
        )

        payload = appraisal.to_dict()
        required_axes = {
            "valence",
            "arousal",
            "certainty",
            "agency",
            "controllability",
            "intimacy",
            "threat",
            "protectiveness",
            "jealousy_lite",
            "amusement",
            "fatigue",
            "tenderness",
        }

        self.assertEqual(payload["state_type"], "expressive_appraisal_state")
        self.assertTrue(required_axes.issubset(payload))
        self.assertEqual(appraisal.stance, "protective")
        self.assertGreaterEqual(appraisal.threat, 0.80)
        self.assertGreaterEqual(appraisal.protectiveness, 0.80)
        self.assertNotIn("emotion", appraisal.summary.lower())

    def test_low_persistent_guard_does_not_raise_protective_appraisal(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="general",
                protectiveness=0.08,
                irritation=0.04,
                confidence=0.70,
                arousal=0.18,
            ),
            ni_report=SimpleNamespace(drift_score=0.0, confidence=0.70, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(
                intent_label="ordinary_dialogue",
                session_arc="quiet_observation",
                warmth_level=0.18,
                sarcasm_level=0.16,
            ),
            broadcast=CognitiveBroadcast(label="low_salience", score=0.20),
        )

        self.assertNotEqual(appraisal.stance, "protective")
        self.assertLess(appraisal.threat, 0.66)
        self.assertLess(appraisal.protectiveness, 0.72)

    def test_attachment_chat_raises_intimacy_and_tenderness_without_calling_it_feeling(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="general",
                attachment=0.72,
                social_energy=0.66,
                tenderness=0.58,
                confidence=0.64,
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.68, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_emotional"),
            fe_plan=SimpleNamespace(
                intent_label="attachment_dialogue",
                session_arc="guarded_attachment",
                warmth_level=0.48,
                sarcasm_level=0.12,
            ),
            broadcast=CognitiveBroadcast(label="user_message", score=0.78),
            channel="chat",
            user_text="toi hoi buon va can o ben toi",
        )

        context = self.engine.render_prompt_context(appraisal)

        self.assertEqual(appraisal.stance, "tender_under_cold")
        self.assertGreaterEqual(appraisal.intimacy, 0.80)
        self.assertGreaterEqual(appraisal.tenderness, 0.70)
        self.assertIn("expressive/appraisal state", context)
        self.assertIn("pre-verbal attitude", context)
        self.assertIn("not an inner feeling claim", context)


class AppraisalEventCouplingTests(unittest.TestCase):
    """Lát 2: appraisal = f(sự-kiện × stake × kỳ vọng)."""

    def setUp(self):
        self.engine = AppraisalEngine()

    def _kwargs(self, broadcast):
        return dict(
            internal_state=PersistentInternalState(last_focus_kind="general", valence=0.05),
            ni_report=SimpleNamespace(drift_score=0.0, confidence=0.6, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(
                intent_label="ordinary_dialogue",
                session_arc="quiet_observation",
                warmth_level=0.20,
                sarcasm_level=0.0,
            ),
            broadcast=broadcast,
            channel="autonomous",
        )

    def test_sad_scene_with_stakes_lowers_valence_and_raises_tenderness(self):
        broadcast = CognitiveBroadcast(
            label="ambient_context",
            content="bạn đang xem một video buồn, nhân vật khóc một mình",
            score=0.40,
        )
        without = self.engine.evaluate(**self._kwargs(broadcast))
        with_stakes = self.engine.evaluate(**self._kwargs(broadcast), standing_stakes=DEFAULT_STANDING_STAKES)

        self.assertLess(with_stakes.valence, without.valence)
        self.assertGreater(with_stakes.tenderness, without.tenderness)
        self.assertTrue(any("event_affect" in e for e in with_stakes.evidence))

    def test_neutral_scene_does_not_shift_even_with_stakes(self):
        broadcast = CognitiveBroadcast(
            label="ambient_context",
            content="Visual Studio Code workspace open",
            score=0.30,
        )
        without = self.engine.evaluate(**self._kwargs(broadcast))
        with_stakes = self.engine.evaluate(**self._kwargs(broadcast), standing_stakes=DEFAULT_STANDING_STAKES)

        self.assertAlmostEqual(with_stakes.valence, without.valence, places=6)
        self.assertAlmostEqual(with_stakes.tenderness, without.tenderness, places=6)

    def test_no_stakes_keeps_legacy_behavior(self):
        broadcast = CognitiveBroadcast(
            label="ambient_context",
            content="bạn đang xem một video buồn, nhân vật khóc",
            score=0.40,
        )
        a = self.engine.evaluate(**self._kwargs(broadcast))
        b = self.engine.evaluate(**self._kwargs(broadcast), standing_stakes=None)
        self.assertAlmostEqual(a.valence, b.valence, places=6)


class AppraisalPersistenceTests(unittest.TestCase):
    """Lát 3: appraisal dịch chuyển và LƯU LẠI qua commit_turn."""

    def setUp(self):
        self.engine = InternalStateEngine()

    def test_commit_turn_persists_negative_appraisal_shift(self):
        state = PersistentInternalState(valence=0.10, tenderness=0.20, arousal=0.20)
        appraisal = SimpleNamespace(stance="tender_under_cold", valence=-0.50, tenderness=0.70, arousal=0.45)
        committed = self.engine.commit_turn(state, channel="autonomous", appraisal=appraisal)

        self.assertLess(committed.valence, state.valence)
        self.assertGreater(committed.tenderness, state.tenderness)
        self.assertGreater(committed.arousal, state.arousal)

    def test_commit_turn_without_appraisal_keeps_valence(self):
        state = PersistentInternalState(valence=0.10, tenderness=0.20, arousal=0.20)
        committed = self.engine.commit_turn(state, channel="autonomous", appraisal=None)
        self.assertEqual(committed.valence, state.valence)


if __name__ == "__main__":
    unittest.main()
