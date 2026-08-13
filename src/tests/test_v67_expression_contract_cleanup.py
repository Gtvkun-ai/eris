# -*- coding: utf-8 -*-
"""Regression cho cleanup final của native expression contract V67.

Các test này cố ý khóa *ownership*, không khóa vài con số threshold:
- public speech phải có typed ExpressionCommitment;
- ID lifecycle cũ không được giả làm commitment;
- reply_expected/user_busy không đi vào expression policy;
- capability speech chỉ là realization path của một commitment cần grounding.
"""
from pathlib import Path
from types import SimpleNamespace

from cortex.subject.expression_commitment import commitment_payload, is_committed_speech
from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from runtime.subject_proposals import AutonomousProposalSource


def _candidate(*, topic="một ý tự thân của Eris", committed=True, grounding=False):
    return SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat" if not grounding else "screen_comment",
        topic=topic,
        speech_act="share_opinion" if not grounding else "comment_on_grounded_screen",
        anchor_type="internal" if not grounding else "environment",
        anchor_id="v67:test",
        evidence_refs=("evidence:v67",),
        requires_grounding=grounding,
        confidence=0.8,
        relevance=0.8,
        expression_urge_id="urge:legacy:v67",
        expression_commitment=(
            commitment_payload(
                origin="test",
                source_id="commit:v67",
                semantic_target=topic,
                motive="share",
                pressure=0.8,
                freshness=0.9,
                persistence=0.8,
            )
            if committed else {}
        ),
    )


def _aff(candidate):
    return SimpleNamespace(
        affordance_id="aff:v67",
        owner="test_owner",
        candidate=candidate,
        metadata={"intention_id": "intention:legacy:v67"},
    )


def _board(*, reply_expected=False, user_busy=False):
    return TypedCognitiveBlackboard(
        now=1000.0,
        reply_expected=reply_expected,
        user_busy=user_busy,
        seconds_since_user=5.0,
        seconds_since_assistant=40.0,
    )


def test_legacy_ids_are_not_expression_authority():
    legacy_only = SimpleNamespace(
        action_kind="speak",
        arguments={"expression_urge_id": "urge:old", "intention_id": "intention:old"},
    )
    assert is_committed_speech(legacy_only) is False


def test_public_proposal_rejects_candidate_without_typed_commitment():
    assert AutonomousProposalSource.from_affordance(
        _aff(_candidate(committed=False)), turn_id="autonomous:v67"
    ) is None


def test_materializer_needs_no_compatibility_flag_and_ignores_reply_expected(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    decision = controller.decide(_board(reply_expected=True, user_busy=True), _candidate())
    assert decision.action is InitiativeAction.SPEECH
    assert decision.reason == "expression_committed"
    assert decision.speech_intent is not None
    assert decision.speech_intent.expression_commitment["commitment_id"]


def test_materializer_fails_closed_without_commitment(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    decision = controller.decide(_board(), _candidate(committed=False))
    assert decision.action is InitiativeAction.NO_OP
    assert decision.reason == "candidate_without_expression_commitment"


def test_expression_policy_contains_only_self_density_and_repeat(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    signal = controller.policy_signals(_board(reply_expected=True, user_busy=True), (_aff(_candidate()),))["aff:v67"]
    assert "reply_expected" not in signal
    assert "reply_cost" not in signal
    assert "user_busy" not in signal
    assert "busy_cost" not in signal
    assert "recent_user_cost" not in signal
    assert {"cooldown_cost", "repeat_cost", "global_budget_pressure", "kind_budget_pressure"} <= set(signal)


def test_reply_expected_does_not_change_silence_or_body_scores():
    subject = SimpleNamespace(substrate=SimpleNamespace(
        action_efficacy=0.5, processing_capacity=1.0, project_viability=0.5
    ))
    source = AutonomousProposalSource(subject)
    plain, _ = source.collect(_board(reply_expected=False), (), turn_id="a")
    waiting, _ = source.collect(_board(reply_expected=True), (), turn_id="b")

    def action(rows, name):
        return next(item for item in rows if item["action_kind"] == name)

    for kind in ("silence", "body_only"):
        left = action(plain, kind)
        right = action(waiting, kind)
        for key in ("expected_need_relief", "expected_action_efficacy", "commitment_conflict"):
            assert left[key] == right[key]
        assert left["need_effects"] == right["need_effects"]


def test_capability_speech_exists_only_as_grounding_path_for_commitment():
    subject = SimpleNamespace(substrate=SimpleNamespace(
        action_efficacy=0.6, processing_capacity=0.8, project_viability=0.5
    ))
    source = AutonomousProposalSource(subject)

    committed_rows, _ = source.collect(
        _board(), (_aff(_candidate(grounding=True)),), turn_id="grounded"
    )
    route = [row for row in committed_rows if row.get("arguments", {}).get("capability_route")]
    assert len(route) == 1
    assert route[0]["arguments"]["expression_commitment"]

    uncommitted_rows, _ = source.collect(
        _board(), (_aff(_candidate(committed=False, grounding=True)),), turn_id="uncommitted"
    )
    assert not [row for row in uncommitted_rows if row.get("arguments", {}).get("capability_route")]


def test_production_code_has_no_committed_by_neuro_compatibility_path():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runtime" / "ai_orchestrated" / "initiative.py").read_text(encoding="utf-8")
    pipeline = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    assert "committed_by_neuro" not in source
    assert "committed_by_neuro" not in pipeline
