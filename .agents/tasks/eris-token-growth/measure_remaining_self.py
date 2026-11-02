# -*- coding: utf-8 -*-
"""Measure the REMAINING Self-prefix branches + static prompts (read-only).

Follow-up to measure_real_self.py, which already sized the living_user branch.
This script sizes everything else that enters the Root Self prefix via
``_read_self`` -> ``project_self_view`` and the static system/style prompts.

What it does, all read-only:
  1. memory_state: copy the real memory/core to a temp sandbox, build
     MemoryCognitionCore(sandbox).load() exactly like host.memory_state, strip
     concept_graph like _read_self does, run it through project_self_view(),
     then size every top-level key under memory_state separately.
  2. mind_state / subject_self: grep already confirmed they are runtime-only
     (reducer + subject_service). This records WHY they cannot be rebuilt from
     the memory/core files, and whether any persisted form exists on disk.
  3. static prompts in src/llm/contracts.py + ROOT_SYSTEM_CORE: size each.

No LLM call, no app build, no product code edited, no store overwrite (temp
copy only). SIZES only (chars + heuristic tokens); never personal values.
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

# Pure measurement: no embedding model load, no network.
os.environ.setdefault("ERIS_EMBEDDING_ENABLED", "0")

OUT_DIR = REPO / ".agents" / "tasks" / "eris-token-growth"
RAW_OUT = OUT_DIR / "remaining-self-measurement.raw.json"


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chars(value) -> int:
    return len(_dumps(value))


def _est_tokens_text(text: str) -> int | None:
    try:
        from llm.token_budget import estimate_tokens  # type: ignore

        return estimate_tokens([{"content": text}])
    except Exception:
        return None


def _est_tokens(value) -> int | None:
    return _est_tokens_text(_dumps(value))


def _resolve_real_base_dir() -> Path:
    explicit = str(os.getenv("ERIS_HOME", "") or "").strip()
    core_override = str(os.getenv("ERIS_MEMORY_CORE_DIR", "") or "").strip()
    if core_override:
        return Path(core_override).expanduser().resolve()
    home = Path(explicit).expanduser().resolve() if explicit else (Path.home() / "Documents" / "ErisLive").resolve()
    return home / "memory" / "core"


def _measure_memory_state(report: dict) -> None:
    real_base = _resolve_real_base_dir()
    report["memory_state"] = {"real_base_dir": str(real_base), "real_base_exists": real_base.exists()}
    if not real_base.exists():
        report["memory_state"]["error"] = "real memory core dir not found"
        return

    sandbox = Path(tempfile.mkdtemp(prefix="eris-remaining-measure-"))
    base = sandbox / "core"
    shutil.copytree(real_base, base)
    try:
        from memory.memory_cognition import MemoryCognitionCore
        from runtime.conversation.self_prompt_view import project_self_view

        core = MemoryCognitionCore(str(base))
        loaded = core.load()  # exactly what host.memory_state is

        # _read_self strips concept_graph before projecting.
        loaded = {k: v for k, v in loaded.items() if k != "concept_graph"}

        # project_self_view expects {"memory_state": ..., optionally "mind_state"}.
        snapshot = {"memory_state": loaded}
        projected = project_self_view(snapshot)
        pmem = projected.get("memory_state", {})

        # Size every top-level key of the projected memory_state separately.
        per_key = {}
        for key in sorted(pmem.keys()):
            per_key[key] = {"chars": _chars(pmem[key]), "tokens": _est_tokens(pmem[key])}
        report["memory_state"]["projected_per_key"] = per_key
        report["memory_state"]["projected_total"] = {
            "chars": _chars(pmem), "tokens": _est_tokens(pmem),
        }
        # Raw (pre-projection) per-key, to show what projection trimmed.
        raw_per_key = {}
        for key in sorted(loaded.keys()):
            raw_per_key[key] = {"chars": _chars(loaded[key])}
        report["memory_state"]["raw_per_key_chars"] = raw_per_key
        report["memory_state"]["raw_total_chars"] = _chars(loaded)

        # Record simple counts for the heavy layers (no personal values).
        counts = {}
        for name, attr in (
            ("semantic", "semantic"), ("episodic", "episodic"),
            ("relational", "relational"), ("procedural", "procedural"),
            ("affective_residue", "affective_residue"), ("repair", "repair"),
            ("belief_core", "belief_store"), ("worldview", "worldview"),
        ):
            store = getattr(core, attr, None)
            loader = getattr(store, "load", None)
            if callable(loader):
                try:
                    counts[name] = len(list(loader()))
                except Exception:
                    counts[name] = None
        report["memory_state"]["store_record_counts"] = counts
    except Exception:
        report["memory_state"]["exception"] = traceback.format_exc()
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _measure_mind_and_subject(report: dict) -> None:
    """mind_state/subject_self are runtime-only; document why, check disk."""
    real_base = _resolve_real_base_dir()
    # load() has no ai_orchestrated_state key; persisted mind variant only lives
    # in the in-RAM memory_state dict injected by the ai_orchestrated persist
    # callback, saved back via memory_core.save() (active_state + agent_mind only).
    report["mind_state"] = {
        "measured": False,
        "reason": (
            "Needs ai_state_reducer.snapshot().to_dict() from a live RuntimeCoordinator. "
            "MemoryCognitionCore.load() does NOT emit ai_orchestrated_state (the persisted "
            "mind variant), so there is no standalone mind_state snapshot in memory/core to read."
        ),
    }
    report["subject_self"] = {
        "measured": False,
        "reason": (
            "Needs host.subject_service.self_view() from the live SubjectService. "
            "No standalone self_view file is written under memory/core."
        ),
    }


def _measure_static_prompts(report: dict) -> None:
    prompts = {}
    try:
        from llm import contracts as C

        for name in (
            "STYLE_FALLBACK_PROMPT", "SELF_IDENTITY_PROFILE_PROMPT", "RUNTIME_RULES_PROMPT",
            "INFERENCE_LADDER_PROMPT", "AUTONOMOUS_BEHAVIOR_PROMPT", "CHAT_RULES_PROMPT",
            "PERSONA_PROMPT", "PROMPT", "DECISION_GBNF",
        ):
            val = getattr(C, name, None)
            if isinstance(val, str):
                prompts[f"contracts.{name}"] = {"chars": len(val), "tokens": _est_tokens_text(val)}
    except Exception:
        report["static_prompts_contracts_exception"] = traceback.format_exc()

    try:
        from runtime.conversation.root_prompt_contract import ROOT_SYSTEM_CORE

        prompts["root_prompt_contract.ROOT_SYSTEM_CORE"] = {
            "chars": len(ROOT_SYSTEM_CORE), "tokens": _est_tokens_text(ROOT_SYSTEM_CORE),
        }
    except Exception:
        report["root_core_exception"] = traceback.format_exc()

    try:
        from runtime.conversation.root_session_projector import SELF_BOOTSTRAP_INSTRUCTION

        prompts["root_session_projector.SELF_BOOTSTRAP_INSTRUCTION"] = {
            "chars": len(SELF_BOOTSTRAP_INSTRUCTION), "tokens": _est_tokens_text(SELF_BOOTSTRAP_INSTRUCTION),
        }
    except Exception:
        report["self_bootstrap_exception"] = traceback.format_exc()

    try:
        from runtime.eris_voice_contract import AUTONOMOUS_VOICE_CORE_V39

        prompts["eris_voice_contract.AUTONOMOUS_VOICE_CORE_V39"] = {
            "chars": len(AUTONOMOUS_VOICE_CORE_V39), "tokens": _est_tokens_text(AUTONOMOUS_VOICE_CORE_V39),
        }
    except Exception:
        pass

    report["static_prompts"] = prompts


def main() -> None:
    report: dict = {"ok": False}
    try:
        _measure_memory_state(report)
        _measure_mind_and_subject(report)
        _measure_static_prompts(report)
        report["ok"] = True
    except Exception:
        report["exception"] = traceback.format_exc()
    RAW_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
