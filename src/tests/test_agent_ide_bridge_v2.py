from __future__ import annotations

import json
import time

from runtime.agent_harness.event_bus import AgentEventBus
from runtime.agent_harness.task_store import AgentTaskStore
from runtime.agent_service.protocol import project_agent_event
from runtime.agent_service.websocket_server import AgentWebSocketService


def test_task_store_event_seq_replay_and_session_restore(tmp_path):
    path = tmp_path / "tasks.json"
    store = AgentTaskStore(path)
    first = store.create_task("first", task_id="t1", thread_id="thread-a", session_id="session-a")
    second = store.create_task("second", task_id="t2", thread_id="thread-b", session_id="session-b")
    e1 = store.append_event(first["task_id"], "task_started", summary="one")
    e2 = store.append_event(second["task_id"], "task_started", summary="two")
    assert e1 and e2 and e2["seq"] == e1["seq"] + 1

    reopened = AgentTaskStore(path)
    replay = reopened.events_since(e1["seq"])
    assert [item["task_id"] for item in replay] == ["t2"]
    assert reopened.list_tasks(session_id="session-a")[0]["task_id"] == "t1"
    assert reopened.latest_task_for_thread(
        "thread-a", session_id="session-a", statuses={"running"}
    )["task_id"] == "t1"


def test_protocol_projects_interrupt_and_artifact_semantics():
    interrupt = project_agent_event({
        "type": "interrupt_requested",
        "event_id": "e1",
        "seq": 7,
        "task_id": "t1",
        "thread_id": "th1",
        "session_id": "s1",
        "created_at": 1.0,
        "summary": "Chọn cách sửa",
        "data": {
            "question": "Chọn cách sửa",
            "options": [{"id": "a", "label": "Minimal"}, {"id": "b", "label": "Refactor"}],
            "allowOther": True,
        },
    })
    assert interrupt[0]["type"] == "interrupt.request"
    assert interrupt[0]["payload"]["options"][1]["id"] == "b"

    artifact = project_agent_event({
        "type": "file_changed",
        "event_id": "e2",
        "seq": 8,
        "task_id": "t1",
        "thread_id": "th1",
        "session_id": "s1",
        "created_at": 2.0,
        "summary": "changed",
        "data": {"path": "runtime/foo.py"},
    })
    assert artifact[0]["type"] == "artifact.modified"
    assert artifact[0]["payload"]["path"] == "runtime/foo.py"


def test_websocket_service_handshake_routes_new_message_and_restores_tasks(tmp_path):
    from websockets.sync.client import connect

    store = AgentTaskStore(tmp_path / "tasks.json")
    bus = AgentEventBus(store=store, legacy_udp=False)
    started: list[tuple[str, dict]] = []
    resumed: list[tuple[str, dict]] = []
    controlled: list[tuple[str, dict]] = []

    def start_task(goal: str, **kwargs):
        started.append((goal, kwargs))
        task = store.create_task(
            goal,
            task_id="task-ws-1",
            thread_id=kwargs["thread_id"],
            session_id=kwargs["session_id"],
        )
        bus.emit(task["task_id"], "task_started", summary=goal)
        return {"status": "started", "task_id": task["task_id"]}

    def resume_task(task_id: str, **kwargs):
        resumed.append((task_id, kwargs))
        return {"status": "resuming", "task_id": task_id}

    def control_task(task_id: str, **kwargs):
        controlled.append((task_id, kwargs))
        return {"status": "queued", "task_id": task_id}

    service = AgentWebSocketService(
        store=store,
        event_bus=bus,
        start_task=start_task,
        resume_task=resume_task,
        control_task=control_task,
        port=0,
        discovery_path=tmp_path / "discovery.json",
    )
    assert service.start()
    try:
        with connect(service.endpoint, open_timeout=3) as ws:
            ws.send(json.dumps({
                "type": "session.hello",
                "token": service.token,
                "sessionId": "session-vscode",
                "client": "test-client",
                "lastEventSeq": 0,
                "capabilities": ["editor.openFile"],
            }))
            ready = json.loads(ws.recv(timeout=3))
            assert ready["type"] == "session.ready"
            assert ready["tasks"] == []
            assert json.loads(ws.recv(timeout=3))["type"] == "event.replay.end"

            ws.send(json.dumps({
                "type": "message.user",
                "threadId": "thread-vscode",
                "content": "đọc lỗi rồi sửa",
                "context": {"current": {"path": "runtime/foo.py"}},
            }))
            received = []
            deadline = time.time() + 3
            while time.time() < deadline:
                packet = json.loads(ws.recv(timeout=3))
                received.append(packet)
                if packet.get("type") == "message.accepted":
                    break
            accepted = next(item for item in received if item.get("type") == "message.accepted")
            assert accepted["taskId"] == "task-ws-1"
            assert accepted["continued"] is False
            assert started and started[0][1]["ide_context"]["client"]["capabilities"] == ["editor.openFile"]

            # Chuyển projection sang waiting_user. Tin nhắn tiếp theo phải resume
            # cùng task chứ không tạo task LangGraph thứ hai trên cùng thread.
            bus.emit(
                "task-ws-1",
                "interrupt_requested",
                summary="Chọn hướng",
                data={
                    "question": "Chọn hướng",
                    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "allowOther": True,
                },
            )
            # Nhận event interrupt live trước khi gửi câu trả lời tự do.
            packet = json.loads(ws.recv(timeout=3))
            assert packet["type"] == "interrupt.request"

            ws.send(json.dumps({
                "type": "message.user",
                "threadId": "thread-vscode",
                "content": "chọn hướng A nhưng sửa tối thiểu",
                "context": {"current": {"path": "runtime/bar.py"}},
            }))
            ack = json.loads(ws.recv(timeout=3))
            assert ack["type"] == "message.accepted"
            assert ack["continued"] is True
            assert resumed and resumed[-1][0] == "task-ws-1"
            assert resumed[-1][1]["response"]["text"].startswith("chọn hướng A")
            # Resume nhận snapshot editor mới chứ không mắc kẹt ở context lúc task bắt đầu.
            assert resumed[-1][1]["response"]["ideContext"]["current"]["path"] == "runtime/bar.py"
            assert resumed[-1][1]["response"]["ideContext"]["client"]["sessionId"] == "session-vscode"
    finally:
        service.stop()
