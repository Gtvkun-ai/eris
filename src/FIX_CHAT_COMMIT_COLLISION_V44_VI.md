# Sửa lỗi chat không phát ra UI/TTS sau khi restart — V44

## Hiện tượng trong log

- Architecture C khởi động thành công.
- Lời mở đầu được phát bình thường.
- Runtime nhận câu `xin chào`.
- Main model hoàn thành suy luận và trả content.
- Không có dòng `ERIS: ...`, không có public commit.
- Public lifecycle chuyển sang `DEGRADED`.
- Cuối phiên, launcher chủ động dừng `vision.py` với `unexpected=False`; đây không phải crash Python.

## Nguyên nhân

Khóa idempotency cũ của lượt chat có dạng:

`chat:session_turn:<sequence>:assistant`

`SessionTurnLedger` đánh số lại từ đầu sau mỗi lần khởi động, nhưng receipt trong
durable public-turn store tồn tại qua nhiều phiên. Vì vậy một lượt mới có thể đụng
khóa của phiên cũ. Registry trả receipt đã commit và không chạy lại side effect
UI/TTS. Model đã tạo câu trả lời, nhưng người dùng không nhìn hoặc nghe thấy gì.

## Bản vá

Khóa commit mới gồm:

- `runtime_session_id`
- `_active_public_lifecycle_turn_id`
- logical `turn_id`

Khóa vẫn ổn định trong cùng một lượt để chống phát trùng, nhưng khác nhau giữa
hai lần restart và giữa hai message mới.

## Kiểm tra

- Test hồi quy mới cho tính ổn định trong cùng lượt.
- Test khóa khác nhau giữa hai runtime session.
- Test khóa khác nhau giữa hai user message.
- Cụm Architecture C và test hồi quy: đạt.
- 701 test khả dụng của repo: đạt.
- Các kiểm tra còn lại bị chặn hoặc fail riêng vì archive thiếu các module `tools/*`,
  không liên quan bản vá này.
- Compile toàn bộ source: đạt.

## Phạm vi đóng gói

Gói V44 được tạo lại từ chính `src(48).zip`, giữ nguyên các entry gốc. Chỉ:

1. thay `runtime/ai_orchestrated/orchestrator.py`;
2. thêm `tests/test_chat_commit_idempotency_scope_v44.py`;
3. thêm báo cáo này.

Không xóa cache, asset, log hay file khác trong đợt vá này.
