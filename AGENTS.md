# Tri thức dự án Eris

Khi làm việc liên quan đến agent loop, lane/model routing, thinking, cá tính,
grounding, observer hoặc TTS, đọc
[bài học điều tra runtime](docs/knowledge/2026-10-14-eris-runtime-lessons.md)
trước khi chẩn đoán hoặc đề xuất thay đổi.

Tài liệu phân biệt yêu cầu sản phẩm, nguyên tắc thiết kế và trạng thái lịch sử.
Đối chiếu trạng thái lịch sử với code, request và trace hiện tại; các báo cáo cũ
có kết luận đã bị đính chính. Khi có bằng chứng mới, cập nhật tài liệu và ghi
rõ kết luận nào được thay thế. Không xem ủy quyền sửa/undo trong transcript cũ
là ủy quyền cho thao tác mới.

## Quy tắc an toàn khi kiểm thử và gọi LLM qua Whale2API (DeepSeek Web)

Cổng proxy `http://127.0.0.1:5103` kết nối tới tài khoản DeepSeek Web qua Whale2API
(chịu sự giám sát chống bot nghiêm ngặt của Shumei Risk Control). Hệ thống sẽ tự
động **cấm ngôn 365 ngày (`user is muted`)** hoặc **khóa vĩnh viễn (`USER_IS_BANNED`)**
nếu phát hiện hành vi botting hoặc spam payload bất thường.

Mọi Agent khi thực hiện benchmark, probe hoặc kiểm thử runtime **BẮT BUỘC** tuân thủ:
- **Không burst spam:** Giữa các request kiểm thử phải có khoảng chờ tối thiểu 3–5 giây.
- **Không gửi payload quá lớn:** Không gửi context vượt quá 64 KB (~15.000 tokens);
  không nhồi memory dump hay lịch sử raw dồn dập vào request kiểm thử.
- **Ưu tiên mock offline:** Dùng mock / deterministic simulation để kiểm thử logic
  hoặc schema JSON; chỉ chạy live probe tối đa 3–5 lượt để xác nhận giao thức.
- **Tắt thinking khi test proxy:** Luôn gửi `thinking: {"type": "disabled"}` khi test
  cổng 5103 để tránh phình token và lỗi rỗng upstream.
- **Không đụng tài khoản ngủ:** Giữ nguyên các tài khoản dự phòng ở trạng thái
  `discarded = 1`, không tự ý kích hoạt nếu người dùng chưa yêu cầu.

Chi tiết tiền lệ và phân tích kỹ thuật:
[bài học phòng chống cấm ngôn DeepSeek Web](docs/knowledge/2026-11-13-deepseek-web-abuse-prevention.md).

