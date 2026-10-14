# Eris "first user message ignored" — read-only investigation

Scope: trace the inbound turn-intake path from UDP transport → incoming_dispatcher →
chat_cycle → orchestrator → `ConversationKernel.handle_event`, and determine the exact
fate of a user message that arrives while Eris is mid-delivery or running the post-observer.
All findings come from static reading of `src/runtime/`. No code was modified.

---

## 1. Verdict (one paragraph)

The first user message is almost certainly **DELAYED, not dropped or overwritten** — delayed
until the single runtime thread next calls `transport.poll_json()`, which during the opening
delivery + ~20s post-observer window happens only at a few cooperative poll points. The
transport is a **single, non-blocking UDP socket drained one datagram per `poll_json()` call,
with no background reader thread** (`src/transport/udp.py:547 poll_json` does one
`recvfrom(4096)`; `RuntimeTransportBoundary` wraps only `send_json`, never receive). So an
inbound `chat` datagram sits in the OS socket buffer until the loop polls it. There is **no
single "pending user input" slot** in Python that a second message overwrites, and
`user_turn` is **exempt** from the kernel phase-drop gate that discards autonomous signals.
The most likely root cause of the *perceived* "ignored first message, answered second" is
**intake latency plus one real swallow path**: `IncomingMessageDispatcher._handle_chat`
(`src/runtime/incoming_dispatcher.py:131-146`) classifies the text and, if it is a
backchannel while the speech floor is busy, calls `_end_chat_cycle()` and `return`s **without
ever producing a `user_turn`** — the message is intentionally swallowed. If the first message
normalized to a backchannel token (e.g. `ok`, `ừ`, `à`) while the opening audio floor was
still busy, it was deliberately preserved-as-silence; the second, non-backchannel message
then became `user_turn rev=2`. Secondary contributor: ordering — stage/audio inbound events
and the second `chat` share the same single-reader socket, so the first `chat` can wait behind
other datagrams and only drain after the busy window.

Single most load-bearing line for the "swallow" case:
`src/runtime/incoming_dispatcher.py:135-146` (backchannel + `speech_floor_busy` → `_end_chat_cycle()` + `return`).

Single most load-bearing fact for the "delay" case:
`src/transport/udp.py:547` — one non-blocking `recvfrom` per poll, no background drain thread.

---

## 2. Inbound turn-intake path (ordered stages, and behavior when busy)

The runtime is **single-threaded cooperative**. One thread runs `run_loop`
(`autonomous_loop_runtime.py:run_loop`) → `run_iteration` → the orchestrator, and it is the
**only** reader of the receive socket. Inbound messages are read exclusively at these
`poll_json()` call sites:

- `autonomous_loop_runtime.py:120` inside `_sleep_interruptible` (polls every ≤0.2s while sleeping; returns early if `chat_mode`).
- `autonomous_loop_runtime.py:161` `_process_pending_user_input` (one poll per call).
- `chat_cycle.py:306` `_poll_ready_chat_events` (drains during an in-flight chat cycle's burst merge).

Stages:

1. **UDP receive** — `src/transport/udp.py:547 poll_json`: `recvfrom(4096)`, returns the parsed
   dict or `None` on `BlockingIOError`. **One datagram per call.** Non-blocking. No queue object
   in Python; the OS socket buffer is the only queue. Messages are not lost here unless the OS
   buffer overflows, but they are only *visible* when the loop chooses to poll.

2. **Dispatch** — `incoming_dispatcher.py:43 dispatch`: table-driven. `chat_start` →
   `_enter_chat_cycle()`; `chat` → `_handle_chat`; stage types (`audio_playback_started/done`,
   `stage_ack`, …) → `_handle_stage_inbound_event`. `maintenance_busy` short-circuits chat while
   maintenance is in progress (`_maintenance_blocks`, line 108). Unknown types are ignored
   (counted, debug-logged), not errored.

3. **Chat intake** — `incoming_dispatcher.py:131 _handle_chat`:
   - opens chat mode if not already (`_enter_chat_cycle`);
   - `classify_interrupt(user_text, final=True)` (`conversation/interrupts.py:22`);
   - **BUSY-SPECIFIC SWALLOW**: if `kind == BACKCHANNEL` **and** `interaction_clock.speech_floor_busy`,
     it logs `preserved audio on backchannel`, calls `_end_chat_cycle()` and `return`s. **No
     `user_turn` is created for this message.** (lines 135-146)
   - otherwise applies barge-in (`_preempt_for_classified_user_turn`) and calls
     `_run_chat_cycle(user_text, …)`.

4. **Chat cycle** — `chat_cycle.py:95 _run_chat_cycle`:
   - If `_chat_processing` is already True (a prior cycle still running on this one thread),
     the new text is appended to `_chat_burst_queue` via `_queue_chat_burst_event` and the call
     returns (lines 128-131). This queue is **append-only** (`chat_cycle.py:290-298`) — it does
     **not** overwrite earlier entries.
   - Else sets `_chat_processing = True`, then `_merge_rapid_chat_burst` (lines 265-283) collects
     the first text + any queued burst events + any further `chat` datagrams it actively polls
     within a 1.2s quiet window, and joins them with newlines. Non-chat datagrams polled here are
     routed through `_handle_incoming` (line 314), not dropped.

5. **Orchestrator ingress** — `ai_orchestrated/orchestrator.py:AIChatOrchestrator.run` →
   `_run_v12`: opens an inference cancel-scope for the user turn, preempts background lanes
   (`_preempt_background_for_chat`), records the user turn into the session ledger, then calls
   `ConversationKernel.handle_event` with a `user_turn` event.

6. **Kernel** — `conversation/kernel.py:122 handle_event` → `_handle_event_once` (line 163):
   for `kind == "user_turn"` it **unconditionally** cancels continuations, discards stale
   deliveries, **increments generation** and claims a new `active_run_id` with
   `phase=THINKING`. There is **no busy-phase early-return for user_turn**.

### What each state does to a *newly arrived* user message

- **(a) Mid-TTS delivery (opening audio playing):** the runtime thread is not blocked on audio
  (audio plays on the frontend; `audio_playback_*` come back as inbound stage events). The new
  `chat` datagram waits in the socket buffer until the next `poll_json()`. When finally polled:
  if it is a non-backchannel, `_handle_chat` runs barge-in and starts a real `user_turn`
  (kernel bumps generation, superseding the opening). If it is a backchannel while
  `speech_floor_busy`, it is **swallowed** (stage 3 above). → DELAYED, or SWALLOWED-if-backchannel.
- **(b) Running post_observer (~20s):** the observer runs as a background inference ticket; the
  main loop is typically in `_sleep_interruptible` and *does* poll every ≤0.2s. A message here is
  normally picked up quickly — **unless** the thread is inside the synchronous part of a prior
  chat cycle or a signal handler that doesn't poll. → mostly DELAYED (short), swallowed if backchannel.
- **(c) Already composing a reply (`_chat_processing == True`):** appended to
  `_chat_burst_queue` and merged into the *current* cycle's text, or processed after. Earlier
  entries are preserved (append-only list). → QUEUED/COALESCED-into-current, not lost.

---

## 3. Exact drop / coalesce / queue decision points

| # | Location | Behavior | Quote (<20 words) |
|---|----------|----------|-------------------|
| D1 | `incoming_dispatcher.py:135-146 _handle_chat` | **SWALLOW** backchannel while speech busy; ends chat, no user_turn | `interrupt.kind == InterruptKind.BACKCHANNEL and speech_busy` → `finish()` then `return` |
| D2 | `conversation/interrupts.py:24-25` | Classifies bare tokens as backchannel | `if normalized in _BACKCHANNELS: return InterruptDecision(BACKCHANNEL, False, False, True)` |
| Q1 | `chat_cycle.py:128-131 _run_chat_cycle` | **QUEUE** if a cycle already running | `if self._chat_processing: self._queue_chat_burst_event(user_text, cycle_start); return` |
| Q2 | `chat_cycle.py:290-298 _queue_chat_burst_event` | Append-only, no overwrite | `with lock: self._chat_burst_queue.append(item)` |
| C1 | `chat_cycle.py:265-283 _merge_rapid_chat_burst` | **COALESCE** burst into one turn | `return "\n".join(text for _, text in collected if text)` |
| K1 | `conversation/kernel.py:171-184` | user_turn always claims run (no busy drop) | `if event.kind == "user_turn":` … `generation=prior.generation + 1` |
| K2 | `conversation/kernel.py:186-199` | **DROP** non-user signals when busy | `if state.phase in busy_phases: return ConversationRunResult(..., status="busy")` |
| P1 | `transport/udp.py:547-556 poll_json` | One datagram per poll; OS buffer is the only queue | `data, _ = self._recv_sock.recvfrom(4096)` |

The backchannel set that triggers D1/D2 (`interrupts.py:10`):
`ừ, uh, uhm, ừm, à, ờ, đúng, đúng rồi, ok, oke, mhm, hm`.

Note on the log's answered text `erm ko co gi dau a`: that string is **not** in `_BACKCHANNELS`,
so it correctly became a `user_turn`. If the user's *first* message had been one of the tokens
above (or a bare "ok"/"à") sent while the opening audio floor was busy, D1 would have swallowed
it silently — matching "I said one line and Eris ignored it, that was a valid skip."

---

## 4. Is `user_turn` exempt from the autonomous phase-drop gate?

**Yes, fully exempt.** `kernel.py:_handle_event_once`:

- `if event.kind == "user_turn":` (line 171) takes a branch that **unconditionally** increments
  generation, cancels continuations, discards stale deliveries, and claims `THINKING`. It never
  checks `state.phase`.
- The busy-phase drop lives only in the `else` branch (non-user events), lines 186-193:
  `busy_phases = {THINKING, WORKING, WRITING, DELIVERING}` … `if state.phase in busy_phases:
  return ConversationRunResult(event=event, decision=None, status="busy")`.

So a user message sent during the 24s opening + 20s observer window is **not** dropped by the
kernel. This refutes investigation hypothesis (e): the kernel is not the drop site. Any loss or
delay is **upstream** of the kernel (dispatcher swallow D1, or socket-poll latency P1).

---

## 5. Role of `enter_chat_mode` / `[LLM CANCEL] epoch` and race analysis

- `_enter_chat_cycle` (`chat_cycle.py:30-41`) only flips `chat_mode` and resets per-turn
  counters; it is **idempotent** (`if self.chat_mode: return`) and **does not cancel anything**.
  The P0 comment is explicit: cancelling TTS here would cut Eris for a mere "ừ".
- The actual cancellation (`[LLM CANCEL] epoch=1 reason=enter_chat_mode`) happens in
  `_preempt_for_classified_user_turn` (`chat_cycle.py:43-64`), called from `_handle_chat`
  **after** classification, via `llm_service.cancel_pending_requests(reason="enter_chat_mode")`
  and `lifecycle.interrupt(reason="new_user_input")`.
- **Race assessment:** because intake is single-threaded, the cancel and the re-ingest cannot
  interleave across two messages on different threads. The classified message that triggers the
  cancel is the **same** message that then calls `_run_chat_cycle` → kernel `user_turn`. There is
  no path where the cancel fires for message A while only message B's text survives — each
  `_handle_chat` call carries its own `user_text`. The "first text discarded, newest survives"
  outcome is therefore **not** a cancel/re-ingest race; it is either D1 (backchannel swallow) or
  P1 (the first datagram simply hadn't been polled yet when the user gave up and sent the second).

---

## 6. The 2.5s turn-collision guard — can it drop a just-arrived user message?

**No.** The guard (`chat_cycle.py:81-92 _end_chat_cycle` → `public_output_runtime.py:1238
_note_autonomous_turn_collision` → `public_turn_runtime.py:70 note_turn_collision`) only sets
`owner.autonomous_turn_collision_until`. That value is consumed **only** by
`subject_initiative_runtime.py:223-224` to set `public_turn_busy`, which **defers autonomous
public expression**. The comments are explicit (`public_turn_runtime.py:72`, `policy_settings.py:68`):
it is a mechanical anti-overlap window for Eris's **own** turns, "never means the user wants Eris
quiet." The user intake path (`_handle_chat` → `_run_chat_cycle` → kernel) never reads
`autonomous_turn_collision_until`. So the collision guard cannot drop or delay an inbound user
message. Hypothesis (4) is refuted.

---

## 7. Recommended fix direction

Priority is **queue-and-process**, not preempt or widen-guard, and the fix must preserve the
single-speaker / generation guards in the kernel (K1/K2) and the backchannel protection.

1. **Make the socket drain promptly during busy windows (addresses P1, the delay).**
   Add a dedicated, bounded inbound queue drained by a short background reader, OR insert
   `poll_json()`/`_process_pending_user_input()` calls at more points during delivery and
   observer waits. Concretely: in `AIChatOrchestrator.run`/`_run_v12` and in the opening
   delivery path, poll for inbound `chat` before and after the long inference, so a user message
   that landed during the 24s/20s window is seen within ~0.2s rather than only on the next
   autonomous sleep. Keep it cooperative to avoid re-entrancy with `_chat_processing`.

2. **Reconsider the backchannel-while-busy swallow (addresses D1, the real "ignored").**
   `incoming_dispatcher.py:135-146` currently drops a backchannel entirely when the speech floor
   is busy. If the user perceives that as "ignored," options: (a) still suppress barge-in/audio
   cancel, but **record the backchannel as a lightweight observed user turn** so the next
   autonomous/observer turn knows the user spoke; or (b) only swallow when audio is *actively
   playing* (`clock.audio_active`) and not merely `audio_pending`. Change is localized to the
   `if interrupt.kind == InterruptKind.BACKCHANNEL and speech_busy:` block. **Preserve** the
   original intent: a bare "ừ" must not cut Eris mid-sentence or spawn a duplicate reply.

3. **Do NOT widen the 2.5s collision guard** — it is unrelated to intake (§6) and widening it
   would only further suppress Eris's own turns.

Functions/kwargs that would change: `IncomingMessageDispatcher._handle_chat` (backchannel
branch), a new poll point in `AIChatOrchestrator._run_v12` / the opening-delivery wait, and
possibly `_process_pending_user_input` reuse. The kernel needs **no** change — `user_turn` is
already preemptive and exempt from the phase gate.

---

## 8. Open questions / not verifiable from static reading

- **Which exact text was the user's first message.** The log shows only the *answered*
  `rev=2` text (`erm ko co gi dau a`). Whether the first (unanswered) message was a backchannel
  token (→ D1 swallow) or a normal sentence (→ P1 delay) cannot be determined without the raw
  inbound UDP log for ~14:10:17. This distinguishes DROPPED-by-D1 from merely DELAYED.
- **Whether the first datagram was ever delivered to the OS socket buffer.** UDP can drop packets
  under load/MTU; the frontend send side (`src/transport/udp.py` send path, panel compaction) and
  OS buffer sizing were not audited. A lost datagram would look identical to a swallow from the
  runtime's perspective.
- **Exact thread position at 14:10:17.** Whether the loop was in `_sleep_interruptible` (polling
  every 0.2s) vs inside a synchronous signal/cycle (not polling) at that instant determines the
  delay magnitude. The log timestamps suggest the observer was running (background), which would
  normally allow polling — leaning the evidence toward D1 (backchannel swallow) over pure P1
  latency, but this is inference, not proof.
- **`speech_floor_busy` truth at intake time.** `audio_playback_done` for the opening fired at
  ~14:10:01; if the clock's `audio_active`/`audio_pending` had already cleared by 14:10:17, the
  D1 branch would NOT trigger and a backchannel would instead start a real (possibly no_reply)
  turn. Confirming requires the interaction-clock state at that timestamp.

---

### Appendix — key citations

- `src/transport/udp.py:547` `poll_json` — one non-blocking `recvfrom` per call.
- `src/runtime/transport_boundary.py` — wraps `send_json` only; no receive thread.
- `src/runtime/incoming_dispatcher.py:131-146` `_handle_chat` — backchannel-while-busy swallow.
- `src/runtime/conversation/interrupts.py:10,22-28` — `_BACKCHANNELS`, `classify_interrupt`.
- `src/runtime/chat_cycle.py:30-64` `_enter_chat_cycle` / `_preempt_for_classified_user_turn`.
- `src/runtime/chat_cycle.py:95-131,265-298` `_run_chat_cycle`, burst queue (append-only).
- `src/runtime/chat_cycle.py:66-92` `_end_chat_cycle` — collision guard emit.
- `src/runtime/conversation/kernel.py:163-199` — user_turn exempt; non-user busy-drop.
- `src/runtime/autonomous_loop_runtime.py:103-165` — the only `poll_json` call sites in the loop.
- `src/runtime/ai_orchestrated/orchestrator.py:974-1006,1141-1170` — signal/iteration poll + phase checks.
- `src/runtime/public_turn_runtime.py:70-97`, `subject_initiative_runtime.py:220-226` — collision guard only defers autonomous.

Content was reconstructed from static code reading; runtime-state claims (e.g. clock values at
14:10:17) are inferences flagged as such in §8.
