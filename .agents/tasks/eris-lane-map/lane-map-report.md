# Eris Lane Map — Read-Only Architecture Report

Scope: `src/runtime/` on branch `main` (HEAD `1b3dbd1d`). This is a read-only audit. No code was modified.

---

## 1. Executive summary

Eris already has the Kiro-style spine the user wants — it is just **buried under a decade of overlapping "cognition" modules that all look like they could speak but mostly cannot.** Critically, the **speech** path is already single-threaded through one governor even though **many background threads run concurrently**: there is exactly ONE autonomous *speech* production loop (`AutonomousLoopRuntimeMixin.run_loop` → `orchestrator.run_iteration`), exactly ONE governor/decider (`ConversationKernel` + `RootAgent`, file `conversation/kernel.py` + `conversation/agent.py`), and exactly ONE speaker (`RuntimeConversationDeliveryAdapter.deliver` → `_send_decision_to_body`, the single UDP/TTS chokepoint in `public_output_runtime.py`). Around that spine, ~15+ background threads tick independently (`ai_orchestrated/state_reducer.py`, `mental_process_runtime.py`, `random_chat_seed_service.py`, `private_mind_loop.py` runners, `semantic_environment_worker.py`, `activation_nervous_system_v98.py`, `motivational_focus_v99.py`, `neuro_continuation.py`, `mind_loop.py`, …). **None of these background threads call `_send_decision_to_body`** (verified: only the delivery adapter and `_emit_body_only` do) — they are **idea-sources** that emit typed `SocialSpeechCandidate` / `ExecutiveAffordance` / `ThoughtObject` objects, and their own docstrings assert they have **no public-speech rights** and must route through the kernel.

**Single most important finding:** The collision/duplication symptom is **not** caused by many lanes each calling TTS. With one real exception (`AIAutonomousOrchestrator._emit_body_only`, which is non-linguistic and therefore cannot speak words), every speech path already funnels through the kernel's generation-guarded delivery adapter. The pain the user reports ("agent loop lỗi lặp 2–3 lần cho 1 câu", "autonomous phối hợp cực tệ") comes from three things that are all fixable without re-architecting:
1. **A hard contract break** in the seed/idea-source path (`mental_material_runtime.project()` passes `seed_event_kind` / `seed_epistemic_mode` / `seed_open_loop` to `SocialSpeechCandidate`, which does not declare those fields → `TypeError`). This silently kills the idea→candidate projection, so the governor loses good proposals and the loop retries.
2. **A barge-in ordering race**: `chat_cycle._enter_chat_cycle` cancels TTS unconditionally on `chat_start`, *before* `incoming_dispatcher._handle_chat` can classify the text as a harmless backchannel ("ừ/à"). The two guards fight.
3. **Lane sprawl itself**: ~15–20 modules produce near-duplicate candidate/affordance types into the same executive, so proposals get regenerated, overwritten, and reordered. This is a *consolidation* problem, not a *speech-arbitration* problem.

The target architecture (idea-sources → single DECIDE → single SPEAKER) is therefore ~70% already built. The work is to (a) fix the two bugs, (b) collapse the redundant idea-sources into a small, named proposal bus, and (c) formally bless the kernel as the only governor and the delivery adapter as the only speaker.

---

## 2. Lane inventory

Classification legend: **GOVERNOR** (central decider), **SPEAKER** (writer+TTS executor), **IDEA-SOURCE** (background propose-only), **MEMORY/STATE** (persistence/projection), **REDUNDANT** (merge/retire candidate).

| Lane / component | File(s) & entry point | Produces | Consumed by | Can reach mic? | Role |
|---|---|---|---|---|---|
| **Autonomous production loop** | `autonomous_loop_runtime.py` → `run_loop()` → `_run_loop_iteration()` → `orchestrator.run_iteration()`. Trigger: single long-lived thread, timer + `_wake_autonomous_loop`. | One "opportunity" per tick submitted to the kernel. | ConversationKernel. | **Only via kernel** — it calls `_run_v12_signal` → `kernel.handle_event`/`handle_due_continuation`. No direct TTS. | GOVERNOR (driver half) |
| **ConversationKernel** | `conversation/kernel.py` → `handle_event` / `handle_due_continuation`. Trigger: user turns (via `chat_cycle`) and autonomous signals. | `ConversationRunResult`; owns generation, run_id, delivery_id, phase, continuation lease. | `delivery_adapter`, orchestrators, chat cycle. | Indirectly — it is the only thing that calls `delivery.deliver`. | **GOVERNOR** (the decider) |
| **RootAgent** | `conversation/agent.py` (`RootAgent`, used by kernel via `self.agent.decide(...)`). | `NextConversationMove` or `NoReply` (the zero-or-one action decision). | ConversationKernel. | No (returns a decision object). | **GOVERNOR** (decision policy) |
| **ConversationWriter** | `conversation/writer.py` → `writer.realize(turn=...)`. Called by kernel after a move is chosen. | `RenderedConversationMove` (surface text + metadata). | delivery_adapter. | No — produces text, does not dispatch. | SPEAKER (writer half) |
| **Delivery adapter** | `conversation/delivery_adapter.py` → `RuntimeConversationDeliveryAdapter.deliver`. Called only by kernel. Docstring: "The single high-level adapter allowed to commit and publish assistant speech." | Public commit: calls `host._send_decision_to_body`, then writes `chat_history` + `session_turn_ledger` **after** transport accepts. | Body transport / TTS. | **YES — the sanctioned path.** | **SPEAKER** |
| **`_send_decision_to_body`** | `public_output_runtime.py` → `_send_decision_to_body(decision, channel=...)`. | Builds stage frame, applies audio-floor + stage-ownership guards, transitions lifecycle to `CONTENT_COMMITTED`, dispatches UDP/TTS. | TTS engine, Live2D body, UI. | **YES — THE single mic chokepoint.** | **SPEAKER** (executor) |
| **AIChatOrchestrator** | `ai_orchestrated/orchestrator.py` (`AIChatOrchestrator.run`). Trigger: user turn from `chat_cycle._run_chat_cycle_inner`. | Assembles context + evidence, calls `kernel.handle_event`. | ConversationKernel. | Via kernel only. | GOVERNOR (chat ingress) |
| **AIAutonomousOrchestrator** | `ai_orchestrated/orchestrator.py` (`run_iteration`, `_run_v12_signal`, `run_social_signal`, `run_force_speak`, `_emit_body_only`). | Autonomous/social/opening signals to kernel; **body-only motion** directly. | ConversationKernel; body transport (for motion only). | **Via kernel for speech. `_emit_body_only` calls `_send_decision_to_body` directly — but asserts `_is_nonlinguistic_body_decision` (empty text, `should_speak=False`), so it cannot speak words.** | GOVERNOR (autonomous ingress) |
| **Continuation lease** | `conversation/continuation.py` (`ContinuationLeaseScheduler`). | Schedules the next self-wake after a delivered move; anti-infinite-self-wake. | Kernel. | No. | MEMORY/STATE (scheduling) |
| **mental_material_runtime** | `mental_material_runtime.py` → `MentalMaterialRuntime.project()`. Fed by `random_chat_seed_service` via `ingest_seed`. | Two affordance lists (concern vs expression) wrapping `SocialSpeechCandidate`. | `expression_urge_runtime`, `executive_cortex`. | No (candidate only). **Currently broken — see §3.** | IDEA-SOURCE (seed) |
| **random_chat_seed(_service)** | `ai_orchestrated/random_chat_seed.py`, `random_chat_seed_service.py`. | Validated seeds → `mental_material_runtime.ingest_seed`. Docstring: seed "KHÔNG tự trở thành concern hay speech candidate." | mental_material_runtime. | No. | IDEA-SOURCE (seed) |
| **expression_urge_runtime** | `expression_urge_runtime.py` (`ExpressionUrgeRuntime`). | Promotes affordances to "urges" (desire-to-express), filters by boundary/topic. | executive_cortex / autonomous signal metadata. | No. | IDEA-SOURCE |
| **subject_initiative_runtime** | `subject_initiative_runtime.py`. "Bridge không tạo Need và không quyết định nói." | `ExecutiveAffordance` from Subject Core motives. | executive_cortex. | No. | IDEA-SOURCE |
| **subject_proposals / behavior_proposals / proposal_lifecycle** | `subject_proposals.py`, `behavior_proposals.py`, `proposal_lifecycle.py`. | Typed proposals + one-shot consume ledger. | executive_cortex, subject_initiative_runtime. | No. | IDEA-SOURCE / MEMORY (ledger) |
| **subconscious_loop** | `subconscious_loop.py` (`SubconsciousLoop.tick`), driven by `mental_process_runtime.tick`. Docstring: "Loop này không tự quyết định nói." | `ThoughtObject`, `surface_seed`, `audit_report`. | mental material / blackboard. | No. | IDEA-SOURCE |
| **mind_loop** | `mind_loop.py` (`MindLoop`). "coordinator, không phải một bộ não mới." | `MindDecision` / `SubjectExecutiveCommit` for Subject Core. | Subject Core. | No. | IDEA-SOURCE (deliberation) |
| **private_mind_loop / private_mind_daemon** | `private_mind_loop.py`, `private_mind_daemon.py`. Driven by `.tick()` from `observer_private_runtime`. | Inner judgments, user-model, `private_mind_surface_queue`, `private_mind_digest`. | Context payload in `_send_decision_to_body` (as digest), active_concern_runtime. | No — digest is context, not speech. | IDEA-SOURCE / MEMORY/STATE |
| **private_life_daemon** | `private_life_daemon.py` (`PrivateLifeDaemon`), `.tick()`. | `private_life_surface_queue`, `private_life_digest`. | Context payload / panel. | No. | IDEA-SOURCE / MEMORY/STATE |
| **banter_arbiter** | `banter_arbiter.py` (`BanterArbiter.arbitrate(decision)`). | A possibly-rewritten `Decision` (repair/aside). | Caller inside the single pipeline (returns the Decision; does not dispatch). | No — mutates/returns a Decision; the kernel path still commits it. | IDEA-SOURCE (decision transform) → fold into writer/governor |
| **horizon_arbiter** | `horizon_arbiter.py` (`HorizonArbiter`). | Topic/horizon arbitration hints. | executive / planner context. | No. | IDEA-SOURCE |
| **final_speech_authority** | `final_speech_authority.py` (`FinalSpeechAuthority.seal` / `verify_or_restore`, `GLOBAL_FINAL_SPEECH_AUTHORITY`). | Seals speech fields + hash; restores if a later layer mutates text. | The single pipeline (guard). | No — it protects the one Decision, not an independent speaker. | MEMORY/STATE (integrity guard) |
| **semantic_authority_v95** | `semantic_authority_v95.py`. | Semantic frame authority for an utterance. | writer / delivery. | No. | MEMORY/STATE (contract) |
| **intention_authority** | `intention_authority.py`. | Intention-plan ownership for autonomous turns (`last_ai_intention_plan`). | `_send_decision_to_body` autonomous payload. | No (payload metadata). | MEMORY/STATE |
| **expression_competition_workspace_v103 / expression_commitment_transition_v102** | `expression_competition_workspace_v103.py`, `expression_commitment_transition_v102.py`. | Stabilizes competition between self-owned expression commitments; commitment transitions. | expression_urge / executive. | No. | IDEA-SOURCE (arbitration) — **high merge candidate** |
| **utterance_selector / utterance_evaluator** | `utterance_selector.py`, `utterance_evaluator.py`. | Selects/scores candidate utterances. | executive / writer. | No. | IDEA-SOURCE (scoring) — **merge candidate** |
| **nervous_system_v103_final** | `nervous_system_v103_final.py` (`NervousAutonomousAuthorityV103`). "Final authority cho normal autonomous expression path." | Activation/pressure gating for autonomous expression. | autonomous signal gating. | No — gates whether a signal is raised; does not dispatch. | IDEA-SOURCE (gating) |
| **public_turn_runtime / public_surface_commit / public_output_runtime** | `public_turn_runtime.py`, `public_surface_commit.py`, `public_output_runtime.py`. | Public turn ledger, surface split (display vs memory text), the dispatch mixin. | delivery_adapter / body. | `public_output_runtime` **yes** (hosts `_send_decision_to_body`); the other two are support. | SPEAKER (support) / MEMORY |
| **stage_dispatcher / stage_ownership** | `stage_dispatcher.py`, `stage_ownership.py`. | Stage frame dispatch + channel-ownership suppression (`_stage_channel_blocked`). | `_send_decision_to_body`. | Downstream of the one speaker (TTS scheduling). | SPEAKER (support) |
| **conversation_lane** | `conversation_lane.py` (`ConversationLane`, frozen dataclass). | Fast-path vs full-analysis routing hint for one chat turn. | chat orchestrator. | No. | IDEA-SOURCE (routing) |
| **incoming_dispatcher** | `incoming_dispatcher.py` → `_handle_chat`. | Routes transport messages; backchannel-preservation guard (~L131–142). | chat_cycle. | No (routes input). | GOVERNOR (input ingress) |
| **chat_cycle** | `chat_cycle.py` → `_enter_chat_cycle` / `_run_chat_cycle`. | Chat-mode entry/exit, barge-in TTS cancel, 2.5s turn-collision guard. | orchestrator. | No (cancels TTS, does not speak). | GOVERNOR (turn lifecycle) |
| **DeepSeek "roles"** | `ai_orchestrated/model_router.py` properties: `observer_client`, `deep_client` (critic), `surface_client`, `executive_client`; cognitive lanes `turn_executive`, `root_conversation`, `post_observer`, `autonomous`, `public_claim_verifier`, `tutor_background`. `companion` routing in `companion_model_routing.py`. | LLM inference per cognitive role. | kernel/writer/observer. | No — these are inference lanes, not speaking lanes. | IDEA-SOURCE / infra (model routing) |

---

## 3. Speech-commit paths (Part A — the collision root cause)

**The single sanctioned mic path:**
`kernel.handle_event` → `self.delivery.deliver(...)` (`conversation/kernel.py:325`) → `RuntimeConversationDeliveryAdapter.deliver` → `host._send_decision_to_body(decision, channel=...)` (`conversation/delivery_adapter.py:156`) → stage/TTS dispatch in `public_output_runtime.py` `_send_decision_to_body` (def at `public_output_runtime.py:182`).

**Who can commit speech / audio independently of the kernel:**

- `AIAutonomousOrchestrator._emit_body_only` → `host._send_decision_to_body(decision, channel="autonomous")` (`ai_orchestrated/orchestrator.py:902`). **This is the only direct caller of `_send_decision_to_body` outside the delivery adapter.** It builds a `Decision(text="", should_speak=False, ...)` and asserts `_is_nonlinguistic_body_decision(decision)` first (`orchestrator.py:901`), so it can only drive body motion, never speech. **Not a speech-collision source, but it is a second writer into the body channel and should ultimately route through the governor for consistency.**

- Barge-in / TTS cancellation is spread across two layers that can race:
  - `chat_cycle._enter_chat_cycle` calls `self._supersede_tts_for_new_user_turn("user_speech_started")` **unconditionally** on chat entry (`chat_cycle.py`, early in `_enter_chat_cycle`).
  - `incoming_dispatcher._handle_chat` classifies the text and **preserves** audio when `interrupt.kind == BACKCHANNEL and speech_busy` (`incoming_dispatcher.py:131–142`).
  - Because the UI's `chat_start` event reaches `_enter_chat_cycle` before the `chat` message body is classified, TTS can already be cancelled before the backchannel check runs. **This is the "chat_start hủy audio trước khi phân loại backchannel" race the audit flagged — confirmed in code order.**

**The contract break that starves the governor of proposals (P0):**
`mental_material_runtime.project()` builds a `common` dict with `seed_event_kind=...`, `seed_epistemic_mode=material.epistemic_mode`, `seed_open_loop=material.open_loop` (`mental_material_runtime.py:445–457`) and then constructs `SocialSpeechCandidate(**common, ...)` (lines 490 and 521). But `SocialSpeechCandidate` (`ai_orchestrated/social_candidate.py`) declares **no** `seed_event_kind` / `seed_epistemic_mode` / `seed_open_loop` fields → `TypeError: __init__() got an unexpected keyword argument 'seed_event_kind'`. Confirmed failing test exists: `src/tests/test_turn_floor_and_duplicate_reply_regressions.py::test_answered_user_event_stays_private_and_cannot_project_second_reply`. When this branch fires, the idea→candidate projection dies, the governor gets fewer/again-recomputed proposals, and the loop appears to "repeat 2–3 times for one question."

**Autonomous entry points that do NOT depend on the lease (confirmed, not necessarily a bug):**
`ai_orchestrated/orchestrator.py`: `run_iteration` fires `_run_v12_signal("autonomous_signal")` when the lease is due (`:1190–1191`), but also falls through to `autonomous_signal` when there is no pending capability event (`:1205`); `run_social_signal` (`:1168`, test-only caller) and `run_force_speak` (`:1171`) also enter without a lease. **All of them still pass through `_run_v12_signal` → kernel, and the kernel drops the signal if phase ∈ {thinking, writing, delivering} (`orchestrator.py:1042–1046`).** So the lease is not the only gate, but it is also not a bypass of the single speaker.

---

## 4. Merge / governor / background / redundant plan (Part B)

**GOVERNOR (collapse into one decision authority).** Keep `ConversationKernel` + `RootAgent` as the sole decider. The two orchestrator entry classes (`AIChatOrchestrator`, `AIAutonomousOrchestrator`) are already thin ingress wrappers around the kernel — keep them as *adapters* but treat the kernel as the one DECIDE step. Fold these decision-shaping modules into the governor so they stop being parallel mini-deciders:
- `banter_arbiter`, `utterance_selector`, `utterance_evaluator`, `expression_competition_workspace_v103`, `expression_commitment_transition_v102`, `nervous_system_v103_final` (gating), `horizon_arbiter` → these should all become **pure scoring/gating functions the RootAgent calls**, not standalone objects that transform a Decision after the fact.

**SPEAKER (exactly one).** `RuntimeConversationDeliveryAdapter.deliver` → `_send_decision_to_body` is already the single speaker. Action: make `_emit_body_only` route its body-only Decision through the governor/delivery path too (or a dedicated non-speech body channel owned by the speaker), so there is literally one function that touches the body transport.

**IDEA-SOURCES (background, propose-only — keep, but behind one bus).** Consolidate the many producers into a single typed **proposal bus** feeding the governor. Current producers that should all emit the *same* candidate type through *one* ingress: `mental_material_runtime`, `random_chat_seed(_service)`, `expression_urge_runtime`, `subject_initiative_runtime`, `subject_proposals`, `behavior_proposals`, `subconscious_loop`, `mind_loop`, `private_mind_loop`, `private_life_daemon`, `conversation_lane` (routing hint). They already converge on `ExecutiveAffordance` + `SocialSpeechCandidate`; the duplication is in the *lifecycle/selection* glue around them (`proposal_lifecycle`, `expression_urge_runtime`, `executive_cortex`, `expression_competition_workspace_v103`).

**MEMORY/STATE (persistence/projection — keep).** `continuation.py`, `session_turn_ledger`, `public_turn_ledger`, `final_speech_authority`, `semantic_authority_v95`, `intention_authority`, private-mind/private-life digests. These are fine as-is.

**REDUNDANT / HIGH MERGE PRIORITY (duplicate role, retire or absorb):**
- `expression_competition_workspace_v103` + `expression_commitment_transition_v102` + `utterance_selector` + `utterance_evaluator` + `banter_arbiter` + `horizon_arbiter` — six modules that all "pick/shape which candidate becomes the move." This is one job the RootAgent should own. **Strongest consolidation win.**
- `subject_proposals` vs `behavior_proposals` vs `subject_initiative_runtime` — three overlapping proposal producers around Subject Core; collapse to one.
- `mind_loop` vs `subconscious_loop` vs `private_mind_loop` — three "thinking" loops. They have distinct cadences but overlapping outputs (thought objects / judgments). Candidates for a single background cognition tick with pluggable workers.

(Nothing here is confirmed *dead* — every lane has at least one reader. "Redundant" above means *duplicate role*, which is the user's actual complaint, not *unreferenced*.)

---

## 5. Existing agent-loop scaffold status (Part C)

**There is no `src/runtime/agent_loop/` directory** (confirmed: file search returns nothing; `src/runtime/cognition/` contains only `normalization.py` and `turn_anchor.py`). So there is **no greenfield decide-loop scaffold to build onto.**

**However, the agent loop already exists under different names and is substantially complete:**
- Single *speech* loop: `autonomous_loop_runtime.run_loop` (one thread drives the DECIDE/SPEAK path). Many other background threads exist for cognition/state, but none commit speech.
- Single DECIDE: `ConversationKernel.handle_event` + `RootAgent.decide` returning zero-or-one `NextConversationMove`.
- Generation-based preemption + single-writer delivery already implemented (`kernel.py`: `generation`, `active_run_id`, `active_delivery_id`, `mark_delivery_started`, `settle_delivery`, idempotent `_event_results`).
- Single SPEAKER: `delivery_adapter.deliver` → `_send_decision_to_body`.

**Implication: this is a CONSOLIDATE-onto-existing effort, not a build-new effort.** The `ConversationKernel`/`RootAgent` pair is already the Kiro-style governor; the task is to route every idea-source through it and delete the parallel selection glue, not to introduce a new loop. Introducing a brand-new `agent_loop/` scaffold would create a *second* governor and make the sprawl worse.

---

## 6. Target mapping + chokepoints (Part D)

Target shape: **many cheap idea-sources → one DECIDE (RootAgent via kernel) → one SPEAKER (delivery adapter / `_send_decision_to_body`).**

| Current lane | Target home |
|---|---|
| `autonomous_loop_runtime.run_loop` | **The loop driver** (keep; it already ticks the single DECIDE). |
| `ConversationKernel` + `RootAgent` | **The one GOVERNOR / DECIDE.** |
| `AIChatOrchestrator`, `AIAutonomousOrchestrator`, `incoming_dispatcher`, `chat_cycle` | Ingress adapters into the governor (keep thin). |
| `delivery_adapter` + `_send_decision_to_body` + `stage_dispatcher`/`stage_ownership`/`public_surface_commit`/`public_turn_runtime` | **The one SPEAKER** and its support. |
| `mental_material_runtime`, `random_chat_seed*`, `expression_urge_runtime`, `subject_initiative_runtime`, `subject_proposals`, `behavior_proposals`, `subconscious_loop`, `mind_loop`, `private_mind_*`, `private_life_daemon` | **IDEA-SOURCES** behind one proposal bus. |
| `banter_arbiter`, `utterance_selector`, `utterance_evaluator`, `expression_competition_workspace_v103`, `expression_commitment_transition_v102`, `horizon_arbiter`, `nervous_system_v103_final` | **Absorb into RootAgent's decide step** as scoring/gating functions. |
| `continuation`, `*_ledger`, `final_speech_authority`, `semantic_authority_v95`, `intention_authority`, digests | **MEMORY/STATE** (keep). |

**Minimal set of chokepoints where "commit to speech" must be funneled (make these the only mic doors):**
1. `conversation/delivery_adapter.py` `RuntimeConversationDeliveryAdapter.deliver` — already the single high-level commit. Keep it the only caller of the next item for *linguistic* output.
2. `public_output_runtime.py` `_send_decision_to_body` — the single UDP/TTS dispatch. **Add an invariant/assert that `channel in {chat, autonomous}` speech may only arrive from the delivery adapter; body-only motion is the only other allowed caller.** Today `_emit_body_only` is the lone second caller (motion only) — fold or formally allowlist it.
3. The barge-in cancel path: unify `chat_cycle._enter_chat_cycle`'s unconditional `_supersede_tts_for_new_user_turn` with `incoming_dispatcher._handle_chat`'s backchannel preservation so TTS is cancelled in exactly one place, *after* interrupt classification. This removes the race, not just a symptom.

**Recommended fix order (small, verifiable, no re-architecture):**
1. **P0 contract fix** — reconcile `SocialSpeechCandidate` fields with `mental_material_runtime.project()`. Either add `seed_event_kind` / `seed_epistemic_mode` / `seed_open_loop` to the dataclass, or stop passing them in `common`. Verify with the existing failing test in `src/tests/test_turn_floor_and_duplicate_reply_regressions.py`.
2. **P0 barge-in ordering** — move the TTS cancel to a single point gated on interrupt classification; add a regression test driving `chat_start` then a `"ừ"` backchannel in event order.
3. **P1 single-speaker invariant** — allowlist callers of `_send_decision_to_body`; route `_emit_body_only` through the sanctioned path.
4. **P1 consolidation** — collapse the six selection/arbitration modules into RootAgent scoring; put all idea-sources behind one proposal bus.

---

## 7. Open questions / not verified

- **RootAgent decide internals** (`conversation/agent.py`) were inferred from the kernel's `self.agent.decide(...)` contract, not read line-by-line. Whether RootAgent *already* internally consults the arbiter/selector modules (making their consolidation trivial) vs. ignores them (making it behavioral) is unverified.
- **`executive_cortex.py`** is clearly the affordance selection hub (it references `source in {mental_material, expression_urge, random_chat_seed}`), but I did not fully trace how its selected affordance becomes a `_pending_conversation_capability_events` entry vs. autonomous-signal metadata. The exact fan-in from idea-sources → one signal needs a closer read before writing the proposal-bus design.
- **Thread model**: a `Thread(`/`asyncio.create_task` grep across `src/runtime` confirms **~15+ concurrent background threads** (e.g. `state_reducer.py:86`, `mental_process_runtime.py:44`, `random_chat_seed_service.py:464`, `private_mind_loop.py:625`, `semantic_environment_worker.py:144`, `activation_nervous_system_v98.py:746`, `motivational_focus_v99.py:651`, `neuro_continuation.py:282`, `mind_loop.py:367`). The "single loop" claim is therefore scoped to the **speech/DECIDE path only** — `private_mind_daemon`/`private_life_daemon` themselves are `.tick()`-driven, but `private_mind_loop` spawns its own worker threads for background model calls. These threads mutate shared state (concern store, surface queues, digests, activation bus) concurrently, which is a plausible secondary source of the "regenerated/overwritten generation" symptom and should be audited for lock discipline during consolidation. None reach the mic.
- **The pytest run** to re-confirm the seed `TypeError` live was attempted but the PowerShell session mangled the command line and returned no output; the break is confirmed by static reading (the dataclass has no such fields; `**common` passes them) and by the named failing test's existence. A clean `python -m pytest src/tests/test_turn_floor_and_duplicate_reply_regressions.py` in a working shell is the final confirmation.
- **`conversation_lane` vs `cognitive_lane` (model_router)** share the word "lane" but are different concepts (turn routing vs. inference admission). Confirmed distinct; flagged to avoid conflation during consolidation.

---

*Content from source files was summarized/paraphrased for this report; file:line citations point to the authoritative code.*
