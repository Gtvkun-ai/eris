# Structure

```
eris/
  src/
    runtime/              # Python Brain (logic chinh)
      coordinator.py      # Entry point, dispatch tasks
      agent_harness/      # Cline bridge, spec, steering, graph_builder
        cline_bridge_client.py  # HTTP client -> cline-bridge sidecar
        steering_loader.py      # Doc .eris/steering/*.md
        spec_manager.py         # Spec-driven development
        graph_builder.py        # Fallback: LangGraph agent loop
      memory_core/        # Long-term memory
    vscode-extension/     # TypeScript extension (UI shell)
      src/
        chatPanel.ts      # Chat UI webview
        erisClient.ts     # WebSocket client -> Python
  cline-bridge/           # Node.js sidecar (Cline SDK)
    src/
      bridge.ts           # HTTP server (nhận task tu Python)
      runtime.ts          # Chay Cline session
      context-provider.ts # Inject Eris context vao Cline
  .eris/
    steering/             # Project-level rules cho Cline
    specs/                # Spec files (plan/exec workflow)
```

## Luong du lieu chinh

```
User chat
  -> erisClient.ts (WS)
  -> coordinator.py
  -> cline_bridge_client.py (HTTP)
  -> cline-bridge/bridge.ts
  -> runtime.ts (Cline session)
  -> WebAI proxy (localhost:8081)
  -> Gemini
```
