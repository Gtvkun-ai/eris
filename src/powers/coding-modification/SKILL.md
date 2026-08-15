# Coding Modification

Sửa ít nhất có thể để giải quyết root cause đã xác định.

## Flow
1. Đọc lại file mục tiêu nếu observation cũ có thể stale.
2. Áp patch nhỏ, tái sử dụng abstraction hiện hữu.
3. Chạy test liên quan.
4. Nếu fail: đọc failure -> replan -> patch tiếp hoặc rollback khi hướng sai.
5. Khi pass: xem `project_git_diff` để kiểm tra accidental changes.
6. Chỉ kết luận xong khi verification có evidence.

Không dùng `project_execute_task`; Agent Harness hiện tại chính là vòng lặp thay thế cho one-shot executor đó.
