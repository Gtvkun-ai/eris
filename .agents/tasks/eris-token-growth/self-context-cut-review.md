# Drop audit/provenance from the Self projection on the Root prompt path

Commit `77fc3a13` moves the warm-up Self projection from "lossless" to "keep the telling, drop the audit". On the Root prompt path only, each profile record loses `evidence_ids`, the raw epoch timestamps (`created_at`/`updated_at`/`last_confirmed_at`/`valid_from`) and the free-text `metadata` dict; each recent episode loses `evidence_ids`/`metadata`/`started_at`/`ended_at`/`session_id`/`source`. The narrative content (path/value and the record qualifiers; title/summary/outcome and the episode signal lists) is kept, `mind_state` and `actions` are untouched, and the canonical `to_dict()` used for persistence is not changed. A representative-fixture measurement shows the `living_user` block shrinking ~51% (profile ~64%, episodes ~31%).

Watch for: valid_until/expires_at are deliberately kept (retention qualifiers, not audit) — this is a conscious narrowing of the plan's "cut all 6 timestamps" list, not a miss (confirmed). The headline size numbers come from a synthetic fixture, not a live portable request, and are disclosed as such (confirmed).

**Verdict**: APPROVED

## High-level view

The cut happens in exactly one place — `self_prompt_view.py`, the transport projection that `_read_self` runs before handing Self to the Root prompt. `ProfileRecord.to_dict()`/`UserEpisode.to_dict()` are not in the diff, so disk persistence and `from_dict` round-trips are unaffected; the one-shot `render_prompt_context` lane lives in other modules and is likewise untouched.

The profile change extends the existing `compact_profile` with an audit-field pop before the defaults pass, and retires the two timestamp aliases (both alias sources and one target are now cut, so no alias can form). Episodes previously only lost `metadata.source_turns`; a new `compact_episode` now drops the full audit set and keeps the telling.

Delta correctness holds for free: both the bootstrap snapshot and every per-turn `self_now` come from the same `_read_self → project_self_view`, so `state_difference` compares two already-projected shapes. Idempotency is guarded by `projection_schema` markers on both profile and episode so a re-projection produces no phantom delta.

The product requirement that Root sees the whole Self including weak/conflicting beliefs is preserved: `mind_state` and `persisted_mind_variants` are never entered by the projection, and `actions` (goals/commitments/workflows) is not touched.

<details>
<summary>Issues (2)</summary>

1. **valid_until/expires_at retained** — the plan's field list said cut 6 timestamps; the code keeps these two via the defaults pass as retention qualifiers. Intentional and documented; no action needed, noted for traceability.
2. **Measurement is fixture-based, not live** — the ~51%/64%/31% figures come from a representative fixture built to code caps, not a real portable request. Honestly disclosed; treat direction/magnitude as solid, absolute numbers as estimate.

</details>

<details>
<summary>Details</summary>

### The cut lives only in the transport projection

Everything happens in `src/runtime/conversation/self_prompt_view.py`. `compact_profile` gains a pop loop over `_PROFILE_AUDIT_FIELDS = (evidence_ids, metadata, created_at, updated_at, last_confirmed_at, valid_from)` that runs before the defaults-gathering pass, and a new `compact_episode` pops `_EPISODE_AUDIT_FIELDS = (evidence_ids, metadata, started_at, ended_at, session_id, source)`. `project_self_view` now maps every `recent_episodes` entry through `compact_episode` instead of only popping `metadata.source_turns`.

`git show 77fc3a13 --stat` confirms the commit touches only `self_prompt_view.py`, the two test files, and the implementation report. `src/memory/living_user/models.py` is not in the commit, so `ProfileRecord.to_dict()` and `UserEpisode.to_dict()` — the serializers `store.save()`/`snapshot()`/`from_dict` share for disk persistence — are unchanged. The projection takes a `deepcopy` and pops on the copy, so the in-memory store objects behind `host.memory_state` are not mutated either.

The cut set matches the decision points exactly: on the prompt path the record keeps `path`, `value`, `explicitness`, `scope`, `status`, `sensitivity`, `tier`, `cardinality`, `recurrence`, `source`, `value_type`, `confidence`, `id`; the episode keeps `title`, `summary`, `outcome`, `topics`, `entities`, `decisions`, `open_loops`, `user_signals`, `importance`, `scope`, `id`.

### valid_until / expires_at kept on purpose

The plan's field list named six timestamps to cut, but the implementation keeps `valid_until` and `expires_at` and routes them through the defaults pass. The implementation report and the code comment both frame these as retention qualifiers (when a fact stops being true) rather than audit provenance, and note they are mostly `None` so the defaults pass folds them to near-zero per-record cost. This is a deliberate, documented narrowing, consistent with the task's "keep qualifiers" requirement — not an omission. Flagging only so a later reader doesn't read it as a bug against the plan text.

### Delta stays on one shape

`root_session.py` builds `bootstrap_self_snapshot` from `_read_self(self._host)` at prime time and recomputes `self_now = _read_self(self._host)` each turn, then `_changed(state.bootstrap_self_snapshot, self_now)` (that's `state_difference`). Both inputs pass through `project_self_view`, so the merge-patch always compares two already-projected shapes — no mixing of a heavy bootstrap with a compact per-turn view. The `projection_schema="eris.root_profile.v1"` / `"eris.root_episode.v1"` markers make the projection idempotent (early-return if already marked), which is what keeps `state_difference` from emitting a phantom delta on an unchanged record between turns.

### mind_state and actions untouched

`project_self_view` only reaches into `memory_state.living_user` (profile + episodes), `memory_state.active_state`, and `memory_state.ai_orchestrated_state`. `result["mind_state"]` is set verbatim from the reducer's `to_dict()` in `_read_self` and is never entered by the projection, so weak/conflicting beliefs and `persisted_mind_variants` survive intact — the `SELF_BOOTSTRAP_INSTRUCTION` product requirement holds. `actions` (goals/commitments/workflows) is likewise not referenced by the projection.

### One-shot render path is separate

`render_prompt_context` is defined in `models.py`, `action_memory.py`, `goal_persistence.py`, `memory_packet_builder.py`, `internal_state.py`, `controlled_slippage.py`, `source_grounding.py` — none of them `self_prompt_view.py`, and none are in this commit. The compact one-shot lane is unaffected, matching the scope constraint.

### Test coverage

The two updated test files pass against the committed code (spot-checked: `test_root_prompt_cleanup.py` + `test_memory_interpretation_context.py` → 17 passed). `test_compact_profile_cuts_audit_keeps_telling_and_qualifiers` asserts the six cut fields are absent from every record and from `defaults`, that path/value/explicitness/scope survive, input is not mutated, and the projection is idempotent. `test_self_view_removes_debug_and_clones_without_changing_owner` and `test_episode_sources_survive_reconsolidation_but_stay_out_of_root` assert episodes lose the audit set but keep title/summary, and that `scrub_evidence` still works on the canonical store (proving `to_dict()` is untouched and the store still holds `source_turns`).

The implementation report's broader run (`50 passed, 1 failed`) attributes the one failure to a pre-existing red in `render_prompt_context` (the untouched one-shot lane), verified by `git stash` on base. Not re-run here per the review scope; the report's method for isolating it (stash + run on base) is sound and the failing path is outside this change.

Not tested: no live portable measurement of actual request bytes — the size reduction is a fixture estimate, disclosed as such. No assertion that `ERIS_ROOT_SESSION_BOOTSTRAP` is enabled on the running portable build (acknowledged as an assumption, consistent with AGENTS.md evidence tiering).

### Measurement honesty

The ~51% / 64% / 31% reductions come from a synthetic `living_user` block (38 records + 8 episodes) built to the code's caps, measured before/after with a temp script that was then deleted (`_measure_cut.py` and `_run_cut_tests.ps1` are both absent). The report explicitly flags these as fixture estimates, not live wire bytes, and notes real-data percentages will vary with actual `evidence_ids`/`metadata` sizes. The direction and order of magnitude are well-supported by what is cut; the absolute numbers are an estimate, correctly labeled.

</details>

<details>
<summary>File map</summary>

- `src/runtime/conversation/self_prompt_view.py` — audit-field pop added to `compact_profile`; new `compact_episode`; `project_self_view` maps episodes through it; timestamp aliases retired.
- `src/tests/conversation/test_root_prompt_cleanup.py` — profile test reworked from lossless-roundtrip to cuts-audit/keeps-telling; episode assertions added.
- `src/tests/test_memory_interpretation_context.py` — episode projection asserts audit gone / telling kept; store `scrub_evidence` still passes.
- `.agents/tasks/eris-token-growth/cheap-cut-implementation.md` — coder's implementation report.

Full diff: `git show 77fc3a13`.

</details>
