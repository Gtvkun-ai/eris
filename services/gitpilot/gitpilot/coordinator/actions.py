"""Workspace action adapter for the Main Coordinator.

Runtime quyết định *làm gì*; module này chỉ biết *thực thi action đó thế nào* trên
local workspace. Tách ranh giới này để cognition kernel không dính chặt vào local
filesystem và có thể thay bằng remote/GitHub adapter về sau.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, Optional

from .. import agent_events as evt
from ..agent_events import AgentEventBus
from ..approval_protocol import ApprovalGate
from ..terminal import TerminalExecutor, TerminalSession
from ..workspace import WorkspaceInfo, WorkspaceManager
from .scheduler import ResearchScheduler
from .state import CoordinatorMemory, CoordinatorState, ResearchJob

HarvestCallback = Callable[[CoordinatorState, bool, Optional[list[str]]], Awaitable[None]]


class CoordinatorActions:
    def __init__(
        self,
        *,
        workspace: WorkspaceInfo,
        bus: AgentEventBus,
        gate: ApprovalGate,
        ws_manager: WorkspaceManager,
        terminal: TerminalExecutor,
        memory: CoordinatorMemory,
        research: ResearchScheduler,
        harvest: HarvestCallback,
    ) -> None:
        self.workspace = workspace
        self.bus = bus
        self.gate = gate
        self.ws = ws_manager
        self.terminal = terminal
        self.memory = memory
        self.research = research
        self.harvest = harvest

    async def readonly(self, state: CoordinatorState, action: dict) -> None:
        typ = str(action.get("type") or "").lower()
        if typ == "search":
            pattern = str(action.get("pattern") or "").strip()
            path = str(action.get("path") or ".").strip() or "."
            if not pattern:
                return
            state.searches.add((pattern, path))
            await self.bus.emit(evt.status_change("investigating", f"Searching {path}"))
            matches = await self.ws.search_files(self.workspace, pattern, path)
            detail = "\n".join(
                f"{m.get('file')}:{m.get('line')}: {m.get('content')}" for m in matches
            )
            state.add_evidence("search", f"{path} :: {pattern}", f"{len(matches)} match(es)", detail[:24_000])
            return

        if typ == "read":
            paths = [str(p) for p in (action.get("paths") or []) if str(p).strip()]
            if not paths:
                return
            await self.bus.emit(evt.status_change("investigating", f"Reading {len(paths)} relevant file(s)"))
            results = await asyncio.gather(
                *[self.ws.read_file(self.workspace, p) for p in paths],
                return_exceptions=True,
            )
            for path, result in zip(paths, results):
                if isinstance(result, BaseException):
                    state.add_evidence("file_read_error", path, "Could not read file", str(result))
                else:
                    state.visited_files.add(path)
                    state.add_evidence("file", path, f"Read {len(result)} chars from {path}", result)
            return

        if typ == "git_status":
            status = await self.ws.status(self.workspace)
            state.add_evidence("git_status", "git", "Current git status", json.dumps(status, ensure_ascii=False, indent=2))
            return

        if typ == "git_diff":
            staged = bool(action.get("staged"))
            diff = await self.ws.diff(self.workspace, staged=staged)
            state.add_evidence("git_diff", "staged" if staged else "working-tree", f"Git diff captured ({len(diff)} chars)", diff)
            return

        if typ == "delegate":
            jobs_raw = action.get("jobs") or []
            submitted: list[str] = []
            for item in jobs_raw:
                if not isinstance(item, dict) or not str(item.get("goal") or "").strip():
                    continue
                job = ResearchJob(
                    goal=str(item.get("goal")),
                    hint_paths=[str(x) for x in (item.get("hint_paths") or [])],
                    search_terms=[str(x) for x in (item.get("search_terms") or [])],
                    label=str(item.get("label") or "research"),
                    priority=float(item.get("priority") or 0.5),
                )
                job_id = self.research.submit(job)
                state.active_research[job_id] = job.label
                submitted.append(job_id)
            if submitted:
                await self.bus.emit(evt.status_change("delegating", f"Queued {len(submitted)} background research branch(es)"))
                state.add_evidence(
                    "delegation",
                    "coordinator",
                    f"Queued {len(submitted)} background research job(s)",
                    json.dumps({job_id: state.active_research[job_id] for job_id in submitted}, ensure_ascii=False),
                )
                await asyncio.sleep(0)
            return

        if typ == "await_subagents":
            requested = [str(x) for x in (action.get("job_ids") or []) if str(x).strip()]
            await self.bus.emit(evt.status_change("researching", "Collecting background research"))
            await self.harvest(state, True, requested or None)
            return

        raise ValueError(f"unknown read-only action: {typ or 'unknown'}")

    async def barrier(self, state: CoordinatorState, action: dict, *, mode: str) -> None:
        typ = str(action.get("type") or "").lower()
        if typ == "await_subagents":
            await self.readonly(state, action)
            return

        if mode in {"plan_only", "inspect"} and typ in {"write", "delete", "run"}:
            state.add_evidence("mode_guard", typ, f"Blocked {typ} in read-only mode {mode}")
            return

        if typ == "write":
            for item in action.get("files") or []:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                content = str(item.get("content") or "")
                if not path:
                    continue
                allowed = await self.gate.check(
                    "write_file",
                    {"path": path, "content_length": len(content)},
                    summary=f"Modify {path}",
                )
                if not allowed:
                    state.add_evidence("write_denied", path, "User denied file write")
                    continue
                await self.ws.write_file(self.workspace, path, content)
                await self.bus.emit(evt.file_write(path, "modify"))
                state.add_evidence("write", path, f"Wrote {len(content)} chars")
                self._invalidate_repo_model()
            return

        if typ == "delete":
            for path in [str(p) for p in (action.get("paths") or []) if str(p).strip()]:
                allowed = await self.gate.check("Delete local file", {"path": path}, summary=f"Delete {path}")
                if not allowed:
                    state.add_evidence("delete_denied", path, "User denied deletion")
                    continue
                deleted = await self.ws.delete_file(self.workspace, path)
                if deleted:
                    await self.bus.emit(evt.file_write(path, "delete"))
                state.add_evidence("delete", path, f"Deleted={deleted}")
                self._invalidate_repo_model()
            return

        if typ == "run":
            command = str(action.get("command") or "").strip()
            if not command:
                return
            timeout = int(action.get("timeout") or 120)
            allowed = await self.gate.check(
                "run_command",
                {"command": command, "timeout": timeout},
                summary=f"Run: {command}",
            )
            if not allowed:
                state.add_evidence("command_denied", command, "User denied command")
                return
            await self.bus.emit(evt.status_change("executing", command[:180]))
            result = await self.terminal.execute(
                TerminalSession(workspace_path=self.workspace.path), command, timeout=timeout,
            )
            await self.bus.emit(evt.terminal_exit(command, result.exit_code, result.duration_ms))
            detail = (result.stdout or "") + (("\nSTDERR:\n" + result.stderr) if result.stderr else "")
            state.add_evidence(
                "command",
                command,
                f"exit={result.exit_code}, duration={result.duration_ms}ms, timed_out={result.timed_out}",
                detail,
            )
            # Shell có thể mutate bất kỳ file nào nên invalidate conservatively.
            self._invalidate_repo_model()
            return

        raise ValueError(f"unknown mutating/barrier action: {typ or 'unknown'}")

    def _invalidate_repo_model(self) -> None:
        self.memory.workspace_signature = ""
        self.memory.graph.stale_claims()
