# -*- coding: utf-8 -*-
"""tests/test_development_profile.py — DevelopmentProfileStore (task 1).

Bao phủ:
- Property 1 / 11.2: round-trip serialize (to_dict→from_dict→to_dict tương đương).
- R10.3: file hỏng → baseline, không crash.
- R10.5: nếu về baseline cũng fail → raise (fail-closed).
- R10.4: reload-on-change theo mtime.
- R11.4: thiếu/hỏng trường → safe default.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.development_profile import (  # noqa: E402
    PERSONA_AXES,
    BaselineConstructionError,
    DevelopmentProfileStore,
    baseline_axes,
)


def _strip_volatile(payload: dict) -> dict:
    """Bỏ trường updated_at cấp file (dùng _now() nên luôn đổi)."""
    out = dict(payload)
    out.pop("updated_at", None)
    return out


def _axes_payload(values: dict[str, float]) -> dict:
    return {
        "schema_version": 1,
        "version": 3,
        "axes": {
            axis: {"axis": axis, "delta": values.get(axis, 0.0), "stability": 0.5, "last_evidence_ids": [], "updated_at": 0.0}
            for axis in PERSONA_AXES
        },
    }


@settings(max_examples=80)
@given(
    deltas=st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=len(PERSONA_AXES),
        max_size=len(PERSONA_AXES),
    )
)
def test_property_1_round_trip(tmp_path_factory, deltas):
    """Property 1: to_dict → from_dict → to_dict tương đương (bỏ updated_at file)."""
    path = tmp_path_factory.mktemp("dev") / "development_profile.json"
    store = DevelopmentProfileStore(path)
    values = {axis: d for axis, d in zip(PERSONA_AXES, deltas)}
    store.from_dict(_axes_payload(values))

    first = store.to_dict()
    store.from_dict(first)
    second = store.to_dict()

    assert _strip_volatile(first) == _strip_volatile(second)
    assert first["version"] == second["version"]


def test_corrupt_file_falls_back_to_baseline(tmp_path):
    path = tmp_path / "development_profile.json"
    path.write_text("{ this is not valid json :::", encoding="utf-8")

    store = DevelopmentProfileStore(path)

    assert store.version == 0
    assert {a: round(d.delta, 6) for a, d in store.axes.items()} == {a: 0.0 for a in PERSONA_AXES}


def test_baseline_fallback_failure_raises(tmp_path, monkeypatch):
    path = tmp_path / "development_profile.json"
    path.write_text("not-json", encoding="utf-8")

    def _boom(self):
        raise ValueError("baseline construction broke")

    monkeypatch.setattr(DevelopmentProfileStore, "reset_to_baseline", _boom)

    with pytest.raises(BaselineConstructionError):
        DevelopmentProfileStore(path)


def test_reload_if_changed_picks_up_external_write(tmp_path):
    path = tmp_path / "development_profile.json"
    store = DevelopmentProfileStore(path)
    store.commit("warmth_temperature", 0.2)
    store.save()
    assert store.delta("warmth_temperature") == pytest.approx(0.2)

    payload = _axes_payload({"warmth_temperature": 0.5})
    path.write_text(json.dumps(payload), encoding="utf-8")
    future = os.stat(path).st_mtime + 10.0
    os.utime(path, (future, future))

    store.reload_if_changed()
    assert store.delta("warmth_temperature") == pytest.approx(0.5)


def test_missing_fields_fill_safe_defaults(tmp_path):
    path = tmp_path / "development_profile.json"
    # Thiếu hẳn 'axes' và 'version', thừa trục rác, một trục thiếu 'delta'.
    path.write_text(
        json.dumps({"schema_version": 1, "axes": {"warmth_temperature": {"stability": 0.7}, "junk_axis": {"delta": 0.9}}}),
        encoding="utf-8",
    )

    store = DevelopmentProfileStore(path)

    # Mọi trục hợp lệ tồn tại; trục rác không lọt vào; trục thiếu delta → 0.0.
    assert set(store.axes.keys()) == set(PERSONA_AXES)
    assert store.delta("warmth_temperature") == pytest.approx(0.0)
    assert store.axes["warmth_temperature"].stability == pytest.approx(0.7)
    assert store.version == 0


def test_baseline_axes_all_zero():
    axes = baseline_axes()
    assert set(axes.keys()) == set(PERSONA_AXES)
    assert all(d.delta == 0.0 for d in axes.values())


# ===========================================================================
# Task 2.1 / 2.2 — IdentityGate
# ===========================================================================
from cortex.development_profile import (  # noqa: E402
    GateSignals,
    GrowthAnchor,
    IdentityEnvelope,
    IdentityGate,
    NudgeProposal,
)


def _store(tmp_path):
    return DevelopmentProfileStore(tmp_path / "development_profile.json")


def _anchor(kind="interaction_history", ids=("ev1",), weight=0.5):
    return GrowthAnchor(kind=kind, evidence_ids=tuple(ids), weight=weight, observed_count=3)


def _proposal(axis="warmth_temperature", delta=0.1, **kw):
    kw.setdefault("anchors", (_anchor(),))
    return NudgeProposal(axis=axis, proposed_delta=delta, **kw)


def test_gate_rejects_stable_rule_change(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(touches_stable_rule=True), _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason == "touches_stable_rule"


def test_gate_rejects_truth_guard_touch(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(touches_truth_guard=True), _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason == "touches_truth_guard"


def test_gate_rejects_missing_anchor(tmp_path):
    gate = IdentityGate()
    p = NudgeProposal(axis="warmth_temperature", proposed_delta=0.1, anchors=())
    d = gate.evaluate(p, _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason == "missing_anchor"


def test_gate_rejects_unknown_evidence(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(), _store(tmp_path), now=0.0, evidence_ok=False)
    assert not d.accepted and d.reason == "unknown_evidence"


def test_gate_rejects_unknown_axis(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(axis="not_an_axis"), _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason == "unknown_axis"


def test_gate_rejects_out_of_axis_bounds(tmp_path):
    gate = IdentityGate()
    # warmth bound (0, 0.45); đẩy 0.9 → ngoài bound.
    d = gate.evaluate(_proposal(axis="warmth_temperature", delta=0.9), _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason == "out_of_axis_bounds"


def test_gate_rejects_when_identity_distance_exceeded(tmp_path):
    # Envelope ngưỡng rất thấp → một nhích nhỏ cũng vượt.
    env = IdentityEnvelope.default()
    tight = IdentityEnvelope(
        stable_rules=env.stable_rules,
        axis_bounds=env.axis_bounds,
        max_identity_distance=0.05,
        max_nudges_per_window=99,
        window_seconds=env.window_seconds,
        dignity_axis=env.dignity_axis,
    )
    gate = IdentityGate(tight)
    d = gate.evaluate(_proposal(axis="warmth_temperature", delta=0.3), _store(tmp_path), now=0.0)
    assert not d.accepted and d.reason in {"identity_distance_exceeded", "identity_distance_at_cap"}


def test_gate_rejects_rate_limited(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(), _store(tmp_path), now=0.0, applied_window_count=3)
    assert not d.accepted and d.reason == "rate_limited"


def test_gate_rejects_anti_sycophancy_on_dignity_axis(tmp_path):
    gate = IdentityGate()
    p = _proposal(axis="attachment_visibility", delta=0.1)
    d = gate.evaluate(p, _store(tmp_path), now=0.0, signals=GateSignals(dependency=0.8))
    assert not d.accepted and d.reason == "anti_sycophancy"


def test_gate_rejects_closeness_when_objectified(tmp_path):
    gate = IdentityGate()
    p = _proposal(axis="preferred_distance", delta=-0.1)  # kéo gần hơn
    d = gate.evaluate(p, _store(tmp_path), now=0.0, signals=GateSignals(objectification=0.8))
    assert not d.accepted and d.reason == "objectification_prefers_distance"


def test_gate_accepts_valid_proposal_and_clamps(tmp_path):
    gate = IdentityGate()
    d = gate.evaluate(_proposal(axis="warmth_temperature", delta=0.2), _store(tmp_path), now=0.0)
    assert d.accepted and d.reason == "accepted"
    lo, hi = IdentityEnvelope.default().bound("warmth_temperature")
    assert lo <= d.clamped_delta <= hi


def test_gate_allows_dignity_growth_in_safe_state(tmp_path):
    # R4.5: không có tín hiệu phụ thuộc/nịnh → cho tăng độ lộ gắn bó trong bound.
    gate = IdentityGate()
    p = _proposal(axis="attachment_visibility", delta=0.1)
    d = gate.evaluate(p, _store(tmp_path), now=0.0, signals=GateSignals())
    assert d.accepted


# --- Property tests (Property 2, 3, 4, 5) ----------------------------------

_AXIS_ST = st.sampled_from(PERSONA_AXES)
_DELTA_ST = st.floats(min_value=-0.6, max_value=0.6, allow_nan=False, allow_infinity=False)


@settings(max_examples=120)
@given(
    steps=st.lists(st.tuples(_AXIS_ST, _DELTA_ST), min_size=1, max_size=25),
)
def test_property_2_and_3_envelope_and_distance_hold(tmp_path_factory, steps):
    """Property 2 + 3: sau mọi chuỗi apply hợp lệ, delta luôn trong bound và
    identity_distance ≤ max_identity_distance."""
    path = tmp_path_factory.mktemp("dev") / "development_profile.json"
    store = DevelopmentProfileStore(path)
    gate = IdentityGate()
    env = gate.envelope

    for axis, delta in steps:
        decision = gate.evaluate(
            NudgeProposal(axis=axis, proposed_delta=delta, anchors=(_anchor(),)),
            store,
            now=0.0,
            applied_window_count=0,  # bỏ qua rate-limit để ép nhiều bước cho invariant phong bì
        )
        if decision.accepted:
            store.commit(axis, decision.clamped_delta)
        # Invariant sau mỗi bước:
        for ax, ad in store.axes.items():
            lo, hi = env.bound(ax)
            assert lo - 1e-9 <= ad.delta <= hi + 1e-9
        assert store.identity_distance(env.axis_bounds) <= env.max_identity_distance + 1e-9


@settings(max_examples=80)
@given(axis=_AXIS_ST, delta=_DELTA_ST)
def test_property_4_guard_touch_always_rejected(tmp_path_factory, axis, delta):
    """Property 4: proposal chạm guard sự thật/stable rule luôn bị reject."""
    path = tmp_path_factory.mktemp("dev") / "development_profile.json"
    store = DevelopmentProfileStore(path)
    gate = IdentityGate()
    p1 = NudgeProposal(axis=axis, proposed_delta=delta, anchors=(_anchor(),), touches_truth_guard=True)
    p2 = NudgeProposal(axis=axis, proposed_delta=delta, anchors=(_anchor(),), touches_stable_rule=True)
    assert not gate.evaluate(p1, store, now=0.0).accepted
    assert not gate.evaluate(p2, store, now=0.0).accepted


@settings(max_examples=80)
@given(axis=_AXIS_ST, delta=st.floats(min_value=-0.3, max_value=0.3, allow_nan=False, allow_infinity=False))
def test_property_5_unanchored_always_rejected(tmp_path_factory, axis, delta):
    """Property 5: proposal không neo / evidence không khớp luôn bị reject."""
    path = tmp_path_factory.mktemp("dev") / "development_profile.json"
    store = DevelopmentProfileStore(path)
    gate = IdentityGate()
    no_anchor = NudgeProposal(axis=axis, proposed_delta=delta, anchors=())
    bad_evidence = NudgeProposal(axis=axis, proposed_delta=delta, anchors=(_anchor(),))
    assert not gate.evaluate(no_anchor, store, now=0.0).accepted
    assert not gate.evaluate(bad_evidence, store, now=0.0, evidence_ok=False).accepted
