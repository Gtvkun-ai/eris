# Requirements Document

## Introduction

This feature introduces an **epistemic self-awareness** capability into ERIS's private mind. Today the private-mind layer enforces honesty by *gating*: `SurfaceValve._has_public_anchor()` checks whether a claim has a real-world anchor, and if it does not, the claim is muted (`body_only`) or flagged `needs_external_evidence`. Honesty is achieved by silencing.

The design philosophy here shifts from **"honesty by gating/muting"** to **"honesty by self-knowledge."** The goal is *not* to stop ERIS from ever saying something ungrounded about the screen or world. ERIS is allowed to tease, riff, speculate, and be playful. The goal is that ERIS must always **know** which of three epistemic states a claim is in, and must never be silently in the dangerous middle state of "ungrounded but believes it's grounded."

**Guiding principle (Cartesian).** *"I think, therefore I am" — even doubt is evidence of life.* A claim made without external grounding is not, by default, a lie; by default it is a thought in doubt. Speculation and self-aware uncertainty are proof of cognition, not defects to be silenced. Therefore the absence of a Public_Anchor defaults a claim to **doubt** (`speculative`/`ungrounded_aware`), never to false certainty. The only state that is genuinely forbidden as *public assertion* is confabulation — asserting an unverifiable thing as if true. And even confabulation is never fully silenced: the thought continues to live as bodily presence (`body_only`); only the public assertion is withheld. Cognition is never cut to zero.

Three epistemic states ERIS must be self-aware of for any claim it surfaces:

1. **Grounded** (`grounded`) — the claim has a real public anchor (`screen_fact` / `vision_fact` / `user_chat` / `scene_evidence` / etc.); ERIS speaks because it believes the claim is true.
2. **Ungrounded-but-aware / deliberate** (`ungrounded_aware`) — ERIS knows there is no fresh public anchor, still chooses to speak (teasing, playful, speculative), and is *aware* it is doing so. This is the Cartesian doubt-as-life state: acceptable, expected, and the *default* for any unanchored claim. It is personality and aliveness, not a defect.
3. **Ungrounded-blind / confabulation** (`ungrounded_blind`) — ERIS asserts something it cannot verify *while believing the claim is grounded* (intent `sincere` with no anchor). This is the failure mode the feature exists to eliminate from public speech. It is reached only by an explicit sincere assertion without grounding, never as a default. When it occurs, the claim is withheld from public speech but kept alive as bodily presence rather than discarded.

The capability adds an explicit **epistemic stance** and **intent** to ERIS's data contracts (`InternalJudgment`, `SurfaceCandidate`, and the downstream `SurfaceImpulse`), repurposes the existing anchor computation as an *input to self-labeling* rather than a *mute switch*, defaults unanchored claims to doubt rather than to false certainty, and enforces the central invariant: confabulation must never surface as silent public assertion, yet cognition is never cut to zero.

## Assumptions and Known Limitations

- **Anchor detection is marker-based, not semantic.** The `grounded` stance is assigned when a recognized Public_Anchor marker is present in a Claim's evidence references (or its public anchor count is greater than zero). The classifier does **not** verify that the cited anchor actually supports the specific assertion. A Claim that references a real `screen_fact` but misinterprets or misuses it will still be classified `grounded`. Detecting that class of "anchored-but-distorted" confabulation is explicitly **out of scope** for this feature.
- **Intent is self-declared.** The `intent` value originates from the Internal_Judgment producer (model adapter or deterministic fallback). This feature governs how intent is defaulted, validated, classified, and carried forward, but does not attempt to detect a dishonestly-declared intent.

## Glossary

- **Private_Mind**: ERIS's internal cognition layer (`src/cortex/private_mind/`) that turns runtime signals into thought fragments, concerns, judgments, and surface candidates. It does not produce public speech directly.
- **Claim**: A single assertion ERIS may surface, carried by a `Surface_Candidate` (and originating in an `Internal_Judgment`). The unit that epistemic stance and intent are attached to.
- **Epistemic_Stance**: A self-knowledge label on a claim with exactly one of three values: `grounded`, `ungrounded_aware`, `ungrounded_blind`.
- **Intent**: A self-declared communicative purpose for a claim, with values including `sincere`, `playful`, `teasing`, `speculative`. Indicates *why* ERIS is surfacing the claim. Per the Cartesian principle, an unanchored claim with no declared intent defaults to `speculative` (doubt), not `sincere`.
- **Public_Anchor**: A real-world evidence reference recognized by the system. The recognized anchor markers are: `dossier.user.`, `user_chat`, `vision_fact`, `screen_fact`, `scene_evidence`, `ev.active_window`, `ev.active_app`, `runtime_event`.
- **Epistemic_Classifier**: The logic that assigns an `Epistemic_Stance` to each claim using anchor presence and ERIS's declared belief/intent as inputs.
- **Surface_Valve**: The existing filter (`surface_valve.py`) that turns an `Internal_Judgment` into a `Surface_Candidate`/`SurfaceImpulse`. Extended here to enforce the confabulation invariant.
- **Internal_Judgment**: The private-mind judgment dataclass (`contracts.py`). Gains epistemic stance and intent fields.
- **Surface_Candidate**: The filtered impulse that may rise to the `SurfaceArbiter` (`contracts.py`). Gains epistemic stance and intent fields.
- **Surface_Impulse**: The downstream object (`SurfaceImpulse` in `surface_arbiter`) that the Surface_Valve emits for a permitted Claim. Gains epistemic stance and intent fields so the declared purpose reaches public-speech generation.
- **Body_Only**: An existing Surface_Valve channel (`body_only`) on which a Claim influences ERIS's bodily/expressive presence without producing public speech. Used to keep cognition alive for a withheld `ungrounded_blind` Claim.
- **Confabulation**: The `ungrounded_blind` state — asserting an unverifiable claim while believing it grounded.
- **Self_Knowledge_Failure**: The condition where a claim's `Epistemic_Stance` cannot be determined from available signals (anchor presence and declared belief).

## Requirements

### Requirement 1: Classify the epistemic stance of every claim

**User Story:** As ERIS's designer, I want every surfaced claim to carry an explicit epistemic stance, so that ERIS always knows whether it is making a grounded claim, a deliberately ungrounded one, or a blind one.

#### Acceptance Criteria

1. WHEN a Claim is submitted to the Epistemic_Classifier prior to any Surface_Valve surface decision, THE Epistemic_Classifier SHALL assign to that Claim exactly one Epistemic_Stance value from the set {`grounded`, `ungrounded_aware`, `ungrounded_blind`} before the Claim is eligible to surface.
2. WHEN a Claim has at least one Public_Anchor, THE Epistemic_Classifier SHALL assign the Epistemic_Stance `grounded` regardless of the Claim's declared Intent.
3. IF a Claim has no Public_Anchor AND the Claim's declared Intent is one of {`playful`, `teasing`, `speculative`}, THEN THE Epistemic_Classifier SHALL assign the Epistemic_Stance `ungrounded_aware`.
4. IF a Claim has no Public_Anchor AND the Claim's declared Intent is `sincere`, THEN THE Epistemic_Classifier SHALL assign the Epistemic_Stance `ungrounded_blind`, because the Claim asserts sincere belief without grounding.
5. THE Epistemic_Classifier SHALL use the result of the existing Public_Anchor computation as an input to stance assignment rather than as a muting decision.
6. THE Epistemic_Classifier SHALL recognize a Public_Anchor when any of the anchor markers (`dossier.user.`, `user_chat`, `vision_fact`, `screen_fact`, `scene_evidence`, `ev.active_window`, `ev.active_app`, `runtime_event`) is present in the Claim's evidence references, or when the Claim's public anchor count is greater than zero.
7. WHEN the Epistemic_Classifier evaluates two Claims that have identical Public_Anchor presence and identical declared Intent, THE Epistemic_Classifier SHALL assign the same Epistemic_Stance to both Claims.
8. WHEN the Epistemic_Classifier assigns the Epistemic_Stance `grounded` to a Claim that has a declared Intent of `playful`, `teasing`, or `speculative`, THE Epistemic_Classifier SHALL retain the Claim's declared Intent unchanged so that the playful or speculative purpose is preserved alongside the `grounded` stance.

### Requirement 2: Determine and declare the intent of every claim

**User Story:** As ERIS's designer, I want each claim to carry a self-declared intent, so that an ungrounded claim can be distinguished as deliberate personality versus accidental confabulation.

#### Acceptance Criteria

1. WHEN an Internal_Judgment produces a Claim, THE Private_Mind SHALL attach exactly one Intent value to that Claim from the set {`sincere`, `playful`, `teasing`, `speculative`}.
2. IF an Internal_Judgment produces a Claim without a declared Intent AND the Claim has at least one Public_Anchor, THEN THE Private_Mind SHALL assign the default Intent `sincere`.
3. IF an Internal_Judgment produces a Claim without a declared Intent AND the Claim has no Public_Anchor, THEN THE Private_Mind SHALL assign the default Intent `speculative` so that an unanchored claim defaults to doubt rather than to false certainty.
4. IF an Internal_Judgment produces a Claim whose declared Intent value is not a member of the set {`sincere`, `playful`, `teasing`, `speculative`}, THEN THE Private_Mind SHALL discard the out-of-set value and apply the same anchor-based default rules as for an absent Intent.
5. WHEN an Internal_Judgment is produced by the deterministic fallback path without a declared Intent, THE Private_Mind SHALL apply the same anchor-based default rules, such that an unanchored fallback Claim defaults to the Intent `speculative` and remains eligible to surface as doubt.
6. WHILE the Intent is `sincere`, THE Private_Mind SHALL record on the Claim that ERIS believes the assertion to be true.
7. WHILE the Intent is one of {`playful`, `teasing`, `speculative`}, THE Private_Mind SHALL record on the Claim that it is a deliberate non-grounded expression that ERIS does not assert as verified.
8. THE Private_Mind SHALL persist the declared Intent value unchanged on the Claim so that the Epistemic_Classifier and the Surface_Valve each read an identical Intent value.

### Requirement 3: Eliminate silent confabulation (central invariant)

**User Story:** As ERIS's designer, I want confabulation to never surface silently, so that ERIS is never in the state of asserting something ungrounded while believing it is grounded.

#### Acceptance Criteria

1. IF a Claim is classified with the Epistemic_Stance `ungrounded_blind`, THEN THE Surface_Valve SHALL block that Claim from surfacing through the `surface_arbiter` channel AND SHALL NOT emit a public-speech SurfaceImpulse for that Claim.
2. WHEN the Surface_Valve blocks an `ungrounded_blind` Claim that was not produced by a Self_Knowledge_Failure, THE Surface_Valve SHALL record the reason `epistemic_confabulation_blocked` on the Claim's metadata.
3. THE Surface_Valve SHALL NOT surface any Claim whose Epistemic_Stance is `ungrounded_blind` through the `surface_arbiter` channel without an explicit recorded Epistemic_Stance value and a recorded block reason on the Claim's metadata.
4. IF a Claim's Epistemic_Stance cannot be determined from the available signals of Public_Anchor presence and declared Intent, THEN THE Epistemic_Classifier SHALL treat the Claim as a Self_Knowledge_Failure and assign the Epistemic_Stance `ungrounded_blind`.
5. WHEN a Self_Knowledge_Failure occurs, THE Surface_Valve SHALL block the Claim from surfacing through the `surface_arbiter` channel AND SHALL record the reason `epistemic_self_knowledge_failure` on the Claim's metadata in place of `epistemic_confabulation_blocked`.
6. WHEN the Surface_Valve blocks a Claim with the Epistemic_Stance `ungrounded_blind`, THE Surface_Valve SHALL retain the Claim's Epistemic_Stance value and recorded block reason on the Claim's metadata so that every blocked Claim remains auditable rather than discarded silently.
7. WHEN the Surface_Valve blocks an `ungrounded_blind` Claim from the `surface_arbiter` channel, THE Surface_Valve SHALL route the Claim to the `body_only` channel so that the thought persists as bodily presence and cognition is never cut to zero, while no public assertion is produced.
8. THE Surface_Valve SHALL NOT discard or drop an `ungrounded_blind` Claim outright; it SHALL withhold only the public assertion while preserving the Claim on the `body_only` channel.

### Requirement 4: Allow grounded and deliberately-ungrounded claims to surface differently

**User Story:** As ERIS, I want to be able to speak grounded truths and deliberate playful riffs through appropriate channels, so that my personality is preserved while my honesty stays intact.

#### Acceptance Criteria

1. WHERE a Claim has the Epistemic_Stance `grounded`, THE Surface_Valve SHALL permit the Claim to surface through the `surface_arbiter` channel only when the Claim satisfies all of the existing usefulness, confidence, and interrupt-cost thresholds.
2. IF a Claim has the Epistemic_Stance `grounded` AND the Claim fails to satisfy one or more of the existing usefulness, confidence, or interrupt-cost thresholds, THEN THE Surface_Valve SHALL withhold the Claim for that threshold reason and SHALL NOT record an epistemic block reason on the Claim's metadata.
3. WHERE a Claim has the Epistemic_Stance `ungrounded_aware`, THE Surface_Valve SHALL permit the Claim to surface through the `surface_arbiter` channel subject to the same usefulness, confidence, and interrupt-cost thresholds that apply to `grounded` Claims.
4. WHEN a Claim with the Epistemic_Stance `ungrounded_aware` is permitted to surface, THE Surface_Valve SHALL set the Claim's metadata field `epistemic_deliberate_ungrounded` to true.
5. WHEN a Claim with the Epistemic_Stance `ungrounded_aware` surfaces, THE Surface_Valve SHALL set the resulting SurfaceImpulse's Intent equal to the Claim's declared Intent so downstream speech reflects the playful or speculative purpose.
6. WHERE a Claim has the Epistemic_Stance `grounded`, THE Surface_Valve SHALL include all of the Claim's Public_Anchor references on the resulting SurfaceImpulse.
7. THE Surface_Valve SHALL apply the same surface-or-block decision and the same metadata handling to any two Claims that have an identical Epistemic_Stance and identical declared Intent, regardless of whether the Internal_Judgment originated from the model adapter or the deterministic fallback path.

### Requirement 5: Represent epistemic self-knowledge in the data contracts

**User Story:** As a developer of the private-mind layer, I want epistemic stance and intent represented as first-class fields on the data contracts, so that self-knowledge is carried explicitly rather than inferred ad hoc.

#### Acceptance Criteria

1. THE Internal_Judgment contract SHALL provide a field `epistemic_stance` that holds either a null value or exactly one value from {`grounded`, `ungrounded_aware`, `ungrounded_blind`}.
2. THE Internal_Judgment contract SHALL provide a field `intent` that holds exactly one value from {`sincere`, `playful`, `teasing`, `speculative`}.
3. THE Surface_Candidate contract SHALL provide a field `epistemic_stance` that holds either a null value or exactly one value from {`grounded`, `ungrounded_aware`, `ungrounded_blind`}.
4. THE Surface_Candidate contract SHALL provide a field `intent` that holds exactly one value from {`sincere`, `playful`, `teasing`, `speculative`}.
5. WHEN an Internal_Judgment is constructed from a mapping that omits `epistemic_stance` or `intent`, THE Internal_Judgment contract SHALL set `intent` to `sincere` and SHALL set `epistemic_stance` to a null value reserved for the Epistemic_Classifier to assign.
6. WHEN a Surface_Candidate or Internal_Judgment is serialized through its `to_dict` representation, THE contract SHALL include both the `epistemic_stance` and `intent` fields, emitting a null value for `epistemic_stance` when it is unset.
7. WHEN a Surface_Candidate is created from an Internal_Judgment, THE Private_Mind SHALL copy the Internal_Judgment's `intent` value onto the Surface_Candidate's `intent` field unchanged.
8. IF an Internal_Judgment or Surface_Candidate is constructed from a mapping that provides an `intent` value outside {`sincere`, `playful`, `teasing`, `speculative`}, THEN THE contract SHALL reject the provided value and set `intent` to `sincere`.
9. IF an Internal_Judgment or Surface_Candidate is constructed from a mapping that provides an `epistemic_stance` value outside {`grounded`, `ungrounded_aware`, `ungrounded_blind`}, THEN THE contract SHALL reject the provided value and set `epistemic_stance` to a null value for the Epistemic_Classifier to assign.
10. THE Surface_Impulse contract SHALL provide a field `epistemic_stance` that holds either a null value or exactly one value from {`grounded`, `ungrounded_aware`, `ungrounded_blind`}, and a field `intent` that holds exactly one value from {`sincere`, `playful`, `teasing`, `speculative`}.
11. WHEN the Surface_Valve emits a Surface_Impulse for a permitted Claim, THE Surface_Valve SHALL copy the Claim's `epistemic_stance` and `intent` values onto the Surface_Impulse unchanged.
12. WHEN a Surface_Impulse is serialized through its `to_dict` representation, THE contract SHALL include both the `epistemic_stance` and `intent` fields, emitting a null value for `epistemic_stance` when it is unset.
