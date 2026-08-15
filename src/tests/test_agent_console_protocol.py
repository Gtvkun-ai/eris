from __future__ import annotations

import json

from runtime.agent_harness.supervisor_bridge import AgentSupervisorBridge
from runtime.agent_harness.task_store import AgentTaskStore
from runtime.incoming_dispatcher import IncomingMessageDispatcher


def test_agent_task_store_projects_events_and_controls(tmp_path):
    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task = store.create_task("fix capability routing", executor="gemini", model="test")
    task_id = task["task_id"]

    store.append_event(task_id, "task_started", actor="system", summary="start")
    store.append_event(
        task_id,
        "skill_activated",
        actor="executor",
        summary="coding-debug",
        data={"skill": "coding-debug"},
    )
    store.append_event(
        task_id,
        "file_changed",
        actor="tool",
        summary="changed",
        data={"path": "runtime/foo.py"},
    )
    store.append_event(
        task_id,
        "test_result",
        actor="tool",
        summary="tests",
        data={"passed": 8, "failed": 1, "summary": "8 passed, 1 failed"},
    )
    store.append_event(
        task_id,
        "checkpoint_created",
        actor="system",
        summary="checkpoint",
        data={"checkpoint_id": "cp-17"},
    )
    store.enqueue_control(task_id, "directive", text="reuse existing registry")

    snapshot = store.snapshot(selected_task_id=task_id)
    projected = snapshot["tasks"][0]
    assert projected["status"] == "running"
    assert projected["active_skills"] == ["coding-debug"]
    assert projected["changed_files"] == ["runtime/foo.py"]
    assert projected["tests"]["failed"] == 1
    assert projected["checkpoint_id"] == "cp-17"
    assert projected["pending_controls"] == 1

    controls = store.consume_controls(task_id)
    assert controls[0]["action"] == "directive"
    assert store.snapshot(selected_task_id=task_id)["tasks"][0]["pending_controls"] == 0


def test_supervisor_bridge_can_redirect_without_mutating_agent_state_directly(tmp_path):
    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task_id = store.create_task("refactor router")["task_id"]

    # Không dùng UDP trong test: event bus giả chỉ persist event qua cùng API.
    class _Events:
        def emit(self, task_id, event_type, **kwargs):
            return store.append_event(task_id, event_type, **kwargs)

    supervisor = AgentSupervisorBridge(store=store, event_bus=_Events())
    assert supervisor.redirect(
        task_id,
        "Reuse CapabilityDiscovery; do not create a second router.",
        reason="duplicate abstraction",
        checkpoint_id="cp-3",
    )

    controls = store.consume_controls(task_id)
    assert [item["action"] for item in controls] == ["rollback", "directive"]
    snapshot = store.snapshot(selected_task_id=task_id)
    assert snapshot["tasks"][0]["events"][-1]["type"] == "supervisor_redirect"


def test_agent_snapshot_is_udp_sized_even_with_many_events(tmp_path):
    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task_id = store.create_task("large event stream")["task_id"]
    for index in range(100):
        store.append_event(
            task_id,
            "tool_result",
            actor="tool",
            summary=f"tool {index}",
            detail="x" * 5000,
            data={"tool": "project_read_file", "raw": "y" * 9000},
        )
    payload = {
        "type": "agent_console_ack",
        "agent_console": store.snapshot(selected_task_id=task_id, task_limit=12, event_limit=32),
    }
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 63_000


def test_dispatcher_exposes_agent_control_route():
    calls = []

    class _Owner:
        _maintenance_in_progress = False
        logger = None
        subsystem_health_registry = None
        _handle_agent_control = lambda self, msg: calls.append(msg)
        _handle_panel_state_ack = lambda self, msg: None
        _handle_phase7_validation_control = lambda self, msg: None
        _enter_chat_cycle = lambda self: None
        _handle_anchor_control = lambda self, msg: None
        _handle_depth_control = lambda self, msg: None
        _handle_settings_update = lambda self, msg: None
        _handle_settings_health = lambda self: None
        _handle_settings_connection_test = lambda self, msg: None
        _handle_maintenance_catalog = lambda self, msg=None: None
        _handle_maintenance_request = lambda self, msg: None
        _handle_debug_command = lambda self, msg: None
        _end_chat_cycle = lambda self: None
        _handle_stage_inbound_event = lambda self, msg: None
        _handle_force_speak_request = lambda self: None
        _capture_speech_interrupt_for_user = lambda self, text, timestamp: None
        _supersede_tts_for_new_user_turn = lambda self, reason: None
        _run_chat_cycle = lambda self, text, user_timestamp: None

    result = IncomingMessageDispatcher(_Owner()).dispatch({"type": "agent_control", "action": "snapshot"})
    assert result.handled is True
    assert calls and calls[0]["action"] == "snapshot"


def test_event_bus_listener_receives_task_id_without_log_scraping(tmp_path):
    from runtime.agent_harness.event_bus import AgentEventBus

    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task_id = store.create_task("inspect router")["task_id"]
    seen = []
    bus = AgentEventBus(store=store, port=65500)
    bus._send = lambda payload: True
    bus.add_listener(lambda event: seen.append(event))
    bus.emit(task_id, "tool_started", actor="tool", summary="read", data={"tool": "project_read_file"})
    assert seen and seen[0]["task_id"] == task_id
    assert seen[0]["type"] == "tool_started"
