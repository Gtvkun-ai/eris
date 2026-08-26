# Eris Coding Team Architecture

## Goal

Eris uses a native role-specialized coding team inspired by GitPilot's public topology model, while keeping **one Eris task owner, one official coding API lane, one checkpoint graph, and one tool/permission spine**.

This is intentionally **not** a vendored GitPilot/CrewAI sidecar. A second autonomous runtime would duplicate task state, context, permissions and retries—the same integration tax that made the earlier Cline path non-elegant.

## Engineering Team

```text
Eris Supervisor
      |
Official Coding API
      |
AgentHarness / LangGraph
      |
Explorer -> Planner -> Coder -> Reviewer
                         ^          |
                         |----------|  blocking findings, bounded rounds
```

### Explorer — reality first

Read-only. Establishes repository facts before planning:

- repository map, exact source and callers
- semantic retrieval when available
- current Git diff and recent Git history
- dependency manifests
- test-suite inventory
- IDE diagnostics/runtime evidence when relevant

Explorer hands Planner a compact evidence artifact instead of raw tool chatter.

### Planner — change contract

Read-only. Converts Explorer evidence into an ordered implementation contract:

- exact files/symbols
- intended diff shape
- verification/test surface
- risks and rollback points
- only genuine user decisions remain interrupts

### Coder — transactional implementation

The only specialist with source mutation privileges. It deep-reads touched code, applies the smallest coherent patch, runs targeted verification, corrects failures, and inspects the resulting diff before handoff.

### Reviewer — independent gate

Read-only except verification tests. Reviews correctness, regression risk, security, maintainability, performance and test coverage. Blocking findings hand the task back to Coder. Review loops are bounded by `ERIS_CODING_MAX_REVIEW_ROUNDS` (default 3).

## Mechanical boundaries

Role boundaries are enforced by disclosed tool schemas, not only prompts:

- Explorer/Planner cannot see mutation tools.
- Reviewer cannot patch source.
- Coder cannot hand off a mutation task without verified changed-file evidence.
- Plan and Inspect modes use read-only topologies.
- Each specialist receives a role-local default skill set.
- Role transitions carry compact handoff artifacts; raw prior-role chatter is excluded from the specialist model context.
- Per-task/per-role model selection uses request-local transport views and never mutates the shared coding client.

## Topologies

| Mode | Topology |
| --- | --- |
| Auto / Execute | Explorer -> Planner -> Coder -> Reviewer |
| Plan | Explorer -> Planner |
| Inspect | Explorer -> Reviewer |

The public GitPilot Feature Builder also includes PR-management stages. Eris deliberately stops at Reviewer: commit/push/PR is a separate user-visible source-control decision, not an implicit coding side effect.

## Ownership invariant

**Only the Eris official-API coding subbrain decides the coding task.** Repository context, semantic indexing, IDE RPC, tests and source-control inspection are sensors/tools. They never become a second autonomous owner.
