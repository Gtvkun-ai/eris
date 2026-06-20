# -*- coding: utf-8 -*-
"""Test công tắc guard warn-only thống nhất (guard_config).

Phủ:
- ERIS_GUARDS_WARN_ONLY bật → guards_warn_only() True, mọi rule về log_only.
- Tắt → per-rule mặc định STRICT (giữ guard sự-thật active như cũ), không phá hành vi.
- Per-rule override qua ERIS_GUARD_MODE__<NAME>.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import guard_config as gc


def _reload():
    return importlib.reload(gc)


def _clear(monkeypatch):
    for key in list(os.environ):
        if key.startswith("ERIS_GUARD"):
            monkeypatch.delenv(key, raising=False)


def test_warn_only_flag_off_by_default(monkeypatch):
    _clear(monkeypatch)
    m = _reload()
    assert m.guards_warn_only() is False
    # per-rule mặc định STRICT (guard sự-thật vẫn active)
    assert m.get_guard_mode("chat_grounding_guard") == m.STRICT_GUARD_MODE
    # global no-arg vẫn log_only như cũ
    assert m.get_guard_mode() == m.LOG_ONLY_GUARD_MODE


def test_warn_only_flag_on_forces_log_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ERIS_GUARDS_WARN_ONLY", "1")
    m = _reload()
    assert m.guards_warn_only() is True
    assert m.get_guard_mode("chat_grounding_guard") == m.LOG_ONLY_GUARD_MODE
    assert m.get_guard_mode("memory_haunting_guard") == m.LOG_ONLY_GUARD_MODE
    assert m.get_guard_mode() == m.LOG_ONLY_GUARD_MODE


def test_per_rule_override_when_not_warn_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ERIS_GUARD_MODE__CHAT_GROUNDING_GUARD", "off")
    m = _reload()
    assert m.get_guard_mode("chat_grounding_guard") == m.OFF_GUARD_MODE
    # rule khác vẫn strict
    assert m.get_guard_mode("memory_haunting_guard") == m.STRICT_GUARD_MODE


def test_warn_only_accepts_various_truthy(monkeypatch):
    for val in ("1", "true", "yes", "on"):
        _clear(monkeypatch)
        monkeypatch.setenv("ERIS_GUARDS_WARN_ONLY", val)
        m = _reload()
        assert m.guards_warn_only() is True
    for val in ("0", "false", "no", "off", ""):
        _clear(monkeypatch)
        monkeypatch.setenv("ERIS_GUARDS_WARN_ONLY", val)
        m = _reload()
        assert m.guards_warn_only() is False


def teardown_module(module):
    # Trả guard_config về trạng thái sạch cho các test khác.
    for key in list(os.environ):
        if key.startswith("ERIS_GUARD"):
            os.environ.pop(key, None)
    os.environ["ERIS_GUARDS_WARN_ONLY"] = "0"
    importlib.reload(gc)
