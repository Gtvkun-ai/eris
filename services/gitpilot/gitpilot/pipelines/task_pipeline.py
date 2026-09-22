"""Task Pipeline — Central Orchestrator with dynamic subagent dispatch.

Architecture: one Orchestrator that runs an agentic loop.
The orchestrator decides what to investigate, spawns subagents as needed,
evaluates what they return, then decides: investigate more or plan now.

    Orchestrator.run():
        loop:
            think() → next action (READ / SEARCH / ASK / PLAN / DONE)
            if READ:   spawn Reader subagent for that target
            if SEARCH: spawn Searcher subagent for that query
            if ASK:    return clarification request to user
            if PLAN:   create implementation plan from accumulated context
            if DONE:   return answer (no code change needed)
        → return PlanResult

No hard file caps. No phase markers. Investigation depth is decided by
the orchestrator based on task complexity and context quality.

Safety valve: a token budget (not file count) prevents runaway loops.
When accumulated context > budget, orchestrator gets a "context full"
signal and must decide: plan with what it has, or ask user for scope reduction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Token budget as a soft signal to the orchestrator, not a hard file cap.
# When context exceeds this, orchestrator is informed — it still decides.
_CONTEXT_TOKEN_BUDGET = 32_000
_MAX_ORCHESTRATOR_TURNS = 12   # Safety valve against infinite loops only
_CHARS_PER_TOKEN = 4           # Rough estimate


# ---------------------------------------------------------------------------
# Shared context accumulator
# ---------------------------------------------------------------------------

@dataclass
class InvestigationContext:
    """All knowledge accumulated during the orchestrator's investigation loop."""

    goal: str
    repo: str
    owner: str
    branch: str

    # Accumulated file contents: {rel_path: content_str}
    files: dict[str, str] = field(default_factory=dict)
    # Cache AST metadata: {rel_path: {classes, functions, module_doc, ...}}
    ast_metadata: dict[str, dict] = field(default_factory=dict)
    # Free-form notes the orchestrator can write to itself
    notes: list[str] = field(default_factory=list)
    # What has already been investigated (avoid re-reading)
    investigated: set[str] = field(default_factory=set)
    # Turn counter
    turn: int = 0

    def add_file(self, path: str, content: str) -> None:
        self.files[path] = content
        self.investigated.add(path)

    def add_ast(self, path: str, meta: dict) -> None:
        self.ast_metadata[path] = meta
        self.investigated.add(f"ast:{path}")

    def token_estimate(self) -> int:
        total_chars = sum(len(c) for c in self.files.values())
        total_chars += sum(
            len(json.dumps(m)) for m in self.ast_metadata.values()
        )
        return total_chars // _CHARS_PER_TOKEN

    def is_over_budget(self) -> bool:
        return self.token_estimate() > _CONTEXT_TOKEN_BUDGET

    def summary_for_orchestrator(self) -> str:
        """Compact representation of what we know so far."""
        parts = [f"Goal: {self.goal}", f"Turn: {self.turn}"]

        if self.files:
            parts.append(f"\nFiles read ({len(self.files)}):")
            for p in list(self.files)[:20]:
                snippet = self.files[p][:150].replace("\n", " ")
                parts.append(f"  [{p}] {snippet}...")

        if self.ast_metadata:
            parts.append(f"\nAST metadata available for: {', '.join(list(self.ast_metadata)[:10])}")

        if self.notes:
            parts.append(f"\nNotes: {'; '.join(self.notes[-5:])}")

        budget_used = self.token_estimate()
        parts.append(
            f"\nContext budget: {budget_used}/{_CONTEXT_TOKEN_BUDGET} tokens"
            + (" [NEAR LIMIT]" if self.is_over_budget() else "")
        )

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Subagents (spawned on demand by orchestrator)
# ---------------------------------------------------------------------------

class ReaderSubagent:
    """Fetches file(s) or AST metadata for a given target."""

    def __init__(self, ctx: InvestigationContext, fetch_file_fn, cache_data: dict):
        self.ctx = ctx
        self.fetch_file_fn = fetch_file_fn
        self.cache_data = cache_data  # raw cache.json files section

    async def read_files(self, paths: list[str]) -> dict[str, str]:
        """Fetch actual file contents. Returns {path: content}."""
        fetched: dict[str, str] = {}
        if not self.fetch_file_fn:
            return fetched

        results = await asyncio.gather(
            *[
                self.fetch_file_fn(self.ctx.owner, self.ctx.repo, p, self.ctx.branch)
                for p in paths
                if p not in self.ctx.files
            ],
            return_exceptions=True,
        )
        for path, result in zip(paths, results):
            if isinstance(result, str):
                fetched[path] = result
                self.ctx.add_file(path, result)
                logger.debug("[reader] fetched %s (%d chars)", path, len(result))
            else:
                logger.debug("[reader] failed %s: %s", path, result)
        return fetched

    def read_ast(self, paths: list[str]) -> dict[str, dict]:
        """Load AST metadata from cache (instant, no network)."""
        result: dict[str, dict] = {}
        for path in paths:
            if path in self.cache_data:
                rec = self.cache_data[path]
                self.ctx.add_ast(path, rec)
                result[path] = rec
        return result

    def search_cache(self, keywords: list[str], top_n: int = 15) -> list[dict]:
        """Keyword search over cached AST metadata. Returns ranked file list."""
        kws = [k.lower() for k in keywords if len(k) > 2]
        scored: list[tuple[float, str, dict]] = []

        for rel, rec in self.cache_data.items():
            score = 0.0
            text = " ".join([
                rel,
                rec.get("module_doc", ""),
                " ".join(rec.get("classes", [])),
                " ".join(rec.get("functions", [])),
            ]).lower()
            for kw in kws:
                if kw in rel.lower():
                    score += 3.0
                score += min(text.count(kw) * 0.2, 2.0)
            if score > 0.3:
                scored.append((score, rel, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "path": rel,
                "score": round(s, 2),
                "language": rec.get("language", ""),
                "module_doc": rec.get("module_doc", ""),
                "classes": rec.get("classes", [])[:4],
                "functions": rec.get("functions", [])[:4],
                "skeleton": rec.get("skeleton", "")[:300],
            }
            for s, rel, rec in scored[:top_n]
        ]


# ---------------------------------------------------------------------------
# Analyst Subagent — reads a module's files and calls LLM to distill summary
# ---------------------------------------------------------------------------

_ANALYST_SYSTEM = """\
You are an Analyst subagent. Your job: read the provided code files for a specific module
and produce a CONCISE summary (under 400 words) focused on what's relevant to the task.

Cover:
- What this module does
- Key classes/functions that relate to the task
- Any obvious issues or patterns the orchestrator should know about

Do NOT list every function. Focus on what matters for the task.
Reply in the SAME language as the task description.
"""


class AnalystSubagent:
    """Reads files in one module and distills a focused LLM summary.

    Multiple AnalystSubagents run in parallel (asyncio.gather) when the
    orchestrator requests multi-module analysis. Each makes exactly 1 LLM call.
    """

    def __init__(
        self,
        module: str,
        goal: str,
        *,
        reader: "ReaderSubagent",
        llm_call,
        max_files: int = 6,
    ):
        self.module = module
        self.goal = goal
        self.reader = reader
        self.llm_call = llm_call
        self.max_files = max_files

    async def run(self) -> dict:
        """Read top files in module, call LLM to summarize. Returns analysis dict."""
        t0 = time.perf_counter()

        # Find top relevant files in this module from cache
        hits = self.reader.search_cache(
            [w for w in self.goal.lower().split() if len(w) > 3],
            top_n=self.max_files * 3,
        )
        module_files = [
            h["path"] for h in hits
            if h["path"].startswith(self.module.rstrip("/") + "/")
        ][:self.max_files]

        if not module_files:
            # Module name doesn't appear in paths as prefix — use score fallback
            module_files = [h["path"] for h in hits[:self.max_files]]

        # Fetch full file content
        fetched = await self.reader.read_files(module_files)

        # Build context for LLM
        file_sections = "\n\n".join(
            f"### `{path}`\n```\n{content[:2500]}\n```"
            for path, content in fetched.items()
        ) or "(no files fetched — using cache metadata only)"

        if not fetched:
            # Fallback: AST metadata only
            ast = self.reader.read_ast(module_files[:4])
            file_sections = "\n".join(
                f"- `{p}`: classes={m.get('classes', [])[:3]} "
                f"functions={m.get('functions', [])[:3]}"
                for p, m in ast.items()
            )

        user_msg = (
            f"Task: {self.goal}\n\n"
            f"Module: `{self.module}/`\n\n"
            f"## Files\n\n{file_sections}"
        )

        if self.llm_call:
            try:
                summary = await self.llm_call(_ANALYST_SYSTEM, user_msg)
            except Exception as exc:
                summary = f"[analyst error: {exc}]"
        else:
            # No LLM — produce structured cache summary
            summary = (
                f"Module `{self.module}/`: {len(fetched)} files read.\n"
                + "\n".join(f"  - `{p}`" for p in fetched)
            )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "[analyst:%s] done in %dms — %d files, llm=%s",
            self.module, elapsed_ms, len(fetched), self.llm_call is not None,
        )

        return {
            "module": self.module,
            "files_read": list(fetched.keys()),
            "summary": summary,
            "latency_ms": elapsed_ms,
        }


async def run_analysts_parallel(
    modules: list[str],
    goal: str,
    *,
    reader: "ReaderSubagent",
    llm_call,
    max_files_per_module: int = 6,
) -> list[dict]:
    """Spawn one AnalystSubagent per module, all running in parallel.

    Returns list of analysis dicts sorted by module name.
    Each analyst makes exactly 1 LLM call concurrently with the others.
    """
    analysts = [
        AnalystSubagent(
            module=mod,
            goal=goal,
            reader=reader,
            llm_call=llm_call,
            max_files=max_files_per_module,
        )
        for mod in modules
    ]

    logger.info(
        "[analysts] spawning %d parallel analysts for modules: %s",
        len(analysts), modules,
    )

    results = await asyncio.gather(
        *[a.run() for a in analysts],
        return_exceptions=True,
    )

    out = []
    for mod, result in zip(modules, results):
        if isinstance(result, dict):
            out.append(result)
        else:
            logger.warning("[analyst:%s] failed: %s", mod, result)
            out.append({"module": mod, "files_read": [], "summary": f"[failed: {result}]", "latency_ms": 0})

    return out


# ---------------------------------------------------------------------------
# Orchestrator decision
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorDecision:
    """What the orchestrator wants to do next."""

    action: str  # "read_files" | "read_ast" | "search" | "analyze_modules" | "plan" | "done" | "ask"

    # For read_files / read_ast
    paths: list[str] = field(default_factory=list)
    # For search
    keywords: list[str] = field(default_factory=list)
    # For analyze_modules — list of top-level module names to analyze in parallel
    modules: list[str] = field(default_factory=list)
    # For ask
    question: str = ""
    # For plan / done — the orchestrator's answer or plan
    answer: str = ""
    # Orchestrator's reasoning (logged, not shown to user)
    reasoning: str = ""


_ORCHESTRATOR_SYSTEM = """\
You are the central orchestrator for GitPilot, managing an investigation of a code repository.

Your job: decide what to do NEXT based on:
1. The user's goal
2. What you have already read (files, AST data, search results, analyst summaries)
3. Whether you have enough context to answer or plan

You control subagents by choosing one of these actions:

  search           — keyword search across all cached files (use to find relevant files)
  read_ast         — get AST metadata (classes, functions, doc) for specific files (fast, no network)
  read_files       — fetch full content of specific files (use when you need actual code)
  analyze_modules  — spawn PARALLEL Analyst subagents for a list of modules
                     each analyst reads files in its module and calls LLM to distill a focused summary
                     use this when you need deep understanding of multiple modules at once
  plan             — you have enough context, create an implementation plan
  done             — the goal is answered without code changes needed
  ask              — you need user clarification before proceeding

Respond with ONLY a JSON object:
{
  "action": "search|read_files|read_ast|analyze_modules|plan|done|ask",
  "reasoning": "why you chose this",

  // For read_files or read_ast:
  "paths": ["path/to/file1.py", "path/to/file2.py"],

  // For search:
  "keywords": ["keyword1", "keyword2"],

  // For analyze_modules (PARALLEL — all run at the same time):
  "modules": ["src/runtime", "src/cortex", "services/gitpilot"],

  // For plan:
  "steps": [
    {"action": "EDIT|CREATE|DELETE|READ", "file": "path", "description": "what", "reason": "why"}
  ],

  // For done:
  "answer": "the complete answer",

  // For ask:
  "question": "what you need to know"
}

Rules:
- Be strategic. Don't read the same file twice.
- Start with search or read_ast (cheap, no LLM) before analyze_modules (costs N LLM calls).
- Use analyze_modules when the task clearly spans multiple modules and you need deep understanding.
- When you have enough context to answer confidently: plan or done.
- Don't over-investigate. Simple tasks need few files.
- LANGUAGE: always reply ("answer", "reasoning", step descriptions) in the SAME language as the user's goal.
  If the goal is in Vietnamese → respond in Vietnamese. If English → English. Never mix.
"""


# ---------------------------------------------------------------------------
# Central Orchestrator
# ---------------------------------------------------------------------------

class TaskOrchestrator:
    """Central agent that investigates and plans autonomously.

    The orchestrator runs an agentic loop:
        think → act → observe → think → ...

    Investigation depth is decided by the orchestrator, not by hard caps.
    A token budget acts as a soft signal ("context getting large"), not a block.
    """

    def __init__(
        self,
        goal: str,
        *,
        owner: str,
        repo: str,
        branch: str = "HEAD",
        llm_call=None,
        fetch_file_fn=None,
        cache_data: dict | None = None,
    ):
        self.ctx = InvestigationContext(
            goal=goal, repo=repo, owner=owner, branch=branch,
        )
        self.llm_call = llm_call
        self.reader = ReaderSubagent(self.ctx, fetch_file_fn, cache_data or {})
        self._t_start = time.perf_counter()

    async def think(self) -> OrchestratorDecision:
        """Ask the LLM orchestrator what to do next."""
        if self.llm_call is None:
            # No LLM: heuristic 3-step — search → read_ast → plan
            # Note: ctx.turn is already incremented before think() is called
            if self.ctx.turn == 1:
                # Step 1: keyword search to find relevant files
                norm = self.ctx.goal.lower()
                kws = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
                return OrchestratorDecision(
                    action="search",
                    keywords=kws,
                    reasoning="heuristic step 1: search by keywords",
                )
            elif self.ctx.turn == 2 and self.reader.cache_data:
                # Step 2: read AST for files found in search (notes contain result)
                top = self.reader.search_cache(
                    [w for w in self.ctx.goal.lower().split() if len(w) > 3], top_n=8
                )
                # Filter out already-read files
                unread = [
                    f["path"] for f in top
                    if f"ast:{f['path']}" not in self.ctx.investigated
                ][:6]
                if unread:
                    return OrchestratorDecision(
                        action="read_ast",
                        paths=unread,
                        reasoning=f"heuristic step 2: read AST for {len(unread)} relevant files",
                    )
                return OrchestratorDecision(
                    action="plan",
                    reasoning="heuristic: no unread files found, going to plan",
                )
            else:
                return OrchestratorDecision(
                    action="plan",
                    reasoning="heuristic step 3: plan with accumulated context",
                )

        user_msg = self.ctx.summary_for_orchestrator()

        if self.ctx.is_over_budget():
            user_msg += (
                "\n\n⚠️ Context budget exceeded. You MUST choose 'plan' or 'done' now "
                "— do not request more files."
            )

        try:
            raw = await self.llm_call(_ORCHESTRATOR_SYSTEM, user_msg)
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                raise ValueError("no JSON in orchestrator response")
            parsed = json.loads(json_match.group())
            action = parsed.get("action", "plan")
            return OrchestratorDecision(
                action=action,
                paths=parsed.get("paths", []),
                keywords=parsed.get("keywords", []),
                question=parsed.get("question", ""),
                answer=parsed.get("answer", ""),
                reasoning=parsed.get("reasoning", ""),
            )
        except Exception as exc:
            logger.warning("[orchestrator] think() failed: %s", exc)
            return OrchestratorDecision(
                action="plan",
                reasoning=f"LLM failed ({exc}) — defaulting to plan",
            )

    async def act(self, decision: OrchestratorDecision) -> str:
        """Execute the orchestrator's decision. Returns observation string."""
        action = decision.action

        if action == "search":
            results = self.reader.search_cache(decision.keywords)
            self.ctx.notes.append(
                f"Search '{' '.join(decision.keywords)}' → {len(results)} results: "
                + ", ".join(r["path"] for r in results[:5])
            )
            return (
                f"Search results for {decision.keywords}:\n"
                + "\n".join(
                    f"  [{r['score']:.1f}] {r['path']} — {r['module_doc'] or r['functions'][:2]}"
                    for r in results[:10]
                )
            )

        elif action == "read_ast":
            meta = self.reader.read_ast(decision.paths)
            self.ctx.notes.append(
                f"Read AST for: {', '.join(meta.keys())}"
            )
            return (
                f"AST metadata for {len(meta)} files:\n"
                + "\n".join(
                    f"  {p}: classes={m.get('classes', [])[:3]} "
                    f"functions={m.get('functions', [])[:3]}"
                    for p, m in meta.items()
                )
            )

        elif action == "read_files":
            fetched = await self.reader.read_files(decision.paths)
            self.ctx.notes.append(
                f"Read {len(fetched)} files: {', '.join(fetched.keys())}"
            )
            return f"Fetched {len(fetched)} files: {', '.join(fetched.keys())}"

        elif action == "analyze_modules":
            # Spawn parallel Analyst subagents — N modules × 1 LLM call each
            analyses = await run_analysts_parallel(
                decision.modules,
                self.ctx.goal,
                reader=self.reader,
                llm_call=self.llm_call,
            )
            # Inject summaries into context
            for analysis in analyses:
                summary_key = f"analyst:{analysis['module']}"
                self.ctx.files[summary_key] = analysis["summary"]
                self.ctx.investigated.add(summary_key)
            total_files = sum(len(a["files_read"]) for a in analyses)
            max_ms = max((a["latency_ms"] for a in analyses), default=0)
            self.ctx.notes.append(
                f"analyze_modules parallel → {len(analyses)} analysts, "
                f"{total_files} files, wall-clock {max_ms}ms"
            )
            return (
                f"Parallel analysis complete: {len(analyses)} modules, "
                f"{total_files} total files read in {max_ms}ms wall-clock time.\n"
                + "\n".join(
                    f"  [{a['module']}] {len(a['files_read'])} files: {a['summary'][:150]}..."
                    for a in analyses
                )
            )

        elif action in ("plan", "done", "ask"):
            return f"Terminal action: {action}"

        return f"Unknown action: {action}"

    async def run(self) -> dict:
        """Run the agentic loop until the orchestrator decides to stop."""
        logger.info("[orchestrator] starting for goal: %r", self.ctx.goal)

        for _ in range(_MAX_ORCHESTRATOR_TURNS):
            self.ctx.turn += 1

            # Think
            decision = await self.think()
            logger.info(
                "[orchestrator] turn=%d action=%s reasoning=%r",
                self.ctx.turn, decision.action, decision.reasoning[:80],
            )

            # Terminal actions — stop the loop
            if decision.action == "done":
                return self._result(
                    summary=decision.answer or "Đã trả lời.",
                    steps=[],
                )

            if decision.action == "ask":
                return self._result(
                    summary=f"❓ {decision.question}",
                    steps=[],
                    needs_clarification=True,
                )

            if decision.action == "plan":
                steps = await self._build_plan(decision)
                summary = self._plan_summary(steps, decision)
                return self._result(summary=summary, steps=steps)

            # Non-terminal — act and observe
            observation = await self.act(decision)
            logger.debug("[orchestrator] observation: %s", observation[:200])

        # Safety valve: max turns exceeded
        logger.warning("[orchestrator] max turns reached, forcing plan")
        steps = await self._build_plan(OrchestratorDecision(action="plan"))
        return self._result(
            summary=f"⚠️ Investigation capped at {_MAX_ORCHESTRATOR_TURNS} turns.\n"
                    + self._plan_summary(steps, None),
            steps=steps,
        )

    async def _build_plan(self, decision: OrchestratorDecision) -> list[dict]:
        """Build implementation steps from accumulated context + LLM."""
        # If the orchestrator already provided steps in its decision, use them
        if hasattr(decision, "steps") and decision.steps:
            return decision.steps

        # Otherwise ask LLM to generate steps from accumulated context
        if self.llm_call is None or not self.ctx.files:
            return []

        context_dump = "\n\n".join(
            f"### `{p}`\n```\n{c[:3000]}\n```"
            for p, c in list(self.ctx.files.items())[:8]
        )
        system = (
            "You are a senior engineer. Create a minimal, targeted implementation plan.\n"
            "Output ONLY JSON: {\"steps\": [{\"action\": \"EDIT|CREATE|DELETE\", "
            "\"file\": \"path\", \"description\": \"what\", \"reason\": \"why\"}]}\n"
            "Max 6 steps.\n\n## Code Context\n\n" + context_dump
        )
        try:
            raw = await self.llm_call(system, f"Task: {self.ctx.goal}")
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group()).get("steps", [])[:6]
        except Exception as exc:
            logger.warning("[orchestrator] plan build failed: %s", exc)
        return []

    def _plan_summary(self, steps: list[dict], decision) -> str:
        elapsed = int((time.perf_counter() - self._t_start) * 1000)
        lines = [f"## Plan — {self.ctx.goal}\n"]
        if steps:
            for i, s in enumerate(steps, 1):
                lines.append(
                    f"{i}. **{s.get('action', '?')}** `{s.get('file', '?')}` — {s.get('description', '')}"
                )
        else:
            lines.append("_No code changes required._")
        lines.append(
            f"\n_Investigation: {self.ctx.turn} turns, "
            f"{len(self.ctx.files)} files read, "
            f"~{self.ctx.token_estimate()} tokens, "
            f"{elapsed}ms_"
        )
        return "\n".join(lines)

    def _result(self, summary: str, steps: list[dict], needs_clarification: bool = False) -> dict:
        elapsed = int((time.perf_counter() - self._t_start) * 1000)
        return {
            "goal": self.ctx.goal,
            "summary": summary,
            "steps": steps,
            "metadata": {
                "pipeline": "task_orchestrator",
                "latency_ms": elapsed,
                "turns": self.ctx.turn,
                "files_read": len(self.ctx.files),
                "ast_read": len(self.ctx.ast_metadata),
                "tokens_used": self.ctx.token_estimate(),
                "needs_clarification": needs_clarification,
            },
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def task_pipeline(
    goal: str,
    *,
    owner: str,
    repo: str,
    branch: str = "HEAD",
    keywords: list[str] | None = None,
    fetch_file_fn=None,
    llm_call=None,
    fallback_fn=None,
) -> dict:
    """Entry point: run the central TaskOrchestrator.

    Falls back to ``fallback_fn`` when no rich cache is available.

    Args:
        goal:          User's code task.
        owner/repo:    Repository coordinates.
        branch:        Branch/ref.
        keywords:      Pre-extracted keywords from gatekeeper (optional hint).
        fetch_file_fn: Async ``(owner, repo, path, branch) -> str``.
        llm_call:      Async ``(system, user) -> str``.
        fallback_fn:   Async fallback (old generate_plan) when no cache.
    """
    # Load cache
    cache_data = _load_cache_files(repo)

    if cache_data is None:
        logger.info("[task_pipeline] no cache for %s, falling back", repo)
        if fallback_fn:
            return await fallback_fn(goal)
        return {
            "goal": goal,
            "summary": (
                f"Chưa có index cho `{repo}`. "
                "Chạy `python tools/repo_context/cli.py cache --build` để build cache."
            ),
            "steps": [],
            "metadata": {"pipeline": "no_cache"},
        }

    orchestrator = TaskOrchestrator(
        goal=goal,
        owner=owner,
        repo=repo,
        branch=branch,
        llm_call=llm_call,
        fetch_file_fn=fetch_file_fn,
        cache_data=cache_data,
    )

    try:
        return await orchestrator.run()
    except Exception as exc:
        logger.exception("[task_pipeline] orchestrator crashed: %s", exc)
        if fallback_fn:
            return await fallback_fn(goal)
        raise


def _load_cache_files(repo: str) -> dict | None:
    """Load the files section of the rich cache. Returns None if not found."""
    try:
        cache_root = Path.home() / ".gitpilot" / "repo_cache"
        if not cache_root.exists():
            return None
        safe_repo = repo.replace(".", "-")
        for entry in cache_root.iterdir():
            if not entry.is_dir():
                continue
            suffix = entry.name.split("_", 1)[-1] if "_" in entry.name else ""
            if suffix in (safe_repo, repo) or entry.name.endswith(f"_{repo}"):
                cache_file = entry / "cache.json"
                if cache_file.exists():
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    if data.get("schema_version") == 3:
                        return data.get("files", {})
    except Exception as exc:
        logger.debug("[task_pipeline] cache load failed: %s", exc)
    return None


__all__ = ["task_pipeline", "TaskOrchestrator", "InvestigationContext"]
