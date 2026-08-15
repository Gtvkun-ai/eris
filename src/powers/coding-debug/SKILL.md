# Coding Debug

Mục tiêu là tìm **root cause**, không vá triệu chứng đầu tiên nhìn thấy.

## Quy tắc
- Bắt đầu từ evidence gần lỗi nhất: traceback/log/test failure.
- Tìm implementation và caller trước khi đề xuất patch.
- Chạy test hẹp trước, test rộng sau khi sửa.
- Nếu cùng một hướng thất bại lặp lại, dừng và replan thay vì retry mù.
- Nếu phát hiện hai hướng kiến trúc khác nhau đáng kể và user chưa chọn constraint, trả về nhu cầu clarification thay vì tự chọn bừa.

Khi đã đủ evidence để sửa, activate `coding-modification`.
