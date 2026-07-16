# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from runtime.hardening_config import HardeningConfig
from runtime.observability import ErisObservability
from runtime.phase7_validation import Phase7ValidationManager
from transport.udp import UdpTransport


def _clean_metrics(store: ErisObservability, turns: int = 20) -> None:
    for index in range(turns):
        store.increment("phase7_public_turn_total")
        store.increment("hardening_public_turn_total")
        store.observe("chat_latency_ms", 900 + index)
        store.observe("tts_latency_ms", 1400 + index)
        store.increment("panel_state_sent_total")
        store.increment("panel_state_ack_complete_total")
        store.observe("panel_state_ack_latency_ms", 30 + index)
    store.increment("greeting_validation_total", tags={"result": "pass"})
    for _ in range(5):
        store.increment("action_confirmation_total")
    store.increment("memory_provenance_total")
    store.increment("repair_state_event_total")


def test_phase7_manager_writes_pass_report_with_real_coverage(tmp_path: Path) -> None:
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "all.jsonl")
    store.write_jsonl = False
    config = replace(
        HardeningConfig(),
        production_validation_enabled=True,
        production_validation_turns=20,
        production_validation_dir=str(tmp_path / "phase7"),
    )
    manager = Phase7ValidationManager(
        observability=store,
        config=config,
        release_id="phase7-test",
        provider_health_fn=lambda: {
            "action": {"ready": True, "provider": "action"},
            "speech": {"ready": True, "provider": "speech"},
            "memory": {"ready": True, "provider": "memory"},
            "budget": {"ready": True, "provider": "budget"},
        },
        environment_fn=lambda: {"runtime": "test"},
    )
    assert manager.start(validation_id="validation-test") is not None
    _clean_metrics(store)
    for scenario in manager.REQUIRED_SCENARIOS:
        manager.mark_scenario(scenario, passed=True, detail="test evidence")
    # Không dùng record_public_turn để tránh double-count metric trong helper.
    assert manager.state is not None
    manager.state.public_turns = 20
    report = manager.finalize(reason="test")
    assert report is not None
    assert report.status == "pass"
    assert report.scenario_coverage["complete"] is True
    assert Path(manager.state.report_path).is_file()
    assert Path(manager.state.events_path).is_file()
    payload = json.loads(Path(manager.state.report_path).read_text(encoding="utf-8"))
    assert payload["validation_id"] == "validation-test"
    assert payload["public_turns"] == 20


def test_phase7_panel_delivery_fails_when_body_never_acknowledges(tmp_path: Path) -> None:
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "all.jsonl")
    store.write_jsonl = False
    config = replace(
        HardeningConfig(),
        production_validation_enabled=True,
        production_validation_turns=20,
        production_validation_dir=str(tmp_path / "phase7"),
    )
    manager = Phase7ValidationManager(observability=store, config=config)
    manager.start(validation_id="missing-panel-ack")
    for _ in range(20):
        store.increment("hardening_public_turn_total")
        store.increment("phase7_public_turn_total")
        store.increment("panel_state_sent_total")
    assert manager.state is not None
    manager.state.public_turns = 20
    report = manager.finalize(reason="test")
    assert report is not None
    finding = next(item for item in report.findings if item.name == "panel_delivery_ack_rate")
    assert finding.status == "fail"
    assert report.status == "fail"


def test_panel_packet_has_receipt_identity_and_hardening_status(monkeypatch) -> None:
    transport = UdpTransport("127.0.0.1", 9, "127.0.0.1", 0)
    sent: list[str] = []
    monkeypatch.setattr(transport, "send_text", sent.append)
    try:
        packet_id = transport.send_panel_state({
            "private_mind_digest": {"anchor": {"deception": {"count": 1}}},
            "emotion_debug": {"summary": {"valence": 0.1}, "items": {"calm": 0.7}},
            "depth_v2": {"schema": 2, "signals": ["x"]},
            "hardening_status": {"release": {"status": "pass"}, "phase7": {"status": "running"}},
        })
    finally:
        transport.close()
    assert packet_id and packet_id.startswith("panel-")
    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert payload["packet_id"] == packet_id
    assert payload["sent_at"] > 0
    assert payload["hardening_status"]["phase7"]["status"] == "running"


def test_udp_start_can_enable_phase7_even_when_boot_config_is_disabled(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from runtime.coordinator import RuntimeCoordinator

    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "obs.jsonl")
    store.write_jsonl = False
    disabled = replace(
        HardeningConfig(),
        production_validation_enabled=False,
        production_validation_turns=20,
        production_validation_dir=str(tmp_path / "phase7"),
    )
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator.observability = store
    coordinator.hardening_config = disabled
    coordinator.phase7_validation = Phase7ValidationManager(observability=store, config=disabled)
    coordinator.provider_health_snapshot = lambda: {}
    coordinator.rollout_controller = None
    coordinator.runtime_session_id = "test-runtime"
    coordinator.tts_engine = None
    coordinator.transport = SimpleNamespace(send_json=lambda payload: setattr(coordinator, "last_ack", payload))
    coordinator._handle_phase7_validation_control({"action": "start", "validation_id": "manual-start"})
    assert coordinator.phase7_validation.active
    assert coordinator.phase7_validation.state.validation_id == "manual-start"
    assert coordinator.last_ack["status"] == "ok"
