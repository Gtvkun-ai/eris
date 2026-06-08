# Implementation Plan

## Overview

This plan implements epistemic self-awareness for ERIS's private mind: a pure stance classifier, new `epistemic_stance`/`intent` fields on three data contracts, the Cartesian intent default (unanchored → `speculative`), and the confabulation invariant in `SurfaceValve` (block public, keep `body_only`). Tasks are ordered so the pure logic and contract changes land first, then the valve integration, then tests and regression verification.

## Tasks

- [x] 1. Create the pure epistemic classifier module
  - Create `src/cortex/private_mind/epistemic.py` with no dependencies on other private_mind modules.
  - Define `VALID_INTENTS`, `VALID_STANCES`, `DELIBERATE_INTENTS` frozensets and the reason constants `CONFABULATION_BLOCKED = "epistemic_confabulation_blocked"`, `SELF_KNOWLEDGE_FAILURE = "epistemic_self_knowledge_failure"`.
  - Implement `normalize_intent(value) -> str | None` (valid value or None for absent/out-of-set).
  - Implement `resolve_intent(declared, *, has_anchor) -> str`: valid declared value passes through; otherwise `sincere` if `has_anchor` else `speculative`.
  - Implement `classify_epistemic_stance(*, has_anchor, intent) -> str`: anchor → `grounded`; else deliberate intent → `ungrounded_aware`; else → `ungrounded_blind`.
  - Keep all functions pure (no time, RNG, or I/O).
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 2.2, 2.3, 2.4_

- [x] 2. Add property-based and unit tests for the classifier module
  - Create `tests/test_epistemic.py`.
  - Table-driven test over `(has_anchor ∈ {True, False}) × (intent ∈ {sincere, playful, teasing, speculative, "", "garbage", None})` asserting expected stance.
  - Property test (determinism): same inputs always yield same output (Property 2).
  - Test `resolve_intent`: unanchored+absent → `speculative`; anchored+absent → `sincere`; out-of-set → anchor-based default.
  - Test that a deliberate intent with no anchor never yields `ungrounded_blind` (Property 3).
  - _Requirements: 1.4, 1.7, 2.3, 2.4_

- [x] 3. Add epistemic fields to the private_mind data contracts
  - In `src/cortex/private_mind/contracts.py`, add `_VALID_INTENTS`/`_VALID_STANCES` module constants and helpers `normalize_stance(value) -> str | None` and `normalize_intent_field(value) -> str` (default `sincere`).
  - Add `epistemic_stance: str | None = None` and `intent: str = "sincere"` slots to `InternalJudgment`; normalize in `__post_init__`; emit both in `to_dict` (null stance when unset); read both in `from_mapping` with validation/defaulting.
  - Add the same two fields, normalization, `to_dict`, and `from_mapping` handling to `SurfaceCandidate`.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8, 5.9_

- [x] 4. Add epistemic fields to SurfaceImpulse
  - In `src/cortex/surface_arbiter.py`, add `epistemic_stance: str | None = None` and `intent: str = "sincere"` to the `SurfaceImpulse` dataclass.
  - Include both fields in `to_context()`, emitting `null` for an unset stance.
  - _Requirements: 5.10, 5.12_

- [x] 5. Write contract tests for the new fields
  - Add tests (e.g. in `tests/test_private_mind_contracts.py`, create if absent) covering: default values, normalization of out-of-enum `intent` → `sincere`, out-of-enum `epistemic_stance` → `None`, `to_dict`/`to_context` include both fields, and intent copied unchanged when a `SurfaceCandidate` is built from a mapping.
  - _Requirements: 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.12_

- [x] 6. Integrate intent declaration in the judgment producers
  - In `src/cortex/private_mind/inner_synthesizer.py`, ensure judgments/candidates carry a declared `intent` when known (model path reads `intent` from the model mapping via `InternalJudgment.from_mapping`; deterministic-fallback candidate leaves intent unset so the valve applies the anchor-based default).
  - Copy the `InternalJudgment.intent` onto the `SurfaceCandidate` when one is constructed (Req 5.7).
  - _Requirements: 2.1, 2.5, 5.7_

- [x] 7. Wire the classifier into SurfaceValve.filter
  - In `src/cortex/private_mind/surface_valve.py`, import from `epistemic`. At the start of `filter()`: compute `has_anchor = self._has_public_anchor(candidate)`, resolve intent from candidate/judgment via `resolve_intent`, classify stance via `classify_epistemic_stance`.
  - Add `_stamp_epistemic(candidate, *, stance, intent)` returning a copy with `epistemic_stance`/`intent` set.
  - Ensure stance/intent are stamped before any routing or threshold logic so the public path always carries a non-null stance (Property 1).
  - _Requirements: 1.1, 1.5, 1.6, 1.8_

- [x] 8. Implement the confabulation-block + body_only routing
  - Add `_withhold_to_body_only(candidate, *, judgment)` that sets `channel="body_only"`, records the block reason (`SELF_KNOWLEDGE_FAILURE` for an undeterminable/self-knowledge-failure stance, else `CONFABULATION_BLOCKED`), and retains stance + reason on metadata.
  - In `filter()`: when stance is `ungrounded_blind`, return the body_only candidate immediately (never `None`, never `surface_arbiter`, no public impulse).
  - Handle the defensive Self_Knowledge_Failure path (stance undeterminable → `ungrounded_blind` + `epistemic_self_knowledge_failure`).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 9. Implement differential surfacing for grounded vs ungrounded_aware
  - For `grounded`/`ungrounded_aware`, continue into the existing `_apply_public_surface_gate` and the existing `min_usefulness`/`min_confidence`/`max_interrupt_cost` thresholds unchanged.
  - On a threshold-withheld `grounded` claim, ensure no epistemic block reason is recorded (Req 4.2).
  - When `ungrounded_aware` is permitted, set `metadata["epistemic_deliberate_ungrounded"] = True` (Req 4.4).
  - Preserve the pre-existing `api_invalid_json` rejection for both stances (Property 6).
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7_

- [x] 10. Propagate stance and intent into SurfaceImpulse
  - In `SurfaceValve.to_surface_impulse()`, copy `candidate.epistemic_stance` and `candidate.intent` onto the emitted `SurfaceImpulse` unchanged.
  - For `grounded`, ensure public-anchor references are included on the impulse evidence (Req 4.6).
  - For `ungrounded_aware`, reflect the deliberate/speculative purpose in `llm_contract` so downstream speech honors the intent (Req 4.5).
  - _Requirements: 4.5, 4.6, 5.11_

- [x] 11. Write SurfaceValve integration tests
  - Add tests in `tests/test_surface_valve.py` (create if absent): `ungrounded_blind` never returns a `surface_arbiter` candidate and never emits a public impulse, lands on `body_only` with stance + reason retained (Properties 4, 5).
  - `ungrounded_aware` unanchored claim (e.g. from a fallback candidate) surfaces and sets `epistemic_deliberate_ungrounded` and carries intent to the impulse (Property 3 liveliness fix).
  - `grounded` claim follows existing thresholds; threshold-withheld grounded claim carries no epistemic block reason.
  - An `api_invalid_json` grounded/aware candidate is still withheld from public speech (Property 6).
  - Equivalence: identical stance + intent produces identical decision regardless of model vs fallback origin (Req 4.7).
  - _Requirements: 3.1, 3.7, 4.2, 4.4, 4.5, 4.7_

- [x] 12. Run the full private_mind test suite and verify no regressions
  - Run the existing `tests/test_surface_arbiter.py` plus the new tests; fix any breakages caused by the new fields.
  - Confirm serialization round-trips (`to_dict`/`from_mapping`/`to_context`) for all three contracts include the new fields.
  - _Requirements: 5.6, 5.12_

## Notes

- The classifier (`epistemic.py`) is intentionally pure and isolated so the determinism and cross-producer-equivalence properties are easy to test and hold by construction.
- Contract changes are additive: new fields default to safe values (`intent="sincere"`, `epistemic_stance=None`), so existing serialization and call sites keep working.
- The epistemic layer is additive to the existing public-surface gate — it never loosens an existing rejection (notably `api_invalid_json`). A claim must pass both to reach `surface_arbiter`.
- Tasks 1, 3, and 4 are independent and can start in parallel; the valve integration (7–10) depends on all three plus the producer intent wiring (6).

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "3", "4"] },
    { "wave": 2, "tasks": ["2", "5", "6"] },
    { "wave": 3, "tasks": ["7"] },
    { "wave": 4, "tasks": ["8", "9"] },
    { "wave": 5, "tasks": ["10"] },
    { "wave": 6, "tasks": ["11"] },
    { "wave": 7, "tasks": ["12"] }
  ]
}
```
