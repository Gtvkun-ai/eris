# Audit-cut Self projection for agent_mind, active_state and semantic_memory

Commit `410f6792` extends the already-merged `compact_profile`/`compact_episode` pattern to the three remaining heavy Self branches that feed the Root prompt. Three new pure functions — `compact_agent_mind`, `compact_active_state`, `compact_semantic_item` — are added to `self_prompt_view.py` and wired into `project_self_view`, the single projection gate that `_read_self` returns through. Each drops per-record audit/provenance (raw epochs, evidence id lists, decay knobs, embedding hashes, access counters, the `raw_content` duplicate of `claim`) and empty/zero/default fields, while preserving the cognitive content: beliefs, preferences, claims, and — critically — non-empty `contradiction_ids`. Persistence is untouched; the change lives entirely on the projection path on a `deepcopy`.

Watch for: the commit bundles episode-fading plumbing (`project_bootstrap_self`, a `project_runtime_context` guard, a `_same_json` `zip(strict=False)` tweak) alongside the three-branch audit-cut (confirmed). The delta-reconstruction test exercises the projection+overlay mechanism but on a synthetic `memory_state`, not on the three specific nested-record branches (confirmed). Neither is blocking.

**Verdict**: APPROVED

## High-level view

The cut is placed in the one correct spot. `_read_self` (`root_session.py`) ends with `return project_self_view(result)`, so every memory_state branch flows through a single door, while `store.save()` serializes through the canonical `*.to_dict()` which this path never calls. The `--stat` for commit `410f6792` lists only `self_prompt_view.py`, the test file, and task docs — no persistence file is touched, so the canonical stores keep their full audit shape.

The three functions honor the audit-cut contract rather than top-k or summarization. `compact_agent_mind` pops only bookkeeping fields from each belief/preference record and never removes a record; `claim/confidence/tags/polarity/strength/stability` are explicitly outside the cut tuples and asserted to survive. Conflicting beliefs are protected: `contradiction_ids` is dropped only when falsy, kept verbatim when non-empty, on both the agent_mind and semantic branches — the "Root phải thấy belief trái chiều" requirement holds.

`compact_active_state` follows the fail-safe rule: `_is_empty_default` treats only `None`, `""`, `[]`, `()`, `{}` and real numeric zero as droppable, and explicitly excludes bools so `False` is kept as a real value. Meaningful non-defaults (trust=0.25, valence=0.02, curiosity=0.576, `rhythm_phase="settled"`, `last_event="maintenance_reset"`) survive; when a value is neither empty nor zero it is kept. `compact_semantic_item` drops the `raw_content` metadata duplicate of `claim` plus embedding/access audit while leaving `claim` and the light qualifiers intact.

Idempotency is enforced by a per-branch `projection_schema` marker and a `deepcopy` of the input, so `state_difference` (which compares bootstrap-self against self-now, both already projected) cannot manufacture a phantom delta across turns. The reconstruction test confirms `apply_overlay(bootstrap, delta) == _read_self(host)`.

Measurement is real and read-only: a copy of the live `memory/core` is loaded and run through the patched `project_self_view`, giving active_state 6198→3102, agent_mind 7852→4189, semantic_memory 3389→1646 chars, with `raw_per_key_chars` unchanged as independent evidence that serialization didn't move. No personal content is printed.

<details>
<summary>Issues (2)</summary>

1. **Bundled episode-fading changes** — the commit also adds `project_bootstrap_self`, a `project_runtime_context` `isinstance` guard, and a `_same_json` `zip(strict=False)` tweak that belong to the episode-fading work, not the three-branch audit-cut. Non-blocking; worth a note so a future bisect isn't misled about what this commit scoped.
2. **Delta test uses synthetic state** — `test_every_request_can_reconstruct_current_self_and_context` validates the projected-shape overlay/reconstruction on a flat synthetic `memory_state`, not on the agent_mind/active_state/semantic nested records. Per-function idempotency tests cover the phantom-delta risk, so coverage is adequate, but a reconstruction test over a realistic three-branch payload would close the gap directly.

</details>

<details>
<summary>Details</summary>

### Projection-only placement, persistence confirmed untouched

The entire product change is in `self_prompt_view.py`. `git show --stat 410f6792` lists `self_prompt_view.py`, `test_root_prompt_cleanup.py`, `plan.md`, `agent-mind-active-semantic-cut.md`, and `remaining-self-measurement.raw.json` — nothing under `cortex/agent_mind_persistence.py`, `memory/active_state_snapshot.py`, or `memory/semantic_memory.py`. `PersistentAgentMindStore.to_dict`, `ActiveStateSnapshot.to_dict`, and `SemanticMemoryItem.to_dict` are not in the diff, so `store.save()` still emits the full audit shape (confirmed). Each `compact_*` opens with `deepcopy(dict(...))` and mutates only the copy, so the in-RAM store objects are not touched (confirmed; the per-function tests assert `source == before`). The wiring is added inside `project_self_view` only — the one-shot `render_prompt_context` path is in another module and is not called here (confirmed from the diff).

### agent_mind: records kept, bookkeeping dropped, conflicts protected

`compact_agent_mind` iterates `beliefs`/`preferences` dict-of-records and pops the audit tuples (`created_at/updated_at/last_seen/source_ids/positive_evidence_count/negative_evidence_count/decay_rate` on beliefs; `created_at/updated_at/last_reinforced/source` on preferences). No record is ever removed. `claim/confidence/tags/domain/key` and `polarity/strength/stability` are outside the cut tuples. The guard `if not record.get("contradiction_ids"): record.pop("contradiction_ids", None)` drops the field only when it is empty/falsy and keeps a non-empty list verbatim (confirmed; `test_compact_agent_mind_cuts_audit_keeps_beliefs_and_contradictions` asserts `b.conflict` keeps `["b.keep"]` while `b.keep`'s empty list is dropped). Empty `habits`/`last_feedback_events` and the top-level epoch `updated_at` are dropped; `schema_version` is kept.

### active_state: fail-safe prune, bool False preserved

`_is_empty_default` returns True only for `None`, empty string/list/tuple/dict, and real numeric zero, and returns False for any bool before the numeric branch — so `False` is never mistaken for `0` and is kept (confirmed; test asserts `last_social_presence_present is False` survives). `_prune_empty` recurses through the nested `metadata.internal_state`/`*_dynamics`/`action_memory` dicts, dropping empty-default keys and collapsing dicts that become empty. Non-default values survive: the test confirms trust=0.25, valence=0.02, curiosity=0.576, preferred_distance=0.58, `attachment_drift="guarded"`, `rhythm_phase="settled"`, `last_event="maintenance_reset"` are all kept, and `goal_persistence` collapses to just its real string `{"status": "empty"}`. `session_arc == "unknown"` is explicitly treated as a default and dropped. The rule only ever removes empties/zeros, so no meaningful non-default value is at risk.

The existing `test_self_view_removes_debug_and_clones_without_changing_owner` was updated to reflect that once the duplicate `internal_state` is popped and the remaining active_state body prunes to nothing, only the `projection_schema` marker remains — `internal_state` no longer leaks into the prompt. The ordering in `project_self_view` pops the duplicate `internal_state` before `compact_active_state` runs, and the function is idempotent regardless.

### semantic_memory: raw_content duplicate removed, claim intact

`compact_semantic_item` drops top-level `evidence_ids/first_seen_at/updated_at` and the metadata audit set `raw_content/embedding_text_hash/embedding_version/access_count/last_accessed_at/fact_profile_evidence`; `raw_content` is a verbatim copy of `claim` on the real store, so dropping it is pure dedup (confirmed; the test seeds `metadata.raw_content == claim` and asserts it is cut while `claim` stays). `id/claim/confidence/status/tags` and the light qualifiers `fact_key/domain/importance` are kept, and the same non-empty-`contradiction_ids` protection applies. Emptied `metadata` is dropped. Items that aren't a `Mapping` are returned untouched.

### Idempotency and the bootstrap/delta contract

Each function returns early when its `projection_schema` marker is already present, and `state_difference` compares two already-projected snapshots, so a double projection cannot create a phantom delta. `test_every_request_can_reconstruct_current_self_and_context` primes a bootstrap self, then across several turns asserts `apply_overlay(bootstrap, step["self_changes_since_bootstrap"]) == _read_self(host)` and that returning to the original state restores the exact prefix — validating the overlay/reconstruction over the projected shape. This test drives a synthetic flat `memory_state` rather than the three nested-record branches, so it validates the mechanism but not the specific branch payloads; the per-function idempotency assertions (`compact_x(compact_x(src)) == compact_x(src)`) cover the phantom-delta risk for those branches directly.

I ran only `test_root_prompt_cleanup.py` as a narrow spot-check (the delta and idempotency behaviour gates two of the checks): **11 passed in 0.90s**, matching the report. I did not re-run the broad suites; the report's base-vs-changed comparison shows all 7 changed-run failures are red on base as well (action-guard/claim/schema contracts and one one-shot render-path test unrelated to this projection), i.e. no regression introduced by this change.

### Measurement evidence

`remaining-self-measurement.raw.json` holds real counts measured on a copy of `C:\Users\Gtvkun\Documents\ErisLive\memory\core` run through the patched `project_self_view`: active_state 6198→3102 (−50%), agent_mind 7852→4189 (−47%), semantic_memory 3389→1646 (−51%), projected_total 27897→19395 (−30%). `raw_per_key_chars` still reads 6198/7852/3389 — independent evidence that the on-disk serialization did not change because projection runs on a deepcopy. Only sizes are recorded; no belief/claim text is printed. `mind_state` and `subject_self` are flagged as runtime-only and not measurable from the static store, consistent with them being out of scope.

### Bundled, out-of-scope changes

Besides the three-branch audit-cut, commit `410f6792` adds `project_bootstrap_self` (strips `recent_episodes`/`episode_recap` from the bootstrap overlay), guards `project_runtime_context`'s `living_user` lookup with `isinstance`, and switches `_same_json`'s `zip` to `strict=False`. These belong to the episode-fading effort rather than this task's stated scope (audit-cut of the three Self branches). Low-risk, but bundling them into this commit muddies the scope boundary the plan drew and will mislead a future bisect.

</details>

<details>
<summary>File map</summary>

- `src/runtime/conversation/self_prompt_view.py` — adds `compact_agent_mind`, `compact_active_state` (+ `_is_empty_default`/`_prune_empty`), `compact_semantic_item`; wires the three into `project_self_view`; also adds `project_bootstrap_self` and tweaks `project_runtime_context`/`_same_json` (episode-fading, bundled).
- `src/tests/conversation/test_root_prompt_cleanup.py` — three new audit-cut tests plus an updated active_state assertion; 11 pass.
- `.agents/tasks/eris-token-growth/remaining-self-measurement.raw.json` — real before/after char/token counts.
- `.agents/tasks/eris-token-growth/plan.md`, `agent-mind-active-semantic-cut.md` — plan and coder report.

Full diff: `git show 410f6792 -- src/runtime/conversation/self_prompt_view.py`

</details>
