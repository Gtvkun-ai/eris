# Tech Stack & Conventions

## Backend (Python Brain)
- Python 3.12+
- LangGraph cho agent loop
- Khong dung async/await trong runtime chinh (threading model)
- Tat ca import lazy (trong ham) de tranh circular import

## Frontend (VS Code Extension)
- TypeScript + esbuild
- Khong dung React/Vue — vanilla JS trong webview
- WebSocket de communicate voi Python Brain

## GitPilot
- Local backend clone: services/gitpilot
- CLI: gitpilot
- Default API docs: http://127.0.0.1:8000/docs

## Conventions
- Python: snake_case, type hints, docstrings
- TypeScript: camelCase, JSDoc khi can
- Khong commit .env hay credentials
- File steering: .eris/steering/*.md
- File spec: .eris/specs/*.md

## LLM
- Coding provider is configured in GitPilot.
