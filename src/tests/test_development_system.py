# -*- coding: utf-8 -*-
"""tests/test_development_system.py — DevelopmentSystem apply/undo/reset (task 3).

- Property 6 (4.2, 5.5): số apply thành công trong cửa sổ ≤ max_nudges_per_window.
- Property 7 (5.6): ghi Sổ fail → Hồ_Sơ không đổi (fail-closed).
- Property 8 (5.2, 5.3, 5.4): undo khôi phục đúng phiên trước; reset về baseline, giữ Sổ.
- R11.3: Sổ round-trip serialize.
"""

from __future__ import annotations

import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.development_profile import (  # noqa: E402
    DevelopmentProfileStore,
    GrowthAnchor,
    IdentityGate,
    NudgeProposal,
)
from cortex.development_system import DevelopmentLog, DevelopmentSystem  # noqa: E402


def _system(tmp_path):
    profile = DevelopmentProfileStore(tmp_path / "development_profile.json")
    log = DevelopmentLog(tmp_path / "development_log.json")
    return DevelopmentSystem(profile=profile, log=log, gate=IdentityGate())


def _prop(axis="warmth_temperature", delta=0.02):
    return NudgeProposal(
        axis=axis,
        proposed_delta=delta,
        anchors=(GrowthAnchor(kind="interaction_history", evidence_ids=("ev1",), observed_count=3),),
    )


def test_property_6_rate_limit(tmp_path):
    sys_ = _system(tmp_path)
    max_n = sys_.gate.envelope.max_nudges_per_window
    applied = 0
    for _ in range(max_n + 5):
        r = sys_.apply(_prop(delta=0.02), now=1000.0)  # cùng thời điểm → cùng cửa sổ
        if r.applied:
            applied += 1
    assert applied <= max_n


def test_property_7_log_failure_leaves_profile_unchanged(tmp_path, monkeypatch):
    sys_ = _system(tmp_path)
    before = sys_.profile.delta("warmth_temperature")
    before_version = sys_.profile.version

    def _boom(self):
        raise OSError("disk full")

    monkeypatch.setattr(DevelopmentLog, "_save", _boom)

    r = sys_.apply(_prop(delta=0.2), now=1000.0)

    assert not r.applied and r.reason == "log_write_failed"
    assert sys_.profile.delta("warmth_temperature") == pytest.approx(before)
    assert sys_.profile.version == before_version


def test_property_8_undo_restores_previous(tmp_path):
    sys_ = _system(tmp_path)
    r = sys_.apply(_prop(delta=0.2), now=1000.0)
    assert r.applied
    assert sys_.profile.delta("warmth_temperature") == pytest.approx(0.2)

    u = sys_.undo_last(now=1001.0)
    assert u.applied
    assert sys_.profile.delta("warmth_temperature") == pytest.approx(0.0)


def test_property_8_reset_to_baseline_keeps_log(tmp_path):
    sys_ = _system(tmp_path)
    sys_.apply(_prop(axis="warmth_temperature", delta=0.2), now=1000.0)
    sys_.apply(_prop(axis="read_boldness", delta=0.1), now=1000.0)
    assert sys_.profile.identity_distance() > 0.0

    sys_.reset(now=1002.0)

    assert all(d.delta == 0.0 for d in sys_.profile.axes.values())
    assert sys_.profile.version == 0
    # Sổ giữ lịch sử (applied + reset).
    assert any(e.action == "reset" for e in sys_.log.entries)
    assert any(e.action == "applied" for e in sys_.log.entries)


def test_log_round_trip(tmp_path):
    sys_ = _system(tmp_path)
    sys_.apply(_prop(delta=0.2), now=1000.0)
    first = sys_.log.to_dict()

    reloaded = DevelopmentLog(tmp_path / "development_log.json")
    assert reloaded.to_dict() == first


def test_rejected_proposal_is_logged(tmp_path):
    sys_ = _system(tmp_path)
    r = sys_.apply(NudgeProposal(axis="warmth_temperature", proposed_delta=0.1, anchors=()), now=1000.0)
    assert not r.applied and r.reason == "missing_anchor"
    assert any(e.action == "rejected" and e.reason == "missing_anchor" for e in sys_.log.entries)


@settings(max_examples=60)
@given(deltas=st.lists(st.floats(min_value=0.01, max_value=0.05, allow_nan=False), min_size=1, max_size=12))
def test_property_6_rate_limit_property(tmp_path_factory, deltas):
    path = tmp_path_factory.mktemp("devsys")
    profile = DevelopmentProfileStore(path / "development_profile.json")
    log = DevelopmentLog(path / "development_log.json")
    system = DevelopmentSystem(profile=profile, log=log, gate=IdentityGate())
    max_n = system.gate.envelope.max_nudges_per_window

    applied = 0
    for d in deltas:
        if system.apply(_prop(delta=d), now=1000.0).applied:
            applied += 1
    assert applied <= max_n


# ===========================================================================
# Task 5.1 — giao diện người dùng (describe / steer)
# ===========================================================================
from cortex.development_profile import PERSONA_AXES  # noqa: E402


def test_describe_baseline(tmp_path):
    sys_ = _system(tmp_path)
    text = sys_.describe_for_user()
    assert "lúc mới gặp" in text


def test_describe_hides_internal_params_and_numbers(tmp_path):
    sys_ = _system(tmp_path)
    sys_.apply(_prop(axis="warmth_temperature", delta=0.2), now=1000.0)
    sys_.apply(_prop(axis="read_boldness", delta=0.1), now=1000.0)
    text = sys_.describe_for_user()

    assert "ấm hơn" in text
    # Không lộ tên tham số nội bộ:
    for axis in PERSONA_AXES:
        assert axis not in text
    # Không lộ số thô:
    assert not any(ch.isdigit() for ch in text)


def test_steer_applies_in_envelope(tmp_path):
    sys_ = _system(tmp_path)
    r = sys_.steer("ấm hơn chút đi", now=1000.0)
    assert r.applied and r.axis == "warmth_temperature"
    assert sys_.profile.delta("warmth_temperature") > 0.0
    assert "nghiêng theo ý bạn" in r.message


def test_steer_truncates_outside_envelope_and_reports(tmp_path):
    sys_ = _system(tmp_path)
    # Đẩy warmth gần trần trước (bound hi = 0.45).
    sys_.apply(_prop(axis="warmth_temperature", delta=0.42), now=1000.0)
    r = sys_.steer("ấm hơn nữa", now=2_000_000.0)  # cách xa cửa sổ để không rate-limit
    assert r.applied
    assert sys_.profile.delta("warmth_temperature") <= 0.45 + 1e-9
    assert "giới hạn" in r.message


def test_steer_unclear_direction(tmp_path):
    sys_ = _system(tmp_path)
    r = sys_.steer("ờ thì cũng được", now=1000.0)
    assert not r.applied and r.reason == "unclear_direction"


def test_undo_and_reset_callable_from_system(tmp_path):
    sys_ = _system(tmp_path)
    sys_.apply(_prop(axis="warmth_temperature", delta=0.2), now=1000.0)
    assert sys_.undo_last(now=1001.0).applied
    sys_.apply(_prop(axis="read_boldness", delta=0.1), now=1002.0)
    assert sys_.reset(now=1003.0).applied
    assert all(d.delta == 0.0 for d in sys_.profile.axes.values())
