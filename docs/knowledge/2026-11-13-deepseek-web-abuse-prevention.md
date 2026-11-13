# Bài học điều tra: Phòng chống cấm ngôn (Ban/Mute) tài khoản DeepSeek Web qua Whale2API

Ngày lập: 2026-11-13.
Áp dụng cho: Mọi Agent, Subagent, Script kiểm thử, Benchmark và Runtime Caller khi tương tác với cổng LLM `http://127.0.0.1:5103` (Whale2API / DS2API).

---

## 1. Bối cảnh sự việc & Bằng chứng thực tế

Vào ngày 13/11/2026, toàn bộ 3 tài khoản đang hoạt động trong Pool Whale2API đều bị phát hiện không thể giao tiếp và hệ thống trả về lỗi liên hoàn `429 upstream_empty_output` dẫn tới `writer_failed: v03_missing_public_surface`.

Khi kiểm tra sâu vào cơ sở dữ liệu `tools/whale2api/docker-data/whale2api/whale2api.db` (bảng `pool_account_test_jobs`) và nhật ký container Docker `whale2api`, phát hiện:

1. **Án phạt cấm ngôn (Muted) 365 ngày:**
   ```json
   {"identifier": "azaikyousuke306@gmail.com", "ok": false, "message": "user is muted（解禁 2027-11-04 02:09:40）"}
   ```
   Tài khoản bị DeepSeek khóa quyền gửi tin nhắn đúng 1 năm (từ 04/11/2026 đến 04/11/2027).

2. **Dấu vết tại thời điểm phát lệnh phạt:**
   Trong log Docker `whale2api` lúc `2026-11-04T10:09:20.839Z` (trước thời điểm chốt lệnh cấm 20 giây tính theo múi giờ Bắc Kinh):
   ```text
   level=WARN msg=[upstream_empty_output] surface=openai_chat 
   trigger_reason=no_visible_text_no_thinking_no_tools 
   upstream_message="Upstream account hit a rate limit and returned empty output." 
   model=deepseek-flash prompt_byte_len=194366 completion_payload_json_bytes=104293 client_request_content_length=104485
   ```

3. **Nguyên nhân gốc:**
   Một Agent kiểm thử trước đó đã chạy tác vụ `.agents/tasks/eris-eq-verification/` (được ghi nhận trong `docs/knowledge/2026-11-04-eq-live-verification.md` với 44 lời gọi live liên tiếp).
   Script đã replay toàn bộ lịch sử hội thoại, `Self` bootstrap, memory state và context khổng lồ lên tới **194.366 bytes (~194 KB, gần 30.000 tokens)** và bắn dồn dập cách nhau chỉ vài giây.
   Ngoài ra, một loạt tài khoản clone khác cùng dải IP bị DeepSeek gom cụm Risk Control và khóa vĩnh viễn (`login failed: USER_IS_BANNED`).

---

## 2. Bản chất kiến trúc: Hiểu đúng về Whale2API

* **Không phải Unlimited API trả phí:** Cổng `http://127.0.0.1:5103/v1` không phải là DeepSeek Official API trả phí (`api.deepseek.com`), mà là **Reverse Proxy** giả lập giao thức Web của người dùng miễn phí (`chat.deepseek.com`).
* **Hệ thống giám sát Shumei (数美科技):** DeepSeek áp dụng hệ thống kiểm soát rủi ro và anti-bot hàng đầu (đó là lý do repo có sidecar `device-harvest`). Hệ thống này giám sát:
  * Tần suất gửi tin nhắn (burst rate).
  * Kích thước payload (người dùng web thật không bao giờ paste 200 KB trong 1 tích tắc không có phím bấm).
  * Hành vi và device fingerprint.
* **Hậu quả vi phạm:**
  * **Spam payload quá nặng / gọi quá nhanh:** Ăn án phạt **cấm ngôn 365 ngày** (`user is muted`).
  * **Nhiều tài khoản có hành vi giống bot trên cùng một IP:** Bị gom vào Fraud Cluster và ăn án phạt **khóa vĩnh viễn** (`USER_IS_BANNED`).

---

## 3. Quy tắc bắt buộc đối với mọi Agent khi kiểm thử (Strict Directives)

Tất cả các Agent khi tham gia phát triển, debug, benchmark hoặc kiểm thử runtime Eris **BẮT BUỘC** tuân thủ các quy tắc sau:

### Quy tắc 1: Tuyệt đối KHÔNG burst spam request
* Mọi script vòng lặp kiểm thử gọi vào `http://127.0.0.1:5103` **bắt buộc phải có khoảng nghỉ (sleep / cooldown) tối thiểu từ 3 đến 5 giây** giữa mỗi lần gọi.
* Nghiêm cấm chạy kiểm thử đồng thời (concurrent threads / async asyncio.gather) với số lượng lớn nhắm vào cổng proxy.

### Quy tắc 2: Khống chế kích thước Payload (Token Budget)
* Khi tạo payload kiểm thử, **không được gửi context vượt quá 64 KB** (tương đương ~15.000 tokens).
* Nghiêm cấm việc dump toàn bộ `self.memory_state`, `active_social_carry` thô hoặc toàn bộ lịch sử hàng chục lượt chat chưa gọt giũa vào request kiểm thử.

### Quy tắc 3: Ưu tiên Mock và Deterministic Simulation
* Kiểm thử định dạng (JSON format), prompt contract, routing logic, speech polish, TTS hay UI **bắt buộc phải kiểm thử bằng mock / fixture offline trước**.
* Chỉ chạy live test (`--confirm-live`) khi thực sự cần kiểm tra tương thích upstream, và giới hạn **tối đa 3 đến 5 request** cho một lần smoke test. Cấm tuyệt đối các vòng lặp benchmark 40–50 lượt live dồn dập.

### Quy tắc 4: Luôn truyền `thinking: {"type": "disabled"}` khi test proxy
* Whale2API và DeepSeek Web có cơ chế sinh thinking tự động nếu không có cờ tắt, dễ làm payload phình to và kích hoạt lỗi `upstream_empty_output`.
* Luôn đảm bảo request kiểm thử mang cờ `"thinking": {"type": "disabled"}` trừ phi chính mục tiêu của bài test là kiểm tra luồng suy nghĩ.

### Quy tắc 5: Bảo vệ danh sách tài khoản dự phòng
* Không tự ý đánh thức (unmute / activate) các tài khoản đang ở trạng thái ngủ (`discarded = 1`, `discard_reason = 'manual'`) nếu chưa có sự đồng ý của người dùng.
* Khi phát hiện tài khoản bị cấm ngôn hoặc lỗi liên tục, đánh dấu `discarded = 1` ngay lập tức để bảo vệ các tài khoản còn lại trong pool.

