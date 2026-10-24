# Các file bên ngoài quản lý Eris

Đối chiếu source ngày 18/10/2026. Phạm vi: entry point, launcher, manager,
bootstrap, cấu hình và build; không nghiên cứu lại nội bộ từng module.
Đây là đối chiếu checkout, chưa launch/stop/build bất kỳ process nào.

## Chuỗi mở ứng dụng

```mermaid
flowchart TD
    managerBat["run_manager.bat"] --> managerGui["ErisManager.exe hoặc src/manager_gui.py"]
    managerGui -.-> vbsLauncher["run_eris.vbs: launcher bản build"]
    vbsLauncher --> godotApp["Eris.exe: Godot"]
    mainBat["run_eris.bat"] --> godotApp
    mainBat -->|"không có Eris.exe"| pythonEntry["src/vision.py"]
    godotApp --> godotListener["UdpListener.cs: AutoStartVision"]
    godotListener --> processOwner["ErisProcessManager.cs"]
    processOwner -->|"ưu tiên nếu tồn tại"| bundledBrain["runtime/eris-runtime.exe"]
    processOwner -->|"fallback dev"| pythonEntry
    runtimeBat["run_runtime.bat"] --> pythonEntry
    serviceBat["run_eris_service.bat: headless IDE"] --> pythonEntry
```

Hai nhánh từ ErisProcessManager là lựa chọn thay thế, không chạy cả hai.
Nhánh Python của run_eris.bat cũng là fallback khi không có Eris.exe.
Generated VBS có fallback Python tương tự. Khi khởi chạy binary đóng gói,
không suy nó trùng source hiện tại nếu chưa kiểm tra build/provenance.

## Ai quản lý ai

| File | Trách nhiệm cụ thể |
|---|---|
| `run_eris.bat` | Thiết lập interpreter/env/root/cache/state/home, kiểm secrets, mở bridge nếu có, rồi mở Eris.exe hoặc Python backend |
| `run_runtime.bat` | Mở trực tiếp src/vision.py, không mở Godot; env được thiết lập ít hơn run_eris.bat |
| `run_eris_service.bat` | Cùng entry Python nhưng bật VS Code service mode, tắt TTS và nhiều nhánh tự nói/background, dùng settings path riêng |
| `run_manager.bat` | Ưu tiên manager EXE có sẵn, sau đó chạy src/manager_gui.py |
| `src/manager_gui.py` | Tkinter control panel; mở script/EXE/VBS, sửa/cài tài khoản và mở pool UI; không phải vòng lặp chat |
| `src/body/UdpListener.cs` | Startup frontend; auto-start backend, xử lý callback crash và lên lịch restart sau 2 giây nếu bật |
| `src/body/ErisProcessManager.cs` | Sở hữu handle process Brain, start/stop/toggle, truyền environment, thu stdout/stderr và báo exit |
| `src/vision.py` | Entry point và composition root backend: config, single-instance lock, dựng dịch vụ, chạy coordinator và cleanup |
| `src/body/Live2DBodyManager.cs` | Sở hữu process renderer riêng; start/control/stop Live2D, không sở hữu vòng suy nghĩ |
| `eris_setup.py` | CLI setup/doctor/health/dependencies, portable Python, gọi build và một số service phụ |
| `run_doctor.bat` | Gọi eris_setup.py; không chỉ là một kiểm tra read-only tự động |
| `_fullbuild.py` | Copy/package source/runtime assets và sinh launcher cho output; có profile dev/release |
| `_patchbuild.py` | Chuẩn bị gói cập nhật; không phải thành phần chạy chat |

Manager GUI dùng subprocess.Popen để mở công cụ. Không thấy nó theo dõi các
handle đó để làm process supervisor chung. Sở hữu process Brain thuộc C# manager;
restart policy nằm ở UdpListener. Trong eris_setup.py, stop_all chỉ terminate
các process thuộc danh sách _procs mà chính phiên setup đã start.

## src/vision.py nối hệ thống thế nào

```mermaid
flowchart TD
    entryPoint["src/vision.py"] --> configLoad["Logging, secrets, env và single-instance lock"]
    configLoad --> overseer["AttentionOverseer"]
    overseer --> compose["Dựng client, memory, parser, telemetry, action và UDP"]
    compose --> coordinator["RuntimeCoordinator"]
    overseer --> bindTts["Khởi tạo và bind TTS nếu không headless"]
    bindTts --> coordinator
    coordinator --> runLoop["coordinator.run_loop"]
    runLoop --> shutdown["Signal hoặc thoát: stop và nhả lock"]
```

Tên vision.py dễ gây hiểu nhầm: file này bootstrap toàn backend, không chỉ nhìn
màn hình. AttentionOverseer.run_loop chuyển quyền chạy sang coordinator.
AttentionOverseer.stop gọi coordinator.stop, process-manager.stop, TTS shutdown
và cleanup WebAI/DS2API child process do nó đã start. Các daemon là nhánh có điều
kiện: feature flag, file tồn tại và health check; không mặc định mọi service đều bật.

## Các file hỗ trợ bên ngoài

| File | Vai trò |
|---|---|
| `eris_secrets.py` | Chọn secrets path/version, nạp .env, đọc secret/config và materialize env; không cần đọc giá trị key để lập sơ đồ |
| `secret_versions.py` | Manifest active version, stage/activate/rollback secret có kiểm tra |
| `app_logging.py` | Root logger, category, secure redaction và lọc noise |
| `guard_config.py` | Cấu hình chế độ của nhóm guard tương thích; không phải process manager |
| `semantic_authority.py` | Policy semantic authority; đọc RuntimeSettingsStore, không là entry point |
| `failure_meta.py` | Contract/chuẩn hóa metadata lỗi |
| `sender.py` | Công cụ gửi UDP Hello World khi chạy trực tiếp, không bootstrap Eris |
| `setup_secrets.bat` | Tạo secrets.json từ example nếu thiếu rồi mở editor |
| `run_deepseek_pool_ui.bat`, `run_elevenlabs_pool_ui.bat` | Mở UI đã chạy hoặc start service UI tương ứng nếu chưa lên |
| `project.godot`, `Eris.csproj` | Cấu hình frontend Godot và build C# |
| `ErisManager.spec` | PyInstaller entry src/manager_gui.py cho manager EXE |
| `build_dev_fast.bat`, `build_release_clean.bat` | Gọi _fullbuild.py với profile dev/release |
| `run_build.py` | Wrapper gọi _fullbuild.py và tự trả lời prompt; không là runtime launcher |

## Phân biệt bản source và bản build

- Launcher hiện tại và default C# VisionScriptPath đều trỏ src/vision.py.
  Root vision.py có nội dung khác (SHA-256 khác); không xem hai bản là tương đương.
- _fullbuild.py copy cây src và sinh run_eris.bat/run_eris.vbs cho output.
  Vì vậy launcher được sinh trong bản build khác launcher checkout hiện tại.
- Manager action Start Eris hiện trỏ run_eris.vbs. File đó không tồn tại ở root
  checkout lúc kiểm tra; _can_run sẽ báo missing. Build có code sinh file này.
  Không kết luận launcher trong bản portable cũng thiếu file.
- app_logging.py và eris_secrets.py ở root/src đang trùng hash. Không áp điều
  này sang vision.py hoặc mọi helper khác nếu chưa đối chiếu.

Các kết luận trên chỉ cần đọc source và kiểm tra path/hash; không chạy launcher,
không mở secret payload, không rebuild và không thay đổi cấu hình/runtime.
