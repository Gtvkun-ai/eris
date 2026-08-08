# -*- coding: utf-8 -*-
"""Regression V27: opening đa dạng phải đến từ motive tái nhập phiên."""
from __future__ import annotations

from types import SimpleNamespace

from runtime.ai_orchestrated.opening_director import OpeningDirector, deterministic_render_opening
from runtime.ai_orchestrated.opening_history import OpeningHistoryStore
from runtime.ai_orchestrated.opening_reentry import build_session_reentry_context
from tests.opening_test_helpers import make_opening_input


def _reentry(*, seconds: float, now: float = 10_000.0, scene_partner=None, evidence=(), open_loops=()):
    return build_session_reentry_context(
        SimpleNamespace(),
        now=now,
        seconds_since_last_session=seconds,
        restart_detected=False,
        greeted_recently=False,
        open_loops=open_loops,
        evidence_payloads=evidence,
        scene_partner=scene_partner or {},
        time_of_day="morning",
    )


def test_absence_boost_is_nonlinear_and_restart_like_gap_is_small() -> None:
    quick = _reentry(seconds=30)
    hours = _reentry(seconds=4 * 3600)
    day = _reentry(seconds=18 * 3600)
    assert quick["return_salience"] < hours["return_salience"] < day["return_salience"]
    assert quick["motive_boosts"]["reconnect"] < hours["motive_boosts"]["reconnect"]


def test_old_boundary_becomes_historical_risk_not_hard_block() -> None:
    context = _reentry(
        seconds=3 * 3600,
        now=20_000.0,
        scene_partner={
            "boundary_flags": ["explicit_social_boundary"],
            "updated_at": 1_000.0,
            "closeness_band": "familiar",
            "tease_tolerance_estimate": 0.8,
            "tease_tolerance_confidence": 0.8,
        },
    )
    assert context["current_boundary_active"] is False
    assert context["historical_boundary_present"] is True
    assert context["motive_boosts"]["playful_protest"] < context["motive_boosts"]["reconnect"]


def test_recent_boundary_is_current_and_zeroes_opening_boosts() -> None:
    context = _reentry(
        seconds=3 * 3600,
        now=20_000.0,
        scene_partner={
            "boundary_flags": ["explicit_social_boundary"],
            "updated_at": 19_700.0,
        },
    )
    assert context["current_boundary_active"] is True
    assert max(context["motive_boosts"].values()) == 0.0


def test_social_probe_can_open_without_seed_or_screen() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        reentry={
            "absence_band": "short_absence",
            "motive_boosts": {"reconnect": 0.24, "social_probe": 0.95, "quiet_acknowledgement": 0.20},
            "motive_subjects": {"social_probe": "thăm dò một điều còn chưa biết về user"},
        },
    )
    director = OpeningDirector(mode="rules")
    plan = director.plan(opening_input)
    assert plan.encounter.intent == "social_probe"
    assert plan.hook.decision == "none"
    assert "social_probe" in plan.beat_shape
    assert deterministic_render_opening(plan).question_count == 1


def test_grounded_morning_scene_comment_can_beat_plain_reconnect() -> None:
    opening_input = make_opening_input(
        screen_evidence=[{
            "evidence_id": "screen:youtube",
            "source": "screen",
            "kind": "foreground_app",
            "subject": "YouTube",
            "claim": "YouTube là ứng dụng foreground",
            "confidence": 0.94,
            "freshness_ms": 500,
            "privacy_class": "ordinary_ui",
            "allowed_for_surface": True,
        }],
        session_state={"time_of_day": "morning"},
        reentry={
            "absence_band": "few_hours",
            "motive_boosts": {"reconnect": 0.32, "scene_comment": 0.96, "quiet_acknowledgement": 0.20},
            "motive_subjects": {"scene_comment": "YouTube"},
        },
    )
    plan = OpeningDirector(mode="rules").plan(opening_input)
    surface = deterministic_render_opening(plan)
    assert plan.encounter.intent == "scene_comment"
    assert plan.hook.source == "screen"
    assert "YouTube" in surface.display_text
    assert "đầu ngày" in surface.display_text


def test_playful_protest_only_wins_when_relational_fit_is_high() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        scene_partner={
            "closeness_band": "familiar",
            "tease_tolerance_estimate": 0.90,
            "tease_tolerance_confidence": 0.90,
        },
        reentry={
            "absence_band": "few_hours",
            "motive_boosts": {"reconnect": 0.45, "playful_protest": 0.98, "quiet_acknowledgement": 0.20},
        },
    )
    plan = OpeningDirector(mode="rules").plan(opening_input)
    assert plan.encounter.intent == "playful_protest"
    assert "Mấy tiếng" in deterministic_render_opening(plan).display_text


def test_history_tracks_motive_family_not_only_wording() -> None:
    store = OpeningHistoryStore()
    opening_input = make_opening_input(
        screen_evidence=[],
        reentry={"motive_boosts": {"social_probe": 0.95, "reconnect": 0.20}},
    )
    director = OpeningDirector(history=store, mode="rules")
    plan = director.plan(opening_input)
    store.append_plan(plan, session_id="s1", display_text=deterministic_render_opening(plan).display_text)
    assert store.motive_on_cooldown("social_probe", sessions=2)
    assert store.snapshot()[-1].motive_family == "social_probe"
