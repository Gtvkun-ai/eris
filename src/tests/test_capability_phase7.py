# -*- coding: utf-8 -*-
"""CapabilityRegistry phải nói đúng phần Eris thấy được và phần chưa nối."""

from __future__ import annotations

from types import SimpleNamespace

from actions.capability_registry import iter_public_capabilities, render_capability_registry_prompt
from actions.capability_runtime import bind_runtime_owner, runtime_capability_flags
from runtime.source_grounding import SourceGroundingEngine


def _owner() -> SimpleNamespace:
    return SimpleNamespace(
        telemetry_service=SimpleNamespace(capture_snapshot=lambda **_: None),
        last_signal_snapshot=SimpleNamespace(active_app="Godot", active_window_title="Eris DEBUG"),
        screen_text_worker=SimpleNamespace(),
        vision_semantic_compressor=None,
        action_router=SimpleNamespace(),
        action_executor=SimpleNamespace(),
        runtime_settings={"capabilities": {"respect_runtime_availability": True}},
    )


def test_observational_capabilities_are_grounded_in_live_runtime() -> None:
    bind_runtime_owner(_owner())
    flags = runtime_capability_flags()
    try:
        assert flags["observe_active_app"] is True
        assert flags["observe_idle_state"] is True
        assert flags["read_uia_text"] is True
        assert flags["telemetry_summary"] is True
        assert flags["camera_view"] is False
        assert flags["meet_participants"] is False
    finally:
        bind_runtime_owner(None)


def test_capability_prompt_states_available_and_unavailable_separately() -> None:
    bind_runtime_owner(_owner())
    try:
        prompt = render_capability_registry_prompt(max_items=20)
        assert "observe_active_app" in prompt and "status=available" in prompt
        assert "meet_participants" in prompt and "status=unavailable_now" in prompt
        assert "camera_view" in prompt and "status=unavailable_now" in prompt
    finally:
        bind_runtime_owner(None)


def test_internal_capability_question_does_not_route_to_web_missing() -> None:
    report = SourceGroundingEngine().analyze(
        "Eris có thấy được telemetry và thời gian hệ thống hiện tại không?",
        runtime_state={"active_app": "Godot"},
        allow_web=False,
    )
    assert report.primary_source == "runtime_state"
    assert report.requested_source is None
    assert "web_access_or_search_result" not in report.missing_evidence
