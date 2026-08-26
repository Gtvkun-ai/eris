# Coding Modification

Sửa ít nhất có thể để giải quyết root cause đã xác định.

## Flow
1. Đọc lại file mục tiêu nếu observation cũ có thể stale.
2. Áp patch nhỏ, tái sử dụng abstraction hiện hữu.
3. Chạy test liên quan.
4. Nếu fail: đọc failure -> replan -> patch tiếp hoặc rollback khi hướng sai.
5. Khi pass: xem `project_git_diff` để kiểm tra accidental changes.
6. Chỉ kết luận xong khi verification có evidence.

Không dùng `project_execute_task`; Unified Agent Harness với dedicated coding subbrain chính là owner của vòng lặp. Không delegate toàn bộ goal sang WebAI hoặc một coding-agent runtime thứ hai.
