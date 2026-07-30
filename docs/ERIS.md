# ERIS

ERIS là desktop companion hai lớp:
body bằng Godot/C# và runtime bằng Python.
Bản chạy full của ERIS là kiểu export Godot + bundle runtime đi kèm,
không còn phụ thuộc vào Python cài sẵn trên máy tester.

## Bản Full

Trong bản full, layout mục tiêu thường là:

```text
ErisBuild/
  Eris.exe
  Eris.pck
  runtime/
    eris-runtime.exe
    _internal/...
  .env
  config/
    secrets.json
```

Nếu `runtime/eris-runtime.exe` có mặt cạnh `Eris.exe`, body sẽ ưu tiên chạy
runtime bundle đó. Nếu không có, body mới fallback sang Python dev-mode.

## Khởi Động

### Body

Body là lớp hiển thị và điều khiển:

- render nhân vật, bubble, overlay
- nhận chat và event từ runtime
- phát animation, motion, audio
- quản lý settings, memory, tutor và maintenance UI
- bật/tắt Live2D body mode

Các phần chính nằm trong `body/`, scene gốc khai báo ở `project.godot`.

### Runtime

Runtime là bộ điều phối nhận thức.
Entry hiện tại ở `vision.py` ở root repo; trong layout dev/build cũ,
`ErisProcessManager` vẫn có đường fallback tới `src/vision.py`.

Runtime khởi tạo:

- `RemoteModelProcessManager`
- `LlmService`
- `MemoryCognitionCore`
- `DecisionParser`
- `TelemetryService`
- `ActionRouter` và `ActionExecutor`
- TTS engine
- `RuntimeCoordinator`

Khi body chạy, `ErisProcessManager` sẽ:

1. tìm `runtime/eris-runtime.exe`
2. nếu có thì chạy binary bundle
3. nếu không thì chạy Python script
4. inject env, secrets và path runtime

## Luồng Chạy

1. Người dùng tương tác với body.
2. Body gửi event qua UDP sang runtime.
3. Runtime thu telemetry, memory và context.
4. `LlmService` tạo phản hồi hoặc quyết định.
5. `DecisionParser` chuẩn hóa output.
6. `RuntimeCoordinator` gửi `Decision` về body.
7. Body hiển thị thoại, animation, motion hoặc event tương ứng.

## Kênh Giao Tiếp

- `4242`: runtime -> body
- `4243`: body -> runtime
- `4252`: lane riêng cho Live2D stage mirror
- `6011`: DS2API / Whale2API daemon nếu bật

## Live2D

ERIS có nhánh Live2D riêng cho body mode.
Godot forward event `eris.stage` sang lane `4252`, còn renderer Live2D
vẽ model và đẩy yêu cầu context menu về `4242`.

## Cấu Hình

Các file chính:

- `.env`
- `.env.example`
- `config/secrets.json`
- `config/secrets.example.json`
- `src/settings/runtime_settings.json`

`config/secrets.json` là file thực để chứa key.
` .env` có thể override nhiều giá trị runtime.
Không nên commit hai file này.

## Build Full

### 1. Build runtime

```powershell
powershell -ExecutionPolicy Bypass -File build\build_runtime.ps1
```

Script này đóng gói Python runtime bằng PyInstaller sang `dist\eris-runtime\`,
rồi có thể copy sang thư mục export của Godot nếu truyền `-Target`.

### 2. Export body

Mở project bằng Godot 4.6 .NET và export Windows Desktop ra `Eris.exe`.

### 3. Ghép lại

Copy `dist\eris-runtime\` sang cạnh `Eris.exe` dưới tên `runtime\`.

### 4. DS2API tùy chọn

Nếu dùng nhánh DeepSeek Web / DS2API:

```powershell
cd src\tools\whale2api
go build -o whale2api.exe ./cmd/whale2api
```

Runtime có thể tự khởi động daemon này khi `ERIS_DS2API_ENABLED=1`
và file binary tồn tại.

## Chạy

### Chạy full build

- mở `Eris.exe`
- body tự spawn runtime bundle
- runtime tự nhận env và secrets

### Chạy dev

```powershell
python vision.py
```

## Dữ Liệu Chạy

- `memory_core/`: state runtime đang sống
- `logs/`: log theo phiên
- `goal_memory.json`, `goal_profiles.json`: mục tiêu và profile
- `long_term_memory.json`: mảnh nhớ dài hạn

Đây là dữ liệu runtime cục bộ, không nên commit.

## Ghi Nhớ Thực Tế

- ERIS hiện là hệ Windows-first.
- Bản full ưu tiên runtime bundle hơn Python cài sẵn.
- Nếu body hiện lên nhưng không nói, thường là hỏng runtime, thiếu key,
  hoặc UDP 4242/4243 bị chặn.

