# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.opening_director import OpeningDirector
from runtime.ai_orchestrated.opening_history import OpeningHistoryStore, semantic_overlap, surface_hash

from tests.opening_test_helpers import make_opening_input


def test_history_is_idempotent_and_redacted() -> None:
    store = OpeningHistoryStore()
    opening_input = make_opening_input()
    plan = OpeningDirector(history=store, mode="rules").plan(opening_input)
    store.append_plan(plan, session_id="s", display_text="Anh về rồi à.", hook_subject_class="social_media")
    store.append_plan(plan, session_id="s", display_text="Anh về rồi à.", hook_subject_class="social_media")
    records = store.snapshot()
    assert len(records) == 1
    assert records[0].hook_subject_class == "social_media"
    assert "Facebook" not in str(records[0].to_dict())
    assert store.move_on_cooldown(plan.comedic_move.family, sessions=4)
    assert store.exact_duplicate("Anh về rồi à.")


def test_question_ignore_temporarily_blocks_startup_questions() -> None:
    store = OpeningHistoryStore()
    opening_input = make_opening_input()
    for index in range(2):
        plan = OpeningDirector(history=store, mode="rules").plan(opening_input)
        store.append_plan(
            plan,
            session_id=f"s{index}",
            display_text=f"Mở đầu {index}?",
            hook_subject_class="social_media",
            question_ignored=True,
        )
    assert store.question_temporarily_blocked()


def test_hash_and_semantic_overlap_are_deterministic() -> None:
    assert surface_hash("Chào anh") == surface_hash("  chào ANH! ")
    assert semantic_overlap("phủ nhận để ý", "phủ nhận việc để ý") > 0.4
