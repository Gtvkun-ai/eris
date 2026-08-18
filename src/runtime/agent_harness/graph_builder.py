"""LangGraph Builder for the Unified Agent Harness.

The graph owns execution state and checkpoints.  Agent Console events are a
separate projection so the Godot frontend can observe/control a task without
scraping model reasoning or stdout.
"""
from __future__ import annotations

import json
import uuid
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt

from .graph_state import AgentState
from .permission_gate import PermissionGate, Permission
from .capability_discovery import CapabilityDiscovery
from .skill_loader import SkillLoader
from .task_store import AgentTaskStore
from .event_bus import AgentEventBus
from .workspace_checkpoint_store import WorkspaceCheckpointStore
from .checkpointing import DurableSqliteCheckpointer, default_langgraph_checkpoint_path


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
        checkpoint_path: str | None = None,
        checkpointer: Any = None,
        logger: Any = None,
    ):
        self.llm = llm
        self.discovery = CapabilityDiscovery(powers_root)
        self.skill_loader = SkillLoader(self.discovery)
        self.permission_gate = PermissionGate()
        self.tool_registry = dict(tool_registry or {})
        self.tool_specs = dict(tool_specs or {})
        self.task_store = task_store or AgentTaskStore()
        self.tool_specs.update(self._builtin_tool_specs())
        state_path = Path(getattr(self.task_store, "path", Path(".eris_state") / "agent_console" / "tasks.json"))
        self.workspace_checkpoints = WorkspaceCheckpointStore(state_path.parent / "workspace_checkpoints")
        self.event_bus = event_bus or AgentEventBus(self.task_store, logger=logger)
        self.executor_name = str(executor_name or "gemini")
        self.model_name = str(model_name or "")
        self.workspace_scope = workspace_scope
        # ProjectOperations reads the active WorkspaceManager record. Serialize only
        # the tiny activate+tool critical section so concurrent Gemini tasks may
        # reason in parallel without ever running a tool against the wrong repo.
        self._workspace_tool_lock = threading.RLock()
        self.logger = logger
        # Checkpoint graph phải sống qua restart; MemorySaver chỉ phù hợp test/demo.
        self._checkpoint_runtime = None
        if checkpointer is not None:
            self.checkpointer = checkpointer
            self.checkpoint_path = ""
        else:
            resolved_checkpoint = Path(checkpoint_path).expanduser().resolve() if checkpoint_path else default_langgraph_checkpoint_path(self.task_store)
            self._checkpoint_runtime = DurableSqliteCheckpointer(resolved_checkpoint)
            self.checkpointer = self._checkpoint_runtime.saver
            self.checkpoint_path = str(resolved_checkpoint)
        self.graph = self._build_graph()

    @staticmethod
    def _builtin_tool_specs() -> dict[str, dict[str, Any]]:
        return {
            "inspect_capability_catalog": {
                "name": "inspect_capability_catalog",
                "description": "Inspect Eris' live capability self-model with health, latency, risk, reversibility, executor and workspace requirements.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "include_unavailable": {"type": "boolean"},
                    },
                },
                "effect": "inspect",
                "risk_level": "low",
                "workspace_required": False,
                "estimated_time": "<1s",
                "reversible": True,
            },
            "list_task_checkpoints": {
                "name": "list_task_checkpoints",
                "description": "List atomic LangGraph + filesystem checkpoints for the current Agent task.",
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
                "effect": "inspect",
                "risk_level": "low",
                "workspace_required": False,
                "estimated_time": "<1s",
                "reversible": True,
            },
            "editor_open_file": {
                "name": "editor_open_file",
                "description": "Ask the connected VS Code client to open a workspace file and optionally reveal a line.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "line": {"type": "integer", "minimum": 1},
                        "column": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
                "effect": "control",
                "risk_level": "low",
                "workspace_required": True,
                "estimated_time": "<1s",
                "reversible": True,
            },
            "editor_focus_problems": {
                "name": "editor_focus_problems",
                "description": "Ask the connected VS Code client to focus the Problems panel.",
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
                "effect": "control",
                "risk_level": "low",
                "workspace_required": False,
                "estimated_time": "<1s",
                "reversible": True,
            },
        }

    def _executor_ready(self) -> bool:
        health = getattr(self.llm, "health", None)
        if not callable(health):
            return True
        try:
            ready, _reason = health()
            return bool(ready)
        except Exception:
            return False

    def _inspect_capability_catalog(self, args: dict[str, Any]) -> dict[str, Any]:
        from .capability_self_model import CapabilitySelfModel

        model = CapabilitySelfModel(harness=self, harness_ready=self._executor_ready())
        return model.catalog(
            str(args.get("query", "") or ""),
            include_unavailable=bool(args.get("include_unavailable", True)),
            limit=48,
        )

    def _list_task_checkpoints(self, task_id: str) -> dict[str, Any]:
        records = self.workspace_checkpoints.list(task_id, limit=48)
        return {
            "task_id": task_id,
            "count": len(records),
            "checkpoints": [
                {
                    "checkpoint_id": item.checkpoint_id,
                    "step": item.step,
                    "created_at": item.created_at,
                    "snapshot_mode": item.snapshot_mode,
                    "complete": item.complete,
                    "workspace_path": item.workspace_path,
                    "reason": item.reason,
                    "bytes_archived": item.bytes_archived,
                    "warnings": list(item.warnings),
                }
                for item in records
            ],
        }

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
            if action in {"directive", "choice"}:
                control_data = control.get("data") if isinstance(control.get("data"), dict) else {}
                fresh_ide_context = control_data.get("ide_context") if isinstance(control_data.get("ide_context"), dict) else {}
                if fresh_ide_context:
                    patch["ide_context"] = _compact_ide_context(fresh_ide_context)
                text = str(control.get("text", "") or "").strip()
                if text:
                    prefix = (
                        "[USER CHOICE FROM ERIS CONSOLE]\n"
                        if action == "choice"
                        else "[RUNTIME DIRECTIVE FROM USER/ERIS SUPERVISOR]\n"
                    )
                    directive_messages.append(HumanMessage(content=prefix + text))
                    self.event_bus.emit(
                        task_id,
                        "choice_consumed" if action == "choice" else "directive_consumed",
                        actor="executor",
                        summary=(
                            "Executor đã nhận lựa chọn của người dùng và sẽ tiếp tục từ quyết định đó."
                            if action == "choice"
                            else "Executor đã nhận chỉ thị mới và sẽ replan từ trạng thái hiện tại."
                        ),
                        importance=0.86 if action == "choice" else 0.82,
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
        if status in {"paused", "stopped"} or str(control_patch.get("rollback_requested", "") or "").strip():
            return control_patch

        messages = list(state.get("messages", []) or [])
        if directive_messages:
            messages.extend(directive_messages)
        injected = state.get("injected_context", "")
        ide_context = _compact_ide_context(state.get("ide_context"))
        ide_context_text = json.dumps(ide_context, ensure_ascii=False, separators=(",", ":")) if ide_context else "{}"
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
            "When the task genuinely needs a user decision, call ask_user_choice with 2-5 concise options instead of inventing a preference. "
            "Do not ask for confirmation for routine reversible work.\n"
            + mode_rule +
            f"Current Goal: {state.get('goal', '')}\n"
            f"Current Task ID: {task_id or '(none)'}\n"
            f"Locked Workspace: {state.get('workspace_path', '') or '(none)'}\n"
            f"Active Skills: {', '.join(state.get('active_skills', []) or [])}\n"
            f"IDE Context (structured, may be partial): {ide_context_text}\n"
            f"\n--- INJECTED SKILL CONTEXT ---\n{injected}\n--- END SKILL CONTEXT ---\n"
        ))

        response = None
        disclosed_tools = self._disclosed_tool_specs(
            state.get("active_skills", []) or [],
            task_mode=task_mode,
            ide_context=ide_context,
        )
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
        ide_context: dict[str, Any] | None = None,
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
            {
                "name": "ask_user_choice",
                "description": "Pause the current LangGraph task and ask the connected Eris client for a compact multiple-choice decision. Use only when user intent is genuinely required.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["label"],
                            },
                        },
                        "allow_other": {"type": "boolean"},
                    },
                    "required": ["question", "options"],
                },
                "effect": "inspect",
                "risk_level": "low",
            },
        ]
        client_caps = _ide_client_capabilities(ide_context)
        if "editor.openFile" in client_caps:
            specs.append(dict(self.tool_specs["editor_open_file"]))
        if "editor.focusProblems" in client_caps:
            specs.append(dict(self.tool_specs["editor_focus_problems"]))
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
        if name == "ask_user_choice":
            return {"name": name, "effect": "inspect", "risk_level": "low", "workspace_required": False}
        spec = self.tool_specs.get(name)
        return dict(spec) if isinstance(spec, dict) else {}

    def _invoke_tool(self, name: str, args: dict[str, Any], *, task_id: str = "") -> Any:
        if name == "search_capabilities":
            return self.discovery.search(str(args.get("query", "") or ""))
        if name == "activate_skill":
            return self.skill_loader.activate_skill(str(args.get("skill_name", "") or ""))
        if name == "inspect_capability_catalog":
            return self._inspect_capability_catalog(args)
        if name == "list_task_checkpoints":
            return self._list_task_checkpoints(task_id)
        if name == "editor_open_file":
            if not task_id:
                raise RuntimeError("editor_command_requires_task")
            payload = {
                "command": "editor.openFile",
                "path": str(args.get("path", "") or "").strip(),
                "line": max(1, int(args.get("line", 1) or 1)),
                "column": max(1, int(args.get("column", 1) or 1)),
            }
            self.event_bus.emit(
                task_id, "editor_command", actor="executor",
                summary=f"Mở file {payload['path']}", importance=0.52, data=payload,
            )
            return {"success": True, "status": "queued", "data": payload}
        if name == "editor_focus_problems":
            if not task_id:
                raise RuntimeError("editor_command_requires_task")
            payload = {"command": "editor.focusProblems"}
            self.event_bus.emit(
                task_id, "editor_command", actor="executor",
                summary="Mở Problems trong VS Code.", importance=0.44, data=payload,
            )
            return {"success": True, "status": "queued", "data": payload}
        tool = self.tool_registry.get(name)
        if tool is None:
            raise KeyError(f"unknown_tool:{name}")
        return tool(**args)

    def _should_snapshot_before_tool(self, name: str, spec: dict[str, Any]) -> bool:
        effect = str(spec.get("effect", "") or "").lower()
        return bool(name.startswith("project_") and effect in {"write", "control"})

    def _ensure_atomic_checkpoint(self, state: AgentState, *, tool_name: str, step: int) -> str:
        task_id = str(state.get("task_id", "") or "")
        thread_id = str(state.get("thread_id", "") or "")
        workspace_path = str(state.get("workspace_path", "") or "")
        if not task_id or not thread_id or not workspace_path:
            return ""
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_id = self._current_checkpoint_id(config)
        if not checkpoint_id:
            self.event_bus.emit(
                task_id,
                "checkpoint_degraded",
                actor="system",
                summary="Không lấy được LangGraph checkpoint trước side effect; filesystem snapshot không được quảng cáo là atomic.",
                step=step,
                importance=0.90,
                data={"tool": tool_name, "workspace_path": workspace_path},
            )
            return ""
        try:
            self.workspace_checkpoints.resolve(task_id=task_id, checkpoint_id=checkpoint_id)
            return checkpoint_id
        except (FileNotFoundError, KeyError):
            pass
        projection_fn = getattr(self.task_store, "execution_projection", None)
        projection = projection_fn(task_id) if callable(projection_fn) else {}
        record = self.workspace_checkpoints.capture(
            task_id=task_id,
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
            workspace_path=workspace_path,
            step=step,
            reason=f"before:{tool_name}",
            task_projection=projection,
        )
        self.event_bus.emit(
            task_id,
            "checkpoint_created",
            actor="system",
            summary=(
                f"Atomic checkpoint {checkpoint_id} đã lưu trước {tool_name}."
                if record.complete else
                f"Checkpoint {checkpoint_id} đã lưu trước {tool_name}, nhưng filesystem snapshot bị degraded."
            ),
            step=step,
            importance=0.72 if record.complete else 0.92,
            data={
                "checkpoint_id": checkpoint_id,
                "filesystem_snapshot": record.snapshot_mode,
                "complete": record.complete,
                "bytes_archived": record.bytes_archived,
                "warnings": list(record.warnings),
                "tool": tool_name,
            },
        )
        return checkpoint_id

    def _restore_atomic_checkpoint(
        self,
        *,
        task_id: str,
        checkpoint_id: str,
        thread_id: str,
        workspace_path: str,
    ):
        with self._workspace_tool_lock:
            record = self.workspace_checkpoints.restore(
                task_id=task_id,
                checkpoint_id=checkpoint_id or "latest",
                workspace_path=workspace_path,
            )
        projection = self.workspace_checkpoints.load_projection(record)
        restore_projection = getattr(self.task_store, "restore_execution_projection", None)
        if callable(restore_projection):
            restore_projection(task_id, projection, checkpoint_id=record.graph_checkpoint_id)
        self.event_bus.emit(
            task_id,
            "checkpoint_restored",
            actor="system",
            summary=f"Đã rollback graph + workspace về checkpoint {record.graph_checkpoint_id}.",
            importance=0.97,
            data={
                "checkpoint_id": record.graph_checkpoint_id,
                "filesystem_snapshot": record.snapshot_mode,
                "complete": record.complete,
                "workspace_path": record.workspace_path,
                "step": record.step,
            },
        )
        return record

    def restore_task_checkpoint(self, task_id: str, checkpoint_id: str = "latest"):
        """Restore a persisted task checkpoint outside a live worker.

        Running tasks consume rollback at a LangGraph node boundary so the graph
        can branch from the exact checkpoint. Terminal tasks have no worker left
        to consume controls, so the control plane may call this method directly.
        In that case filesystem + task projection are restored to the same stored
        graph checkpoint and the task is left stopped, never falsely resumable.
        """
        task = self.task_store.get_task(str(task_id or "").strip(), event_limit=0)
        if task is None:
            raise KeyError(f"unknown_agent_task:{task_id}")
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        workspace_path = str(metadata.get("workspace_path", "") or "").strip()
        thread_id = str(task.get("thread_id", "") or task_id).strip()
        if not workspace_path:
            raise RuntimeError("task_workspace_unavailable")
        record = self._restore_atomic_checkpoint(
            task_id=str(task_id),
            checkpoint_id=str(checkpoint_id or "latest"),
            thread_id=thread_id,
            workspace_path=workspace_path,
        )
        # There is no live graph worker to continue from this branch. Keep the
        # restored files/projection truthful and visibly terminal. A future
        # explicit restart/resume feature can branch from record.graph_checkpoint_id.
        self.task_store.update_task(
            str(task_id),
            status="stopped",
            finished_at=time.time(),
            checkpoint_id=record.graph_checkpoint_id,
        )
        self.event_bus.emit(
            str(task_id),
            "task_stopped",
            actor="system",
            summary=(
                f"Task đã rollback về checkpoint {record.graph_checkpoint_id}. "
                "Không có worker đang chạy nên task được giữ ở trạng thái stopped."
            ),
            importance=0.88,
            data={"checkpoint_id": record.graph_checkpoint_id, "reason": "terminal_rollback"},
        )
        return record

    def _tool_execution_node(self, state: AgentState) -> dict:
        """Execute LLM tool calls with permission checks and typed UI events."""
        task_id = str(state.get("task_id", "") or "")
        control_patch, directive_messages = self._consume_controls(state)
        status = str(control_patch.get("status", state.get("status", "running")) or "running")
        if status in {"paused", "stopped"} or str(control_patch.get("rollback_requested", "") or "").strip():
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

        # HUMAN-IN-THE-LOOP THẬT: ask_user_choice phải interrupt trước mọi
        # side effect trong node. LangGraph sẽ checkpoint rồi trả control về caller;
        # worker không ngồi polling. Khi resume, node chạy lại và interrupt() trả về
        # response đã được client gửi qua Command(resume=...).
        choice_call = next(
            (item for item in tool_calls if isinstance(item, dict) and str(item.get("name", "") or "") == "ask_user_choice"),
            None,
        )
        if isinstance(choice_call, dict):
            choice_resume_context: dict[str, Any] = {}
            call_id = str(choice_call.get("id", "") or f"tool_{uuid.uuid4().hex[:10]}")
            args = choice_call.get("args") if isinstance(choice_call.get("args"), dict) else {}
            question, options = _normalize_choice_request(args)
            if not question or len(options) < 2:
                text = "ask_user_choice requires a question and at least two valid options."
                out_messages.append(ToolMessage(content=text, tool_call_id=call_id))
                if task_id:
                    self.event_bus.emit(
                        task_id, "tool_failed", actor="tool", summary=text, step=step,
                        importance=0.86, data={"tool": "ask_user_choice"},
                    )
            else:
                resume_value = interrupt({
                    "type": "interrupt.request",
                    "reason": "user_choice",
                    "taskId": task_id,
                    "threadId": str(state.get("thread_id", "") or ""),
                    "toolCallId": call_id,
                    "question": question,
                    "options": options,
                    "allowOther": bool(args.get("allow_other", True)),
                    "step": step,
                })
                choice_resume_context = _resume_ide_context(resume_value)
                selected = _choice_resume_text(resume_value, options)
                out_messages.append(ToolMessage(
                    content=("User decision: " + selected) if selected else "User resumed without a textual choice.",
                    tool_call_id=call_id,
                ))
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "interrupt_resolved",
                        actor="user",
                        summary=selected or "Người dùng đã tiếp tục task.",
                        step=step,
                        importance=0.92,
                        data={"tool": "ask_user_choice", "tool_call_id": call_id},
                    )

            # Provider yêu cầu mỗi tool_call có một ToolMessage. Các call còn lại
            # được defer để model replan sau quyết định, tránh side effect chạy lại
            # khi node được LangGraph replay lúc resume.
            for pending in tool_calls:
                if not isinstance(pending, dict) or pending is choice_call:
                    continue
                pending_id = str(pending.get("id", "") or f"tool_{uuid.uuid4().hex[:10]}")
                pending_name = str(pending.get("name", "") or "tool")
                out_messages.append(ToolMessage(
                    content=f"Deferred {pending_name}: reissue this tool after incorporating the user decision.",
                    tool_call_id=pending_id,
                ))
            choice_patch: dict[str, Any] = {
                "messages": out_messages,
                "active_skills": active_skills,
                "active_tools": active_tools,
                "injected_context": injected_context,
                **control_patch,
            }
            if choice_resume_context:
                choice_patch["ide_context"] = choice_resume_context
            return choice_patch

        # Permission ASK cũng dùng interrupt thật. Nếu node có nhiều tool call,
        # chỉ call đầu tiên cần quyền được xử lý; các ASK còn lại bị defer để model
        # re-issue sau, tránh một resume vô tình cấp quyền cho cả cụm side effect.
        permission_call = None
        for candidate in tool_calls:
            if not isinstance(candidate, dict):
                continue
            candidate_name = str(candidate.get("name", "") or "")
            candidate_args = candidate.get("args") if isinstance(candidate.get("args"), dict) else {}
            if self.permission_gate.check_permission(
                candidate_name,
                candidate_args,
                tool_spec=self._tool_spec(candidate_name, state.get("active_skills", []) or []),
            ) == Permission.ASK:
                permission_call = candidate
                break

        approved_permission_call_id = ""
        denied_permission_call_id = ""
        permission_resume_context: dict[str, Any] = {}
        if isinstance(permission_call, dict):
            permission_call_id = str(permission_call.get("id", "") or f"tool_{uuid.uuid4().hex[:10]}")
            # Một số provider test không gắn id. Ghi id ổn định vào call để vòng
            # execute phía dưới không sinh một UUID khác sau khi interrupt resume.
            permission_call["id"] = permission_call_id
            permission_name = str(permission_call.get("name", "") or "tool")
            permission_args = permission_call.get("args") if isinstance(permission_call.get("args"), dict) else {}
            resume_value = interrupt({
                "type": "permission.request",
                "reason": "tool_permission",
                "taskId": task_id,
                "threadId": str(state.get("thread_id", "") or ""),
                "toolCallId": permission_call_id,
                "question": f"Cho phép Eris chạy {permission_name}?",
                "options": [
                    {"id": "allow_once", "label": "Cho phép một lần", "description": "Chỉ áp dụng cho tool call này."},
                    {"id": "deny", "label": "Không cho phép", "description": "Bỏ tool này và để agent chọn hướng khác."},
                ],
                "allowOther": False,
                "tool": permission_name,
                "args": _safe_tool_args(permission_args),
                "step": step,
            })
            permission_resume_context = _resume_ide_context(resume_value)
            if _permission_resume_allowed(resume_value):
                approved_permission_call_id = permission_call_id
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "interrupt_resolved",
                        actor="user",
                        summary=f"Người dùng cho phép chạy {permission_name} một lần.",
                        step=step,
                        importance=0.94,
                        data={"tool": permission_name, "tool_call_id": permission_call_id, "permission": "allow_once"},
                    )
            else:
                denied_permission_call_id = permission_call_id
                if task_id:
                    self.event_bus.emit(
                        task_id,
                        "interrupt_resolved",
                        actor="user",
                        summary=f"Người dùng từ chối quyền chạy {permission_name}.",
                        step=step,
                        importance=0.94,
                        data={"tool": permission_name, "tool_call_id": permission_call_id, "permission": "deny"},
                    )

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name", "") or "")
            call_id = str(call.get("id", "") or f"tool_{uuid.uuid4().hex[:10]}")
            args = call.get("args") if isinstance(call.get("args"), dict) else {}

            permission = self.permission_gate.check_permission(name, args, tool_spec=self._tool_spec(name, state.get("active_skills", []) or []))

            if permission == Permission.DENY:
                result = f"Denied by PermissionGate: {name}"
                out_messages.append(ToolMessage(content=result, tool_call_id=call_id))
                if task_id:
                    self.event_bus.emit(task_id, "tool_failed", actor="tool", summary=result, step=step, importance=0.94, data={"tool": name})
                continue
            if permission == Permission.ASK and call_id != approved_permission_call_id:
                if call_id == denied_permission_call_id:
                    result = f"Permission denied by user: {name}"
                else:
                    result = f"Deferred {name}: request permission again after the current decision."
                out_messages.append(ToolMessage(content=result, tool_call_id=call_id))
                if task_id and call_id == denied_permission_call_id:
                    self.event_bus.emit(
                        task_id,
                        "tool_failed",
                        actor="tool",
                        summary=f"Người dùng không cấp quyền cho {name}.",
                        step=step,
                        importance=0.86,
                        data={"tool": name, "reason": "permission_denied"},
                    )
                continue

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

            try:
                tool_spec = self._tool_spec(name, state.get("active_skills", []) or [])
                if self._should_snapshot_before_tool(name, tool_spec):
                    self._ensure_atomic_checkpoint(state, tool_name=name, step=step)
                workspace_ref = str(state.get("workspace_id", "") or state.get("workspace_path", "") or "").strip()
                # A running task owns its workspace for its lifetime. Workspace list
                # is harmless, but switch/join/leave from inside the executor would
                # invalidate every later observation and is therefore refused.
                if workspace_ref and name in {"workspace_join", "workspace_switch", "workspace_leave"}:
                    raise RuntimeError("task_workspace_locked: create/select workspace from Agent Console before starting the task")
                scope = self.workspace_scope(workspace_ref) if workspace_ref and callable(self.workspace_scope) else nullcontext()
                with self._workspace_tool_lock, scope:
                    result = self._invoke_tool(name, args, task_id=task_id)
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
        if permission_resume_context:
            patch["ide_context"] = permission_resume_context
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
        if str(state.get("rollback_requested", "") or "").strip():
            return "__end__"
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
        session_id: str = "",
        workspace_id: str = "",
        workspace_path: str = "",
        workspace_name: str = "",
        ide_context: dict[str, Any] | None = None,
    ):
        """Bắt đầu một task mới trên LangGraph thread bền vững.

        Khi gặp ``interrupt()`` hàm trả về ngay với status ``waiting_user``;
        worker được giải phóng hoàn toàn. Client sẽ gọi ``resume_task`` sau.
        """
        normalized_mode = "inspect" if str(task_mode or "execute").strip().lower() == "inspect" else "execute"
        normalized_source = str(source or "eris_chat").strip() or "eris_chat"
        normalized_session = str(session_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_workspace_path = str(workspace_path or "").strip()
        normalized_workspace_name = str(workspace_name or "").strip()
        clean_context = _compact_ide_context(ide_context)
        task = self.task_store.create_task(
            clarified_goal or goal,
            task_id=task_id,
            executor=self.executor_name,
            model=self.model_name,
            thread_id=thread_id,
            session_id=normalized_session,
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
            thread_id=thread_id,
            session_id=normalized_session,
            pending_interrupt={},
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
                "session_id": normalized_session,
                "workspace_id": normalized_workspace_id,
                "workspace_path": normalized_workspace_path,
                "workspace_name": normalized_workspace_name,
            },
        )

        initial_state: AgentState = {
            "goal": clarified_goal or goal,
            "task_id": task_id,
            "thread_id": thread_id,
            "session_id": normalized_session,
            "executor": self.executor_name,
            "model": self.model_name,
            "task_mode": normalized_mode,
            "source": normalized_source,
            "workspace_id": normalized_workspace_id,
            "workspace_path": normalized_workspace_path,
            "workspace_name": normalized_workspace_name,
            "ide_context": clean_context,
            "status": "running",
            "messages": [HumanMessage(content=clarified_goal or goal)],
            "active_skills": [],
            "active_tools": [],
            "injected_context": "",
            "pending_directives": [],
            "rollback_requested": "",
            "step_count": 0,
        }
        return self._drive_graph_task(
            task_id=task_id,
            thread_id=thread_id,
            workspace_path=normalized_workspace_path,
            graph_input=initial_state,
        )

    def resume_task(
        self,
        task_id: str,
        response: Any = None,
        *,
        directive: str = "",
        ide_context: dict[str, Any] | None = None,
    ):
        """Resume task đã interrupt/pause mà không cần worker polling sống nền.

        ``waiting_user`` dùng đúng ``Command(resume=...)`` và cùng ``thread_id``.
        ``paused`` là pause ở node boundary nên re-enter bằng state patch thường.
        """
        task_id = str(task_id or "").strip()
        task = self.task_store.get_task(task_id, event_limit=0)
        if task is None:
            raise KeyError(f"unknown_agent_task:{task_id}")
        status = str(task.get("status", "") or "").strip().lower()
        if status in {"completed", "failed", "stopped"}:
            raise RuntimeError(f"agent_task_terminal:{status}")

        thread_id = str(task.get("thread_id", "") or task_id).strip()
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        workspace_path = str(metadata.get("workspace_path", "") or "").strip()

        clean_resume_context = _compact_ide_context(ide_context)

        if status in {"waiting_user", "waiting_permission"}:
            # Nếu caller truyền context riêng mà response chưa có, gắn vào payload
            # resume. interrupt() sẽ đọc nó ở đúng node đang chờ.
            if clean_resume_context and isinstance(response, dict) and not isinstance(response.get("ideContext"), dict):
                response = {**response, "ideContext": clean_resume_context}
            self.event_bus.emit(
                task_id,
                "interrupt_resume_requested",
                actor="user",
                summary="Đã nhận phản hồi; đang resume đúng LangGraph checkpoint.",
                importance=0.82,
            )
            graph_input: Any = Command(resume=response)
        elif status == "paused":
            messages: list[HumanMessage] = []
            if str(directive or "").strip():
                messages.append(HumanMessage(content="[RUNTIME DIRECTIVE AFTER PAUSE]\n" + str(directive).strip()))
            graph_input = {"status": "running", "rollback_requested": ""}
            if messages:
                graph_input["messages"] = messages
            if clean_resume_context:
                graph_input["ide_context"] = clean_resume_context
            self.event_bus.emit(
                task_id,
                "task_resumed",
                actor="system",
                summary="Task tiếp tục từ checkpoint của cùng LangGraph thread.",
                importance=0.76,
            )
        else:
            raise RuntimeError(f"agent_task_not_waiting:{status or 'unknown'}")

        return self._drive_graph_task(
            task_id=task_id,
            thread_id=thread_id,
            workspace_path=workspace_path,
            graph_input=graph_input,
        )

    def stop_task(self, task_id: str, *, reason: str = "user") -> bool:
        """Dừng projection task kể cả khi hiện không còn worker để consume control."""
        task = self.task_store.get_task(str(task_id or "").strip(), event_limit=0)
        if task is None:
            return False
        if str(task.get("status", "") or "") in {"completed", "failed", "stopped"}:
            return True
        self.event_bus.emit(
            str(task_id),
            "task_stopped",
            actor="system",
            summary="Task đã dừng theo control plane.",
            importance=0.95,
            data={"reason": str(reason or "user")},
        )
        return True

    def _drive_graph_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        workspace_path: str,
        graph_input: Any,
    ):
        """Chạy graph cho tới END, pause boundary, rollback hoặc interrupt thật."""
        base_config = {"configurable": {"thread_id": thread_id}}
        config = dict(base_config)
        try:
            while True:
                pending_rollback = ""
                if isinstance(graph_input, dict):
                    pending_rollback = str(graph_input.get("rollback_requested", "") or "").strip()
                if pending_rollback:
                    try:
                        record = self._restore_atomic_checkpoint(
                            task_id=task_id,
                            checkpoint_id=pending_rollback,
                            thread_id=thread_id,
                            workspace_path=workspace_path,
                        )
                    except Exception as exc:
                        self.event_bus.emit(
                            task_id,
                            "rollback_failed",
                            actor="system",
                            summary=f"Không rollback được checkpoint {pending_rollback}: {type(exc).__name__}: {exc}",
                            importance=0.96,
                            data={"checkpoint_id": pending_rollback, "error": type(exc).__name__},
                        )
                        config = dict(base_config)
                        graph_input = {
                            "status": "running",
                            "rollback_requested": "",
                            "messages": [HumanMessage(content=(
                                "[ROLLBACK UNAVAILABLE] The requested checkpoint could not be restored. "
                                "Continue from the current state and choose a safe alternative."
                            ))],
                        }
                    else:
                        config = {"configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": record.graph_checkpoint_id,
                        }}
                        graph_input = {
                            "status": "running",
                            "rollback_requested": "",
                            "messages": [HumanMessage(content=(
                                "[ATOMIC ROLLBACK RESTORED]\n"
                                "Graph state and workspace were restored to the selected checkpoint. "
                                "Reassess before attempting another side effect."
                            ))],
                        }

                result = self.graph.invoke(graph_input, config)
                config = dict(base_config)

                interrupt_values = _extract_interrupt_values(result)
                if interrupt_values:
                    payload = _normalize_interrupt_payload(
                        interrupt_values[0], task_id=task_id, thread_id=thread_id
                    )
                    kind = str(payload.get("type", "interrupt.request") or "interrupt.request")
                    waiting_status = "waiting_permission" if kind == "permission.request" else "waiting_user"
                    event_type = "permission_requested" if waiting_status == "waiting_permission" else "interrupt_requested"
                    self.task_store.update_task(task_id, status=waiting_status, pending_interrupt=payload)
                    self.event_bus.emit(
                        task_id,
                        event_type,
                        actor="executor",
                        summary=str(payload.get("question", "") or payload.get("message", "") or "Cần phản hồi của người dùng."),
                        detail="LangGraph đã checkpoint và nhả worker; task sẽ resume bằng Command(resume=...).",
                        step=int(payload.get("step", 0) or 0),
                        importance=0.98,
                        data=payload,
                    )
                    public = dict(result) if isinstance(result, dict) else {}
                    public["status"] = waiting_status
                    public["interrupt"] = payload
                    return public

                final_status = str((result or {}).get("status", "running") or "running") if isinstance(result, dict) else "running"
                rollback_after_step = str((result or {}).get("rollback_requested", "") or "").strip() if isinstance(result, dict) else ""
                if rollback_after_step:
                    graph_input = {"rollback_requested": rollback_after_step}
                    continue

                # Pause/stop là boundary state: worker kết thúc ngay, không sleep loop.
                if final_status in {"paused", "stopped", "waiting_user", "waiting_permission"}:
                    return result

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

    def close(self) -> None:
        """Đóng SQLite connection khi runtime shutdown/reload."""
        runtime = self._checkpoint_runtime
        self._checkpoint_runtime = None
        if runtime is not None:
            runtime.close()

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



def _normalize_choice_request(args: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Chuẩn hóa payload choice trước khi đưa vào LangGraph interrupt."""
    question = str(args.get("question", "") or "").strip()[:1200]
    raw_options = args.get("options") if isinstance(args.get("options"), list) else []
    options: list[dict[str, str]] = []
    for index, item in enumerate(raw_options[:5]):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "") or "").strip()[:240]
        if not label:
            continue
        option_id = str(item.get("id", "") or "").strip()[:80] or f"option_{index + 1}"
        description = str(item.get("description", "") or "").strip()[:700]
        value = str(item.get("value", "") or "").strip()[:1600] or label
        options.append({
            "id": option_id,
            "label": label,
            "description": description,
            "value": value,
        })
    return question, options


def _choice_resume_text(response: Any, options: list[dict[str, str]]) -> str:
    """Biến response từ VS Code/legacy UI thành observation ngắn cho LLM."""
    if isinstance(response, dict):
        choice_id = str(
            response.get("choiceId", "")
            or response.get("choice_id", "")
            or response.get("id", "")
            or ""
        ).strip()
        explicit = str(
            response.get("value", "")
            or response.get("text", "")
            or response.get("custom", "")
            or ""
        ).strip()
        if explicit:
            return explicit[:2000]
        if choice_id:
            for option in options:
                if str(option.get("id", "") or "") == choice_id:
                    return str(option.get("value", "") or option.get("label", "") or "")[:2000]
            return choice_id[:2000]
    if response is None:
        return ""
    return str(response).strip()[:2000]


def _resume_ide_context(response: Any) -> dict[str, Any]:
    """Lấy IDE context mới đi kèm phản hồi interrupt, nếu client có gửi."""
    if not isinstance(response, dict):
        return {}
    raw = response.get("ideContext") if isinstance(response.get("ideContext"), dict) else response.get("ide_context")
    return _compact_ide_context(raw) if isinstance(raw, dict) else {}


def _permission_resume_allowed(response: Any) -> bool:
    """Chuẩn hóa phản hồi permission từ Choice Card/legacy client."""
    if isinstance(response, dict):
        value = str(
            response.get("choiceId", "")
            or response.get("choice_id", "")
            or response.get("value", "")
            or response.get("text", "")
            or ""
        ).strip().lower()
    else:
        value = str(response or "").strip().lower()
    return value in {"allow", "allow_once", "yes", "y", "ok", "approve", "approved", "cho phép", "dong y", "đồng ý"}


def _extract_interrupt_values(result: Any) -> list[Any]:
    """Đọc interrupt ở cả output V1 dict lẫn GraphOutput mới hơn."""
    raw = None
    if isinstance(result, dict):
        raw = result.get("__interrupt__")
    if raw is None:
        raw = getattr(result, "interrupts", None)
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    values: list[Any] = []
    for item in raw:
        values.append(getattr(item, "value", item))
    return values


def _normalize_interrupt_payload(value: Any, *, task_id: str, thread_id: str) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
    else:
        payload = {"question": str(value or "")}
    payload.setdefault("type", "interrupt.request")
    payload.setdefault("taskId", task_id)
    payload.setdefault("threadId", thread_id)
    return _compact_jsonish(payload, depth=0)


def _compact_ide_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact = _compact_jsonish(value, depth=0)
    return compact if isinstance(compact, dict) else {}


def _compact_jsonish(value: Any, *, depth: int) -> Any:
    """Giữ context checkpointable và không để client nhét payload vô hạn."""
    if depth > 5:
        return "[truncated-depth]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 5000 else value[:4999].rstrip() + "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            out[str(key)[:120]] = _compact_jsonish(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_compact_jsonish(item, depth=depth + 1) for item in list(value)[:80]]
    return str(value)[:1000]


def _ide_client_capabilities(ide_context: dict[str, Any] | None) -> set[str]:
    if not isinstance(ide_context, dict):
        return set()
    client = ide_context.get("client") if isinstance(ide_context.get("client"), dict) else {}
    raw = client.get("capabilities") if isinstance(client.get("capabilities"), list) else []
    return {str(item).strip() for item in raw if str(item).strip()}

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
