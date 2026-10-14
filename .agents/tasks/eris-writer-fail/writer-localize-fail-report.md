# Eris Writer "No-Reply" Investigation — Localize/Prepare Failure

Read-only investigation. No code was modified. All citations are `file:line` against the
working tree at `c:\Users\Gtvkun\Documents\GitHub\eris\src\`.

---

## 1. Verdict (one paragraph)

The user-visible "no reply" is a **fail-closed drop**: when the writer's post-model
`localize` or `prepare` stage raises, `conversation/kernel.py` logs `writer_failed`, calls
`_fail_run`, and `chat_cycle.py` transitions the lifecycle `COMPOSING → DEGRADED` with
`reason="no_public_commit"` — **nothing is ever sent to the user, by design** there is no
degraded-reply fallback. Two distinct rejections produce this: (a) `v03_speech_language_mismatch`
raised in `prepare_public_output` when a TTS segment carries a `ja` contract but the transcript
has no kana/kanji (`conversation/public_output_artifact.py:142`), and (b) a generic `RuntimeError`
code, which is simply `_v03_error_code` falling back to `type(exc).__name__` because the raised
exception's message did not match the safe allow-list regex (`conversation/runtime_writer.py:17`
+ `:33`). **Is `thinking_mode="enabled"` the trigger? Partly / indirectly — yes as an aggravator,
no as the mechanical fault.** The single most load-bearing line is
`conversation/runtime_writer.py:353` (`"thinking_mode": runtime_context.get("thinking_mode","enabled")`)
feeding `src/llm/client.py:794-809`, where any localhost gateway URL is force-set to
`mode="enabled"` and `max_tokens=max(max_tokens,2048)` — this makes the writer round-trip
slower and longer, which widens the window for a malformed/wrong-language/truncated candidate,
and the strict fail-closed localize/prepare gates then drop the whole turn instead of degrading.
**The brief's "8s localizer timeout is the direct cause" is only partly supported** (see §3):
the 11.9s/9.75s are the *total* `_realize_v03` durations, not the localizer sub-call, and the
observed failure codes are `v03_speech_language_mismatch` / `RuntimeError`, not the
localizer-timeout code `v03_speech_localizer_unavailable`.

---

## 2. The localize/prepare path and the two failure modes

### 2.1 Path overview (`conversation/runtime_writer.py:_realize_v03`, L179-277)

The method timestamps `started_at` at L196 and advances a `stage` string through:
`generate → surfaces → localize → prepare`. Every exception is funneled through one handler
(`except Exception as exc:` near L265) which computes `code = _v03_error_code(exc)` and re-raises
`RuntimeError('v03_candidate_rejected:'+stage+'='+code)` (L204). So the logged
`stage=…` is wherever the exception fired, and `code=…` is the sanitized error label.

- **stage=surfaces** (L157-166): empty display → `v03_missing_public_surface`; display-language
  mismatch → `v03_display_language_mismatch`.
- **stage=localize** (L169-173): `payload = _prelocalize_v03_speech(payload, host, language_hint=speech_language)`
  where `speech_language = runtime_text('tts','language', default='ja')`.
- **stage=prepare** (L178-197): `RuntimeConversationDeliveryAdapter(self.host).prepare_candidate(...)`
  then `validate_prepared(prepared)` then `enforce_completed_action_claims(...)`.

The error-code sanitizer (`conversation/runtime_writer.py:17-33`): the regex
`_SAFE_V03_ERROR` only accepts strings shaped like `v03_snake_case`, `public_writer_snake_case`,
or `ALL_CAPS[:ALL_CAPS]`. Anything else (e.g. a bare `"deadline_exceeded"`, a provider message,
a `KeyError('x')` repr) is replaced by `type(exc).__name__`. **This is why `code=RuntimeError`
appears: a `RuntimeError` whose *message* was not in the allow-list leaked.** It is NOT a distinct
error type; it is "unrecognized message, fell back to the class name."

### 2.2 What `_prelocalize_v03_speech` actually does (`conversation/runtime_writer.py:35-100`)

Step by step:
1. If `language_hint` ∉ {ja,jp,japanese} → return payload unchanged (L47-48).
2. Build an `UtteranceSpec` and read `source = spec.speech.text` (L49-53).
3. **If `source` is empty → return payload unchanged WITHOUT setting a ja `speech_text`** (L54-55).
   This is a silent early-exit and is the seed of failure mode (a) — see §2.3.
4. If `source` already contains kana/kanji (`_contains_japanese_script`) → copy it to
   `result['speech_text']` and return (L56-60). No model call.
5. Otherwise it **does make a second model call**: it fetches a `SpeechLocalizer`
   (`host.character_speech_localizer`, else a cached `host._character_preverify_localizer`,
   else constructs one — L62-71) and calls `translate(source, language_hint='ja', strict=True)`
   (L73-74).
6. On ANY localizer exception it re-raises `RuntimeError('v03_speech_localizer_unavailable')`
   (or `v03_speech_localization_cancelled` if cancelled) — L75-82. **Both are safe codes**, so a
   localizer failure logs as `code=v03_speech_localizer_unavailable`, *not* `RuntimeError`.
7. If the converted string is empty or still non-Japanese → `RuntimeError('v03_speech_localizer_unavailable')`
   (L83-84). On success it writes `speech_text`, `speech_language='ja'`, and patches the nested
   `speech`/`utterance` maps (L86-99).

The localizer lane (`runtime/speech_localizer.py`): provider is `deepseek`
(`localizer_provider_name`, L? — `ERIS_TTS_LOCALIZER_PROVIDER=deepseek` in `.env:114`), it calls
`_translate_with_deepseek_api` which POSTs **directly with `requests.post`, bypassing
`llm/client.py`** (`speech_localizer.py:_translate_with_deepseek_api`), with an explicit
`"thinking": {"type": "disabled"}` in the payload. The call is wrapped in
`inference_context("speech_localizer", timeout_seconds=_localizer_timeout_seconds(), ...)` and
run through `GLOBAL_INFERENCE_BROKER`. **Note:** `_prelocalize_v03_speech` calls
`translate(source, language_hint='ja', strict=True)` with **no `cancel_event` and no
`authority_check`** (runtime_writer.py:74) — so a user interrupt cannot cancel the localizer
from this path.

### 2.3 Failure mode (a): `v03_speech_language_mismatch` (gen 75)

Raised at `conversation/public_output_artifact.py:142`, inside `prepare_public_output`:

```
for segment in segments:
    ...
    if str(contract.get('language','')).lower() == 'ja':
        if not _contains_japanese_script(segment.tts_text):
            raise RuntimeError('v03_speech_language_mismatch')
```

Because the log shows `stage=prepare` (not `stage=localize`), **localize did not raise** — it
returned a payload whose speech transcript was still not valid Japanese. The most plausible
producers:
- The writer returned an **empty `speech_text`** → `_prelocalize_v03_speech` early-exits at
  runtime_writer.py:54-55 without producing ja → `StageFrameBuilder` then derives the TTS surface
  from the Vietnamese display text (`stage_contracts.py:build`, the `else`/no-utterance branch,
  ~L321-345, where the prepare-time builder has **no localizer** so `tts_text=tts_source`) →
  segment is Vietnamese under a `ja` contract → mismatch.
- The writer returned a mixed/romaji `speech_text` that passed the loose `_contains_japanese_script`
  check at localize but a later split segment lands on a non-Japanese fragment.

Key structural fact: `prepare_public_output` builds `StageFrameBuilder(language_hint=language)`
**without injecting a localizer** (`public_output_artifact.py:prepare_public_output`, builder
construction), and `StageFrameBuilder.__init__` defaults `localizer=None`
(`stage_contracts.py:191`). So prepare can only *detect* a non-Japanese transcript, never fix it —
by contract (comment at stage_contracts.py:~L300-309, "renderer is not a localize authority").
That is correct design, but it means any gap left by `_prelocalize_v03_speech` becomes a
hard turn-drop at prepare.

### 2.4 Failure mode (b): generic `RuntimeError` at stage=prepare (gen 77)

This is NOT the localizer (that path yields the safe `v03_speech_localizer_unavailable`). At
`stage=prepare` the chain is `prepare_candidate → prepare_public_output → validate_prepared →
enforce_completed_action_claims`. A `RuntimeError`-class exception whose message is **not** in
the `_SAFE_V03_ERROR` allow-list produces `code=RuntimeError`. Candidate sources, by likelihood:

1. **Broker deadline inside a nested inference call** → `inference_broker.InferenceRejected`
   (which **is a subclass of `RuntimeError`**, `inference_broker.py:150`) with message
   `"deadline_exceeded"` (`inference_broker.py:997`, `raise InferenceRejected("deadline_exceeded")`).
   `"deadline_exceeded"` is lowercase and does not match `_SAFE_V03_ERROR` → sanitized to
   `RuntimeError`. If any provider-touching call runs under prepare (e.g. a voice/TTS-provider
   probe), its timeout surfaces exactly as the observed `code=RuntimeError`.
2. **Provider-touching helpers in `stage_output.py:frames_for_tts`** call
   `_tts_provider()` / `_provider_transcript_limit()` **unguarded** (stage_output.py, the
   ElevenLabs branch `_tts_provider() == "elevenlabs"`). If those raise a non-allow-listed
   exception during prepare, it maps to the class name.
3. A raw `KeyError`/`ValueError`/`AttributeError` from payload shaping in
   `prepare_public_output` — all map to their class name, not `RuntimeError`, so only a
   genuine `RuntimeError('lowercase_or_freeform')` or `InferenceRejected` yields the literal
   `RuntimeError`. **This points strongly at `InferenceRejected("deadline_exceeded")` as the
   gen-77 culprit** — i.e. a timeout, consistent with the long 9.75s duration.

**Confidence:** (a) is well-grounded in code I read end to end. (b) is a ranked inference —
`InferenceRejected("deadline_exceeded")` is the only common `RuntimeError`-subclass with a
non-allow-listed lowercase message on this path; I could not pin the exact nested call that
times out under prepare without a live stack trace (see Open Questions §6).

---

## 3. Timeout analysis (8s localizer vs 11.9s / 9.75s observed) — refuted as a direct cause

- `.env:97` sets `ERIS_TTS_LOCALIZER_TIMEOUT_SEC=8`. The code default is now **60.0s**
  (`speech_localizer.py:_localizer_timeout_seconds`, "60.0" default; a regression test
  `src/tests/test_architecture_c_runtime_regressions.py:366` asserts `== 60.0`). So the brief's
  "8s default" is stale **but the deployment's `.env` does pin 8s**, so 8s is the effective value
  here.
- **However, the 11.9s (gen75) and 9.75s (gen77) are the TOTAL `_realize_v03` durations**, measured
  from `started_at` at `runtime_writer.py:130` (which is before `generate`, surfaces, localize AND
  prepare). They are **not** the localizer sub-call. The localizer runs under its own 8s
  `inference_context` budget inside stage=localize.
- Decisive evidence against "localizer timeout": a localizer timeout raises inside
  `_prelocalize_v03_speech` and is re-labeled `v03_speech_localizer_unavailable` at
  `runtime_writer.py:76/84` — a *safe* code, logged at `stage=localize`. The hard evidence shows
  **`stage=prepare`** with codes `v03_speech_language_mismatch` and `RuntimeError`, i.e. the
  localize sub-call **completed within budget**; the drop happened afterward.
- What the long durations DO indicate: the **writer generate call** itself was slow. With thinking
  forced on (see §5), `client.py:809` sets `max_tokens≥2048` and the model emits a reasoning
  stream; the writer deadline is `min(300, 60, 24.0)=24s` (`model_router.py:_public_writer_deadline_seconds`
  + `.env:ERIS_MAIN_SEMANTIC_DEADLINE_SEC=300`), so it does not time out, but it runs ~1.5–2× the
  6.4s success turn. The slowness is real and thinking-linked; the *drop* is the strict gate, not
  the clock.

**Conclusion:** the 8s localizer timeout is a plausible contributor to failure mode (b) *only if*
the gen-77 `RuntimeError` is an `InferenceRejected("deadline_exceeded")` from a nested
provider call — but it is **not** the localizer's own timeout (that would log a different, safe
code at a different stage). The brief's strong-lead framing is **refuted as stated** and
**reframed** in §4.

---

## 4. Ranked fixes (A–D) with exact file:line

### Fix D — stop the user-visible "no reply" (FASTEST, highest user impact)
Add a degraded-delivery fallback so a failed localize/prepare still shows the Vietnamese display
text (with a safe TTS fallback) instead of dropping the turn.
- **Where the drop happens:** `conversation/kernel.py:303-319` (`writer_failed` → `_fail_run`)
  and `conversation/chat_cycle.py:194-207` (lifecycle stuck `COMPOSING` → `DEGRADED`
  `no_public_commit`).
- **Where to add the fallback:** when `_realize_v03` raises specifically
  `v03_candidate_rejected:localize=…` or `…:prepare=v03_speech_language_mismatch`, emit a
  display-only commit (Vietnamese bubble, TTS either skipped or set to speak the already-produced
  ja text if any). Natural insertion point is the kernel exception path at `kernel.py:~303`
  (catch, attempt a display-only `deliver`, then only `_fail_run` if that also fails), or a new
  degraded branch in `RuntimeConversationDeliveryAdapter.deliver` keyed off a "display_only" flag.
- **Tradeoff:** must not violate the ja-TTS contract silently. Degrade = "show text, don't fake
  Japanese audio" — i.e. skip/queue TTS, never speak Vietnamese through the ja voice. This is the
  single most direct stop for "user got NO reply."

### Fix B — localizer timeout headroom + graceful degrade (robust, targets mode (b))
- Raise `ERIS_TTS_LOCALIZER_TIMEOUT_SEC` from `8` (`.env:97`) toward the code default `60`
  (`speech_localizer.py:_localizer_timeout_seconds`), OR set
  `ERIS_TTS_FAIL_OPEN_ON_LOCALIZATION_ERROR=1` (`.env:113`, consumed at
  `runtime/tts_engine.py:220`) so a localization error degrades to speaking the source rather than
  failing closed. **Caveat:** fail-open there governs the *tts_engine* path; the
  **writer-side** `_prelocalize_v03_speech` is independently fail-closed with `strict=True`
  (`runtime_writer.py:74`) and does NOT consult that flag — so B alone will not save the
  writer-stage drop. Pair B with D.
- **Tradeoff:** longer localizer budget raises worst-case latency; fail-open risks a Vietnamese
  transcript reaching TTS (mitigated because D/degrade should skip ja audio, not mis-speak it).

### Fix C — isolate eloquence-thinking from the TTS path (robust, structural)
Keep thinking for display wording but give the ja localization its own bounded, non-thinking
budget. The localizer already sends `"thinking":{"type":"disabled"}` and bypasses `client.py`
(`speech_localizer.py:_translate_with_deepseek_api`), so this is **largely already true** for the
localizer; the remaining coupling is the **writer** generate call being slow+long under forced
thinking (§5). C in practice = reduce the writer's forced-thinking cost (see A) while leaving the
localizer alone.
- **Tradeoff:** preserves the eloquence gain only on the display wording; needs the gateway/client
  to actually honor a per-call thinking choice (see §5).

### Fix A — revert writer `thinking_mode` default to "disabled"
- **Where:** `conversation/runtime_writer.py:353`
  (`"thinking_mode": runtime_context.get("thinking_mode", "enabled")`), with the eloquence rationale
  comment at L349-352.
- **Effect on THIS deployment:** see §5 — this is **NOT a no-op** here, but the lever that actually
  controls forcing is in `client.py`, not the gateway.
- **Tradeoff:** gives back the eloquence improvement the change was shipped for. Prefer A as a
  mitigation of latency/length, not as the correctness fix (D is the correctness fix).

**Which single fix stops "no reply" fastest:** **Fix D** (degraded display-only commit). It makes
the failure non-fatal regardless of root cause.
**Which combination is robust:** **D + B + A** — D guarantees a reply, B widens the localize
budget and lets it degrade, A/§5 removes the thinking-driven latency/length inflation that opens
the failure window. Keep C's localizer isolation (already in place).

**Must preserve:** ja TTS (never speak Vietnamese through the ja voice — degrade = text-only, not
mis-localized audio); the eloquence gains on display wording; secret redaction in
`_v03_error_code` (`runtime_writer.py:17-33` — do not widen it to log raw provider text);
single-speaker/single-clip TTS contract (`stage_output.py` idempotency and segment rules).

---

## 5. Does the gateway's forced thinking make Option A a no-op on the local deployment?

**No — but the real lever is Eris's own client, not the gateway.** Two facts from the tree:

1. **The gateway does NOT force thinking.** `tools/whale2api/.env` and `.env:238` set
   `WHALE2API_THINKING_INJECTION_ENABLED=0` ("ERIS tự quản lý thinking" — Eris manages thinking
   itself). So the Whale gateway honors whatever `thinking` field the client sends. The brief's
   premise that "the gateway FORCES thinking ON for localhost regardless" is **not supported by
   the gateway config** in this tree.
2. **Eris's `client.py` DOES force thinking on for localhost.** At `src/llm/client.py:794-809`,
   `is_ds2api = "api.deepseek.com" not in base_url and ("6011" in base_url or "localhost" in
   base_url or "127.0.0.1" in base_url)`; when true, `mode = "enabled"` **overriding** the
   requested `thinking_mode`, and `max_tokens = max(max_tokens, 2048)` + `reasoning_effort` is
   sent. The deployment's writer/base URL is `http://127.0.0.1:5103/v1` (`.env:11`
   `ERIS_REMOTE_BASE_URL`), which matches `127.0.0.1` → **forced enabled**.

**Implication for Option A (set writer default `thinking_mode="disabled"` at runtime_writer.py:353):**
On this local-gateway deployment, flipping only L353 is **overridden** by `client.py:796-797`, so A
alone would have **little effect** — effectively a near-no-op for the writer going to
`127.0.0.1:5103`. To actually disable writer thinking on local, you must change the forcing in
`client.py:794-806` (e.g. respect the caller's `thinking_mode`, or extend the existing
per-worker escape hatch — note `ERIS_EXECUTIVE_THINKING_DISABLED` already carves out the
`executive` worker at `client.py:804-806`, and `.env:38` sets it to `1`; an analogous
`worker_role == "surface"/"public_writer"` escape would let the writer opt out while keeping the
localhost default for other lanes). **So: A is only effective if paired with a `client.py` change;
by itself it is a no-op on the local deployment.** The localizer is unaffected either way because
it bypasses `client.py` and already sends `thinking: disabled`.

---

## 6. Open questions

1. **Exact source of the gen-77 `RuntimeError` at stage=prepare.** The strongest candidate is
   `InferenceRejected("deadline_exceeded")` (RuntimeError subclass, lowercase message →
   sanitized to `RuntimeError`) from a nested provider call under `prepare_public_output`
   (likely a `_tts_provider()`/transcript-limit probe in `stage_output.py:frames_for_tts`). A live
   stack trace, or temporarily widening `_v03_error_code` logging in a dev build, would confirm.
2. **Why `speech_text` is empty / non-Japanese for gen-75 but fine for gen-76.** Needs the raw
   writer JSON for those generations. Hypothesis: forced-thinking + `max_tokens≥2048` occasionally
   yields a truncated or reasoning-polluted JSON where `speech_text` is dropped or malformed, so
   `_prelocalize_v03_speech` early-exits (runtime_writer.py:54) with no ja transcript. The
   DeepSeek raw trace for pid 10152 confirms the *provider* returned without error, so the gap is
   in the returned JSON shape, not the transport.
3. **Startup warmup `RuntimeError` (21:10:42).** `root_session.py:_background_prime` catches all and
   logs only `type(exc).__name__` (`root_session.py:147-148`), so the message is lost. Warmup only
   runs for localhost base_urls (`root_session.py:132-134`) and does an inference prime; a
   thinking-inflated prime that overruns its bootstrap budget would surface as a bare `RuntimeError`
   here too — **plausibly the same forced-thinking latency root as the writer**, but it is a
   daemon thread that degrades silently (`self._clear()`), so it is **non-fatal and separate** from
   the per-turn drop. Lower priority. Confirm by logging the warmup exception message.
4. **Interaction with user interrupts.** `_prelocalize_v03_speech` calls the localizer with no
   `cancel_event`/`authority_check` (runtime_writer.py:74), so a mid-localize interrupt cannot
   cancel it; worth checking whether a superseded turn can still hold the localizer and contribute
   to perceived "no reply" on the *next* turn.

---

## Appendix — key citations

- `conversation/runtime_writer.py:17-33` — `_SAFE_V03_ERROR` / `_v03_error_code` (why `RuntimeError`).
- `conversation/runtime_writer.py:35-100` — `_prelocalize_v03_speech` (second model call, early-exits).
- `conversation/runtime_writer.py:130,157-204` — `_realize_v03` stage machine + single catch.
- `conversation/runtime_writer.py:349-353` — writer `reasoning_effort="low"` / `thinking_mode="enabled"` defaults.
- `conversation/public_output_artifact.py:140-142` — `v03_speech_language_mismatch` raise.
- `conversation/public_output_artifact.py:prepare_public_output` — builder has no localizer; segment ja check.
- `runtime/stage_contracts.py:108-121` — `_contains_japanese_script` (kana/kanji range only).
- `runtime/stage_contracts.py:191,300-345` — `StageFrameBuilder` localizer=None default; needs_language_repair; no-utterance branch.
- `runtime/speech_localizer.py:_localizer_timeout_seconds` — default 60.0 (test asserts 60.0).
- `runtime/speech_localizer.py:_translate_with_deepseek_api` — bypasses client.py, sends `thinking: disabled`.
- `runtime/inference_broker.py:150` — `InferenceRejected(RuntimeError)`; `:997` — `raise InferenceRejected("deadline_exceeded")`.
- `src/llm/client.py:794-809` — localhost ds2api → `mode="enabled"`, `max_tokens≥2048`; `:804-806` executive escape hatch.
- `conversation/kernel.py:303-319` — writer_failed / _fail_run.
- `conversation/chat_cycle.py:194-207` — lifecycle COMPOSING → DEGRADED `no_public_commit`.
- `conversation/root_session.py:132-148` — warmup localhost-only, swallows exception message.
- `.env:11` base_url `127.0.0.1:5103`; `:97` localizer timeout 8; `:113` fail-open 0; `:114` provider deepseek;
  `:14` `ERIS_DEEPSEEK_THINKING=disabled`; `:38` executive thinking disabled; `:238` gateway thinking injection off.

Content paraphrased from source code; code excerpts kept minimal for secret-safety.
