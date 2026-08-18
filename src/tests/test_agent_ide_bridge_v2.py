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
            second_received = []
            deadline = time.time() + 3
            while time.time() < deadline:
                packet = json.loads(ws.recv(timeout=3))
                second_received.append(packet)
                if packet.get("type") == "message.accepted":
                    break
            ack = next(item for item in second_received if item.get("type") == "message.accepted")
            assert ack["continued"] is True
            # Backend persist user message thành event thật; UI không cần tự bịa
            # bubble optimistic rồi hy vọng history khớp sau reconnect.
            assert any(item.get("type") == "message.user" for item in second_received)
            assert resumed and resumed[-1][0] == "task-ws-1"
            assert resumed[-1][1]["response"]["text"].startswith("chọn hướng A")
            # Resume nhận snapshot editor mới chứ không mắc kẹt ở context lúc task bắt đầu.
            assert resumed[-1][1]["response"]["ideContext"]["current"]["path"] == "runtime/bar.py"
            assert resumed[-1][1]["response"]["ideContext"]["client"]["sessionId"] == "session-vscode"
    finally:
        service.stop()


def test_task_store_projects_semantic_coding_state_and_thread_history(tmp_path):
    store = AgentTaskStore(tmp_path / "tasks.json")
    store.create_task("sửa parser", task_id="semantic-1", thread_id="thread-sem", session_id="session-sem")
    store.append_event(
        "semantic-1",
        "coding_state",
        summary="Đang đọc parser.py",
        data={
            "phase": "inspecting",
            "current_action": "Đọc parser và diagnostics",
            "current_file": "runtime/parser.py",
            "files_inspected": ["runtime/parser.py"],
            "next_action": "Chạy test parser",
        },
    )
    store.append_event(
        "semantic-1",
        "test_result",
        summary="Test chưa đạt",
        data={"passed": 4, "failed": 1, "summary": "4 passed, 1 failed"},
    )
    long_diff = "diff --git a/runtime/parser.py b/runtime/parser.py\n" + ("+changed\n" * 700)
    store.append_event(
        "semantic-1",
        "file_changed",
        summary="Đã sửa parser",
        data={"path": "runtime/parser.py", "diff": long_diff},
    )

    task = store.get_task("semantic-1", event_limit=0)
    assert task is not None
    state = task["coding_state"]
    assert state["current_file"] == "runtime/parser.py"
    assert "runtime/parser.py" in state["files_inspected"]
    assert "runtime/parser.py" in state["files_modified"]
    assert state["test_state"]["failed"] == 1

    history = store.tasks_for_thread("thread-sem", session_id="session-sem", event_limit=50)
    assert len(history) == 1
    assert [event["type"] for event in history[0]["events"]] == [
        "coding_state", "test_result", "file_changed"
    ]
    # Diff semantic phải sống qua public projection/reconnect, không bị generic
    # debug truncation biến thành {truncated:true}.
    assert history[0]["events"][-1]["data"]["diff"].startswith("diff --git")
    assert len(history[0]["events"][-1]["data"]["diff"]) > 3500


def test_protocol_projects_user_coding_diff_and_editor_result():
    common = {
        "event_id": "evt", "seq": 10, "task_id": "t", "thread_id": "th",
        "session_id": "s", "created_at": 1.0,
    }
    user = project_agent_event({**common, "type": "user_message", "data": {"content": "fix bug"}})
    assert user[0]["type"] == "message.user"
    assert user[0]["payload"]["content"] == "fix bug"

    coding = project_agent_event({
        **common, "type": "coding_state",
        "data": {"phase": "testing", "current_file": "a.py"},
    })
    assert coding[0]["type"] == "coding.state"
    assert coding[0]["payload"]["phase"] == "testing"

    diff = project_agent_event({
        **common, "type": "diff_observed", "summary": "git diff",
        "data": {"chars": 12, "diff": "diff --git a/a.py b/a.py"},
    })
    assert diff[0]["type"] == "artifact.diff"
    assert diff[0]["payload"]["diff"].startswith("diff --git")

    editor = project_agent_event({
        **common, "type": "editor_result", "summary": "opened",
        "data": {"requestId": "ide1", "command": "editor.openDiff", "success": True},
    })
    assert editor[0]["type"] == "editor.result"
    assert editor[0]["payload"]["success"] is True


def test_websocket_history_editor_ack_and_session_boundary(tmp_path):
    from websockets.sync.client import connect

    store = AgentTaskStore(tmp_path / "tasks.json")
    bus = AgentEventBus(store=store, legacy_udp=False)
    own = store.create_task("own", task_id="own-1", thread_id="thread-own", session_id="session-own")
    bus.emit(own["task_id"], "user_message", summary="own", data={"content": "own"})
    bus.emit(own["task_id"], "coding_state", summary="inspect", data={"phase": "inspecting"})
    other = store.create_task("other", task_id="other-1", thread_id="thread-other", session_id="session-other")
    bus.emit(other["task_id"], "user_message", summary="secret", data={"content": "secret"})

    service = AgentWebSocketService(
        store=store,
        event_bus=bus,
        start_task=lambda goal, **kwargs: {"status": "started", "task_id": "unused"},
        resume_task=lambda task_id, **kwargs: {"status": "resuming", "task_id": task_id},
        control_task=lambda task_id, **kwargs: {"status": "queued", "task_id": task_id},
        port=0,
        discovery_path=tmp_path / "discovery.json",
    )
    assert service.start()
    try:
        with connect(service.endpoint, open_timeout=3) as ws:
            ws.send(json.dumps({
                "type": "session.hello", "token": service.token, "sessionId": "session-own",
                "client": "test-client", "lastEventSeq": store.latest_event_seq(),
                "capabilities": ["editor.openDiff"],
            }))
            assert json.loads(ws.recv(timeout=3))["type"] == "session.ready"
            assert json.loads(ws.recv(timeout=3))["type"] == "event.replay.end"

            ws.send(json.dumps({"type": "thread.history", "threadId": "thread-own"}))
            history = json.loads(ws.recv(timeout=3))
            assert history["type"] == "thread.history"
            assert any(item["type"] == "message.user" for item in history["events"])
            assert any(item["type"] == "coding.state" for item in history["events"])

            ws.send(json.dumps({"type": "task.get", "taskId": "other-1"}))
            denied = json.loads(ws.recv(timeout=3))
            assert denied["type"] == "error"
            assert denied["code"] == "task_not_found"

            ws.send(json.dumps({
                "type": "editor.command.result", "taskId": "own-1", "requestId": "ide-1",
                "command": "editor.openDiff", "success": True, "message": "opened",
            }))
            editor_result = json.loads(ws.recv(timeout=3))
            assert editor_result["type"] == "editor.result"
            assert editor_result["payload"]["requestId"] == "ide-1"
    finally:
        service.stop()


def test_coordinator_recovers_stale_running_task_instead_of_queueing_forever(tmp_path):
    from runtime.coordinator import RuntimeCoordinator

    store = AgentTaskStore(tmp_path / "tasks.json")
    store.create_task("recover me", task_id="stale-1", thread_id="thread-stale", session_id="session-stale")
    store.update_task("stale-1", status="running")

    class _Harness:
        def stop_task(self, task_id, reason=""):
            return {"status": "stopped", "task_id": task_id, "reason": reason}

    coordinator = object.__new__(RuntimeCoordinator)
    coordinator.agent_harness = _Harness()
    coordinator.agent_task_store = store
    coordinator._agent_task_threads = {}
    captured = []
    coordinator.resume_agent_task_async = lambda task_id, **kwargs: captured.append((task_id, kwargs)) or {
        "status": "resuming", "task_id": task_id
    }

    result = RuntimeCoordinator.control_agent_task(
        coordinator,
        "stale-1",
        action="resume",
        source="vscode",
        ide_context={"current": {"path": "runtime/foo.py"}},
    )
    assert result["status"] == "resuming"
    assert captured[0][0] == "stale-1"
    assert captured[0][1]["ide_context"]["current"]["path"] == "runtime/foo.py"
    assert store.consume_controls("stale-1") == []


def test_prompt_context_uses_semantic_state_not_raw_reasoning(tmp_path):
    from runtime.prompt_context_builder import PromptContextBuilderMixin

    store = AgentTaskStore(tmp_path / "tasks.json")
    store.create_task("fix parser", task_id="prompt-1", thread_id="thread-p", session_id="session-p")
    store.append_event(
        "prompt-1",
        "coding_state",
        summary="semantic",
        data={
            "phase": "testing",
            "current_action": "Đang chạy parser tests",
            "current_file": "runtime/parser.py",
            "files_modified": ["runtime/parser.py"],
            "test_state": {"status": "running", "passed": 0, "failed": 0},
        },
    )

    holder = object.__new__(PromptContextBuilderMixin)
    holder.agent_task_store = store
    rendered = PromptContextBuilderMixin._agent_execution_prompt_context(holder)
    assert "BACKSTAGE_AGENT_RUNTIME_V3" in rendered
    assert '"phase":"testing"' in rendered
    assert "runtime/parser.py" in rendered
    assert "chain-of-thought" in rendered


def test_live_ide_rpc_roundtrip_uses_connected_vscode_context(tmp_path):
    import threading
    from websockets.sync.client import connect
    from runtime.agent_service.ide_rpc import IdeRpcBroker

    store = AgentTaskStore(tmp_path / "tasks.json")
    bus = AgentEventBus(store=store, legacy_udp=False)
    store.create_task(
        "inspect live problems",
        task_id="rpc-1",
        thread_id="thread-rpc",
        session_id="session-rpc",
    )
    broker = IdeRpcBroker(bus, default_timeout=2.0)
    service = AgentWebSocketService(
        store=store,
        event_bus=bus,
        start_task=lambda goal, **kwargs: {"status": "started", "task_id": "unused"},
        resume_task=lambda task_id, **kwargs: {"status": "resuming", "task_id": task_id},
        control_task=lambda task_id, **kwargs: {"status": "queued", "task_id": task_id},
        ide_rpc=broker,
        port=0,
        discovery_path=tmp_path / "discovery.json",
    )
    assert service.start()
    try:
        with connect(service.endpoint, open_timeout=3) as ws:
            ws.send(json.dumps({
                "type": "session.hello",
                "token": service.token,
                "sessionId": "session-rpc",
                "client": "test-client",
                "lastEventSeq": store.latest_event_seq(),
                "capabilities": ["context.problems"],
            }))
            assert json.loads(ws.recv(timeout=3))["type"] == "session.ready"
            assert json.loads(ws.recv(timeout=3))["type"] == "event.replay.end"

            holder: dict[str, object] = {}

            def _request():
                holder["result"] = broker.request("rpc-1", "ide.getProblems", {"scope": "workspace"})

            worker = threading.Thread(target=_request)
            worker.start()
            request = json.loads(ws.recv(timeout=3))
            assert request["type"] == "ide.request"
            assert request["payload"]["method"] == "ide.getProblems"
            request_id = request["payload"]["requestId"]

            ws.send(json.dumps({
                "type": "ide.response",
                "taskId": "rpc-1",
                "requestId": request_id,
                "method": "ide.getProblems",
                "success": True,
                "data": {"items": [{"path": "runtime/a.py", "message": "boom"}]},
            }))
            worker.join(timeout=3)
            assert not worker.is_alive()
            result = holder["result"]
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["data"]["items"][0]["path"] == "runtime/a.py"
    finally:
        service.stop()


def test_changeset_projection_persists_accept_and_protocol(tmp_path):
    store = AgentTaskStore(tmp_path / "tasks.json")
    store.create_task("patch", task_id="cs-1", thread_id="thread-cs", session_id="session-cs")
    created = store.append_event(
        "cs-1",
        "changeset_created",
        summary="Patch 2 files",
        data={
            "change_set_id": "op-42",
            "operation_id": "op-42",
            "checkpoint_id": "cp-before",
            "files": ["a.py", "b.py"],
            "status": "pending",
        },
    )
    task = store.get_task("cs-1", event_limit=0)
    assert task["change_sets"][0]["status"] == "pending"
    assert task["change_sets"][0]["checkpoint_id"] == "cp-before"

    packets = project_agent_event({**created, "task_id": "cs-1", "thread_id": "thread-cs", "session_id": "session-cs"})
    assert packets[0]["type"] == "changeset.created"
    assert packets[0]["payload"]["changeSetId"] == "op-42"

    accepted = store.append_event(
        "cs-1",
        "changeset_accepted",
        summary="accepted",
        data={"change_set_id": "op-42", "operation_id": "op-42", "files": ["a.py", "b.py"]},
    )
    task = store.get_task("cs-1", event_limit=0)
    assert task["change_sets"][0]["status"] == "accepted"
    update = project_agent_event({**accepted, "task_id": "cs-1", "thread_id": "thread-cs", "session_id": "session-cs"})
    assert update[0]["type"] == "changeset.updated"
    assert update[0]["payload"]["status"] == "accepted"
