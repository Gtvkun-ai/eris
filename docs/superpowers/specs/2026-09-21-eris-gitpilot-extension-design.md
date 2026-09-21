# Eris GitPilot Extension Integration

## Intent

Turn the Eris VS Code extension into a branded distribution of the upstream GitPilot VS Code extension. The visible coding workflow and execution brain should come from GitPilot itself, while Eris remains an optional identity/context layer that never sits in the coding critical path.

Success means:

- The Eris extension shows GitPilot's native Home/Chat/Settings experience instead of the current Eris-specific webview.
- Chat, sessions, planning, approvals, tool execution, diffs, apply/revert, provider settings, and agent controls use GitPilot's native implementation.
- The extension launches or attaches to the local GitPilot server at `http://127.0.0.1:8000` using GitPilot's own lifecycle and API contracts.
- The Eris package can be built and installed as one VSIX without requiring the separate upstream GitPilot extension.
- Existing Eris Desktop/runtime integration is optional and cannot block GitPilot coding.
- The implementation remains traceable to the vendored upstream source at `services/gitpilot/extensions/vscode`.

## Current State

`src/vscode-extension` is a custom Eris Code extension. It owns a bespoke webview, a second client/session model, a runtime manager, and an SSE adapter over GitPilot. This duplicates upstream behavior and has already drifted from the installed extension version.

The repository also vendors the upstream GitPilot backend and its native extension under `services/gitpilot`. That extension already contains the intended VS Code UI, REST/SSE/WebSocket integration, approval flow, patch workflow, settings, commands, and tests.

## Chosen Architecture

Use the upstream extension as the source of truth for coding behavior, with a thin Eris distribution layer:

```text
VS Code
  |
  v
Eris · GitPilot extension (upstream GitPilot UI + client)
  |
  v
GitPilot server at 127.0.0.1:8000
  |
  v
GitPilot multi-agent runtime and configured LLM provider
```

The implementation will copy/synchronize the upstream extension source and resources into `src/vscode-extension`, then apply only deliberate distribution changes:

- package identity, display name, description, publisher, and Eris icon/branding;
- a stable Eris packaging/build entrypoint;
- optional Eris context hook that is best-effort and does not change GitPilot task execution;
- local backend discovery and launch configuration suitable for the Eris monorepo.

The old Eris webview and duplicate GitPilot adapter are removed from the active build. They must not remain as a second presentation or execution path inside the VSIX.

## User-Facing Contract

The extension keeps an Eris-branded Activity Bar entry but exposes GitPilot's native commands and settings. Command identifiers remain `gitpilot.*` so upstream command wiring and future upstream syncs do not need an Eris-only translation layer.

The key settings are GitPilot's native settings:

- `gitpilot.serverUrl`, default `http://127.0.0.1:8000`;
- `gitpilot.serverCommand`, default `gitpilot`;
- `gitpilot.autoConnect`, enabled by default;
- `gitpilot.permissionMode`, default `normal`;
- provider, model, topology, timeout, and security settings supplied by upstream.

Eris-specific settings are limited to optional observation/context behavior. They must not replace GitPilot's workspace context, permissions, approvals, or patch application.

## Runtime and Data Flow

1. The extension activates on GitPilot view/startup and constructs the upstream client and state store.
2. The runtime manager probes `/api/status`; if unavailable and auto-connect is enabled, it starts `gitpilot serve` using the configured command.
3. The native GitPilot UI creates or resumes a session and sends chat/task requests through the upstream REST and streaming contracts.
4. GitPilot emits plan, status, tool, approval, diagnostic, diff, and completion events. The upstream UI renders them and owns user decisions.
5. Apply/revert and checkpoint actions use GitPilot's native APIs and VS Code filesystem/diff surfaces.
6. Any Eris observation is published best-effort after or alongside the coding event. Observation failure is logged and ignored by the coding flow.

## Packaging and Migration

- `src/vscode-extension` remains the package consumed by Eris build/release tooling.
- Its package version advances from the stale `0.22.0` line to a new Eris distribution version based on the integrated GitPilot release.
- The build emits the upstream-style `out/` artifact expected by the copied package manifest, then the existing Eris VSIX packer is updated to include all required upstream resources and compiled assets.
- A dedicated build/install script will compile, package, and force-install the generated VSIX through the available VS Code CLI when present.
- The old `gtvk.eris-code` installation is replaced by the new VSIX; no separate `ruslanmv.gitpilot-vscode` installation is required for the Eris distribution.
- The backend setup/run scripts remain under `services/gitpilot`, with the extension defaulting to the global `gitpilot` command and documenting the monorepo setup fallback.

## Testing and Verification

Before implementation, the integration must have tests that prove:

- the branded package manifest exposes the upstream GitPilot commands/views/settings;
- the compiled artifact contains the upstream entrypoint and required UI resources;
- backend startup/probe behavior works against a local GitPilot server;
- an SSE task event sequence reaches the native state/UI boundary;
- approval, cancel, diff/apply/revert, and server-unavailable paths retain upstream behavior;
- Eris observation failure does not fail a GitPilot task.

Verification will run the upstream VS Code extension test suite, TypeScript typecheck/compile, the Eris package build, and a local `/api/status` smoke check. Existing unrelated memory changes will remain untouched.

## Non-Goals

- Rewriting GitPilot's multi-agent backend or provider system.
- Keeping the old Eris chat UI as a fallback inside the same VSIX.
- Making Eris Desktop a prerequisite for coding.
- Adding new agent behavior unrelated to replacing the extension surface.
- Silently installing secrets, GitHub tokens, or provider credentials.
