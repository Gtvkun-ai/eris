# ERIS

ERIS là một hiện diện desktop (desktop companion) chạy trên Godot: phần thân (body)
vẽ bằng Godot/C#, phần nhận thức (cortex/runtime) viết bằng Python. Body và runtime
nói chuyện với nhau qua UDP. Cognition dùng các model qua API miễn phí (Gemini / Groq),
có cÆ¡ chế **xoay vòng nhiều key** để tận dụng free quota.

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

### 2.4. Model runtime

Local inference backends have been removed. ERIS now uses remote providers for the main brain, private-mind fragment lanes, vision API, tutor helpers, and style/interoception.


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
- Key DeepSeek Web riêng cho surface/autonomous micro-line: `api_keys.ERIS_DS_SURFACE_API_KEY`

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
- Nếu gá»­i build cho người khác, tuyệt đối không kèm file key của bạn; mỗi tester nên
  tự tạo key free riêng.
- Các file state runtime (`memory_core/`, `long_term_memory.json`, ...) là dữ liệu cá
  nhân của từng lần chạy, không nên commit.

---

## 8. Curiosity Tutor (gia sư web — tùy chọn, mặc định TẮT)

ERIS có thể tự "đi hỏi gia sư" khi gặp lỗ hiểu biết: khi một vi phạm kỳ vọng
(`SituationModel`) hoặc một tình huống màn hình không phân loại được xuất hiện, ERIS hình
thành câu hỏi (bằng **local LLM**), **mở một cửa sổ trình duyệt thật** tới
`gemini.google.com` bằng tài khoản Google đăng nhập sẵn, gõ câu hỏi như người, rồi chưng
cất câu trả lời thành claim đưa vào trí nhớ ngữ nghĩa. Đôi khi ERIS sẽ tự nhiên "khoe"
điều vừa học bằng giọng của chính nó (có tiết chế). Toàn bộ chạy ngoài hot path.

> ⚠️ **Rủi ro cần biết.** Tự động hóa tài khoản Google tiêu dùng **vi phạm ToS của
> Google** và tài khoản **có thể bị khóa**. Cửa sổ Gemini thật có thể **lộ email/tab
> khác** trên màn hình. Mặc định tính năng **TẮT**; chỉ bật nếu bạn chấp nhận rủi ro này.

### 8.1. Cài Playwright (chỉ khi dùng Tutor)
```powershell
pip install playwright
playwright install chromium
```

### 8.2. Đăng nhập profile một lần (bằng tay) — BẮT BUỘC
Đã có sẵn script. Chạy **một lần**:
```powershell
python tutor_login.py
```
Cửa sổ Chromium mở `gemini.google.com` với profile bền vững
(`C:\Users\Gtvkun\Documents\eris_tutor_profile`). Đăng nhập Google trong cửa sổ đó, rồi
quay lại terminal nhấn Enter để lưu phiên. Từ đó ERIS dùng lại phiên này.

> Nếu chưa đăng nhập, lượt hỏi đầu sẽ thấy màn login/captcha → Tutor **tạm ngưng** (không
> tự vượt) cho tới khi bạn đăng nhập tay; nó không spam tài khoản.

### 8.3. Bật trong `.env`
```dotenv
ERIS_TUTOR_ENABLED=1
ERIS_TUTOR_PROFILE_DIR=C:\eris_tutor_profile
ERIS_TUTOR_USE_REMOTE_LLM=1
```
Các tinh chỉnh khác (nhịp hỏi, trần/giờ, selector, tần suất khoe) xem `.env.example`.

### 8.4. Lưu việc lưu claim
Mặc định ERIS sẽ **hỏi + diễn cảnh** nhưng **chưa lưu claim** cho tới khi đường commit
vào trí nhớ được nối (adapter `tutor_ingest_fn`). Đây là bước cố tình để ngỏ vì ghi vào
trí nhớ dài hạn là thao tác nhạy cảm — gắn một callable `tutor_ingest_fn(text, *, source,
gap_id, citations) -> int` lên runtime để bật lưu claim.
