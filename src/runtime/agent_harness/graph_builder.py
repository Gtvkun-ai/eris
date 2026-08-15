"""LangGraph Builder for the Unified Agent Harness.

The graph owns execution state and checkpoints.  Agent Console events are a
separate projection so the Godot frontend can observe/control a task without
scraping model reasoning or stdout.
"""
from __future__ import annotations

import uuid
import threading
from contextlib import nullcontext
from typing import Any, Callable, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .graph_state import AgentState
from .permission_gate import PermissionGate, Permission
from .capability_discovery import CapabilityDiscovery
from .skill_loader import SkillLoader
from .task_store import AgentTaskStore
from .event_bus import AgentEventBus


class AgentHarness:
    """Kiro-like execution harness backed by LangGraph checkpoints.

    `tool_registry` is intentionally generic.  Eris native capabilities, Gemini
    adapters, MCP tools or test helpers can all be mounted here without teaching
    the Subject Core their schemas.
    """

    def __init__(
        self,
        llm,
        powers_root: str,
        *,
        tool_registry: dict[str, Callable[..., Any]] | None = None,
        tool_specs: dict[str, dict[str, Any]] | None = None,
        task_store: AgentTaskStore | None = None,
        event_bus: AgentEventBus | None = None,
        executor_name: str = "gemini",
        model_name: str = "",
        workspace_scope: Callable[[str], Any] | None = None,
        logger: Any = None,
    ):
        self.llm = llm
        self.discovery = CapabilityDiscovery(powers_root)
        self.skill_loader = SkillLoader(self.discovery)
        self.permission_gate = PermissionGate()
        self.tool_registry = dict(tool_registry or {})
        self.tool_specs = dict(tool_specs or {})
        self.task_store = task_store or AgentTaskStore()
        self.event_bus = event_bus or AgentEventBus(self.task_store, logger=logger)
        self.executor_name = str(executor_name or "gemini")
        self.model_name = str(model_name or "")
        self.workspace_scope = workspace_scope
        # ProjectOperations reads the active WorkspaceManager record. Serialize only
        # the tiny activate+tool critical section so concurrent Gemini tasks may
        # reason in parallel without ever running a tool against the wrong repo.
        self._workspace_tool_lock = threading.RLock()
        self.logger = logger
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    def _consume_controls(self, state: AgentState) -> tuple[dict[str, Any], list[HumanMessage]]:
        task_id = str(state.get("task_id", "") or "")
        if not task_id:
            return {}, []
        controls = self.task_store.consume_controls(task_id)
        if not controls:
            return {}, []

        patch: dict[str, Any] = {}
        directive_messages: list[HumanMessage] = []
        for control in controls:
            action = str(control.get("action", "") or "").lower()
            if action == "directive":
                text = str(control.get("text", "") or "").strip()
                if text:
                    directive_messages.append(HumanMessage(content=(
                        "[RUNTIME DIRECTIVE FROM USER/ERIS SUPERVISOR]\n" + text
                    )))
                    self.event_bus.emit(
                        task_id,
                        "directive_consumed",
                        actor="executor",
                        summary="Executor đã nhận chỉ thị mới và sẽ replan từ trạng thái hiện tại.",
                        importance=0.82,
                    )
            elif action == "pause":
                patch["status"] = "paused"
                self.event_bus.emit(task_id, "task_paused", actor="system", summary="Task đã tạm dừng ở node boundary.")
            elif action == "resume":
                patch["status"] = "running"
                self.event_bus.emit(task_id, "task_resumed", actor="system", summary="Task được phép tiếp tục.")
            elif action == "stop":
                patch["status"] = "stopped"
                self.event_bus.emit(task_id, "task_stopped", actor="system", summary="Task đã nhận lệnh dừng.", importance=0.95)
            elif action == "rollback":
                checkpoint_id = str(control.get("checkpoint_id", "") or "")
                patch["rollback_requested"] = checkpoint_id or "latest"
                # Việc restore checkpoint phải chạy từ control plane ngoài node đang execute.
                # Đánh dấu rõ thay vì giả vờ đã rollback trong lúc graph còn ở giữa super-step.
                self.event_bus.emit(
                    task_id,
                    "rollback_queued",
                    actor="system",
                    summary=(f"Rollback đã xếp hàng tới checkpoint {checkpoint_id}." if checkpoint_id else "Rollback đã xếp hàng tới checkpoint gần nhất."),
                    importance=0.95,
                    data={"checkpoint_id": checkpoint_id},
                )
        return patch, directive_messages

    def _agent_node(self, state: AgentState) -> dict:
        """Core reasoning step.  Emits summaries, never private chain-of-thought."""
        task_id = str(state.get("task_id", "") or "")
        control_patch, directive_messages = self._consume_controls(state)
        status = str(control_patch.get("status", state.get("status", "running")) or "running")
        if status in {"paused", "stopped"}:
            return control_patch

        messages = list(state.get("messages", []) or [])
        if directive_messages:
            messages.extend(directive_messages)
        injected = state.get("injected_context", "")
        task_mode = str(state.get("task_mode", "execute") or "execute").strip().lower()
        step = int(state.get("step_count", 0) or 0) + 1

        if task_id:
            self.task_store.update_task(task_id, status="running", current_step=step)
            self.event_bus.emit(
                task_id,
                "agent_status",
                actor="executor",
                summary="Executor đang quyết định bước tiếp theo.",
                step=step,
                importance=0.34,
            )

        mode_rule = (
            "INSPECT-ONLY MODE: investigate and report evidence. Do not modify files, run write/control tools, or claim changes were made.\n"
            if task_mode == "inspect"
            else "EXECUTION MODE: you may use disclosed tools to inspect, modify, test, and verify within permission policy.\n"
        )
        sys_msg = SystemMessage(content=(
            "You are the execution specialist inside Eris' unified agent harness.\n"
            "Do not roleplay Eris' social persona. Work on the task, use available tools, "
            "verify results, and expose concise action summaries rather than private reasoning.\n"
            + mode_rule +
            f"Current Goal: {state.get('goal', '')}\n"
            f"Locked Workspace: {state.get('workspace_path', '') or '(none)'}\n"
            f"Active Skills: {', '.join(state.get('active_skills', []) or [])}\n"
            f"\n--- INJECTED SKILL CONTEXT ---\n{injected}\n--- END SKILL CONTEXT ---\n"
        ))

        response = None
        disclosed_tools = self._disclosed_tool_specs(state.get("active_skills", []) or [], task_mode=task_mode)
        invoke_with_tools = getattr(self.llm, "invoke_with_tools", None)
        if callable(invoke_with_tools):
            response = invoke_with_tools(
                [sys_msg] + messages,
                tools=disclosed_tools,
                goal=str(state.get("goal", "") or ""),
                active_skills=list(state.get("active_skills", []) or []),
                workspace=str(state.get("workspace_path", "") or "") or None,
            )
        else:
            invoke = getattr(self.llm, "invoke", None)
            if callable(invoke):
                response = invoke([sys_msg] + messages)

        patch: dict[str, Any] = {"step_count": step, **control_patch}
        if directive_messages:
            patch["messages"] = directive_messages
        if response is not None:
            patch.setdefault("messages", [])
            patch["messages"] = list(patch["messages"]) + [response]
            tool_calls = list(getattr(response, "tool_calls", []) or [])
            if task_id:
                if tool_calls:
                    names = [str(call.get("name", "tool")) for call in tool_calls if isinstance(call, dict)]
                    self.event_bus.emit(
                        task_id,
                        "agent_plan",
                        actor="executor",
                        summary="Bước kế tiếp: " + ", ".join(names[:6]),
                        step=step,
                        importance=0.56,
                        data={"tools": names[:12]},
                    )
                else:
                    final_text = str(getattr(response, "content", "") or "").strip()
                    self.event_bus.emit(
                        task_id,
                        "agent_summary",
                        actor="executor",
                        summary=(final_text[:1200] if final_text else "Executor đã hoàn tất lượt suy luận hiện tại mà không yêu cầu tool thêm."),
                        step=step,
                        importance=0.62 if final_text else 0.46,
                    )
        return patch

    def _disclosed_tool_specs(
        self,
        active_skills: list[str] | tuple[str, ...],
        *,
        task_mode: str = "execute",
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = [
            {
                "name": "search_capabilities",
                "description": "Search Eris Powers/Skills by the capability needed. Returns lightweight descriptions only.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "effect": "inspect",
                "risk_level": "low",
            },
            {
                "name": "activate_skill",
                "description": "Activate one discovered skill and reveal its instructions plus exact tool schemas.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"skill_name": {"type": "string"}},
                    "required": ["skill_name"],
                },
                "effect": "inspect",
                "risk_level": "low",
            },
        ]
        inspect_only = str(task_mode or "execute").strip().lower() == "inspect"
        for name in self.skill_loader.tools_for_skills(list(active_skills)):
            spec = self.tool_specs.get(name)
            if not isinstance(spec, dict):
                continue
            if inspect_only and str(spec.get("effect", "") or "").lower() not in {"observe", "inspect", "read"}:
                continue
            specs.append(dict(spec))
        return specs

    def _tool_spec(self, name: str, active_skills: list[str] | tuple[str, ...]) -> dict[str, Any]:
        if name == "search_capabilities":
            return {"name": name, "effect": "inspect", "risk_level": "low"}
        if name == "activate_skill":
            return {"name": name, "effect": "inspect", "risk_level": "low"}
        spec = self.tool_specs.get(name)
        return dict(spec) if isinstance(spec, dict) else {}

    def _invoke_tool(self, name: str, args: dict[str, Any]) -> Any:
        if name == "search_capabilities":
            return self.discovery.search(str(args.get("query", "") or ""))
        if name == "activate_skill":
            return self.skill_loader.activate_skill(str(args.get("skill_name", "") or ""))
        tool = self.tool_registry.get(name)
        if tool is None:
            raise KeyError(f"unknown_tool:{name}")
        return tool(**args)

    def _tool_execution_node(self, state: AgentState) -> dict:
        """Execute LLM tool calls with permission checks and typed UI events."""
        task_id = str(state.get("task_id", "") or "")
        control_patch, directive_messages = self._consume_controls(state)
        status = str(control_patch.get("status", state.get("status", "running")) or "running")
        if status in {"paused", "stopped"}:
            return {**control_patch, "messages": directive_messages} if directive_messages else control_patch

        messages = list(state.get("messages", []) or [])
        if not messages:
            return control_patch
        last_message = messages[-1]
        tool_calls = list(getattr(last_message, "tool_calls", []) or [])
        if not tool_calls:
            return control_patch

        out_messages: list[ToolMessage | HumanMessage] = list(directive_messages)
        active_skills = list(state.get("active_skills", []) or [])
        active_tools = self.skill_loader.tools_for_skills(active_skills)
        injected_context = str(state.get("injected_context", "") or "")
        step = int(state.get("step_count", 0) or 0)

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name", "") or "")
            call_id = str(call.get("id", "") or f"tool_{uuid.uuid4().hex[:10]}")
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            permission = self.permission_gate.check_permission(name, args, tool_spec=self._tool_spec(name, state.get("active_skills", []) or []))

            if task_id:
                self.event_bus.emit(
                    task_id,
                    "tool_started",
                    actor="tool",
                    summary=f"{name} đang chạy.",
                    step=step,
                    importance=0.42,
                    data={"tool": name, "args": _safe_tool_args(args)},
                )

            if permission == Permission.DENY:
                result = f"Denied by PermissionGate: {name}"
                out_messages.append(ToolMessage(content=result, tool_call_id=call_id))
                if task_id:
                    self.event_bus.emit(task_id, "tool_failed", actor="tool", summary=result, step=step, importance=0.94, data={"tool": name})
                continue
            if permission == Permission.ASK:
                result = f"Permission required before executing: {name}"
                out_messages.append(ToolMessage(content=result, tool_call_id=call_id))
                control_patch["status"] = "waiting_permission"
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "permission_requested",
                        actor="system",
                        summary=f"Cần quyền trước khi chạy {name}.",
                        step=step,
                        importance=0.96,
                        data={"tool": name, "args": _safe_tool_args(args)},
                    )
                continue

            try:
                workspace_ref = str(state.get("workspace_id", "") or state.get("workspace_path", "") or "").strip()
                # A running task owns its workspace for its lifetime. Workspace list
                # is harmless, but switch/join/leave from inside the executor would
                # invalidate every later observation and is therefore refused.
                if workspace_ref and name in {"workspace_join", "workspace_switch", "workspace_leave"}:
                    raise RuntimeError("task_workspace_locked: create/select workspace from Agent Console before starting the task")
                scope = self.workspace_scope(workspace_ref) if workspace_ref and callable(self.workspace_scope) else nullcontext()
                with self._workspace_tool_lock, scope:
                    result = self._invoke_tool(name, args)
                text = _tool_result_text(result)
                out_messages.append(ToolMessage(content=text, tool_call_id=call_id))
                if name == "search_capabilities" and task_id:
                    self.event_bus.emit(
                        task_id,
                        "skill_search",
                        actor="executor",
                        summary=f"Đã tìm skill cho: {str(args.get('query', '') or '')[:180]}",
                        detail=text,
                        step=step,
                        importance=0.58,
                    )
                if name == "activate_skill":
                    skill_name = str(args.get("skill_name", "") or "").strip()
                    if skill_name and not text.startswith("Error:"):
                        if skill_name not in active_skills:
                            active_skills.append(skill_name)
                        active_tools = self.skill_loader.tools_for_skills(active_skills)
                        injected_context = (injected_context + "\n\n" + text).strip()
                        if task_id:
                            self.event_bus.emit(
                                task_id,
                                "skill_activated",
                                actor="executor",
                                summary=f"Đã kích hoạt skill {skill_name}.",
                                step=step,
                                data={"skill": skill_name},
                            )
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "tool_result",
                        actor="tool",
                        summary=f"{name} hoàn tất.",
                        detail=text,
                        step=step,
                        importance=0.48,
                        data={"tool": name},
                    )
                    self._project_tool_result_events(task_id, name, result, step=step)
            except Exception as exc:
                text = f"{type(exc).__name__}: {exc}"
                out_messages.append(ToolMessage(content=text, tool_call_id=call_id))
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "tool_failed",
                        actor="tool",
                        summary=f"{name} thất bại: {text[:240]}",
                        step=step,
                        importance=0.88,
                        data={"tool": name},
                    )

        patch: dict[str, Any] = {
            "messages": out_messages,
            "active_skills": active_skills,
            "active_tools": active_tools,
            "injected_context": injected_context,
            **control_patch,
        }
        return patch

    def _project_tool_result_events(self, task_id: str, name: str, result: Any, *, step: int) -> None:
        """Project useful tool metadata into typed console events.

        The timeline should show semantic facts (files changed, tests passed)
        instead of forcing the Godot UI to parse arbitrary JSON/stdout.
        """
        if not task_id or not isinstance(result, dict):
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        success = bool(result.get("success", False))

        if name == "project_apply_patch":
            touched = data.get("touched_files") if isinstance(data.get("touched_files"), list) else []
            for path in touched[:80]:
                rel = str(path or "").strip()
                if rel:
                    self.event_bus.emit(
                        task_id,
                        "file_changed",
                        actor="tool",
                        summary=f"Đã thay đổi {rel}",
                        step=step,
                        importance=0.62,
                        data={"path": rel, "tool": name},
                    )

        if name == "project_run_tests":
            output = str(data.get("output", "") or "")
            passed_count, failed_count = _parse_test_counts(output, success=success)
            self.event_bus.emit(
                task_id,
                "test_result",
                actor="tool",
                summary=("Test đạt." if success else "Test chưa đạt."),
                detail=output[-1800:],
                step=step,
                importance=0.78 if success else 0.92,
                data={
                    "passed": passed_count,
                    "failed": failed_count,
                    "summary": ("pass" if success else "fail") + f" · exit={data.get('exit_code', '')}",
                    "exit_code": data.get("exit_code"),
                },
            )

        if name == "project_git_diff":
            diff = str(data.get("diff", "") or "")
            if diff.strip():
                self.event_bus.emit(
                    task_id,
                    "diff_observed",
                    actor="tool",
                    summary=f"Đã kiểm tra git diff ({len(diff)} ký tự).",
                    step=step,
                    importance=0.55,
                    data={"chars": len(diff)},
                )

    def _should_continue(self, state: AgentState) -> Literal["tools", "__end__"]:
        if str(state.get("status", "running") or "running") in {"paused", "stopped", "waiting_permission", "waiting_user"}:
            return "__end__"
        messages = state.get("messages", []) or []
        if not messages:
            return "__end__"
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "__end__"

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tool_execution_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges("agent", self._should_continue, {"tools": "tools", "__end__": END})
        workflow.add_edge("tools", "agent")
        return workflow.compile(checkpointer=self.checkpointer)

    def invoke(
        self,
        goal: str,
        thread_id: str = "default_thread",
        *,
        task_id: str = "",
        clarified_goal: str = "",
        task_mode: str = "execute",
        source: str = "eris_chat",
        workspace_id: str = "",
        workspace_path: str = "",
        workspace_name: str = "",
    ):
        """Start one task and project its lifecycle to Agent Console."""
        normalized_mode = "inspect" if str(task_mode or "execute").strip().lower() == "inspect" else "execute"
        normalized_source = str(source or "eris_chat").strip() or "eris_chat"
        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_workspace_path = str(workspace_path or "").strip()
        normalized_workspace_name = str(workspace_name or "").strip()
        task = self.task_store.create_task(
            clarified_goal or goal,
            task_id=task_id,
            executor=self.executor_name,
            model=self.model_name,
            thread_id=thread_id,
            metadata={
                "original_goal": goal,
                "source": normalized_source,
                "task_mode": normalized_mode,
                "workspace_id": normalized_workspace_id,
                "workspace_path": normalized_workspace_path,
                "workspace_name": normalized_workspace_name,
            },
        )
        task_id = str(task.get("task_id", ""))
        existing_metadata = dict(task.get("metadata", {}) or {})
        existing_metadata.update({
            "original_goal": goal,
            "source": normalized_source,
            "task_mode": normalized_mode,
            "workspace_id": normalized_workspace_id,
            "workspace_path": normalized_workspace_path,
            "workspace_name": normalized_workspace_name,
        })
        self.task_store.update_task(
            task_id,
            clarified_goal=clarified_goal,
            status="running",
            metadata=existing_metadata,
        )
        self.event_bus.emit(
            task_id,
            "task_started",
            actor="system",
            summary=clarified_goal or goal,
            importance=0.90,
            data={
                "executor": self.executor_name,
                "model": self.model_name,
                "source": normalized_source,
                "task_mode": normalized_mode,
                "workspace_id": normalized_workspace_id,
                "workspace_path": normalized_workspace_path,
                "workspace_name": normalized_workspace_name,
            },
        )

        config = {"configurable": {"thread_id": thread_id}}
        initial_state: AgentState = {
            "goal": clarified_goal or goal,
            "task_id": task_id,
            "thread_id": thread_id,
            "executor": self.executor_name,
            "model": self.model_name,
            "task_mode": normalized_mode,
            "source": normalized_source,
            "workspace_id": normalized_workspace_id,
            "workspace_path": normalized_workspace_path,
            "workspace_name": normalized_workspace_name,
            "status": "running",
            "messages": [HumanMessage(content=clarified_goal or goal)],
            "active_skills": [],
            "active_tools": [],
            "injected_context": "",
            "pending_directives": [],
            "rollback_requested": "",
            "step_count": 0,
        }
        try:
            result = self.graph.invoke(initial_state, config)
            final_status = str((result or {}).get("status", "running") or "running") if isinstance(result, dict) else "running"
            checkpoint_id = self._current_checkpoint_id(config)
            if checkpoint_id:
                self.event_bus.emit(
                    task_id,
                    "checkpoint_created",
                    actor="system",
                    summary=f"Đã lưu LangGraph checkpoint {checkpoint_id}.",
                    importance=0.52,
                    data={"checkpoint_id": checkpoint_id},
                )
            if final_status == "running":
                final_text = _final_result_text(result)
                self.event_bus.emit(
                    task_id,
                    "task_completed",
                    actor="executor",
                    summary=(final_text[:520] if final_text else "Gemini đã hoàn tất task."),
                    detail=final_text,
                    importance=0.92,
                    data={"final": final_text[:8000]},
                )
            return result
        except Exception as exc:
            self.event_bus.emit(
                task_id,
                "task_failed",
                actor="system",
                summary=f"Agent loop lỗi: {type(exc).__name__}: {exc}",
                importance=1.0,
            )
            raise

    def _current_checkpoint_id(self, config: dict[str, Any]) -> str:
        getter = getattr(self.graph, "get_state", None)
        if not callable(getter):
            return ""
        try:
            snapshot = getter(config)
            cfg = getattr(snapshot, "config", None)
            if isinstance(cfg, dict):
                configurable = cfg.get("configurable")
                if isinstance(configurable, dict):
                    return str(configurable.get("checkpoint_id", "") or "")
        except Exception:
            return ""
        return ""


def _parse_test_counts(output: str, *, success: bool) -> tuple[int, int]:
    """Best-effort counts for pytest/unittest style summaries."""
    import re
    text = str(output or "")[-5000:]
    passed = 0
    failed = 0
    for pattern, target in (
        (r"(?<![A-Za-z])(\d+)\s+passed", "passed"),
        (r"(?<![A-Za-z])(\d+)\s+failed", "failed"),
        (r"FAILED\s+\(", "failed_marker"),
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if target == "passed":
            passed = int(match.group(1))
        elif target == "failed":
            failed = int(match.group(1))
        elif failed == 0:
            failed = 1
    if success and passed == 0:
        passed = 1
    if not success and failed == 0:
        failed = 1
    return passed, failed


def _final_result_text(result: Any) -> str:
    """Extract the public final executor result without exposing chain-of-thought."""
    if not isinstance(result, dict):
        return ""
    messages = list(result.get("messages", []) or [])
    for message in reversed(messages):
        # Tool observations are evidence, not the executor's final public result.
        if message.__class__.__name__.lower().startswith("tool"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            text = content.strip()
            return text if len(text) <= 8000 else text[:7999].rstrip() + "…"
    return ""


def _safe_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    """Keep UI metadata useful without dumping secrets or giant payloads."""
    safe: dict[str, Any] = {}
    for key, value in list(args.items())[:24]:
        lowered = str(key).lower()
        if any(token in lowered for token in ("key", "token", "secret", "password", "credential")):
            safe[str(key)] = "[redacted]"
            continue
        text = str(value)
        safe[str(key)] = text if len(text) <= 320 else text[:319] + "…"
    return safe


def _tool_result_text(result: Any) -> str:
    if result is None:
        return "OK"
    if isinstance(result, (dict, list, tuple)):
        try:
            import json
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
    else:
        text = str(result)
    return text if len(text) <= 12000 else text[:11999].rstrip() + "…"
