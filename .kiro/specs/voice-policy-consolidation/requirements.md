# Requirements — VoicePolicy Consolidation (Nước 1)

## Introduction

ERIS' persona/voice and its "forbidden register" (the corporate help-desk / "I'm an AI
assistant" / flat emotion-denial voice) are currently **defined in several places that each
restate the same concept in a different textual form**. When these copies drift, the system
produces self-contradicting behavior: a guard bans a register that the prompt simultaneously
encourages, or the reroll instruction describes "clean voice" differently from the few-shot.

This feature introduces a single canonical `VoicePolicy` source of truth with **three derived
outputs**, consumed by the three existing sites — **without adding any new capability**. It is
a de-fragmentation refactor: same behavior, one definition.

### Current fragmentation (verified in code)

The **forbidden register** is defined three times:
1. `src/runtime/disclaimer_markers.py` — ASCII marker tuples used for *detection* (consumer A).
2. `src/llm/service.py:ANTI_DISCLAIMER_FEWSHOT` + the inline fallback copy in
   `RelationalVoiceSeedAdapter._anti_disclaimer_fewshot()` — prose *few-shot instruction* (consumer D).
3. `src/llm/service.py:rewrite_guard_violation_text` `disclaimer_clause` — prose *reroll instruction*.

The **persona voice constraint** is defined twice:
1. `src/llm/contracts.py:STYLE_FALLBACK_PROMPT` — the canonical persona.
2. `src/runtime/prompt_context_builder.py:_build_action_plan_context` — an inline "INFJ 5w4 594
   constraint" block (consumer C).

## Glossary

- **VoicePolicy**: the new canonical object that owns the forbidden-register data and the persona
  voice-constraint text, and exposes the three derived outputs below.
- **Consumer A (detection)**: post-generation guard (`PostGenerationFiltersMixin`) that detects
  disclaimer/help-desk text via marker tuples.
- **Consumer C (prompt constraint)**: prompt builder text that tells the model ERIS' voice rules.
- **Consumer D (few-shot)**: anti-disclaimer style demo injected into seed/continuer prompts.
- **Reroll**: `rewrite_guard_violation_text` rewrite path that repairs a blocked line.

## Requirements

### Requirement 1 — Single source of truth

**User Story:** As a maintainer, I want the persona voice and forbidden register defined exactly
once, so that changing ERIS' voice means editing one place.

#### Acceptance Criteria
1. THE system SHALL provide one module (`VoicePolicy`) that owns: the forbidden-register marker
   data, the anti-disclaimer few-shot text, the reroll disclaimer clause, and the persona
   voice-constraint block.
2. WHERE a forbidden-register phrase or voice rule is needed by a consumer, THE consumer SHALL
   obtain it from `VoicePolicy` and SHALL NOT restate it as its own literal.
3. THE `VoicePolicy` module SHALL depend only on the standard library (leaf module) so that any
   existing consumer can import it without creating an import cycle.

### Requirement 2 — Three derived outputs

**User Story:** As a maintainer, I want VoicePolicy to expose exactly the three shapes the
consumers need, so each site asks for what it needs and nothing redefines the concept.

#### Acceptance Criteria
1. THE `VoicePolicy` SHALL expose a **detection** output: the marker tuples and the predicates
   `is_disclaimer_text` / `normalize_guard_ascii` / category detection used by Consumer A.
2. THE `VoicePolicy` SHALL expose a **prompt-constraint** output (`render_prompt_constraint`) used
   by Consumer C and reusable as the few-shot (Consumer D).
3. THE `VoicePolicy` SHALL expose a **reroll-spec** output (`render_reroll_clause`) used by the
   reroll path for `violation_rule == "anti_disclaimer_voice"`.

### Requirement 3 — Behavior preservation (backward compatibility)

**User Story:** As a maintainer, I want this refactor to change structure only, so that ERIS'
observable behavior, guard strictness, and prompt content stay the same.

#### Acceptance Criteria
1. THE detection predicate `is_disclaimer_text` and the marker tuple contents SHALL remain
   byte-identical to the current values after consolidation.
2. THE guard SHALL NOT become weaker: every phrase blocked before SHALL still be blocked.
3. THE existing public import names SHALL keep working: `from runtime.disclaimer_markers import
   CHAT_DISCLAIMER_HARD_MARKERS, CHAT_DISCLAIMER_HELPER_MARKERS, CHAT_DISCLAIMER_EMOTION_MARKERS,
   is_disclaimer_text, normalize_guard_ascii` SHALL resolve unchanged.
4. THE constant `llm.service.ANTI_DISCLAIMER_FEWSHOT` SHALL keep resolving to the same text (it
   MAY become a re-export of the canonical text).
5. THE prompt text emitted for Consumer C and the reroll clause SHALL be semantically equivalent
   to today's wording (verbatim move preferred; no rewriting of the persona content in this task).

### Requirement 4 — No new capability, no scope creep

**User Story:** As the requester, I want this to stay a consolidation, so it does not turn into a
behavior change or a learning system.

#### Acceptance Criteria
1. THE feature SHALL NOT add dynamic/learned voice behavior (that is explicitly deferred — see
   "Future (out of scope)").
2. THE feature SHALL NOT alter guard rules, thresholds, or the set of consumers.
3. IF a consumer currently has a defensive fallback (e.g. the adapter's inline few-shot when the
   service constant is missing), THEN that fallback SHALL be preserved by pointing to `VoicePolicy`
   instead of an inline literal.

### Requirement 5 — Safety floor stays static

**User Story:** As the requester, I want the static guard to remain the floor, so a future
learning layer can never be the only thing preventing disclaimer leaks.

#### Acceptance Criteria
1. THE detection markers SHALL remain a static, code-defined floor owned by `VoicePolicy`.
2. THE design SHALL leave a clear seam where a future learning layer could augment (never replace)
   the static floor.

## Future (out of scope — deferred, do NOT implement here)

- **Nước 2**: turn disclaimer detection into a learning signal (negative/positive exemplars in
  AgentMind, dynamic few-shot). Deferred until there is a measurable voice-quality metric and only
  ever layered *on top of* the static floor from Requirement 5.
