# Task 1 Report: Typed Pedagogical Contracts

## TDD Evidence

- Added `src/tests/test_pedagogical_contracts.py` before the implementation.
- Red run: `pytest -q src/tests/test_pedagogical_contracts.py` failed during collection with `ModuleNotFoundError: runtime.pedagogical_contracts`.
- Green run: `pytest -q src/tests/test_pedagogical_contracts.py` passed, `4 passed`.
- Full repository run: `pytest -q` reached collection but stopped on the pre-existing missing module `tools.run_v103_nervous_replay` in `src/tests/test_v103_final2_verification.py`.

## Changed Files

- `src/runtime/pedagogical_contracts.py`: frozen/slots contracts, bounded serializers, status normalization, and directive validation.
- `src/tests/test_pedagogical_contracts.py`: round-trip, fail-closed, budget, immutability, and bounded-field tests.

## Self-Review

- Contract objects are immutable and slot-backed.
- Episode status normalization accepts only the eleven specified statuses and rejects unknown payloads.
- Episode creation initializes planning status, revision one, zero counters, and no pending chunk.
- Ratios are clamped to `0.0..1.0`; persisted strings and identifiers are bounded.
- Directive hard limits are validated centrally, with the specified `directive_budget_exceeded` reason.
- No raw chat content or chain-of-thought fields are represented.

## Concerns

- The broader suite cannot complete because the checkout lacks `tools.run_v103_nervous_replay`; this is unrelated to Task 1 and was present before these changes.
- Plan cardinality (3-8 concepts) is represented by the bounded plan container and should be enforced by the Task 4 plan builder when rejecting malformed provider payloads.

## Review Fixes

- Enforced `TeachingPlan` concept cardinality at construction: fewer than three or more than eight concepts now fail closed with a `ValueError` instead of being silently accepted/truncated.
- Added finite timestamp normalization and bounded integer normalization for episode revisions/counters and directive/receipt revisions.
- Normalized directive and receipt boolean fields to actual booleans, including string and invalid-object inputs.
- Updated directive validation to reject zero or negative chunk budgets.
- Added three focused regression tests covering these review findings; focused suite now reports `7 passed`.
