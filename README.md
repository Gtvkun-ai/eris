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
- `src/tools/`: công cụ đi kèm như Whale2API và ElevenLabs helper.
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

Nếu dùng semantic memory bằng embedding thật, cài thêm `torch` và `transformers`:

```powershell
.\.venv\Scripts\python.exe -m pip install torch transformers
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

## Các File `.bat`

Các file `.bat` trong root là launcher nhanh cho Windows:

- `run_runtime.bat`: chạy runtime Python chính qua `.venv\Scripts\python.exe`, fallback sang `python` nếu chưa có venv.
- `setup_tutor_browser.bat`: cài Playwright package và Chromium. Chạy một lần trước khi dùng tutor/browser.
- `tutor_login.bat`: mở helper đăng nhập browser sau khi đã setup Playwright.
- `run_elevenlabs_pool_ui.bat`: mở giao diện quản lý ElevenLabs pool tại `http://127.0.0.1:18888`.

Thứ tự setup máy mới thường là:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Expand-Archive .\eris-assets-tools-embedding.zip -DestinationPath . -Force
.\setup_tutor_browser.bat
.\run_elevenlabs_pool_ui.bat
.\run_runtime.bat
```

## Tutor Và Browser

Cài Playwright Chromium:

```powershell
.\setup_tutor_browser.bat
```

Chạy helper đăng nhập:

```powershell
.\tutor_login.bat
```

## Công Cụ Phụ

Một số công cụ trong repo này đã được chỉnh riêng cho Eris, nên không nên cài bằng hướng dẫn upstream rồi coi là tương đương. Cách khuyến nghị là dùng gói assets đi kèm project.

`tools\` hiện là junction trỏ tới `src\tools\`. Hai đường dẫn đó là cùng một cây nội dung, không phải hai bản tool độc lập.

Binary, cache và model nặng không đưa vào Git. Sau khi clone source, tải gói assets tại:

```text
https://pixeldrain.com/u/mBDHhG2F
```

Giải nén gói đó vào root repo và paste đè toàn bộ file/folder nếu Windows hỏi:

```powershell
Expand-Archive .\eris-assets-tools-embedding.zip -DestinationPath . -Force
```

Nếu giải nén bằng Explorer/WinRAR/7-Zip: mở zip, kéo toàn bộ nội dung vào thư mục repo Eris, chọn Replace/Overwrite/Merge để paste đè.

Sau khi giải nén, các path này phải tồn tại:

```powershell
Test-Path src\embedding_model
Test-Path tools\whale2api\whale2api.exe
Test-Path tools\whale2api\poolui.exe
```

Gói assets không chứa key, account pool, `.env`, DB runtime hay memory. Các phần đó vẫn phải cấu hình riêng trên từng máy.

### Whale2API / DS2API

Runtime tự bật DS2API khi `ERIS_DS2API_ENABLED=1` và tìm thấy `tools\whale2api\whale2api.exe`. Sau khi giải nén gói assets, cấu hình `.env` của repo chính:

```text
ERIS_DS2API_ENABLED=1
ERIS_DS2API_PORTS=6011,6012,6013,6014
ERIS_DS2API_API_KEY=<gateway-key>
ERIS_DS_BASE_URL=http://127.0.0.1:6011/v1
```

Khi runtime chạy, nó sẽ dùng lại port đã có server hoặc tự spawn `whale2api.exe` cho từng port trong `ERIS_DS2API_PORTS`. Muốn kiểm tra thủ công:

```powershell
Invoke-RestMethod http://127.0.0.1:6011/v1/models
```

Nếu không dùng gói assets thì mới build lại từ source trong repo:

```powershell
cd tools\whale2api
go mod download
go build -o whale2api.exe .\cmd\whale2api
go build -o poolui.exe .\cmd\poolui
cd ..\..
```

Không thay bằng binary upstream khác, vì bản này có chỉnh riêng cho lane DS2API, endpoint, schema, pool DB và hành vi stream của Eris.

### Stockfish

Stockfish là tùy chọn cho phân tích cờ. Nếu không có binary, hệ thống fallback sang engine nội bộ.

Không cần cài thư viện Python cho Stockfish. Chỉ cần UCI binary. Đặt `stockfish.exe` tại:

```text
tools\stockfish\stockfish.exe
```

Hoặc cấu hình đường dẫn rõ ràng:

```text
ERIS_STOCKFISH_PATH=C:\path\to\stockfish.exe
```

Các biến tinh chỉnh thường dùng:

```text
ERIS_STOCKFISH_THREADS=1
ERIS_STOCKFISH_HASH_MB=96
ERIS_STOCKFISH_MULTIPV=3
ERIS_STOCKFISH_MOVETIME_MS=180
ERIS_STOCKFISH_ON_DEMAND_MOVETIME_MS=700
```

### Mô Hình Embedding

Embedding model nằm trong gói assets. Sau khi giải nén, thư mục này phải có dữ liệu:

```text
src\embedding_model
```

Cấu hình đề xuất:

```text
ERIS_EMBEDDING_ENABLED=1
ERIS_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
ERIS_EMBEDDING_CACHE_DIR=src\embedding_model
ERIS_EMBEDDING_MAX_LENGTH=512
ERIS_EMBEDDING_POOLING=auto
```

Nếu máy chưa cài `torch`/`transformers`, hoặc không muốn dùng embedding, tắt bằng:

```text
ERIS_EMBEDDING_ENABLED=0
```

Khi đó recall vẫn chạy bằng tìm kiếm từ khóa dự phòng, chỉ kém tìm kiếm ngữ nghĩa hơn.

## ElevenLabs Pool UI

`run_elevenlabs_pool_ui.bat` là giao diện quản lý pool TTS ElevenLabs của Eris. Nó khác với `poolui.exe` của Whale2API.

Mở giao diện:

```powershell
.\run_elevenlabs_pool_ui.bat
```

Địa chỉ local:

```text
http://127.0.0.1:18888
```

Giữ cửa sổ `.bat` mở khi đang dùng UI. Nếu port mặc định bận, đổi port bằng:

```powershell
$env:ERIS_ELEVENLABS_POOL_PORT="18889"
.\run_elevenlabs_pool_ui.bat
```

### Cấu Hình ElevenLabs Pool

Pool cần `FIREBASE_API_KEY` để đổi ElevenLabs refresh token thành bearer token tạm thời. Có thể đặt trong `.env` hoặc `config\secrets.json`:

```text
FIREBASE_API_KEY=<firebase-api-key-cua-elevenlabs-web>
ERIS_TTS_PROVIDER=elevenlabs
ERIS_ELEVENLABS_VOICE_ID=<voice-id>
ERIS_ELEVENLABS_MODEL=eleven_v3
```

Nếu không dùng pool, runtime vẫn có thể dùng key đơn:

```text
ELEVENLABS_API_KEY=<xi-api-key>
```

Nhưng khi pool đã có account, TTS sẽ ưu tiên account trong pool để xoay quota. Nếu pool có account nhưng tất cả hết quota/disabled, runtime sẽ không tự quay về key đơn để tránh dùng nhầm account vừa bị loại.

### Lấy `FIREBASE_API_KEY` Và Refresh Token

`FIREBASE_API_KEY` là key web Firebase mà ElevenLabs dùng để refresh phiên đăng nhập. Cách lấy thường dùng:

1. Đăng nhập `elevenlabs.io` trên trình duyệt.
2. Mở DevTools.
3. Tìm request tới `securetoken.googleapis.com/v1/token?key=...`.
4. Copy giá trị sau `key=` vào `FIREBASE_API_KEY`.

Refresh token là token phiên của account ElevenLabs. Cách lấy thường dùng:

1. Đăng nhập account ElevenLabs cần đưa vào pool.
2. Mở DevTools, tab Application/Storage hoặc Network.
3. Tìm trường `refreshToken` hoặc request refresh token của Firebase.
4. Copy refresh token đó.
5. Mở `http://127.0.0.1:18888`, bấm `Thêm Refresh Token`, dán token vào ô token.

UI cho phép dán nhiều refresh token cùng lúc, mỗi token một dòng. Khi bấm lưu, server sẽ tự sync quota; nếu lỗi `Thiếu FIREBASE_API_KEY` thì kiểm tra lại `.env`/`config\secrets.json`.

Refresh token và DB pool là dữ liệu nhạy cảm. Không đưa vào Git, không bỏ vào zip public, không gửi cho người khác.

### File Pool ElevenLabs

File pool thật nằm ở:

```text
config\elevenlabs_pool.db
```

File này chứa refresh token/bearer token đã lưu. Muốn chuyển pool sang máy khác thì copy riêng file này vào đúng đường dẫn trên máy đích sau khi đã clone source và giải nén assets.

Muốn reset pool:

1. Tắt `run_elevenlabs_pool_ui.bat` và runtime.
2. Xóa `config\elevenlabs_pool.db`.
3. Mở lại `run_elevenlabs_pool_ui.bat`.
4. Thêm refresh token lại từ UI.

Các thao tác trong UI:

- `Thêm Refresh Token`: thêm một hoặc nhiều account.
- `Làm Mới`: tải lại danh sách và thống kê quota.
- `Sync`: đồng bộ quota account đó từ ElevenLabs.
- `Tắt/Bật`: loại account khỏi vòng xoay hoặc bật lại.
- `Xóa`: xóa account khỏi pool.

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
