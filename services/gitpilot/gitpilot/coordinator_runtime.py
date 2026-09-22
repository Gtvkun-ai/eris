"""Coordinator-centric local agent runtime — V106.

V106 giữ triết lý V105 và thêm workspace-scoped long-term memory:
- Main memory persistent qua session (repo model + investigation graph).
- Action graph có dependency/barrier thay vì gather mọi read-only action mù quáng.
- Logical research jobs đi qua PriorityQueue + worker pool cố định; không tạo một
  asyncio.Task cho mỗi subagent.
- Claims/frontiers/evidence là state có cấu trúc, không chỉ nằm trong prompt.
- Prompt/protocol/research/scheduler/state được tách module; runtime chỉ điều phối.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

from . import agent_events as evt
from .agent_events import AgentEventBus
from .approval_protocol import ApprovalGate
from .coordinator.actions import CoordinatorActions
from .coordinator.protocol import MAIN_SYSTEM, apply_graph_update, extract_json
from .coordinator.research import ResearchWorker
from .coordinator.scheduler import ActionScheduler, ResearchScheduler
from .coordinator.state import CoordinatorMemory, CoordinatorState, ResearchJob, ResearchReport, stable_json
from .coordinator.workspace_memory import WorkspaceMemoryRecord, WorkspaceMemoryStore
from .terminal import TerminalExecutor
from .workspace import WorkspaceInfo, WorkspaceManager

logger = logging.getLogger(__name__)

LLMCall = Callable[[str, str], Awaitable[str]]
_DEFAULT_PARALLELISM = 8
_DEFAULT_PROMPT_CHARS = 90_000


async def _default_llm_call(system: str, user: str) -> str:
    """Use light HTTP chat first; fall back to the existing provider adapter."""
    from .direct_chat import ProviderNotReachable, chat, resolve_endpoint

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    endpoint = resolve_endpoint()
    if endpoint is not None:
        return await chat(messages, endpoint=endpoint)

    def call() -> str:
        from .llm_provider import build_llm
        return str(build_llm().call(messages))

    try:
        return await asyncio.to_thread(call)
    except Exception as exc:
        raise ProviderNotReachable(str(exc)) from exc


class LocalCoordinatorRuntime:
    """One Main Coordinator with dynamic tools and private parallel specialists."""

    def __init__(
        self,
        *,
        workspace: WorkspaceInfo,
        bus: AgentEventBus,
        gate: ApprovalGate,
        ws_manager: Optional[WorkspaceManager] = None,
        terminal: Optional[TerminalExecutor] = None,
        llm_call: Optional[LLMCall] = None,
        cancelled: Optional[Callable[[], bool]] = None,
        memory: Optional[dict[str, Any]] = None,
        conversation_messages: Optional[list[dict[str, str]]] = None,
        workspace_memory_store: Optional[WorkspaceMemoryStore] = None,
    ) -> None:
        self.workspace = workspace
        self.bus = bus
        self.gate = gate
        self.ws = ws_manager or WorkspaceManager()
        self.terminal = terminal or TerminalExecutor()
        self.llm_call = llm_call or _default_llm_call
        self.cancelled = cancelled or (lambda: False)
        self.max_parallel = max(
            1,
            int(os.getenv("GITPILOT_COORDINATOR_PARALLELISM", str(_DEFAULT_PARALLELISM))),
        )
        self.prompt_chars = max(
            20_000,
            int(os.getenv("GITPILOT_COORDINATOR_PROMPT_CHARS", str(_DEFAULT_PROMPT_CHARS))),
        )
        self._deadline_seconds = max(
            0.0,
            float(os.getenv("GITPILOT_COORDINATOR_DEADLINE_SEC", "0") or 0),
        )
        self.memory = CoordinatorMemory.from_dict(memory)
        self.conversation_messages = list(conversation_messages or [])
        self.workspace_memory_store = workspace_memory_store or WorkspaceMemoryStore()
        self.workspace_memory_record: Optional[WorkspaceMemoryRecord] = None
        self._research: Optional[ResearchScheduler] = None
        self._actions: Optional[CoordinatorActions] = None
        self._action_scheduler = ActionScheduler()
        self.memory_snapshot: dict[str, Any] = self.memory.to_dict()

    async def run(self, user_message: str, *, mode: str = "auto") -> dict[str, Any]:
        # V106: hydrate cognitive state from the workspace itself, not merely from
        # the current chat session. A brand-new session can therefore reuse what
        # Main learned the last time this same working tree was opened.
        try:
            await self._hydrate_workspace_memory()
        except Exception:
            # Long-term memory is an accelerator, never a boot dependency. A
            # read-only home directory or transient lock failure must not make
            # GitPilot unable to work in the repo.
            logger.warning("Workspace memory unavailable; continuing with session state", exc_info=True)
            self.workspace_memory_record = None
        state = CoordinatorState(
            goal=user_message,
            memory=self.memory,
            conversation_messages=self.conversation_messages,
        )
        worker = ResearchWorker(
            workspace=self.workspace,
            ws_manager=self.ws,
            llm_call=self.llm_call,
            state=state,
            prompt_chars=self.prompt_chars,
            cancelled=self.cancelled,
            deadline_hit=lambda: self._deadline_hit(state),
        )
        self._research = ResearchScheduler(
            parallelism=self.max_parallel,
            runner=lambda job, job_id: worker.run(job, job_id),
        )

        async def harvest_bridge(
            current_state: CoordinatorState,
            wait: bool,
            job_ids: Optional[list[str]],
        ) -> None:
            await self._harvest_research(current_state, wait=wait, job_ids=job_ids)

        self._actions = CoordinatorActions(
            workspace=self.workspace,
            bus=self.bus,
            gate=self.gate,
            ws_manager=self.ws,
            terminal=self.terminal,
            memory=self.memory,
            research=self._research,
            harvest=harvest_bridge,
        )

        await self.bus.emit(evt.status_change("orienting", "Understanding the workspace…"))
        await self._ambient_probe(state)

        try:
            while True:
                await self._harvest_research(state, wait=False)
                if self.cancelled():
                    await self.bus.emit(evt.agent_error("Cancelled by user", recoverable=True))
                    return self._finish(state, "Cancelled", cancelled=True)
                if self._deadline_hit(state):
                    answer = (
                        "The coordinator reached the configured runtime safety deadline before "
                        "the repository context was sufficient. It is stopping without inventing "
                        "a conclusion."
                    )
                    await self._emit_final(answer)
                    return self._finish(state, answer, incomplete=True)

                state.turn += 1
                await self.bus.emit(evt.status_change("coordinating", f"Coordinator loop {state.turn}"))
                decision = await self._main_decision(state, mode=mode)
                apply_graph_update(state, decision.get("graph"), source="main")
                kind = str(decision.get("kind") or "continue").lower()

                if kind == "respond":
                    answer = str(decision.get("answer") or "").strip()
                    repo_claims = bool(decision.get("repo_claims"))
                    grounded = [str(x) for x in (decision.get("grounded_in") or [])]
                    valid_repo = state.evidence_ids(valid_for_repo_claim=True)
                    valid_grounding = [x for x in grounded if x in valid_repo]

                    # Research đang chạy có thể đảo conclusion: fan-in trước rồi bắt
                    # Main quyết định lại với findings mới, không paste report ra user.
                    if repo_claims and self._research and self._research.pending_ids():
                        await self._harvest_research(state, wait=True)
                        state.add_evidence(
                            "guard",
                            "coordinator",
                            "Collected active research before repository conclusion",
                            "Main must reassess the final answer after fan-in.",
                        )
                        continue
                    if repo_claims and not valid_grounding:
                        state.add_evidence(
                            "guard",
                            "coordinator",
                            "Rejected an ungrounded repository conclusion",
                            "Final repo claims must cite fresh/revision-compatible evidence, not only generic workspace metadata.",
                        )
                        continue
                    if not answer:
                        state.add_evidence("guard", "coordinator", "Rejected empty final answer")
                        continue

                    await self._emit_final(answer)
                    return self._finish(state, answer, grounded_in=valid_grounding)

                actions = decision.get("actions") or []
                if not isinstance(actions, list) or not actions:
                    state.add_evidence(
                        "guard",
                        "coordinator",
                        "Decision had no executable action",
                        json.dumps(decision, ensure_ascii=False)[:1500],
                    )
                    continue
                await self._execute_main_actions(state, actions, mode=mode)
        finally:
            if self._research is not None:
                await self._research.close(cancel_pending=True)
            # Persist even on cancellation/provider failure. Current-turn raw source
            # is compacted to digests; future turns still revalidate by revision.
            try:
                await self._persist_workspace_memory()
            except Exception:
                logger.warning("Failed to persist workspace coordinator memory", exc_info=True)
            self.memory_snapshot = self.memory.to_dict()

    async def _hydrate_workspace_memory(self) -> None:
        """Merge session state with durable workspace knowledge.

        Workspace memory is the broad reusable context; session memory may contain
        newer findings from this chat.  ``merge_from`` resolves sequential evidence
        id collisions rather than silently overwriting either side.
        """
        record = await asyncio.to_thread(self.workspace_memory_store.load, self.workspace)
        merged = record.memory.copy()
        merged.merge_from(self.memory)
        merged.compact()
        self.memory = merged
        self.workspace_memory_record = record
        self.memory_snapshot = self.memory.to_dict()

    async def _persist_workspace_memory(self) -> None:
        self.memory.compact()
        record = await asyncio.to_thread(
            self.workspace_memory_store.save, self.workspace, self.memory
        )
        # Store.save performs merge-on-save against the latest disk copy, so keep
        # that merged result as the session snapshot too.
        self.workspace_memory_record = record
        self.memory = record.memory
        self.memory_snapshot = self.memory.to_dict()

    async def _ambient_probe(self, state: CoordinatorState) -> None:
        """Refresh cheap repo identity; reuse file-map cache when revision is stable."""
        async def status_call():
            try:
                return await self.ws.status(self.workspace)
            except Exception as exc:
                return {"unavailable": str(exc)}

        async def head_call():
            try:
                log = await self.ws.log(self.workspace, count=1)
                return log[0].get("sha", "") if log else ""
            except Exception:
                return ""

        status, head = await asyncio.gather(status_call(), head_call())
        prelisted_files: Optional[list[str]] = None
        folder_fingerprint = ""
        git_available = not (isinstance(status, dict) and "unavailable" in status)
        if not git_available:
            # Folder-only workspaces have no HEAD/status to invalidate durable
            # knowledge. Build a cheap metadata fingerprint (path + size + mtime),
            # not a content hash. list_files is already capped/ignored by the
            # WorkspaceManager, so this remains an orientation probe rather than
            # a full repository read.
            try:
                prelisted_files = list(await self.ws.list_files(self.workspace, "."))

                def _folder_meta() -> list[tuple[str, int, int]]:
                    rows: list[tuple[str, int, int]] = []
                    root = self.workspace.path.resolve()
                    for rel in prelisted_files or []:
                        try:
                            stat = (root / rel).stat()
                            rows.append((rel, int(stat.st_size), int(stat.st_mtime_ns)))
                        except OSError:
                            rows.append((rel, -1, -1))
                    return rows

                rows = await asyncio.to_thread(_folder_meta)
                folder_fingerprint = hashlib.sha1(
                    stable_json(rows).encode("utf-8")
                ).hexdigest()[:16]
            except Exception:
                prelisted_files = None

        revision_basis = {
            "workspace": str(self.workspace.path),
            "branch": status.get("branch") if isinstance(status, dict) else "",
            "head": head,
            "modified": sorted((status.get("modified") or []) if isinstance(status, dict) else []),
            "added": sorted((status.get("added") or []) if isinstance(status, dict) else []),
            "deleted": sorted((status.get("deleted") or []) if isinstance(status, dict) else []),
            "untracked": sorted((status.get("untracked") or []) if isinstance(status, dict) else []),
            "folder_fingerprint": folder_fingerprint,
        }
        signature = hashlib.sha1(stable_json(revision_basis).encode("utf-8")).hexdigest()[:16]
        previous_signature = self.memory.workspace_signature
        state.workspace_revision = signature
        state.prior_revision_matches = bool(previous_signature and previous_signature == signature)

        if self.workspace_memory_record is not None and (
            self.workspace_memory_record.memory.evidence_digest
            or self.workspace_memory_record.memory.graph.claims
            or self.workspace_memory_record.memory.graph.frontiers
        ):
            state.add_evidence(
                "workspace_memory",
                self.workspace_memory_record.identity.key,
                "Loaded reusable long-term context for this workspace",
                json.dumps({
                    "persistent_evidence": len(self.workspace_memory_record.memory.evidence_digest),
                    "persistent_claims": len(self.workspace_memory_record.memory.graph.claims),
                    "persistent_frontiers": len(self.workspace_memory_record.memory.graph.frontiers),
                    "prior_revision": previous_signature or "unknown",
                }, ensure_ascii=False),
            )

        if previous_signature and previous_signature != signature:
            self.memory.graph.stale_claims()

        state.add_evidence(
            "workspace_status",
            "git",
            f"Workspace revision={signature}; branch={revision_basis.get('branch') or 'unknown'}",
            json.dumps({**revision_basis, "status": status}, ensure_ascii=False, indent=2)[:7000],
        )

        # Git/folder map chỉ enumerate lại khi chưa có cache hoặc revision đổi.
        if state.prior_revision_matches and self.memory.workspace_map:
            workspace_map = dict(self.memory.workspace_map)
            state.add_evidence(
                "workspace_map_cache",
                ".",
                f"Reused persistent workspace map ({workspace_map.get('file_count', '?')} files)",
                json.dumps(workspace_map, ensure_ascii=False),
            )
        else:
            try:
                files = prelisted_files if prelisted_files is not None else list(
                    await self.ws.list_files(self.workspace, ".")
                )
                top_dirs: list[str] = []
                seen: set[str] = set()
                for rel in files:
                    head_name = str(rel).replace("\\", "/").split("/", 1)[0]
                    if head_name and head_name not in seen:
                        seen.add(head_name)
                        top_dirs.append(head_name)
                workspace_map = {
                    "file_count": len(files),
                    "top_entries": top_dirs,
                }
                self.memory.workspace_map = workspace_map
                state.add_evidence(
                    "workspace_map",
                    ".",
                    f"Workspace contains {len(files)} files across {len(top_dirs)} top-level entries",
                    "Top-level entries: " + ", ".join(top_dirs[:160]),
                )
            except Exception as exc:
                state.add_evidence("workspace_map", ".", "Workspace file map unavailable", str(exc))

        # Update signature AFTER old evidence was classified fresh/stale.
        self.memory.workspace_signature = signature

    async def _main_decision(self, state: CoordinatorState, *, mode: str) -> dict[str, Any]:
        user = (
            state.compact_prompt(self.prompt_chars)
            + f"\n\nRUNTIME MODE: {mode}\n"
            + f"PHYSICAL RESEARCH WORKERS: {self.max_parallel} (logical job count is not capped)\n"
            + "Choose the next highest-information actions. Use action ids/depends_on for real dependencies."
        )
        raw = await self.llm_call(MAIN_SYSTEM, user)
        try:
            return extract_json(raw)
        except Exception as exc:
            state.add_evidence(
                "model_protocol_error",
                "main",
                f"Main returned invalid decision JSON: {type(exc).__name__}",
                (raw or "")[:2500],
            )
            return {"kind": "continue", "actions": [{"type": "git_status"}]}

    async def _execute_main_actions(self, state: CoordinatorState, actions: list[Any], *, mode: str) -> None:
        clean = [a for a in actions if isinstance(a, dict)]
        if self._actions is None:
            raise RuntimeError("coordinator action adapter is not active")

        def on_error(action: dict[str, Any], error: BaseException) -> None:
            state.add_evidence(
                "action_error",
                str(action.get("type") or "unknown"),
                f"Action failed: {type(error).__name__}",
                str(error),
            )

        await self._action_scheduler.execute(
            clean,
            run_readonly=lambda action: self._actions.readonly(state, action),
            run_barrier=lambda action: self._actions.barrier(state, action, mode=mode),
            on_error=on_error,
        )

    async def _harvest_research(
        self,
        state: CoordinatorState,
        *,
        wait: bool,
        job_ids: Optional[list[str]] = None,
    ) -> None:
        if self._research is None:
            return
        results = await self._research.collect(wait=wait, job_ids=job_ids)
        for job_id, result in results:
            label = state.active_research.pop(job_id, "research")
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    continue
                state.add_evidence("subagent_error", f"{label}/{job_id}", "Research branch failed", str(result))
                continue
            report: ResearchReport = result
            state.reports.append(report)
            report_evidence = state.add_evidence(
                "subagent_report",
                f"{report.label}/{report.job_id}",
                report.summary,
                json.dumps(
                    {
                        "claims": report.claims,
                        "evidence_ids": report.evidence_ids,
                        "new_frontiers": report.new_frontiers,
                        "files_read": report.files_read,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            for claim in report.claims:
                statement = str(claim.get("claim") or "").strip()
                if statement:
                    refs = [str(x) for x in (claim.get("evidence") or []) if str(x) in state.evidence_ids()]
                    self.memory.graph.add_claim(
                        statement,
                        confidence=float(claim.get("confidence") or 0.0),
                        evidence_ids=refs,
                        status="working",
                        source=f"subagent:{report.label}",
                    )
            for frontier in report.new_frontiers:
                self.memory.graph.add_frontier(
                    frontier,
                    source=f"subagent:{report.label}",
                    priority=0.6,
                    evidence_ids=[report_evidence.id],
                )

    def _deadline_hit(self, state: CoordinatorState) -> bool:
        return self._deadline_seconds > 0 and (time.monotonic() - state.started_at) >= self._deadline_seconds

    async def _emit_final(self, answer: str) -> None:
        await self.bus.emit(evt.status_change("responding", "Coordinator has enough context"))
        for offset in range(0, len(answer), 160):
            await self.bus.emit(evt.text_delta(answer[offset : offset + 160]))
        await self.bus.emit(evt.status_change("done", "Completed"))
        await self.bus.emit(evt.agent_done(summary=answer[:5000]))

    def _finish(
        self,
        state: CoordinatorState,
        answer: str,
        *,
        grounded_in: Optional[list[str]] = None,
        cancelled: bool = False,
        incomplete: bool = False,
    ) -> dict[str, Any]:
        grounded = grounded_in or []
        self.memory.remember_turn(state.goal, answer, grounded)
        self.memory_snapshot = state.export_memory()
        return {
            "summary": answer,
            "pipeline": "coordinator_loop_v4",
            "grounded_in": grounded,
            "cancelled": cancelled,
            "incomplete": incomplete,
            "metadata": {
                "turns": state.turn,
                "evidence_count": len(state.evidence),
                "subagent_reports": len(state.reports),
                "files_read": len(state.visited_files),
                "persistent_claims": len(self.memory.graph.claims),
                "persistent_frontiers": len(self.memory.graph.frontiers),
                "workspace_memory_key": (
                    self.workspace_memory_record.identity.key
                    if self.workspace_memory_record is not None else ""
                ),
            },
        }


__all__ = ["LocalCoordinatorRuntime"]
