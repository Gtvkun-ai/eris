# Eris

Eris là dự án companion/runtime chạy cục bộ trên Windows. Phần body dùng Godot 4 .NET; phần cognition dùng Python để xử lý chat, nhận biết màn hình, memory, gọi model, TTS, công cụ nền và các luồng chủ động.

Python giữ vai trò runtime chính. Godot hiển thị body và nhận lệnh qua UDP nội bộ.

## Tổng Quan

- `project.godot`, `Eris.sln`, `body/`: dự án Godot/C# cho body UI.
- `src/vision.py`: entrypoint chính của runtime Python.
- `src/runtime/`: coordinator, settings, orchestration, TTS, chess, engagement và background services.
- `src/memory/`: engine memory và các lớp persistence.
- `src/llm/`: client model, router, repair và lớp ổn định request.
- `src/actions/`: registry và executor cho các hành động desktop/tool.
- `src/tools/`: tool đi kèm như Whale2API và ElevenLabs helper.
- `browser_extension/`: bridge trình duyệt.
- `tests/`, `src/tests/`: bộ kiểm thử hồi quy.

Memory, log, báo cáo kiểm thử và kết quả build là dữ liệu sinh ra khi chạy, không phải source. Sau khi dọn sạch, `memory_core/` chỉ nên còn `.gdignore`.

## Yêu Cầu

- Windows
- Python 3.12 trở lên
- Godot 4.6 .NET
- Git
- Tùy chọn: Playwright Chromium cho tutor/browser workflow

Gói phụ thuộc Python chính nằm trong `requirements.txt`. Gói phụ thuộc riêng cho Live2D nằm trong `src/requirements-live2d.txt`.

## Cài Đặt

Tạo virtualenv và cài gói phụ thuộc:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tạo file cấu hình local:

```powershell
Copy-Item .env.example .env
```

Điền các key/model cần dùng trong `.env`. Một số biến thường gặp:

- `ERIS_REMOTE_API_ENABLED`
- `ERIS_REMOTE_PROVIDER`
- `ERIS_REMOTE_MODEL`
- `ERIS_REMOTE_API_KEY` hoặc key theo provider như `GEMINI_API_KEY`
- `ERIS_DS2API_ENABLED`
- `ERIS_DS2API_BASE_URL`
- `ERIS_DS2API_API_KEY`
- `ERIS_TTS_ENABLED`
- `ERIS_SPEECH_API_KEY`
- `ERIS_HOME`

Không commit `.env`, API key, DB runtime, memory dump, log hoặc kết quả build.

## Chạy

Chạy runtime Python:

```powershell
.\run_runtime.bat
```

Mở `project.godot` bằng Godot và chạy main scene để bật body UI.

UDP mặc định:

- runtime gửi tới `127.0.0.1:4242`
- runtime nhận từ `127.0.0.1:4243`

## Tutor Và Browser

Cài Playwright Chromium:

```powershell
.\setup_tutor_browser.bat
```

Chạy helper đăng nhập:

```powershell
.\tutor_login.bat
```

## ElevenLabs Pool UI

Mở control panel ElevenLabs pool:

```powershell
.\run_elevenlabs_pool_ui.bat
```

Địa chỉ local:

```text
http://127.0.0.1:18888
```

## Memory

Mặc định runtime state sống ngoài repo tại:

```text
%USERPROFILE%\Documents\ErisLive
```

Có thể đổi bằng:

```powershell
$env:ERIS_HOME="D:\path\to\ErisLive"
```

Memory runtime nằm ở:

```text
<ERIS_HOME>\memory\core
```

Muốn reset memory thì tắt Eris rồi xóa file sinh ra trong folder đó. Không xóa `src/memory/` khi chỉ muốn reset memory, vì đó là source engine.

## Kiểm Thử

Chạy toàn bộ kiểm thử:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --tb=line -q --no-header
```

Chạy qua trình chạy kiểm thử của dự án:

```powershell
.\.venv\Scripts\python.exe run_tests.py
```

Chạy hồ sơ kiểm thử humanness:

```powershell
.\.venv\Scripts\python.exe run_tests.py humanness
```

In bản ghi humanness:

```powershell
.\.venv\Scripts\python.exe run_tests.py humanness-talk
```

## Build

Build bằng script một lệnh:

```powershell
.\.venv\Scripts\python.exe _fullbuild.py
```

Script copy và compile runtime sang:

```text
C:\Users\Gtvkun\Documents\eris
```

Luôn dùng Python trong `.venv` khi build. Trộn phiên bản Python dễ tạo `.pyc` không tương thích.

## Quy Ước Dọn Dẹp

Các mục sau là dữ liệu local/generated và không nên commit:

- `.venv/`
- `.godot/`
- `.kiro/`
- `.dotnet/`
- `.vs/`
- `.pytest_cache/`
- `__pycache__/`
- `dist/`
- `build/_work/`
- log, báo cáo kiểm thử và trạng thái memory

Source nên chỉ giữ code, mẫu cấu hình, asset cần thiết và kiểm thử.
