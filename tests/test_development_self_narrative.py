# -*- coding: utf-8 -*-
"""Tests cho Nước 2 — long-arc self-continuity vào self-narrative.

Phủ:
  - adapter trả "" khi cờ tắt / khi chưa đổi gì;
  - adapter trả câu narrative khi cờ bật + profile đã đổi thật;
  - SelfModel._prompt_context chèn câu đó khi bật, bỏ khi tắt.
"""

from __future__ import annotations

import importlib

import pytest


def _reset_dev_singleton():
    import cortex.development_system as ds

    ds._DEFAULT_SYSTEM = None


@pytest.fixture
def dev_profile(tmp_path, monkeypatch):
    """Trỏ profile long-arc vào file tạm, reset singleton, dọn sau test."""
    profile_path = tmp_path / "development_profile.json"
    monkeypatch.setenv("ERIS_DEVELOPMENT_PROFILE_PATH", str(profile_path))
    _reset_dev_singleton()
    yield profile_path
    _reset_dev_singleton()


def _commit_warmth(delta=0.25):
    from cortex.development_system import get_default_development_system

    system = get_default_development_system()
    system.profile.commit("warmth_temperature", delta, evidence_ids=("test",))
    system.profile.save()
    return system


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
def test_narrative_empty_when_flag_off(dev_profile, monkeypatch):
    monkeypatch.delenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", raising=False)
    _commit_warmth()
    from cortex.development_self_narrative import development_self_narrative_line

    assert development_self_narrative_line() == ""


def test_narrative_empty_when_unchanged(dev_profile, monkeypatch):
    monkeypatch.setenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", "1")
    # không commit gì -> profile baseline -> describe_for_user là "chưa nghiêng..."
    from cortex.development_self_narrative import development_self_narrative_line

    assert development_self_narrative_line() == ""


def test_narrative_present_when_changed(dev_profile, monkeypatch):
    monkeypatch.setenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", "1")
    _commit_warmth(0.3)
    from cortex.development_self_narrative import development_self_narrative_line

    line = development_self_narrative_line()
    assert line.startswith("self_continuity_arc:")
    assert "ấm hơn" in line  # warmth_temperature dương -> giọng ấm hơn


# ---------------------------------------------------------------------------
# SelfModel integration
# ---------------------------------------------------------------------------
def _self_prompt_context():
    from cortex.self_model import SelfModelEngine
    from cortex.internal_state import PersistentInternalState

    engine = SelfModelEngine()
    state = engine.evaluate(internal_state=PersistentInternalState(), channel="chat")
    return state.prompt_context


def test_self_model_excludes_arc_when_off(dev_profile, monkeypatch):
    monkeypatch.delenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", raising=False)
    _commit_warmth(0.3)
    ctx = _self_prompt_context()
    assert "self_continuity_arc" not in ctx
    # vẫn dựng được prompt bình thường
    assert "identity_profile:" in ctx


def test_self_model_includes_arc_when_on(dev_profile, monkeypatch):
    monkeypatch.setenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", "1")
    _commit_warmth(0.3)
    ctx = _self_prompt_context()
    assert "self_continuity_arc" in ctx
    assert "ấm hơn" in ctx
