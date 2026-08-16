# Workspace Navigation

Dùng skill này để xác nhận **task đang ở đúng repo** trước khi đọc/sửa sâu.

## Flow
1. `workspace_list` khi task không có workspace rõ hoặc user nhắc repo quen thuộc.
2. Khi task đã khóa workspace, không switch/join/leave từ bên trong executor.
3. Dùng `get_project_status` để xác nhận branch/trạng thái.
4. `project_list_files` chỉ khi chưa có manh mối tốt hơn; nếu đã biết symbol/path thì chuyển sang coding-inspection.
5. `project_git_diff` để phát hiện work-in-progress của user trước khi agent sửa.
