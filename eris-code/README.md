# Eris Code

Eris Code is a **standalone VS Code coding product**. It does not require, import, discover or launch Eris Desktop.

## Runtime ownership

```text
VS Code / Eris Code
        |
        v
GitPilot backend
        |
        v
GitPilot Router + specialists
        |
        v
Official model provider (OpenAI by default for this setup)
```

Eris Desktop is optional and may only contribute observation / long-term project context through the versioned Eris Link. If Eris Desktop is closed, coding behavior remains available.

## Install GitPilot

GitPilot's PyPI package is named `gitcopilot`; the CLI is `gitpilot`.

Windows:

```powershell
.\scripts\install_gitpilot.ps1
```

or:

```powershell
py -3.12 -m pip install --upgrade gitcopilot==0.2.7
gitpilot doctor
```

GitPilot requires Python 3.11/3.12 for the pinned runtime.

## Configure the official API in GitPilot

Do **not** put the coding API key in Eris Desktop or in the webview. Configure the GitPilot backend provider itself, e.g. OpenAI, using GitPilot's supported settings/environment.

Example environment:

```text
GITPILOT_PROVIDER=openai
OPENAI_API_KEY=<your key>
GITPILOT_OPENAI_MODEL=<your chosen coding model>
```

Then start the backend:

```text
gitpilot serve --port 8000
```

Eris Code can auto-start the local CLI when `erisCode.gitpilot.autoStart=true`.

## Multi-agent invariant

The default topology is `feature_builder`. Eris Code first tries a **GitHub-connected GitPilot session** so GitPilot can own the multi-agent coding flow.

Upstream GitPilot currently documents a different behavior for folder-only sessions: code generation can use direct LLM structured output instead of the CrewAI pipeline. Therefore Eris Code defaults `erisCode.gitpilot.allowFolderDirectFallback=false` and refuses to silently downgrade. Connect an `origin` on GitHub (and configure GitPilot GitHub access), or explicitly enable the fallback if you accept that behavior.

## Eris Desktop link

Disabled by default:

```text
erisCode.erisLink.enabled = false
```

When enabled, Eris Code reads a small read-only context envelope from `erisCode.erisLink.endpoint`. Failure or timeout is ignored. The extension never launches Eris Desktop.

See `protocol/ERIS_LINK_V1.md`.
