# Eris Subject Core implementation bundle

Implementation date: 2026-08-05
Base snapshot: `src(55)` and `body(11)`
Architecture basis: *Đặc tả kỹ thuật kiến trúc chủ thể nhân tạo Eris*

## Scope delivered

This bundle provides a feature-flagged, compatibility-first implementation of the target Subject Core architecture:

- Mind boundary: substrate measurement, appraisal, need activation and episodes, coalition arbitration, beliefs, values, narrative interpretation, reflective mismatch, authorship, continuity, competence, existential decisions, and bounded consolidation.
- Persistence boundary: SQLite migrations, WAL, foreign-key enforcement, append-only subject events, canonical JSON hashing, optimistic CAS projections, idempotency, authorship records, and world outcomes.
- Audit boundary: separate append-only forensic store, hash-chain verification, causal trace queries, and deterministic replay helpers.
- Actuator and Sandbox World boundary: typed action requests, capability tokens, path and command checks, network denial by default, simulation, idempotent outcomes, and legacy executor gating.
- Dialogue boundary: semantic-commitment plans, rolling thought buffer, natural realizer without factual additions, incremental TTS/body delivery, cancellation, and typed performance frames.
- Emergence evaluation harness: paired instances, interventions, ablation, metrics, report generation, and scenario fixtures.
- Body bridge: versioned C# parser for `eris.subject.performance`; it accepts only typed public performance fields and does not expose private Mind state.

## Rollout behavior

The new runtime is disabled by default. Enable it explicitly:

```bash
export ERIS_SUBJECT_CORE_ENABLED=1
export ERIS_SUBJECT_CORE_DATA_DIR=/absolute/path/to/data/subject_core
export ERIS_SUBJECT_WORKSPACE=/absolute/path/to/workspace
```

`runtime.subject_bootstrap.build_subject_core_components()` creates the repository, forensic audit store, SubjectService, SandboxWorld, and a scoped capability token. When an existing `ActionExecutor` is supplied, it is bound to the sandbox boundary.

The legacy `CausalAffectPipeline` remains import-compatible and can be bound to `SubjectService`; it is not silently replaced as production authority while the feature flag is disabled.

## Primary implementation paths

```text
cortex/subject/
memory/subject/
runtime/audit/
runtime/world/
runtime/dialogue/
runtime/subject_bootstrap.py
runtime/subject_runtime.py
experiments/emergence/
```

Compatibility edits:

```text
actions/executor.py
cortex/causal_affect_pipeline.py
runtime/outcome_observer.py
runtime/coordinator_bootstrap.py
pyproject.toml
```

Body addition:

```text
body/SubjectPerformanceFrame.cs
```

## Verification completed

Focused implementation and regression gate:

```text
79 passed in 0.60s
```

This consists of 26 new Subject Core, persistence, audit, sandbox, dialogue, integration, and emergence tests plus 53 existing causal-affect and V55 regression tests.

Broader repository run, excluding three test files that cannot be collected because their pre-existing `tools.*` modules are absent:

```text
827 passed, 16 failed in 17.01s
```

The remaining failures are in pre-existing V53/V54 capability-retrieval expectations and missing pre-existing utilities such as `tools.report_pdf_acceptance`, `tools.evaluate_semantic_paraphrases`, and audit helpers. They are not failures in the newly added Subject Core test set.

Additional checks:

- Python bytecode compilation completed successfully for `actions`, `cortex`, `runtime`, `memory`, `domain`, `parser_grounding`, `core`, and `experiments`.
- Bootstrap smoke test created both SQLite stores and verified empty repository and audit hash chains.
- `ruff`, `mypy`, and the Godot/.NET compiler were not installed in the execution environment, so those gates were not run.

## Important limits

This is a comprehensive first-pass implementation and rollout scaffold, not evidence that the full 20-week research program has been completed. Long-history soak testing, real-world calibration, quantified holdout validation for derived needs, security review against the deployment environment, and scientific emergence claims still require actual experiments and operational data.

The architecture intentionally does not claim consciousness. It implements traceable history-dependent behavior, bounded learning, authorship records, world resistance, and falsifiable evaluation hooks.
