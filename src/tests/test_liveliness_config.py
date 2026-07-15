from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.liveliness_config import (
    MAX_IDLE_INTERVAL_SEC,
    LivelinessConfig,
    load_liveliness_config,
)

_KEYS = (
    "ERIS_LIVELINESS_VISION_FRESH_SEC",
    "ERIS_LIVELINESS_SEED_MAX_LEN",
    "ERIS_LIVELINESS_REPEAT_WINDOW_SEC",
    "ERIS_LIVELINESS_SIM_THRESHOLD_PCT",
    "ERIS_LIVELINESS_MAX_LINE_REPEAT",
    "ERIS_LIVELINESS_MAX_ALT_SEEDS",
    "ERIS_LIVELINESS_MIN_GROUNDED_PER_HR",
    "ERIS_LIVELINESS_SUBINTERVAL_SEC",
    "ERIS_LIVELINESS_MIN_GROUNDED_PCT",
    "ERIS_LIVELINESS_DECISION_RETENTION",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def test_defaults_when_absent() -> None:
    cfg = load_liveliness_config()
    assert cfg == LivelinessConfig()
    assert cfg.sim_threshold == pytest.approx(0.78)


def test_malformed_values_fall_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_LIVELINESS_MAX_LINE_REPEAT", "abc")
    monkeypatch.setenv("ERIS_LIVELINESS_VISION_FRESH_SEC", "not_a_number")
    cfg = load_liveliness_config()
    assert cfg.max_line_repeat == 3
    assert cfg.vision_fresh_sec == 30.0


def test_out_of_range_values_are_clamped(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_LIVELINESS_MAX_LINE_REPEAT", "999")
    monkeypatch.setenv("ERIS_LIVELINESS_SIM_THRESHOLD_PCT", "-5")
    cfg = load_liveliness_config()
    assert cfg.max_line_repeat == 10
    assert cfg.sim_threshold_pct == 0


def test_repeat_window_floor_is_max_idle_interval(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_LIVELINESS_REPEAT_WINDOW_SEC", "30")
    cfg = load_liveliness_config()
    assert cfg.repeat_window_sec == MAX_IDLE_INTERVAL_SEC


def test_valid_values_are_used(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_LIVELINESS_MIN_GROUNDED_PCT", "75")
    monkeypatch.setenv("ERIS_LIVELINESS_MAX_ALT_SEEDS", "5")
    cfg = load_liveliness_config()
    assert cfg.min_grounded_pct == 75
    assert cfg.max_alt_seeds == 5


def test_load_never_raises_on_any_garbage(monkeypatch) -> None:
    for key in _KEYS:
        monkeypatch.setenv(key, "💥garbage💥")
    cfg = load_liveliness_config()  # should not raise
    assert isinstance(cfg, LivelinessConfig)
