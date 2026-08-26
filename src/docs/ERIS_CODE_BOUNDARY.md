# Eris Desktop / Eris Code boundary

Eris Desktop and Eris Code are separate products and separate runtimes.

## Eris Desktop owns

- identity / companion behavior
- long-term memory
- desktop / environment observation
- personal context

## Eris Code owns

- VS Code UI and editor observation
- GitPilot process/session lifecycle
- coding tasks, plans, patches, tests, reviews and approvals
- coding model/provider configuration through GitPilot

## Hard rules

- Eris Code never launches Eris Desktop.
- Eris Desktop does not own GitPilot task state.
- The old Eris IDE WebSocket bridge is disabled by default (`ERIS_AGENT_WS_ENABLED=0`).
- Optional communication is read-only observation through `Eris Link v1` and is disabled by default.
- Enable the Desktop observer endpoint only when wanted: `ERIS_CODE_OBSERVER_LINK_ENABLED=1` (default port 8767).
- The observer endpoint accepts GET only; it cannot edit files, approve tools, select models or control GitPilot.
