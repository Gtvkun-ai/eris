# ERIS â€” Äá»™ tin cáº­y LLM (Phase 0/1/4 + DDS)

TÃ i liá»‡u nÃ y tÃ³m táº¯t cÃ¡c thay Ä‘á»•i Ä‘Ã£ lÃ m Ä‘á»ƒ sá»­a lá»—i LLM (413/500/timeout) vÃ 
hÆ°á»›ng tÃ¡i kiáº¿n trÃºc gá»i model theo mÃ´ hÃ¬nh **DDS â€” Decompose â†’ Distill â†’
Synthesize**.

## SÆ¡ Ä‘á»“ DDS

```
                â”Œâ”€â”€â”€â”€â”€â”€â”€â”€ WORKER LAYER (song song, key-pool, cÃ³ tráº§n Ä‘á»“ng thá»i) â”€â”€â”€â”€â”€â”€â”€â”€â”
INPUT (turn) â”€â–º â”‚  rÃºt gá»n memory / conversation / grounding / ni / ti thÃ nh bullet ngáº¯n â”‚
+ state         â”‚  má»—i worker text thuáº§n, â‰¤ vÃ i trÄƒm token, lá»—i â†’ giá»¯ khá»‘i gá»‘c (degrade) â”‚
                â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                                 â”‚  CHá»ˆ pháº§n distilled (nhá»)
                                                 â–¼
                          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€ SYNTHESIS (qwen/Groq hoáº·c Gemini) â”€â”€â”€â”€â”€â”€â”€â”€â”
                          â”‚  prompt = ngá»¯ cáº£nh Ä‘Ã£ rÃºt gá»n â†’ cÃ¢u nÃ³i / directive â”‚
                          â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

Distillation **chá»‰ kÃ­ch hoáº¡t khi ngá»¯ cáº£nh náº·ng** vÆ°á»£t `ERIS_DDS_TRIGGER_TOKENS`
(máº·c Ä‘á»‹nh 60% hard-cap). Turn nhá» Ä‘i tháº³ng synthesis nhÆ° cÅ©.

## HÃ ng rÃ o token (cháº·n 413)

- `src/llm/token_budget.py`: Æ°á»›c lÆ°á»£ng token (chars/4), suy provider tá»«
  base_url/model, tráº§n TPM (Groq=6000), vÃ  **hard-cap**: náº¿u prompt vÆ°á»£t cap thÃ¬
  cáº¯t history cÅ© (giá»¯ system + lÆ°á»£t cuá»‘i), rá»“i truncate náº¿u váº«n vÆ°á»£t.
- Cháº¡y tá»± Ä‘á»™ng trong cáº£ 3 client (`OpenAICompatibleClient`, `GeminiClient`,
  `LlamaServerClient`) qua `preflight(...)`, log `[LLM PREFLIGHT] ...`.
- Báº­t/chá»‰nh báº±ng `ERIS_LLM_PROMPT_HARD_CAP_TOKENS`.

## Request hygiene cho Gemma (cháº·n 500)

- Gemma trÃªn Gemini API khÃ´ng nháº­n `system_instruction` vÃ  khÃ´ng nháº­n áº£nh inline.
  `GeminiClient` tá»± **gáº­p system vÃ o lÆ°á»£t user Ä‘áº§u** vÃ  **tÆ°á»›c áº£nh** khi model báº¯t
  Ä‘áº§u báº±ng `gemma`. áº¢nh nÃªn Ä‘Æ°á»£c mÃ´ táº£ thÃ nh text á»Ÿ máº¡ch local trÆ°á»›c.
- PhÃ¢n loáº¡i lá»—i: `429/5xx` â†’ Ä‘Ã¡nh dáº¥u key nghá»‰ + xoay key thá»­ láº¡i; `4xx` khÃ¡c
  (sai shape) â†’ KHÃ”NG retry.
- Timeout synthesis tÃ¡ch khá»i fragment: `ERIS_PRIVATE_MIND_SYNTHESIS_TIMEOUT`.

## Key-pool (Phase 4)

- `src/llm/key_pool.py`: pool theo provider (gemini/groq), round-robin, **Ä‘Ã¡nh dáº¥u
  key cháº¿t kÃ¨m cooldown** (429=60s, 5xx=15s) vÃ  tá»± há»“i; bá» qua key cháº¿t khi xoay.
- Náº¡p thÃªm key dá»± phÃ²ng tá»« env: `ERIS_GROQ_FALLBACK_API_KEYS`,
  `ERIS_PRIVATE_MIND_FALLBACK_API_KEYS`, `ERIS_GEMINI_FALLBACK_API_KEYS`.
- Tráº§n Ä‘á»“ng thá»i per-provider: `ERIS_LLM_MAX_CONCURRENCY` (+ override `*_GEMINI_*`,
  `*_GROQ_*`) â€” dÃ¹ng bá»Ÿi worker DDS song song.

## Náº¡p config (.env) â€” sá»­a R3/E7

- TrÆ°á»›c Ä‘Ã¢y khÃ´ng cÃ³ chá»— nÃ o náº¡p `.env` â†’ má»i toggle trong `.env` vÃ´ hiá»‡u, runtime
  cháº¡y theo `secrets.json`/default. Nay `eris_secrets.load_env_file()` náº¡p `.env`
  vá»›i precedence **OS-env > .env > secrets.json**, log nguá»“n tháº¯ng qua
  `log_config_sources(...)`. Test cÃ´ láº­p báº±ng `ERIS_DISABLE_DOTENV=1`.

## Máº¡ch nÃ o cháº¡y Ä‘Ã¢u

| Máº¡ch | Khuyáº¿n nghá»‹ | Cáº¥u hÃ¬nh |
|---|---|---|
| Synthesis chÃ­nh (chat/directive) | qwen (Groq) / Gemini | `ERIS_REMOTE_*` |
| Worker distill (DDS) | remote/Groq when enabled | cheap plain-text client |
| Fragment private-mind | Groq Qwen | `ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER=openai_compatible` |
| Judgment/diary | Groq / remote | `ERIS_PRIVATE_MIND_PROVIDER` |
| Observer / vision | rule-based observer / remote vision | `ERIS_LOCAL_LLM_ENGINE=remote` |

No-GPU machines: use the cloud/remote preset, or reduce heavy background loops and raise
`ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC` to avoid frequent remote calls.

## LÆ°u Ã½ build

ÄÃ¢y lÃ  source `.py`. Äá»ƒ cÃ³ hiá»‡u lá»±c dÆ°á»›i `Eris.exe` cáº§n build `.pyc` má»›i rá»“i Ä‘á»“ng
bá»™ sang báº£n Ä‘Ã³ng gÃ³i (khÃ´ng kÃ¨m `secrets.json`/`.env` tháº­t).
