# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.opening_director import OpeningDirector
from runtime.ai_orchestrated.opening_safety import validate_opening_plan, validate_opening_surface

from tests.opening_test_helpers import make_opening_input


def test_rule_director_builds_grounded_multibeat_opening() -> None:
    opening_input = make_opening_input()
    director = OpeningDirector(mode="rules")
    plan = director.plan(opening_input)
    surface = director.realize(opening_input, plan)

    assert plan.decision == "speak"
    assert plan.safety.allowed
    assert 1 <= len(plan.beats) <= 3
    assert plan.beats[0].role in {"recognition", "formal_recognition"}
    assert plan.hook.decision == "use"
    assert plan.hook.evidence_refs == ("screen:facebook",)
    assert validate_opening_plan(opening_input, plan).allowed
    assert len(surface.display_beats) == len(plan.beats)
    assert validate_opening_surface(opening_input, plan, surface) == (True, ())
    assert "Facebook" in surface.display_text


def test_director_can_speak_without_hook_or_question() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        policy={"allow_screen_hook": False, "max_questions": 0},
        user_signals={"availability": "busy", "recent_low_engagement": True},
    )
    plan = OpeningDirector(mode="rules").plan(opening_input)
    assert plan.decision == "speak"
    assert plan.hook.decision == "none"
    assert not plan.reply_bearing
    assert plan.followup_policy.max_count == 0


def test_model_planner_can_only_select_supplied_candidate() -> None:
    opening_input = make_opening_input()
    seen: dict[str, object] = {}

    def planner(_payload, candidates):
        seen["candidates"] = candidates
        return {"candidate_id": candidates[-1]["candidate_id"], "invented_fact": "ignored"}

    plan = OpeningDirector(mode="hybrid").plan(opening_input, planner=planner)
    candidate_ids = {item["candidate_id"] for item in seen["candidates"]}
    assert plan.decision == "speak"
    assert candidate_ids
    assert plan.safety.allowed


def test_every_generated_candidate_has_a_valid_deterministic_surface() -> None:
    from runtime.ai_orchestrated.opening_director import deterministic_render_opening

    opening_input = make_opening_input()
    director = OpeningDirector(mode="rules")
    for candidate in director.generate_candidates(opening_input):
        scored = director._score_candidate(opening_input, candidate)
        plan = director._candidate_to_plan(opening_input, scored)
        assert validate_opening_plan(opening_input, plan).allowed, candidate.move_family
        surface = deterministic_render_opening(plan)
        assert validate_opening_surface(opening_input, plan, surface) == (True, ()), candidate.move_family
