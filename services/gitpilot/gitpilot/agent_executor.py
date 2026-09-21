# gitpilot/agent_executor.py
"""
Streaming multi-step agent executor.

Wraps existing CrewAI plan+execute functions with granular event streaming
via the AgentEventBus. Does NOT modify agentic.py or any existing module.

Execution pipeline:
  1. Plan   (reuses generate_plan_lite / generate_plan)
  2. Execute (reuses execute_plan_lite / execute_plan, with streaming shim)
  3. Validate (run detected linter/tests, feed errors back)

All events flow through AgentEventBus -> consumers (WS v2, SSE, VS Code).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from . import agent_events as evt
from .agent_events import AgentEventBus
from .approval_protocol import ApprovalGate
from .terminal import TerminalExecutor, TerminalSession
from .workspace import WorkspaceManager, WorkspaceInfo
from .test_detection import detect_test_command, detect_framework_name
from .diagnostics_runner import run_linter, parse_diagnostics

logger = logging.getLogger(__name__)

# Maximum retries for self-correction after validation errors
MAX_VALIDATION_RETRIES = 2


class StreamingAgentExecutor:
    """
    Autonomous multi-step agent executor with real-time streaming.

    Orchestrates the full pipeline:
      plan -> per-step execution -> validation -> self-correction -> done

    Emits all events through the AgentEventBus so any transport
    (WebSocket v2, SSE, VS Code postMessage) can forward them.
    """

    def __init__(
        self,
        bus: AgentEventBus,
        gate: ApprovalGate,
        workspace: Optional[WorkspaceInfo] = None,
        ws_manager: Optional[WorkspaceManager] = None,
        terminal: Optional[TerminalExecutor] = None,
    ) -> None:
        self._bus = bus
        self._gate = gate
        self._workspace = workspace
        self._ws_manager = ws_manager or WorkspaceManager()
        self._terminal = terminal or TerminalExecutor()
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the executor to stop after the current step."""
        self._cancelled = True

    async def execute(
        self,
        user_message: str,
        repo_full_name: str,
        branch: Optional[str] = None,
        token: Optional[str] = None,
        mode: str = "auto",
        topology_id: str = "feature_builder",
    ) -> Optional[dict]:
        """
        Main entry point. Streams events throughout.

        Args:
            user_message: The user's request
            repo_full_name: "owner/repo" (required for multi-agent path)
            branch: Git branch (default HEAD)
            token: GitHub token (for remote repos)
            mode: "auto" | "plan_only" | "inspect"
            topology_id: GitPilot topology; local mode tái sử dụng sequence nhưng
                bỏ các agent chỉ có ý nghĩa với GitHub như PR manager.

        Returns:
            The plan dict on success, None on failure.
        """
        # V78: local/folder session KHÔNG còn downgrade sang direct LLM.
        # Nếu session có workspace local, dùng chính CrewAI + local tools của
        # GitPilot để chạy Explorer → Planner → Coder → Reviewer. GitHub path
        # cũ vẫn được giữ nguyên phía dưới để patch upstream luôn hẹp.
        if not self._is_valid_repo_full_name(repo_full_name):
            try:
                if self._workspace is None:
                    await self._bus.emit(evt.agent_error(
                        "Local session has no workspace; cannot run GitPilot coding team"
                    ))
                    return None
                return await self._execute_local_team(
                    user_message=user_message, mode=mode, topology_id=topology_id
                )
            except Exception as e:
                logger.error("StreamingAgentExecutor local team error: %s", e, exc_info=True)
                await self._bus.emit(evt.agent_error(str(e)))
                return None

        try:
            # ── Phase 1: Plan ──
            await self._bus.emit(evt.status_change("planning", "Analyzing your request..."))

            plan = await self._generate_plan(user_message, repo_full_name, token, branch)
            if not plan:
                await self._bus.emit(evt.agent_error("Failed to generate plan"))
                return None

            # Emit plan structure
            steps = plan.get("steps", []) if isinstance(plan, dict) else []
            if hasattr(plan, "steps"):
                steps = [
                    {"title": s.title, "description": s.description}
                    for s in plan.steps
                ]

            goal = plan.get("goal", user_message) if isinstance(plan, dict) else getattr(plan, "goal", user_message)
            summary = plan.get("summary", "") if isinstance(plan, dict) else getattr(plan, "summary", "")

            for i, step in enumerate(steps):
                title = step.get("title", f"Step {i + 1}") if isinstance(step, dict) else getattr(step, "title", f"Step {i + 1}")
                await self._bus.emit(evt.plan_step(i, title, "pending"))

            if self._cancelled:
                await self._bus.emit(evt.agent_error("Cancelled by user", recoverable=True))
                return None

            if mode == "plan_only":
                await self._bus.emit(evt.agent_done(summary="Plan generated."))
                return plan if isinstance(plan, dict) else {"goal": goal, "summary": summary, "steps": steps}

            # ── Phase 2: Execute ──
            await self._bus.emit(evt.status_change("generating", "Executing plan..."))

            result = await self._execute_plan(plan, repo_full_name, token, branch)

            # Stream result text in chunks (simulate token streaming from batch)
            answer = self._extract_answer(result)
            chunk_size = 80
            for i in range(0, len(answer), chunk_size):
                if self._cancelled:
                    break
                await self._bus.emit(evt.text_delta(answer[i : i + chunk_size]))
                await asyncio.sleep(0.015)

            if self._cancelled:
                await self._bus.emit(evt.agent_error("Cancelled by user", recoverable=True))
                return None

            # ── Phase 3: Validate ──
            await self._bus.emit(evt.status_change("reviewing", "Validating changes..."))
            await self._run_validation()

            # ── Done ──
            await self._bus.emit(evt.status_change("done"))
            await self._bus.emit(evt.agent_done(summary=answer[:500]))

            return plan if isinstance(plan, dict) else {"goal": goal, "summary": summary}

        except Exception as e:
            logger.error("StreamingAgentExecutor error: %s", e, exc_info=True)
            await self._bus.emit(evt.agent_error(str(e)))
            return None

    # ── Internal helpers ──

    async def _execute_local_team(
        self,
        *,
        user_message: str,
        mode: str,
        topology_id: str,
    ) -> dict:
        """Chạy coding team GitPilot trên đúng workspace local của user.

        Đây là adapter V78, không phải một agent framework mới. Nó tái sử dụng:
        - CrewAI + provider/model builder hiện có của GitPilot;
        - topology registry hiện có;
        - local file/git/shell tools hiện có;
        - ApprovalGate và AgentEventBus hiện có.
        """
        import contextvars
        from .agentic import _build_llm, _crewai, _guarded_agent_call
        from .local_tools import (
            delete_local_file, git_diff, git_log, git_status, list_local_files,
            local_tool_runtime, read_local_file, run_command, run_in_sandbox,
            search_in_files, write_local_file,
        )

        sequence = self._local_sequence(topology_id, mode)
        outputs: dict[str, str] = {}
        llm = _build_llm()
        loop = asyncio.get_running_loop()

        read_tools = [read_local_file, list_local_files, search_in_files, git_status, git_diff, git_log]
        coder_tools = [
            read_local_file, list_local_files, search_in_files, git_status, git_diff,
            write_local_file, delete_local_file, run_command, run_in_sandbox,
        ]
        reviewer_tools = [read_local_file, list_local_files, search_in_files, git_status, git_diff]

        role_specs = {
            "explorer": {
                "role": "Repository Explorer",
                "goal": "Locate the relevant code and evidence before any edit",
                "tools": read_tools,
                "instruction": (
                    "Explore the local workspace first. Read the real files that matter, "
                    "trace call/data flow, identify tests and report evidence with paths. "
                    "Do not propose edits before you have inspected enough evidence."
                ),
            },
            "planner": {
                "role": "Implementation Planner",
                "goal": "Turn repository evidence into a narrow, verifiable plan",
                "tools": read_tools,
                "instruction": (
                    "Use the Explorer evidence and inspect more files only when needed. "
                    "Produce a small implementation plan: root cause/hypothesis, files to "
                    "change, invariants, and exact verification. Do not modify files."
                ),
            },
            "developer": {
                "role": "Coder",
                "goal": "Implement the approved plan with minimal changes and verify it",
                "tools": coder_tools,
                "instruction": (
                    "Implement the plan in the CURRENT local workspace using the provided "
                    "tools. Read before writing. Keep scope narrow. Run focused tests/build "
                    "after edits and inspect git diff. Do not commit or push."
                ),
            },
            "reviewer": {
                "role": "Code Reviewer",
                "goal": "Review the actual workspace diff for correctness and regression risk",
                "tools": reviewer_tools,
                "instruction": (
                    "Review the actual git diff and relevant source. Check correctness, "
                    "scope, maintainability, security and missing regression coverage. "
                    "Do not modify files."
                ),
            },
        }

        previous = ""
        with local_tool_runtime(self._workspace, gate=self._gate, bus=self._bus, loop=loop):
            for index, role_id in enumerate(sequence):
                if self._cancelled:
                    await self._bus.emit(evt.agent_error("Cancelled by user", recoverable=True))
                    return {"summary": "Cancelled", "roles": list(outputs)}

                spec = role_specs.get(role_id)
                if spec is None:
                    continue
                await self._bus.emit(evt.status_change(role_id, spec["role"]))
                await self._bus.emit(evt.plan_step(index, spec["role"], "running", role_id))

                context_text = previous[-12000:] if previous else "No previous phase output."
                task_description = (
                    f"User request:\n{user_message}\n\n"
                    f"Previous phase output:\n{context_text}\n\n"
                    f"Your phase instructions:\n{spec['instruction']}"
                )
                agent = _crewai()["Agent"](
                    role=spec["role"],
                    goal=spec["goal"],
                    backstory=(
                        "You are one specialist inside GitPilot. The local workspace tools "
                        "are the source of truth. Never invent file contents or tool results."
                    ),
                    llm=llm,
                    tools=spec["tools"],
                    verbose=True,
                    allow_delegation=False,
                )
                task = _crewai()["Task"](
                    description=task_description,
                    expected_output=f"Concise evidence-based output from {spec['role']}",
                    agent=agent,
                )
                crew = _crewai()["Crew"](
                    agents=[agent], tasks=[task],
                    process=_crewai()["Process"].sequential, verbose=True,
                )

                def _run():
                    result = crew.kickoff()
                    return result.raw if hasattr(result, "raw") else str(result)

                ctx = contextvars.copy_context()
                text = str(await _guarded_agent_call(ctx, _run, label=f"local_{role_id}"))
                outputs[role_id] = text
                previous = text
                # V79 telemetry: emit output mà specialist chủ động trả về, không
                # scrape verbose log/chain-of-thought nội bộ của CrewAI.
                await self._bus.emit(evt.phase_summary(role_id, text))
                await self._bus.emit(evt.plan_step(index, spec["role"], "completed", role_id))

                # Plan mode dừng sau Planner; inspect mode chỉ chạy role read-only.
                if mode == "plan_only" and role_id == "planner":
                    break

        summary_parts = [f"{name.title()}: {text}" for name, text in outputs.items()]
        summary = "\n\n".join(summary_parts)
        if summary:
            for i in range(0, len(summary), 120):
                await self._bus.emit(evt.text_delta(summary[i:i + 120]))

        if not self._cancelled and mode != "plan_only" and "developer" in outputs:
            await self._bus.emit(evt.status_change("verify", "Validation"))
            await self._run_validation()

        await self._bus.emit(evt.status_change("done", "GitPilot team completed"))
        await self._bus.emit(evt.agent_done(summary=summary[:5000]))
        return {"summary": summary, "roles": list(outputs), "topology_id": topology_id}

    @staticmethod
    def _local_sequence(topology_id: str, mode: str) -> list[str]:
        """Tái sử dụng topology registry, nhưng bỏ role GitHub-only ở local mode."""
        if mode == "plan_only":
            return ["explorer", "planner"]
        if mode == "inspect":
            return ["explorer", "reviewer"]
        try:
            from .topology_registry import RoutingStrategy, get_topology
            topology = get_topology(topology_id or "feature_builder")
            if topology and topology.routing_policy.strategy == RoutingStrategy.fixed_sequence:
                allowed = {"explorer", "planner", "developer", "reviewer"}
                sequence = [role for role in (topology.routing_policy.sequence or []) if role in allowed]
                if sequence:
                    return sequence
        except Exception:
            pass
        return ["explorer", "planner", "developer", "reviewer"]

    @staticmethod
    def _is_valid_repo_full_name(name: object) -> bool:
        """True iff `name` is a non-empty 'owner/repo' string with both parts.

        Rejects: None, empty strings, strings without '/', strings with
        empty owner or repo, and strings containing more than one '/'.
        """
        if not isinstance(name, str) or not name.strip():
            return False
        parts = name.strip().split("/")
        return len(parts) == 2 and all(p.strip() for p in parts)

    async def _generate_plan(self, goal, repo_full_name, token, branch):
        """Wrap existing plan generators with event streaming."""
        try:
            from .agentic import generate_plan_lite
            return await generate_plan_lite(
                goal=goal,
                repo_full_name=repo_full_name,
                token=token,
                branch_name=branch,
            )
        except ImportError:
            logger.warning("generate_plan_lite not available, using fallback")
        except Exception as e:
            logger.error("Plan generation error: %s", e)
            await self._bus.emit(evt.agent_error(f"Planning failed: {e}"))
        return None

    async def _execute_plan(self, plan, repo_full_name, token, branch):
        """Wrap existing plan executors with event streaming."""
        try:
            from .agentic import execute_plan_lite
            return await execute_plan_lite(
                plan=plan,
                repo_full_name=repo_full_name,
                token=token,
                branch_name=branch,
            )
        except ImportError:
            logger.warning("execute_plan_lite not available, using fallback")
        except Exception as e:
            logger.error("Plan execution error: %s", e)
            await self._bus.emit(evt.agent_error(f"Execution failed: {e}"))
        return None

    async def _run_validation(self) -> None:
        """Run linter and/or tests if the workspace supports them."""
        if not self._workspace:
            return

        ws_path = self._workspace.path if hasattr(self._workspace, "path") else Path(str(self._workspace))

        # ── Lint check ──
        try:
            lint_result = await run_linter(ws_path, self._terminal, timeout=60)
            if lint_result:
                entries = parse_diagnostics(lint_result.stdout + lint_result.stderr)
                errors = [e for e in entries if e.get("severity") == "error"]
                warnings = [e for e in entries if e.get("severity") == "warning"]
                await self._bus.emit(evt.diagnostics(
                    errors=len(errors),
                    warnings=len(warnings),
                    entries=entries,
                ))
        except Exception as e:
            logger.debug("Linter not available: %s", e)

        # ── Test check ──
        try:
            test_cmd = await detect_test_command(ws_path)
            if test_cmd:
                framework = await detect_framework_name(ws_path) or "unknown"
                session = TerminalSession(workspace_path=ws_path)

                await self._bus.emit(evt.tool_start(
                    uuid.uuid4().hex[:8], "run_tests", {"command": test_cmd}
                ))

                # Stream test output
                output_chunks = []
                exit_code = -1
                duration_ms = 0

                async for chunk in self._terminal.execute_streaming(session, test_cmd, timeout=120):
                    if chunk.get("type") == "stdout":
                        output_chunks.append(chunk["data"])
                        await self._bus.emit(evt.terminal_output("stdout", chunk["data"]))
                    elif chunk.get("type") == "error":
                        output_chunks.append(chunk.get("data", ""))
                        await self._bus.emit(evt.terminal_output("stderr", chunk.get("data", "")))
                    elif chunk.get("type") == "exit":
                        exit_code = chunk.get("exit_code", -1)
                        duration_ms = chunk.get("duration_ms", 0)

                await self._bus.emit(evt.terminal_exit(test_cmd, exit_code, duration_ms))

                # Parse test results
                full_output = "".join(output_chunks)
                passed, failed, skipped = self._parse_test_counts(full_output)

                await self._bus.emit(evt.test_result(
                    framework=framework,
                    passed=passed,
                    failed=failed,
                    skipped=skipped,
                    output=full_output,
                    exit_code=exit_code,
                ))
        except Exception as e:
            logger.debug("Test runner not available: %s", e)

    @staticmethod
    def _extract_answer(result) -> str:
        """Extract the response text from various result formats."""
        if result is None:
            return "Task completed."
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return (
                result.get("result")
                or result.get("answer")
                or result.get("summary")
                or result.get("message")
                or str(result)
            )
        if hasattr(result, "raw"):
            return str(result.raw)
        return str(result)

    @staticmethod
    def _parse_test_counts(output: str) -> tuple[int, int, int]:
        """Best-effort extraction of pass/fail/skip counts from test output."""
        passed = failed = skipped = 0

        # Jest / Vitest: "Tests: 3 passed, 1 failed, 4 total"
        m = re.search(r"(\d+)\s+passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", output)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+)\s+skipped", output)
        if m:
            skipped = int(m.group(1))

        # pytest: "3 passed, 1 failed, 2 skipped"
        m = re.search(r"(\d+)\s+passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", output)
        if m:
            failed = int(m.group(1))

        # go test: "ok" or "FAIL"
        if "FAIL" in output and failed == 0:
            failed = output.count("FAIL")
        if "ok" in output and passed == 0:
            passed = output.count("\nok")

        return passed, failed, skipped


    # ---------------------------------------------------------------------
    # Batch P2-D — additive streaming co-method.
    #
    # Adapts the legacy ``execute(...)`` to the :mod:`gitpilot.streaming`
    # adapter contract.  Yields :class:`StreamEvent` objects so the SSE
    # route can flush each as it arrives.  Behaviour falls back to a
    # single ``assistant_chunk`` when the underlying executor has nothing
    # to stream (e.g. folder-only sessions).  No legacy method is
    # modified.
    # ---------------------------------------------------------------------
    async def run_streaming(self, payload):
        """Yield ``StreamEvent`` instances for the request *payload*.

        Recognised keys (every key is optional; sensible defaults apply):

        * ``user_message`` (str)  — the user's request
        * ``repo_full_name`` (str) — ``owner/repo`` for GitHub sessions
        * ``branch`` (str), ``token`` (str), ``mode`` (str)

        The method itself does not import ``gitpilot.streaming`` at
        module top-level so the agent executor stays usable in
        contexts where the streaming layer isn't wired (CLI, tests).
        """
        from .streaming import StreamEvent  # local import — keep agent_executor lean

        user_message = str(payload.get("user_message", ""))
        repo_full_name = str(payload.get("repo_full_name", ""))
        branch = payload.get("branch")
        token = payload.get("token")
        mode = payload.get("mode", "auto")

        yield StreamEvent(
            event="agent_event",
            data={"type": "executor_started", "mode": mode},
        )

        try:
            result = await self.execute(
                user_message=user_message,
                repo_full_name=repo_full_name,
                branch=branch,
                token=token,
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001 — boundary adapter
            yield StreamEvent(
                event="error",
                data={"code": "executor.failed", "message": str(exc)[:240]},
            )
            return

        if result is None:
            yield StreamEvent(
                event="assistant_chunk",
                data={"text": "(no plan produced — streaming fallback)"},
            )
            return

        plan_text = result.get("summary") if isinstance(result, dict) else None
        if not plan_text and isinstance(result, dict):
            plan_text = "\n".join(
                str(step.get("title") or step) for step in (result.get("steps") or [])[:5]
            )
        if plan_text:
            yield StreamEvent(
                event="assistant_chunk",
                data={"text": plan_text},
            )

        yield StreamEvent(event="agent_event", data={"type": "executor_finished"})
