# -*- coding: utf-8 -*-
"""Tests cho lớp cờ chiều-sâu (control-file) — nền của tab Panel trong context menu.

Panel Godot gửi `depth_control` qua UDP -> coordinator ghi control-file qua các hàm
dưới đây. Bật/tắt live, control-file thắng env.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def flags_path(tmp_path, monkeypatch):
    p = tmp_path / "depth_flags.json"
    monkeypatch.setenv("ERIS_DEPTH_FLAGS_PATH", str(p))
    import cortex.depth_flags as df
    df._cache["mtime"] = -1.0
    df._cache["data"] = {}
    return p


def test_flag_default_off(flags_path, monkeypatch):
    import cortex.depth_flags as df
    monkeypatch.delenv("ERIS_TOM_ADVISOR", raising=False)
    assert df.flag_enabled("ERIS_TOM_ADVISOR") is False


def test_flag_env_on(flags_path, monkeypatch):
    import cortex.depth_flags as df
    monkeypatch.setenv("ERIS_TOM_ADVISOR", "1")
    assert df.flag_enabled("ERIS_TOM_ADVISOR") is True


def test_control_file_overrides_env(flags_path, monkeypatch):
    import cortex.depth_flags as df
    monkeypatch.setenv("ERIS_TOM_ADVISOR", "1")   # env bật
    df.set_flags({"tom_advisor": False})           # control-file tắt -> thắng
    assert df.flag_enabled("ERIS_TOM_ADVISOR") is False
    assert df.all_states()["tom_advisor"] is False


def test_set_flags_live_toggle(flags_path):
    import cortex.depth_flags as df
    df.set_flags({"emotional_consequence": True})
    assert df.flag_enabled("ERIS_EMOTIONAL_CONSEQUENCE") is True
    df.set_flags({"emotional_consequence": False})
    assert df.flag_enabled("ERIS_EMOTIONAL_CONSEQUENCE") is False


def test_set_flags_ignores_unknown(flags_path):
    import cortex.depth_flags as df
    out = df.set_flags({"not_a_flag": True})
    assert "not_a_flag" not in out
    assert set(out.keys()) == set(df.KNOWN_FLAGS.keys())


def test_all_states_covers_six_flags(flags_path):
    import cortex.depth_flags as df
    assert set(df.all_states().keys()) == {
        "emotional_consequence", "development_growth", "interior_surface",
        "tom_advisor", "real_embeddings", "private_mind",
    }


# ---------------------------------------------------------------------------
# panel_snapshot — tín hiệu sống
# ---------------------------------------------------------------------------
@pytest.fixture
def snap_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ERIS_MEMORY_CORE_DIR", str(tmp_path))
    monkeypatch.setenv("ERIS_PANEL_SNAPSHOT_MIN_SEC", "0")  # bỏ throttle trong test
    import runtime.panel_snapshot as ps
    with ps._lock:
        ps._last_write = 0.0
        ps._signal_log.clear()
    return tmp_path


class _Appraisal:
    valence = -0.3
    arousal = 0.4
    tenderness = 0.5
    threat = 0.1
    stance = "tender_under_cold"


def test_snapshot_disabled_writes_nothing(snap_env, monkeypatch):
    monkeypatch.delenv("ERIS_PANEL_SNAPSHOT", raising=False)
    import runtime.panel_snapshot as ps
    ps.write(appraisal=_Appraisal(), expression_gate={"want_to_say": 0.7})
    assert not (snap_env / "panel_snapshot.json").exists()


def test_snapshot_writes_when_enabled(snap_env, monkeypatch):
    monkeypatch.setenv("ERIS_PANEL_SNAPSHOT", "1")
    import runtime.panel_snapshot as ps
    ps.write(
        appraisal=_Appraisal(),
        expression_gate={"want_to_say": 0.71, "suppression_pressure": 0.44, "allowed_expression": 0.40},
        tom_read="tom_read: Ngài có thể đang bực (độ tin ~0.72).",
        channel="chat",
    )
    data = json.loads((snap_env / "panel_snapshot.json").read_text(encoding="utf-8"))
    assert data["affect"]["stance"] == "tender_under_cold"
    assert data["n1"]["want"] == 0.71
    assert data["tom_read"]["live"] is True
    assert data["tom_read"]["confidence"] == 0.72
    assert any(s["kind"] == "tom_read" for s in data["signal_log"])


def test_panel_state_reads_live_snapshot(snap_env, flags_path, monkeypatch):
    monkeypatch.setenv("ERIS_PANEL_SNAPSHOT", "1")
    import runtime.panel_snapshot as ps
    ps.write(appraisal=_Appraisal(), expression_gate={"want_to_say": 0.6, "allowed_expression": 0.3},
             tom_read="tom_read: Ngài có thể đang tò mò (độ tin ~0.55).")
    from runtime.panel_state import build_panel_state
    s = build_panel_state()
    assert s["affect"]["live"] is True
    assert s["affect"]["stance"] == "tender_under_cold"
    assert s["tom_read"]["live"] is True
    assert s["n1"]["want"] == 0.6
    assert s["identity"]["alive"] is True


def test_panel_state_ignores_stale_snapshot(snap_env, flags_path, monkeypatch):
    # ghi snapshot với ts cũ -> bị coi như Eris không còn chạy
    (snap_env / "panel_snapshot.json").write_text(json.dumps({
        "ts": 1.0, "affect": {"live": True, "stance": "x"}, "tom_read": {"live": True, "text": "cũ"},
        "n1": {"live": True}, "signal_log": []
    }), encoding="utf-8")
    from runtime.panel_state import build_panel_state
    s = build_panel_state()
    assert s["affect"]["live"] is False
    assert s["identity"]["alive"] is False
