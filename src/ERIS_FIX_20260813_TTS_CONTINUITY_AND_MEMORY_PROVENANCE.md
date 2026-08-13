# ERIS hotfix: TTS continuity + memory/self-history provenance

Date: 2026-08-13

## Symptoms addressed

1. A long reply split into multiple TTS clips could sound hesitant, pause for several seconds between clips, and lose one clip entirely.
2. Autonomous `user_probe` could invent a remembered premise such as "you told me before that you were trying coffee..." even when no history evidence existed.
3. Public wording could invent embodied autobiography for ERIS, e.g. "I usually drink black coffee", despite no episodic physical history.

## TTS fixes

- Conversation StageOutput may create up to 8 logical TTS segments; TaskManager now accepts the full segmented turn instead of falling back when an old prefetch threshold is exceeded.
- Multi-segment turns are always owned by `TtsTaskManager`; even a forced-inline task strategy is ignored once the transcript has already been split into provider-safe clips.
- Multi-segment synthesis automatically uses a small 2-3 worker prefetch window, even though the historical profile keeps `prefetch_workers=1` for compatibility on ordinary single-clip turns.
- `max_prefetch_segments` for the conversation profile now matches `max_tts_segments` (8).
- Legacy TTS queue fallback now defaults to 12 slots (minimum 8), enough to contain one full segmented conversation turn.
- Legacy append behavior no longer evicts an earlier segment of the same turn when the queue is full; it fails the newest append instead. Normal segmented conversation should not reach this branch.

## Memory / hallucination fixes

- Added typed claim domains:
  - `self_preference`: non-embodied preference/opinion, evidence-exempt.
  - `self_history`: autobiographical action/history, evidence-required.
- `conversation_history`, `user_statement`, `memory`, and `self_history` now require real evidence refs.
- Direct chat gets an explicit `user-statement:current-turn` evidence ref for claims about the foreground user message.
- Autonomous internal/idle/self/presence speech no longer receives conversation-history or user-statement authority merely because a social initiative exists.
- `user_probe` explicitly removes `conversation_history`, `user_statement`, and `memory` domains. A probe must ask from a real unknown rather than fabricate a prior-memory bridge.
- Added `runtime/self_biography_guard.py` as a narrow backstop against:
  - fake user-history bridges in `user_probe` (e.g. "lúc trước bạn có kể...");
  - unsupported embodied self-history (e.g. "tôi hay uống...").
- A plain preference such as "tôi nghiêng về vị đắng" remains allowed as `self_preference`.
- Direct-chat grounding retry now revalidates embodied self-history and copies the rewritten `claim_manifest` back into the accepted payload.

## Regression coverage

Added `tests/test_20260813_tts_hallucination_hardfix.py` covering:

- 5-segment turns never falling back to inline/legacy due to prefetch thresholds;
- forced-inline being ignored for already-segmented turns;
- conversation prefetch budget matching StageOutput budget;
- automatic 2+ worker prefetch for multi-segment turns;
- legacy queue headroom;
- no segment cancellation/drop across a five-segment TaskManager playback simulation;
- historical/user-statement claims requiring provenance;
- `self_preference` vs `self_history` behavior;
- `user_probe` losing history/memory claim authority;
- fake coffee-memory bridge detection;
- unsupported embodied self-history detection.

Relevant regression set after this hotfix: **251 passed**.
