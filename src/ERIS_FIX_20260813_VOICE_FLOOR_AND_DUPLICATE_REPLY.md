# ERIS hotfix 2026-08-13: voice floor + duplicate reply + TTS hard limit

## Runtime issues fixed

1. Public audio floor now starts at `AUDIO_BUFFERING`/TTS dispatch, not only after playback begins.
   Autonomous cognition may continue privately, but autonomous public speech is deferred while the floor is owned by a pending/playing public turn.
2. Audio floor is turn-owned. Late `done` events from an old turn cannot release a newer turn's floor.
3. Multi-segment speech keeps the floor across inter-segment gaps; an intermediate segment `done`/`failed` does not reopen autonomous speech.
4. User barge-in remains authoritative and can still supersede pending/playing audio immediately.
5. A user event that has already received a foreground chat reply is consumed for public MentalMaterial routing. Its material remains available privately, but cannot promote into concern/expression and become a second reply to the same user message.
6. Direct-user writer guidance now requires direct analysis/answer first when a retrospective/reference request is already answerable, instead of asking the user to explain their motive or choose an interpretation unnecessarily.
7. TTS hard transcript budget now overrides inline-continuity preference. Logical segments are never rejoined past `GLOBAL_TTS_REQUEST_BUDGET.max_transcript_chars`.
8. ElevenLabs no longer bypasses sentence splitting for an over-budget ordinary turn. Voice Director metadata is preserved while over-budget transcripts continue through safe splitting.

## Regression coverage

Added `tests/test_turn_floor_and_duplicate_reply_regressions.py` covering:

- pending audio owns floor before playback;
- stale completion cannot release a newer turn;
- answered user-event material remains private and cannot project a second reply;
- inline dispatcher does not rejoin segments over provider hard limit;
- StageOutput prefers extra safe segments over provider-limit violations.

Relevant test sweep after patch: **147 passed**.

A broader historical repair test (`test_plain_nhac_lai_is_not_routed_as_music_or_screen`) also fails in the untouched uploaded baseline and is unrelated to this hotfix.
