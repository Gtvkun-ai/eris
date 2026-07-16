# ERIS env presets

Sample `.env` files for supported runtime shapes. Pick one, copy it to the repo
root as `.env`, then fill in the required API keys.

| Preset | File | Best for | Local engine | API quota |
|--------|------|----------|--------------|-----------|
| Cloud | `.env.cloud.example` | No GPU / laptop | off, full remote | high |
| Minimal | `.env.minimal.example` | Quick tests / weak machines | off | lowest |

## Windows usage

```cmd
copy env-examples\.env.cloud.example .env
```

Notes:
- Local inference presets have been removed from this repo.
- Do not commit a real `.env` with keys.
