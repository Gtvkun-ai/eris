"""Info Pipeline — targeted question-answering without full repo reads.

Handles "info" route from the Gatekeeper:
    - "explain how X works"
    - "what is Y"
    - "tai sao Z crash"
    - "how does dialog system work"

Strategy:
    1. Query rich cache (tools/repo_context/) with goal keywords
       → top-N relevant files with AST signatures (instant, offline)
    2. Fetch ONLY those files from GitHub API (targeted, not full tree)
    3. Single LLM call: "Given these files, answer the question"

Target latency: < 8 seconds
Repo reads:     5-10 files max (not entire tree)
Agents:         0 (direct LLM call, no CrewAI)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Max files to fetch for context (keep prompt manageable)
_MAX_FILES_TO_FETCH = 8
# Max chars per file content to include in prompt
_MAX_FILE_CHARS = 3000
# Max total context chars sent to LLM
_MAX_TOTAL_CONTEXT_CHARS = 20_000


# ---------------------------------------------------------------------------
# Cache query helpers
# ---------------------------------------------------------------------------

def _query_rich_cache(repo: str, keywords: list[str], top_n: int = 10) -> list[dict]:
    """Query the local AST cache for files relevant to the given keywords.

    Returns a list of dicts: [{rel_path, language, module_doc, classes,
    functions, skeleton, size, score}] sorted by relevance descending.
    """
    try:
        cache_root = Path.home() / ".gitpilot" / "repo_cache"
        if not cache_root.exists():
            return []

        safe_repo = repo.replace(".", "-")
        cache_file: Optional[Path] = None
        for entry in cache_root.iterdir():
            if not entry.is_dir():
                continue
            suffix = entry.name.split("_", 1)[-1] if "_" in entry.name else ""
            if suffix in (safe_repo, repo) or entry.name.endswith(f"_{repo}"):
                candidate = entry / "cache.json"
                if candidate.exists():
                    cache_file = candidate
                    break

        if cache_file is None:
            return []

        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("schema_version") != 3:
            return []

        files_data = data.get("files", {})
        if not files_data:
            return []

        # Score each file by keyword relevance
        kws = [k.lower() for k in keywords if len(k) > 2]
        scored: list[tuple[float, str, dict]] = []

        for rel, rec in files_data.items():
            score = 0.0
            text_blob = " ".join([
                rel,
                rec.get("module_doc", ""),
                " ".join(rec.get("classes", [])),
                " ".join(rec.get("functions", [])),
                rec.get("skeleton", "")[:500],
            ]).lower()

            for kw in kws:
                if kw in rel.lower():
                    score += 3.0
                if any(kw in c.lower() for c in rec.get("classes", [])):
                    score += 2.5
                if any(kw in f.lower() for f in rec.get("functions", [])):
                    score += 2.0
                score += min(text_blob.count(kw) * 0.15, 1.5)

            if score > 0.3:
                scored.append((score, rel, rec))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, rel, rec in scored[:top_n]:
            results.append({
                "path": rel,
                "language": rec.get("language", ""),
                "module_doc": rec.get("module_doc", ""),
                "classes": rec.get("classes", [])[:6],
                "functions": rec.get("functions", [])[:6],
                "skeleton": rec.get("skeleton", "")[:800],
                "size": rec.get("size", 0),
                "score": round(score, 2),
            })

        logger.info(
            "[info_pipeline] cache hit: %d relevant files for keywords=%r",
            len(results), keywords[:4],
        )
        return results

    except Exception as exc:
        logger.debug("[info_pipeline] cache query failed: %s", exc)
        return []


def _build_context_prompt(
    goal: str,
    relevant_files: list[dict],
    fetched_contents: dict[str, str],
) -> str:
    """Build the context section of the LLM prompt."""
    parts: list[str] = []

    # Files with full content (fetched from GitHub)
    for path, content in fetched_contents.items():
        lang = next(
            (f["language"] for f in relevant_files if f["path"] == path), ""
        )
        snippet = content[:_MAX_FILE_CHARS]
        if len(content) > _MAX_FILE_CHARS:
            snippet += f"\n... [truncated, {len(content) - _MAX_FILE_CHARS} more chars]"
        parts.append(f"### `{path}` [{lang}]\n```\n{snippet}\n```")

    # Files with only cache metadata (no full content fetched)
    cache_only = [f for f in relevant_files if f["path"] not in fetched_contents]
    if cache_only:
        parts.append("### Additional relevant files (AST signatures only)")
        for f in cache_only[:4]:
            doc = f["module_doc"]
            classes = ", ".join(f["classes"][:4]) if f["classes"] else ""
            funcs = ", ".join(f["functions"][:4]) if f["functions"] else ""
            skel = f["skeleton"][:300] if f["skeleton"] else ""
            line = f"**`{f['path']}`**"
            if doc:
                line += f" — {doc}"
            if classes:
                line += f"\n  Classes: `{classes}`"
            if funcs:
                line += f"\n  Functions: `{funcs}`"
            if skel:
                line += f"\n```\n{skel[:200]}\n```"
            parts.append(line)

    total = "\n\n".join(parts)
    # Hard cap
    if len(total) > _MAX_TOTAL_CONTEXT_CHARS:
        total = total[:_MAX_TOTAL_CONTEXT_CHARS] + "\n\n... [context truncated]"
    return total


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def info_pipeline(
    goal: str,
    *,
    owner: str,
    repo: str,
    branch: str = "HEAD",
    keywords: list[str] | None = None,
    fetch_file_fn=None,
    llm_call=None,
) -> dict:
    """Answer an informational question with targeted file reads.

    Args:
        goal:          The user's question.
        owner/repo:    Repository coordinates.
        branch:        Branch/ref to fetch files from.
        keywords:      Pre-extracted keywords from gatekeeper (optional).
        fetch_file_fn: Async ``(owner, repo, path, branch) -> str`` to fetch
                       file content from GitHub.  When None, uses cache only.
        llm_call:      Async ``(system, user) -> str`` for the answer call.
                       When None, returns structured cache summary instead.

    Returns:
        PlanResult-compatible dict with ``summary`` (the answer) and
        ``steps=[]`` (no code changes).
    """
    t_start = time.perf_counter()

    # Extract keywords from goal if not provided
    if not keywords:
        norm = re.sub(r"[^\w\s]", " ", goal.lower())
        keywords = [w for w in norm.split() if len(w) > 3][:10]

    # Step 1: Query rich cache
    relevant_files = _query_rich_cache(repo, keywords, top_n=_MAX_FILES_TO_FETCH + 4)

    # Step 2: Fetch actual file contents for top-N files
    fetched_contents: dict[str, str] = {}
    if fetch_file_fn and relevant_files:
        paths_to_fetch = [f["path"] for f in relevant_files[:_MAX_FILES_TO_FETCH]]
        fetch_tasks = [
            fetch_file_fn(owner, repo, path, branch)
            for path in paths_to_fetch
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for path, result in zip(paths_to_fetch, results):
            if isinstance(result, str):
                fetched_contents[path] = result
            else:
                logger.debug("[info_pipeline] fetch failed for %s: %s", path, result)

    t_fetched = time.perf_counter()
    logger.info(
        "[info_pipeline] fetched %d/%d files in %.1fs",
        len(fetched_contents), len(relevant_files), t_fetched - t_start,
    )

    # Step 3: Build context and call LLM
    if not relevant_files:
        # No cache → cannot answer with confidence
        summary = (
            f"Tôi chưa có index cho repo `{repo}`. "
            f"Vui lòng chạy: `python tools/repo_context/cli.py --repo <path> cache --build` "
            f"để build cache, sau đó hỏi lại."
        )
        return _wrap(goal, summary, t_start, files_read=0, from_cache=False)

    context = _build_context_prompt(goal, relevant_files, fetched_contents)

    if llm_call is None:
        # No LLM — return structured cache summary
        file_list = "\n".join(
            f"- `{f['path']}` (score={f['score']}) — {f['module_doc'] or 'no doc'}"
            for f in relevant_files[:6]
        )
        summary = (
            f"Các file liên quan nhất đến câu hỏi của bạn:\n\n{file_list}\n\n"
            f"_(LLM không khả dụng — đây là cache lookup result)_"
        )
        return _wrap(goal, summary, t_start, files_read=len(fetched_contents), from_cache=True)

    system = (
        "You are GitPilot, a coding assistant. "
        "Answer the user's question based ONLY on the provided code context. "
        "Reply in the SAME language as the user (Vietnamese if they wrote Vietnamese). "
        "Be concise and direct. Cite specific file names and line patterns when relevant. "
        "If the context is insufficient, say so clearly.\n\n"
        "## Code Context\n\n" + context
    )

    try:
        answer = await llm_call(system, goal)
    except Exception as exc:
        logger.warning("[info_pipeline] LLM call failed: %s", exc)
        answer = f"Lỗi khi gọi LLM: {exc}. Thử lại sau."

    t_done = time.perf_counter()
    logger.info(
        "[info_pipeline] done in %.1fs (fetch=%.1fs, llm=%.1fs)",
        t_done - t_start,
        t_fetched - t_start,
        t_done - t_fetched,
    )

    return _wrap(
        goal, answer, t_start,
        files_read=len(fetched_contents),
        from_cache=len(fetched_contents) == 0,
    )


def _wrap(goal: str, summary: str, t_start: float, *, files_read: int, from_cache: bool) -> dict:
    return {
        "goal": goal,
        "summary": summary,
        "steps": [],
        "metadata": {
            "pipeline": "info_pipeline",
            "latency_ms": int((time.perf_counter() - t_start) * 1000),
            "files_read": files_read,
            "from_cache": from_cache,
            "agents": 0,
        },
    }


__all__ = ["info_pipeline"]
