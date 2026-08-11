# Neuro Parallel V31

## Runtime contract

Direct chat is availability-first. Subject Core finalizes a deterministic fast-gate decision without waiting for remote Neuro cognition. If the user-origin action competition remains meaningfully ambiguous, the selector emits `parallel_review_recommended` as a typed advisory signal.

The advisory job is queued during Subject ingress and released only after the public writer has produced a reply. This preserves chat/provider priority while allowing slow cognition to overlap with later public-turn work such as parsing, playback, and post-turn processing. The `neuro_continuation` inference lane is optional and lower priority than chat and current-turn TTS.

A slow Neuro result is advisory only. It cannot finalize or rewrite the already committed Subject decision. Runtime accepts a callback only when the result is still bound to the current conversation epoch, includes a non-empty semantic follow-up brief, has sufficient confidence, and either changes the selected semantic direction or reports a material delta above the continuation threshold.

Accepted advice becomes an `ExecutiveAffordance(owner="neuro_continuation", claim_required=True)`. It returns through the normal self-turn competition and initiative governor, preserving the existing `single_writer` invariant. The background worker never speaks directly.

## Cancellation and staleness

Every user turn advances a conversation epoch and cooperatively cancels older Neuro scopes. A result from an older epoch is discarded. If the public writer fails to produce a first reply, the current Neuro job is cancelled because there is no valid public turn to continue.

## Deliberation split

`requires_deliberation` remains the blocking/high-stakes signal used by autonomous action selection. `parallel_review_recommended` is a separate direct-chat advisory signal. Entropy alone is diagnostic and never activates either path. Homogeneous social ties fast-commit without background review.

This separation prevents conversational uncertainty from being mistaken for semantic difficulty while still allowing unresolved user-turn ambiguity to receive a low-priority second look without adding human-facing latency.
