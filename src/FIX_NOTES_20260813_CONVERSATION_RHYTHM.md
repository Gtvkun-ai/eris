# ERIS Conversation Rhythm / Topic Closure Fix — 2026-08-13

## Bugs fixed

1. **Answered user-event was not actually consumed**
   - The previous duplicate-reply guard called `mark_user_event_answered(user_text, turn_id=turn_id)` from `_commit_once`, where `user_text` and `turn_id` were not in scope.
   - The exception was swallowed by the surrounding defensive `try/except`, so the bug looked patched while user-event mental material retained public speech rights.
   - The consumption call now runs in the chat turn scope immediately after the foreground assistant commit, where the real `user_text` and `turn_id` exist.

2. **Explicitly closed topics could resurrect through autonomous cognition**
   - Phrases such as “đổi chủ đề”, “cho qua”, “đi vào dĩ vãng”, “đừng nhắc nữa”, “move on”, etc. now establish a public conversation boundary.
   - Existing mental material / expression urges can remain available to private cognition, but lose public projection rights for the closed beat.
   - Active concerns are not deleted. ERIS can still think; it simply may not drag the closed topic back into speech.

3. **ERIS lacked a real conversation-leading move**
   - `UNDERSTAND_USER` already existed as a Subject motive, but the runtime bridge explicitly returned `None`, preventing that motive from ever becoming a public candidate.
   - It can now materialize as `speech_act=user_probe` when user-model uncertainty is meaningful or after a topic closure.
   - The probe must be one light, specific, non-invasive question about a real unknown: preference, habit, current interest, taste, or way of thinking.

4. **Topic transitions were too abrupt / self-monologue heavy**
   - Fresh-topic moves now carry an explicit rhythm contract: bridge naturally before switching subjects instead of hard-cutting into an unrelated monologue.
   - Surface wording is instructed to vary bridges rather than repeat one template. Natural equivalents include “à mà…”, “nói chuyện khác chút…”, or an opinion invitation such as “anh nghĩ sao?” when it actually fits.

5. **Too much self-expression, too little curiosity about the user**
   - If ERIS has taken several autonomous public turns in a row, Subject initiative now softly shifts value from `SHARE` toward `UNDERSTAND_USER`.
   - This is deliberately a bias, not a forced-question quota, so ERIS should not turn into an interviewer.

6. **Closure state lifecycle**
   - The closure remains active through ERIS's short acknowledgement so old concerns cannot immediately reappear.
   - Once ERIS genuinely crosses into a fresh `user_probe` / topic-shift move, the handoff closure phase clears while the private old-topic speech boundary remains in place.

## Main files changed

- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/conversation_handoff.py`
- `runtime/expression_consummation.py`
- `runtime/expression_urge_runtime.py`
- `runtime/mental_material_runtime.py`
- `runtime/subject_initiative_runtime.py`
- `cortex/subject/initiative.py`
- `runtime/ai_orchestrated/model_router.py`
- `tests/test_conversation_rhythm_and_closure_regressions.py`

## Verification

Focused regression suite: **141 passed**.

A broader selected suite previously showed 3 failures, all reproduced unchanged on the uploaded original source. Those tests expect legacy candidates without the newer mandatory `expression_commitment` contract; this patch does not alter that contract merely to make obsolete expectations green.
