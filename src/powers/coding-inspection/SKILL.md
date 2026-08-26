# Coding Inspection

Điều tra trước, sửa sau. Mỗi lượt chọn **một thao tác nhỏ nhất** để giảm context và tăng khả năng replan.

## Flow khuyến nghị
1. Tìm symbol/text liên quan thay vì list toàn repo nếu đã có manh mối.
2. Đọc đúng đoạn/file cần thiết.
3. Với task không tầm thường, lấy baseline bằng `project_git_log`, `project_dependency_summary` và `project_test_inventory` khi chúng liên quan; không dump lockfile hay toàn repo vào context.
4. Kiểm tra implementation hiện hữu để tránh tạo abstraction trùng.
5. Xem `project_git_diff` trước khi kết luận trạng thái hiện tại.
6. Khi lỗi runtime là manh mối chính, dùng `read_current_error` hoặc `inspect_runtime_log`.

Không sửa code trong skill này. Nếu đã xác định được root cause, activate `coding-modification`.
