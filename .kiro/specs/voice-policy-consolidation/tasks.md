# Tasks — VoicePolicy Consolidation (Nước 1)

- [x] 1. Create the canonical `VoicePolicy` leaf module
  - Added `src/runtime/voice_policy.py` (imports: `re`, `unicodedata`, `dataclasses` only).
  - Moved forbidden-register marker tuples (HELPER/HARD/EMOTION) verbatim from `disclaimer_markers.py`.
  - Moved `normalize_guard_ascii` + `is_disclaimer_text` verbatim.
  - Moved `ANTI_DISCLAIMER_FEWSHOT`, the reroll disclaimer clause, and the persona "INFJ 5w4 594"
    voice-constraint block as module constants.
  - Exposed `VoicePolicy` + `VOICE_POLICY` with `forbidden_markers`, `is_disclaimer`, `normalize`,
    `render_anti_disclaimer_fewshot`, `render_reroll_clause`, `render_prompt_constraint`. Added
    `# SEAM:` for the future learning layer.
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 5.1, 5.2_

- [x] 2. Convert `disclaimer_markers.py` into a thin re-export shim
  - Now re-exports `CHAT_DISCLAIMER_*`, `is_disclaimer_text`, `normalize_guard_ascii` from
    `voice_policy`. All importers unchanged.
  - _Requirements: 1.2, 3.1, 3.3_

- [x] 3. Re-export the few-shot from `llm/service.py`
  - `ANTI_DISCLAIMER_FEWSHOT = _VOICE_POLICY_FEWSHOT` (re-export); name preserved.
  - _Requirements: 1.2, 3.4_

- [x] 4. Point the reroll clause at the policy
  - `rewrite_guard_violation_text` now uses `VOICE_POLICY.render_reroll_clause()`; inline literal removed.
  - _Requirements: 1.2, 2.3, 3.5_

- [x] 5. Point the adapter few-shot fallback at the policy
  - `RelationalVoiceSeedAdapter._anti_disclaimer_fewshot()` fallback →
    `VOICE_POLICY.render_anti_disclaimer_fewshot()`; preference order preserved.
  - _Requirements: 1.2, 3.4, 4.3_

- [x] 6. Point the prompt voice-constraint at the policy
  - `_build_action_plan_context` now uses `VOICE_POLICY.render_prompt_constraint()`; inline INFJ block removed.
  - _Requirements: 1.2, 2.2, 3.5_

- [x] 7. Unit + parity tests
  - Added `tests/test_voice_policy.py`: marker-match coverage, golden snapshot, `render_*` anchors,
    shim-parity (`is` identity). 13 tests.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 8. Verify
  - Diagnostics clean on all 6 edited/new files. `python -m unittest tests.test_voice_policy` → 13/13 OK.
  - Full-deps parity run (`tests/test_relational_voice_seed.py`, guard tests) NOT run: workspace
    `.venv` lacks `requests` so the coordinator/service import graph can't load here. Pure tests +
    diagnostics cover the consolidation; texts were moved verbatim so behavior is preserved by construction.
  - _Requirements: 3.1, 3.2, 4.2_
