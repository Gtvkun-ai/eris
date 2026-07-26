# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace


def test_commentary_cadence_requires_deliberation_after_maximum_quiet(monkeypatch) -> None:
    from runtime.ai_orchestrated import commentary_cadence as module

    settings = {
        "enabled": True,
        "desired_interval_seconds": 60,
        "maximum_quiet_seconds": 120,
        "startup_delay_seconds": 8,
        "minimum_user_silence_seconds": 12,
    }
    monkeypatch.setattr(module, "_setting", lambda name, default: settings.get(name, default))
    cadence = module.CommentaryCadence()
    expectation = cadence.evaluate(
        now=1121.0,
        last_commentary_at=1000.0,
        session_started_at=1000.0,
        seconds_since_user=30.0,
        seconds_since_assistant=121.0,
        discourse_open=False,
        perception_delta=False,
        activity_event=False,
        has_public_seed=False,
        telemetry={},
    )
    assert expectation.due is True
    assert expectation.required is True
    assert expectation.reason == "maximum_quiet_reached"
    assert expectation.anchor_kind == "persona_presence"


def test_commentary_cadence_never_forces_over_active_user(monkeypatch) -> None:
    from runtime.ai_orchestrated import commentary_cadence as module

    monkeypatch.setattr(module, "_setting", lambda name, default: {
        "enabled": True,
        "desired_interval_seconds": 60,
        "maximum_quiet_seconds": 120,
        "startup_delay_seconds": 8,
        "minimum_user_silence_seconds": 12,
    }.get(name, default))
    expectation = module.CommentaryCadence().evaluate(
        now=1300.0,
        last_commentary_at=1000.0,
        session_started_at=1000.0,
        seconds_since_user=2.0,
        seconds_since_assistant=300.0,
        discourse_open=True,
        perception_delta=True,
        activity_event=True,
        has_public_seed=True,
        telemetry={"user_busy": True},
    )
    assert expectation.due is False
    assert expectation.required is False
    assert expectation.reason == "user_busy"


def test_heart_metaphor_stays_in_conversation_instead_of_web_route() -> None:
    from runtime.source_grounding import SourceGroundingEngine

    report = SourceGroundingEngine().analyze(
        "ý là nhìn vào trái tim nhỏ bé này",
        allow_web=False,
    )
    assert report.primary_source == "user_text"
    assert report.grounding_source == "user_text"
    assert "web_access_or_search_result" not in report.missing_evidence


def test_relational_bid_anchor_comes_from_typed_frame() -> None:
    from runtime.cognition.turn_anchor import anchor_from_semantic_frame

    frame = {
        "version": "semantic_frame.v1",
        "discourse_relation": "relational_bid",
        "user_act": "closeness_bid",
        "target": "assistant",
    }
    assert anchor_from_semantic_frame(frame) == "closeness_bid"


def test_self_turn_does_not_release_baton_while_chat_generation_is_active(monkeypatch) -> None:
    from runtime.ai_orchestrated.self_turn_pipeline import SelfTurnPipeline

    monkeypatch.setattr("runtime.ai_orchestrated.self_turn_pipeline.time.sleep", lambda _seconds: None)
    host = SimpleNamespace(
        chat_mode=True,
        _chat_processing=True,
        interaction_clock=SimpleNamespace(busy=False),
        logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
    )
    pipeline = object.__new__(SelfTurnPipeline)
    pipeline.host = host
    assert pipeline._acquire_baton() is False
    assert host.chat_mode is True


def test_self_turn_releases_baton_via_chat_cycle_owner(monkeypatch) -> None:
    from runtime.ai_orchestrated.self_turn_pipeline import SelfTurnPipeline

    monkeypatch.setattr("runtime.ai_orchestrated.self_turn_pipeline.time.sleep", lambda _seconds: None)
    calls: list[str] = []
    host = SimpleNamespace(
        chat_mode=True,
        _chat_processing=False,
        interaction_clock=SimpleNamespace(busy=False),
        logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
        _conversation_went_stale=lambda: True,
    )

    def _end_chat_cycle() -> None:
        calls.append("ended")
        host.chat_mode = False

    host._end_chat_cycle = _end_chat_cycle
    pipeline = object.__new__(SelfTurnPipeline)
    pipeline.host = host
    assert pipeline._acquire_baton() is True
    assert calls == ["ended"]
    assert host.chat_mode is False


def test_runtime_settings_v3_migrates_companion_commentary_defaults() -> None:
    from runtime.runtime_settings_store import RuntimeSettingsStore

    migrated, changed = RuntimeSettingsStore._migrate_payload({
        "version": 3,
        "initiative": {"global_hourly_budget": 10},
        "tts": {"speech_persona_warmth": 0.24},
    })
    assert changed is True
    assert migrated["version"] == 13
    assert migrated["initiative"]["global_hourly_budget"] == 40
    assert migrated["commentary"]["enabled"] is True
    assert migrated["commentary"]["maximum_quiet_seconds"] == 120
