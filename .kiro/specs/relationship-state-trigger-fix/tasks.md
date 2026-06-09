# Implementation Plan

## Overview

Localized fix across three files: `affect_semantics.py` (detect natural relational warmth), `relationship_dynamics.py` (graded warmth response + warmth-driven distance reduction), and `chat_cycle.py` (log familiarity). Test-first: reproduce the frozen-warmth defect, apply the three fixes, then convert the reproduction into passing behavior tests and run regression.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"], "depends_on": [] },
    { "wave": 2, "tasks": ["2", "3", "5"], "depends_on": ["1"] },
    { "wave": 3, "tasks": ["4"], "depends_on": ["2", "3"] },
    { "wave": 4, "tasks": ["6"], "depends_on": ["4", "5"] },
    { "wave": 5, "tasks": ["7"], "depends_on": ["6"] }
  ]
}
```

- Task 1 first (documents the defect).
- Tasks 2 and 3 are in the same file; 3 builds on 2's tokens. Task 5 (logging) is independent and can run in parallel.
- Task 4 depends on 2+3 (needs the real warmth signal).
- Task 6 depends on 4+5; Task 7 depends on 6.

## Tasks

- [x] 1. Add a reproducing test for the frozen-warmth bug
  - Create a test module under the project's test layout for the affect classifier and relationship engine warmth path.
  - Assert the CURRENT defect: `AffectSemanticClassifier.analyze("em cũng quan trọng với tôi")` and `analyze("tôi muốn hiểu được em")` return `intimacy < 0.30` and `attachment < 0.30`, and that feeding such an event through `RelationshipDynamicsEngine.update()` from default state leaves `trust == 0.25` and `preferred_distance == 0.58`.
  - This test will be inverted/extended in task 6 once the fix lands.
  - _Requirements: 1.1, 1.2, 2.1_

- [x] 2. Widen intimacy/attachment lexicon (`src/cortex/affect_semantics.py`)
  - Add natural Vietnamese relational phrases to `PHRASE_GROUPS["intimacy"]` (`quan trong voi`, `quan trong voi toi`, `muon hieu`, `hieu duoc em`, `hieu em`, `quan tam`, `tran trong em`, `coi trong`, `can em`, `muon o ben`, `o ben em`) at weights ~0.18–0.30.
  - Add to `PHRASE_GROUPS["attachment"]` (`khong muon mat`, `muon gan`, `giu em`, `luon o day`).
  - Keep weights moderate so no single phrase alone saturates a downstream gate.
  - _Requirements: 2.1, 3.1_

- [x] 3. Add bounded positive-warmth prototype to the classifier (`src/cortex/affect_semantics.py`)
  - In `analyze()`, after phrase/regex/context passes, add a warmth-aggregation prototype: when a second-person relational target (`em`, `cau`) co-occurs with a caring/understanding verb (`quan trong`, `muon hieu`, `tran trong`, `quan tam`, `coi trong`), set `intimacy = max(intimacy, ~0.55)` and `attachment = max(attachment, ~0.50)`.
  - Guard the prototype so it does NOT fire when `conflict`, `objectification`, `correction`, or `perceived_rejection` dominate the same turn.
  - Append evidence labels (`prototype:relational_warmth`, per-phrase labels).
  - _Requirements: 2.1, 3.1, 3.3_

- [x] 4. Make the warmth response graded and add a distance path (`src/cortex/relationship_dynamics.py`)
  - In `update()` section 9, lower the gate to `intimacy_pressure >= 0.30`, keep `rupture < 0.55 and dignity_defense < 0.55`.
  - Scale gains by warmth: `attachment_visibility += 0.010 + warmth*0.030 + trust*0.010`; `trust += 0.010 + warmth*0.018`.
  - Add `preferred_distance += -(0.012 + warmth*0.028)` so genuine warmth reduces distance.
  - Use only `_nudge`/`clamp01`; do not touch section 4b caps or section 11 inertia. Add an anti-teleport guard so lone weak-token turns (aggregate below 0.30) produce no gain.
  - Update the `notes.append(...)` label to `attachment:warmth_gain:{warmth:.2f}`.
  - _Requirements: 2.2, 2.3, 2.4, 3.1, 3.2, 3.4_

- [x] 5. Log familiarity and attachment_visibility (`src/runtime/chat_cycle.py`)
  - Extend the `[relationship dynamics]` log line to include `familiarity` and `attachment_vis` alongside the existing `trust | rupture | distance` fields. Additive only, no behavior change.
  - _Requirements: 2.5, 3.5_

- [x] 6. Replace the reproduction test with passing behavior tests
  - Detection (Property 1): `analyze()` on the two target phrases now yields `intimacy >= 0.30` and `attachment >= 0.30` with warmth evidence present.
  - No teleport (Property 2): a single low-weight token keeps `intimacy_pressure` below 0.30 and one `update()` call leaves trust unchanged.
  - Sustained warmth (Property 3): ~12 warm events from default state raise `trust` > 0.40, drop `preferred_distance` below 0.58, raise `attachment_visibility` above 0.12, all monotonic and ≤ 1.0.
  - Negative guards (Property 5): technical-only, objectifying, and correction turns produce no warmth gain.
  - Suppression (Property 4): with `rupture >= 0.55` or `dignity_defense >= 0.55`, a warm event yields no warmth gain.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.3, 3.4_

- [x] 7. Run regression suite and verify
  - Run the existing relationship/affect test suite (`pytest` under the project layout) to confirm unchanged behavior (3.2, 3.5, 3.6).
  - Confirm the new log line renders without error (Property 6 / 2.5).
  - Remove any temporary scratch files created during verification.
  - _Requirements: 3.2, 3.5, 3.6_

## Notes

- Keep edits minimal and scoped to the warmth path; preserve the codebase's deliberate "no keyword teleporting" design (heavy inline comments in `relationship_dynamics.py` reflect this intent).
- All numeric thresholds (0.30 gate, gain coefficients, prototype floors ~0.50–0.55) are starting calibrations; task 6 should confirm they produce a visible-but-gradual change and may be tuned within the same task.
- `pytest` is the assumed runner; confirm the project's actual test command before task 1/7 if a config (`pyproject.toml`, `pytest.ini`) indicates otherwise.
