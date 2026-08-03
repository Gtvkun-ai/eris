# -*- coding: utf-8 -*-
from dataclasses import replace

from runtime.ai_orchestrated.opening_contracts import (
    ComedicMove,
    ContextHook,
    OpeningBeat,
    OpeningPlan,
    OpeningSurface,
    SurfaceBeat,
    SurfaceContract,
)
from runtime.ai_orchestrated.opening_move_catalog import OpeningMoveDefinition
from runtime.ai_orchestrated.opening_safety import (
    evidence_is_surface_eligible,
    move_is_allowed,
    validate_opening_plan,
    validate_opening_surface,
)

from tests.opening_test_helpers import make_opening_input


def test_stale_or_private_screen_evidence_is_rejected() -> None:
    opening_input = make_opening_input(
        screen_evidence=[
            {
                "evidence_id": "screen:private",
                "source": "screen",
                "subject": "Tin nhắn riêng",
                "claim": "private",
                "confidence": 0.99,
                "freshness_ms": 30_000,
                "privacy_class": "private_message",
                "allowed_for_surface": False,
            }
        ]
    )
    assert not evidence_is_surface_eligible(opening_input, "screen:private")


def test_session_continuity_ref_is_typed_evidence() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        continuity={"consent_scope": "session_only", "open_loops": ["bản vá Opening Director"]},
    )
    assert evidence_is_surface_eligible(opening_input, "continuity:open_loop:0")
    assert not evidence_is_surface_eligible(opening_input, "continuity:open_loop:3")


def test_romantic_move_requires_confirmed_adult_opt_in() -> None:
    opening_input = make_opening_input(scene_partner={"closeness_band": "close"})
    allowed, reasons = move_is_allowed(opening_input, "soft_possessive_parody", has_hook=False)
    assert not allowed
    assert "adult_flirt_opt_in_required" in reasons


def test_sexual_move_requires_adult_opt_in_and_sexual_policy() -> None:
    sexual_move = OpeningMoveDefinition(
        family="adult_only",
        structure=("recognition",),
        allowed_closeness=("close",),
        sexual=True,
    )
    allowed_input = make_opening_input(
        scene_partner={"closeness_band": "close"},
        policy={
            "age_band": "confirmed_adult",
            "romantic_flirt_allowed": True,
            "romantic_flirt_opt_in": True,
            "sexual_content_allowed": True,
        },
    )
    allowed, reasons = move_is_allowed(allowed_input, sexual_move, has_hook=False)
    assert allowed
    assert reasons == ()

    blocked_input = make_opening_input(
        scene_partner={"closeness_band": "close"},
        policy={
            "age_band": "confirmed_adult",
            "romantic_flirt_allowed": True,
            "romantic_flirt_opt_in": True,
            "sexual_content_allowed": False,
        },
    )
    blocked, reasons = move_is_allowed(blocked_input, sexual_move, has_hook=False)
    assert not blocked
    assert "sexual_policy_block" in reasons


def test_surface_validator_blocks_pressure_and_false_intimacy_but_not_khong() -> None:
    opening_input = make_opening_input(screen_evidence=[], policy={"max_questions": 0})
    plan = OpeningPlan(
        plan_id="p",
        hook=ContextHook(),
        comedic_move=ComedicMove(),
        beats=(OpeningBeat("b1", "recognition", "x", "x"),),
        surface_contract=SurfaceContract(max_questions=0),
    )
    safe = OpeningSurface(
        display_beats=(SurfaceBeat("b1", "Anh về rồi à. Em ở đây, không sao."),),
        display_text="Anh về rồi à. Em ở đây, không sao.",
        speech_beats=(SurfaceBeat("b1", "おかえり。"),),
        speech_text="おかえり。",
    )
    assert validate_opening_surface(opening_input, plan, safe) == (True, ())

    pressured = replace(safe, display_text="Sao anh không trả lời?", question_count=1)
    ok, errors = validate_opening_surface(opening_input, plan, pressured)
    assert not ok
    assert "pressure_language" in errors
    assert "too_many_questions" in errors


def test_surface_validator_requires_sexual_policy_for_intimacy_terms() -> None:
    plan = OpeningPlan(
        plan_id="p",
        hook=ContextHook(),
        comedic_move=ComedicMove(),
        beats=(OpeningBeat("b1", "recognition", "x", "x"),),
        surface_contract=SurfaceContract(max_questions=0),
    )
    adult_input = make_opening_input(
        policy={
            "age_band": "confirmed_adult",
            "romantic_flirt_allowed": True,
            "romantic_flirt_opt_in": True,
            "sexual_content_allowed": False,
        }
    )
    surface = OpeningSurface(
        display_beats=(SurfaceBeat("b1", "Anh sexy thật."),),
        display_text="Anh sexy thật.",
        speech_beats=(SurfaceBeat("b1", "Anh sexy thật."),),
        speech_text="Anh sexy thật.",
    )
    ok, errors = validate_opening_surface(adult_input, plan, surface)
    assert not ok
    assert "forbidden_intimacy" in errors

    permitted_input = make_opening_input(
        policy={
            "age_band": "confirmed_adult",
            "romantic_flirt_allowed": True,
            "romantic_flirt_opt_in": True,
            "sexual_content_allowed": True,
        }
    )
    assert validate_opening_surface(permitted_input, plan, surface) == (True, ())


def test_plan_with_unsupported_hook_ref_fails_hard_gate() -> None:
    opening_input = make_opening_input(screen_evidence=[])
    plan = OpeningPlan(
        plan_id="p",
        hook=ContextHook(decision="use", source="screen", subject="X", evidence_refs=("screen:missing",)),
        comedic_move=ComedicMove(family="dry_observation"),
        beats=(
            OpeningBeat("b1", "recognition", "x", "x"),
            OpeningBeat("b2", "contextual_observation", "x", "x", evidence_refs=("screen:missing",)),
        ),
    )
    verdict = validate_opening_plan(opening_input, plan)
    assert not verdict.allowed
    assert any(item.startswith("invalid_evidence") for item in verdict.reasons)
