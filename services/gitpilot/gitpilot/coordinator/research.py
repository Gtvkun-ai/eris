"""Private read-only research worker used by the coordinator scheduler."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from ..workspace import WorkspaceInfo, WorkspaceManager
from .protocol import SUBAGENT_SYSTEM, extract_json
from .state import CoordinatorState, Evidence, ResearchJob, ResearchReport

LLMCall = Callable[[str, str], Awaitable[str]]


class ResearchWorker:
    """Open-ended specialist loop. Main/scheduler own lifecycle and concurrency."""

    def __init__(
        self,
        *,
        workspace: WorkspaceInfo,
        ws_manager: WorkspaceManager,
        llm_call: LLMCall,
        state: CoordinatorState,
        prompt_chars: int,
        cancelled: Callable[[], bool],
        deadline_hit: Callable[[], bool],
    ) -> None:
        self.workspace = workspace
        self.ws = ws_manager
        self.llm_call = llm_call
        self.state = state
        self.prompt_chars = prompt_chars
        self.cancelled = cancelled
        self.deadline_hit = deadline_hit

    async def run(self, job: ResearchJob, job_id: str) -> ResearchReport:
        local_evidence: list[Evidence] = []
        visited: set[str] = set()

        def add(kind: str, source: str, summary: str, detail: str = "") -> Evidence:
            item = self.state.add_evidence(kind, source, summary, detail)
            local_evidence.append(item)
            return item

        # Hints chỉ là điểm xuất phát; specialist vẫn tự mở rộng frontier nếu cần.
        if job.search_terms:
            search_results = await asyncio.gather(
                *[self.ws.search_files(self.workspace, term, ".") for term in job.search_terms],
                return_exceptions=True,
            )
            for term, result in zip(job.search_terms, search_results):
                if isinstance(result, BaseException):
                    add("subagent_search_error", term, "Search failed", str(result))
                else:
                    detail = "\n".join(
                        f"{m.get('file')}:{m.get('line')}: {m.get('content')}" for m in result
                    )
                    add("subagent_search", term, f"{len(result)} match(es)", detail[:20_000])

        if job.hint_paths:
            reads = await asyncio.gather(
                *[self.ws.read_file(self.workspace, p) for p in job.hint_paths],
                return_exceptions=True,
            )
            for path, result in zip(job.hint_paths, reads):
                if isinstance(result, BaseException):
                    add("subagent_file_error", path, "Read failed", str(result))
                else:
                    visited.add(path)
                    add("subagent_file", path, f"Read {len(result)} chars", result)

        while True:
            if self.cancelled() or self.deadline_hit():
                return ResearchReport(
                    job_id=job_id,
                    label=job.label,
                    summary="Research stopped by cancellation/runtime safety boundary before completion.",
                    evidence_ids=[e.id for e in local_evidence],
                    files_read=sorted(visited),
                )

            packed: list[str] = []
            packed_chars = 0
            for evidence in reversed(local_evidence):
                block = evidence.prompt_line(max_detail=1800)
                if packed and packed_chars + len(block) > self.prompt_chars // 2:
                    break
                packed.append(block)
                packed_chars += len(block)
            state_text = "\n\n".join(reversed(packed))
            prompt = (
                f"JOB LABEL: {job.label}\nJOB GOAL: {job.goal}\n"
                f"FILES ALREADY READ: {sorted(visited)}\n\n"
                f"EVIDENCE:\n{state_text or '(none yet)'}\n\n"
                "Decide whether to investigate more or report to Main."
            )
            raw = await self.llm_call(SUBAGENT_SYSTEM, prompt)
            try:
                decision = extract_json(raw)
            except Exception as exc:
                add("subagent_protocol_error", job.label, "Invalid subagent JSON", (raw or "")[:1800])
                return ResearchReport(
                    job_id=job_id,
                    label=job.label,
                    summary=f"Subagent protocol failed: {exc}",
                    evidence_ids=[e.id for e in local_evidence],
                    files_read=sorted(visited),
                )

            if str(decision.get("kind") or "").lower() == "report":
                claims = decision.get("claims") or []
                if not isinstance(claims, list):
                    claims = []
                valid_ids = {e.id for e in local_evidence}
                cleaned_claims: list[dict] = []
                for claim in claims:
                    if not isinstance(claim, dict):
                        continue
                    refs = [str(x) for x in (claim.get("evidence") or []) if str(x) in valid_ids]
                    cleaned = dict(claim)
                    cleaned["evidence"] = refs
                    cleaned_claims.append(cleaned)
                return ResearchReport(
                    job_id=job_id,
                    label=job.label,
                    summary=str(decision.get("summary") or "Research complete."),
                    claims=cleaned_claims,
                    evidence_ids=[e.id for e in local_evidence],
                    new_frontiers=[str(x) for x in (decision.get("new_frontiers") or []) if str(x).strip()],
                    files_read=sorted(visited),
                )

            actions = decision.get("actions") or []
            if not isinstance(actions, list) or not actions:
                add("subagent_guard", job.label, "No executable read-only action in decision")
                continue

            async def one(act: dict) -> None:
                typ = str(act.get("type") or "").lower()
                if typ == "search":
                    pattern = str(act.get("pattern") or "").strip()
                    path = str(act.get("path") or ".")
                    if not pattern:
                        return
                    matches = await self.ws.search_files(self.workspace, pattern, path)
                    detail = "\n".join(
                        f"{m.get('file')}:{m.get('line')}: {m.get('content')}" for m in matches
                    )
                    add("subagent_search", f"{path} :: {pattern}", f"{len(matches)} match(es)", detail[:20_000])
                elif typ == "read":
                    paths = [str(p) for p in (act.get("paths") or []) if str(p).strip()]
                    reads = await asyncio.gather(
                        *[self.ws.read_file(self.workspace, p) for p in paths],
                        return_exceptions=True,
                    )
                    for path, result in zip(paths, reads):
                        if isinstance(result, BaseException):
                            add("subagent_file_error", path, "Read failed", str(result))
                        else:
                            visited.add(path)
                            add("subagent_file", path, f"Read {len(result)} chars", result)
                elif typ == "git_status":
                    status = await self.ws.status(self.workspace)
                    add("subagent_git_status", "git", "Git status captured", json.dumps(status, ensure_ascii=False, indent=2))
                elif typ == "git_diff":
                    diff = await self.ws.diff(self.workspace, staged=bool(act.get("staged")))
                    add("subagent_git_diff", "git", f"Diff captured ({len(diff)} chars)", diff)
                else:
                    add("subagent_guard", typ or "unknown", "Blocked non-read-only subagent action")

            await asyncio.gather(
                *[one(a) for a in actions if isinstance(a, dict)],
                return_exceptions=False,
            )
