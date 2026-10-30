# P2 — Root tự chọn nội dung trình bày

**Mặc định bật.** Không cần môi trường mới hay cấu hình.

- Root quyết định `presentation_blocks` (math/table/code/chart/document) ngay trong `move`; TTS chỉ đọc `say`.
- Khi Root dùng `math_workspace` thành công, bộ nối lấy `artifact_bundle_id` từ **receipt thực của executor**; không tin ID do AI tự viết.
- Chỉ sau khi text đã được gửi ra giao diện, P2 mới gắn các artifact vào `turn_id` thật. Không ghi artifact nếu Root chưa finalize hoặc text chưa gửi.
- Rich Chat loại bản sao job tạm khi kết quả đã được gắn vào tin chat. P0/P1, Live2D, TTS và đường tài liệu cũ vẫn còn.
- Lỗi render tiếp tục gửi về Root qua P1 renderer feedback. ACK không xác nhận tính đúng đắn.

**Chạy:** giải nén và `build_dev_fast.bat`, mở **Rich Chat**. Thử hỏi: “Giải ∫₀¹ x dx bằng công thức và biểu đồ/bảng”, hoặc yêu cầu toán cần `math_workspace`.

**Giới hạn kiểm chứng:** pytest + Node kiểm tra contract và JS. Chưa xác nhận Eris.exe trên Windows hay tỉ lệ tự chọn tool của LLM thực tế. Không có agent loop thứ hai. Việc chọn tool có được cải thiện trong thực tế cần log `root-agent` và kết quả giao diện.
