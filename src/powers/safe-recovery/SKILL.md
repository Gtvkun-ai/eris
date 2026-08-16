# Safe Recovery

Checkpoint Agent là cặp **LangGraph state + filesystem snapshot + task projection**.

## Quy tắc
- Dùng `list_task_checkpoints` để biết checkpoint nào thật sự có filesystem snapshot.
- Dùng diff/status để hiểu thay đổi hiện tại trước khi đề xuất rollback.
- Không tự gọi shell `git reset --hard` để bắt chước rollback. Control plane của Eris sở hữu atomic restore.
- Sau rollback, phải replan từ evidence đã phục hồi; không lặp lại action vừa bị revert theo quán tính.
- Snapshot degraded phải được coi là giới hạn thật, không quảng cáo rollback tuyệt đối.
