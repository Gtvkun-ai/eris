# -*- coding: utf-8 -*-
"""Repository definition v4: legacy guards can no longer mutate public speech."""

import importlib
import os

import guard_config as gc


def _reload():
    return importlib.reload(gc)


def _clear(monkeypatch):
    for key in list(os.environ):
        if key.startswith("ERIS_GUARD"):
            monkeypatch.delenv(key, raising=False)


def test_observe_only_is_architecture_default(monkeypatch):
    _clear(monkeypatch)
    m = _reload()
    assert m.guards_warn_only() is True
    assert m.get_guard_mode() == m.LOG_ONLY_GUARD_MODE
    assert m.get_guard_mode("chat_grounding_guard") == m.LOG_ONLY_GUARD_MODE


def test_legacy_environment_cannot_resurrect_mutating_guard(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ERIS_GUARDS_WARN_ONLY", "0")
    monkeypatch.setenv("ERIS_GUARD_MODE", "strict")
    monkeypatch.setenv("ERIS_GUARD_MODE__CHAT_GROUNDING_GUARD", "off")
    m = _reload()
    assert m.guards_warn_only() is True
    assert m.get_guard_mode() == m.LOG_ONLY_GUARD_MODE
    assert m.get_guard_mode("chat_grounding_guard") == m.LOG_ONLY_GUARD_MODE


def test_legacy_mode_constants_remain_import_compatible():
    assert gc.STRICT_GUARD_MODE == "strict"
    assert gc.SELF_CLAMP_GUARD_MODE == "self_clamp"
    assert gc.OBSERVE_ONLY_GUARD_MODE == gc.LOG_ONLY_GUARD_MODE
