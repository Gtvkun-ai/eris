# ERIS DeepSeek Web Multi-Worker Base

This revision adds a role-based DeepSeek Web foundation without modifying
Whale2API or DeepSeek Web behavior.

## Required gateway keys

```env
ERIS_DS_COMPANION_API_KEY=...
ERIS_DS_OBSERVER_API_KEY=...
ERIS_DS_CRITIC_API_KEY=...
ERIS_DS_INNER_API_KEY=...
ERIS_DS_STYLE_API_KEY=...
ERIS_DS_RESEARCH_API_KEY=...
```

Each value is a Whale2API gateway API key. Configure PoolUI so each gateway key
can use only the account/account-pool assigned to that cognitive role. ERIS does
not need Gmail addresses or DeepSeek passwords.

Shared defaults:

```env
ERIS_DS_BASE_URL=http://127.0.0.1:6011/v1
ERIS_DS_MODEL=deepseek-v4-flash
```

Role-specific `_BASE_URL` and `_MODEL` variables are supported, for example
`ERIS_DS_OBSERVER_MODEL`, but are optional.

## Routing supplied by this base

- `companion`: main DS2API chat key; official API fallback behavior is retained.
- `observer`: preferred by social parser and social observer fallback.
- `critic`: preferred by social critic, format fallback and escalation.
- `inner`: exposed as `llm_service.inner_client`; used by PrivateMind,
  daydream/affect self-read and memory curator.
- `style`: preferred by the existing style client slot.
- `research`: exposed as `llm_service.research_client`; used by Tutor remote
  generation and distillation.

Missing role keys do not stop startup. The old Groq/Gemini/legacy provider path
remains as fallback, allowing incremental rollout.

## JSONL boundary

`llm/deepseek_workers.py` wraps role clients without changing the normal
OpenAI-compatible response shape. When a structured worker receives
`response_format={"type":"json_object"}` or `json_schema`, it:

1. accepts one JSON object or array;
2. removes accidental code fences;
3. serializes it as one canonical physical line;
4. retries once with a strict repair instruction when invalid;
5. raises `JsonlContractError` rather than committing malformed data.

JSONL defaults:

- enabled: observer, critic, inner, research;
- disabled: companion, style.

These defaults can be changed with `ERIS_DS_<ROLE>_JSONL`.

## Session behavior

The existing isolated Web session mechanism remains unchanged. Chat and
`autonomous` retain companion continuity. `inner`, `private_mind` and
`daydream` are also persistent. Observer, critic, style and research remain
one-shot/short-lived unless the inference lane configuration is changed.

## Files changed

- `llm/deepseek_workers.py`
- `llm/process_manager.py`
- `llm/service.py`
- `llm/client.py`
- `vision.py`
- `runtime/private_mind_model_adapter.py`
- `runtime/affect_self_read.py`
- `runtime/coordinator_bootstrap.py`
- `runtime/tutor_wiring.py`
- `memory/memory_ai_curator.py`
- `config/deepseek.env.example`
