# -*- coding: utf-8 -*-
"""V103 FINAL2 - verification/observability closure theo PDF nervous roadmap."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.activation_nervous_system_v98 import (
    ContinuousDynamicsRuntime,
    ModulationEvent,
    SharedActivationBus,
)
from runtime.ai_orchestrated.autonomous_trace import (
    NERVOUS_COMPACT_SCHEMA,
    NERVOUS_TRACE_SCHEMA,
    PublicTurnTraceStore,
)
from runtime.nervous_system_v103_final import (
    NervousAutonomousAuthorityV103,
    NervousSystemConfigV103,
)
from tools.run_v103_nervous_replay import run_replay


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v103_final2"


def _vocal_initial():
    return {
        "curiosity": 0.05,
        "boredom": 0.90,
        "social_need": 0.90,
        "task_focus": 0.0,
        "concern_salience": 0.05,
        "uncertainty": 0.0,
        "expressive_pressure": 1.0,
        "inhibition": 0.0,
        "fatigue": 0.0,
    }


def test_nervous_trace_carries_field_inputs_motor_commit_surface_and_tts(tmp_path):
    now = 0.0
    bus = SharedActivationBus(clock=lambda: now, initial_values=_vocal_initial())
    authority = NervousAutonomousAuthorityV103(
        bus, config=NervousSystemConfigV103(mode="active"), clock=lambda: now,
    )
    bus.submit(ModulationEvent(
        source="ambient_stagnation",
        impulses={"boredom": 0.14, "social_need": 0.05},
        strength=0.9, created_at=0.0, event_id="trace:stimulus",
    ))
    authority.preprocess_affordances((), now=0.0)
    _, decision = authority.preprocess_affordances((), now=0.60)
    assert decision.committed and decision.channel == "vocalization"

    store = PublicTurnTraceStore(path=tmp_path / "trace.jsonl")
    payload = authority.trace_snapshot(now=0.60)
    payload.update({
        "trace_id": "nrv:test",
        "turn_id": "nrv:test",
        "channel": "autonomous",
        "stage": "nervous",
        "owner": "continuous_nervous_system",
    })
    store.append("nervous_state", payload, now=0.60)
    store.append("surface_result", {
        "trace_id": "nrv:test", "stage": "surface", "owner": "nervous_local_motor",
        "surface_status": "local_exact", "surface": "haiz", "same_text_tts": True,
    }, now=0.61)
    store.append("tts_event", {
        "trace_id": "nrv:test", "stage": "tts", "owner": "tts", "tts_event": "audio_done",
    }, now=0.70)
    store.append("outcome", {
        "trace_id": "nrv:test", "stage": "outcome", "owner": "public_lifecycle", "outcome": "delivered",
    }, now=0.80)

    rows = store.recent(limit=20, trace_id="nrv:test")
    assert rows[0]["schema"] == NERVOUS_TRACE_SCHEMA
    assert rows[0]["field_snapshot"]["boredom"] == pytest.approx(0.9)
    assert rows[0]["top_inputs"]
    assert rows[0]["motor"]["vocalization"] > rows[0]["motor"]["body"]
    assert rows[0]["commit"] == "vocalization"

    compact = store.compact_trace("nrv:test")
    assert compact["schema"] == NERVOUS_COMPACT_SCHEMA
    assert compact["commit"] == "vocalization"
    assert compact["surface"] == "haiz"
    assert compact["tts_status"] == "done"
    assert compact["outcome"] == "delivered"


def test_v97_fixture_migrates_to_modulation_without_restoring_candidate_authority():
    fixture = json.loads((FIXTURES / "legacy_v97_public_state.json").read_text(encoding="utf-8"))
    now = 10.0
    bus = SharedActivationBus(clock=lambda: now)
    authority = NervousAutonomousAuthorityV103(
        bus, config=NervousSystemConfigV103(mode="active"), clock=lambda: now,
    )
    events = authority.migrate_legacy_state(fixture, source_version="v97", now=now)

    assert events and events[0].source == "legacy_v97_state_migration"
    assert "no_candidate_restore" in events[0].tags
    assert all("candidate" not in event.targets for event in events)
    assert authority.recent_history()[-1]["event"] == "legacy_state_migration"

    dynamics = ContinuousDynamicsRuntime(bus, clock=lambda: now)
    before = bus.snapshot()
    now = 10.5
    after = dynamics.tick_once(now=now, dt=0.5)
    assert after.value("inhibition") > before.value("inhibition")
    assert after.value("task_focus") > before.value("task_focus")


def test_v102_fixture_migrates_commitment_charge_into_fields_not_commitment_objects():
    fixture = json.loads((FIXTURES / "legacy_v102_commitment_state.json").read_text(encoding="utf-8"))
    now = 20.0
    bus = SharedActivationBus(clock=lambda: now)
    authority = NervousAutonomousAuthorityV103(
        bus, config=NervousSystemConfigV103(mode="active"), clock=lambda: now,
    )
    events = authority.migrate_legacy_state(fixture, source_version="v102", now=now)

    assert events and events[0].source == "legacy_v102_state_migration"
    assert "commitment_to_field" in events[0].tags
    assert set(events[0].targets) >= {"expressive_pressure", "concern_salience", "task_focus"}

    dynamics = ContinuousDynamicsRuntime(bus, clock=lambda: now)
    before = bus.snapshot()
    now = 20.5
    after = dynamics.tick_once(now=now, dt=0.5)
    assert after.value("expressive_pressure") > before.value("expressive_pressure")
    assert after.value("concern_salience") > before.value("concern_salience")


def test_full_replay_is_deterministic_and_exercises_public_receipt_and_candidate_bypass():
    first = run_replay()
    second = run_replay()
    assert first == second
    assert first["pass"] is True
    assert first["sha256"] == second["sha256"]
    segments = {item["label"]: item for item in first["segments"]}
    assert segments["local_vocalization"]["surface"] == "haiz"
    assert segments["proposition_candidate_bypass"]["candidate_bypass"].startswith(
        "candidate_bypass:nervous_motor:proposition"
    )
    assert any(row.get("receipt") == "public_commit" for row in segments["local_vocalization"]["rows"])
    assert any(row.get("receipt") == "public_commit" for row in segments["proposition_candidate_bypass"]["rows"])


def test_trace_sanitizer_does_not_accept_private_prompt_or_raw_material(tmp_path):
    store = PublicTurnTraceStore(path=tmp_path / "trace.jsonl")
    store.append("nervous_state", {
        "trace_id": "safe",
        "field_snapshot": {"boredom": 0.7},
        "motor": {"vocalization": 0.8},
        "commit": "vocalization",
        "private_prompt": "DO NOT LOG",
        "mental_material": "PRIVATE MATERIAL",
    })
    raw = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "DO NOT LOG" not in raw
    assert "PRIVATE MATERIAL" not in raw
