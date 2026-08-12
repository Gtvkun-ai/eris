# ERIS Social Startup Fix — 2026-08-10

## Scope

Fixes three startup/autonomous social-selection issues:

1. Startup greeting now updates relational homeostasis as a real public contact.
2. `contact_bid` and `user_probe` are coalesced before Subject/Neuro competition.
3. Duplicate homogeneous social lanes fast-commit without remote neuro deliberation.

## Behavior changes

### Startup greeting

After a successful startup public commit, `note_relational_public_act(...)` is called with:

- `outreach=True`
- `sharing=False`
- `expect_response=False`

This lowers affiliation pressure and raises interaction satiety, while preventing a soft startup greeting from becoming `outreach_waiting=True`. Therefore the ordinary 150-second outreach response window does not later count user silence as a failed/unanswered outreach.

### Contact/probe coalescing

`contact_bid` and `user_probe` are treated as two realizations of one immediate social-contact objective. When both exist:

- if `user_model_uncertainty >= 0.60`, keep `user_probe`;
- otherwise keep `contact_bid`;
- if no user-model uncertainty was supplied at the Subject boundary, preserve the already-materialized runtime affordance.

Coalescing occurs both before the self-turn Subject frame and again at the Subject proposal boundary as an invariant for alternate callers.

### Neuro fast-path

If the leading ambiguous channels are duplicate social speech lanes with the same speech act, and ambiguity is only routine low-margin / uncertainty / entropy, Neuro keeps the deterministic scored winner and returns:

`fast_gate:homogeneous_social_tie`

It still deliberates for commitment conflict, surprising low precision, different social intents, task/capability competition, and other materially distinct choices.

## Validation

- Direct regression set: 30 passed.
- Additional Subject/Neuro integration set: 36 passed.
- Changed production modules compile successfully with `py_compile`.
