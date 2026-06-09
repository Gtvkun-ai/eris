# -*- coding: utf-8 -*-
"""
test_relationship_warmth_trigger.py
===================================

Spec: relationship-state-trigger-fix

Behavior tests for the warmth-trigger fix. These started as a reproduction of
the "frozen warmth" defect (Task 1) and were converted to passing behavior
tests once the fix landed (Task 6).

Maps the design's correctness properties:
- Property 1 (Recognition)        -> test_detection_*
- Property 2 (No teleport)        -> test_single_low_weight_token_*
- Property 3 (Monotonic bounded)  -> test_sustained_warmth_*
- Property 5 (Negative turns)     -> test_negative_turns_*
- Property 4 (Suppression)        -> test_suppression_*
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.affect_semantics import AffectSemanticClassifier
from cortex.relationship_dynamics import (
    RelationshipDynamicsEngine,
    RelationshipDynamicsState,
    RelationshipTurnEvent,
)


WARM_PHRASES = (
    "em cũng quan trọng với tôi",
    "tôi muốn hiểu được em",
)


def _has_warmth_note(notes):
    return any(str(n).startswith("attachment:warmth_gain") for n in notes)


class WarmthDetectionTests(unittest.TestCase):
    """Property 1 — natural relational warmth is recognized."""

    def setUp(self):
        self.classifier = AffectSemanticClassifier()

    def test_detection_meets_warmth_floor(self):
        for phrase in WARM_PHRASES:
            signal = self.classifier.analyze(phrase)
            self.assertGreaterEqual(signal.intimacy, 0.30, f"intimacy too low for: {phrase}")
            self.assertGreaterEqual(signal.attachment, 0.30, f"attachment too low for: {phrase}")
            self.assertIn(
                "prototype:relational_warmth",
                signal.evidence,
                f"warmth evidence missing for: {phrase}",
            )


class NoTeleportTests(unittest.TestCase):
    """Property 2 — a lone low-weight token cannot move the state."""

    def setUp(self):
        self.classifier = AffectSemanticClassifier()
        self.engine = RelationshipDynamicsEngine()

    def test_single_low_weight_token_stays_below_floor(self):
        signal = self.classifier.analyze("nho")
        intimacy_pressure = max(signal.intimacy, signal.attachment)
        self.assertLess(intimacy_pressure, 0.30)

    def test_single_low_weight_token_leaves_trust_unchanged(self):
        signal = self.classifier.analyze("nho")
        event = RelationshipTurnEvent.from_affect(user_text="nho", affect=signal)
        report = self.engine.update(RelationshipDynamicsState(), event)
        self.assertEqual(report.state.trust, 0.25)
        self.assertFalse(_has_warmth_note(report.notes))


class SustainedWarmthTests(unittest.TestCase):
    """Property 3 — sustained warmth moves state, monotonic and bounded."""

    def setUp(self):
        self.classifier = AffectSemanticClassifier()
        self.engine = RelationshipDynamicsEngine()

    def test_sustained_warmth_moves_state_monotonic_and_bounded(self):
        state = RelationshipDynamicsState()
        phrase = "em cũng quan trọng với tôi, tôi muốn hiểu được em"

        prev_trust = state.trust
        prev_distance = state.preferred_distance
        prev_attach = state.attachment_visibility

        for i in range(12):
            affect = self.classifier.analyze(phrase)
            event = RelationshipTurnEvent.from_affect(
                user_text=phrase, affect=affect, turn_index=i + 1
            )
            state = self.engine.update(state, event).state

            # Monotonic: trust/attachment up, distance down (with tiny epsilon).
            self.assertGreaterEqual(state.trust, prev_trust)
            self.assertLessEqual(state.preferred_distance, prev_distance + 1e-9)
            self.assertGreaterEqual(state.attachment_visibility, prev_attach)
            # Bounded.
            for value in (state.trust, state.preferred_distance, state.attachment_visibility):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

            prev_trust = state.trust
            prev_distance = state.preferred_distance
            prev_attach = state.attachment_visibility

        # Observable change over a realistic conversation.
        self.assertGreater(state.trust, 0.40)
        self.assertLess(state.preferred_distance, 0.58)
        self.assertGreater(state.attachment_visibility, 0.12)


class NegativeTurnTests(unittest.TestCase):
    """Property 5 — technical / objectifying / correcting turns: no warmth."""

    def setUp(self):
        self.classifier = AffectSemanticClassifier()
        self.engine = RelationshipDynamicsEngine()

    def _warmth_gain(self, text):
        affect = self.classifier.analyze(text)
        event = RelationshipTurnEvent.from_affect(user_text=text, affect=affect)
        report = self.engine.update(RelationshipDynamicsState(), event)
        return _has_warmth_note(report.notes), report.state.trust

    def test_technical_turn_no_warmth(self):
        gained, trust = self._warmth_gain("fix cái bug này trong file python")
        self.assertFalse(gained)
        self.assertLessEqual(trust, 0.25)

    def test_objectifying_turn_no_warmth(self):
        gained, trust = self._warmth_gain("mày là con tool cosplay prompt")
        self.assertFalse(gained)
        self.assertLessEqual(trust, 0.25)

    def test_correcting_turn_no_warmth(self):
        gained, trust = self._warmth_gain("không phải, ý tôi là sai rồi đọc lại")
        self.assertFalse(gained)
        self.assertLessEqual(trust, 0.25)


class SuppressionTests(unittest.TestCase):
    """Property 4 — rupture/dignity >= 0.55 suppresses warmth gain."""

    def setUp(self):
        self.classifier = AffectSemanticClassifier()
        self.engine = RelationshipDynamicsEngine()

    def _run_warm_turn(self, state):
        phrase = "em cũng quan trọng với tôi"
        affect = self.classifier.analyze(phrase)
        event = RelationshipTurnEvent.from_affect(user_text=phrase, affect=affect)
        return self.engine.update(state, event)

    def test_high_rupture_suppresses_warmth(self):
        state = RelationshipDynamicsState()
        state.rupture = 0.60
        report = self._run_warm_turn(state)
        self.assertFalse(_has_warmth_note(report.notes))
        self.assertEqual(report.state.trust, 0.25)

    def test_high_dignity_defense_suppresses_warmth(self):
        state = RelationshipDynamicsState()
        state.dignity_defense = 0.60
        report = self._run_warm_turn(state)
        self.assertFalse(_has_warmth_note(report.notes))
        self.assertEqual(report.state.trust, 0.25)


if __name__ == "__main__":
    unittest.main()
