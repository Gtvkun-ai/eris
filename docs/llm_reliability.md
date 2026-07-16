# ERIS — Độ tin cậy LLM (Phase 0/1/4 + DDS)

Tài liệu này tóm tắt các thay đổi đã làm để sửa lỗi LLM (413/500/timeout) và
hướng tái kiến trúc gọi model theo mô hình **DDS — Decompose → Distill →
Synthesize**.

## Sơ đồ DDS

```
                ┌──────── WORKER LAYER (song song, key-pool, có trần đồng thời) ────────┐
INPUT (turn) ─► │  rút gọn memory / conversation / grounding / ni / ti thành bullet ngắn │
+ state         │  mỗi worker text thuần, ≤ vài trăm token, lỗi → giữ khối gốc (degrade) │
                └───────────────────────────────┬──────────────────────────────────────┘
                                                 │  CHỈ phần distilled (nhỏ)
                                                 â–¼
                          ┌──────── SYNTHESIS (qwen/Groq hoặc Gemini) ────────┐
                          │  prompt = ngữ cảnh đã rút gọn → câu nói / directive │
                          └────────────────────────────────────────────────────┘
```

Distillation **chỉ kích hoạt khi ngữ cảnh nặng** vượt `ERIS_DDS_TRIGGER_TOKENS`
(mặc định 60% hard-cap). Turn nhỏ đi thẳng synthesis như cũ.

## Hàng rào token (chặn 413)

- `src/llm/token_budget.py`: ước lượng token (chars/4), suy provider từ
  base_url/model, trần TPM (Groq=6000), và **hard-cap**: nếu prompt vượt cap thì
  cắt history cũ (giữ system + lượt cuối), rồi truncate nếu vẫn vượt.
- Chạy tự động trong cả 3 client (`OpenAICompatibleClient`, `GeminiClient`,
  `LlamaServerClient`) qua `preflight(...)`, log `[LLM PREFLIGHT] ...`.
- Bật/chỉnh bằng `ERIS_LLM_PROMPT_HARD_CAP_TOKENS`.

## Request hygiene cho Gemma (chặn 500)

- Gemma trên Gemini API không nhận `system_instruction` và không nhận ảnh inline.
  `GeminiClient` tự **gập system vào lượt user đầu** và **tước ảnh** khi model bắt
  đầu bằng `gemma`. Ảnh nên được mô tả thành text ở mạch local trước.
- Phân loại lỗi: `429/5xx` → đánh dấu key nghỉ + xoay key thử lại; `4xx` khác
  (sai shape) → KHÔNG retry.
- Timeout synthesis tách khỏi fragment: `ERIS_PRIVATE_MIND_SYNTHESIS_TIMEOUT`.

## Key-pool (Phase 4)

- `src/llm/key_pool.py`: pool theo provider (gemini/groq), round-robin, **đánh dấu
  key chết kèm cooldown** (429=60s, 5xx=15s) và tá»± hồi; bỏ qua key chết khi xoay.
- Nạp thêm key dự phòng từ env: `ERIS_GROQ_FALLBACK_API_KEYS`,
  `ERIS_PRIVATE_MIND_FALLBACK_API_KEYS`, `ERIS_GEMINI_FALLBACK_API_KEYS`.
- Trần đồng thời per-provider: `ERIS_LLM_MAX_CONCURRENCY` (+ override `*_GEMINI_*`,
  `*_GROQ_*`) — dùng bởi worker DDS song song.

## Nạp config (.env) — sửa R3/E7

- Trước đây không có chá»— nào nạp `.env` → mọi toggle trong `.env` vô hiệu, runtime
  chạy theo `secrets.json`/default. Nay `eris_secrets.load_env_file()` nạp `.env`
  với precedence **OS-env > .env > secrets.json**, log nguồn thắng qua
  `log_config_sources(...)`. Test cô lập bằng `ERIS_DISABLE_DOTENV=1`.

## Mạch nào chạy đâu

| Mạch | Khuyến nghị | Cấu hình |
|---|---|---|
| Synthesis chính (chat/directive) | qwen (Groq) / Gemini | `ERIS_REMOTE_*` |
| Worker distill (DDS) | remote/Groq when enabled | cheap plain-text client |
| Fragment private-mind | Groq Qwen | `ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER=openai_compatible` |
| Judgment/diary | Groq / remote | `ERIS_PRIVATE_MIND_PROVIDER` |
| Observer / vision | rule-based observer / remote vision | `ERIS_LOCAL_LLM_ENGINE=remote` |

No-GPU machines: use the cloud/remote preset, or reduce heavy background loops and raise
`ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC` to avoid frequent remote calls.

## Lưu ý build

Đây là source `.py`. Để có hiệu lực dưới `Eris.exe` cần build `.pyc` mới rồi đồng
bộ sang bản đóng gói (không kèm `secrets.json`/`.env` thật).
