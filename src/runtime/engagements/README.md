# ERIS Engagement Runtime

`runtime.engagements` keeps long-running interaction commitments alive across
chat and autonomous turns. It deliberately separates five concerns:

- `EngagementRegistry`: lifecycle, focus, bounded event log and persistence.
- `EngagementAdapter`: domain-specific state reduction and planner projection.
- `InteractionContract`: role, initiative, style and action constraints.
- `EngagementInteractionPolicy`: event/cadence decisions without writing text.
- `AttentionManager`: chooses one engagement when several are active.
- `EvidenceRouter`: routes app/workspace/resource evidence to the bound engagement instead of broadcasting it.

## Adding a new activity

1. Implement `EngagementAdapter` in `adapters.py` or another module.
2. Register it with `AdapterRegistry.register()`.
3. Produce an `EngagementProposal` from a detector or an explicit caller.
4. Bind stable evidence identifiers with `bind_engagement()` or the `binding=` argument.
5. Feed domain changes through `emit_domain_event()` or `emit_evidence_event()`.

The coordinator and planner must remain domain-agnostic. Do not add
`if engagement.kind == ...` branches there. Domain state belongs in adapters;
activity/screen telemetry remains evidence and must not be promoted into facts
without an adapter event.

## Runtime flow

```text
user/chat + activity evidence
          -> EngagementRuntime
          -> event-sourced registry
          -> adapter projection
          -> interaction policy
          -> attention arbitration
          -> chat/autonomous planner context
```

The generic companion timer yields to an active engagement's policy. This is
important for monitoring and event-driven sessions: a timer is not permission
to abandon the task and start unrelated banter.

## Evidence binding

Use stable identifiers whenever a task can run beside another task:

```python
runtime.observe_user_message(
    "Theo dõi deployment này.",
    binding={"resource_id": "deploy:prod"},
)

runtime.emit_evidence_event(
    "deployment.completed",
    binding={"resource_id": "deploy:prod"},
    payload={"result": "success"},
)
```

Mechanical activity without a matching binding may seed the foreground engagement,
but it is never broadcast to background monitors.

## Durable event consumers

Subsystems that project or export engagement events should use the shared pump:

```python
consumer = runtime.create_event_consumer(
    "analytics_projection",
    lambda batch: project(batch.events),
)
result = consumer.poll_once()
```

The registry owns the durable cursor, lease, retry schedule and dead-letter state.
A consumer must acknowledge only after its handler succeeds. Retention gaps,
hash-chain failures and projection replay mismatches are surfaced through
registry diagnostics/readiness rather than being disguised as an empty batch.

## Replay and repair

`audit_event_stream()` validates the global event chain. `replay_engagement()`
rebuilds adapter state from retained history. `repair_engagement_projection()`
may update the stored projection only when the replay is complete from the
engagement's creation event; it refuses to invent missing history after
retention has truncated the stream.
