"""V13 Root tool contract: discovery, schema, live recheck, sandbox delegation."""
from __future__ import annotations

from types import SimpleNamespace

from actions.contracts import ActionExecutionResult
from runtime.conversation.agent import ROOT_STEP_SCHEMA, RuntimeModelRootAgent
from runtime.conversation.context import RootCapabilityRegistry
from runtime.conversation.contracts import ConversationEvent, NextConversationMove
from runtime.tooling import ToolGateway, DomainTool


class FakeExecutor:
    def __init__(self, observed=True):
        self.calls = []
        self.observed = observed

    def execute_capability(self, tool_id, args):
        self.calls.append((tool_id, args))
        return ActionExecutionResult(
            action_name=tool_id, action_input=str(args), success=True,
            message="Done", observed=self.observed,
            status="observed" if self.observed else "dispatched",
        )


class Live:
    def __init__(self, **kwargs):
        self.flags = kwargs

    def __call__(self):
        return {"statuses": {name: {"available": yes} for name, yes in self.flags.items()}}


class Router:
    executive_client = object()

    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []

    def invoke_structured_worker(self, _client, **kwargs):
        self.requests.append(kwargs)
        return self.steps.pop(0)


def event():
    return ConversationEvent(event_id="v13:1", session_id="s", kind="user_turn", text="What time is it?")


def test_model_protocol_has_no_legacy_capability_step():
    kinds = {k for spec in ROOT_STEP_SCHEMA["oneOf"] for k in spec["properties"]["kind"]["enum"]}
    assert "use_capability" not in kinds
    assert {"tool_discover", "tool_describe", "tool_call"} <= kinds


def test_discovery_only_offers_live_callable_tools():
    executor = FakeExecutor()
    gateway = ToolGateway(executor, status_provider=Live(get_local_time=True, project_execute_task=True,
                                                       launch_app=False, semantic_screen_vision=True))
    result = gateway.discover()
    ids = {tool["id"] for tool in result["tools"]}
    assert ids == {"get_local_time"}
    assert gateway.describe("launch_app")["status"] == "unavailable"
    assert gateway.describe("project_execute_task")["status"] == "unavailable"
    assert gateway.describe("semantic_screen_vision")["status"] == "unavailable"
    assert not executor.calls


def test_exact_schema_validation_blocks_execution():
    executor = FakeExecutor()
    gateway = ToolGateway(executor, status_provider=Live(launch_app=True))
    schema = gateway.describe("launch_app")["input_schema"]
    assert schema["required"] == ["command"]
    assert gateway.call("launch_app", {"unknown": "oops"})["status"] == "invalid"
    assert gateway.call("launch_app", {"command": 42})["status"] == "invalid"
    assert executor.calls == []
    result = gateway.call("launch_app", {"command": "notepad"})
    assert result["status"] == "completed"
    assert executor.calls == [("launch_app", {"command": "notepad"})]


def test_recheck_availability_before_call_and_fail_closed_without_snapshot():
    executor = FakeExecutor()
    live = Live(open_url=True)
    gateway = ToolGateway(executor, status_provider=live)
    assert gateway.describe("open_url")["status"] == "ok"
    live.flags["open_url"] = False
    assert gateway.call("open_url", {"url": "https://example.org"})["status"] == "unavailable"
    assert not executor.calls
    empty = ToolGateway(executor, status_provider=lambda: {})
    assert empty.discover()["tools"] == []


def test_unobserved_action_is_dispatched_not_completed():
    gateway = ToolGateway(FakeExecutor(observed=False), status_provider=Live(open_url=True))
    result = gateway.call("open_url", {"url": "https://example.org"})
    assert result["status"] == "dispatched"
    assert not result["observed"]


def test_domain_tool_is_discoverable_and_strictly_typed():
    called = []
    gateway = ToolGateway(None, domain_tools=(DomainTool(
        id="lesson.advise", group="learning", description="Review an answer",
        schema={"type": "object", "properties": {"question": {"type": "string"}},
                "required": ["question"], "additionalProperties": False},
        execute=lambda args, ev, h: called.append((args, ev)) or {"status": "completed", "data": {"score": 2}},
        available=lambda: True,
    ),), status_provider=lambda: {})
    assert gateway.discover(query="lesson")["tools"][0]["id"] == "lesson.advise"
    assert gateway.call("lesson.advise", {"question": 7})["status"] == "invalid"
    assert gateway.call("lesson.advise", {"question": "Why?"})["status"] == "completed"
    assert len(called) == 1


def test_root_e2e_discovers_describes_executes_and_records_real_receipt():
    executor = FakeExecutor()
    gateway = ToolGateway(executor, status_provider=Live(get_local_time=True))
    ledger = RootCapabilityRegistry({})
    steps = [
        {"kind": "tool_discover", "query": "thời gian"},
        {"kind": "tool_describe", "tool_id": "get_local_time"},
        {"kind": "tool_call", "tool_id": "get_local_time", "arguments": {}},
        {"kind": "move", "intent": "Báo giờ", "say": "Giờ thực tế dựa theo result", "delivery": "tự nhiên", "after": "wait_user"},
    ]
    router = Router(steps)
    result = RuntimeModelRootAgent(router).decide(
        event=event(), recent_history=(), note="",
        runtime_context={"__root_tool_gateway": gateway,
                         "__root_capabilities": ledger, "__conversation_run_id": "r1"},
    )
    assert isinstance(result, NextConversationMove)
    assert executor.calls == [("get_local_time", {})]
    receipts = ledger.result_receipts_for("v13:1", run_id="r1", generation=0)
    assert len(receipts) == 1
    assert receipts[0].name == "get_local_time"
    assert receipts[0].status == "completed"
    assert router.requests[0]["payload"]["tool_inventory"]["available_count"] == 1
    assert router.requests[-1]["payload"]["tool_results"][-1]["result"]["status"] == "completed"


def test_root_repeated_tool_call_dedup_and_no_second_execution():
    executor = FakeExecutor()
    gateway = ToolGateway(executor, status_provider=Live(get_local_time=True))
    router = Router([
        {"kind": "tool_call", "tool_id": "get_local_time", "arguments": {}},
        {"kind": "tool_call", "tool_id": "get_local_time", "arguments": {}},
        {"kind": "no_reply", "reason": "done"},
    ])
    RuntimeModelRootAgent(router).decide(event=event(), recent_history=(), note="",
        runtime_context={"__root_tool_gateway": gateway, "__root_capabilities": RootCapabilityRegistry({}),
                         "__conversation_run_id": "r2"})
    assert executor.calls == [("get_local_time", {})]


def test_real_action_executor_without_subject_sandbox_fails_closed():
    # This test uses the actual production executor, not a mock that might
    # accidentally execute a desktop command without subject authorization.
    from actions.executor import ActionExecutor
    gateway = ToolGateway(ActionExecutor(), status_provider=Live(launch_app=True))
    response = gateway.call("launch_app", {"command": "notepad"})
    assert response["status"] == "failed"
    assert response["success"] is False
    assert response["error_kind"] == "SubjectCoreUnavailable"


def test_large_executor_output_cannot_claim_completed_without_evidence():
    class Verbose(FakeExecutor):
        def execute_capability(self, tool_id, args):
            self.calls.append((tool_id, args))
            return ActionExecutionResult(action_name=tool_id, success=True,
                                         message="ok", data={"blob": "x" * 30000}, observed=True)
    gateway = ToolGateway(Verbose(), status_provider=Live(get_local_time=True))
    response = gateway.call("get_local_time", {})
    assert response["status"] == "truncated"
    assert "message" not in response
