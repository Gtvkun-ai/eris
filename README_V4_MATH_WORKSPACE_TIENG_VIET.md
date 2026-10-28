# ERIS V4 Experimental — Sandbox, Math Engine & Artifact Workspace

> Đây là bản R&D tích hợp tiếp từ Eris V3. Các thành phần được chạy thử trực tiếp; không gọi đây là bản production hoàn chỉnh.

## 1. Đã làm thật

- Đã thêm `math_workspace` vào public capability registry, ActionExecutor và hợp đồng đối số. Root/Executive khi chọn capability này sẽ đi qua đường action hiện có. Handler không tự phát speech.
- Tính toán ma trận (tối đa 8×8), định thức, hạng, đạo hàm, tích phân, giải phương trình một biến, vẽ đồ thị hàm một biến bằng SymPy, NumPy và Matplotlib thực sự.
- Toán được thực hiện ở subprocess với thời gian/tài nguyên hữu hạn, qua `SandboxWorld.RUN_COMMAND`, không eval hoặc exec văn bản bất kỳ do model đưa vào trong math worker.
- Artifact phát qua `parse_mode=workspace_artifact`, tách khỏi Bubble, TTS và lọc chuỗi thoại. Đầu ra PNG kèm SHA-256, JSON kèm LaTeX thô, bảng, code.
- UI Godot `UdpListener.ArtifactWorkspace.cs`: tự mở bàn làm việc, hiển thị ảnh PNG đã kiểm hash, code, bảng, chữ và công thức đã rasterize qua mathtext.
- Công cụ `python_workspace`: có đường chạy Python tùy ý trong Docker: không mạng, file code chỉ đọc, ảnh và stdout ra thư mục artifact. Không fallback sang host Python nếu Docker thiếu.
- `tools/math_workspace_probe.py` chạy 3 bài thật (ma trận, đạo hàm, đồ thị). 

## 2. Cài đặt

Trong PowerShell, mở thư mục gốc Eris:

```powershell
py -m pip install -r requirements-artifact-workspace.txt
$env:PYTHONPATH="src;."
python tools/math_workspace_probe.py
```

Để gửi artifact và tự mở Panel trên Godot đang chạy:

```powershell
$env:ERIS_ARTIFACT_WORKSPACE="$(Get-Location)\logs\eris_artifacts"
python tools/math_workspace_probe.py --send
```

Với Godot .NET, mở project rồi build C# theo workflow của dự án. Nếu build thành công, Python gửi UDP `127.0.0.1:4242`, UI mở panel bên cạnh avatar. Không cần đưa LaTeX vào Bubble.

**Lưu ý:** Thư mục `ERIS_ARTIFACT_WORKSPACE` phải là cùng một thư mục được nhìn thấy từ tiến trình Python và tiến trình Godot. Nếu chạy từ thư mục khác, hãy đặt biến môi trường **trước khi chạy cả hai**.

## 3. Dùng làm tool của Eris

- `math_workspace` nhận đối tượng JSON:

```json
{"kind":"plot", "expression":"x^2-2", "xmin":-5, "xmax":5, "title":"Parabol"}
```

- Ma trận:

```json
{"kind":"matrix", "rows":[[1,2],[3,4]], "title":"Tính định thức"}
```

- Các tác vụ hợp lệ: `simplify`, `differentiate`, `integrate`, `solve`, `plot`, `matrix`.
- `python_workspace` nhận `{"code":"print(2+2)"}` và **yêu cầu cài Docker Engine/ Docker Desktop hoạt động**. Image mặc định `python:3.12-slim` chỉ chứa thư viện chuẩn. Để có NumPy/SymPy trong container code tự do, bạn cần một image đã cài các gói này và đặt `ERIS_ARTIFACT_DOCKER_IMAGE`.

## 4. Test

```powershell
$env:PYTHONPATH="src;."
python -m pytest -q src/tests/workspace/test_math_workspace_v4.py src/tests/world/test_sandbox_world.py src/tests/world/test_sandbox_hardening_v3.py src/tests/world/test_native_sandbox.py
```

## 5. Trạng thái đã kiểm chứng / chưa kiểm chứng

| Hạng mục | Trạng thái |
|---|---|
| Math worker tạo PNG + kết quả chính xác | Đã chạy thật ở môi trường kiểm thử |
| Tool qua ActionExecutor tạo artifact và receipt | Đã chạy test trực tiếp với handler |
| Python Docker không fallback sang host | Đã test đường từ chối khi thiếu Docker |
| Chạy container Docker thật | Chưa test vì môi trường này không có Docker |
| Godot C# build, Panel hiện đúng trên máy Windows | Chưa xác nhận, thiếu Godot/.NET SDK trong môi trường này |
| Full LaTeX/KaTeX | Chưa. Mathtext dựng được một tập công thức; LaTeX khác được lưu dạng chữ |
| Đồ thị tương tác kéo tham số, zoom/pan bằng dữ liệu thật | Chưa. V4 tạo ảnh đồ thị tĩnh |
| LLM tự chọn công cụ toán trong phiên live | Chưa đo; registry + ActionExecutor đã nối nhưng cần log/trace chạy live |
| Chạy code không tin cậy trên Windows không có Docker | Không hỗ trợ, không fallback thiếu cách ly |

## 6. Thành phần thay đổi

- `src/runtime/workspace/math_worker.py` — tiến trình toán.
- `src/runtime/workspace/math_artifacts.py` — gọi SandboxWorld và chuẩn hóa artifact.
- `src/runtime/workspace/python_docker.py` — Python container.
- `src/body/UdpListener.ArtifactWorkspace.cs` — UI Godot.
- `src/body/UdpListener.cs` — route `workspace_artifact` trước parser hội thoại.
- `src/actions/capability_registry.py`, `contracts.py`, `executor.py`, `capability_runtime.py` — tool discovery và dispatch.
- `src/tests/workspace/test_math_workspace_v4.py`, `tools/math_workspace_probe.py`.

## 7. Giới hạn thử nghiệm quan trọng

- Chạy worker SymPy trong subprocess với RLIMIT khi trên POSIX; đây **không phải** cách ly OS đầy đủ. Worker chỉ cho phép cây phép toán toán học từ AST whitelist, không cho model gửi mã Python tùy ý qua `math_workspace`.
- Docker sandbox mất mạng và giảm quyền, nhưng volume output hiện chưa có quota đĩa riêng. Chỉ chạy nội dung đáng tin vừa phải trên máy R&D, và kiểm tra hạn mức Docker trước khi mở cho quy mô lớn.
- Hiện artifact mới nhất lưu thành job trong workspace; chưa có editor tương tác dạng Jupyter hoặc đồ thị slider tự động tạo động.
- Root/Executive vẫn là nơi quyết định khi nào chọn công cụ. Không tạo thêm một Agent Loop cạnh tranh với Identity.
