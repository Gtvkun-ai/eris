# Tech Stack & Conventions

## Backend (Python Brain)
- Python 3.12+
- LangGraph cho agent loop (fallback khi Cline bridge khong co)
- Khong dung async/await trong runtime chinh (threading model)
- Tat ca import lazy (trong ham) de tranh circular import

## Frontend (VS Code Extension)
- TypeScript + esbuild
- Khong dung React/Vue — vanilla JS trong webview
- WebSocket de communicate voi Python Brain

## Cline Bridge (Node.js)
- Node.js ESM
- @cline/core SDK
- Provider: openai-compatible + localhost:8081 (WebAI proxy)
- Build: tsc (khong dung esbuild cho bridge)

## Conventions
- Python: snake_case, type hints, docstrings
- TypeScript: camelCase, JSDoc khi can
- Khong commit .env hay credentials
- File steering: .eris/steering/*.md
- File spec: .eris/specs/*.md

## LLM
- Provider: Gemini qua WebAI-to-API proxy
- Endpoint: http://localhost:8081/v1 (OpenAI-compatible)
- Model mac dinh: gemini-3-pro
- Khong can API key — dung Google cookie session
