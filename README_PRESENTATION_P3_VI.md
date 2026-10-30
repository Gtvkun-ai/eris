# P3 — Presentation feedback, validation và phục hồi (bật sẵn)

- Browser chỉ ACK rendered khi artifact có DOM thật; công thức đã được MathJax dựng, ảnh đã tải thành công. Ảnh lỗi hoặc MathJax lỗi trả `E_RENDER`.
- Giới hạn tự thử lại render: tối đa 3 lần, giãn cách 5 giây, dùng polling UI hiện có; không tạo thêm agent loop/LLM.
- Godot chỉ nhận ACK đúng artifact/revision đang phục vụ, lưu bằng ghi file nguyên tử, khóa chống race; ACK `rendered` không bị downgrade bởi `failed` muộn.
- Root nhìn `presentation_health`: `awaiting_viewer`, `rendered`, `failed`. Không xem thiếu ACK là lỗi. Nếu thất bại, Root có thể đổi nội dung/công cụ **khi phù hợp lượt hiện hành**; không tự phát lời thoại cũ.
- Đã giữ P0/P1/P2, Live2D, TTS và Rich Chat đang có. Không cần cấu hình biến môi trường.

## Kiểm tra nhanh trên Windows

1. Build Eris bằng `build_dev_fast.bat`, mở Rich Chat, hỏi một câu có công thức, bảng hoặc đồ thị.
2. Kiểm tra artifact hiện dưới tin chat đúng lượt, không lặp trong gallery.
3. Kiểm tra `logs/eris_artifacts/presentation_v1/feedback/` có `art_*.r1.json` với `status=rendered` nếu browser dựng thành công; khi không mở Rich Chat, không có ACK thì Root nhận `awaiting_viewer`, không báo lỗi.
4. Nếu ảnh hỏng, phản hồi phải là `failed/E_RENDER`. Sau nội dung mới hoặc khi người dùng yêu cầu sửa, Root có thể tạo artifact khác; không tự tuyên bố thành công dựa vào ACK.

Đợt test trong môi trường tạo bản vá: 79 bài Python/Node đạt; 2 bài Chromium bị giới hạn quyền mở URL/file, **không tính đạt**. Chưa có Godot/.NET build Windows trong môi trường này. ACK không chứng minh kết quả toán đúng hay người dùng đã đọc.
