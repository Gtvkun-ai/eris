# -*- coding: utf-8 -*-
"""Measure how heavy the Root "Self/memory" block is on the REAL user memory.

Read-only against the user's live store: the real ``memory/core`` dir is copied
into a throwaway temp dir and every store is pointed there, so this script never
mutates or overwrites the canonical files.

It reconstructs the living_user branch of the dict ``_read_self`` feeds into
``project_self_view`` (service.summary(limit=80) + episode_prompt_view), then
measures three things per Self part:
  (a) CURRENT form  -> after the evidence/metadata cut (compact_profile/episode)
  (b) HEAVY old form -> raw to_dict() with no compaction, for the delta
  (c) real record / episode counts

No LLM call, no app build, no product code edited. Output is written to a file
(terminal here is noisy); character + token SIZES only, never personal values.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

# Keep this a pure measurement: no embedding model load, no network.
os.environ.setdefault("ERIS_EMBEDDING_ENABLED", "0")

OUT_DIR = REPO / ".agents" / "tasks" / "eris-token-growth"
RAW_OUT = OUT_DIR / "real-self-measurement.raw.json"


def _dumps(value) -> str:
    """Same separators the runtime uses when it json.dumps the Self prefix."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chars(value) -> int:
    return len(_dumps(value))


def _est_tokens(value) -> int | None:
    try:
        from llm.token_budget import estimate_tokens  # type: ignore

        return estimate_tokens([{"content": _dumps(value)}])
    except Exception:
        return None


def _resolve_real_base_dir() -> Path:
    """Mirror vision.py: ERIS_HOME or ~/Documents/ErisLive, then /memory/core."""
    explicit = str(os.getenv("ERIS_HOME", "") or "").strip()
    core_override = str(os.getenv("ERIS_MEMORY_CORE_DIR", "") or "").strip()
    if core_override:
        return Path(core_override).expanduser().resolve()
    home = Path(explicit).expanduser().resolve() if explicit else (Path.home() / "Documents" / "ErisLive").resolve()
    return home / "memory" / "core"


def main() -> None:
    report: dict = {"ok": False, "steps": []}

    real_base = _resolve_real_base_dir()
    report["real_base_dir"] = str(real_base)
    report["real_base_exists"] = real_base.exists()

    if not real_base.exists():
        report["error"] = (
            "Real memory core dir not found. User may never have run the built "
            "app on this machine, so there is no real store to measure."
        )
        RAW_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # Record the real files + byte sizes (read-only stat).
    files = []
    for p in sorted(real_base.glob("*")):
        if p.is_file():
            files.append({"name": p.name, "bytes": p.stat().st_size})
    report["store_files"] = files

    # Copy the whole core dir to a temp sandbox so service init / trace writes
    # never touch the canonical files.
    sandbox = Path(tempfile.mkdtemp(prefix="eris-self-measure-"))
    base = sandbox / "core"
    shutil.copytree(real_base, base)
    report["sandbox"] = str(base)

    try:
        from memory.living_user.service import LivingUserMemoryService
        from memory.living_user.models import UserMemoryScope
        from runtime.conversation.self_prompt_view import project_self_view

        service = LivingUserMemoryService(str(base))

        # ------------------------------------------------------------------
        # Real counts (profile records, episodes).
        # ------------------------------------------------------------------
        profile_full = service.profile_store.snapshot(include_sensitive=False, limit=80)
        profile_records = profile_full.get("records") if isinstance(profile_full, dict) else None
        n_profile_records = len(profile_records) if isinstance(profile_records, list) else None
        n_profile_total = len(service.profile_store.all())

        scope = UserMemoryScope()
        episode_view = service.episode_prompt_view(scope=scope)
        recent_episodes = episode_view.get("recent_episodes") if isinstance(episode_view, dict) else []
        episode_recap = episode_view.get("episode_recap") if isinstance(episode_view, dict) else ""
        n_recent_episodes = len(recent_episodes) if isinstance(recent_episodes, list) else 0
        n_episodes_total = len(service.episode_store.all())

        report["counts"] = {
            "profile_records_snapshot_limit80": n_profile_records,
            "profile_records_total_on_disk": n_profile_total,
            "recent_episodes_in_prompt_view": n_recent_episodes,
            "episodes_total_on_disk": n_episodes_total,
            "episode_recap_present": bool(episode_recap),
        }

        # ------------------------------------------------------------------
        # Build the living_user branch exactly as _read_self assembles it:
        #   memory_state.living_user = {**service.summary(...)'s living_user
        #   bits, **episode_prompt_view()}.  summary() already nests
        #   profile/recent_episodes/actions, and _read_self then re-overlays
        #   episode_prompt_view on top (same shape).
        # ------------------------------------------------------------------
        summary = service.summary(include_sensitive=False, limit=80)
        living_from_summary = dict(summary)
        # _read_self overlays the owner's fresh episode view on top.
        living_from_summary.update(episode_view)

        # The snapshot that reaches project_self_view (living_user branch only;
        # mind_state / subject_self are measured separately / flagged below).
        real_snapshot = {"memory_state": {"living_user": living_from_summary}}

        projected = project_self_view(real_snapshot)
        proj_living = projected["memory_state"]["living_user"]

        # ------------------------------------------------------------------
        # (a) CURRENT form, per key, after the compact_profile/compact_episode cut.
        # ------------------------------------------------------------------
        def _part(container: dict, key):
            return container.get(key) if isinstance(container, dict) else None

        current = {}
        current["living_user.profile"] = {
            "chars": _chars(_part(proj_living, "profile")),
            "tokens": _est_tokens(_part(proj_living, "profile")),
        }
        current["living_user.recent_episodes"] = {
            "chars": _chars(_part(proj_living, "recent_episodes")),
            "tokens": _est_tokens(_part(proj_living, "recent_episodes")),
        }
        current["living_user.episode_recap"] = {
            "chars": _chars(_part(proj_living, "episode_recap")),
            "tokens": _est_tokens(_part(proj_living, "episode_recap")),
        }
        current["living_user.actions"] = {
            "chars": _chars(_part(proj_living, "actions")),
            "tokens": _est_tokens(_part(proj_living, "actions")),
        }
        # Any other keys the projection kept in living_user (replay etc. are
        # dropped by project_self_view; measure whatever survives).
        other_keys = [k for k in proj_living if k not in {"profile", "recent_episodes", "episode_recap", "actions"}]
        current["living_user.other_surviving_keys"] = {
            "keys": other_keys,
            "chars": _chars({k: proj_living[k] for k in other_keys}),
        }
        current["living_user.TOTAL_projected"] = {
            "chars": _chars(proj_living),
            "tokens": _est_tokens(proj_living),
        }

        # ------------------------------------------------------------------
        # (b) HEAVY old form: the same real data WITHOUT compact_profile /
        #     compact_episode.  summary()'s profile is the raw snapshot; the
        #     raw recent_episodes = episode_store.recent(limit=8).to_dict()
        #     (full to_dict, the rollup prompt_view path without compaction).
        # ------------------------------------------------------------------
        heavy_profile = service.profile_store.snapshot(include_sensitive=False, limit=80)
        heavy_recent = [x.to_dict() for x in service.episode_store.recent(limit=8, scope=scope)]
        heavy_actions = service.action_store.snapshot()

        heavy = {}
        heavy["living_user.profile"] = {
            "chars": _chars(heavy_profile),
            "tokens": _est_tokens(heavy_profile),
        }
        heavy["living_user.recent_episodes_raw_recent8"] = {
            "chars": _chars(heavy_recent),
            "tokens": _est_tokens(heavy_recent),
            "count": len(heavy_recent),
        }
        heavy["living_user.actions"] = {
            "chars": _chars(heavy_actions),
            "tokens": _est_tokens(heavy_actions),
        }

        report["self_measurements"] = {
            "current_after_cut": current,
            "heavy_old_form": heavy,
            "profile_cut_saving_chars": heavy["living_user.profile"]["chars"] - current["living_user.profile"]["chars"],
        }

        # ------------------------------------------------------------------
        # Why recent_episodes/recap came out empty, and what actions carry.
        # These are SIZE/COUNT diagnostics only; no personal values dumped.
        # ------------------------------------------------------------------
        rollup_file = base / "living_user_episode_rollups.json"
        all_eps = service.episode_store.all()
        now = __import__("time").time()
        ep_ages_days = sorted(round((now - float(getattr(e, "ended_at", 0.0) or 0.0)) / 86400.0, 1) for e in all_eps)
        report["episode_diagnostics"] = {
            "rollup_file_exists": rollup_file.exists(),
            "recent_days_window": 7.0,
            "episodes_total": len(all_eps),
            "episode_ages_days_sorted": ep_ages_days,
            "episodes_within_7d": sum(1 for d in ep_ages_days if d <= 7.0),
            "note": (
                "recent() only keeps episodes <= recent_days old; render() only emits a recap "
                "when a valid rollup entry exists. If no episode is within 7d and no rollup file "
                "exists, the Root prompt's recent_episodes + episode_recap are both empty."
            ),
        }

        actions_snap = service.action_store.snapshot()
        goals = actions_snap.get("goals", []) if isinstance(actions_snap, dict) else []
        commits = actions_snap.get("commitments", []) if isinstance(actions_snap, dict) else []
        flows = actions_snap.get("workflows", []) if isinstance(actions_snap, dict) else []

        def _status_breakdown(rows):
            out = {}
            for r in rows:
                s = r.get("status") if isinstance(r, dict) else "?"
                out[s] = out.get(s, 0) + 1
            return out

        # Size the audit/provenance fields inside actions (the fields the other
        # two living_user parts already drop via compact_*). Measured, not guessed.
        AUDIT = ("evidence_ids", "metadata", "created_at", "updated_at",
                 "completed_at", "due_at", "scope")
        audit_chars = 0
        total_actions_chars = 0
        for row in [*goals, *commits, *flows]:
            if not isinstance(row, dict):
                continue
            total_actions_chars += _chars(row)
            audit_chars += _chars({k: row[k] for k in AUDIT if k in row})

        report["actions_diagnostics"] = {
            "goals": {"count": len(goals), "status": _status_breakdown(goals)},
            "commitments": {"count": len(commits), "status": _status_breakdown(commits)},
            "workflows": {"count": len(flows), "status": _status_breakdown(flows)},
            "includes_inactive_records": True,
            "actions_block_chars": current["living_user.actions"]["chars"],
            "audit_provenance_chars_within_records": audit_chars,
            "note": (
                "project_self_view does NOT run a compact_* pass on actions, so "
                "evidence_ids/timestamps/metadata/scope still ship. The snapshot also "
                "includes inactive (completed/cancelled/archived) records."
            ),
        }

        # ------------------------------------------------------------------
        # Branches that need the live runtime reducer / subject service and
        # cannot be rebuilt from the store files alone.
        # ------------------------------------------------------------------
        report["not_measured"] = {
            "mind_state": "Needs ai_state_reducer.snapshot() from a live RuntimeCoordinator; not rebuildable from memory/core files alone.",
            "subject_self": "Needs host.subject_service.self_view() from the live runtime; no standalone file.",
            "memory_state_other_layers": (
                "memory_state also carries semantic/episodic/relational/procedural/affective/belief/"
                "worldview/etc. via MemoryCognitionCore.load(); those enter the Self prefix too but are "
                "outside the living_user branch this script isolates. Their on-disk byte sizes are listed "
                "in store_files above (e.g. semantic_memory.json, relational_memory.json)."
            ),
        }

        report["ok"] = True
    except Exception:
        report["exception"] = traceback.format_exc()
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    RAW_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
