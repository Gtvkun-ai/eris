# Eris Personality-Flattening Report (READ-ONLY investigation)

Scope: trace every stage from RootAgent move-selection → self-verify → surface writer → post-processing → TTS and determine WHICH stages can sand down Eris's personality (edge, teasing, playful self-deprecation, mild sulk, opinion). Anchored on the real trace `events_20261014T070850Z` (session 14:08) where an edgy move was rewritten flat by self-verify.

---

## 1. Verdict (prompt only, or more?)

**It is not only the prompt. There are at least four independent flatteners, and the prompts are actually the LEAST guilty layer.** The three prompts that matter most — the RootAgent system prompt (`agent.py`), the surface-writer prompt (`model_router._public_reply_prompt`), and the voice contract (`eris_voice_contract.py`) — have all been rewritten to be pro-personality and explicitly tell the model "don't neutralize toward a safe middle." The flattening comes from runtime/guard mechanisms layered on top of those prompts:

1. **[RUNTIME] SELF-VERIFY** (`agent.py::_verify_move`) — the proven culprit from the trace. A second model call, run on essentially every user-turn move, whose checklist frames a mild poke as "pressuring / violating what the user wants," producing a REVISE that deletes edge. This is the single most direct flattener.
2. **[RUNTIME/STATE] AFFECT COLD-START** (`cortex/affective_dynamics.py` baselines + `affective_voice_state.py`) — because the voice contract makes emotional intensity *follow* `AFFECTIVE_VOICE_STATE`, and that state starts near-neutral (low arousal, playfulness ≈ 0.10, relationship closeness/playful_safety = 0.0), a fresh or cold session is told to be flat **even if every prompt is perfect**. Edge/tease is explicitly gated on `playful_safety` being high.
3. **[GUARD] STANCE GUARD** (`social_stance_policy.py::guard_subjective_stance_payload`) — a deterministic rewrite that, on `stance_contest` frames, can overwrite the model's wording with a fixed template ("Không. Tôi vẫn nghĩ vậy."), stripping any nuance/edge. Narrow trigger, but when it fires it is a hard flatten.
4. **[GUARD/SANITIZER] STAGE-DIRECTION STRIP on the DISPLAY surface** (`stage_transformers.py` + `final_surface_sanitizer.py`) — parenthetical performance beats like `(cười khẽ)` / `(nhướn mày)` are pulled out of the text the user *reads* and shunted to the avatar channel. Safe for secrets, but it does remove tone-carrying beats from the display string.

The performance-act catalog and the writer's performance-preset enum are **not** the main problem — the enum is expressive (`dry_tease`, `playful`, `annoyed_soft`, `warm_embarrassed`, `surprised`), but it defaults to `"neutral"` and the catalog's acts are gated behind `requires_request_marker` (only fire when the user literally asks "cười đi / dỗi đi"), so spontaneous performance is limited.

Direct answer to the user ("là prompt đang bóp hay còn gì bóp nữa"): **the prompt is barely bóp; the real squeezing is self-verify + a cold affect state + the stance guard. These are structural, not prompt-wording, issues.**

---

## 2. Per-stage flatten table

| # | Stage | Layer | Flattens? | Evidence (file — <20-word quote / note) |
|---|-------|-------|-----------|------------------------------------------|
| 1 | RootAgent move selection (`_system_prompt`) | PROMPT | **No** (actively anti-flatten) | `agent.py` ~L795: "Đừng trung hòa mọi move về cùng một mức trung lập an toàn." |
| 2 | **Self-verify** (`_verify_move`) | RUNTIME | **YES — primary** | `agent.py` L678: checklist asks if move "vi phạm điều user vừa yêu cầu hoặc cấm" → poke misread as pressure |
| 3 | continue_thinking / revise loop | RUNTIME | Minor | `agent.py`: reflection capped at 2, no-progress streak forces early finalize — can over-deliberate toward safe but bounded |
| 4 | Surface writer prompt (`_public_reply_prompt`) | PROMPT | **No** (anti-flatten) | `model_router.py` L1699: "những phản xạ rất người thì cứ để bật ra khi cảm xúc thật đang có" |
| 5 | Voice contract (`CHAT_VOICE_CORE_V39`) | PROMPT | **No**, but delegates intensity to state | `eris_voice_contract.py`: "Hướng và cường độ cảm xúc... phải đi theo AFFECTIVE_VOICE_STATE" |
| 6 | **Affect voice state projection** | RUNTIME/STATE | **YES — hidden** | `affective_voice_state.py` + `affective_dynamics.py` baselines: playfulness 0.10, closeness/playful_safety 0.0 at cold start |
| 7 | **Stance guard** (`guard_subjective_stance_payload`) | GUARD | **YES (narrow)** | `social_stance_policy.py` L163: rewrites to `build_direct_stance_text()` fixed templates on stance_contest |
| 8 | Performance preset enum + default | RUNTIME | Mild | `model_router.py` L588 enum is rich, but fallback `"neutral"` (L2090); writer may omit preset |
| 9 | Performance act catalog | RUNTIME | Mild (gated) | `performance_act_catalog.py`: `requires_request_marker=True` — acts only fire when user asks |
| 10 | Stage transformers — DisplayFilter / ActionTagExtractor | SANITIZER | **Partial (display)** | `stage_transformers.py`: `(cười khẽ)` extracted out of display text into avatar motion |
| 11 | Final surface sanitizer | SANITIZER | **No (SAFE)** | `final_surface_sanitizer.py`: only secrets/paths/stack-trace/stage-paren words; "không bóp câu bình thường" |
| 12 | discourse_surface renderer | GUARD | Deterministic-only | `discourse_surface.py`: fixed templates only for REPEAT/CONFIRM/CLARIFY/REPAIR; empty otherwise, model wins |
| 13 | public_surface_commit | SANITIZER | **No (SAFE)** | `public_surface_commit.py`: wraps transformers+sanitizer for history/memory commit |
| 14 | speech_persona_polish (TTS) | GUARD | **No (preserves)** | `speech_persona_polish.py`: "preserve source valence, energy, irritation, delight, sadness, playfulness" |
| 15 | addressing_policy | SANITIZER | **No (SAFE)** | normalizes honorifics (Ngài→bạn), does not touch tone |
| 16 | prosody_director | RUNTIME | Neutral/plumbing | maps delivery hint → prosody; follows the chosen performance preset |

Legend: PROMPT = wording-only, RUNTIME/STATE = computed signal, GUARD/SANITIZER = deterministic rewrite.

---

## 3. Deep dive: self-verify (the proven culprit)

**Where:** `src/runtime/conversation/agent.py`, `_verify_move` (def ~L636), triggered from `decide` at the finalize branch:

```python
if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say"))):
    return self._verify_move(...)
```

This means self-verify runs on **every user-turn that produces a move** — including casual small talk and deflection turns like the trace case. It is not scoped to high-stakes turns.

**The verify payload checklist** (`agent.py` L675-679), verbatim:

- "Move này có thật sự đạt intent đã nêu không?"
- "Nó có LẶP lại điều vừa nói trong recent_public_history không?"
- "Nó có hợp affect/relationship/personality hiện tại không?"
- **"Nó có vi phạm điều user vừa yêu cầu hoặc cấm không (ví dụ hỏi ngược khi bị cấm, bắt user chọn hộ)?"**

**The verify system prompt** (`agent.py` L683-690), verbatim:

> "Bạn đang TỰ KIỂM một move Eris vừa chọn trước khi phát ra public. Chỉ kiểm chất lượng, KHÔNG viết lại dài dòng hay thêm phong cách. Nếu move đã ổn, trả kind=confirm. Nếu cần sửa nhỏ cho đúng self_check, trả kind=revise ... Nếu move không nên nói ra (lặp, vi phạm điều user cấm, không đạt intent), trả kind=withdraw. withdraw là lựa chọn hợp lệ khi im lặng tốt hơn."

**Why it deleted the edge in the trace:** The user said "erm ko có gì đâu á" (a deflection). Question #4 asks whether the move "violates what the user just asked or forbade." A low-effort verify model (reasoning_effort="low", temperature=0.2, 400 tokens — L693-702) reads the poke "Không có gì mà vẫn mở tôi lên" as *pressuring the user who clearly wants to drop it*, i.e. a soft violation, and returns `kind=REVISE` with the note "không nhắc lại việc user mở lên." The checklist contains **no clause that teases, edge, mild sulk, or playful self-deprecation are legitimate and must be preserved.** It only lists ways a move can be *too much*; it never lists under-expression (blandness) as a defect. The optimization pressure is strictly one-directional: toward safer, quieter output.

**Design asymmetry:** The prompt further says "KHÔNG viết lại ... thêm phong cách" — verify is explicitly forbidden to *add* personality but implicitly licensed to *remove* it. Combined with "withdraw là lựa chọn hợp lệ khi im lặng tốt hơn," the verify step is biased toward silence/neutrality.

**Fix type — hybrid, leaning structural:**
- **Prompt tweak (necessary, insufficient):** add an explicit clause to the verify checklist/system that edge, teasing, playful self-deprecation, mild sulk and opinion are *in-character and must NOT be revised out*; only revise for genuine boundary/fact violations, repetition, or missed intent. Add a symmetric defect: "Move có bị trung hòa / mất cá tính so với affect & intent không?" so the pressure is two-directional.
- **Structural (recommended):** do **not** run self-verify on casual/low-stakes turns. Gate `_verify_move` so it only fires when the move touches a real risk surface (fact claim, capability/tool report, boundary, safety, stance_contest). A deflection-reply or small-talk move should finalize without a second neutralizing model pass. This directly prevents the trace failure, which was a casual deflection turn.

---

## 4. Affect-state startup defaults (the hidden flattener)

The voice contract (`eris_voice_contract.py`) and the writer prompt both hand emotional authority to `AFFECTIVE_VOICE_STATE`:

> "Hướng và cường độ cảm xúc của câu phải đi theo AFFECTIVE_VOICE_STATE hiện tại." (`CHAT_VOICE_CORE_V39`)

And edge/tease is explicitly conditioned on relationship bandwidth:

> "Khi playful_safety đủ cao, được phép đùa cheeky, trêu nhẹ..." (`CHAT_STYLE_RULES_V39`, rule 4)

So the question is: what is that state at cold start?

**Core affect baselines** (`cortex/affective_dynamics.py`, `CORE_BASELINE` L36 / `AUX_BASELINE` L50):
- `valence` 0.02, `arousal` 0.16, `tenderness` 0.16, `fatigue` 0.12, `playful_pressure` 0.0
- `playfulness` (aux) **0.10**, `delight` low, `sadness` 0.22, `anxiety` 0.27

**Relationship bandwidth** (`affective_voice_state.py` project, when `relationship is None` or fresh): `closeness` 0.0, `playful_safety` 0.0, `familiarity` 0.0, `boundary_safety` 0.5.

**Consequence:** On a fresh/cold session with no accumulated affect events (`has_dynamic_affect` false → the legacy branch, or dynamic branch resting at baseline), the projected state is low-arousal, playfulness ≈ 0.10, and `playful_safety = 0.0`. Under the contract's own rule ("tease only when playful_safety high"), the writer is **correctly** producing flat output — the prompt is perfect, but the state it is told to obey says "there is almost no playfulness and no established safety to tease." This is a genuine hidden flattener for early-session turns: personality has to "warm up" via affect events before edge is licensed, and the warm-up decay constants are on the order of tens of minutes (`playfulness` half-life ~24 min, `playful_pressure` ~22 min per the decay tables around L66-92).

`expressive_drive` is also computed from these low inputs with a 0.12 floor and small positive weights minus restraint/fatigue (`affective_voice_state.py`), so at baseline it sits low — reinforcing a muted delivery.

**Fix type — structural/tuning:** either (a) raise the cold-start playfulness / playful_safety floor for an INFJ-VTuber persona so tease is licensed sooner, or (b) decouple "edge is allowed" from `playful_safety` so dry/self-deprecating humor (which is in-character even with a stranger) is not gated behind relationship warmth, or (c) speed up warm-up for playful axes. This is **not** fixable by editing prompts alone — the prompts already say the right thing; they are faithfully obeying a flat number.

---

## 5. Ranked top flatteners with fix direction

1. **Self-verify checklist Q4 + one-directional revise bias** — [RUNTIME] `agent.py` L678 / L683-690. **Highest impact; proven in trace.** Fix: prompt clause protecting edge + structurally skip verify on casual turns.
2. **Affect cold-start neutrality feeding a state-authoritative voice contract** — [RUNTIME/STATE] `affective_dynamics.py` baselines + `eris_voice_contract.py`. **High, hidden.** Fix: raise cold-start playful floor / decouple dry humor from playful_safety (tuning, structural).
3. **Stance guard fixed-template rewrite** — [GUARD] `social_stance_policy.py` L163 `build_direct_stance_text`. **Medium, narrow (only stance_contest + when `needs_direct_stance_rewrite` true).** Fix: let the guard enforce only the *stance-first ordering* and keep the model's edgy wording when it already opens with the stance; reserve the fixed template as a last-resort fallback.
4. **Stage-direction strip on display surface** — [SANITIZER] `stage_transformers.py` ActionTagExtractor/`_PARENS_ACTION_RE`. **Low-medium.** Fix (optional): keep short expressive beats in the *display* text (they are tone, not secrets) while still routing an avatar motion; only strip from TTS/memory.
5. **Performance default `"neutral"` + marker-gated catalog** — [RUNTIME] `model_router.py` L2090, `performance_act_catalog.py` `requires_request_marker`. **Low.** Fix: default to an affect-derived preset instead of literal `"neutral"`; allow a subset of acts (dry_tease, fake_sulk) to self-trigger from affect, not only explicit user requests.

---

## 6. SAFE-keep list (do NOT loosen — these protect correctness, not personality)

- `final_surface_sanitizer.py` — secret/API-key/stack-trace/internal-path redaction and stage-word stripping. Fail-closed on secrets. **Keep as-is.**
- `public_surface_commit.py` — history/memory/TTS commit surfaces built through the sanitizer. **Keep.**
- `addressing_policy.py` / `clean_public_addressing` — honorific normalization (language-lock / forbidden-honorific guard). **Keep.**
- `speech_persona_polish.py` — explicitly preserves source valence/energy/irritation/delight/playfulness and blocks only forbidden honorifics, unlicensed relationship-escalation, apology, promise. It does NOT flatten tone. **Keep.**
- The language-lock portions of `_public_reply_prompt` (display stays in `vi`, speech in `ja`). **Keep.**
- `discourse_surface.py` deterministic templates — only fire for exact repeat/confirm/clarify/repair of a referenced turn; otherwise defers to the model. **Keep.**

A later fix that loosens flatteners (1)–(5) must not touch the above, or it risks regressing secret-redaction and the vi/ja language lock.

---

## 7. Open questions / limits of this read-only pass

- **Exact verify output in the trace:** the investigation brief supplies the REVISE note ("không nhắc lại việc user mở lên"); I confirmed the mechanism and prompt that produce it, but did not re-run the model, so the causal link is inferred from the checklist wording, not observed token-by-token here.
- **`has_dynamic_affect` at the 14:08 turn:** whether that specific session had already accumulated affect events (dynamic branch) or was resting at baseline is not determinable from code alone; the earlier `dry_tease` success in the same session suggests some playful state existed, which means the self-verify REVISE — not a cold affect state — was the dominant flattener for *that* turn. Cold-start affect is a separate, additional flattener for fresh sessions.
- **`assistant_act.kind_invalid:proactive_topic_open` warning:** `AssistantActKind` (`semantic_frame.py` L62) has no `proactive_topic_open`; unknown kinds that are not in `_ASSISTANT_ACT_KIND_ALIASES` degrade to `AssistantActKind.OTHER` with a logged violation (`validate_assistant_act`, L648-671). This is a soft-metadata downgrade and does **not** block or rewrite the public text (the writer prompt states soft-metadata errors "KHÔNG bao giờ được làm bạn bỏ text"), so it is not itself a personality flattener — but a repeatedly-rejected expressive act enum means the richer intent is silently coerced to OTHER, which may indirectly dull downstream prosody/performance selection. Worth confirming whether `OTHER` maps to the `"neutral"` performance default.
- Whether the no-progress early-finalize path (`_advance_progress_and_maybe_finalize`, streak ≥ 2) ever truncates a would-be edgier continuation was not traced end-to-end.
