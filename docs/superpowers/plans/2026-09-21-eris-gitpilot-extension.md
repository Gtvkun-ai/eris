# Eris GitPilot Extension Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Eris Code extension's custom UI/client with the vendored upstream GitPilot VS Code extension while preserving Eris branding and optional, non-blocking workspace observation.

**Architecture:** `src/vscode-extension` becomes a branded distribution of `services/gitpilot/extensions/vscode`. GitPilot's native `StateStore`, API clients, panels, commands, server controller, approvals, diff workflow, and provider settings become the only coding path. Eris observation lives in a small `src/eris` adapter and is fire-and-forget.

**Tech Stack:** TypeScript, VS Code Extension API, Node.js 22, Python test contract, GitPilot FastAPI server, VSIX packaging.

**Spec:** `docs/superpowers/specs/2026-09-21-eris-gitpilot-extension-design.md`

## Global Constraints

- The upstream source of truth is `services/gitpilot/extensions/vscode`.
- The shipped package is `gtvk.eris-code`; the separate `ruslanmv.gitpilot-vscode` extension is not required.
- The shipped extension uses upstream `gitpilot.*` command identifiers and `gitpilot.*` settings.
- The default backend URL is `http://127.0.0.1:8000` and the default launch command is `gitpilot`.
- Eris observation is optional and must never block chat, plan, approval, tool execution, diff, apply, revert, or session flows.
- Existing unrelated changes under `.eris_home/memory/core` must not be modified.
- The current VS Code CLI is 1.138.0, which satisfies upstream's `^1.110.0` engine requirement.

## Review Focus

- Missing or stale compiled webview assets: the VSIX must contain the templates and CSS that the native GitPilot panels load.
- A busy port 8000: the server controller must follow GitPilot's port-file result instead of assuming the requested port stayed free.
- `gitpilot` missing from the Extension Host PATH: the settings/diagnostics path must show the command error and allow a full command path.
- Workspace without a Git remote: local folder mode must remain usable without silently changing the native GitPilot session contract.
- Eris Link endpoint down: observation failures must be swallowed and must not fail a GitPilot request.

### Task 1: Add the failing integration contract

**Files:**
- Create: `src/tests/test_eris_gitpilot_extension_contract.py`
- Read: `src/vscode-extension/package.json`, `src/vscode-extension/src/extension.ts`, `src/vscode-extension/resources/`

**Interfaces:**
- Consumes: the Eris extension package manifest and source/resource tree.
- Produces: a repeatable contract test that later sync/build work must satisfy.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "src" / "vscode-extension"


def load_manifest():
    return json.loads((EXT / "package.json").read_text(encoding="utf-8"))


def test_manifest_is_eris_branded_gitpilot_distribution():
    manifest = load_manifest()
    commands = {item["command"] for item in manifest["contributes"]["commands"]}
    settings = manifest["contributes"]["configuration"]["properties"]

    assert manifest["name"] == "eris-code"
    assert "GitPilot" in manifest["displayName"]
    assert manifest["main"] == "./out/extension.js"
    assert "gitpilot.openChat" in commands
    assert "gitpilot.applyProposedChanges" in commands
    assert "gitpilot.setPermissionMode" in commands
    assert "gitpilot.serverUrl" in settings
    assert "gitpilot.permissionMode" in settings
    assert "erisCode.erisLink.enabled" in settings


def test_native_gitpilot_entrypoint_and_resources_are_present():
    assert (EXT / "src" / "extension.ts").is_file()
    assert (EXT / "resources" / "icon.svg").is_file()
    assert (EXT / "resources" / "icon.png").is_file()


def test_old_eris_adapter_is_not_the_active_entrypoint():
    manifest = load_manifest()
    assert manifest["main"] != "./dist/extension.js"
    assert not (EXT / "src" / "chatPanel.ts").is_file()
    assert not (EXT / "src" / "gitPilotClient.ts").is_file()
```

- [ ] **Step 2: Run the test to verify it fails for the expected reason**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest src\tests\test_eris_gitpilot_extension_contract.py -q
```

Expected: FAIL because the current package still points at `dist/extension.js`, exposes `erisCode.*` commands, and keeps the old adapter files.

- [ ] **Step 3: Commit the red test**

```powershell
git add src/tests/test_eris_gitpilot_extension_contract.py
git commit -m "test: define Eris GitPilot extension contract"
```

### Task 2: Synchronize upstream GitPilot UI and coding brain

**Files:**
- Create: `src/vscode-extension/resources/icon.svg`, `src/vscode-extension/resources/icon.png`
- Create/replace: `src/vscode-extension/src/**` with the tree from `services/gitpilot/extensions/vscode/src/**`
- Create/replace: `src/vscode-extension/test/**` with the upstream extension tests
- Create: `src/vscode-extension/scripts/sync-upstream.ps1`
- Modify: `src/vscode-extension/package.json`
- Modify: `src/vscode-extension/package-lock.json`
- Modify: `src/vscode-extension/tsconfig.json`
- Modify: `src/vscode-extension/.vscodeignore`

**Interfaces:**
- Consumes: `services/gitpilot/extensions/vscode/src`, its `test`, `resources`, `scripts/copy-webview-assets.js`, `tsconfig.json`, and upstream package dependencies.
- Produces: a branded Eris package with upstream `extension.ts` as `./out/extension.js`, upstream panel/client/state implementations, and a reproducible source sync command.

- [ ] **Step 1: Add the synchronization script**

Implement `src/vscode-extension/scripts/sync-upstream.ps1` with these exact responsibilities:

```powershell
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.." )).Path
$Upstream = Join-Path $RepoRoot "services\gitpilot\extensions\vscode"
$Destination = Join-Path $RepoRoot "src\vscode-extension"

if (-not (Test-Path (Join-Path $Upstream "src\extension.ts"))) {
  throw "Vendored GitPilot extension source is missing."
}

Remove-Item (Join-Path $Destination "src") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Destination "test") -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Upstream "src") (Join-Path $Destination "src") -Recurse -Force
Copy-Item (Join-Path $Upstream "test") (Join-Path $Destination "test") -Recurse -Force
Copy-Item (Join-Path $Upstream "resources") (Join-Path $Destination "resources") -Recurse -Force
Copy-Item (Join-Path $Upstream "scripts\copy-webview-assets.js") (Join-Path $Destination "scripts\copy-webview-assets.js") -Force
Copy-Item (Join-Path $Upstream "tsconfig.json") (Join-Path $Destination "tsconfig.json") -Force
Copy-Item (Join-Path $Upstream ".vscodeignore") (Join-Path $Destination ".vscodeignore") -Force
```

Keep `package.json`, `package-lock.json`, and the Eris packaging scripts under explicit local control so the sync cannot overwrite branding or distribution metadata.

- [ ] **Step 2: Apply the package branding delta**

Start from the upstream package manifest and set:

```json
{
  "name": "eris-code",
  "displayName": "Eris · GitPilot",
  "description": "Eris coding workspace powered by the GitPilot multi-agent assistant.",
  "version": "0.23.0",
  "publisher": "gtvk",
  "main": "./out/extension.js",
  "icon": "resources/icon.png",
  "repository": { "type": "git", "url": "https://github.com/Gtvkun-ai/eris" }
}
```

Keep all upstream `gitpilot.*` commands, views, settings, activation events, dependencies, and `^1.110.0` engine requirement. Add the existing Eris Link settings under `erisCode.erisLink.enabled`, `erisCode.erisLink.observeWorkspace`, and `erisCode.erisLink.endpoint`.

- [ ] **Step 3: Add the Eris identity/context adapter outside the upstream tree**

Create `src/vscode-extension/src/eris/` and move the existing Eris observation modules into that namespace:

- `codingObservation.ts`
- `erisObserverBridge.ts`
- `companionWorkspaceObserver.ts`

Modify the upstream `src/extension.ts` only to instantiate `ErisObserverBridge` and `CompanionWorkspaceObserver` when `erisCode.erisLink.enabled` is true, register `erisCode.companion.observeExternalAgent`, and add the disposables to `context.subscriptions`. Do not pass Eris context into the GitPilot request body and do not await observation network calls from task execution.

- [ ] **Step 4: Build the smallest green slice**

Run:

```powershell
.\src\vscode-extension\scripts\sync-upstream.ps1
Push-Location src\vscode-extension
npm install --no-audit --no-fund
npm run compile
Pop-Location
.\.venv\Scripts\python.exe -m pytest src\tests\test_eris_gitpilot_extension_contract.py -q
```

Expected: the contract test passes, `src/vscode-extension/out/extension.js` exists, and the compiled webview templates exist under `out/ui/webview/`.

- [ ] **Step 5: Commit the source integration**

```powershell
git add src/vscode-extension src/tests/test_eris_gitpilot_extension_contract.py
git commit -m "feat: make Eris extension use native GitPilot"
```

### Task 3: Make Eris packaging ship the native GitPilot artifact

**Files:**
- Modify: `src/vscode-extension/package_vsix.py`
- Modify: `src/vscode-extension/build_vsix.ps1`
- Create: `src/vscode-extension/build_install.ps1`
- Modify: `src/vscode-extension/README.md`
- Modify: `README.md` where the Eris extension build is documented

**Interfaces:**
- Consumes: `src/vscode-extension/package.json`, `out/**`, `resources/**`, and the VS Code `code` CLI.
- Produces: `eris-code-0.23.0.vsix` containing `extension/package.json`, `extension/out/**`, and `extension/resources/**`, plus an install command that replaces the stale `gtvk.eris-code-0.21.0` installation.

- [ ] **Step 1: Add a packaging contract test before changing the packer**

Extend `src/tests/test_eris_gitpilot_extension_contract.py` with a test that opens the generated VSIX as a zip and asserts these entries after packaging:

```python
import zipfile


def test_vsix_contains_native_out_and_resources(tmp_path):
    # The implementation will call package_vsix.py before this assertion.
    vsix = next((ROOT / "src" / "vscode-extension").glob("eris-code-*.vsix"))
    with zipfile.ZipFile(vsix) as archive:
        names = set(archive.namelist())
    assert "extension/package.json" in names
    assert "extension/out/extension.js" in names
    assert "extension/out/ui/webview/gitpilotWorkspaceTemplate.html" in names
    assert "extension/resources/icon.svg" in names
```

Run the test before the packer change and confirm it fails because the current VSIX has `dist/` and the legacy media allowlist instead of the upstream `out/` tree.

- [ ] **Step 2: Update `package_vsix.py` to package upstream layout**

Change the packer to validate `out/extension.js`, recursively include every `.js`, `.js.map`, `.html`, and `.css` file below `out/`, and recursively include `resources/`. Do not include `src/`, `test/`, `node_modules/`, TypeScript source, or maps outside `out/`. Keep the manifest identity/version from `package.json` and fail if the package contains neither the native entrypoint nor the native workspace template.

- [ ] **Step 3: Add build/install automation**

`build_vsix.ps1` must run, in order:

```powershell
npm install --no-audit --no-fund
npm run compile
python package_vsix.py
```

`build_install.ps1` must call `build_vsix.ps1`, resolve the newest `eris-code-*.vsix`, verify `code` is on PATH, and run:

```powershell
code --install-extension $Vsix --force
```

If `code` is missing, the script must leave the VSIX path in its error output instead of failing after deleting anything.

- [ ] **Step 4: Document the new workflow**

Document the exact commands for source sync, compile/package, force-install, backend setup, and backend start. State that the user should reload VS Code after installation and that the Eris extension now exposes GitPilot commands/settings.

- [ ] **Step 5: Run packaging verification and commit**

```powershell
Push-Location src\vscode-extension
.\build_vsix.ps1
Pop-Location
.\.venv\Scripts\python.exe -m pytest src\tests\test_eris_gitpilot_extension_contract.py -q
git add src/vscode-extension README.md src/tests/test_eris_gitpilot_extension_contract.py
git commit -m "build: package native GitPilot UI in Eris VSIX"
```

### Task 4: Verify the full native GitPilot workflow

**Files:**
- Test: `services/gitpilot/extensions/vscode/test/**`
- Test: `src/tests/test_eris_gitpilot_extension_contract.py`
- Verify: `src/vscode-extension/out/**`, `src/vscode-extension/eris-code-0.23.0.vsix`

**Interfaces:**
- Consumes: the synchronized extension, the vendored GitPilot server, and the generated VSIX.
- Produces: evidence that the installed Eris package uses the upstream UI/brain and does not regress the unrelated Eris workspace.

- [ ] **Step 1: Run typecheck and upstream extension tests**

```powershell
Push-Location src\vscode-extension
npm run compile
npm test
Pop-Location
```

Expected: TypeScript compilation succeeds and all upstream extension suites pass, including connection, composer, chat panel, command wiring, settings, diagnostics, and error translation.

- [ ] **Step 2: Run the backend smoke test**

Start the backend in a managed terminal:

```powershell
$server = Start-Process gitpilot -ArgumentList "serve","--port","8000","--no-open","--skip-init" -WorkingDirectory (Get-Location) -PassThru
try {
  $ready = $false
  for ($i = 0; $i -lt 30; $i++) {
    try {
      $response = Invoke-WebRequest http://127.0.0.1:8000/api/status -TimeoutSec 2 -UseBasicParsing
      if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw "GitPilot did not answer /api/status" }
  $response.Content | ConvertFrom-Json | Out-Null
} finally {
  if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
```

Expected: `/api/status` returns JSON with `server_ready: true`, and the server process is stopped by the `finally` block.

- [ ] **Step 3: Install and inspect the new extension package**

```powershell
Push-Location src\vscode-extension
.\build_install.ps1
Pop-Location
code --list-extensions --show-versions | Select-String "gtvk.eris-code"
```

Expected: the installed version is `gtvk.eris-code@0.23.0`; the old `0.21.0` installation is replaced by VS Code's same-extension upgrade path.

- [ ] **Step 4: Verify runtime boundaries**

With the new extension active, verify in the GitPilot output channel:

- server startup/probe uses `gitpilot serve` and `/api/status`;
- the native GitPilot Home/Chat UI opens;
- `gitpilot.permissionMode` changes the backend mode;
- Plan mode shows a plan and blocks writes;
- Ask mode displays approval cards;
- Auto mode executes without approval;
- proposed edits expose native diff/apply/revert actions;
- stopping the optional Eris Link endpoint does not fail a chat request.

- [ ] **Step 5: Run the repository contract test and inspect the diff**

```powershell
.\.venv\Scripts\python.exe -m pytest src\tests\test_eris_gitpilot_extension_contract.py -q
git diff --check
git status --short
```

Expected: contract tests pass, no whitespace errors are reported, and only the integration files plus the new spec/plan are changed; `.eris_home/memory/core/*` remains present in status only as the pre-existing unrelated modifications.

- [ ] **Step 6: Commit the verified integration**

```powershell
git add src/vscode-extension src/tests/test_eris_gitpilot_extension_contract.py README.md
git commit -m "feat: ship Eris as a branded GitPilot extension"
```
