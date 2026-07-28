# Đóng gói bản build thử ERIS

ERIS gồm 2 phần: **body** (Godot/C#, export ra .exe) và **runtime** (Python, chạy
như tiến trình con). Bản build thử cần ghép cả hai cạnh nhau.

> Về "mã hoá Python": không có cách mã hoá thật cho code phải chạy trên máy người
> khác. Cách thực tế là **đóng gói bằng PyInstaller** — gom toàn bộ `src/` + thư viện
> + Python interpreter vào một thư mục `runtime/`, source biến thành `.pyc` (khó đọc,
> dựng rào cản, không phải mã hoá tuyệt đối). Muốn bảo vệ mạnh hơn thì dùng Nuitka
> (biên dịch native) — nặng và phức tạp hơn, để nâng cấp sau.

---

## Bố cục thư mục bản build (đích cần đạt)

```
ErisBuild/
  Eris.exe              <- Godot export (body)
  Eris.pck
  runtime/              <- PyInstaller bundle (toàn bộ Python)
    eris-runtime.exe
    _internal/...
  config/
    secrets.json        <- tester tự điền key (KHÔNG kèm sẵn)
```

Khi chạy `Eris.exe` (bản export), `ErisProcessManager` tự dò:
1. Nếu thấy `runtime/eris-runtime.exe` cạnh `Eris.exe` → chạy nó (không cần Python).
2. Nếu không → fallback `python src/vision.py` (chỉ dùng khi chạy trong editor/dev).

Cơ chế chọn nằm ở `body/ErisProcessManager.cs` (`GetRuntimeBaseDir` /
`BundledRuntimeFileName`). Trong editor dùng `res://`; bản export dùng thư mục
chứa `.exe`.

---

## Bước 1 — Đóng gói Python runtime

Yêu cầu: đã cài Python + dependencies của dự án (xem README), cộng PyInstaller.

```powershell
# từ gốc repo, trong venv đã cài requirements
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File build\build_runtime.ps1
```

Kết quả: `dist\eris-runtime\` (có `eris-runtime.exe`).

> Bundle sẽ **nặng (thường > 2GB)** vì kéo theo `torch`/`transformers`. Lần build đầu
> mất vài phút. Nếu muốn nhẹ hơn, cân nhắc bỏ phần embedding cục bộ (dùng remote API
> hoàn toàn) — đây là việc tách riêng, chưa làm trong bản này.

Tự test runtime trước khi ghép vào Godot:
```powershell
$env:ERIS_PROJECT_ROOT = "$PWD"
dist\eris-runtime\eris-runtime.exe
```
Nó nên khởi động và lắng nghe UDP như `python src\vision.py`.

---

## Bước 2 — Export body Godot

1. Mở dự án bằng **Godot 4.6 .NET**.
2. **Project → Export**. Lần đầu cần **Add… → Windows Desktop** và tải export
   template nếu Godot nhắc.
3. Export ra một thư mục riêng, ví dụ `ErisBuild\Eris.exe`.

> Không cần thêm file `.py` vào bộ lọc export của Godot. Python được ship riêng ở
> bước 1 (thư mục `runtime/`), không nằm trong `.pck`.

---

## Bước 3 — Ghép lại

```powershell
# copy runtime cạnh Eris.exe (đổi đường dẫn ErisBuild cho đúng)
powershell -ExecutionPolicy Bypass -File build\build_runtime.ps1 -Target "C:\path\to\ErisBuild"
```
Hoặc copy tay `dist\eris-runtime` → `ErisBuild\runtime`.

Rồi tạo `ErisBuild\config\secrets.json` (xem `config\secrets.example.json`). Mỗi
tester tự điền key free của họ — **không kèm key của bạn vào bản phát hành.**

---

## Bước 4 — Chạy thử

Chạy `ErisBuild\Eris.exe`. Body hiện lên và tự spawn `runtime\eris-runtime.exe`.
Nếu ERIS câm: mở console của `eris-runtime.exe` (spec để `console=True`) xem log key
/ lỗi. Khi phát hành chính thức có thể đổi `console=False` trong `build\eris_runtime.spec`.

---

## Lưu ý / việc còn lại (trung thực)

- **State ghi cạnh app.** Working directory của runtime là thư mục chứa `.exe`, nên
  `memory_core/`, `long_term_memory.json`... sẽ ghi ở đó. C# đã truyền
  `ERIS_PROJECT_ROOT` để Python định vị đúng base dir.
- **Đường dẫn nội bộ Python:** mới chỉ chỉnh `eris_secrets.py` đọc secrets theo
  `ERIS_PROJECT_ROOT`. Nếu module khác suy đường dẫn từ `__file__`, có thể cần
  chỉnh thêm khi gặp lỗi đọc/ghi file lúc chạy bundle. Đây là việc theo sau, cần test
  bundle thật để lộ ra.
- **torch/transformers + PyInstaller** đôi khi thiếu hidden import. Nếu chạy báo
  `ModuleNotFoundError`, thêm tên module vào `hiddenimports` trong
  `build\eris_runtime.spec` rồi build lại.
- Đây là quy trình cho **Windows**. Nền tảng khác cần điều chỉnh.

---

## Bước 5 — Biên dịch DS2API (Whale2API Go Gateway)

Để biên dịch Gateway Web DS2API (`whale2api.exe`):

```powershell
cd src\tools\whale2api
go build -o whale2api.exe ./cmd/whale2api
```

Chi tiết kiến trúc chống Ban Nick, cấu hình `.env` đầy đủ và tài liệu chi tiết xem tại:
👉 [docs/ds2api_architecture_and_config.md](file:///c:/Users/Gtvkun/Documents/GitHub/eris/docs/ds2api_architecture_and_config.md)

