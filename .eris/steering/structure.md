# Structure

```
eris/
  src/
    runtime/              # Python Brain (logic chinh)
      coordinator.py      # Entry point, dispatch tasks
      agent_harness/      # spec, steering, graph_builder
        steering_loader.py      # Doc .eris/steering/*.md
        spec_manager.py         # Spec-driven development
        graph_builder.py        # LangGraph agent loop
      memory_core/        # Long-term memory
    vscode-extension/     # TypeScript extension (UI shell)
      src/
        chatPanel.ts      # Chat UI webview
        erisClient.ts     # WebSocket client -> Python
  services/
    gitpilot/             # GitPilot backend clone
  .eris/
    steering/             # Project-level rules
    specs/                # Spec files (plan/exec workflow)
```

## Luong du lieu chinh

```
User chat
  -> erisClient.ts (WS)
  -> coordinator.py
  -> GitPilot backend (services/gitpilot, localhost:8000)
  -> official coding provider
```
