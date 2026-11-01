# Third-Party Notices

## DeepTutor (HKUDS/DeepTutor)

- **Source:** https://github.com/HKUDS/DeepTutor
- **Referenced commit:** `ef2d9e5c`
- **License:** Apache License 2.0
- **Adapted in:** `runtime/learning_core/`

Eris does **not** embed DeepTutor as a second foreground agent. The adapted area is intentionally bounded to learning-kernel responsibilities such as data contracts, mastery/gating, learning-path navigation, review scheduling, deterministic grading, and pending-interaction mechanics.

Eris-specific code owns the surrounding runtime integration: SQLite conventions, activation into conversation, `LearningService`, `TutorReasoner` / `TutorRole`, the unified `TurnAgentLoop`, conversation pacing, voice/TTS behavior, and public-response generation.

Implementation notes:

- DeepTutor-derived concepts/algorithms were rewritten to fit Eris contracts and storage conventions.
- The learning kernel is deterministic where authority matters: evidence is committed first, mastery is recomputed from evidence, and an LLM does not directly mutate durable mastery.
- Any semantic assessment produced by an LLM is treated as a proposal that must pass through Eris runtime/kernel boundaries before becoming durable learning evidence.

See the Apache License 2.0 terms from the upstream project for the applicable license conditions.

## Py-FSRS (open-spaced-repetition/py-fsrs)

- **Source:** https://github.com/open-spaced-repetition/py-fsrs
- **Dependency:** fsrs 6.3.2, optional `tutor` extra in pyproject.toml
- **License:** MIT, distributed with the upstream package
- **Used by:** `runtime/learning_core/retention.py`

Eris imports the scheduler through its own adapter; the library's implementation
is not vendored here. Card identity, UTC observation time, review logs and dependency
version are preserved. Historical Eris heuristic stability is not treated as fitted
FSRS state. The default mode computes a shadow projection; the operator can select
FSRS scheduling explicitly with `ERIS_LEARNING_RETENTION_MODE=fsrs`.
