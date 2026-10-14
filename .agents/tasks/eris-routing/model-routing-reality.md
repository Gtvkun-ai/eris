# Eris Model-Routing Reality (read-only investigation)

Scope: what Eris's public chat path ACTUALLY does today for model selection, thinking, and
web search — traced through code, not inferred from config. Evidence is cited as `file:line`
with <20-word quotes. Where I infer, I say so.

---

## 1. Verdict (the three synthesis questions)

- **(a) Does chat use web search today? NO.** The local gateway only advertises/accepts one
  model id, `deepseek-flash`, and its config hard-codes `search=false`
  (`tools/whale2api/internal/config/models.go` `GetModelConfig` → `return true, false, true`).
  The gateway derives `Search` purely from model config and never reads a client `search_enabled`
  field; the OpenAI-chat pass-through whitelist does not include any search key
  (`request_normalize.go` `collectOpenAIChatPassThrough`). The Python chat path never sets
  `search`/`search_enabled`/`tools` anyway. Eris is **not using its web-search advantage at all**.

- **(b) Is Flash-vs-Pro real, i.e. does difficulty switch the model? NO — it only ever would have
  toggled thinking, and even that is dead.** The worker model string is **pinned per worker** by
  `load_worker_spec` to `ERIS_DS2API_MODEL`/`ERIS_DS_MODEL` which `.env` sets to `deepseek-flash`
  for every lane. `companion_model_routing.route_companion_turn` (which emits `tier=flash|pro`) is
  **imported but never called** on the live path, and its `tier` never maps to a model string
  anywhere. So "Pro" is fictional: there is one model, `deepseek-flash`, for all chat lanes.
  (Separately, the hard-coded `deepseek-v4-pro`/`deepseek-v4-flash` in `src/llm/deepseek.py` would
  be *rejected* by this gateway — see §4.)

- **(c) Does the writer run under forced slow thinking? YES.** The surface writer client talks to
  `127.0.0.1:5103`, which `client.py` treats as a DS2API/localhost endpoint and **force-sets
  `thinking.type="enabled"`**, overriding any caller value. The surface lane has no escape hatch
  (only `worker_role=="executive"` + `ERIS_EXECUTIVE_THINKING_DISABLED=1` escapes). The writer even
  defaults `thinking_mode="enabled"` itself. So the user-visible reply is produced under thinking
  mode = slow, every turn.

---

## 2. Per-lane reality table (a normal user chat turn)

| Lane | Model string actually sent | Thinking (actual) | Search (actual) | Source |
|------|---------------------------|-------------------|-----------------|--------|
| RootAgent / executive (decides the move) | `deepseek-flash` | **OFF** (escape hatch fires) | OFF | client resolve `agent.py:213`; model `.env` `ERIS_DS2API_MODEL=deepseek-flash:34`; escape `client.py:803-806` + `.env:38` |
| Surface writer (`generate_public_reply`, user-visible text) | `deepseek-flash` | **ON (forced)** | OFF | client `model_router.py:1764`; force `client.py:795-797`; writer default `runtime_writer.py` `thinking_mode"...","enabled"` |
| Speech localizer (VI→JA transcript for TTS) | `deepseek-flash` | **OFF** (direct POST sets disabled) | OFF | `speech_localizer.py:710` `"thinking": {"type": "disabled"}`; model `.env:113` `ERIS_TTS_LOCALIZER_MODEL=deepseek-flash` |

Notes:
- "Model string" is what Eris sends. The gateway resolves it with `config.ResolveModel`; only
  `deepseek-flash` resolves, everything else 400s with `model %q is not available`
  (`request_normalize.go:19-20`).
- RootAgent thinking-OFF depends on the executive client being built with `worker_role="executive"`
  — it is: `build_executive_client` → `build_deepseek_worker_client("executive")` wraps a
  `JsonlWorkerClient(role="executive")` whose `self.worker_role = normalize_worker_role(role)`
  (`deepseek_workers.py`). RootAgent prefers `executive_client` (`agent.py:213`, `root_session.py:111`).

---

## 3. Does chat use web search? (trace + verdict + what would enable it)

Trace: `runtime_writer.render` → `router.generate_public_reply(...)` (`runtime_writer.py:287`) →
`model_router.create_chat_completion(...)` (`model_router.py` `invoke()` builds `request_kwargs`
with messages/temperature/max_tokens/response_format/reasoning_effort/thinking_mode only — no
search/tools) → `client.create_chat_completion` (`client.py`) builds `payload` with
`model, messages, thinking, max_tokens, reasoning_effort, response_format` — **no `search`,
`search_enabled`, `web_search`, or `tools` key is ever added for a chat turn.**

Grep results: `search_enabled`/`web_search`/`self_search_enabled` exist **only in the tutor
subsystem** (`tutor_research_policy.py`, `tutor_research_runtime.py`, `settings_protocol.py`),
which is background research, not the public chat writer, and is disabled by default
(`runtime_settings_store.py:234-236` tutor defaults `False`).

Gateway side: `request_normalize.go` sets `Search: searchEnabled` where
`_, searchEnabled, _ := config.GetModelConfig(resolvedModel)` and `GetModelConfig("deepseek-flash")`
returns `search=false` (and the test `TestGetModelConfig` asserts exactly `search=false`). The
chat pass-through (`collectOpenAIChatPassThrough`) only forwards temperature/top_p/max_tokens/
penalties/stop — a client `search_enabled` would be dropped. `SearchEnabled` in
`assistantturn/turn.go` governs only citation-link rewriting of upstream output, not whether search
runs.

**Verdict: web search is OFF end-to-end and cannot be turned on from the client at this gateway.**
What would turn it on: (1) the gateway must advertise a search-capable model and have
`GetModelConfig` return `search=true` for it (today only `deepseek-flash` exists and it is
`search=false`; the referenced `deepseek-flash-search` appears **only in gateway test fixtures**,
not in `supportedModelIDs`), AND (2) Eris must send that model id (or the gateway must honor a
pass-through search flag). Both are missing today.

---

## 4. Is Flash-vs-Pro real or fictional on this gateway?

**Fictional.** Two independent reasons:

1. **Model is pinned per worker, routing never selects it.**
   `load_worker_spec` resolves `model` from `get_secret(f"{role}_MODEL") or ERIS_DS2API_MODEL or
   ERIS_DS_MODEL or "deepseek-v4-flash"` (`deepseek_workers.py`). `.env` sets
   `ERIS_DS2API_MODEL=deepseek-flash` (`.env:34`) and `ERIS_DS_MODEL=deepseek-flash` (`.env:44`),
   so every worker (companion, surface, executive, …) gets `deepseek-flash`. Nothing maps
   `CompanionRouteDecision.tier=="pro"` to a different model string: `route_companion_turn` is
   imported in `orchestrator.py:26` but **has zero call sites** in the runtime
   (only tests call it). `runtime_context` never gets `routing_context`/`thinking_mode`/
   `use_escalation` populated (ContextAssembler.assemble sets none of them), so the writer falls to
   its defaults. Even the budget hook `compile_public_reply_context(route=...)` is called by
   `context_assembler.py` **without** `route=`, so routing reasons don't even shape the prompt
   budget in production.

2. **The gateway rejects the "Pro" / v4 ids anyway.**
   `config.supportedModelIDs = { "deepseek-flash" }` (`models.go`). `ResolveModel` rejects
   everything else; the gateway tests make this explicit: `TestResolveModelRejectsPro`
   (`deepseek-v4-pro` rejected), `TestResolveModelRejectsRetiredFlashIDs` (`deepseek-v4-flash`
   rejected). This matches the earlier real error `model "deepseek-flash" is not available` pattern
   — any non-`deepseek-flash` id 400s via `request_normalize.go:19-20`.

**Accepted gateway model ids:** exactly one — `deepseek-flash` (plus it explicitly *rejects*
`*-nothinking` suffixes and all `deepseek-v4-*` ids). `GetModelConfig("deepseek-flash")` →
`thinking=true, search=false, ok=true`.

Dormant mismatch worth noting: `src/llm/deepseek.py` still hard-codes
`DEEPSEEK_DEFAULT_MODEL="deepseek-v4-flash"` / `DEEPSEEK_STRONG_MODEL="deepseek-v4-pro"`. These are
not used on the live chat path because `.env` overrides the worker model to `deepseek-flash`, and
`normalize_model` does **not** rewrite `deepseek-v4-flash`→`deepseek-flash` (it only remaps the
deprecated `deepseek-chat`/`deepseek-reasoner`). Any code path that fell back to the deepseek.py
default instead of the env value would 400 at this gateway.

---

## 5. Thinking-override scope per lane

`client.py` (DeepSeek branch of `create_chat_completion`):
- `is_ds2api` is true when the base_url is not `api.deepseek.com` and contains `6011`/`localhost`/
  `127.0.0.1`. The live base is `http://127.0.0.1:5103/v1` → contains `127.0.0.1` → **is_ds2api=True**
  → `mode="enabled"` (forced), ignoring the caller's `thinking_mode` (`client.py:794-797`).
- The **only** escape: `worker_role=="executive"` AND
  `ERIS_EXECUTIVE_THINKING_DISABLED in {1,true,yes}` → `mode="disabled"` (`client.py:803-806`).
  `.env:38` sets `ERIS_EXECUTIVE_THINKING_DISABLED=1`.
- When `mode=="enabled"`: `max_tokens` is bumped to `max(max_tokens, 2048)` and `reasoning_effort`
  is sent; temperature/penalties are dropped (only meaningful in non-thinking mode).

Per lane:
- **RootAgent (executive):** thinking **OFF** today (escape hatch active). Fast.
- **Surface writer (surface):** thinking **ON (forced)**, no escape hatch — this is the slow,
  user-visible lane. It also self-selects `thinking_mode="enabled"` by default
  (`runtime_writer.py` generate_kwargs), so even removing the force would need the lane to pass
  `disabled`.
- **Speech localizer (tts_localizer):** **bypasses `client.py`** entirely — `_translate_with_deepseek_api`
  calls `requests.post` directly with `"thinking": {"type": "disabled"}` (`speech_localizer.py:710-712`,
  comment at :712 "KHÔNG đi qua llm/client.py"). So it is thinking-OFF regardless of the force.

Net: today exactly one chat lane runs forced-thinking — the **surface writer** — and it is the one
that produces what the user reads. The global `.env` `ERIS_DEEPSEEK_THINKING=disabled` (`.env:14`)
is overridden for localhost and has no effect on the writer.

---

## 6. Ranked fix directions (each with file:line) + must-preserve

Ranked by leverage-to-risk for the user's goal (route between a web-search model and a
strong-reasoning model without being slowed by forced thinking).

### (i) Let chat actually use web search when the turn needs current info
This is gated at TWO layers; both must change.
1. **Gateway**: add a search-capable model to `supportedModelIDs` and make `GetModelConfig` return
   `search=true` for it — `tools/whale2api/internal/config/models.go` (`supportedModelIDs:20-22`,
   `GetModelConfig:51-58`). The gateway already has `deepseek-flash-search` plumbing in test
   fixtures (`assistantturn/turn_test.go:33`) and citation rewriting in `assistantturn/turn.go:97`,
   so wiring a real `deepseek-flash-search` entry is the smallest gateway change. Alternatively,
   let the chat surface honor a pass-through `search` flag by adding it to
   `collectOpenAIChatPassThrough` (`request_normalize.go`) and threading it to `StandardRequest.Search`.
2. **Eris client**: send either the search model id or the search flag. Lowest-blast-radius option:
   add a `search`/`model` override argument to `generate_public_reply` → `create_chat_completion`
   payload in `src/llm/client.py` (payload assembly ~`client.py:789-818`), set only when a turn is
   flagged "needs current info".
   Preferred trigger: a cheap intent flag already decided by RootAgent (it runs thinking-OFF and is
   fast), not a second model call.

### (ii) Make the routing decision actually control model + thinking for the surface lane
Today the decision is computed-but-dead and the writer is force-thinking.
1. **Wire the router in**: call `route_companion_turn(user_text, recent_history=...)` where the chat
   turn is assembled and stash its outputs into `runtime_context` as `routing_context`
   (`decision.prompt_context()`), `thinking_mode`, `reasoning_effort`, `use_escalation`. Natural
   home: `src/runtime/conversation/context_assembler.py` `assemble()` (it already builds
   `runtime_context`; it currently calls `compile_public_reply_context(...)` WITHOUT `route=`, so
   also pass `route=decision` there to re-enable budget shaping). The writer already reads these keys
   (`runtime_writer.py` generate_kwargs: `routing_context`, `thinking_mode`, `reasoning_effort`,
   `use_escalation`).
2. **Add a surface escape hatch in client.py** analogous to executive's: in
   `src/llm/client.py:803-806`, allow `worker_role=="surface"` + a new
   `ERIS_SURFACE_THINKING_FOLLOWS_CALLER=1` (or similar) to honor the caller's `thinking_mode`
   instead of forcing enabled. Without this, step 1 cannot make the writer fast.
3. If a true stronger model becomes available at the gateway (today it is not), map `tier=="pro"`
   to that model id at client-build time (`deepseek_workers.load_worker_spec` or an escalation
   client in `llm/service.py:_resolve_escalation_client:232`). Until the gateway offers a second
   model, "Pro" can only mean "thinking-on", not a different model.

### (iii) Replace/augment the keyword heuristic so it survives English / Gen-Z slang / teencode
`companion_model_routing.py` normalizes to diacritic-stripped Vietnamese and matches fixed phrase
lists (`_plain:19-23`, `_STYLE_REQUESTS`/`_ABSTRACT_MARKERS`/… `:46-115`). English, missing-diacritic,
ALL-CAPS, and teencode turns miss every list and fall through to Flash/no-thinking.
- Lowest-cost, no-extra-model-call fix: feed signals Eris ALREADY computes per turn into the router
  instead of re-deriving from raw text. The affect projection
  (`affective_voice_state` in `runtime/conversation/context_assembler.py`, built by
  `project_affective_voice_state`) and the RootAgent's own `intent`/`semantic_frame` are available
  before the writer runs. Have `route_companion_turn` accept an optional `signals` mapping (affect
  valence/arousal, RootAgent intent, meaning_missing) and let those raise the score independently of
  keyword hits. RootAgent runs thinking-OFF and is fast, so its intent label is effectively a free
  classifier.
- Make `_SIMPLE_CHAT`/length checks language-agnostic (token count + a tiny multilingual greeting
  set) so slang/English short turns still get the cheap path without needing Vietnamese phrases.
- Do NOT add a blocking extra LLM call per turn; reuse the already-computed signals.

### Must-preserve (do not regress while fixing the above)
- **Japanese TTS contract**: the speech localizer must still fail-closed to valid JA and keep its
  direct-POST `thinking: disabled` behavior (`speech_localizer.py`). Don't route localization through
  the forced-thinking client.
- **Single-speaker / single-writer**: the surface writer remains the only lane that emits
  user-visible text (`bootstrap.py` logs `single_writer=1`, `surface=wording_only`). Routing/search
  changes must not add a second speaking lane.
- **Executive thinking-disabled carve-out**: keep `ERIS_EXECUTIVE_THINKING_DISABLED` honored for
  `worker_role=="executive"` (`client.py:803-806`, `.env:38`). A new surface escape hatch must be
  additive, not a replacement of this check.
- **Secret redaction / provenance**: search/citation output must still pass existing claim/grounding
  guards; don't let web citations bypass the evidence policy in `runtime_writer.py`.
- **One model today**: any change that sends a non-`deepseek-flash` id will 400 until the gateway
  advertises that id — ship the gateway change first or gate the client change behind model
  availability.

---

## 7. Open questions

- Is `deepseek-flash-search` reachable upstream at all, or is it purely a test fixture? It appears
  only in gateway tests (`assistantturn/turn_test.go:33`), never in `supportedModelIDs`. Needs a
  gateway owner to confirm the upstream SKU exists before building on it.
- Does the upstream DeepSeek-Web account behind the gateway actually support a search mode? The
  gateway's `UpstreamSafeModelType` normalizes everything to `"default"` because "the upstream
  account only enables the default mode" (`models.go`), which suggests search may not be enabled
  upstream even if advertised.
- Can thinking and search coexist upstream? The gateway models thinking and search as independent
  booleans on one model, but there is no live model that has both true, so this is untested here.
- Is there any non-chat path (autonomous/self-turn) that already differs in model/thinking? The
  autonomous orchestrator reuses the same surface writer and `deepseek-flash`; worth a dedicated
  trace if autonomous latency matters.

---

### Tradeoff map (summary)
- At THIS gateway today: one model (`deepseek-flash`), `thinking=true` available, `search=false`
  always. There is **no** separate strong-reasoning model and **no** search model exposed, so
  "search vs reasoning" is not even a live choice — both would require gateway changes.
- "Strong reasoning" today = `deepseek-flash` with `thinking:enabled` (what the writer already does,
  slowly). "Fast" = same model with thinking disabled (what executive + localizer do).
- If/when a search model is added: whether thinking+search can coexist is unverified (see §7); plan
  for them being mutually exclusive until proven otherwise.

Content was rephrased for compliance with licensing restrictions where external/gateway text was summarized.
