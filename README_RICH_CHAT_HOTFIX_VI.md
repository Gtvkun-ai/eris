# ERIS — Hotfix hiển thị công thức trong Chat Panel

## Đã sửa

- Biểu thức tích phân có cận ở dạng Unicode, ví dụ `∫₀¹ x dx = x²/2 |₀¹ = 1/2`, được tách thành block `formula` và chuyển sang MathText, thay vì luôn bị xem là một đoạn chữ thường. Chữ xung quanh vẫn là paragraph; không sửa lời thoại của Root/TTS.
- V6 tạo ảnh toán theo từng `block_id`; không còn ghi đè `math_0.png` khi có nhiều công thức, tránh thất bại xác minh SHA-256.
- Ảnh công thức trong Chat Panel không ép kích thước tối thiểu 700px như panel đồ thị độc lập.
- Thêm test mô phỏng chính nội dung tích phân trong ảnh và nhiều công thức trong một lượt.

## Cách kiểm tra

1. Giải nén bản đầy đủ vào **thư mục khác**, tránh ghi đè bản chạy ổn. Bản đầy đủ đã bao gồm bản vá Bubble Live2D trước đó.
2. Build Godot C# hoặc chạy script build của dự án. **Không dùng lại Eris.exe cũ chưa build lại.**
3. Cài dependency nếu cần: `py -m pip install -r requirements-artifact-workspace.txt`.
4. Mở Chat Panel, gửi **tin nhắn mới** có đề hoặc lời giải chứa `∫₀¹ x dx = x²/2 |₀¹ = 1/2.`. Lịch sử cũ đã lưu block plain text không tự chuyển thành ảnh toán mới.
5. Nếu ảnh không xuất hiện trên Windows, bảo đảm cả Python và Godot dùng cùng đường dẫn tuyệt đối qua `ERIS_ARTIFACT_WORKSPACE`. Kiểm tra log Godot báo `[artifact]` hoặc `[V6]`.

## Giới hạn cần hiểu rõ

Hotfix này cải thiện một nhóm ký hiệu toán Unicode và lỗi ảnh công thức. **Chưa thay Chat Panel thành renderer như ChatGPT**: chưa có KaTeX/MathJax đầy đủ, Markdown mở rộng, code highlighting kiểu editor, đồ thị tương tác hay rich content đa loại. Để đạt mục tiêu đó cần một pipeline hiển thị có cấu trúc và renderer thích hợp (ví dụ WebView2/HTML với KaTeX), tách khỏi Bubble/TTS.

Python tests: `PYTHONPATH=src python -m pytest -q src/tests/workspace/test_rich_chat_math_hotfix.py src/tests/workspace/test_structured_output_v5.py src/tests/workspace/test_live_workspace_v6.py`

Đã chạy: **24 passed**. Chưa build hay chạy Godot trên Windows trong môi trường này (không có Godot/dotnet).
