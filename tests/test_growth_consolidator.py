# -*- coding: utf-8 -*-
"""tests/test_growth_consolidator.py — Tác_Tử_Nền (task 4 / 4.1).

- should_run gating (R6.3, R6.4).
- lọc evidence không nguồn / axis lạ (R6.5, R1.3).
- Property 9 (8.1, 8.4, 12.4): một phiên đơn lẻ không sinh đề xuất.
- Property 10 (12.1, 12.2): bằng chứng nhất quán nhiều phiên → độ lệch quan sát
  được trên ≥1 trục, vẫn trong phong bì.
"""

from __future__ import annotations

import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.development_profile import DevelopmentProfileStore, IdentityGate  # noqa: E402
from cortex.development_system import DevelopmentLog, DevelopmentSystem  # noqa: E402
from cortex.growth_consolidator import (  # noqa: E402
    GrowthConsolidator,
    GrowthConsolidatorConfig,
    GrowthObservation,
)


def test_should_run_defers_when_user_high_risk():
    c = GrowthConsolidator()
    assert not c.should_run(idle_pressure=0.9, user_interacting_high_risk=True)


def test_should_run_respects_budget_veto():
    c = GrowthConsolidator()
    assert not c.should_run(idle_pressure=0.9, budget_allows=False)


def test_should_run_needs_pressure():
    c = GrowthConsolidator()
    assert not c.should_run(idle_pressure=0.1, consolidation_pressure=0.1)
    assert c.should_run(idle_pressure=0.8)


def test_drops_unsourced_and_unknown_axis():
    c = GrowthConsolidator()
    obs = [
        GrowthObservation("warmth_temperature", 0.05, ("good_ev",), "s1"),
        GrowthObservation("warmth_temperature", 0.05, ("fake_ev",), "s2"),  # evidence không thật
        GrowthObservation("not_an_axis", 0.05, ("good_ev",), "s3"),         # axis lạ
    ]
    proposals = c.consolidate(obs, allowed_evidence_ids={"good_ev"})
    # Chỉ còn 1 quan sát hợp lệ → chưa đủ phiên/tần suất → không đề xuất.
    assert proposals == []


def test_property_9_single_session_no_proposal():
    c = GrowthConsolidator()
    obs = [GrowthObservation("warmth_temperature", 0.05, (f"ev{i}",), "only_session") for i in range(8)]
    allowed = {f"ev{i}" for i in range(8)}
    assert c.consolidate(obs, allowed_evidence_ids=allowed) == []


def test_consistent_multi_session_yields_proposal():
    c = GrowthConsolidator()
    obs = []
    allowed = set()
    for s in range(3):
        for i in range(2):
            eid = f"s{s}_ev{i}"
            allowed.add(eid)
            obs.append(GrowthObservation("warmth_temperature", 0.06, (eid,), f"session_{s}"))
    proposals = c.consolidate(obs, allowed_evidence_ids=allowed)
    assert len(proposals) == 1
    assert proposals[0].axis == "warmth_temperature"
    assert proposals[0].proposed_delta > 0.0
    assert any(a.evidence_ids for a in proposals[0].anchors)


def test_property_10_multi_session_produces_observable_bounded_divergence(tmp_path):
    profile = DevelopmentProfileStore(tmp_path / "development_profile.json")
    log = DevelopmentLog(tmp_path / "development_log.json")
    system = DevelopmentSystem(profile=profile, log=log, gate=IdentityGate())
    c = GrowthConsolidator()

    now = 1000.0
    # Nhiều đợt consolidate qua thời gian, mỗi đợt bằng chứng nhất quán đẩy warmth lên.
    for round_idx in range(6):
        obs, allowed = [], set()
        for s in range(3):
            eid = f"r{round_idx}_s{s}"
            allowed.add(eid)
            for _ in range(1):
                obs.append(GrowthObservation("warmth_temperature", 0.06, (eid,), f"r{round_idx}_session_{s}"))
        for p in c.consolidate(obs, allowed_evidence_ids=allowed):
            system.apply(p, now=now + round_idx * 100000.0)  # cách xa cửa sổ để không bị rate-limit

    env = system.gate.envelope
    lo, hi = env.bound("warmth_temperature")
    # Có phân kỳ quan sát được:
    assert system.profile.delta("warmth_temperature") > 0.0
    # Nhưng vẫn trong phong bì:
    assert lo - 1e-9 <= system.profile.delta("warmth_temperature") <= hi + 1e-9
    assert system.profile.identity_distance(env.axis_bounds) <= env.max_identity_distance + 1e-9


@settings(max_examples=60)
@given(
    n_sessions=st.integers(min_value=0, max_value=1),
    n_obs=st.integers(min_value=1, max_value=10),
)
def test_property_9_insufficient_sessions_hold(n_sessions, n_obs):
    """Dưới ngưỡng phiên → luôn giữ nguyên (không đề xuất)."""
    c = GrowthConsolidator(GrowthConsolidatorConfig(min_sessions=2, min_frequency=3))
    obs, allowed = [], set()
    sessions = max(1, n_sessions)  # 0 hoặc 1 phiên
    for i in range(n_obs):
        eid = f"ev{i}"
        allowed.add(eid)
        obs.append(GrowthObservation("warmth_temperature", 0.05, (eid,), f"session_{i % sessions}"))
    if sessions < 2:
        assert c.consolidate(obs, allowed_evidence_ids=allowed) == []
