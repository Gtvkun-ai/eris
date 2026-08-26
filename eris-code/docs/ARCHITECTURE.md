# Architecture boundary

## Hard invariants

1. `Eris Code` compiles and runs with no Eris Desktop source tree present.
2. No code path invokes `run_eris.bat`, Eris discovery files, or Eris Desktop WebSocket services.
3. GitPilot owns coding task orchestration and provider/model calls.
4. VS Code owns editor observation and patch application UI boundaries.
5. Eris Desktop is an optional observation source only.
6. A missing Eris Desktop never degrades GitPilot availability.
7. A missing GitPilot backend is a visible coding-runtime error; Eris Code does not secretly replace it with a second agent implementation.
8. Multi-agent mode does not silently downgrade to GitPilot folder/direct-LLM unless the user explicitly enables that fallback.

## Why this is separate from Eris Desktop

The previous monolithic architecture mixed avatar/runtime lifecycle, memory, IDE transport, coding model selection and task execution. That made every subsystem able to accidentally become an owner. Eris Code now has one external coding owner (GitPilot), while Eris Desktop can evolve independently as a personal observer/companion.
