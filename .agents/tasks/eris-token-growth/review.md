# Audit-cut of mind_state telemetry + profile qualifiers on the Root Self projection
# Audit-cut of mind_state telemetry + profile qualifiers on the Root Self projection

The change adds three transport-only projection helpers (`compact_personality`,
`compact_identity`, `compact_mind_state`) to `self_prompt_view.py` and wires
`compact_mind_state` into `project_self_view`, dropping the accumulating
telemetry/history/identifier fields from the `mind_state` block of the Root Self
prefix. It also extends `_PROFILE_AUDIT_FIELDS` (and trims the `defaults`
promotion list in `compact_profile`) to drop six technical qualifiers
(`id/value_type/cardinality/recurrence/tier/source`) from each profile record.
The goal is to stop the per-session growth of the Self prefix (trajectory loads
up to 96 records, ledgers, counter dicts) without touching stored state or
cognitive content. Everything is cut at the projection layer only; the reducer's
`to_dict()` persistence is untouched.

Watch for: nothing blocking. The delta-reconstruction invariant is preserved
because bootstrap-snapshot and self-now both route through the same compacted
`project_self_view` (confirmed), and the regression test proving this passes per
the recorded evidence. The one behavioral side effect — `persisted_mind_variants`
now carries projection-marker tombstones — is benign persistence evidence, not
cognitive content, and is covered by an updated test (confirmed).

**Verdict**: APPROVED

## High-level view

The cut sits entirely in `project_self_view` via `compact_mind_state`, placed
before the persisted-variant diff reads `mind_state` as `primary`. Because
`_read_self` returns `project_self_view(result)`, and both the bootstrap path
(`project_bootstrap_self(_read_self(host))`) and the self-now path
(`_read_self(host)`) call it, both sides of `_changed()` compare already-compacted
shapes. No phantom delta can arise from the cut. The marker
`eris.mind_state.v1` makes the helper idempotent.

The field classification matches the verified CUT/KEEP list exactly. Only the
`THỪA` telemetry/history/identifier fields are dropped at three levels (top-level
`schema/version/last_applied_turn_seq/updated_at`; personality
`trajectory/consolidation_ledger/corroboration_records/corroboration/streaks/day_usage/last_*_at/schema/version`;
identity `ledger/corroboration/last_updated_at/schema/version`). Every cognitive
branch survives, including the conflicting-belief fields
(`identity.beliefs` with `contradiction_ids`, `active_conflict`, `emergent_values`).

The "keep when unverified" rule is honored: `memory_candidates`,
`identity.pending_strategies`, and `identity.imprints` are not in any audit tuple
and are asserted present in the test.

Persistence is untouched. The commit changes only `self_prompt_view.py`, the
test, the measure script, and the report doc — none of the four `to_dict()`
owners (`contracts.py`, `personality.py`, `identity.py`, `models.py`) appear in
the diff.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking action items. The one behavioral change
(`persisted_mind_variants` marker tombstones) is intended, in-scope, and
test-covered.

</details>

<details>
<summary>Details</summary>

### Delta reconstruction stays correct (review point 1 — confirmed)

`_read_self` ends in `return project_self_view(result)` (root_session.py:81), so
the mind_state compaction happens inside every Self read. The bootstrap snapshot
is `project_bootstrap_self(_read_self(self._host))` (root_session.py:295) and
`project_bootstrap_self` only pops `living_user` episodes — it does not touch
`mind_state`, so the snapshot it stores is already compacted. Self-now is
`_read_self(self._host)` (root_session.py:360), also compacted. The delta is
`_changed(state.bootstrap_self_snapshot, self_now)` (root_session.py:361),
comparing two compacted shapes. There is no path where a raw mind_state meets a
compacted one, so no phantom delta.

`test_every_request_can_reconstruct_current_self_and_context` exercises `_prime`
+ three `ask` turns + a revert, asserting `current == _read_self(host)` each time
and that the bootstrap fingerprint/prefix are stable. Because `current` is the
bootstrap snapshot with the accumulated overlay applied, this is the
every-request-can-reconstruct-current-self invariant the task requires. The
report records this test passing in the 47-passed run; the routing I traced in
code is consistent with that result, so I did not re-run it.

The call site is ordered correctly: `compact_mind_state` runs immediately before
`primary = result.get("mind_state")` and the `state_difference(primary, persisted)`
call. Placing it earlier than the persisted diff is what keeps `primary` compacted
while `persisted` (`ai_orchestrated_state`) stays raw.

### Field classification matches the verified list (review points 2, 3, 4 — confirmed)

The three audit tuples in the diff are exactly the plan's CUT lists:

```
_PERSONALITY_AUDIT_FIELDS = trajectory, consolidation_ledger, corroboration_records,
                            corroboration, streaks, day_usage,
                            last_consolidated_at, last_decay_at, last_updated_at,
                            schema, version
_IDENTITY_AUDIT_FIELDS    = ledger, corroboration, last_updated_at, schema, version
_MIND_TOP_AUDIT_FIELDS    = schema, version, last_applied_turn_seq, updated_at
```

No cognitive field appears in any tuple. The test asserts the kept set survives
unchanged at each level: personality `core/temperament/mood` plus the
`*_anchor/*_baseline` attractors and `strategy_reinforcement/narrative/relationship_profiles`;
identity `values/motives/defenses/beliefs/emergent_values/relationships/strategies/active_motives/active_defenses/active_conflict/latest_value_choice`;
and the top-level `relationship/appraisal/latest_observation/latest_intention/open_loops/goal_records`.

Conflicting belief preservation is explicit: the fixture carries a `b.conflict`
belief with `contradiction_ids: ["b.keep"]` and an `active_conflict`, and the
test asserts both survive. `emergent_values` is also kept.

The "keep when unverified" fields are protected structurally (absent from every
audit tuple) and behaviorally (asserted present): `memory_candidates` at
top-level, `pending_strategies` and `imprints` under identity. The code correctly
places `pending_strategies` in `compact_identity`, not `compact_personality` —
the risk the plan flagged.

For the profile side, `_PROFILE_AUDIT_FIELDS` gains
`id/value_type/cardinality/recurrence/tier/source`, and the five of those that
were previously `defaults` candidates are removed from the promotion loop (only
`scope/status/sensitivity/valid_until/expires_at` remain). Without that second
change the fields would be popped per-record but re-promoted to `defaults`,
yielding no savings — the diff does both. `scope` and `sensitivity` are kept
(not cut), matching the requirement.

### Persistence untouched (review point 5 — confirmed)

The commit touches four files: `self_prompt_view.py`, the test, the measure
script, and `mind-state-profile-telemetry-cut.md`. None of the four `to_dict()`
owners (`contracts.py`, `personality.py`, `identity.py`,
`memory/living_user/models.py`) are in the diff, so
`RuntimeMindState/PersonalityProfile/IdentityProfile/ProfileRecord.to_dict()` are
unchanged and `store.save()` still serializes the full field set. The
`render_prompt_context` one-shot and `project_root_messages` history projection
are not touched by the diff. Idempotency is enforced by the `projection_schema`
markers (`eris.personality.v1`, `eris.identity.v1`, `eris.mind_state.v1`), and
each helper `deepcopy`s its input before popping, so the owner's state is never
mutated — the test asserts `source == before` and `compact_mind_state(projected)
== projected`.

### persisted_mind_variants tombstones (behavioral side effect — confirmed, in-scope)

Because `primary` (mind_state) is now compacted while `persisted`
(`ai_orchestrated_state`) stays raw, `state_difference` surfaces the dropped
fields and the new markers under `persisted_mind_variants`. The updated
`test_self_view_removes_debug_and_clones_without_changing_owner` encodes the new
expected shape: the real persisted variant plus `projection_schema` /
`identity.projection_schema` tombstones (`{"__erased_from_self": True}`). This is
persistence-diff evidence, small and non-cognitive. The plan explicitly scoped
out running the persisted branch through the same compaction; leaving it raw and
only updating the expected test value is the correct minimal choice.

### Measurement (review point 6 — recorded in evidence)

The report records the measure-script output: profile marginal saving 1,559
chars (3,923 → 2,364 on the real store copy, read-only), consistent with the
~1,500–2,500 estimate; mind_state fixture 12,147 → 1,679 (−10,468) on a fixture
that fills the caps (trajectory 96, ledger 24, corroboration 16/key). The
fixture figure is a cap-saturated upper bound, not a live measurement — the
report states this limitation clearly. Both blocks demonstrably shrank.

</details>

<details>
<summary>File map</summary>

- `src/runtime/conversation/self_prompt_view.py` — adds `compact_personality/compact_identity/compact_mind_state` + three audit tuples; extends `_PROFILE_AUDIT_FIELDS` and trims the `defaults` promotion list; wires `compact_mind_state` into `project_self_view` before the persisted-variant diff.
- `src/tests/conversation/test_root_prompt_cleanup.py` — new `test_compact_mind_state_cuts_telemetry_keeps_cognition`; extended profile test (qualifiers + scope/sensitivity); updated `test_self_view_...` for the marker/tombstone shape.
- `.agents/tasks/eris-token-growth/measure_self_cut.py` — read-only char-count measurement on a store copy + mind_state fixture.
- `.agents/tasks/eris-token-growth/mind-state-profile-telemetry-cut.md` — coder report with CUT/KEEP anchors, test result (47 passed), and char counts.

Full diff: `git show cce85311`.

</details>
