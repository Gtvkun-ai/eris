# ERIS

ERIS là một hiện diện desktop (desktop companion) chạy trên Godot: phần thân (body)
vẽ bằng Godot/C#, phần nhận thức (cortex/runtime) viết bằng Python. Body và runtime
nói chuyện với nhau qua UDP. Cognition dùng các model qua API miễn phí (Gemini / Groq),
có cơ chế **xoay vòng nhiều key** để tận dụng free quota.

> Bản beta. Cần chuẩn bị key API free của riêng bạn (xem phần Cấu hình key).

---

## 1. Yêu cầu

| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Godot | 4.6 (bản **.NET / C#**) | Chạy phần body. Phải là bản Mono/.NET, không phải bản standard. |
| .NET SDK | 8.0+ | Để Godot build C#. |
| Python | 3.10+ (đã test trên 3.13) | Chạy phần cortex/runtime. |
| OS | Windows | Runtime dùng `mss`, `uiautomation`, `msvcrt` (hiện bám Windows). |

Bạn cũng cần ít nhất một **Gemini API key** (bắt buộc) và tùy chọn thêm **Groq API key**.
Cả hai đều có bậc miễn phí.

---

## 2. Cài đặt

### 2.1. Lấy mã nguồn
```powershell
git clone <repo-url> eris
cd eris
```

### 2.2. Môi trường Python
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` chỉ liệt kê các lib runtime cốt lõi (`mss`, `Pillow`, `psutil`,
`requests`, `uiautomation`). Phần embedding/semantic dùng model
`paraphrase-multilingual-MiniLM-L12-v2` (đã kèm trong repo) qua `transformers` + `torch`.
Nếu import báo thiếu, cài thêm:
```powershell
pip install transformers torch
```

### 2.3. Build phía Godot
Mở thư mục dự án bằng **Godot 4.6 .NET**. Lần đầu Godot sẽ tự khôi phục NuGet và
build assembly `Eris`. Nếu build C# lỗi, kiểm tra .NET SDK đã cài đúng.

### 2.4. Model local (llama-cpp + GPU) — chạy mọi mạch nội bộ offline

ERIS dồn các mạch model nội bộ (private-mind fragment/judgment/diary, background
observer, vision compressor) qua **llama-cpp-python** đọc thẳng file `.gguf` đặt
trong `src/` — **không cần Ollama/llama-server ngoài**. Mạch nói chính (main
cognition) vẫn dùng remote API (Gemini) như cũ.

**Bước 1 — Tải các model gguf vào `src/`** (ngang hàng nhau):

| File trong `src/` | Vai trò | Nguồn (HuggingFace) |
|---|---|---|
| `qwen3-1.7b-q4_k_m.gguf` | text: fragment + judgment + observer | `unsloth/Qwen3-1.7B-GGUF` → `Qwen3-1.7B-Q4_K_M.gguf` |
| `moondream2-q4_k.gguf` | vision (model) | `vikhyatk/moondream2` (gguf) |
| `moondream2-mmproj-f16.gguf` | vision (mmproj/clip) | `vikhyatk/moondream2` (mmproj) |

```powershell
# ví dụ tải qwen3 (đổi tên về đúng src/qwen3-1.7b-q4_k_m.gguf)
curl.exe -L -o src\qwen3-1.7b-q4_k_m.gguf ^
  https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf
```

**Bước 2 — Cài `llama-cpp-python`.**

- Chỉ CPU (portable, chậm hơn): `pip install llama-cpp-python` (đã nằm trong
  `requirements.txt`).
- **GPU NVIDIA (CUDA, khuyên dùng):** cần **CUDA Toolkit** + **Visual Studio
  Build Tools (workload C++)**, rồi build từ nguồn. Có sẵn script
  `build_llamacpp_cuda.bat` (chỉnh đường dẫn VS/CUDA cho máy bạn rồi chạy), hoặc
  thủ công:
  ```powershell
  $env:CMAKE_ARGS = "-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75"  # 75 = GTX 16xx/20xx; sửa theo GPU
  $env:FORCE_CMAKE = "1"
  pip install llama-cpp-python==0.3.16 --force-reinstall --no-cache-dir --no-binary llama-cpp-python
  ```
  > Build CUDA mất ~10–40 phút (compile kernel). Wheel ra ~100MB (bản CPU ~6MB).
  > Nếu pip báo lỗi long-path khi giải nén bản mới, dùng `==0.3.16` và đặt
  > `TMP=C:\t` (thư mục ngắn). Kiểm tra GPU đã bật:
  > `python -c "import llama_cpp; print(llama_cpp.llama_supports_gpu_offload())"` → `True`.

**Bước 3 — Bật trong `.env`** (xem `.env.example`):
```dotenv
ERIS_LOCAL_LLM_ENGINE=llamacpp
ERIS_LLAMACPP_N_GPU_LAYERS=-1          # -1 = đẩy hết layer lên GPU; 0 = CPU
ERIS_LLAMACPP_TEXT_MODEL=src/qwen3-1.7b-q4_k_m.gguf
ERIS_LLAMACPP_VISION_MODEL=src/moondream2-q4_k.gguf
ERIS_LLAMACPP_VISION_MMPROJ=src/moondream2-mmproj-f16.gguf
ERIS_PRIVATE_MIND_API_ENABLED=1
ERIS_PRIVATE_MIND_PROVIDER=llamacpp
ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER=llamacpp
ERIS_PRIVATE_MIND_FRAGMENT_FREETEXT=1
```
Đặt `ERIS_LOCAL_LLM_ENGINE=ollama` (hoặc bỏ trống) để quay về Ollama.

> **VRAM:** GPU 4GB chạy được vì các model nạp/giải phóng theo lịch (vision
> `unload` sau mỗi lần gọi). Máy yếu/không GPU thì để `ERIS_LLAMACPP_N_GPU_LAYERS=0`
> (chạy CPU, chậm nhưng vẫn chạy).

---

## 3. Cấu hình key (quan trọng)

ERIS đọc key từ `config/secrets.json`. File này **đã được .gitignore** nên sẽ không
bị commit. Tạo nó từ file mẫu:

```powershell
copy config\secrets.example.json config\secrets.json
```

Rồi mở `config/secrets.json` và dán key thật vào.

### Lấy key free
- **Gemini** (bắt buộc): tạo key tại Google AI Studio. Mỗi key thuộc một Google
  project khác nhau, mỗi project có hũ free quota riêng.
- **Groq** (tùy chọn, dùng cho mạch "private mind" / việc cần JSON chuẩn): tạo key tại
  Groq Console.

### Vì sao nên dán NHIỀU key
Free tier tính theo **project**, không theo key. ERIS giữ một pool key dùng chung cho
mọi mạch gọi; khi một key dính lỗi `429` (hết quota tạm thời) nó **tự xoay sang key kế
tiếp**. Càng nhiều key thuộc các project/tài khoản khác nhau → free quota tổng càng lớn,
ERIS càng ít bị "câm".

- Key Gemini chính: `api_keys.ERIS_REMOTE_API_KEY`
- Các key Gemini dự phòng (xoay vòng): thêm vào mảng `api_keys.ERIS_PRIVATE_MIND_FALLBACK_API_KEYS`
- Key Groq chính + dự phòng: `api_keys.ERIS_GROQ_API_KEY` và `api_keys.ERIS_GROQ_FALLBACK_API_KEYS`

Các giá trị bắt đầu bằng `PASTE_` được coi là placeholder và bị bỏ qua, nên cứ để
nguyên slot nào chưa dùng.

> Tinh chỉnh thêm (nhịp nói, timeout, vision...) có thể đặt qua biến môi trường —
> xem mẫu trong `.env.example`. Env sẽ override `secrets.json`.

---

## 4. Chạy

### Cách thường: qua Godot
Bấm **Run** trong Godot (main scene). Khi body khởi động, nó tự spawn tiến trình
Python runtime (`src/vision.py`) và inject env cần thiết. Body ↔ runtime trao đổi qua
UDP **cổng 4242** (decision về body) và **4243** (event/chat lên runtime).

### Cách thủ công: chạy runtime riêng (để debug)
```powershell
$env:PYTHONPATH = "src"
python src\vision.py
```
Hữu ích khi muốn xem log cortex/LLM mà không phụ thuộc Godot.

---

## 5. Chạy test
```powershell
python run_tests.py
```
hoặc trực tiếp:
```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/ -q
```

---

## 6. Xử lý sự cố

| Triệu chứng | Kiểm tra |
|---|---|
| ERIS không nói gì | Key sai/hết quota. Xem log mạch `LLM`. Thêm key dự phòng vào pool. |
| Body hiện nhưng không phản hồi | Runtime Python chưa chạy hoặc UDP 4242/4243 bị chặn (firewall). |
| `ModuleNotFoundError` khi chạy test | Chưa set `PYTHONPATH=src`, hoặc thiếu dependency. |
| Build C# fail trong Godot | Thiếu .NET SDK, hoặc đang dùng bản Godot không phải .NET. |
| Import lỗi về embedding/torch | `pip install transformers torch`. |

---

## 7. Lưu ý cho beta

- **Không bao giờ commit `config/secrets.json` hay `.env`** — cả hai đã nằm trong
  `.gitignore`. Chỉ chia sẻ `config/secrets.example.json`.
- Nếu gửi build cho người khác, tuyệt đối không kèm file key của bạn; mỗi tester nên
  tự tạo key free riêng.
- Các file state runtime (`memory_core/`, `long_term_memory.json`, ...) là dữ liệu cá
  nhân của từng lần chạy, không nên commit.
