# -*- coding: utf-8 -*-
from types import SimpleNamespace

from runtime.ai_orchestrated.opening_director import OpeningDirector
from runtime.ai_orchestrated.opening_input_assembler import build_opening_input
from runtime.ai_orchestrated.opening_safety import evidence_is_surface_eligible
from runtime.runtime_settings_store import RuntimeSettingsStore

from tests.opening_test_helpers import make_opening_input


class _MemoryKernel:
    def user_memory_summary(self, *, include_sensitive: bool = False):
        assert include_sensitive is False
        return {
            "recent_episodes": [
                {
                    "session_id": "previous-session",
                    "title": "Sửa câu mở đầu của Eris",
                    "summary": "Hai bên đang chỉnh Opening Director để lời đầu có continuity thật.",
                    "open_loops": ["chỉnh Opening Director để câu đầu nhắc lại mạch cũ"],
                    "scope": {"kind": "global", "key": ""},
                }
            ]
        }


def test_assembler_loads_previous_public_episode_before_opening(monkeypatch) -> None:
    import runtime.ai_orchestrated.opening_input_assembler as assembler

    settings = {
        ("opening_director", "cross_session_personalization"): False,
        ("opening_director", "startup_memory_callback"): True,
        ("opening_director", "prefer_continuity_hook"): True,
    }
    monkeypatch.setattr(
        assembler,
        "_runtime_value",
        lambda section, key, default: settings.get((section, key), default),
    )
    host = SimpleNamespace(
        memory_kernel=_MemoryKernel(),
        session_id="current-session",
        last_session_at=0.0,
        chat_mode=False,
        _chat_processing=False,
    )
    state = SimpleNamespace(open_loops=())
    grounding = SimpleNamespace(evidence=(), runtime_opening_evidence=(), privacy_blocked=False)

    opening_input = build_opening_input(
        host,
        state=state,
        grounding=grounding,
        now=100.0,
    )

    assert opening_input.continuity.consent_scope == "cross_session"
    assert opening_input.continuity.open_loops[0].startswith("chỉnh Opening Director")
    assert "Sửa câu mở đầu của Eris" in opening_input.continuity.last_session_summary
    assert opening_input.policy.prefer_continuity_hook is True


def test_director_requires_memory_hook_when_callback_exists() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        continuity={
            "consent_scope": "cross_session",
            "open_loops": ["vá lỗi câu chào đầu phiên"],
            "last_session_summary": "Lần trước đang vá lỗi câu chào đầu phiên.",
        },
        policy={
            "cross_session_personalization_allowed": True,
            "allow_screen_hook": False,
            "allow_continuity_hook": True,
            "prefer_continuity_hook": True,
        },
    )
    seen = {}

    def planner(_payload, candidates):
        seen["candidates"] = candidates
        no_hook = next(item for item in candidates if item["hook"]["decision"] == "none")
        return {"candidate_id": no_hook["candidate_id"]}

    director = OpeningDirector(mode="hybrid")
    plan = director.plan(opening_input, planner=planner)
    surface = director.realize(opening_input, plan)

    assert seen["candidates"]
    assert plan.hook.source == "continuity"
    assert plan.hook.evidence_refs[0].startswith("continuity:")
    assert "Lần trước" in surface.display_text


def test_surface_writer_receives_typed_memory_evidence() -> None:
    opening_input = make_opening_input(
        screen_evidence=[],
        continuity={
            "consent_scope": "cross_session",
            "open_loops": [],
            "last_session_summary": "Đang chỉnh Opening Director để lời đầu có mạch cũ.",
        },
        policy={
            "cross_session_personalization_allowed": True,
            "allow_screen_hook": False,
            "allow_continuity_hook": True,
            "prefer_continuity_hook": True,
        },
    )
    director = OpeningDirector(mode="hybrid")
    plan = director.plan(opening_input)
    captured = {}

    def writer(_plan, evidence):
        captured["evidence"] = evidence
        return {}

    director.realize(opening_input, plan, surface_writer=writer)

    assert evidence_is_surface_eligible(opening_input, "continuity:last_session_summary")
    assert captured["evidence"][0]["evidence_id"] == "continuity:last_session_summary"
    assert captured["evidence"][0]["source"] == "continuity"


def test_settings_v16_enables_startup_memory_callback() -> None:
    migrated, changed = RuntimeSettingsStore._migrate_payload(
        {"version": 15, "opening_director": {"cross_session_personalization": False}}
    )
    assert changed is True
    assert migrated["version"] == 17
    assert migrated["opening_director"]["startup_memory_callback"] is True
    assert migrated["opening_director"]["prefer_continuity_hook"] is True
    assert migrated["opening_director"]["cross_session_personalization"] is False
