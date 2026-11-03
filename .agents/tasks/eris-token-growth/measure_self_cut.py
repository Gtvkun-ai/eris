"""Measure the Root Self-prefix token cut (char counts only, no personal content).

READ-ONLY. Copies the live living_user_profile.json to a temp dir and reads it
through UserProfileStore; it never writes the live store. For mind_state it uses
a synthetic fixture (telemetry + cognition) since no live reducer snapshot is on
disk in a convenient shape. Prints before/after json.dumps char counts for the
old (raw) vs new (projected) shape of each branch. No profile values are printed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from runtime.conversation.self_prompt_view import compact_mind_state, compact_profile  # noqa: E402

LIVE_PROFILE = Path(r"C:\Users\Gtvkun\Documents\ErisLive\memory\core\living_user_profile.json")


def _chars(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def measure_profile() -> None:
    print("== living_user.profile ==")
    if not LIVE_PROFILE.exists():
        print(f"  (live profile not found at {LIVE_PROFILE}; skipping profile measurement)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="eris_profile_ro_"))
    try:
        copy_path = tmp / LIVE_PROFILE.name
        shutil.copy2(LIVE_PROFILE, copy_path)  # read-only copy; never touch the live file
        from memory.living_user.store import UserProfileStore

        store = UserProfileStore(path=copy_path)
        snapshot = store.snapshot(include_sensitive=True)  # shape compact_profile expects
        raw = _chars(snapshot)
        projected = compact_profile(snapshot)
        after = _chars(projected)
        # Marginal cut from THIS task = removing only the 6 technical qualifiers
        # from the already-projected shape (vs the prior projection that kept
        # them). Re-add them to a copy, re-encode, and diff.
        qualifiers = ("id", "value_type", "cardinality", "recurrence", "tier", "source")
        prior = compact_profile(snapshot)
        for row, orig in zip(prior["records"], snapshot["records"]):
            for k in qualifiers:
                if k in orig:
                    row[k] = orig[k]
        prior_defaults_chars = _chars({**prior, "defaults": prior.get("defaults", {})})
        print(f"  records                    : {snapshot.get('record_count')}")
        print(f"  chars raw (store snapshot) : {raw}")
        print(f"  chars prior projection     : {prior_defaults_chars}  (audit cut, qualifiers KEPT)")
        print(f"  chars new projection       : {after}  (audit + qualifiers cut)")
        print(f"  marginal saved (this task) : {prior_defaults_chars - after}")
        print(f"  total saved vs raw         : {raw - after}")
        # Structural checks only (no values printed): path/value survive.
        kept_path = all("path" in row and "value" in row for row in projected["records"])
        print(f"  path+value kept on every record : {kept_path}")
        cut = ("id", "value_type", "cardinality", "recurrence", "tier", "source")
        gone = all(all(k not in row for row in projected["records"]) for k in cut) and \
            all(k not in projected.get("defaults", {}) for k in cut)
        print(f"  technical qualifiers removed    : {gone}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _mind_fixture() -> dict:
    return {
        "schema": "eris.mind.v1", "version": 7, "last_applied_turn_seq": 42, "updated_at": 1787.0,
        "relationship": {"trust": 0.3, "closeness": 0.2, "rupture": 0.0},
        "appraisal": {"pleasantness": 0.1, "curiosity": 0.5, "pressure": 0.0},
        "personality": {
            "schema": "personality.v1", "version": 3,
            "core": {"warmth": 0.6, "assertiveness": 0.4},
            "temperament": {"reactivity": 0.4}, "mood": {"valence": 0.1},
            "core_anchor": {"warmth": 0.55}, "temperament_attractor": {"reactivity": 0.42},
            "mood_baseline": {"valence": 0.05}, "strategy_reinforcement": {"mirror": 0.3},
            "narrative": {"text": "settled and curious", "confidence": 0.7},
            "relationship_profiles": {"primary": {"stance": "warm", "distance": 0.5}},
            "trajectory": [{"turn": i, "warmth": 0.6, "valence": 0.1, "at": 1700.0 + i} for i in range(96)],
            "consolidation_ledger": [{"idx": i, "kind": "decay", "at": 1700.0 + i} for i in range(24)],
            "corroboration_records": {
                k: [{"idx": i, "src": f"u:{i}", "at": 1700.0 + i} for i in range(16)]
                for k in ("warmth", "assertiveness")
            },
            "corroboration": {"warmth": 3, "assertiveness": 2},
            "streaks": {"warmth": {"n": 5, "last": 1780.0}},
            "day_usage": {f"2026-10-{d:02d}": d for d in range(1, 15)},
            "last_consolidated_at": 1700.0, "last_decay_at": 1710.0, "last_updated_at": 1787.0,
        },
        "identity": {
            "schema": "identity.v1", "version": 2,
            "values": {"honesty": 0.8, "kindness": 0.7}, "motives": {"connect": 0.6},
            "defenses": {"withdraw": 0.2},
            "beliefs": {
                "b.keep": {"claim": "User likes directness.", "confidence": 0.7},
                "b.conflict": {"claim": "User wants silence now.", "confidence": 0.5,
                               "contradiction_ids": ["b.keep"]},
            },
            "emergent_values": {"playfulness": 0.4},
            "relationships": {"primary": {"trust": 0.3}},
            "strategies": {"mirror": {"weight": 0.3}},
            "pending_strategies": [{"name": "soften"}], "imprints": [{"moment": "first laugh"}],
            "active_motives": [{"name": "connect"}], "active_defenses": [{"name": "withdraw"}],
            "active_conflict": {"between": ["honesty", "kindness"]},
            "latest_value_choice": {"chose": "honesty"},
            "ledger": [{"idx": i, "kind": "update", "at": 1700.0 + i} for i in range(40)],
            "corroboration": {"honesty": 4, "kindness": 2},
            "last_updated_at": 1787.0,
        },
        "identity_learning_enabled": True,
        "latest_observation": {"turn_id": "t1", "confidence": 0.8},
        "latest_intention": {"plan": "listen"},
        "open_loops": [{"loop": "ask about trip"}],
        "goal_records": [{"goal": "support the user"}],
        "memory_candidates": [{"candidate": "user travels soon"}],
    }


def measure_mind_state() -> None:
    print("== mind_state (synthetic fixture: telemetry + cognition) ==")
    source = _mind_fixture()
    before = _chars(source)
    projected = compact_mind_state(source)
    after = _chars(projected)
    print(f"  chars before (raw) : {before}")
    print(f"  chars after  (cut) : {after}")
    print(f"  saved              : {before - after}")
    ident = projected["identity"]
    conflict_kept = ident["beliefs"]["b.conflict"].get("contradiction_ids") == ["b.keep"]
    cognition_kept = all(k in projected["personality"] for k in ("core", "temperament", "mood")) and \
        all(k in ident for k in ("values", "beliefs", "active_conflict", "emergent_values"))
    unverified_kept = "imprints" in ident and "pending_strategies" in ident and "memory_candidates" in projected
    print(f"  belief trái chiều (conflict) kept : {conflict_kept}")
    print(f"  core/value/belief cognition kept  : {cognition_kept}")
    print(f"  imprints/pending/candidates kept  : {unverified_kept}")


if __name__ == "__main__":
    measure_profile()
    print()
    measure_mind_state()
