# Requirements Document

## Introduction

ERIS chat replies collapse into the generic "helpful assistant" register on social/conversational
turns (disclaimers, over-helpfulness, cheerleading, therapist check-ins, assistant menus), because
a remote instruction-tuned model authors the whole reply and its RLHF attractor fires at the first
token. This feature makes the persona own the generation boundary on social-register turns: a
`RelationalVoiceSeedAdapter` produces a short ERIS-voice opening **seed** via the gemma/style
client, then has the llama/main client **continue** from that seed, joining by string
concatenation. Task-register turns (technical/code, tool/direct-action, factual recall,
insult/boundary) keep the existing single-llama path. Scope is configurable; the prior A–D patches
remain as a downstream safety net.

These requirements are derived from `design.md` (design-first). Each design Correctness Property
(P1–P8) maps to at least one acceptance criterion below.

## Glossary

- **Voice-seed path**: the two-model flow where gemma authors an opening seed and llama continues it.
- **Seed**: a short, stance-locked ERIS-voice opening fragment produced by the gemma/style client.
- **Continuation**: a one-clause completion of the seed produced by the llama/main client.
- **Join**: `seed + " " + continuation` via string concatenation (not assistant-prefill).
- **SOCIAL register**: conversational turns (emotional, relational, identity, opinion, greeting,
  smalltalk, reaction) where the assistant attractor leaks.
- **TASK register**: technical/code, command, tool/direct-action, factual-recall, insult/boundary
  turns that keep the legacy single-llama path.
- **Scope**: `ERIS_VOICE_SEED_SCOPE` ∈ {off, relational, social, always}; gate breadth knob.
- **RelationalAct**: demoted sub-signal that shapes seed direction (and is the trigger only under
  `scope == relational`).
- **Degrade ladder**: provider-aware fallbacks (joined → seed-alone → legacy → no-fallback).
- **A–D net**: the prior post-generation disclaimer guard / repair contract / flag-imperative /
  few-shot patches kept as the downstream safety net.

## Requirements

### Requirement 1: Register-based trigger gate

**User Story:** As ERIS, I want only conversational (social-register) turns to take the voice-seed
path, so that technical/tool work is not fragmented or slowed, while the AI-tell attractor is
denied across the whole social register rather than a narrow phrase/act whitelist.

#### Acceptance Criteria
1. WHEN a chat turn is classified as the SOCIAL register (not code/command/insult, and not an
   upstream direct-action/repeat/grounding-preempt or memory-recall route) THEN the system SHALL
   route the turn to the `RelationalVoiceSeedAdapter` voice-seed path.
2. WHEN a chat turn is classified as the TASK register (`ti_report.mode == "chat_code"`,
   `_looks_like_code_request`, `ChatAct.COMMAND_STYLE`, `ChatAct.INSULT_PROVOCATION`, or
   `ChatAct.IDENTITY_REDUCTION`) THEN the system SHALL NOT take the voice-seed path and SHALL use
   the existing `generate_chat_reply` single-llama path, for any scope below `always`.
3. WHEN a direct-action/tool turn, repeat-guard, grounding-preempt, or memory-recall route has
   already produced a decision upstream THEN the system SHALL NOT consult the voice-seed gate for
   that turn.
4. The register SHALL be derived only from signals already computed in `_run_chat_cycle_inner`
   (`ti_report.mode`, `classify_chat_act`, `_looks_like_code_request`) WITHOUT issuing an extra
   model call.

### Requirement 2: Configurable scope

**User Story:** As the operator, I want to tune how broadly the voice-seed path fires via one env
var, so that I can balance persona coverage against latency/cost without code changes.

#### Acceptance Criteria
1. The system SHALL read `ERIS_VOICE_SEED_SCOPE` into `VoiceSeedScope`, defaulting to `social`
   for any unset or unrecognized value.
2. WHEN `scope == off` THEN `should_use_voice_seed` SHALL return `False` for every turn (feature
   inert; only the A–D net runs).
3. WHEN `scope == relational` THEN the path SHALL fire only when `detect_relational_act` returns a
   non-`NONE` act (legacy narrow whitelist behavior).
4. WHEN `scope == social` THEN the path SHALL fire for every SOCIAL-register turn and SHALL NOT
   fire for TASK-register turns.
5. WHEN `scope == always` THEN the path SHALL fire for every chat turn that survived the upstream
   direct-action/tool routes, including TASK-register turns.

### Requirement 3: gemma seed, llama continuation, and join

**User Story:** As ERIS, I want my own voice to set the opening of social replies and the remote
model only to continue it, so that the assistant attractor never gets the first token.

#### Acceptance Criteria
1. WHEN the voice-seed path fires THEN the system SHALL request a short, stance-locked ERIS-voice
   opening seed from the gemma/style client (`self.style_client`) using a prompt that includes
   `STYLE_FALLBACK_PROMPT`, `ANTI_DISCLAIMER_FEWSHOT`, and the patch-C flag imperatives.
2. The seed SHALL be a short fragment (≤ `seed_max_words`, target ≤ ~120 chars), not a full reply.
3. WHEN a clean seed exists AND the llama/main client (`self.client`) is available THEN the system
   SHALL request a one-clause continuation framed as continuing ERIS's already-started line (not
   restarting, not a disclaimer or offer of help).
4. WHEN both seed and continuation are clean THEN the final text SHALL equal `seed + " " +
   continuation` produced by string concatenation, NOT assistant-prefill.
5. The join SHALL remove a leading echo of the seed from the continuation; IF the continuation is
   a pure echo of the seed THEN the result SHALL be the seed alone.

### Requirement 4: Bounded model usage

**User Story:** As the operator, I want each qualifying turn to cost at most one gemma call and one
llama call, so that the feature reduces (not amplifies) load on the rate-limited llama provider.

#### Acceptance Criteria
1. For each qualifying turn the adapter SHALL invoke `style_client.create_chat_completion` at most
   once and `client.create_chat_completion` at most once.
2. The adapter SHALL NOT add its own retry loop; 429 key rotation SHALL be delegated to the
   in-client bounded `key_pool.rotate()` pass.
3. On a social turn the llama continuation SHALL be capped at `continuation_max_tokens` so llama
   writes only a short tail.

### Requirement 5: Provider-aware degrade ladder

**User Story:** As the user, I want ERIS to always say something coherent even when a provider is
rate-limited, so that I never get a silent freeze or a crash.

#### Acceptance Criteria
1. WHEN the llama continuation fails (HTTP 429 after key rotation, timeout, empty, or a dirty-tail
   that fails `_reroll_still_disclaimer`) THEN the system SHALL return the clean gemma seed alone
   as a complete `Decision`.
2. WHEN the gemma seed cannot be produced (429 after key rotation, timeout, empty, or dirty) THEN
   `try_answer` SHALL return `None` and the turn SHALL fall through to the legacy single-llama path.
3. WHEN both providers are unavailable THEN the turn SHALL reach the existing no-fallback /
   body-only behavior in `_run_chat_cycle_inner` via the legacy path.
4. The adapter SHALL NOT raise into the chat hot path; any unexpected exception SHALL be caught and
   resolved to `None`.
5. The adapter SHALL NEVER return a `Decision` whose `text` is empty.

### Requirement 6: Disclaimer-free output at the boundary

**User Story:** As ERIS, I want neither the seed nor the joined reply to read as a corporate
assistant, so that the persona holds without relying on the downstream net.

#### Acceptance Criteria
1. At adapter exit, neither the seed nor the final joined text SHALL satisfy
   `_reroll_still_disclaimer` (both are clean).
2. IF the gemma seed itself reads as a disclaimer THEN the path SHALL fall through to the legacy
   path rather than emit it.
3. The A–D safety net (`_apply_chat_disclaimer_guard` and the grounding guard via
   `_apply_chat_final_guards`) SHALL remain applied to whatever decision this path commits.

### Requirement 7: Grounding and truthfulness preserved

**User Story:** As ERIS, I want relational stance to never masquerade as a hard fact or a
screen/memory/web claim, so that truth guards stay intact.

#### Acceptance Criteria
1. The produced `Decision` SHALL set `extracted_fact` to an empty string.
2. The produced `Decision` SHALL be routed through `_apply_chat_final_guards` before commit, so
   grounding/anti-mindreading/anti-fabrication guards still apply.
3. The seed/continuation prompts SHALL forbid fabricated screen/memory/web claims by reusing
   `STYLE_FALLBACK_PROMPT` and the inference-ladder constraints.

### Requirement 8: Adapter contract and chat_cycle integration

**User Story:** As a maintainer, I want the new adapter to follow the existing pre-LLM adapter
pattern, so that the integration is predictable and reversible.

#### Acceptance Criteria
1. `RelationalVoiceSeedAdapter` SHALL expose `try_answer(user_text, *, stance) -> Optional[Decision]`,
   mirroring `MemoryRecallAdapter`.
2. The hook `_build_relational_voice_seed_decision` SHALL be invoked in `_run_chat_cycle_inner`
   AFTER the memory-recall block and the upstream direct-action/repeat/grounding-preempt routes,
   and BEFORE `chat_generation_kwargs`/`generate_chat_reply`.
3. WHEN the hook returns a non-`None` `Decision` THEN the system SHALL set the cognitive action
   plan (`notes=("relational_voice_seed",)`), apply `_apply_chat_final_guards`, commit via
   `_commit_chat_decision`, set `last_user_text_for_semantics`, and `return`.
4. The adapter SHALL be lazily constructed via `_ensure_relational_voice_seed_adapter`, mirroring
   `_ensure_memory_recall_adapter`.

### Requirement 9: Performance expectations

**User Story:** As the operator, I want the cost profile to be explicit, so that the latency
tradeoff is intentional.

#### Acceptance Criteria
1. TASK-register turns SHALL remain single-call (legacy path); the extra call SHALL be confined to
   social-register turns.
2. The design SHALL reduce net llama token spend per social turn (llama writes only a short tail),
   even though social turns make two calls.
3. Timeouts (`seed_timeout_seconds`, `continuation_timeout_seconds`) SHALL bound each call so a
   slow provider degrades rather than hangs the chat cycle.

### Requirement 10: Offline testability

**User Story:** As a developer, I want to verify behavior without live models, so that tests are
deterministic and cheap.

#### Acceptance Criteria
1. `classify_chat_register`, `should_use_voice_seed`, `detect_relational_act`, and `_join` SHALL be
   pure, deterministic functions testable with no model.
2. `try_answer` SHALL be testable end-to-end with fake `style_client`/`client` returning canned
   strings (and raising `requests.HTTPError(429)`/timeouts) to exercise every degrade rung.
3. `should_use_voice_seed` SHALL match the scope truth table for all `(register, scope, act)`
   combinations under property-based testing (Hypothesis).
