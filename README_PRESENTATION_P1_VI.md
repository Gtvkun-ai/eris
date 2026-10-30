# Eris Presentation P1 — nối Artifact sang Rich Chat (29/10/2026)

## Dùng luôn, KHÔNG cấu hình

1. Giải nén bản đầy đủ vào một thư mục riêng.
2. Build lại Eris với `build_dev_fast.bat` / quy trình Godot C# sẵn có.
3. Mở Eris → Rich Chat. Khi Root tạo `document_source` hoặc dùng `math_workspace`, Rich Chat tự nạp các artifact mới và render bên dưới câu trả lời hoặc trong mục “Bàn làm việc · kết quả công cụ”.

**Không cần bật biến môi trường.** P0 đã bật mặc định, P1 chạy cùng vòng cập nhật giao diện Godot, không thêm Agent Loop. Chat/TTS/Workspace cũ giữ nguyên.

## Đã hoạt động trong source

- Godot đọc JSON sidecar từ `logs/eris_artifacts/presentation_v1` (giới hạn kích thước/số lượng; không đọc file tạm).
- Đính artifact vào đúng `turn_id` của tin assistant; job thiếu `turn_id` thật chỉ hiện trong khu riêng, **không tự đoán** lượt chat.
- Renderer HTML an toàn cho Markdown, LaTeX (MathJax), code, bảng và đồ thị đơn giản. Ảnh PNG artifact chỉ được mở khi ở trong workspace và SHA-256 trùng.
- Trình duyệt gửi `renderer.feedback.v1` về API trên `127.0.0.1` có token; server kiểm tra đúng intent/artifact/revision rồi lưu ACK ở `presentation_v1/feedback/`.
- Root đọc tối đa vài ACK gần đây trong context ở lượt kế tiếp; không thêm thread, không có AI polling. `rendered` chỉ là xác nhận trình duyệt đã dựng DOM/MathJax, KHÔNG xác nhận toán đúng hoặc người dùng đã đọc.

## Đã kiểm thử

- Python: `PYTHONPATH=src python -m pytest -q src/tests/test_p0_artifact_protocol.py src/tests/test_p1_presentation_feedback.py src/tests/test_p1_richchat_renderer.py`
- Đã kiểm tra trình duyệt Chromium trên fixture (math, code, table, document, provisional gallery, 5 feedback ACK).
- Chưa build/chạy EXE Godot trên Windows trong môi trường này. Đầu nối C# cần xác nhận bằng build thật trước khi kết luận end-to-end đạt.

## Còn thuộc P2

- Root chọn kênh artifact một cách thống nhất ngay trong `PresentationIntent` và điều phối hàng đợi/huỷ theo revision hiện hành. P1 vẫn dựa trên `document_source` và các tool có sẵn, không thêm một engine tự ý quyết định thay Root.
