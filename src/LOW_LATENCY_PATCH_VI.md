# Bản vá độ trễ chat và cờ

- Tắt `ERIS_CHAT_MAIN_VISION` mặc định: OCR/UIA cache vẫn được nhét vào mọi lượt chat, nhưng không chụp screenshot liên tục.
- OCR mơ hồ chỉ đặt cờ vision cho lượt chat kế tiếp; escalation hết hạn sau 30 giây hoặc khi đổi cửa sổ/engagement.
- Chess bridge là structured grounding chính thức. Khi có FEN tươi, không bắt vision nhìn lại bàn cờ.
- Main model chỉ được gọi một lần; nếu thất bại, router chuyển sang fallback ngay thay vì gọi lại main.
- Không dùng `ERIS_SPEECH_API_KEY` để dựng Gemini chat fallback.
- Chess engine mặc định depth 1 cho phản hồi nhanh; có thể tăng lại depth 2 khi chơi chậm/phân tích.
- Sự kiện nước cờ không phải chờ generic commentary grace.
- Extension hiển thị gợi ý từ engine cục bộ ngay khi bridge trả kết quả, không chờ LLM viết lời bình.

Để chẩn đoán provider trong một phiên, đặt `ERIS_LOG_PROFILE=debug`.
