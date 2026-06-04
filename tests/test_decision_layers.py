import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.action_memory import ActionMemoryState
from cortex.action_planner import ActionPlanner
from cortex.action_utility import ActionContext, ActionScore, ActionUtilityReport, ActionUtilityScorer
from cortex.goal_persistence import GoalPersistenceEngine, GoalPersistenceState
from cortex.orientation_context import (
    ActivityIntent,
    ActivityIntentLabel,
    GoalRelation,
    GoalRelationLabel,
    OrientationSignal,
    SemanticContextProbe,
)
from cortex.orientation_semantics import HybridOrientationInterpreter
from cortex.semantic_hypothesis import SemanticHypothesis, SemanticHypothesisReport


class _StubLexicalInterpreter:
    def __init__(self, signal: OrientationSignal) -> None:
        self.signal = signal

    def estimate_orientation(self, probe: SemanticContextProbe) -> OrientationSignal:
        return self.signal


class _StubSemanticEngine:
    def __init__(self, *, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport) -> None:
        self.intent_report = intent_report
        self.relation_report = relation_report

    def compare(self, domain: str, text: str, *, anchors=(), labels=None) -> SemanticHypothesisReport:
        if "activity_intent" in domain:
            return self.intent_report
        return self.relation_report


class _StubScorer:
    def __init__(self, report: ActionUtilityReport) -> None:
        self.report = report
        self.calls = []

    def score(self, ctx: ActionContext) -> ActionUtilityReport:
        self.calls.append(ctx)
        return self.report


def _semantic_report(
    domain: str,
    label: str,
    *,
    confidence: float,
    ambiguity: float = 0.12,
    fallback_used: bool = False,
) -> SemanticHypothesisReport:
    hypothesis = SemanticHypothesis(
        domain=domain,
        label=label,
        score=confidence,
        confidence=confidence,
        raw_similarity=confidence,
        margin_from_next=0.24,
        prototype_prior=0.5,
        anchor_boost=0.0,
        is_fallback=fallback_used,
        evidence=(f"semantic={label}",),
    )
    return SemanticHypothesisReport(
        domain=domain,
        text="stub",
        hypotheses=(hypothesis,),
        dominant=hypothesis,
        ambiguity=ambiguity,
        confidence=confidence,
        semantic_available=True,
        encoder_model_id="stub",
        fallback_used=fallback_used,
        evidence=(f"semantic={label}",),
    )


def _utility_report(action: str, *, utility: float = 0.72) -> ActionUtilityReport:
    score = ActionScore(action=action, total=utility)
    score.add(utility, "stub_winner", "pressure")
    return ActionUtilityReport(
        selected_action=action,
        selected_utility=utility,
        scores={action: score},
        rhythm_phase="execute",
        transition_reason="execute: +0.72:stub_winner",
        memory_pressure=("action_memory_phase=execute",),
        selected_impulse="technical_help_impulse" if action == "practical_help" else "",
        impulse_scores=("impulse.technical_help_impulse=0.82",) if action == "practical_help" else (),
        impulse_arbitration={"selected": {"name": "technical_help_impulse", "total": 0.82}} if action == "practical_help" else {},
        body_bias_hint={},
    )


class GoalPersistenceEngineTests(unittest.TestCase):
    def test_active_goal_can_remain_background_without_intervention_permission(self):
        state = GoalPersistenceState(
            summary="fix action utility scoring regression",
            status="active",
            strength=0.64,
            confidence=0.72,
            actionability=0.66,
            intervention_permission=0.18,
            goal_type="debug_thread",
        )

        self.assertTrue(state.active)
        self.assertFalse(state.can_intervene)

    def test_weaker_internal_thread_does_not_replace_stronger_user_goal(self):
        engine = GoalPersistenceEngine()
        base = GoalPersistenceState(
            goal_id="goal_primary",
            summary="fix action utility scoring regression",
            source="user_message",
            status="active",
            strength=0.82,
            urgency=0.58,
            confidence=0.76,
            actionability=0.74,
            intervention_permission=0.62,
            coherence=0.78,
            goal_type="debug_thread",
            anchors=("action", "utility", "scoring"),
            updated_at=100.0,
            created_at=80.0,
        )

        after = engine.update(
            base,
            channel="autonomous",
            ni_report=SimpleNamespace(drift_score=0.10, should_raise_guard=False),
            thought_stream_report=SimpleNamespace(
                momentum=SimpleNamespace(
                    affordance="attention",
                    score=0.67,
                    tension=0.62,
                    topic_seed="resume session ritual continuity greeting",
                    evidence=("momentum=0.67",),
                ),
                active_attractor=None,
            ),
            now=160.0,
        )

        self.assertEqual(after.summary, base.summary)
        self.assertEqual(after.source, base.source)
        self.assertEqual(after.status, "active")
        self.assertIn("resume session ritual continuity greeting", after.recent_summaries)


class HybridOrientationInterpreterTests(unittest.TestCase):
    def test_explicit_avoidance_veto_beats_semantic_research_relabel(self):
        lexical = OrientationSignal(
            intent=ActivityIntent(ActivityIntentLabel.TECHNICAL_FOCUS.value, 0.64, ("lexical",)),
            relation=GoalRelation(GoalRelationLabel.ALIGNED.value, 0.58, ("lexical",)),
            orientation_coherence=0.62,
            goal_conflict_score=0.18,
            intervention_pressure=0.12,
            confidence=0.66,
            reason_span="lexical",
            evidence=("lexical",),
            channels={},
        )
        semantic_engine = _StubSemanticEngine(
            intent_report=_semantic_report("activity_intent", ActivityIntentLabel.RESEARCH.value, confidence=0.86),
            relation_report=_semantic_report("goal_relation", GoalRelationLabel.ALIGNED.value, confidence=0.82),
        )
        interpreter = HybridOrientationInterpreter(
            lexical_interpreter=_StubLexicalInterpreter(lexical),
            semantic_engine=semantic_engine,
        )

        result = interpreter.estimate_orientation(
            SemanticContextProbe(
                focus_kind="coding",
                current_text="toi dang ne viec nay, nhin vao src/runtime/coordinator.py cho qua",
                active_goal_strength=0.62,
                active_goal_intervention_permission=0.58,
                active_goal_summary="fix coordinator bug",
            )
        )

        self.assertEqual(result.intent.label, ActivityIntentLabel.POSSIBLE_AVOIDANCE.value)
        self.assertIn("hybrid:explicit_avoidance_veto", result.intent.evidence)

    def test_conflict_semantic_label_is_blocked_without_goal_permission(self):
        lexical = OrientationSignal(
            intent=ActivityIntent(ActivityIntentLabel.TECHNICAL_FOCUS.value, 0.60, ("lexical",)),
            relation=GoalRelation(GoalRelationLabel.UNKNOWN.value, 0.22, ("lexical",)),
            orientation_coherence=0.54,
            goal_conflict_score=0.20,
            intervention_pressure=0.18,
            confidence=0.58,
            reason_span="lexical",
            evidence=("lexical",),
            channels={},
        )
        semantic_engine = _StubSemanticEngine(
            intent_report=_semantic_report("activity_intent", ActivityIntentLabel.PLAY_OR_RECOVERY.value, confidence=0.84),
            relation_report=_semantic_report("goal_relation", GoalRelationLabel.CONFLICTING.value, confidence=0.88),
        )
        interpreter = HybridOrientationInterpreter(
            lexical_interpreter=_StubLexicalInterpreter(lexical),
            semantic_engine=semantic_engine,
        )

        result = interpreter.estimate_orientation(
            SemanticContextProbe(
                focus_kind="general",
                current_text="xem video giai tri mot chut",
                active_goal_strength=0.12,
                active_goal_intervention_permission=0.10,
            )
        )

        self.assertNotEqual(result.relation.label, GoalRelationLabel.CONFLICTING.value)
        self.assertLessEqual(result.intervention_pressure, 0.36)


class ActionMemoryStateTests(unittest.TestCase):
    def test_absorb_context_then_record_moves_from_watching_to_exposure(self):
        state = ActionMemoryState(continuity_pressure=0.34)

        state.absorb_context(
            channel="autonomous",
            snapshot=SimpleNamespace(idle_seconds=360.0),
            self_state=SimpleNamespace(state_label="settled"),
            conversation_dynamics=SimpleNamespace(mode="steady", conversation_pressure=0.0),
            relationship_dynamics=SimpleNamespace(dignity_defense=0.0, preferred_distance=0.0),
            goal_state=SimpleNamespace(active=True, strength=0.70, urgency=0.54, intervention_permission=0.20, can_intervene=False),
            now=100.0,
        )

        self.assertEqual(state.rhythm_phase, "watching")
        self.assertGreater(state.continuity_pressure, 0.0)

        state.record(
            action="inner_whim",
            family="inner_whim",
            channel="autonomous",
            spoke=True,
            utility=0.66,
            now=120.0,
        )

        self.assertEqual(state.rhythm_phase, "exposure")
        self.assertGreater(state.exposure_recoil, 0.0)
        self.assertEqual(state.recent_actions(), ("inner_whim",))


class ActionUtilityScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = ActionUtilityScorer()

    def test_background_goal_without_permission_penalizes_reengagement(self):
        ctx = ActionContext(
            channel="autonomous",
            goal_state=SimpleNamespace(
                active=True,
                strength=0.82,
                urgency=0.52,
                confidence=0.74,
                actionability=0.66,
                intervention_permission=0.12,
                can_intervene=False,
                goal_type="debug_thread",
            ),
            action_memory=ActionMemoryState(),
            now=100.0,
        )

        report = self.scorer.score(ctx)

        self.assertLess(report.scores["reengagement"].total, report.scores["no_speech"].total)
        self.assertTrue(
            any("goal_background_only_no_proactive_pull" in reason for reason in report.scores["reengagement"].reasons)
        )

    def test_technical_help_impulse_can_win_without_social_noise(self):
        ctx = ActionContext(
            channel="autonomous",
            action_memory=ActionMemoryState(),
            impulse_arbitration={
                "selected": {"name": "technical_help_impulse", "total": 0.84, "evidence": ("task",)},
                "candidates": [
                    {"name": "technical_help_impulse", "total": 0.84},
                    {"name": "silence_impulse", "total": 0.30},
                ],
            },
            now=100.0,
        )

        report = self.scorer.score(ctx)

        self.assertEqual(report.selected_action, "practical_help")
        self.assertGreater(report.scores["practical_help"].total, report.scores["random_chatter"].total)


class ActionPlannerTests(unittest.TestCase):
    def test_planner_maps_practical_help_to_direct_style_contract(self):
        planner = ActionPlanner(scorer=_StubScorer(_utility_report("practical_help")))

        plan = planner.plan(
            channel="chat",
            user_text="fix action planner scoring bug",
            concrete_signals=("tests are failing",),
            notes=("meaning_shift=true",),
        )

        self.assertTrue(plan.should_speak)
        self.assertEqual(plan.speech_act, "practical_help")
        self.assertEqual(plan.speech_intent, "practical_help")
        self.assertEqual(plan.style_attitude, "thuc dung, ro rang")
        self.assertIn("debug", plan.style_limit)
        self.assertNotIn("no_screen_claim", plan.risk_flags)

    def test_planner_uses_local_memory_when_external_action_memory_is_missing(self):
        planner = ActionPlanner(scorer=_StubScorer(_utility_report("inner_whim", utility=0.61)))

        plan = planner.plan(
            channel="autonomous",
            notes=("spontaneous_life=1",),
            auto_record_local_memory=True,
        )

        self.assertTrue(plan.should_speak)
        self.assertEqual(planner._local_action_memory.recent_actions(), ("inner_whim",))
        self.assertEqual(planner._local_action_memory.recent_families(), ("inner_whim",))


if __name__ == "__main__":
    unittest.main()
