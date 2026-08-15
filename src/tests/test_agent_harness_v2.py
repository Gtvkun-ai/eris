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


def test_permission_gate_autopilot_runs_routine_dev_without_asking():
    gate = PermissionGate()
    assert gate.unattended is True
    assert gate.check_permission("project_read_file", {"path": "src/a.py"}) == Permission.ALLOW
    assert gate.check_permission("project_apply_patch", {"patch": "x"}) == Permission.ALLOW
    assert gate.check_permission("project_run_tests", {"command": "pytest -q"}) == Permission.ALLOW
    assert gate.check_permission("project_run_command", {"command": "git status"}) == Permission.ALLOW
    assert gate.check_permission("project_run_command", {"command": "git commit -am x"}) == Permission.ALLOW
    assert gate.check_permission("project_run_command", {"command": "git checkout feature-x"}) == Permission.ALLOW
    assert gate.check_permission("launch_app", {"app": "code"}) == Permission.ALLOW
    assert gate.check_permission("open_url", {"url": "https://example.com"}) == Permission.ALLOW
    assert gate.check_permission("workspace_switch", {"project_id": "x"}) == Permission.ALLOW


def test_permission_gate_autopilot_denies_protected_boundary_instead_of_prompting():
    gate = PermissionGate()
    assert gate.check_permission("project_run_command", {"command": "git push origin main"}) == Permission.DENY
    assert gate.check_permission("project_run_command", {"command": "git reset --hard HEAD~1"}) == Permission.DENY
    assert gate.check_permission("project_run_command", {"command": "git clean -fd"}) == Permission.DENY
    assert gate.check_permission("project_run_command", {"command": "npm publish"}) == Permission.DENY
    assert gate.check_permission("future_untyped_danger", {}) == Permission.DENY
    assert gate.check_permission(
        "future_read_tool", {}, tool_spec={"effect": "read", "risk_level": "low"}
    ) == Permission.ALLOW


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


def test_capability_self_model_distinguishes_instant_long_and_ambiguous():
    from runtime.agent_harness.capability_self_model import CapabilitySelfModel

    class _Discovery:
        capabilities = [
            {"name": "coding-debug", "description": "inspect debug test code", "keywords": ["debug", "code"]},
            {"name": "coding-modification", "description": "modify patch code", "keywords": ["patch", "refactor"]},
        ]

    class _Harness:
        discovery = _Discovery()

    model = CapabilitySelfModel(harness=_Harness(), harness_ready=True)

    instant = model.assess("em biết tôi đang nghe nhạc gì không")
    assert instant.lane == "instant"
    assert "get_now_playing" in instant.matched_capabilities

    long_task = model.assess("debug capability_route trong executive_cortex.py rồi sửa và chạy test")
    assert long_task.lane == "long_execution"
    assert long_task.executor == "gemini/langgraph"
    assert long_task.can_modify is True

    ambiguous = model.assess("làm agent ngon hơn đi")
    assert ambiguous.lane == "clarify"
    assert "Chốt nhánh" in ambiguous.clarification


def test_chat_router_can_launch_inspect_only_consult_from_normal_chat():
    from runtime.agent_harness.capability_self_model import CapabilitySelfModel
    from runtime.agent_harness.chat_router import classify_agent_chat_route

    class _Discovery:
        capabilities = [
            {"name": "coding-inspection", "description": "inspect repository code", "keywords": ["code", "routing"]},
        ]

    class _Harness:
        discovery = _Discovery()

    route = classify_agent_chat_route(
        "soi kỹ xem routing trong executive_cortex.py có gì cấn không",
        self_model=CapabilitySelfModel(harness=_Harness(), harness_ready=True),
    )
    assert route.action == "consult"
    assert "INSPECT-ONLY" in route.goal


def test_inspect_mode_discloses_no_write_or_control_tools():
    import pytest
    pytest.importorskip("langchain_core")
    pytest.importorskip("langgraph")
    from runtime.agent_harness.graph_builder import AgentHarness

    harness = object.__new__(AgentHarness)

    class _Loader:
        def tools_for_skills(self, _skills):
            return ["project_read_file", "project_apply_patch", "project_run_tests"]

    harness.skill_loader = _Loader()
    harness.tool_specs = {
        "project_read_file": {"name": "project_read_file", "effect": "read", "input_schema": {}},
        "project_apply_patch": {"name": "project_apply_patch", "effect": "write", "input_schema": {}},
        "project_run_tests": {"name": "project_run_tests", "effect": "control", "input_schema": {}},
    }
    specs = harness._disclosed_tool_specs(["coding-inspection"], task_mode="inspect")
    names = {item["name"] for item in specs}
    assert "search_capabilities" in names
    assert "activate_skill" in names
    assert "project_read_file" in names
    assert "project_apply_patch" not in names
    assert "project_run_tests" not in names


def test_autopilot_interactive_profile_can_still_be_enabled_for_debugging():
    gate = PermissionGate(mode="interactive")
    assert gate.unattended is False
    # Unknown future tool remains explicitly gated in interactive debug mode.
    assert gate.check_permission("future_untyped_tool", {}) == Permission.ASK


def test_terminal_agent_event_wakes_eris_frontstage(tmp_path):
    from runtime.coordinator import RuntimeCoordinator
    from runtime.agent_harness.task_store import AgentTaskStore
    from runtime.agent_harness.supervisor_bridge import AgentSupervisorBridge

    store = AgentTaskStore(tmp_path / "agent_tasks.json")
    task_id = store.create_task("fix routing")['task_id']
    store.update_task(task_id, clarified_goal="fix routing")

    class _Events:
        def emit(self, task_id, event_type, **kwargs):
            return store.append_event(task_id, event_type, **kwargs)

    coordinator = object.__new__(RuntimeCoordinator)
    coordinator.agent_task_store = store
    coordinator.agent_supervisor = AgentSupervisorBridge(store=store, event_bus=_Events())
    coordinator._agent_supervisor_marks = {}
    coordinator.logger = None
    history = []
    wakes = []
    coordinator._append_chat_history = lambda role, content, **kwargs: history.append((role, content))
    coordinator._wake_autonomous_loop = lambda reason="": wakes.append(reason)

    event = store.append_event(
        task_id,
        "task_completed",
        actor="executor",
        summary="done",
        detail="Fixed routing and tests pass.",
        data={"final": "Fixed routing and tests pass."},
    )
    event["task_id"] = task_id
    coordinator._supervise_agent_event(event)

    assert history and history[-1][0] == "system"
    assert "BACKSTAGE AGENT COMPLETED" in history[-1][1]
    assert "Fixed routing" in history[-1][1]
    assert wakes and wakes[-1].startswith("agent_task_completed:")
