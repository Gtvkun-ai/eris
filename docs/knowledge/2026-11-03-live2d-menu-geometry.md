# Live2D: menu lệch khỏi model, 03/11/2026

Ảnh user sau lần triển khai clamp overlay/DPI cho thấy menu Godot sát mép trái,
model bên phải. Ảnh thay thế kết luận rằng chỉ clamp rect và bật DPI-awareness
là đủ để xác nhận lỗi hiển thị đã hết. Không có tọa độ packet lúc chụp ảnh để
khẳng định duy nhất một nguyên nhân. Khi kiểm tra, Eris không còn chạy.

Source trước sửa dùng phép trừ WindowGetPosition cho desktop→viewport, bỏ qua
viewport scale; menu dùng Position dù parent Control có offset; chiều rộng panel
212 không chứa hết nút Learning Canvas. Source mới dùng screen transform của
viewport cho menu/anchor/bubble/hit-test và chiều ngược lại khi di chuyển model.
Menu dùng global canvas position, tính cả minimum width của nội dung. Request
menu có con trỏ ngoài rect model dùng neo trong model, tránh clamp về mép xa.
Log `[Live2D] Context menu:` ghi cursor, screen, viewport, menu và rect model.

Kiểm chứng offline: C# Debug build 0 warning/error; 7 test Python position/menu/
geometry pass ngoài sandbox (2 test UDP timeout trong sandbox). Fixture Godot
`tools/ui-preview/live2d_geometry_preview.tscn` pass 6 ca: scale 1/1.25/1.5,
con trỏ hợp lệ và lệch khỏi model, parent offset, minimum width và body anchor.
Fixture không gọi backend/TTS; cần đặt Window.Size rõ ràng khi chạy headless.
Đã export Debug tới Documents/eris, DLL đích trùng SHA-256 với ExportDebug.
Chưa xác nhận trực quan bản mới trên cấu hình hai màn hình/DPI của user.

## Bổ sung: menu hiện đúng nhưng không bấm được

Ảnh tiếp theo của user cho thấy menu chồng lên model; lần kiểm tra vị trí trước
không chứng minh input native đi tới nút. Đã thêm protocol control gửi từng rect
UI Godot theo pixel desktop (50 ms, gửi lại cả khi không đổi để chịu mất UDP).
Renderer nhường mouse trong các rect này trước model hit-test; stale press vào
UI cũng được replay thay vì bị model giữ. Đóng panel gửi danh sách mới/rỗng,
trả quyền tương tác model. Không gộp rect để tránh vô hiệu hóa khoảng trống.

35 test Python pass, bỏ đúng test chat-panel đã biết lỗi; ba test mới kiểm rect
âm/clear, UI chồng model và stale-press replay. Fixture Godot bổ sung cả chuỗi
mouse move/down/up qua GUI + _Input/_UnhandledInput thật: mỗi ca phát đúng một
Pressed và điểm nút được nhận diện là vùng capture Godot. Chưa xác nhận click
vật lý xuyên hai cửa sổ trên cấu hình màn hình của user.

## Đính chính 03/11 (chiều): capture path dùng screen transform gây click xuyên

User báo tiếp: không bấm được nút thanh điều khiển, không chuột phải vào body,
và run_eris.bat mở ra UI 2D thay vì Live2D. Đối chiếu log bản export
(`eris_run_20261103_122110.txt`) và source hiện tại:

- **Mở ra 2D là đúng theo thiết kế, không phải lỗi render.** File
  `%APPDATA%/Godot/app_userdata/Eris/body_renderer_mode.txt` = `2d` nên app
  không tự khôi phục Live2D. Log phiên đó không có dòng `[Live2D]`/`[BodyMode]`:
  Live2D chưa từng bật. Giá trị `2d` do lần trước ghi (Chuyển về 2D hoặc renderer
  thoát → `HandleLive2DProcessExited` ghi "2d").

- **Nguyên nhân click xuyên:** `UpdateMousePassthrough` (WIP) đổi tọa độ chuột
  so panel sang `Live2DScreenToViewport(screenMouse)` =
  `GetViewport().GetScreenTransform().AffineInverse() * screenMouse`. Trên nhánh
  Windows, điểm chuột này được so với `control.GetGlobalRect()` trong
  `IsMouseOverInteractiveOverlay`. Khi screen transform chưa hợp lệ lúc khởi tạo
  hoặc gồm transform canvas, điểm rơi ngoài mọi panel → `mustCapture=false` →
  `WS_EX_TRANSPARENT` giữ bật → click và chuột phải xuyên qua cả nút lẫn body.
  Fixture WIP đặt `Window.Size` headless và không chạy qua nhánh
  `ApplyWindowsGlobalMousePassthrough`, nên không bắt được lỗi này.

- **Đã sửa:** hoàn nguyên riêng tọa độ chuột của capture path về
  `screenMouse - DisplayServer.WindowGetPosition()` (đã kiểm chứng khớp
  `GetGlobalRect()` trước WIP). Giữ nguyên `Live2DScreenToViewport` cho phần đặt
  menu/anchor/bubble Live2D. C# Debug build 0 error/0 warning;
  `test_live2d_body_switch.py` 32 pass, 1 fail là test cũ không liên quan
  (`HideAllSpeechBubbles` trong `ToggleChatPanel`).

Chưa xác nhận trực quan trên máy hai màn hình/DPI của user; cần re-export Godot
rồi thử bấm nút và chuột phải thật. Đây là đính chính source, không phải xác
nhận live.
