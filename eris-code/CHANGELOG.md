# 0.18.0 — Runtime split

- Split Eris Code from Eris Desktop runtime.
- Removed Eris Service discovery/launcher and standalone coding agent from the extension.
- GitPilot is the only coding runtime/owner used by the extension.
- Pinned external runtime install to `gitcopilot==0.2.7`.
- Default topology is `feature_builder`.
- Added strict no-silent-downgrade policy for folder/direct-LLM fallback.
- Added reversible local patch snapshots for GitPilot proposed edits.
- Added optional read-only Eris Link v1 observation context.
- Renamed commands/settings/view namespace to `erisCode.*`.
