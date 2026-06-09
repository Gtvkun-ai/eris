# Bugfix Design Document

## Overview

This fix makes the relationship state respond to genuine relational warmth expressed in natural Vietnamese, while preserving ERIS's deliberate refusal to let isolated keywords "teleport" the state. Work is localized to three files: `affect_semantics.py` (detection), `relationship_dynamics.py` (graded warmth response + warmth-driven distance reduction), and `chat_cycle.py` (log `familiarity` for observability). Every change stays gradient-based and inertia-respecting: the classifier emits weighted evidence and the engine applies small capped nudges, so no single message jumps the state.

## Glossary

- **Relationship state**: `RelationshipDynamicsState` (in `relationship_dynamics.py`) holding `trust`, `familiarity`, `preferred_distance`, `attachment_visibility`, `rupture`, `dignity_defense`, etc. Defaults: `trust=0.25`, `preferred_distance=0.58`, `attachment_visibility=0.12`, `familiarity=0.0`.
- **Affect signal**: `AffectSemanticSignal` produced by `AffectSemanticClassifier.analyze()`, including `intimacy` and `attachment` scores in [0,1].
- **Warmth path**: section 9 of `RelationshipDynamicsEngine.update()`, the only branch where a warm/relational statement can raise trust/attachment_visibility.
- **Teleporting**: an unwanted instant jump of relationship state caused by a single keyword. The system intentionally avoids this.
- **`intimacy_pressure`**: `max(affect.intimacy, affect.attachment)`, the quantity the warmth path gates on.

## Bug Details

When the user expresses warmth in natural Vietnamese ("em cũng quan trọng với tôi", "tôi muốn hiểu được em"), the relationship state stays pinned at defaults (`trust=0.25`, `preferred_distance=0.58`) turn after turn, and `attachment_visibility` stays at `0.12`. The warmth never registers.

Affected code:
- `src/cortex/affect_semantics.py` — `AffectSemanticClassifier`: intimacy/attachment lexicon and aggregation.
- `src/cortex/relationship_dynamics.py` — `RelationshipDynamicsEngine.update()` sections 9 (warmth) and 11 (distance).
- `src/runtime/chat_cycle.py` — relationship log line (observability).

A raw LLM leak once showed `familiarity=0.77, trust=0.52`, suggesting a log/prompt mismatch. Investigation shows there is a single shared state object; the apparent mismatch is an observability gap plus model fabrication (see Hypothesized Root Cause).

## Expected Behavior

- Warm/relational input in natural Vietnamese is recognized strongly enough to register a meaningful, non-zero increase in trust over an interaction. (req 2.1)
- Sustained genuine warmth reduces `preferred_distance` from its default, not only coldness complaints. (req 2.2)
- Trust and distance move at an observable rate over a realistic conversation rather than effectively frozen. (req 2.3)
- `attachment_visibility` increases as the relationship warms. (req 2.4)
- The relationship log line includes `familiarity` so the real, prompt-injected state is observable and single-sourced. (req 2.5)
- Preserved: no keyword teleporting (3.1), inertia/decay (3.2), no warmth on technical/objectifying/correcting turns (3.3), suppression under rupture/dignity ≥ 0.55 (3.4), single shared state + correct persistence (3.5), unchanged non-relationship behavior (3.6).

## Hypothesized Root Cause

**Primary — warmth signal never reaches the trigger.** `AffectSemanticClassifier` sums small weighted phrases on accent-stripped text. The current intimacy/attachment lexicon (`nho` 0.14, `yeu` 0.18, `gan bo` 0.22, `dung bo` 0.35, `o lai` 0.28) matches none of the natural relational phrasing the user actually types, so `intimacy ≈ attachment ≈ 0`. Section 9 gates on `intimacy_pressure >= 0.45`, so the gate never opens; trust stays `0.25`, attachment_visibility stays `0.12`. Section 11 derives distance from `closeness_pull = trust*0.010 + familiarity*0.006` (~0.0025/turn at defaults) offset by `defense_push`, and there is no direct warmth→distance reduction (only section 4b coldness-repair lowers distance), so `preferred_distance` stays `0.58`. Even if the gate opened, trust gain is only `+0.008/turn`.

**Secondary — observability gap.** The `chat_cycle.py` relationship log line logs only `trust | rupture | preferred_distance` and omits `familiarity`. `familiarity` has an unconditional `+0.006/turn` gain, so it genuinely climbs and is rendered into the prompt via `to_prompt_context()` — but is invisible in logs. `sense()` and `commit_turn()` both preserve `relationship_dynamics`, so there is one shared state object across update/prompt/persist. The leaked `familiarity=0.77` is likely real-but-unlogged; the leaked `trust=0.52` (vs rendered `0.25`) has no second source and is most likely model fabrication, unanchored because the real trust was frozen.

## Correctness Properties

### Property 1: Recognition
For the target warm phrases, `intimacy >= 0.30` and `attachment >= 0.30` after `analyze()`.

**Validates: Requirements 2.1**

### Property 2: No teleport
A single low-weight token keeps `intimacy_pressure` below the warmth floor; one warm turn does not move trust by more than one nudge.

**Validates: Requirements 3.1**

### Property 3: Monotonic bounded warmth
Sustained warm turns increase `trust` and `attachment_visibility` and decrease `preferred_distance`, all clamped to [0,1].

**Validates: Requirements 2.2, 2.3, 2.4, 3.2**

### Property 4: Suppression
With `rupture >= 0.55` or `dignity_defense >= 0.55`, warmth gain is zero.

**Validates: Requirements 3.4**

### Property 5: Negative turns
Technical/objectifying/correcting turns produce no warmth gain.

**Validates: Requirements 3.3**

### Property 6: Single source
Logged state equals the state rendered into the prompt within a turn (now including familiarity).

**Validates: Requirements 2.5, 3.5**

## Fix Implementation

### Fix 1 — Detect natural relational warmth (`affect_semantics.py`)

**1a. Widen `intimacy`/`attachment` phrase groups** with natural Vietnamese relational expressions at moderate weights (~0.18–0.30), so no single phrase alone clears a downstream gate:
- `intimacy`: `quan trong voi`, `quan trong voi toi`, `muon hieu`, `hieu duoc em`, `hieu em`, `quan tam`, `tran trong em`, `coi trong`, `can em`, `muon o ben`, `o ben em`.
- `attachment`: `khong muon mat`, `muon gan`, `giu em`, `luon o day`.

**1b. Add a bounded positive-warmth prototype** (symmetric to the existing `phu_phang_tinh_cam` rejection prototype). When a second-person relational target (`em`, `cau`) co-occurs with a caring/understanding verb (`quan trong`, `muon hieu`, `tran trong`, `quan tam`, `coi trong`), set bounded floors:
```text
intimacy   = max(intimacy, ~0.55)
attachment = max(attachment, ~0.50)
```
Bounded at ≈0.5–0.6 (not the 0.9 of acute rejection prototypes) so warmth is recognized but earns state change gradually. Guard so it does NOT fire when conflict/objectification/correction/perceived_rejection dominate the same turn (preserves 3.3).

**1c. Evidence labels** for each added phrase/prototype (`intimacy:quan trong voi`, `prototype:relational_warmth`) per the module convention.

### Fix 2 — Respond to warmth gradually (`relationship_dynamics.py`, `update()` section 9 + 11)

Make the warmth path graded and add a warmth-driven distance reduction, keeping the rupture/dignity gate:
```python
if intimacy_pressure >= 0.30 and current.rupture < 0.55 and current.dignity_defense < 0.55:
    warmth = intimacy_pressure
    current.attachment_visibility = _nudge(current.attachment_visibility,
        0.010 + warmth*0.030 + current.trust*0.010)
    current.trust = _nudge(current.trust, 0.010 + warmth*0.018)
    current.preferred_distance = _nudge(current.preferred_distance, -(0.012 + warmth*0.028))
    notes.append(f"attachment:warmth_gain:{warmth:.2f}")
```
- Lower floor (0.30) + scaled gains make ~10–20 sustained warm turns visibly change the relationship (2.3).
- New `preferred_distance` reduction gives warmth its own distance path (2.2).
- All changes use `_nudge`/`clamp01`; section 11 distance inertia and section 4b repair caps stay untouched (3.2).
- **Anti-teleport guard (3.1):** gate on prototype/aggregate `intimacy_pressure` (multi-cue) and/or a minimum `event.event_confidence`; lone weak tokens stay below 0.30.

### Fix 3 — Log full relationship state (`chat_cycle.py`)

Extend the relationship log line (additive only, no behavior change):
```python
self.logger.info(
    "[relationship dynamics] event=%s | trust=%.2f | familiarity=%.2f | attachment_vis=%.2f | rupture=%.2f | distance=%.2f | notes=%s",
    relationship_report.state.last_event,
    relationship_report.state.trust,
    relationship_report.state.familiarity,
    relationship_report.state.attachment_visibility,
    relationship_report.state.rupture,
    relationship_report.state.preferred_distance,
    ",".join(relationship_report.notes) or "none",
)
```

### Requirements mapping

| Req | Fix |
|---|---|
| 2.1 | Fix 1a/1b/1c |
| 2.2 | Fix 2 (distance path) |
| 2.3 | Fix 2 (floor + scaled gains) |
| 2.4 | Fix 2 |
| 2.5 | Fix 3 |
| 3.1 | Fix 1 moderate weights + Fix 2 graded floor/confidence guard |
| 3.2 | Fix 2 (`_nudge`/`clamp01` only) |
| 3.3 | Fix 1b guard + Fix 2 rupture/dignity gate |
| 3.4 | Fix 2 retains gate |
| 3.5 | Unchanged; Fix 3 additive logging |
| 3.6 | Changes scoped to warmth path only |

## Testing Strategy

Targeted unit tests (no full-system run required):

1. **Detection (P1, 2.1):** `analyze()` on "em cũng quan trọng với tôi" and "tôi muốn hiểu được em" → `intimacy >= 0.30`, `attachment >= 0.30`, warmth evidence present.
2. **No teleport (P2, 3.1):** a single low-weight token keeps `intimacy_pressure` below floor; one `update()` call leaves trust unchanged.
3. **Sustained warmth (P3, 2.2/2.3/2.4):** feed ~12 warm events from default state; assert `trust` rises meaningfully (e.g. > 0.40), `preferred_distance < 0.58`, `attachment_visibility > 0.12`, all monotonic and ≤ 1.0.
4. **Negative guards (P5, 3.3):** technical-only, objectifying, and correction turns produce no warmth gain.
5. **Suppression (P4, 3.4):** with `rupture >= 0.55` or `dignity_defense >= 0.55`, a warm event yields no warmth gain.
6. **Logging (P6, 2.5):** the new log line renders `familiarity` and `attachment_visibility` without error.

Regression: run the existing relationship/affect test suite (`pytest` under the project's test layout) for 3.2/3.5/3.6. Remove any temporary scratch files after verification.
