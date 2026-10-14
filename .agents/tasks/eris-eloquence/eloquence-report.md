# Eris Eloquence Investigation — Speech Production Pipeline

Read-only audit. No code was modified. All claims cite `file:symbol` with short quotes (<20 words).
Scope: why spoken/shown replies feel less elegant than the strong model should produce.

---

## 1. Executive summary

**Biggest eloquence killer: the public words you read/hear are NOT written by the model that did the thinking.**
Eris runs a two-stage split. `RuntimeModelRootAgent` (the semantic authority) decides *what* to say but is explicitly told its `say` field is **not a transcript** — "say mô tả đầy đủ điều writer cần truyền đạt nhưng không phải transcript" (`conversation/agent.py:_system_prompt`). A **second, separate model call** — `generate_public_reply` on the **surface lane** — re-renders that intent into the final words at `temperature=0.56`, `max_tokens=720`, `thinking_mode="disabled"`, and `reasoning_effort="low"` (passed by `runtime_writer.py:realize`). So the eloquent reasoning pass never writes the sentence the user sees; a cheaper-configured wording pass does.

Compounding it:
- **Hypothesis B is real in effect, not by model identity.** By default every lane (root/executive and surface) resolves to the SAME model string (`"deepseek-v4-flash"`), while a stronger model exists but is unused (`DEEPSEEK_STRONG_MODEL = "deepseek-v4-pro"`, `llm/deepseek.py`). The quality drop between Root and Surface is not "big model vs small model" — it is **same model, degraded settings** (low effort, no thinking, token cap, drop-if-busy). If the operator sets per-lane models, surface could silently become the weaker one.
- **Hypothesis C is strongly supported.** The surface prompt (`model_router.py:_public_reply_prompt`) is dominated by prohibitions ("Không tự thêm intent mới…", "Không phát minh grounding…", display-language locks). Genuine style guidance exists (the V39 voice contract) but is a minority of the token budget and sits amid a wall of "do not" rules.
- **The spoken (JA) transcript is independently restyled.** `speech_persona_polish.py` injects a softening + forced signature-ending (`ですね` ~55% of sentences) directive into the TTS localizer, so the audio can drift from the shown Vietnamese text and acquire a catchphrase tic.

The *mechanical* post-processing chain (sanitizer, stage transformers, addressing policy) is mostly safety-correct and is **not** the main problem — it strips markdown/emoji/secrets/stage-tags and normalizes honorifics, but does not re-write phrasing or cap sentence count on the live path.

---

## 2. Speech-path map (RootAgent `say` → committed text / TTS)

Order of stages a reply passes through on the production (V12 "prepared") path:

| # | Stage | file:symbol | What it does to the text | Evidence (short quote) |
|---|-------|-------------|--------------------------|------------------------|
| 1 | Root decides intent | `conversation/agent.py:RuntimeModelRootAgent.decide` | (a) LLM. Produces `say`, NOT final words. Strong-ish settings: `reasoning_effort="medium"`, `temperature=0.3`, `max_tokens=1200` | "say mô tả … nhưng không phải transcript" |
| 2 | Writer wraps the move | `conversation/runtime_writer.py:realize` | Builds generate kwargs; defaults `reasoning_effort="low"`, `thinking_mode="disabled"` | `"reasoning_effort": runtime_context.get("reasoning_effort", "low")` |
| 3 | **Public wording** | `ai_orchestrated/model_router.py:generate_public_reply` | **(a) LLM re-render** on `surface_client`. `temperature=0.56`, `max_tokens=720`, schema-locked JSON | `client = client or self.surface_client or …` |
| 3b | Language repair (conditional) | same, `call(client, request_messages=repair_messages)` | (a) one extra LLM call if `text` came back in wrong display language | "LANGUAGE REPAIR ONLY: field text vừa bị sai ngôn ngữ." |
| 4 | Realize/prepare candidate | `runtime_writer.py:_realize_v03` → `delivery_adapter.py:prepare_candidate` | passthrough + prepares artifact; may pre-localize JA speech | `allow_language_repair' ] = False` then `prepare_candidate(...)` |
| 5 | **Surface commit** | `public_surface_commit.py:PublicSurfaceCommitter.build` → `StageTransformerChain` | (b)(d) strip markdown, action tags, emoji, honorifics; split display/tts/memory surfaces | `self.transformers.transform(raw)` |
| 6 | Final sanitizer | `final_surface_sanitizer.py:FinalSurfaceSanitizer.sanitize` | (b)(d) redact secrets, stack traces, private URLs/paths, stage directions. Safety, not style | "van cuối, chặn dữ liệu nội bộ, secret…" |
| 7 | Addressing policy | `addressing_policy.py:clean_public_addressing` | (b) regex rewrite of honorifics/pronouns (`Ngài/Master → bạn`), fix possessives | "Loại cách gọi cũ và sửa câu ở mức tối thiểu" |
| 8 | Stage frame build | `stage_contracts.py:StageFrameBuilder.build` | (e) passthrough for canonical commit (`has_utterance_commit=True`); re-runs transformers per surface; no translate/rewrite | "Stage may remove markup/tags, but it may not translate or rewrite" |
| 9 | TTS text clean | `conversation/public_output_artifact.py:tts_clean` → `tts_engine.py:_clean_text` | (b)(d) strip markdown/URL/code, squash whitespace, strip TTS honorifics | `re.sub(r"https?://\\S+", "", t)` |
| 10 | **Speech persona polish** (JA audio only) | `speech_persona_polish.py:resolve_speech_persona_policy` | (a→via localizer) injects softening + forced `ですね` signature into the SpeechLocalizer prompt | "signature ending is selected … carry ですね once" |
| 11 | Speech localizer (if JA) | `runtime_writer.py:_prelocalize_v03_speech` → `speech_localizer.SpeechLocalizer.localize` | (a) LLM/translation to kana/kanji; rejects candidate if it can't produce valid JA | "SpeechLocalizer là owner dịch ĐÃ CÓ trong Eris" |
| 12 | Commit history/ledger | `delivery_adapter.py:deliver` | writes `memory_text` to chat history AFTER transport accept | "Chỉ từ đây trở xuống mới là PUBLIC COMMIT thật" |

Stages that are **pure passthrough / metadata-only** (do NOT touch the outgoing string): `prosody_director`, `speech_delivery_planner`, `voice_profile_compiler`, `body_choreography`, `voice_director`/`voice_policy` (motion/prosody metadata). `utterance_selector` / `utterance_evaluator` are **not wired into the V12 conversation path at all** (grep in `runtime/conversation` and `runtime/ai_orchestrated` returns no references) — legacy, not an active eloquence factor.

---

## 3. Writer analysis (the prime suspect)

`model_router.py:generate_public_reply`:
- **Lane/model:** `client = client or self.surface_client or getattr(self.llm_service, "client", None)`. `surface_client` → `llm_service.surface_client` → `process_manager.build_surface_client()` → `build_deepseek_worker_client("surface")`.
- **Model name:** from `deepseek_workers.load_worker_spec`: `get_secret("ERIS_DS_SURFACE_MODEL") or ERIS_DS2API_MODEL or ERIS_DS_MODEL or "deepseek-v4-flash"`. So the surface worker's model is whatever the shared gateway serves; the **hardcoded floor is v4-flash**, and the strong `deepseek-v4-pro` is never selected automatically.
- **Decoding:** `temperature=0.56`, `frequency_penalty=0.0`, `max_tokens=720` (`620` on rewrite), `reasoning_effort=<low by default from writer>`, `thinking_mode="disabled"` for DeepSeek.
- **Reliability tilt against quality:** the surface worker is `drop_if_busy=True` by default (`deepseek_workers.JsonlWorkerClient.__init__`: `self.worker_role in {"inner", "seed", "surface"}`) and `repair_attempts=0` for surface. Under load it raises `RoleWorkerBusyError` and the turn degrades — the sentence you get is then the fallback, not a crafted one.
- **Is strong output replaced by a weaker rewrite? Yes, structurally.** Root reasons with `reasoning_effort="medium"`/`thinking` available; the words are then produced by a pass with thinking disabled and low effort. Even on the identical base model, that is a measurable quality/fluency gap.

**Prompt content (hypothesis C), `_public_reply_prompt`:**
- Style-positive lines exist and are decent: `CHAT_VOICE_CORE_V39` ("Giọng public của ERIS là tiếng Việt hội thoại tự nhiên, tinh ý…"), and `CHAT_STYLE_RULES_V39` (allow asymmetric rhythm, fragments, dry humor, let mood show).
- But the writer prompt wraps those in a **much larger body of constraints**: "RootAgent đã quyết định toàn bộ ý nghĩa… Writer CHỈ hiện thực", "Không tự thêm intent mới", "Không phát minh grounding, memory hay capability", a HARD DISPLAY LANGUAGE LOCK, `STANCE_PUBLIC_RULES_VI`, plus soft-metadata handling. The net instruction load pushes the model toward *compliance and fidelity*, not toward *crafting the best Vietnamese sentence*. The style rules are present but out-weighted.

---

## 4. Ranked top causes + fix directions

1. **Two-stage split renders the final words with a degraded pass.** (`runtime_writer.py:realize` sets `reasoning_effort="low"`; `generate_public_reply` uses `thinking_mode="disabled"`, `max_tokens=720`.) The eloquent reasoning never writes the sentence.
   *Fix direction:* let the strong lane produce near-final words — either have Root emit a near-final `say` and make the writer a light fidelity/format pass, OR raise the writer to the executive lane with `reasoning_effort` ≥ medium and thinking enabled for user-facing chat. Measure latency delta before/after.

2. **Surface lane defaults to the fast model and is droppable.** (`deepseek_workers.load_worker_spec` floor `"deepseek-v4-flash"`; `JsonlWorkerClient` `drop_if_busy` includes `surface`; `DEEPSEEK_STRONG_MODEL="deepseek-v4-pro"` unused.)
   *Fix direction:* pin the public-wording lane to the strong model (set `ERIS_DS_SURFACE_MODEL`/`ERIS_EXECUTIVE_MODEL=deepseek-v4-pro`) and make the user-facing writer **not** drop-if-busy (prefer a short wait over a degraded fallback).

3. **Prompt overload crowds out style.** (`model_router.py:_public_reply_prompt` — prohibitions dominate; style rules are a minority.)
   *Fix direction:* lead the writer prompt with 2–3 strong naturalness directives, move the long prohibition list to a terminal "constraints" block, and drop constraints already enforced mechanically downstream (markdown/stage-tag/secret rules are redundant with the sanitizer).

4. **Forced JA signature ending + persona softening on the spoken transcript.** (`speech_persona_polish.py:_signature_ending_policy` default `rate≈0.55`; `resolve_speech_persona_policy` warmth/cuteness modifiers.) Produces a catchphrase tic and tone drift in audio.
   *Fix direction:* lower/disable `signature_ending_rate`, or gate it strictly on `mode == "soft"`; audit whether persona warmth is doubling the affect the voice contract already carries.

5. **Display (VI) vs speech (JA) are two separate generations that can diverge.** (`runtime_settings_store` default `tts.language="ja"`; writer returns separate `speech_text`; `_prelocalize_v03_speech` re-derives JA.) What is heard may be less natural than what is shown, and vice-versa.
   *Fix direction:* if the product goal is Vietnamese voice, set `tts.language="vi"` to remove the translation hop entirely; if JA is intended, treat the localizer prompt as a first-class style surface, not an afterthought.

---

## 5. Minimum-stages target (what should touch outgoing text)

Keep text-touching to:
- **One generation stage** that produces near-final words with the strong lane/effort (merge Root-intent + wording, or a high-effort writer).
- **One safety/cleanup pass**: `FinalSurfaceSanitizer` (secrets, stack traces, internal paths) + stage-tag extraction + addressing normalization. These are correctness/safety, keep them.
- **One TTS text clean** (`tts_engine._clean_text`) — mechanical, keep.

Make these **metadata/passthrough only** (already true, keep that way): `prosody_director`, `speech_delivery_planner`, `voice_profile_compiler`, `body_choreography`, stage emotion/motion. Remove `utterance_selector`/`utterance_evaluator` from consideration (not on the live path).

**Do NOT remove (intentional safety / correctness):**
- `FinalSurfaceSanitizer` secret/stack-trace/private-URL/path redaction.
- Stage-direction and action-tag extraction (keeps "(cười khẽ)" out of TTS/memory).
- Display-language lock + addressing policy (prevents `Ngài/Master` and wrong-language leaks).
- The `prepared_public_output` seal/hash checks (prevent silent text tampering between prepare and dispatch).

---

## 6. Latency / cost tradeoff

- Moving wording to a strong/high-effort pass means roughly **one higher-cost model call per turn** instead of one cheap one. Root already runs a loop (`max_root_steps` up to 6) at medium effort, so the dominant cost is already paid in cognition; upgrading the single wording call is incremental, not multiplicative.
- Current writer cap is `max_tokens=720` (`620` rewrite). Enabling thinking / higher effort raises provider latency on `surface_client`; the module already instruments `public_writer_provider_ms` (`GLOBAL_OBSERVABILITY.observe`), so the delta is measurable before/after.
- Keeping `drop_if_busy` off for the user-facing writer trades a possible short wait for consistent quality (today a busy surface worker yields a degraded fallback sentence).
- The JA path adds a localizer call (stage 11) regardless; switching `tts.language="vi"` would *remove* a model/translation hop and reduce both latency and divergence.

---

## 7. Open questions / unverified

- **Actual deployed model per lane is config-dependent.** I confirmed the code defaults (`deepseek-v4-flash` floor, `deepseek-v4-pro` as the unused strong model) but did not read the operator's `secrets.json` / env, so I cannot state which model `ERIS_DS2API_MODEL` currently serves surface vs executive. Verify with the live env.
- **Whether `reasoning_context["reasoning_effort"]` is ever raised above `"low"` for chat.** I saw the default in `runtime_writer.py`; I did not trace every caller that builds `runtime_context` to confirm nothing bumps it. Grep `reasoning_effort` across the context assembler to be sure.
- **SpeechLocalizer internals.** I confirmed it is invoked and persona-polished but did not read `speech_localizer.py` end-to-end; the exact model/temperature of the JA translation pass is unverified.
- **Perceptual claim.** "Elegance loss" is inferred from architecture (degraded second pass, prompt overload, forced catchphrase). I did not run the app or compare raw-model vs shipped output side by side; a quick A/B (log Root `say` vs final `text`) would quantify how much wording changes per turn.

---

### Compliance note
This report is based solely on reading the repository source. No external sources were used.
