from pathlib import Path

from runtime.agent_harness.capability_discovery import CapabilityDiscovery
from runtime.agent_harness.gemini_cli_executor import GeminiCliDecisionExecutor
from runtime.agent_harness.native_tool_adapter import NativeCapabilityToolAdapter
from runtime.agent_harness.permission_gate import PermissionGate, Permission
from runtime.agent_harness.skill_loader import SkillLoader


ROOT = Path(__file__).resolve().parents[1]


def test_skill_search_is_progressive_and_activation_reveals_tools():
    discovery = CapabilityDiscovery(str(ROOT / "powers"))
    result = discovery.search("đang nghe nhạc media")
    assert "desktop-awareness" in result
    assert "get_now_playing" not in result

    loader = SkillLoader(discovery)
    activated = loader.activate_skill("desktop-awareness")
    assert "get_now_playing" in activated
    assert "Desktop Awareness" in activated


def test_permission_gate_blocks_dangerous_git_subcommands():
    gate = PermissionGate()
    assert gate.check_permission("project_run_command", {"command": "git status"}) == Permission.ALLOW
    assert gate.check_permission("project_run_command", {"command": "git commit -am x"}) == Permission.ASK
    assert gate.check_permission("project_run_command", {"command": "git push origin main"}) == Permission.DENY
    assert gate.check_permission("project_run_command", {"command": "git reset --hard HEAD~1"}) == Permission.DENY


def test_gemini_decision_parser_handles_fenced_json():
    payload = GeminiCliDecisionExecutor.parse_decision(
        '```json\n{"action":"tool","summary":"check media","tool_call":{"name":"get_now_playing","args":{}}}\n```'
    )
    assert payload["action"] == "tool"
    assert payload["tool_call"]["name"] == "get_now_playing"


def test_native_adapter_uses_typed_execute_capability():
    class Result:
        success = True
        status = "observed"
        message = "ok"
        data = {"title": "Song"}
        evidence = ("observer:get_now_playing",)
        error_kind = ""
        observer_reason = ""

    class FakeExecutor:
        def __init__(self):
            self.calls = []

        def execute_capability(self, capability_id, arguments):
            self.calls.append((capability_id, arguments))
            return Result()

    fake = FakeExecutor()
    adapter = NativeCapabilityToolAdapter(fake)
    out = adapter.registry(["get_now_playing"])["get_now_playing"]()
    assert fake.calls == [("get_now_playing", {})]
    assert out["success"] is True
    assert out["data"]["title"] == "Song"


def test_chat_router_routes_concrete_code_task_but_not_simple_desktop():
    from runtime.agent_harness.chat_router import classify_agent_chat_route

    code = classify_agent_chat_route("sửa lỗi capability_route trong executive_cortex.py rồi chạy test")
    assert code.action == "execute"

    desktop = classify_agent_chat_route("em biết tôi đang nghe nhạc gì không")
    assert desktop.action == "none"
    assert desktop.reason == "single_step_native_capability"


def test_chat_router_asks_when_improvement_has_material_branches():
    from runtime.agent_harness.chat_router import classify_agent_chat_route

    route = classify_agent_chat_route("làm agent ngon hơn đi")
    assert route.action == "clarify"
    assert "nhiều hướng" in route.clarification


def test_chat_router_can_execute_short_continuation_from_public_context():
    from runtime.agent_harness.chat_router import classify_agent_chat_route

    route = classify_agent_chat_route(
        "làm đi",
        previous_assistant_text=(
            "Tôi sẽ sửa capability routing trong executive_cortex.py, tận dụng CapabilityDiscovery rồi chạy test."
        ),
    )
    assert route.action == "execute"
    assert "Ngữ cảnh công khai" in route.goal


def test_runtime_coordinator_routes_concrete_chat_into_async_harness():
    from runtime.coordinator import RuntimeCoordinator

    calls = []

    class _Harness:
        def invoke(self, goal, thread_id="", task_id="", clarified_goal=""):
            calls.append((goal, thread_id, task_id, clarified_goal))
            return {"status": "done"}

    coordinator = object.__new__(RuntimeCoordinator)
    coordinator.agent_harness = _Harness()
    coordinator._agent_task_threads = {}
    coordinator._agent_last_started_task_id = ""
    coordinator.logger = None

    route = coordinator.route_agent_user_turn(
        "sửa capability_route trong executive_cortex.py rồi chạy test",
        turn_id="session_turn:test",
    )
    assert route["action"] == "execute"
    assert route["task_id"].startswith("task_")
    thread = coordinator._agent_task_threads.get(route["task_id"])
    if thread is not None:
        thread.join(timeout=2)
    assert calls
    assert calls[0][1] == "session_turn:test"


def test_native_adapter_keeps_dynamic_project_tools_mounted_before_workspace():
    class FakeExecutor:
        def execute_capability(self, capability_id, arguments):
            raise AssertionError("not executed")

    adapter = NativeCapabilityToolAdapter(FakeExecutor())
    specs = adapter.tool_specs()
    # project tools may be transiently unavailable until workspace activation,
    # but their schemas must remain mountable for progressive skill disclosure.
    assert "project_read_file" in specs
    assert "project_run_tests" in specs


def test_supervisor_policy_advises_when_patch_happens_before_inspection(tmp_path):
    from runtime.coordinator import RuntimeCoordinator
    from runtime.agent_harness.task_store import AgentTaskStore
    from runtime.agent_harness.supervisor_bridge import AgentSupervisorBridge

    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task_id = store.create_task("fix router")["task_id"]
    store.append_event(task_id, "task_started", actor="system", summary="start")

    class _Events:
        def emit(self, task_id, event_type, **kwargs):
            return store.append_event(task_id, event_type, **kwargs)

    coordinator = object.__new__(RuntimeCoordinator)
    coordinator.agent_task_store = store
    coordinator.agent_supervisor = AgentSupervisorBridge(store=store, event_bus=_Events())
    coordinator._agent_supervisor_marks = {}

    event = store.append_event(
        task_id,
        "tool_started",
        actor="tool",
        summary="patch",
        data={"tool": "project_apply_patch"},
    )
    event["task_id"] = task_id
    coordinator._supervise_agent_event(event)

    snapshot = store.snapshot(selected_task_id=task_id)
    types = [item["type"] for item in snapshot["tasks"][0]["events"]]
    assert "supervisor_advisory" in types
    controls = store.consume_controls(task_id)
    assert controls and controls[-1]["action"] == "directive"
