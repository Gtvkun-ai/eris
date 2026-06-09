# Bugfix Requirements Document

## Introduction

The relationship state in ERIS does not respond to warm, relational user input. When the user expresses connection in natural Vietnamese phrasing such as "em cũng quan trọng với tôi" (you matter to me too) or "tôi muốn hiểu được em" (I want to understand you), the logged relationship state stays pinned at the dataclass defaults (trust=0.25, preferred_distance=0.58, mode=settled) turn after turn. The warmth the user is offering never registers.

Two root causes drive the reported symptom:

1. **Trigger almost never fires (primary).** The only path for a warm statement to raise trust and lower distance is section 9 of `RelationshipDynamicsEngine.update()`, which gates on `intimacy_pressure = max(affect.intimacy, affect.attachment) >= 0.45`. The affect signals come from `AffectSemanticClassifier`, which scores intimacy/attachment from a small accent-stripped keyword lexicon. Natural relational phrases match no token, so intimacy/attachment stay near zero, the gate never opens, and trust/distance stay frozen at defaults. Even when the gate does open, the gain is only ~0.008 trust per turn, and there is no path for a warm statement to reduce `preferred_distance` (only cold-complaint repair does that).

2. **Observability gap (secondary).** The relationship log line in `chat_cycle.py` logs only trust, rupture, and preferred_distance, and omits familiarity. Familiarity has an unconditional +0.006/turn gain, so it genuinely climbs over a session and is rendered into the prompt, but is invisible in logs. This produced the appearance of a log/prompt mismatch (e.g. a raw leak showing familiarity=0.77) when in fact there is a single state object shared by the log and the prompt. The trust=0.52 seen in the same leak has no second live source feeding the prompt and is most likely model fabrication in raw output, which the frozen real state did nothing to anchor against.

The fix must make warmth detection and state response work for natural Vietnamese relational phrasing, while preserving the system's deliberate avoidance of keyword "teleporting," its inertia/decay behavior, and its resistance to false warmth on technical, objectifying, or correcting turns. The fix must also close the logging gap so the real state is observable.

## Bug Analysis

### Current Behavior (Defect)

What currently happens when warm/relational input is processed.

1.1 WHEN the user sends a warm/relational statement whose phrasing is not in the affect lexicon (e.g. "em cũng quan trọng với tôi", "tôi muốn hiểu được em") THEN the system computes intimacy/attachment ≈ 0, the section 9 gate (`intimacy_pressure >= 0.45`) never opens, and trust stays at its default 0.25

1.2 WHEN warm/relational input arrives across multiple turns THEN the system leaves `preferred_distance` frozen at its default 0.58 because no warm-statement path reduces distance (only perceived-coldness repair does)

1.3 WHEN warm/relational input is detected weakly enough to open the section 9 gate THEN the system raises trust by only ~0.008/turn, so meaningful warmth change is effectively unreachable within a normal conversation

1.4 WHEN warm/relational input arrives THEN the system leaves `attachment_visibility` at its default 0.12, so the agent's expressed closeness does not move

1.5 WHEN a turn is processed THEN the relationship log line records only trust, rupture, and preferred_distance and omits familiarity, so the genuinely climbing familiarity value is invisible and the real injected state cannot be confirmed from logs

### Expected Behavior (Correct)

What should happen instead.

2.1 WHEN the user sends a warm/relational statement in natural Vietnamese phrasing that is not limited to the existing keyword lexicon THEN the system SHALL recognize the relational warmth strongly enough to register a meaningful (non-zero) increase in trust over the course of the interaction

2.2 WHEN sustained warm/relational input is received THEN the system SHALL reduce `preferred_distance` from its default in response to genuine warmth, not only in response to coldness complaints

2.3 WHEN warm/relational input is recognized THEN the system SHALL move trust and distance at a rate that produces an observable, intentional change over a realistic conversation rather than a rate that is effectively frozen

2.4 WHEN warmth is recognized THEN the system SHALL allow `attachment_visibility` to increase so the agent's expressed closeness reflects the warmer relationship

2.5 WHEN a turn is processed THEN the system SHALL log the relationship state including familiarity so the real, prompt-injected state is fully observable and a single source of truth is confirmable from logs

### Unchanged Behavior (Regression Prevention)

Existing behavior that must be preserved.

3.1 WHEN evidence of warmth is weak or based only on isolated keyword matches THEN the system SHALL CONTINUE TO avoid "teleporting" the state, preserving the deliberate design choice against keyword-driven instant jumps

3.2 WHEN any turn is processed THEN the system SHALL CONTINUE TO apply its existing inertia and decay behavior so state changes remain gradual and stable

3.3 WHEN the turn is technical, objectifying, or correcting (no genuine relational warmth) THEN the system SHALL CONTINUE TO NOT raise trust, attachment_visibility, or reduce preferred_distance

3.4 WHEN rupture (>= 0.55) or dignity_defense (>= 0.55) conditions are present THEN the system SHALL CONTINUE TO suppress warmth gains as it does today

3.5 WHEN state is read across `sense()`, `update()`, `commit_turn()`, and prompt rendering within a turn THEN the system SHALL CONTINUE TO use a single shared relationship state object and SHALL CONTINUE TO persist `relationship_dynamics` correctly

3.6 WHEN input does not concern relationship dynamics THEN the system SHALL CONTINUE TO produce the same non-relationship behavior it produces today
