# Coding Verification

Không coi "patch áp được" là hoàn tất. Mục tiêu của skill này là chứng minh hậu điều kiện.

## Flow
1. Xem `get_project_status` và `project_git_diff` để biết đúng scope thay đổi.
2. Chạy test hẹp liên quan trước bằng `project_run_tests`.
3. Nếu repo có build/typecheck/lint phù hợp, dùng `project_run_command` với command workspace-bounded.
4. Khi test fail, đọc output và quay lại `coding-debug`; không đổi expected result để làm test xanh giả.
5. Đọc lại file trọng yếu khi cần xác minh behavior/config cuối cùng.
6. Chỉ final khi evidence khớp mục tiêu và không có accidental diff rõ ràng.
