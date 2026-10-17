BẢN CẬP NHẬT UI ERIS — 17/10/2026

Đây là gói các file đã thêm/sửa, không phải ứng dụng standalone.

1. Giải nén vào thư mục gốc dự án Eris, cùng cấp project.godot.
2. Cho phép thay thế src/body/UdpListener.cs và
   src/body/UdpListener.ConversationUi.cs. Các file còn lại là file mới.
3. Chạy dotnet build Eris.csproj bằng môi trường Godot .NET của dự án.
4. Mở tools/ui-preview/companion_preview.tscn trong Godot .NET 4.7.2,
   nhấn F6 để xem UI độc lập. Scene dùng dữ liệu minh họa, không ghi dữ
   liệu người dùng hoặc gọi backend.

run_ui_preview.bat sử dụng Godot đã tải ở scratch/ui-qa/godot trên máy
làm việc này. Engine không nằm trong ZIP vì không phải file mã nguồn
thay đổi. Nếu máy đích không có đường dẫn đó, dùng cách mở scene ở bước 4.

Ảnh UI và log kiểm tra nằm trong docs/ui/. Xem hướng dẫn đầy đủ tại
docs/ui/companion-workspace.md.

Gói không chứa .env, secrets, dữ liệu người dùng, build cache hoặc engine.
Scene desktop đầy đủ vẫn cần thư mục asset/ của dự án gốc; snapshot đang
làm việc thiếu thư mục này. Scene xem trước UI không cần asset/ đó.

ERIS_UI_PATCH_SHA256.txt ghi SHA-256 từng file trong gói.
