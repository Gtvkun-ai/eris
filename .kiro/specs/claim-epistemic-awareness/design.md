# Design Document

## Overview

This feature gives ERIS's private mind an explicit **epistemic self-awareness** about every claim it may surface. The shift, stated in the requirements, is from *"honesty by gating/muting"* to *"honesty by self-knowledge,"* under a Cartesian principle: an unanchored claim defaults to **doubt** (`speculative`), not to false certainty, and cognition is never cut to zero.

Concretely, the design:

1. Adds two first-class fields — `epistemic_stance` and `intent` — to three data contracts: `InternalJudgment`, `SurfaceCandidate` (both in `private_mind/contracts.py`), and `SurfaceImpulse` (in `surface_arbiter.py`).
2. Introduces a small, **pure, deterministic** `Epistemic_Classifier` helper in the private-mind package that maps `(has_public_anchor, intent) -> epistemic_stance`.
3. Repurposes the existing `SurfaceValve._has_public_anchor()` from a *mute switch* into the **classifier input**.
4. Reworks `SurfaceValve.filter()` so that stance drives routing: `grounded`/`ungrounded_aware` may reach `surface_arbiter` (subject to the existing thresholds); `ungrounded_blind` is withheld from public speech but routed to `body_only` and kept auditable.
5. Centralizes **intent defaulting** (anchored→`sincere`, unanchored→`speculative`) so the deterministic fallback path produces "live doubt" rather than silent confabulation.

The design deliberately keeps the classifier pure and the contract changes additive/backward-compatible (new fields default to safe values), so existing serialization and call sites continue to work.

## Architecture

### Position in the existing pipeline

```
inner_synthesizer (model | deterministic fallback)
        │  produces InternalJudgment (+ SurfaceCandidate)
        ▼
SurfaceValve.filter(judgment)
        │
        ├─ 1. resolve intent on the candidate        (Req 2: defaulting/validation)
        ├─ 2. has_anchor = _has_public_anchor(cand)   (Req 1.5/1.6: now a classifier input)
        ├─ 3. stance = classify_epistemic_stance(has_anchor, intent)  (Req 1)
        ├─ 4. stamp stance + intent onto candidate
        ├─ 5. route by stance:
        │       grounded / ungrounded_aware ─► existing public-surface gate + thresholds ─► surface_arbiter
        │       ungrounded_blind            ─► block public, record reason, route body_only (Req 3)
        ▼
SurfaceValve.to_surface_impulse(candidate)
        │  copies stance + intent onto SurfaceImpulse  (Req 4.5, Req 5.10-12)
        ▼
SurfaceArbiter (downstream public-speech generation)
```

### Stance decision table (Req 1)

The classifier is a total function over `(has_public_anchor, intent)`:

| has_public_anchor | intent ∈ {playful, teasing, speculative} | intent = sincere | intent undeterminable* |
|---|---|---|---|
| **true** | `grounded` (intent retained) | `grounded` | `grounded` |
| **false** | `ungrounded_aware` | `ungrounded_blind` | `ungrounded_blind` (self-knowledge failure) |

\* "undeterminable" should not normally occur because intent is defaulted before classification (see Intent resolution). It is handled defensively as a Self_Knowledge_Failure (Req 3.4).

Key property: anchor presence dominates intent for the stance label (Req 1.2), but intent is preserved unchanged alongside the stance (Req 1.8), so a playful claim that happens to cite a `screen_fact` is `grounded` yet still tagged `playful`.

### Intent resolution (Req 2) — the Cartesian default

Resolution happens once, before classification, at candidate construction inside the valve (so both the classifier and the gate read the identical value, Req 2.8):

```
resolve_intent(declared_intent, has_public_anchor):
    if declared_intent in {sincere, playful, teasing, speculative}:
        return declared_intent
    # absent or out-of-set -> anchor-based default
    return sincere if has_public_anchor else speculative
```

This is the liveliness fix: an unanchored fallback claim with no declared intent becomes `speculative` → `ungrounded_aware` → eligible to surface as doubt, instead of `sincere` → `ungrounded_blind` → blocked.

### Routing by stance in `SurfaceValve` (Req 3, Req 4)

- **`grounded`** — proceeds into the existing `_apply_public_surface_gate` and the `filter()` thresholds (`min_usefulness`, `min_confidence`, `max_interrupt_cost`). If it fails a threshold it is withheld for that threshold reason, with **no** epistemic block reason recorded (Req 4.2). Public anchors are carried to the impulse (Req 4.6).
- **`ungrounded_aware`** — same thresholds as `grounded` (Req 4.3). On permit: set `metadata["epistemic_deliberate_ungrounded"] = True` (Req 4.4) and carry intent to the impulse (Req 4.5/5.11).
- **`ungrounded_blind`** — never reaches `surface_arbiter` and no public-speech impulse is emitted (Req 3.1). Record the block reason (`epistemic_confabulation_blocked`, or `epistemic_self_knowledge_failure` for a Self_Knowledge_Failure, Req 3.2/3.5), retain stance + reason on metadata (Req 3.6), and route the candidate to the `body_only` channel — never discard (Req 3.7/3.8).

### Interaction with the existing public-surface gate

`_apply_public_surface_gate` already contains independent logic (`api_invalid_json` hard-reject, `novelty`/`repetition`/`evidence_strength` thresholds, `semantic_family` checks). Ordering is defined to avoid contradiction:

1. **Epistemic classification + block decision runs first.** If stance is `ungrounded_blind`, the candidate is routed to `body_only` and returned immediately; the public-surface gate is not consulted for public emission.
2. For `grounded`/`ungrounded_aware`, the **existing** `_apply_public_surface_gate` still applies unchanged. The existing `api_invalid_json` → reject behavior is preserved: an `api_invalid_json` candidate continues to be withheld from public speech by that pre-existing rule. Epistemic routing does not loosen it; both must pass.

This makes the epistemic layer strictly *additive* to the existing safety gate: a claim must satisfy both the epistemic invariant and the pre-existing public-surface conditions to reach `surface_arbiter`.

## Components and Interfaces

### New: `epistemic.py` (private_mind package)

A pure, dependency-free module so the classifier is trivially testable and deterministic (Req 1.7).

```python
# src/cortex/private_mind/epistemic.py
from typing import Literal

EpistemicStance = Literal["grounded", "ungrounded_aware", "ungrounded_blind"]
Intent = Literal["sincere", "playful", "teasing", "speculative"]

VALID_INTENTS: frozenset[str] = frozenset({"sincere", "playful", "teasing", "speculative"})
VALID_STANCES: frozenset[str] = frozenset({"grounded", "ungrounded_aware", "ungrounded_blind"})
DELIBERATE_INTENTS: frozenset[str] = frozenset({"playful", "teasing", "speculative"})

CONFABULATION_BLOCKED = "epistemic_confabulation_blocked"
SELF_KNOWLEDGE_FAILURE = "epistemic_self_knowledge_failure"


def normalize_intent(value: object) -> str | None:
    """Return a valid intent string, or None if absent/out-of-set."""
    v = str(value or "").strip().lower()
    return v if v in VALID_INTENTS else None


def resolve_intent(declared: object, *, has_anchor: bool) -> str:
    """Req 2: anchored+undeclared -> sincere; unanchored+undeclared -> speculative (doubt)."""
    norm = normalize_intent(declared)
    if norm is not None:
        return norm
    return "sincere" if has_anchor else "speculative"


def classify_epistemic_stance(*, has_anchor: bool, intent: str) -> str:
    """Req 1: total, pure mapping (has_anchor, intent) -> stance."""
    if has_anchor:
        return "grounded"
    if intent in DELIBERATE_INTENTS:
        return "ungrounded_aware"
    # sincere, or anything not deliberate, with no anchor
    return "ungrounded_blind"
```

`resolve_intent` + `classify_epistemic_stance` are the only logic the valve calls; both are pure functions of their inputs, satisfying the determinism criterion (Req 1.7) and the equal-handling-across-producers criterion (Req 4.7).

### Modified: `SurfaceValve` (`surface_valve.py`)

`filter()` is restructured to run epistemic resolution/classification before the public-surface gate.

```python
def filter(self, judgment: InternalJudgment | None) -> SurfaceCandidate | None:
    if judgment is None or judgment.surface_candidate is None:
        return None
    candidate = judgment.surface_candidate

    # 1. resolve + stamp intent (prefer candidate intent, else judgment intent, else default)
    has_anchor = self._has_public_anchor(candidate)
    declared = candidate.intent or judgment.intent
    intent = resolve_intent(declared, has_anchor=has_anchor)

    # 2. classify stance (anchor as input, not mute switch)
    stance = classify_epistemic_stance(has_anchor=has_anchor, intent=intent)
    candidate = self._stamp_epistemic(candidate, stance=stance, intent=intent)

    # 3. confabulation invariant: withhold public, keep alive on body_only
    if stance == "ungrounded_blind":
        return self._withhold_to_body_only(candidate, judgment=judgment)

    # 4. existing public-surface gate + thresholds (unchanged behavior)
    candidate = self._apply_public_surface_gate(candidate, judgment=judgment)
    ...  # existing min_usefulness / min_confidence / max_interrupt_cost / _looks_private logic
```

New private helpers:

- `_stamp_epistemic(candidate, *, stance, intent) -> SurfaceCandidate` — returns a copy with `epistemic_stance`/`intent` set and, for `ungrounded_aware`, `metadata["epistemic_deliberate_ungrounded"]=True` when later permitted.
- `_withhold_to_body_only(candidate, *, judgment) -> SurfaceCandidate` — sets `channel="body_only"`, records the block reason (`epistemic_self_knowledge_failure` if the stance came from an undeterminable intent, else `epistemic_confabulation_blocked`), retains stance + reason on metadata. Returns the candidate (not `None`) so cognition persists; `filter()` returns it as a body-only candidate.

`to_surface_impulse()` is extended to copy `epistemic_stance` and `intent` onto the emitted `SurfaceImpulse` (Req 4.5, 5.11). For an `ungrounded_aware` impulse the existing `llm_contract` text is augmented so downstream speech reflects the deliberate/speculative purpose.

### Modified: data contracts

`InternalJudgment` and `SurfaceCandidate` (`contracts.py`) and `SurfaceImpulse` (`surface_arbiter.py`) each gain the two fields. Because the private-mind dataclasses use `@dataclass(slots=True)`, the new fields are declared as slots with defaults and normalized in `__post_init__`.

## Data Models

### Shared helpers in `contracts.py`

```python
_VALID_INTENTS = ("sincere", "playful", "teasing", "speculative")
_VALID_STANCES = ("grounded", "ungrounded_aware", "ungrounded_blind")

def normalize_stance(value: Any) -> str | None:
    v = str(value or "").strip().lower()
    return v if v in _VALID_STANCES else None  # invalid/absent -> None (Req 5.1/5.9)

def normalize_intent_field(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in _VALID_INTENTS else "sincere"  # invalid/absent -> sincere (Req 5.2/5.8)
```

Note: at the contract layer an undeclared `intent` normalizes to `sincere` (Req 5.5/5.8). The Cartesian *anchor-aware* defaulting (`speculative` when unanchored) is applied later, in the valve via `resolve_intent`, where anchor presence is known. The contract default is the safe baseline; the valve refines it.

### `InternalJudgment` (additions)

| Field | Type | Default | Notes |
|---|---|---|---|
| `epistemic_stance` | `str \| None` | `None` | Null until the classifier assigns it (Req 5.1/5.5). Validated via `normalize_stance`. |
| `intent` | `str` | `"sincere"` | Validated via `normalize_intent_field` (Req 5.2/5.8). |

`__post_init__` normalizes both; `to_dict` emits both, with `epistemic_stance: null` when unset (Req 5.6); `from_mapping` reads `epistemic_stance`/`intent`, applying validation/defaulting (Req 5.5/5.8/5.9).

### `SurfaceCandidate` (additions)

Same two fields and same normalization/serialization rules (Req 5.3/5.4/5.6). When a `SurfaceCandidate` is created from an `InternalJudgment`, the judgment's `intent` is copied unchanged (Req 5.7).

### `SurfaceImpulse` (additions)

| Field | Type | Default | Notes |
|---|---|---|---|
| `epistemic_stance` | `str \| None` | `None` | Copied from candidate on emit (Req 5.10/5.11). |
| `intent` | `str` | `"sincere"` | Copied from candidate on emit. |

`to_context()` includes both fields, emitting `null` for an unset stance (Req 5.12).

## Error Handling

- **Out-of-enum intent** (mapping construction): discarded, replaced with `sincere` at the contract layer (Req 5.8); the valve may further refine to `speculative` when unanchored (Req 2.4).
- **Out-of-enum stance** (mapping construction): discarded, set to `None` for the classifier to assign (Req 5.9).
- **Undeterminable stance at classification time** (defensive — should not occur after `resolve_intent`): treated as a Self_Knowledge_Failure, stance `ungrounded_blind`, reason `epistemic_self_knowledge_failure`, routed to `body_only` (Req 3.4/3.5).
- **No silent drops**: a blocked `ungrounded_blind` candidate is always returned on `body_only` with stance + reason retained, never `None` (Req 3.6/3.8).

## Correctness Properties

These invariants must hold for every claim processed by the valve, regardless of producer (model adapter or deterministic fallback).

### Property 1: Total classification

Every candidate that reaches a surface decision has a non-null `epistemic_stance` ∈ {`grounded`, `ungrounded_aware`, `ungrounded_blind`}. There is no path to `surface_arbiter` with an unset stance.

**Validates: Requirements 1.1, 5.1**

### Property 2: Determinism

`classify_epistemic_stance(has_anchor, intent)` and `resolve_intent(declared, has_anchor)` are pure functions: identical inputs always yield identical outputs, with no hidden state or time/RNG dependence.

**Validates: Requirements 1.7, 4.7**

### Property 3: Doubt-not-lie default

An unanchored claim with no valid declared intent is `speculative` → `ungrounded_aware`, never `ungrounded_blind`. `ungrounded_blind` is reachable only by an explicit `sincere` intent without an anchor, or by a defensive Self_Knowledge_Failure.

**Validates: Requirements 2.3, 2.5, 1.4**

### Property 4: No silent confabulation

No `ungrounded_blind` claim is ever emitted as a public-speech `SurfaceImpulse`; every blocked claim carries an explicit stance and a recorded block reason.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 5: Cognition never zero

An `ungrounded_blind` claim is never discarded; it is always returned on the `body_only` channel with stance + reason retained.

**Validates: Requirements 3.6, 3.7, 3.8**

### Property 6: Additive safety

A claim reaches `surface_arbiter` only if it passes both the epistemic invariant and the pre-existing public-surface gate (including `api_invalid_json` rejection). The epistemic layer never loosens an existing rejection.

**Validates: Requirements 4.1, 4.3**

### Property 7: Intent preservation

A claim's resolved `intent` is carried unchanged from candidate → impulse, and is preserved even when the stance is `grounded`.

**Validates: Requirements 1.8, 5.7, 5.11**

## Testing Strategy

Unit tests, mapped to acceptance criteria:

- **Classifier purity/totality (R1):** table-driven tests over all `(has_anchor ∈ {T,F}) × (intent ∈ {sincere, playful, teasing, speculative, "", "garbage"})` combinations asserting the expected stance; a determinism test asserting equal inputs → equal output (R1.7); a test that a `grounded` claim keeps a `playful` intent (R1.8).
- **Intent resolution (R2):** unanchored+undeclared → `speculative`; anchored+undeclared → `sincere`; out-of-set → anchor-based default; fallback-path claim (unanchored, undeclared) ends `speculative` and is eligible to surface (R2.5).
- **Confabulation invariant (R3):** `ungrounded_blind` never reaches `surface_arbiter` and emits no public impulse; reason recorded (`epistemic_confabulation_blocked` vs `epistemic_self_knowledge_failure`); candidate returned on `body_only` with stance + reason retained (not dropped).
- **Differential surfacing (R4):** `grounded` and `ungrounded_aware` subject to identical thresholds; threshold-withheld `grounded` carries no epistemic block reason; `ungrounded_aware` permit sets `epistemic_deliberate_ungrounded=True` and intent flows to the impulse; grounded anchors flow to the impulse; same handling for model vs deterministic-fallback origin (R4.7).
- **Contracts (R5):** field presence/defaults/null handling, `to_dict`/`to_context` include both fields, judgment→candidate→impulse intent propagation, out-of-enum rejection for both fields on all three contracts.
- **Gate composition:** an `api_invalid_json` candidate that is `grounded`/`ungrounded_aware` is still withheld from public speech by the pre-existing rule (epistemic layer does not loosen it).
