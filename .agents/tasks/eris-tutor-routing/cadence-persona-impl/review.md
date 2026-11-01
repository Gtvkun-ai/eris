# Cadence-as-persona: soften tutor sentence quota, teach Eris to pace by caring

Branch `cadence-persona` turns presentation rhythm from a numeric constraint into a personality trait. Three moves: the `ROOT_SYSTEM_CORE` finalize sentence now says `say` is one beat a listener can swallow in one breath (not a dumping ground for a whole lesson), a new persona sentence tells Eris to notice whether the listener is keeping up and to spread a long explanation across `after=may_continue` turns *because it cares about the learner, not because it is being counted*; and `TutorGuardrailPolicy` stops using `max_sentences` as a hard length ceiling, widening every envelope to the contract maximum (6) so the guardrail still gates phase/kind/evidence but no longer flattens voice by sentence count. A single observability log line in `agent.py` records the `after` type so live sessions can show whether Root actually spreads beats.

Watch for: nothing blocking. The hard constraints all hold — no new `max_sentences`/quota/budget/scheduler was introduced (confirmed: the string `max_sentences` appears exactly once in `ROOT_SYSTEM_CORE`, the surviving ban sentence), the real pedagogy directives (no early answers, no solving-for-the-student, spaced retrieval, assessment goals) are untouched in `enforce()` (confirmed), and the two loosened test files still assert the real invariants and pass (confirmed, 24 passed on narrow re-run). The effectiveness of the cadence change is a model behavior inside prompt freedom and can only be confirmed live — the author states this clearly (possible, by design).

**Verdict**: APPROVED

## High-level view

The prompt change is the heart of it. The old finalize sentence invited Root to pack "everything the writer needs to convey" into one `say`; the new wording reframes `say` as a single beat and adds a persona sentence that motivates spreading content across `may_continue` turns as an act of attention to the learner. Both edits preserve the "không phải transcript" clause and the `delivery`/`after` grammar, and neither introduces a counting rule — the existing ban sentence (speech budget, max_sentences, semantic scheduler) is intact.

The policy change is a genuine removal of a hard cap, not a renamed one. Every `MoveEnvelope` previously carried a small `max_sentences` (1–6 depending on phase/pace); they now all use one widened hint of 6, and `enforce()` switched from `min(move, envelope)` to `max(move, envelope)` so the guardrail can no longer pull a move's length below its own intent. The phase/kind gating, `requires_user_response`, interaction type, and every pedagogy directive stay exactly as they were.

The test edits are the one place where loosening could hide a regression, so they got the closest look. The three changed assertions moved from equality/upper-bound on sentence counts to lower bounds (`>= 2`, `>= 4`, `>= 1`) and carry comments explaining the new semantics; critically, the assertions that protect the real contract (the LLM can't override phase/kind/kp_id, the `BIẾN THỂ` directive survives, "Bỏ qua bài học" stays out of the instruction) are untouched. The files pass on a narrow re-run.

The `agent.py` edit is a log-only line inside the existing `move` finalize branch. It emits the normalized `after` type and nothing else — no `say`/`intent` content, no new schema field, no soft-forcing.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking action items. The one open item is verification-only and already documented by the author: live-session confirmation that Root actually paces beats is outside what fixtures can prove.

</details>

<details>
<summary>Details</summary>

### `say` reframed from transcript-dump to a single beat (1a)

The finalize sentence changed from "say mô tả đầy đủ điều writer cần truyền đạt nhưng không phải transcript" to "say là MỘT nhịp, một ý người nghe nuốt được trong một hơi, không phải transcript và cũng không phải chỗ nhồi cả lời giải hay cả bài giảng vào một move". The "không phải transcript" clause and the `delivery`/`after` grammar of the same sentence are preserved verbatim, matching the plan's item 1a exactly. No number or quota enters the wording.

### Persona sentence motivates pacing by attention, not by count (1b)

A new sentence sits next to the existing "cá tính... quyết số nhịp nối" line: Eris notices whether the listener is keeping up, like a good storyteller who knows where to pause, and when one idea is complete but more remain (teaching, listing steps, setting a problem) it says that idea in its own voice then uses `after=may_continue` to spread the rest — "rải vì quan tâm người học, không vì bị đếm câu". This is written as character, not as a rule, which is the whole point of the task. The confirmed string count shows `max_sentences` still appears exactly once in the core prompt (the ban sentence), so this sentence introduced no counting construct. The pre-existing confusion-signal sentence (`repair_needed`, `ví dụ/góc nhìn MỚI`) is intact (1c, confirmed present, no duplicate added).

### Hard sentence cap removed, not renamed (policy.py)

This is the load-bearing change for constraint (a)/(b)/(c), and it holds up. Previously `envelope()` computed `teach_budget = 6/5/4` by pace and handed each phase a tight `max_sentences` (probe=2, practice=3, assess/review/advance/transfer/independent=2, adaptive repair=`min(3, budget)`, yield floor=1). Now a single module constant `_SOFT_CADENCE_HINT = 6` — the contract's own upper bound — is used for every envelope, and `teach_budget` is gone. The field survives only for contract compatibility; the comments state plainly it is a soft hint and that Root's personality owns the real pacing via `after=may_continue`.

The second half of the change is in `enforce()`:

```python
# before
max_sentences=min(move.max_sentences, envelope.max_sentences),
# after
max_sentences=max(move.max_sentences, envelope.max_sentences),
```

The `min` → `max` flip is what makes the hint non-coercive: the guardrail can no longer drag a move's length below its own intent. Everything else in `enforce()` that matters pedagogically is byte-for-byte unchanged — `allowed_kinds` gating, `requires_user_response` (including the Socratic-question carve-out that forces a user response even inside a `teach` phase), `interaction_type`, and the full `directives` table: "không hé đáp án", "không giải mẫu... không gợi ý trước khi người học trả lời", the spaced-retrieval "MỘT câu hỏi nhớ lại không gợi ý", the `BIẾN THỂ` transfer probe, and the assessment `question_goal` lines. Constraint (c) — step 2 must not strip the real pedagogy — is satisfied: only the length coercion was removed.

`reasoner.py` was correctly left untouched. The plan flagged it as "inspect, change only if it force-counts"; it only sets `max_sentences=envelope.max_sentences` and its `instruction_by_kind` carries no length rule, so leaving it alone is right and keeps the "Giữ giọng Eris tự nhiên" line intact.

### Test assertions re-aimed at the real invariant (d)

The one place a loosening could mask a failure is the two edited test files, so these were the spot-check target. Three assertions changed:

- `test_probe_phase_cannot_be_overridden_by_semantic_model`: `== 2` → `>= 2`. The test's real job — probe phase and `probe_question` kind survive an adversarial model, `requires_user_response is True` — is unchanged above the edited line.
- `test_learner_pace_changes_teaching_budget`: `envelope == 4` / `move <= 4` → `>= 4` / `>= 4`. Still asserts the teach phase resolves; the pace-driven hard ceiling is what was removed, so the equality no longer describes the contract.
- `test_illegal_llm_move_cannot_override_adaptive_envelope`: `<= 2` → `>= 1`, with the `kp_id`, `BIẾN THỂ`-in-`instruction_vi`, `requires_user_response`, and "Bỏ qua bài học" not-present assertions all kept.

None of these deletes a semantic assertion to pass; each re-expresses the length expectation as a floor consistent with "hint, not quota" and keeps the behavioral guards. A narrow re-run of both files (`test_tutor_executive_v1.py`, `test_learn04_adaptive_teaching.py`) returned 24 passed, matching the author's evidence. The broader evidence (94 passed across the four mandated files plus the affected tutor suites) was read, not re-run per the judge-not-retest instruction.

### `after`-type log line only (agent.py, constraint e)

The `agent.py` edit adds one `self._log("info", "[root-agent] finalize move after=%s", ...)` inside the existing `kind == "move"` finalize branch. It logs only the normalized `after` value (`str(raw.get("after","wait_user")).strip().lower()[:24]`) — no `say` or `intent` content, no new field on `NEXT_MOVE_SCHEMA`, no soft-forcing logic. This is exactly the "log the `after` type only" scope of constraint (e) and the plan's item 7; `test_architecture_v12.py` (which asserts `max_sentences` never appears in the schema) is in the mandated green set.

### Scope and bundling

The diff touches exactly the five files the plan names and nothing in the forbidden set (`continuation.py`, `kernel.py`, writer, TTS). No unrelated changes are bundled. The one ruff finding the author reports — `F401` for an unused import at `test_learn04_adaptive_teaching.py:14` — is pre-existing (the diff only touches lines 161–166) and correctly left out of scope rather than opportunistically "fixed".

</details>

<details>
<summary>File map</summary>

- `src/runtime/conversation/root_prompt_contract.py` — finalize sentence reframed to "one beat" (1a); persona cadence sentence added next to "quyết số nhịp nối" (1b); ban sentence and confusion sentence intact.
- `src/runtime/tutor/policy.py` — `max_sentences` hard ceilings replaced by one soft hint (`_SOFT_CADENCE_HINT = 6`); `enforce()` `min` → `max`; `teach_budget` removed; all pedagogy directives and phase/kind gating unchanged.
- `src/runtime/conversation/agent.py` — one observability log line for the `after` type in the `move` finalize branch; no schema change.
- `src/tests/test_tutor_executive_v1.py` — two `max_sentences` assertions re-aimed as floors; behavioral guards kept.
- `src/tests/test_learn04_adaptive_teaching.py` — one `max_sentences` assertion re-aimed as a floor; directive/kind guards kept.

Full diff: `git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona diff main`

</details>
