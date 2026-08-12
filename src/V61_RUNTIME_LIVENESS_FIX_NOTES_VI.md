# ERIS V61 — Runtime Liveness & Cognitive Recovery

## Vì sao cần V61

Run log ngày 2026-08-12 cho thấy Eris không chết toàn process, nhưng một số nhánh nhận thức bị lỗi hoặc tự mắc vòng lặp. Kiểu lỗi này nguy hiểm vì bên ngoài chỉ thấy Eris im/ngơ, trong khi log vẫn đầy activity.

Các bệnh được tái hiện từ log thật:

1. **Startup autonomous crash** với `NameError: display_code is not defined`.
2. **Language repair autonomous dùng sai request**: hàm nhận prompt repair nhưng vẫn gửi prompt cũ.
3. **Zombie expression urge**: Surface chặn câu trùng, nhưng urge không được hạ/cooldown nên Neuro cứ chọn lại cùng ý.
4. **Environment semantic wake storm**: cùng một meaning có thể đánh thức autonomous loop nhiều lần trong vài giây.
5. **Semantic reviewer bảo nên im nhưng utility vẫn chọn SPEAK** khi interruption cao và continuity thấp.
6. **Structured environment meaning bị thought cũ lấn át** dù telemetry vừa có evidence mới.
7. **Startup failure không đi vào subsystem health**, khiến process trông “healthy” dù public startup cognition vừa vấp programmer error.

## Sửa gì

### 1. Sửa crash `display_code`

`generate_autonomous_reply()` giờ tạo đầy đủ:

- `display_code`
- `speech_code`
- `display_language`
- `speech_language`

cùng contract với direct chat writer.

### 2. Sửa language retry

Callback `call(..., request_messages=...)` giờ thật sự gửi `request_messages` khi có. Retry ngôn ngữ không còn là “gọi lại y chang rồi hy vọng vũ trụ đổi ý”.

### 3. Chặn zombie urge mà không giả là đã nói

Khi Surface trả `surface_duplicate_recent_utterance`:

- urge tương ứng nhận `surface_blocked_until`;
- giảm strength/freshness;
- tăng `surface_duplicate_blocks`;
- không gọi `note_expressed()` vì chưa có public commit;
- nếu có **evidence mới**, cooldown được mở lại ngay.

Điều này giữ đúng lifecycle: desire vẫn tồn tại, nhưng một wording đã bế tắc không được spam lại toàn cognition.

### 4. Coalesce semantic wake theo meaning

`SemanticEnvironmentWorker` giờ giữ wake signature theo:

- event kinds;
- task hint;
- phase;
- attention level.

Cùng signature trong 3 giây chỉ đánh thức autonomous loop một lần. Telemetry vẫn được cập nhật đầy đủ; chỉ loại wake thừa.

### 5. Executive restraint có lực thật

Khi slow semantic appraisal có confidence tốt, interruption cao và candidate SPEAK có continuity thấp, deterministic Neuro merge thêm một restraint term bounded. Silence cũng nhận bonus tương ứng.

Model vẫn **không chọn action trực tiếp**; nó chỉ cung cấp các measurement bounded. Authority vẫn là local Neuro utility.

### 6. Structured environment meaning được ưu tiên hơn thought cũ

ExpressionUrge giờ đánh dấu `environment_grounded=True` chỉ cho candidate có structured environment provenance đã qua privacy/meaning layer. Candidate này nhận freshness thời gian thực và một priority boost nhỏ để có thể preempt thought cũ.

OCR-only không có cờ này nên không được hưởng ưu tiên.

### 7. Startup health không còn chết âm thầm

Nếu startup autonomous fail:

- ghi `ai_orchestrated.startup` vào `SubsystemHealthRegistry`;
- programmer error như NameError/TypeError/AttributeError được phân loại `PROGRAMMER_ERROR`;
- retry thành công sẽ record recovery;
- retry thất bại chuyển subsystem sang failed.

## Tool kiểm log

Chạy:

```bat
run_v61_log_health_check.bat "duong_dan_den_log.txt"
```

Tool bắt ba kiểu lỗi liveness chính:

- startup programmer error;
- duplicate surface storm không có suppression receipt;
- environment wake storm.

Trên log cũ do user cung cấp, tool báo:

- startup programmer errors: **1**
- duplicate surface blocks: **7**
- suppression receipts: **0**
- environment wakes: **51**, max burst **7/3s**
- PrivateMind busy: **3** (được coi là transient, không phải crash)

## Body duplicate hotfix được giữ lại

Gói V61 cũng giữ sửa V60.1:

- không đóng gói `src/body/*.cs`;
- Body C# chuẩn vẫn ở `<project>/body`;
- fixture C# dưới `src/integration/body_contracts` dùng `.cs.fixture.txt` để compiler không nuốt nhầm;
- có `fix_body_duplicate_compile.bat` để dọn bản `src/body` cũ trên máy một cách có kiểm tra/backup.
