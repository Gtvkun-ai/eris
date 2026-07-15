# -*- coding: utf-8 -*-
"""tests/test_growth_evidence.py — bộ phiên dịch ký-ức→observation (task 7).

- Map bảo thủ: chỉ topic rõ nghĩa; tín hiệu mơ hồ → không sinh quan sát.
- evidence_ids/session_id hợp lệ; allowed chỉ chứa id từ event thật.
- Chuỗi end-to-end: feedback nhiều ngày → consolidate → apply → delta có giới hạn.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.development_profile import DevelopmentProfileStore, IdentityGate  # noqa: E402
from cortex.development_system import DevelopmentLog, DevelopmentSystem  # noqa: E402
from cortex.growth_consolidator import GrowthConsolidator  # noqa: E402
from cortex.growth_evidence import observations_from_feedback  # noqa: E402


_DAY = 86400.0


def _event(ts, sentiment, topics):
    return {"ts": ts, "sentiment": sentiment, "topics": list(topics), "markers": ["x"]}


def test_empty_and_neutral_no_observations():
    obs, allowed = observations_from_feedback([])
    assert obs == [] and allowed == set()
    obs, allowed = observations_from_feedback([_event(1000.0, "positive", [])])  # positive nhưng không topic
    assert obs == [] and allowed == set()


def test_more_life_positive_maps_warmth_and_boldness():
    obs, allowed = observations_from_feedback([_event(2 * _DAY, "positive", ["more_life"])])
    axes = {o.axis for o in obs}
    assert "warmth_temperature" in axes and "read_boldness" in axes
    assert all(o.direction > 0 for o in obs)
    assert allowed == {f"feedback:{int(2 * _DAY)}"}
    assert all(o.session_id == "day:2" for o in obs)


def test_intrusive_question_reduces_boldness_and_distance():
    obs, _ = observations_from_feedback([_event(3 * _DAY, "negative", ["intrusive_question"])])
    by_axis = {o.axis: o.direction for o in obs}
    assert by_axis["read_boldness"] < 0
    assert by_axis["preferred_distance"] > 0  # giữ khoảng cách hơn
    # sentiment negative → kind user_correction (trọng số cao)
    assert all(o.kind == "user_correction" for o in obs)


def test_unmapped_topics_ignored():
    obs, allowed = observations_from_feedback([_event(_DAY, "positive", ["camera_voice", "technical_help"])])
    assert obs == [] and allowed == set()


def test_end_to_end_feedback_to_bounded_growth(tmp_path):
    profile = DevelopmentProfileStore(tmp_path / "development_profile.json")
    log = DevelopmentLog(tmp_path / "development_log.json")
    system = DevelopmentSystem(profile=profile, log=log, gate=IdentityGate())
    consolidator = GrowthConsolidator()

    # 3 ngày khác nhau, mỗi ngày bạn khen kiểu "sống động hơn" → warmth nên lên.
    events = [_event(d * _DAY, "positive", ["more_life"]) for d in (1, 2, 3)]
    observations, allowed = observations_from_feedback(events)
    proposals = consolidator.consolidate(observations, allowed_evidence_ids=allowed)
    assert proposals, "phải có đề xuất khi bằng chứng nhất quán nhiều phiên"

    for i, p in enumerate(proposals):
        system.apply(p, now=1000.0 + i * 200000.0)

    env = system.gate.envelope
    lo, hi = env.bound("warmth_temperature")
    assert system.profile.delta("warmth_temperature") > 0.0
    assert lo - 1e-9 <= system.profile.delta("warmth_temperature") <= hi + 1e-9
    assert system.profile.identity_distance(env.axis_bounds) <= env.max_identity_distance + 1e-9


def test_single_day_does_not_grow(tmp_path):
    # Tất cả feedback trong MỘT ngày → một phiên → consolidator giữ nguyên (R8.1).
    events = [_event(5 * _DAY + i, "positive", ["more_life"]) for i in range(6)]
    observations, allowed = observations_from_feedback(events)
    proposals = GrowthConsolidator().consolidate(observations, allowed_evidence_ids=allowed)
    assert proposals == []
