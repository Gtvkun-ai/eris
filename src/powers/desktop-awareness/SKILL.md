# Desktop Awareness

Dùng skill này khi task cần **quan sát trạng thái thật của máy** thay vì đoán từ hội thoại.

## Nguyên tắc
- Ưu tiên tool có nguồn dữ liệu trực tiếp nhỏ nhất phù hợp với câu hỏi.
- Hỏi bài/media đang phát -> `get_now_playing`, không OCR màn hình trước.
- Hỏi app/cửa sổ đang dùng -> `get_active_application`.
- Chỉ dùng `read_visible_ui_text` khi nội dung UI thật sự cần thiết.
- Không suy diễn nội dung không có trong observation.
- Nếu tool báo unavailable/fail, báo đúng giới hạn rồi mới thử nguồn evidence khác nếu hợp lý.
