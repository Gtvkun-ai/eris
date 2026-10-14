# Writer-Merge Feasibility (ERIS eloquence fix) — READ-ONLY audit

## 1. Verdict (TL;DR)

- **Removing the second wording pass is MED risk, NOT required — and Option B is MUCH cheaper.** The second call (`generate_public_reply`) is not just "re-wording". It also does: display-language lock + one language-repair retry, speech/display two-surface split, JSON-schema shaping, the `prepare_candidate` → `prepare_public_output` seal (parser/stage/UDP/TTS), and the `_prelocalize_v03_speech` Japanese transcript lock. All of that would have to move into Root if the pass is deleted. The user's actual goal — "let the strong pass write the words" + "enable thinking for the public call" — is achieved with a tiny change in Option B, so **recommend Option B.**
- **The Whale/DS2API local gateway does NOT honor `reasoning_effort`, and it does NOT honor `thinking_mode='disabled'` either.** For a localhost/127.0.0.1/:6011 base_url the client **forces thinking ON** (`mode = "enabled"`) regardless of what the writer passes. So on the local gateway the user's suspicion is correct *and then some*: only the thinking flag matters, and today it is already effectively ON for the public call when run against the local Whale gateway. `reasoning_effort` is only attached when `mode=="enabled"` and is then collapsed to `"high"`/`"max"` by `deepseek.reasoning_effort()` — "low"/"medium" never reach the API.

Evidence: `src/llm/client.py:793-810` (`is_ds2api` → `mode="enabled"`; effort only set in enabled branch), `src/llm/deepseek.py:69-73` (`reasoning_effort()` returns only `high`/`max`).

---

## 2. Q1 — What the second pass does beyond wording, and Option A vs B

### 2a. Extra responsibilities of `generate_public_reply` (each must be preserved if the pass is removed)

- **Display-language enforcement + repair retry.** `_public_display_language_mismatch()` detects CJK bleeding into Vietnamese display, then one provider retry with a LANGUAGE-REPAIR system message. `model_router.py:1946-1979`; detector at `model_router.py` `_public_display_language_mismatch` (approx. :116-150).
- **Speech/display two-surface split.** Contract requires `text` (display, vi) and `speech_text` (speech, ja) as distinct surfaces. `_public_reply_prompt` says text is display and speech_text is spoken; `PUBLIC_REPLY_CORE_SCHEMA` requires `should_speak,text,speech_text`.
- **JSON-schema shaping / compat envelope.** `_compat_public_envelope()` validates semantic_frame + assistant_act, builds `UtteranceSpec`, flattens payload (`model_router.py:2021+`).
- **Grounding / evidence wording guard.** Writer is handed scoped citable refs; prompt forbids inventing memory/tool receipts (`runtime_writer.py:realize` builds `CHARACTER_V1_CITABLE_REFS`; prompt text in `_public_reply_prompt`).
- **Length control.** `max_tokens` 720 (or 620 for locked rewrite) at `model_router.py:1878-1882`.
- **Japanese transcript lock (pre-TTS).** `_prelocalize_v03_speech()` forces `speech_text` into real kana/kanji via `SpeechLocalizer` before the seal; rejects candidate if it cannot (`runtime_writer.py:_prelocalize_v03_speech`).
- **The delivery seal.** `prepare_candidate()` runs the parser, stage planner, performance context, then `prepare_public_output()` → `prepared_public_output` artifact consumed by delivery (`delivery_adapter.py:284-330`; sealed into metadata at `runtime_writer.py:253`).

### 2b. What is in Root's `say` today vs final `text`

`say` is a **content directive, not near-final words.** The contract and prompt are explicit:

- Contract: `say` is "a content instruction for SurfaceWriter, NOT a sentence to copy verbatim" (`conversation/contracts.py:55-62`, field `say` :64).
- Root system prompt: "say mô tả đầy đủ điều writer cần truyền đạt nhưng không phải transcript" — *say describes fully what the writer must convey but is not a transcript* (`conversation/agent.py:383`).
- The writer wraps the whole move as `ROOT_CONVERSATION_MOVE_V12` and is told to "Realize this move … do not add a new topic/question/teaching step" (`runtime_writer.py:realize`, root_context block).

So **Option A (Root emits near-final `say`, writer becomes thin) is NOT a small change** — it requires rewriting the Root prompt/contract so `say` becomes near-verbatim words, plus relocating language-lock, the two-surface split, and the Japanese localize step out of the writer. That is a semantic-authority change with broad blast radius.

### 2c. Recommendation: **Option B** (keep the split, upgrade the writer call)

Make the surface writer think, with the strong behavior, while leaving all the preserved machinery untouched. Exact changes:

- `src/runtime/conversation/runtime_writer.py:336-337` — the two defaults:
  ```python
  "reasoning_effort": runtime_context.get("reasoning_effort", "low"),
  "thinking_mode":    runtime_context.get("thinking_mode", "disabled"),
  ```
  Change the writer’s default `thinking_mode` to `"enabled"` (and let `reasoning_effort` default to `"high"`, though see Q2 — effort is ignored by the local gateway). This flows into `generate_public_reply(..., thinking_mode=..., reasoning_effort=...)`.
- `generate_public_reply` already forwards both kwargs to `target.create_chat_completion(...)` (`model_router.py:1885` reasoning_effort, `:1892` thinking_mode) — **no router change needed.**

**MUST PRESERVE (do not drop when touching the writer):**
1. Display language lock + the single language-repair retry (`model_router.py:1946-1979`).
2. The speech/display two-surface split (text=vi, speech_text=ja).
3. The Japanese transcript lock `_prelocalize_v03_speech` before the seal.
4. The sanitizer/parser handoff and the `prepared_public_output` seal (`delivery_adapter.prepare_candidate` → `prepare_public_output`).
5. `_compat_public_envelope` semantic_frame/assistant_act validation.

Note on the user's "cut the writer" instinct: Option B keeps a writer step but stops making it a *low-effort, non-thinking* step — that is exactly the "writer still gets corrected" complaint. Enabling thinking makes the writer's single pass the strong pass, which is the cheapest path to the elegant-but-agentic result.

---

## 3. Q2 — Does the Whale gateway honor `reasoning_effort` or only thinking on/off?

### 3a. Exact request fields sent to the local Whale2API endpoint

In `src/llm/client.py` `DeepSeek…create_chat_completion` (:746-845):

- `is_ds2api` is true when base_url is not api.deepseek.com AND contains `6011`/`localhost`/`127.0.0.1` (`client.py:792`). For the local Whale gateway this is **true**.
- When `is_ds2api`: `mode = "enabled"` is **hard-set** (`client.py:794-795`), ignoring the writer's `thinking_mode='disabled'`. (Only `worker_role=="executive"` + `ERIS_EXECUTIVE_THINKING_DISABLED` can force it back off — not the surface writer.)
- Request body built: `payload["thinking"] = {"type": mode}` (`client.py:807`), `max_tokens` bumped to `max(max_tokens, 2048)` when enabled (`client.py:809`), and `payload["reasoning_effort"] = deepseek_reasoning_effort(reasoning_effort)` **only in the enabled branch** (`client.py:810`).
- `deepseek.reasoning_effort()` maps anything to `"high"` (or `"max"` for max/xhigh/maximum) — "low"/"medium" are discarded (`deepseek.py:69-73`).
- JSON schema is downgraded to `{"type":"json_object"}` for deepseek (`client.py` response_format branch).

**Conclusion:** On the local Whale gateway, `thinking` is sent as a concrete flag (`thinking:{type:...}`) but is **forced to `enabled`**; `reasoning_effort` is sent only as `high`/`max` and never as the writer's requested numeric level. The user is right that the Whale web backend is a thinking on/off world — and in the local-gateway path thinking is already forced on, so the public writer may *already* be thinking today despite `thinking_mode='disabled'` in `runtime_writer.py`. On the official `api.deepseek.com` fallback, `thinking_mode='disabled'` IS honored and effort is still high/max only.

### 3b. Minimal change to enable thinking for the public call

- If the deployment uses the **local Whale gateway**: thinking is **already forced on** for the writer (`client.py:794-795`); the only lever that would currently disable it is the executive-role env, which does not apply to surface. So to *guarantee* thinking for the public writer regardless of endpoint, flip the writer default at **`src/runtime/conversation/runtime_writer.py:337`** from `"disabled"` to `"enabled"`. This matters for the official-API fallback and for correctness/clarity.
- Global override alternative (no code change): set env `ERIS_DEEPSEEK_THINKING=enabled` (`deepseek.py:56-67`) — but that flips thinking for ALL deepseek calls, not just the writer; prefer the per-call writer default.
- Raising `reasoning_effort`: has **no additional effect on the Whale local gateway** (collapsed to high/max and only sent when enabled). Confirmed the user's suspicion — only the thinking flag matters there.

---

## 4. Q3 — Two config knobs for the later implementation

### 4a. Forced `ですね` ending rate

- File/function: `src/runtime/speech_persona_polish.py` → `_signature_ending_policy`.
- Current default: `rate = _runtime_float("signature_ending_rate", 0.55)` (the `0.55` literal) — runtime-overridable via `tts.signature_ending_rate`.
- Target: change the default literal `0.55` to `0.25` (user accepted 20–30%). Also update the clamp fallbacks that hardcode `0.55`: `rate = round(_clamp01(rate, 0.55), 3)` in the same function, and `signature_ending_rate` default usage. Cleanest no-redeploy path: set runtime setting `tts.signature_ending_rate=0.25`.
- Mode gating: **already supported.** `mode in {"technical","boundary"}` → disabled; `mode=="dry"` → capped at 0.24; `mode=="soft"` → `+0.08`. To gate the signature so it only appears in `soft`, add an early `if mode != "soft": return ending, False, 0.0`. (Mode comes from `resolve_speech_persona_policy` via `prosody_style`.)

### 4b. Surface worker `drop_if_busy`

- File/location: `src/llm/deepseek_workers.py:417-419` (and identical block at `:413-421` for the second worker class):
  ```python
  self._drop_if_busy = _env_flag(
      f"ERIS_DS_{self.worker_role.upper()}_DROP_IF_BUSY",
      self.worker_role in {"inner", "seed", "surface"},
  )
  ```
- `surface` defaults to **droppable**. When busy + droppable, `create_chat_completion` acquires non-blocking and raises `RoleWorkerBusyError` immediately (`deepseek_workers.py:442-449`). When NOT droppable it waits `_actor_acquire_timeout` (default 2s, env `ERIS_DS_ACTOR_WAIT_TIMEOUT_S` / `ERIS_DS_SURFACE_ACTOR_WAIT_TIMEOUT_S`).
- Minimal change (no code): set env `ERIS_DS_SURFACE_DROP_IF_BUSY=0` so the user-facing writer waits instead of dropping. Optionally raise `ERIS_DS_SURFACE_ACTOR_WAIT_TIMEOUT_S` so the short wait is enough under load.
- Code change alternative: remove `"surface"` from the default droppable set at `:419`.
- **Risk:** making surface non-droppable means a user turn can **block** up to the actor-wait timeout waiting for the surface lock, adding latency when the surface worker is already busy; it also removes the back-pressure that currently sheds overlapping surface calls. Pair with a sane wait timeout (a few seconds, never exceeding the public-writer deadline `_public_writer_deadline_seconds()` ≈24s).

---

## 5. Risks / what could break / open questions

- **Thinking cost/latency.** Enabling thinking on the writer forces `max_tokens ≥ 2048` (`client.py:809`) and disables temperature/penalty sampling (only applied in the non-thinking branch). Expect slower, more deterministic public wording. The public-writer deadline is ~24s (`_public_writer_deadline_seconds`, `model_router.py`), so a long thinking turn could time out → degraded fallback. Verify the deadline is comfortable before shipping.
- **Deployment ambiguity (open question).** The forced-thinking behavior depends entirely on whether the live base_url is the local Whale gateway (`:6011`/localhost) vs `api.deepseek.com`. Confirm the actual runtime `base_url`/`ERIS_REMOTE_PROVIDER` before concluding "thinking is already on." If it is the local gateway, the writer may already be thinking and the perceived "robotic" wording is a *prompt* problem, not a thinking-flag problem — which lines up with the user's "rewrite the prompt" ask.
- **Prompt rewrite is the real lever for elegance.** `_public_reply_prompt` (`model_router.py:1674-1715`) front-loads many prohibitions. Moving the 2–3 "speak naturally" lines to the top and trimming prohibitions already covered by the sanitizer/persona layer is low risk and independent of the thinking change.
- **`reasoning_effort` is a no-op knob on Whale.** Do not spend implementation effort tuning numeric effort for the local gateway; only the thinking flag is actionable there.
- **Option A later.** If the team ever wants to truly delete the writer pass, budget for Root-prompt/contract changes plus relocating language-lock, two-surface split, and `_prelocalize_v03_speech` — not in scope for this fix.

Content was rephrased for compliance; all quoted code strings are <20 words and cited by file:line.
