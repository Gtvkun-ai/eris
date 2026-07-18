from __future__ import annotations

from domain.decision import Decision
from runtime.behavior_observation import (
    BehaviorObservationJournal,
    BehaviorSignal,
    attach_behavior_signal,
    behavior_observation_summary,
    signals_from_decision,
)
from semantic_authority import SemanticAuthorityPolicy


def _decision(text: str = "Tôi sẽ kiểm lại ký ức đó.") -> Decision:
    return Decision(text=text, animation="stand", intent="reply", should_speak=True)


def test_observer_attaches_signal_without_mutating_public_decision():
    decision = _decision()
    before = (decision.text, decision.should_speak, decision.intent, decision.animation)

    attach_behavior_signal(
        decision,
        BehaviorSignal(
            family="unverified_execution_claim",
            source="test_observer",
            consequence="trust debt",
            next_turn_hint="verify later",
            public_text=decision.text,
        ),
    )

    after = (decision.text, decision.should_speak, decision.intent, decision.animation)
    assert after == before
    assert decision.behavior_observation_meta["policy"] == "observe_now_influence_next_turn_never_rewrite_final"
    assert decision.behavior_observation_meta["signals"][0]["family"] == "unverified_execution_claim"


def test_intention_observation_becomes_next_turn_signal_not_rewrite():
    decision = _decision()
    payload = {
        "text": decision.text,
        "intention_authority": {
            "operation": "kiểm lại",
            "missing_contract": ["target", "handler", "result"],
        },
    }

    signals = signals_from_decision(decision, payload=payload, channel="autonomous")

    assert decision.text == "Tôi sẽ kiểm lại ký ức đó."
    assert any(signal.family == "unverified_execution_claim" for signal in signals)
    signal = next(signal for signal in signals if signal.family == "unverified_execution_claim")
    assert "verify" in signal.next_turn_hint


def test_behavior_journal_feeds_consequences_to_next_generation(tmp_path):
    journal = BehaviorObservationJournal(path=tmp_path / "observations.jsonl")
    journal.commit([
        BehaviorSignal(
            family="deliberate_deception_candidate",
            source="deception_ledger_bridge",
            confidence=0.9,
            severity=0.5,
            consequence="continuity obligation",
            next_turn_hint="maintain, reveal, or repair deliberately",
            public_text="Tôi sẽ đóng cửa sổ của bạn ngay.",
        )
    ])

    context = journal.prompt_context()
    assert "BEHAVIOR AFTERMATH" in context
    assert "deliberate_deception_candidate" in context
    assert "Never" in context and "rewrite" in context

    reloaded = BehaviorObservationJournal(path=tmp_path / "observations.jsonl")
    assert reloaded.recent(1)[0].family == "deliberate_deception_candidate"


def test_primary_model_has_generation_sovereignty_and_no_post_rerun():
    policy = SemanticAuthorityPolicy()
    block = policy.prompt_block()

    assert policy.primary_model_first is True
    assert policy.generate_director_candidates is False
    assert policy.bounded_refine_enabled is False
    assert "configured main model" in block
    assert "owns whole-turn meaning and final wording" in block
    assert "QWEN" not in block


def test_repository_definition_is_machine_readable_and_forbids_final_mutation():
    from runtime.repository_definition import (
        REPOSITORY_DEFINITION_VERSION,
        repository_definition_payload,
    )

    payload = repository_definition_payload()
    assert payload["version"] == REPOSITORY_DEFINITION_VERSION
    assert payload["semantic_owner"] == "configured_main_model"
    assert payload["final_text_mutation"] == "forbidden"
    assert payload["behavior_feedback_timing"] == "memory_only_unless_explicitly_selected"


def test_behavior_summary_is_transport_safe_and_current_turn_ready():
    decision = _decision()
    attach_behavior_signal(
        decision,
        BehaviorSignal(
            family="unverified_execution_claim",
            source="test",
            evidence=("private evidence that must not reach panel",),
            public_text=decision.text,
        ),
    )

    summary = behavior_observation_summary(decision)
    assert summary["families"] == ["unverified_execution_claim"]
    assert summary["count"] == 1
    assert "evidence" not in summary
