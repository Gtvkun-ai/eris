# Design — VoicePolicy Consolidation (Nước 1)

## Overview

Introduce `src/runtime/voice_policy.py`: a leaf module (stdlib-only) that is the **single source
of truth** for (a) the forbidden-register marker data + predicates, (b) the anti-disclaimer
few-shot prose, (c) the reroll disclaimer clause, and (d) the persona voice-constraint block.

Existing sites are rewired to *consume* from it. No literals are restated. Behavior is preserved
by **moving the exact current strings** into `VoicePolicy` rather than rewriting them.

## Architecture

```
                         ┌─────────────────────────────┐
                         │  runtime/voice_policy.py     │  (leaf, stdlib only)
                         │  VOICE_POLICY (singleton)    │
                         │  - forbidden markers + cats  │
                         │  - normalize_guard_ascii     │
                         │  - is_disclaimer_text         │
                         │  - detect_category            │
                         │  - ANTI_DISCLAIMER_FEWSHOT    │  (canonical text)
                         │  - reroll_disclaimer_clause   │
                         │  - prompt_voice_constraint    │
                         └──────────────┬──────────────┘
            ┌───────────────────────────┼───────────────────────────┐
            │ (detection)               │ (few-shot / reroll)        │ (prompt constraint C)
   runtime/disclaimer_markers.py   llm/service.py            prompt_context_builder.py
   (thin re-export shim)           - ANTI_DISCLAIMER_FEWSHOT  _build_action_plan_context
            │                        = re-export             uses VOICE_POLICY.prompt_voice_constraint
   consumers unchanged:             - rewrite_guard_violation_text
   post_generation_filters,           disclaimer_clause = VOICE_POLICY.reroll_disclaimer_clause
   relational_voice_seed_adapter,
   affect_self_read              relational_voice_seed_adapter._anti_disclaimer_fewshot()
                                    fallback -> VOICE_POLICY.anti_disclaimer_fewshot
```

### Why `runtime/` as the home

`runtime/disclaimer_markers.py` already lives in `runtime` and is imported by both runtime and
(indirectly) by the voice-seed adapter. `voice_policy.py` is made a pure leaf (imports only
`re`, `unicodedata`), so `llm/service.py` importing it does **not** create a cycle (the leaf
imports nothing back). This keeps the move minimal.

## Module: `runtime/voice_policy.py`

A frozen module-level singleton `VOICE_POLICY` plus the data it owns. Concretely:

### Forbidden-register data (moved verbatim from `disclaimer_markers.py`)

```python
HELPER_MARKERS: tuple[str, ...] = (...)   # "ho tro va giup do", ...
HARD_MARKERS:   tuple[str, ...] = (...)   # "toi la mot tro ly", "toi la mot ai", ...
EMOTION_MARKERS: tuple[str, ...] = (...)  # "toi khong co cam xuc", ...
```

### Predicates (moved verbatim)

```python
def normalize_guard_ascii(text: str) -> str: ...        # NFD strip + đ→d + lower + collapse
def is_disclaimer_text(text: str) -> bool: ...           # hard + helper markers
def detect_disclaimer_category(text, *, include_emotion_when) -> str: ...
```

`is_disclaimer_text` keeps identical semantics: matches any HARD or HELPER marker (flag-agnostic).

### Prose outputs (moved verbatim from their current homes)

```python
ANTI_DISCLAIMER_FEWSHOT: str   # exact text currently in llm/service.py
REROLL_DISCLAIMER_CLAUSE: str  # exact text currently inline in rewrite_guard_violation_text
PROMPT_VOICE_CONSTRAINT: str   # exact INFJ block currently inline in _build_action_plan_context
```

### Object surface

```python
@dataclass(frozen=True)
class VoicePolicy:
    def forbidden_markers(self, category: str) -> tuple[str, ...]: ...
    def is_disclaimer(self, text: str) -> bool: ...
    def normalize(self, text: str) -> str: ...
    def render_anti_disclaimer_fewshot(self) -> str: ...
    def render_reroll_clause(self) -> str: ...
    def render_prompt_constraint(self) -> str: ...

VOICE_POLICY = VoicePolicy()
```

Module-level functions (`normalize_guard_ascii`, `is_disclaimer_text`, the marker tuples) are also
exported at module scope so the shim can re-export them directly.

## Consumer rewiring

### Consumer A — `disclaimer_markers.py` → thin shim
Replace the literal tuples + predicate bodies with re-exports:
```python
from runtime.voice_policy import (
    HELPER_MARKERS as CHAT_DISCLAIMER_HELPER_MARKERS,
    HARD_MARKERS as CHAT_DISCLAIMER_HARD_MARKERS,
    EMOTION_MARKERS as CHAT_DISCLAIMER_EMOTION_MARKERS,
    normalize_guard_ascii,
    is_disclaimer_text,
)
```
All current importers (`post_generation_filters`, `relational_voice_seed_adapter`,
`affect_self_read`) keep working unchanged (Req 3.3).

### Consumer D — few-shot
- `llm/service.py`: `ANTI_DISCLAIMER_FEWSHOT = _VOICE_POLICY_FEWSHOT` (re-export of the canonical
  text now living in `voice_policy`). Name preserved (Req 3.4).
- `relational_voice_seed_adapter._anti_disclaimer_fewshot()`: the inline literal fallback is
  replaced by `VOICE_POLICY.render_anti_disclaimer_fewshot()`. The preference order
  (`llm_service.ANTI_DISCLAIMER_FEWSHOT` → service module constant → policy) is preserved.

### Reroll — `rewrite_guard_violation_text`
Replace the inline `disclaimer_clause = ("... long literal ...")` with
`disclaimer_clause = VOICE_POLICY.render_reroll_clause()` when
`violation_rule == "anti_disclaimer_voice"`.

### Consumer C — prompt constraint
In `prompt_context_builder._build_action_plan_context`, replace the hardcoded
`"INFJ 5w4 594 constraint:\n- ..."` block with `VOICE_POLICY.render_prompt_constraint()`.
The surrounding `style_block` assembly is otherwise unchanged.

## Import-cycle analysis

- `voice_policy` imports: `re`, `unicodedata`, `dataclasses` only. No project imports. → leaf.
- `disclaimer_markers` → imports `voice_policy`. Safe.
- `llm/service` → imports `voice_policy`. Safe (leaf has no back-edge to llm or runtime).
- `prompt_context_builder` (already a runtime mixin) → imports `voice_policy`. Safe.
- Existing `runtime → llm.service` edges are unaffected.

## Error handling / safety

- `voice_policy` is pure data + pure string ops; cannot raise on normal use.
- Consumers that wrap calls defensively (adapter fallback) keep their try/except.
- The static markers remain the guard floor (Req 5). A `# SEAM:` comment marks where a future
  learning layer could *augment* (append exemplars) without replacing the static set.

## Testing strategy

Because the workspace `.venv` may lack runtime deps (`requests`), tests must not require importing
the full coordinator/service graph.

1. **Pure unit tests** on `voice_policy` (no heavy imports):
   - `is_disclaimer_text` matches each HARD and HELPER marker; rejects clean ERIS lines.
   - marker tuples are non-empty and equal to the pre-refactor snapshot (golden test).
   - `render_*` outputs are non-empty and contain the key anchors (e.g. "Forbidden register",
     "INFJ", the reroll "help-desk" phrasing).
2. **Shim parity test**: importing the legacy names from `disclaimer_markers` yields objects
   identical (`is`) to `voice_policy` exports.
3. **Diagnostics** on every edited file (no compile/type errors).
4. If a Python interpreter with full deps is available, run the existing
   `tests/test_relational_voice_seed.py` and any post-generation guard tests to confirm parity;
   otherwise document the limitation.

## Files touched

| File | Change |
|------|--------|
| `src/runtime/voice_policy.py` | **new** — canonical source |
| `src/runtime/disclaimer_markers.py` | becomes thin re-export shim |
| `src/llm/service.py` | `ANTI_DISCLAIMER_FEWSHOT` re-export; reroll clause from policy |
| `src/runtime/relational_voice_seed_adapter.py` | inline few-shot fallback → policy |
| `src/runtime/prompt_context_builder.py` | INFJ block → policy |
| `tests/test_voice_policy.py` | **new** — unit + parity tests |
