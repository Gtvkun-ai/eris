from dataclasses import replace

from runtime.pedagogical_contracts import (
    ComprehensionState,
    TeachingConcept,
    TeachingPlan,
    TeachingReceipt,
)
from runtime.pedagogical_controller import (
    expire_if_needed,
    note_audio_finished,
    note_public_commit,
    observe_user_turn,
    select_next_action,
    start_episode,
)


def _plan():
    return TeachingPlan(
        "Understand the Core 7 model",
        (
            TeachingConcept("core-7", "Core 7 is about escaping stuckness.", "Explain Core 7."),
            TeachingConcept("contrast", "Core 8 differs in its motivation.", "Contrast Core 7 and 8."),
            TeachingConcept("apply", "Apply the distinction to an example.", "Apply the model."),
        ),
    )


def _episode_with_chunk():
    return start_episode(_plan(), now=100.0)


def test_acknowledgement_does_not_increase_mastery():
    episode = _episode_with_chunk()
    result = observe_user_turn(episode, "Ừ, hiểu rồi.", evidence=(), now=101.0)
    assert result.episode.comprehension.estimated_mastery == episode.comprehension.estimated_mastery
    assert "self_report_understood" in result.evidence_codes


def test_topic_change_cannot_turn_paraphrase_tag_into_mastery():
    episode = _episode_with_chunk()
    result = observe_user_turn(
        episode, "Anyway, about something else.",
        evidence=("topic_change", "user_paraphrase"), now=101.0,
    )
    assert result.episode.comprehension.estimated_mastery == episode.comprehension.estimated_mastery
    assert "topic_change" in result.evidence_codes


def test_correct_paraphrase_advances_current_concept():
    episode = _episode_with_chunk()
    result = observe_user_turn(
        episode,
        "7 muốn thoát cảm giác bị mắc kẹt, không chỉ là người nói nhiều.",
        evidence=("user_paraphrase",), now=101.0,
    )
    assert result.episode.comprehension.estimated_mastery > episode.comprehension.estimated_mastery
    assert result.action.kind in {"advance", "probe", "complete"}


def test_user_correction_enters_repair_without_lowering_user_mastery():
    episode = _episode_with_chunk()
    result = observe_user_turn(
        episode, "Không, bạn đang hiểu sai ý mình.", evidence=("eris_corrected",), now=101.0,
    )
    assert result.episode.status == "repairing"
    assert result.episode.comprehension.estimated_mastery == episode.comprehension.estimated_mastery


def test_two_stalls_force_wait():
    episode = replace(_episode_with_chunk(), consecutive_stalls=1)
    result = select_next_action(episode, now=101.0)
    assert result.kind == "wait"


def test_mismatched_receipts_are_not_consumed():
    episode = _episode_with_chunk()
    receipts = (
        TeachingReceipt("other", episode.plan_revision, episode.pending_chunk.chunk_id),
        TeachingReceipt(episode.episode_id, episode.plan_revision + 1, episode.pending_chunk.chunk_id),
        TeachingReceipt(episode.episode_id, episode.plan_revision, "other-chunk"),
    )
    assert all(note_public_commit(episode, receipt) == episode for receipt in receipts)


def test_matching_receipt_starts_audio_and_audio_completion_waits_for_user():
    episode = _episode_with_chunk()
    receipt = TeachingReceipt(episode.episode_id, episode.plan_revision, episode.pending_chunk.chunk_id)
    speaking = note_public_commit(episode, receipt)
    assert speaking.status == "speaking"
    assert speaking.autonomous_chunks_used == 1
    assert note_audio_finished(speaking, now=101.0).status == "waiting_user"


def test_repeated_focused_question_marks_uncertainty_without_mastery_gain():
    episode = replace(
        _episode_with_chunk(),
        comprehension=ComprehensionState(estimated_mastery=0.4, confidence=0.7, current_concept_id="core-7"),
    )
    result = observe_user_turn(episode, "But why does that make 7 different?", evidence=("focused_question",), now=101.0)
    assert "repeated_focused_question" in result.evidence_codes
    assert result.episode.comprehension.estimated_mastery == 0.4
    assert result.episode.comprehension.confidence < 0.7


def test_explicit_misconception_assertion_is_a_candidate():
    episode = _episode_with_chunk()
    result = observe_user_turn(
        episode, "Core 7 just means talking a lot.", evidence=("misconception_assertion",), now=101.0,
    )
    assert "candidate_misconception" in result.evidence_codes
    assert result.action.kind == "repair"


def test_episode_expires_after_ten_minutes():
    episode = _episode_with_chunk()
    assert episode.expires_at == 700.0
    assert expire_if_needed(episode, now=700.0).status == "expired"


def test_autonomous_budget_exhaustion_forces_wait():
    episode = replace(_episode_with_chunk(), autonomous_chunks_used=2)
    assert select_next_action(episode, now=101.0).kind == "wait"
