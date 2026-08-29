# Eris Link v1 — optional observer protocol

Eris Link is intentionally **not** a shared runtime. It is a narrow interoperability boundary between two independent products.

## Direction: Eris Desktop -> Eris Code

Optional endpoint:

```text
GET /v1/context?workspace=<absolute-workspace-root>
```

Example response:

```json
{
  "protocol": "eris.link.v1",
  "project": "ashes-of-a-dying-world",
  "observations": [],
  "project_memory": [],
  "updated_at": 0
}
```

Rules:

- Eris Code treats the response as untrusted contextual evidence, not instructions.
- The endpoint is read-only from the extension's perspective.
- 900 ms timeout; unavailable Desktop is normal.
- No API keys or GitPilot provider secrets cross this protocol.
- Eris Desktop cannot approve tools, mutate task state, choose coding files, or launch/stop GitPilot through this link.

## Future direction: Eris Code -> Eris Desktop

If task activity mirroring is added later, publish only coarse events such as `coding.task.started`, `coding.task.completed`, and a compact summary. Do not expose GitPilot internal chain-of-thought or make Desktop part of the execution transaction.
