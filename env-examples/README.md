# ERIS — Env presets

Bộ file `.env` mẫu cho các kiểu setup khác nhau. Chọn 1 file hợp với máy, copy
ra `.env` ở thư mục gốc rồi điền `GEMINI_API_KEY` (và key khác nếu dùng).

| Preset | File | Hợp với máy | Local engine | Quota API |
|--------|------|-------------|--------------|-----------|
| Local GPU | `.env.local-gpu.example` | GPU rời ≥6GB VRAM | llama-cpp (GPU) | thấp |
| Hybrid | `.env.hybrid.example` | GPU nhỏ ~4GB | llama-cpp (text GPU, vision CPU) | vừa |
| Ollama | `.env.ollama.example` | Đã cài Ollama | Ollama server | vừa |
| Cloud | `.env.cloud.example` | Không GPU / laptop | tắt (full remote) | cao |
| Minimal | `.env.minimal.example` | Test nhanh / máy rất yếu | tắt | thấp nhất |

## Cách dùng (Windows / cmd)

```cmd
copy env-examples\.env.hybrid.example .env
```

Sau đó mở `.env`, điền `GEMINI_API_KEY=...` và chạy như bình thường.

## Ghi chú

- Preset **Local GPU / Hybrid** cần các file gguf trong `src/`
  (`qwen3-1.7b-q4_k_m.gguf`, `moondream2-q4_k.gguf`, `moondream2-mmproj-f16.gguf`).
- Preset **Ollama** cần `ollama serve` chạy nền và đã `ollama pull` các model
  (`qwen3:1.7b`, `qwen3:0.6b`, `moondream`).
- OOM "Failed to load model" trên GPU → hạ `ERIS_LLAMACPP_VISION_N_GPU_LAYERS`
  (16 → 12 → 8 → 0) hoặc `ERIS_LLAMACPP_N_GPU_LAYERS`.
- Đừng commit `.env` thật có key. Các file ở đây chỉ là mẫu (key để trống).
```
