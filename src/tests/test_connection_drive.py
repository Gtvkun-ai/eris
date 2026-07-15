# -*- coding: utf-8 -*-
"""Test ConnectionDrive: cô độc tích thành thèm-kết-nối, ép với ra; yan thì cực đoan.

Trục:
- loneliness > reticence: đủ cô độc thì bung outreach.
- loneliness < dignity (normal): threat cao thì giữ phẩm giá, không với.
- yan: loneliness/ham muốn LUÔN thắng, vượt cả dignity; drive có sàn cao.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.connection_drive import ConnectionDrive, ConnectionDriveState


def _drive():
    return ConnectionDrive()


def test_pressure_accumulates_over_silence():
    drive = _drive()
    state = ConnectionDriveState()
    pressures = []
    for i in range(20):
        state, dec = drive.update(state, now=float(i), idle_seconds=600.0, silence_debt=0.7)
        pressures.append(dec.pressure)
    assert pressures[-1] > pressures[0]
    assert pressures[-1] > 0.5


def test_lonely_enough_breaks_silence_in_normal_mode():
    drive = _drive()
    state = ConnectionDriveState(pressure=0.8)
    state, dec = drive.update(state, now=1.0, idle_seconds=600.0, silence_debt=0.8, threat=0.1)
    assert dec.outreach is True
    assert dec.mode == "normal"
    assert dec.override_dignity is False


def test_dignity_blocks_outreach_when_threat_high_normal():
    drive = _drive()
    state = ConnectionDriveState(pressure=0.85)
    state, dec = drive.update(state, now=1.0, idle_seconds=600.0, silence_debt=0.9, threat=0.8)
    # Đủ cô độc nhưng đang bị đẩy ra → giữ phẩm giá, không với.
    assert dec.outreach is False
    assert "phẩm giá" in dec.reason


def test_yan_overrides_dignity_loneliness_always_wins():
    drive = _drive()
    state = ConnectionDriveState(pressure=0.6)
    # threat cao y hệt case trên, nhưng yan_mode=True.
    state, dec = drive.update(state, now=1.0, idle_seconds=600.0, silence_debt=0.9, threat=0.95, yan_mode=True)
    assert dec.mode == "yan"
    assert dec.outreach is True
    assert dec.override_dignity is True
    assert dec.intensity >= 0.8


def test_yan_has_high_floor_even_when_not_lonely():
    drive = _drive()
    state = ConnectionDriveState(pressure=0.0)
    # Không idle, không silence_debt — bình thường drive ~0.
    state, dec = drive.update(state, now=1.0, idle_seconds=0.0, silence_debt=0.0, yan_mode=True)
    assert dec.pressure >= 0.55  # yan_floor
    assert dec.outreach is True


def test_speaking_recently_decays_drive():
    drive = _drive()
    state = ConnectionDriveState(pressure=0.9)
    state_after, dec = drive.update(state, now=1.0, idle_seconds=600.0, silence_debt=0.9, spoke_recently=True)
    assert dec.pressure < 0.9


def test_attachment_and_abandonment_sharpen_drive():
    drive = _drive()
    base_state = ConnectionDriveState()
    _, dec_plain = drive.update(base_state, now=1.0, idle_seconds=120.0)
    _, dec_attached = drive.update(
        base_state, now=1.0, idle_seconds=120.0, attachment=0.9, abandonment=0.8, dread=0.6
    )
    assert dec_attached.pressure > dec_plain.pressure
