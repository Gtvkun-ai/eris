# Ghi chú bản vá 2026-08-09

Bản vá này xử lý các lỗi đã xác định trong lần chạy ngày 2026-08-09, ngoại trừ mục #4 (lỗi/rate-limit backend LLM) và #5 (độ trễ toàn turn), theo yêu cầu.

## Các thay đổi chính

- Khôi phục khả năng dùng OCR làm bằng chứng khi vision/VLM chưa được cấu hình hoặc bị lỗi, thay vì làm mất toàn bộ tín hiệu màn hình.
- Cho vision client chạy ở chế độ tự động theo cấu hình khả dụng thay vì mặc định vô hiệu hóa.
- Chặn phát các khẳng định về trạng thái thế giới/tri giác hiện tại khi không có evidence phù hợp.
- Đổi grounding gate sang fail-closed cho cả chat và autonomous; không còn phát nguyên draft sau khi gate đã đánh dấu sai grounding.
- Nhận diện trường hợp người dùng đang sửa một khẳng định tri giác/factual của Eris và ép semantic frame sang repair thay vì disagreement.
- Bỏ qua capability planner đối với lượt hội thoại thuần khi Subject đã xác nhận không cần capability/tool.
- Giữ đại từ tự xưng của Eris ổn định và hạn chế mirror cách gọi nhất thời của người dùng.
- Chặn lặp lại khung câu semantic kiểu “thỉnh thoảng ... cũng không tệ”.
- Siết `speech_act` thành identifier hợp lệ; natural-language prose không còn bị băm thành chuỗi underscore rác.
- Bổ sung regression test cho đúng các lỗi của lần chạy này.

## Không thay đổi

- Không sửa cơ chế 429/timeout/fallback của backend LLM (#4).
- Không sửa timeout tổng, deadline hay kiến trúc latency của lượt hội thoại (#5).

Các đoạn logic mới hoặc dễ gây hiểu nhầm đều có chú thích tiếng Việt ngay trong source.
