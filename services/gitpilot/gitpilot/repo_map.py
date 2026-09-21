"""Hierarchical repository map (Batch B6 + Rich Context Extension).

Generates a compact, factual "site map" of a repository — what
languages, what top-level modules, which files are entry points —
and persists it so every planner prompt can be primed with the same
high-level overview without re-discovering it each turn.

Inspired by Aider's repo-map, Cursor's project context, and the
``AGENTS.md`` convention.  This implementation is fully local: no
LLM call needed.  We read the file tree, count extensions, identify
"key" files via well-known names, and emit a markdown blob bounded
by a hard token budget (default 500).

Rich Context Extension (Option A):
  When a local AST cache exists at ~/.gitpilot/repo_cache/<repo_id>/
  (built by tools/repo_context/cli.py), build_repo_map() enriches the
  ``agents_md`` with:
    - Language breakdown with file counts
    - Top-N most relevant files (with class/function signatures)
      ranked by keyword similarity to the planner's ``goal``
    - Module structure inferred from actual source, not just paths
  Falls back to the original simple file-tree map when no cache exists.
  Best-effort: any failure silently falls through to the old behavior.

Storage:
  ~/.gitpilot/repo_maps/<sha1(owner/repo/branch)>.json  (simple map)
  ~/.gitpilot/repo_cache/<repo_id>/cache.json            (rich cache)

Invalidation:
  Simple map: stored alongside the commit SHA.  When HEAD moves,
  callers detect staleness via ``RepoMap.commit_sha``.
  Rich cache: mtime-based, rebuilt automatically when >10% files stale.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from . import flags
from .context_budget import estimate_tokens

logger = logging.getLogger(__name__)

FLAG_REPO_MAP = "repo_map"

DEFAULT_MAP_TOKEN_BUDGET = 500
MAP_MAX_KEY_FILES = 10
MAP_MAX_MODULES = 12
MAP_MAX_FILES_PER_MODULE = 6
MAPS_DIR_ENV = "GITPILOT_REPO_MAPS_DIR"

# Files we always lift into "key files" when present.  Ordered by
# importance — first match wins for ranking.
_WELL_KNOWN_KEY_FILES: tuple[str, ...] = (
    "README.md",
    "README.rst",
    "README",
    "AGENTS.md",
    "CLAUDE.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    ".github/workflows/ci.yml",
    "LICENSE",
    "CHANGELOG.md",
)


def _coerce_int_safe(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _coerce_str_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if x is not None]


def _coerce_lang_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k): _coerce_int_safe(v) for k, v in value.items()}


@dataclass
class ModuleSummary:
    path: str           # directory path, e.g. "src/util"
    files: List[str] = field(default_factory=list)
    file_count: int = 0


@dataclass
class RepoMap:
    """In-memory + on-disk representation of a repo's site map."""
    owner: str
    repo: str
    branch: str
    commit_sha: Optional[str] = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    languages: dict[str, int] = field(default_factory=dict)
    key_files: List[str] = field(default_factory=list)
    modules: List[ModuleSummary] = field(default_factory=list)
    total_files: int = 0
    agents_md: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RepoMap":
        raw_modules = data.get("modules", []) or []
        modules: List[ModuleSummary] = []
        if isinstance(raw_modules, list):
            for m in raw_modules:
                if isinstance(m, dict):
                    modules.append(ModuleSummary(
                        path=str(m.get("path", "") or ""),
                        files=_coerce_str_list(m.get("files")),
                        file_count=_coerce_int_safe(m.get("file_count")),
                    ))
        out = cls(
            owner=str(data.get("owner", "") or ""),
            repo=str(data.get("repo", "") or ""),
            branch=str(data.get("branch", "") or ""),
            commit_sha=(
                str(data["commit_sha"]) if data.get("commit_sha") is not None else None
            ),
            generated_at=str(data.get("generated_at", "") or ""),
            languages=_coerce_lang_counts(data.get("languages")),
            key_files=_coerce_str_list(data.get("key_files")),
            modules=modules,
            total_files=_coerce_int_safe(data.get("total_files")),
            agents_md=str(data.get("agents_md", "") or ""),
        )
        return out


# ----------------------------------------------------------------------
# Storage helpers
# ----------------------------------------------------------------------

def _maps_root() -> Path:
    import os

    override = os.environ.get(MAPS_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / ".gitpilot" / "repo_maps"


def _cache_key(owner: str, repo: str, branch: str) -> str:
    raw = f"{owner}/{repo}@{branch}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:24]


def _cache_path(owner: str, repo: str, branch: str) -> Path:
    return _maps_root() / f"{_cache_key(owner, repo, branch)}.json"


def load_cached(owner: str, repo: str, branch: str) -> Optional[RepoMap]:
    path = _cache_path(owner, repo, branch)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RepoMap.from_dict(data)
    except Exception as exc:
        logger.debug("[repo-map] could not load %s: %s", path, exc)
        return None


def save_cached(repo_map: RepoMap) -> None:
    root = _maps_root()
    root.mkdir(parents=True, exist_ok=True)
    path = _cache_path(repo_map.owner, repo_map.repo, repo_map.branch)
    try:
        path.write_text(json.dumps(repo_map.to_dict(), indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[repo-map] could not save %s: %s", path, exc)


# ----------------------------------------------------------------------
# Rich Context Integration (Option A)
# Lookup local AST cache from tools/repo_context/ before falling back
# to the simple file-tree map.  All failures are silently swallowed.
# ----------------------------------------------------------------------

# Candidate root directories to search for a local checkout, in priority order.
_LOCAL_REPO_SEARCH_ROOTS: tuple[str, ...] = (
    str(Path.home() / "Documents" / "GitHub"),
    str(Path.home() / "GitHub"),
    str(Path.home() / "source" / "repos"),
    str(Path.home() / "dev"),
    str(Path.home() / "projects"),
    str(Path.home() / "code"),
    str(Path.home() / "repos"),
    str(Path.home()),
)

# Cache of already-resolved local paths to avoid repeated fs scans.
_local_repo_cache: dict[str, Optional[Path]] = {}


def _find_local_repo(repo: str) -> Optional[Path]:
    """Search well-known parent directories for a local checkout of *repo*.

    Returns the repo root Path if found, None otherwise.  Results are
    memoised per process so repeated calls are cheap.
    """
    if repo in _local_repo_cache:
        return _local_repo_cache[repo]

    # Also check ~/.gitpilot/workspaces/*/<repo>
    ws_root = Path.home() / ".gitpilot" / "workspaces"
    if ws_root.exists():
        for owner_dir in ws_root.iterdir():
            candidate = owner_dir / repo
            if candidate.is_dir() and (candidate / ".git").exists():
                _local_repo_cache[repo] = candidate
                return candidate

    for root_str in _LOCAL_REPO_SEARCH_ROOTS:
        candidate = Path(root_str) / repo
        if candidate.is_dir() and (candidate / ".git").exists():
            _local_repo_cache[repo] = candidate
            return candidate

    _local_repo_cache[repo] = None
    return None


def _trigger_background_rebuild(repo_root: Path, cache_dir: Path) -> None:
    """Launch a detached subprocess to rebuild the AST cache for *repo_root*.

    Fire-and-forget: the current process returns immediately.  The rebuild
    writes to ``cache_dir/cache.json`` so the next request picks up fresh
    data automatically.  Duplicate rebuilds are suppressed via a lockfile.
    """
    import subprocess
    import sys

    lock = cache_dir / ".rebuild.lock"
    if lock.exists():
        # Another rebuild already in flight for this cache dir
        logger.debug("[repo-map] rebuild already in progress for %s", cache_dir.name)
        return

    # Find the cli.py entry point relative to THIS file:
    # services/gitpilot/gitpilot/repo_map.py -> tools/repo_context/cli.py
    this_dir = Path(__file__).resolve().parent          # .../services/gitpilot/gitpilot/
    repo_eris_root = this_dir.parent.parent.parent      # .../eris/
    cli_path = repo_eris_root / "tools" / "repo_context" / "cli.py"
    if not cli_path.exists():
        logger.debug("[repo-map] cli.py not found at %s, skipping rebuild", cli_path)
        return

    try:
        lock.touch()  # Create lock before spawning
        cmd = [
            sys.executable, str(cli_path),
            "--repo", str(repo_root),
            "cache", "--build", "--force",
        ]
        # Detached: no stdin/stdout, survives parent process
        kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import platform
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        logger.info(
            "[repo-map] Background rebuild started: PID=%d repo=%s",
            proc.pid, repo_root.name,
        )
    except Exception as exc:
        logger.debug("[repo-map] could not start background rebuild: %s", exc)
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass


def _try_rich_context(
    repo: str,
    goal: str,
    *,
    token_budget: int,
    top_n: int = 6,
) -> Optional[str]:
    """Try to build a rich agents_md from the local AST cache.

    Returns a markdown string on success, None if the cache is missing
    or anything fails.
    """
    try:
        import json as _json
        import re as _re

        cache_root = Path.home() / ".gitpilot" / "repo_cache"
        if not cache_root.exists():
            return None

        # Find the right cache dir by matching repo name in the repo_id suffix
        # (format: <sha1[:12]>_<repo-name>)
        matched_cache: Optional[Path] = None
        safe_repo = repo.replace(".", "-")  # repo_id uses hyphens
        for entry in cache_root.iterdir():
            if not entry.is_dir():
                continue
            # repo_id ends with _<repo-name> (possibly truncated at 40 chars)
            suffix = entry.name.split("_", 1)[-1] if "_" in entry.name else ""
            if suffix == safe_repo or suffix == repo or entry.name.endswith(f"_{repo}"):
                cache_file = entry / "cache.json"
                if cache_file.exists():
                    matched_cache = cache_file
                    break

        if matched_cache is None:
            return None

        data = _json.loads(matched_cache.read_text(encoding="utf-8"))
        if data.get("schema_version") != 3:
            return None

        stats = data.get("stats", {})
        files_data = data.get("files", {})
        if not files_data:
            return None

        # ---- Staleness check (sample up to 40 files) -------------------
        # Compare cached mtime+size against current filesystem.
        # If >10% changed, trigger a background rebuild and annotate output.
        repo_root = Path(data.get("repo_root", ""))
        stale_ratio = 0.0
        is_stale = False
        if repo_root.exists():
            sample_keys = list(files_data.keys())
            import random as _random
            if len(sample_keys) > 40:
                sample_keys = _random.sample(sample_keys, 40)
            stale_count = 0
            checked = 0
            for rel in sample_keys:
                rec = files_data[rel]
                fp = repo_root / rel
                try:
                    st = fp.stat()
                    if (
                        abs(st.st_mtime - rec.get("mtime", 0)) > 1.0
                        or st.st_size != rec.get("size", -1)
                    ):
                        stale_count += 1
                    checked += 1
                except OSError:
                    # File deleted — counts as stale
                    stale_count += 1
                    checked += 1

            if checked > 0:
                stale_ratio = stale_count / checked
                is_stale = stale_ratio > 0.10  # >10% files changed

            if is_stale:
                logger.info(
                    "[repo-map] Cache stale (%.0f%% of sample changed) for %s — "
                    "triggering background rebuild",
                    stale_ratio * 100, repo,
                )
                _trigger_background_rebuild(repo_root, matched_cache.parent)

        # ---- Header ------------------------------------------------
        lines: list[str] = []
        total = stats.get("total_files", len(files_data))
        lines.append(f"## Repository: `{repo}`")
        lines.append(f"**{total} source files**")

        langs = stats.get("languages", {})
        if langs:
            top_langs = sorted(langs.items(), key=lambda kv: -kv[1])[:8]
            lines.append(
                "**Languages:** "
                + ", ".join(f"`{lang}`={count}" for lang, count in top_langs)
            )

        if is_stale:
            pct = int(stale_ratio * 100)
            lines.append(
                f"> ⚠️ Context may be partially outdated ({pct}% of sampled files "
                f"changed). Fresh index is rebuilding in the background — "
                f"next request will have up-to-date context."
            )
        lines.append("")

        # ---- Module overview (top dirs) ----------------------------
        module_index = data.get("module_index", {})
        if module_index:
            lines.append("### Modules")
            for mod, mod_files in sorted(
                module_index.items(), key=lambda kv: -len(kv[1])
            )[:8]:
                lines.append(f"- **`{mod}/`** \u2014 {len(mod_files)} file(s)")
            lines.append("")

        # ---- Relevant files (ranked by goal keywords) ---------------
        if goal and goal.strip():
            keywords = _re.split(r"[\s,;]+", goal.strip().lower())
            keywords = [k for k in keywords if len(k) > 2][:10]

            scored: list[tuple[float, str, dict]] = []
            for rel, rec in files_data.items():
                score = 0.0
                text = " ".join([
                    rel,
                    rec.get("module_doc", ""),
                    " ".join(rec.get("classes", [])),
                    " ".join(rec.get("functions", [])),
                    rec.get("skeleton", ""),
                ]).lower()
                for kw in keywords:
                    if kw in rel.lower():
                        score += 3.0
                    if any(kw in c.lower() for c in rec.get("classes", [])):
                        score += 2.0
                    if any(kw in f.lower() for f in rec.get("functions", [])):
                        score += 1.5
                    score += min(text.count(kw) * 0.1, 1.0)
                if score > 0.4:
                    scored.append((score, rel, rec))

            scored.sort(key=lambda x: x[0], reverse=True)

            if scored:
                lines.append("### Most Relevant Files")
                for score, rel, rec in scored[:top_n]:
                    lang = rec.get("language", "")
                    size_kb = rec.get("size", 0) // 1024
                    doc = rec.get("module_doc", "")
                    classes = rec.get("classes", [])[:4]
                    fns = rec.get("functions", [])[:4]

                    lines.append(f"\n#### `{rel}` [{lang}, {size_kb}KB]")
                    if doc:
                        lines.append(f"> {doc}")
                    if classes:
                        extra = f"+{len(rec['classes'])-4}" if len(rec.get('classes', [])) > 4 else ""
                        lines.append(f"Classes: `{'`, `'.join(classes)}`{extra}")
                    if fns and not classes:
                        extra = f"+{len(rec['functions'])-4}" if len(rec.get('functions', [])) > 4 else ""
                        lines.append(f"Functions: `{'`, `'.join(fns)}`{extra}")
                    # Include skeleton (first 15 lines)
                    skel = rec.get("skeleton", "")
                    if skel:
                        skel_lines = skel.split("\n")[:15]
                        lines.append("```")
                        lines.extend(skel_lines)
                        lines.append("```")
        else:
            # No goal: just show top files by size as overview
            lines.append("### Key Files (by size)")
            top_files = sorted(
                files_data.items(),
                key=lambda kv: -kv[1].get("size", 0),
            )[:8]
            for rel, rec in top_files:
                lang = rec.get("language", "")
                doc = rec.get("module_doc", "")
                size_kb = rec.get("size", 0) // 1024
                summary = f" \u2014 {doc}" if doc else ""
                lines.append(f"- `{rel}` [{lang}, {size_kb}KB]{summary}")

        lines.append("")
        lines.append(
            "_Use `Find files matching a pattern`, `Search file contents` "
            "and `Read file content` tools to drill into anything above._"
        )

        result = "\n".join(lines)

        # Trim to budget (rough: 4 chars per token)
        max_chars = token_budget * 4
        if len(result) > max_chars:
            result = result[:max_chars].rsplit("\n", 1)[0] + "\n..."

        logger.info(
            "[repo-map] Rich context from cache: %d chars (repo=%s, goal_kw=%d)",
            len(result), repo, len(goal.split()) if goal else 0,
        )
        return result

    except Exception as exc:
        logger.debug("[repo-map] rich context lookup failed: %s", exc)
        return None


# ----------------------------------------------------------------------
# Map builder
# ----------------------------------------------------------------------

def _extension_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return "(no-ext)"
    return name.rsplit(".", 1)[-1].lower()


def _top_dir_of(path: str) -> str:
    """Return the first directory segment of a path; '' for root files."""
    if "/" not in path:
        return ""
    return path.split("/", 1)[0]


def _group_into_modules(paths: List[str]) -> List[ModuleSummary]:
    """Group files by top-level directory.  Root-level files form a
    "(root)" pseudo-module so they're still visible."""
    buckets: dict[str, List[str]] = {}
    for p in sorted(paths):
        top = _top_dir_of(p) or "(root)"
        buckets.setdefault(top, []).append(p)

    modules: List[ModuleSummary] = []
    for name, files in buckets.items():
        modules.append(
            ModuleSummary(
                path=name,
                files=files[:MAP_MAX_FILES_PER_MODULE],
                file_count=len(files),
            )
        )
    # Sort by file count descending so the most-populated modules
    # come first — these are the ones the planner most needs to see.
    modules.sort(key=lambda m: (-m.file_count, m.path))
    return modules[:MAP_MAX_MODULES]


def _select_key_files(paths: List[str]) -> List[str]:
    by_name = {p.rsplit("/", 1)[-1]: p for p in paths}
    selected: List[str] = []
    for well_known in _WELL_KNOWN_KEY_FILES:
        # Match either the bare name at any depth or the exact path.
        if well_known in paths:
            selected.append(well_known)
            continue
        if "/" in well_known:
            if well_known in paths:
                selected.append(well_known)
            continue
        if well_known in by_name:
            selected.append(by_name[well_known])
        if len(selected) >= MAP_MAX_KEY_FILES:
            break
    return selected


def _render_agents_md(repo_map: RepoMap, *, token_budget: int) -> str:
    """Render the markdown blob that gets pinned into planner prompts.

    Bounded by ``token_budget``.  If the first-pass output overshoots
    we trim modules from the tail (least-populated) and try again.
    """
    def _build(modules: List[ModuleSummary]) -> str:
        lines: list[str] = []
        lines.append(f"# Repository map — `{repo_map.owner}/{repo_map.repo}` @ `{repo_map.branch}`")
        lines.append("")
        lines.append(f"**Total files:** {repo_map.total_files}")
        if repo_map.languages:
            top = sorted(repo_map.languages.items(), key=lambda kv: -kv[1])[:8]
            lines.append(
                "**Languages:** " + ", ".join(f"`{ext}`={n}" for ext, n in top)
            )
        if repo_map.key_files:
            lines.append("")
            lines.append("## Key files")
            for kf in repo_map.key_files:
                lines.append(f"- `{kf}`")
        if modules:
            lines.append("")
            lines.append("## Modules")
            for mod in modules:
                lines.append(f"- **`{mod.path}/`** — {mod.file_count} file(s)")
                for f in mod.files:
                    lines.append(f"    - `{f}`")
        lines.append("")
        lines.append(
            "_Use the `Find files matching a pattern`, `Search file contents` "
            "and `Read file content` tools to drill into anything above._"
        )
        return "\n".join(lines)

    modules = list(repo_map.modules)
    out = _build(modules)
    while estimate_tokens(out) > token_budget and len(modules) > 3:
        # Drop the least-populated module and try again.
        modules = modules[:-1]
        out = _build(modules)
    return out


def build_repo_map(
    *,
    owner: str,
    repo: str,
    branch: str,
    paths: Iterable[str],
    commit_sha: Optional[str] = None,
    token_budget: int = DEFAULT_MAP_TOKEN_BUDGET,
    goal: str = "",
) -> RepoMap:
    """Construct a :class:`RepoMap` from a list of repository file paths.

    When a local AST cache exists at ``~/.gitpilot/repo_cache/`` (built by
    ``tools/repo_context/cli.py cache --build``), the ``agents_md`` field is
    enriched with class/function signatures and goal-ranked relevant files.
    Falls back to the original compact file-tree map when no cache is found.

    Args:
        owner:        GitHub owner / org name.
        repo:         Repository name.
        branch:       Active branch or ref.
        paths:        Iterable of repo-relative file path strings.
        commit_sha:   Current HEAD SHA (for staleness detection).
        token_budget: Max tokens for the ``agents_md`` string.
        goal:         The planner's goal text (used to rank relevant files
                      in the rich context view).  Empty string for overview.
    """
    files = sorted({p.strip() for p in paths if p and isinstance(p, str)})
    languages = dict(Counter(_extension_of(p) for p in files))
    key_files = _select_key_files(files)
    modules = _group_into_modules(files)

    repo_map = RepoMap(
        owner=owner,
        repo=repo,
        branch=branch,
        commit_sha=commit_sha,
        languages=languages,
        key_files=key_files,
        modules=modules,
        total_files=len(files),
    )

    # --- Try rich context first (Option A) ---------------------------------
    rich_md = _try_rich_context(repo, goal, token_budget=token_budget)
    if rich_md:
        repo_map.agents_md = rich_md
    else:
        # Fall back to the classic compact file-tree map
        repo_map.agents_md = _render_agents_md(repo_map, token_budget=token_budget)

    return repo_map


def get_or_build_repo_map(
    *,
    owner: str,
    repo: str,
    branch: str,
    paths_provider: Callable[[], Iterable[str]],
    commit_sha: Optional[str] = None,
    token_budget: int = DEFAULT_MAP_TOKEN_BUDGET,
    force: bool = False,
    goal: str = "",
) -> RepoMap:
    """Return a cached map if still valid for the current commit, otherwise
    build a fresh one and persist.

    ``paths_provider`` is a zero-arg callable returning ``Iterable[str]``
    of repo paths — keeps this function independent of how paths are fetched.

    ``goal`` is forwarded to :func:`build_repo_map` to enable goal-aware
    rich context ranking when a local AST cache is available.
    """
    if not force:
        cached = load_cached(owner, repo, branch)
        if cached and cached.commit_sha == commit_sha and commit_sha is not None:
            # If we have a cached simple map but rich context is now available,
            # rebuild so the planner gets the enriched version.
            rich_md = _try_rich_context(repo, goal, token_budget=token_budget)
            if rich_md and rich_md != cached.agents_md:
                cached.agents_md = rich_md
            return cached

    paths = list(paths_provider())
    fresh = build_repo_map(
        owner=owner, repo=repo, branch=branch,
        paths=paths, commit_sha=commit_sha,
        token_budget=token_budget, goal=goal,
    )
    save_cached(fresh)
    return fresh


__all__ = [
    "FLAG_REPO_MAP",
    "DEFAULT_MAP_TOKEN_BUDGET",
    "ModuleSummary",
    "RepoMap",
    "build_repo_map",
    "get_or_build_repo_map",
    "load_cached",
    "save_cached",
]
