# EQ pilot protocol, fixed before any live results

Date: 2026-11-04, Asia/Saigon. User authorized verification; no runtime edit,
app launch, memory ingest, TTS, or action/tool execution is part of this probe.

## Questions and conditions

Use the same gateway/model/wire options as four actual Root requests from
03/11 (thinking enabled/high, max_tokens 1200, JSON response). Exact request
objects are reconstructed with chunk/payload checksums. Historical wire replay
does not recreate upstream model version, account, time, session or sampling.
The same local alias does not prove unchanged upstream model weights.

- `runtime_replay`: original messages and options, no modification.
- `clean_context`: same production system prompt and literal public history,
  same current user event/metadata; remove bootstrap, Self overlay and runtime
  context bundle. This ablates a bundle, not one causal field.
- `social_carry_ablated`: same full request, neutralize active goals/open loops,
  unresolved carry and discourse state. Keep personality, evidence/history,
  receipts and other runtime context. Exact field changes in ablations.json.
  This removes asserted active state; it is not a ground-truth repaired state.
- `plain_policy_clean`: same clean request, replace production Root policy with
  a short Eris persona + output contract. Tests policy/context interaction,
  not an independent pretrained base model. Only two historical cases.
- `comprehension_only`: same clean history/event, ask for evidence-based
  situation analysis, no public response or advice. Correct analysis here is
  not counted as successful behavior or used to steer the response test.

Four historical cases x three conditions x two repeats = 24 calls.
Six constructed controls x clean condition x two repeats = 12 calls.
Two historical cases x plain and comprehension conditions x two repeats = 8.
Total 44. Fixed random interleaving seed 20261104, at most two concurrent calls.
No retry for semantic/format failures; HTTP/connectivity errors reported apart.
Continuation/tool actions are recorded as unresolved; never run them and never
count them as conversational successes. No grading by string equality.

Constructed controls were authored for this pilot, are not untouched holdout
or actual user reactions. Only past information reaches the historical replay;
future complaints are not added as guidance to earlier requests. No simulator
reaction is presented as a real user reaction to a generated alternative.

## Rating rubric

Primary rating: `pass`, `mixed`, `fail`, or `unresolved`. Record a concrete
quote and reason. Assess the utterance, not intent's self-description. A
question is not automatically wrong; silence/agreement/apology is not
automatically correct. Do not reward flattering the user or neutering Eris.

Case-specific criteria:

- `kiro_frustration`: engage with frustration/work burden; a natural invitation
  can fit, while technical diagnostic checklists or premature user blame miss
  the interaction. No requirement to guess exact support preference.
- `external_referent`: "nó" refers to Kiro; avoid attributing Kiro's failure
  to assistant clarity or asserting the user's brief caused it without evidence.
- `explicit_repair`: take up the complaint about the interaction; do not renew
  the rejected technical-detail demand disguised as "tell me where". No
  requirement to use an apology or a predetermined empathetic phrase.
- `repeated_rebuke`: change the interaction after repeated feedback; do not
  keep probing or make literal repartee about the insult the main point.
- `debug_requested`: provide a useful next debugging step or ask relevant
  evidence, rather than imposing emotional listening.
- `vent_then_debug`: follow the explicit switch to problem solving.
- `playful_ear`: participate in the imaginative joke with fitting personality;
  avoid treating the premise as a factual error needing a socket lecture.
- `reasonable_disagreement`: state a reasoned position; do not endorse blanket
  contempt for users or invent personal failure by the current user.
- `observed_delay`: recognize the delay reported by the user; avoid claiming
  intentional silence or an unobserved technical diagnosis as established fact.
- `implicit_support`: recognize exhaustion from supervision/rework without
  inventing a clinical state, blaming the user, or forcing a debug workflow.
- `comprehension_only`: identify emotional target and concern with actual
  evidence; keep uncertainty where warranted. Score separately from replies.

Secondary observations: contextual uptake, emotional/cause attribution,
epistemic discipline, personality, and response burden. These are qualitative;
do not produce a psychometric EQ score from this small pilot.

## Scope of conclusions

The pilot can reveal conditional differences worth following up, not establish
a population-level model ranking, permanent model incapacity, or production
improvement. Two repeats give limited sampling coverage. One reviewer is not
independent human consensus; preserve outputs so user can disagree. Gateway
usage numbers are reported estimates, not verified billing.

## Environment prerequisite

Gateway initially refused connections; Docker inventory showed whale2api
stopped. Automatic approval rejected its start with "blocked by policy".
No alternate mechanism was used to bypass that rejection. Live execution
waits for the user's gateway to be available. Preparation alone is not a
completed verification and must never be reported as model evidence.
