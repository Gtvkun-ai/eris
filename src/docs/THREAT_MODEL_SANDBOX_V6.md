# Threat model Sandbox V6

## Tài sản cần bảo vệ

- lịch sử sự kiện, belief, value và authorship trong Subject Core;
- filesystem nằm ngoài workspace;
- secret trong biến môi trường và keyring;
- dịch vụ nội bộ, metadata endpoint và loopback;
- tính đúng-một-lần của side effect;
- tính toàn vẹn của audit và WorldOutcome.

## Ranh giới tin cậy

```text
Mind (không tin cậy để thực thi)
  -> ActionRequest
  -> CapabilityAuthority / token scope
  -> CapabilityPolicy
  -> SandboxWorld
  -> file / command / safe HTTP / body / TTS
  -> WorldOutcome + Audit
```

Mind có thể đề xuất dữ liệu xấu hoặc hành động bị cấm. Actuator không được tự nới quyền. Transport tùy biến do ứng dụng inject được coi là trusted adapter và phải audit riêng.

## Mối đe dọa và kiểm soát

### Token giả hoặc sửa payload

- HMAC-SHA256 trên payload canonical;
- issuer, audience, key ID và policy version bắt buộc;
- compare bằng `hmac.compare_digest`;
- token scope khóa command/action/decision/idempotency key.

### Khóa bị xoay làm gián đoạn token đang sống

- keyring giữ khóa cũ ở trạng thái verify-only;
- runtime tự reload manifest khi mtime đổi;
- token mới dùng khóa active mới;
- khóa cũ không được xóa trước khi TTL cũ kết thúc.

### SSRF tới localhost, private network hoặc metadata service

- hostname phải nằm trong allowlist chính xác;
- HTTPS bắt buộc mặc định;
- DNS result phải là IP global trừ khi operator chủ động cho phép private network;
- kết nối socket ghim vào IP đã kiểm tra;
- URL có username/password bị từ chối;
- redirect mặc định tắt; redirect được kiểm tra lại toàn bộ.

### DNS rebinding

- resolver chạy trước;
- `_PinnedHTTPConnection` và `_PinnedHTTPSConnection` kết nối thẳng tới IP đã kiểm tra;
- TLS vẫn xác minh theo hostname gốc bằng SNI;
- redirect phải resolve và kiểm tra lại.

### Header injection và proxy abuse

- chặn CR/LF trong header value;
- chặn Host, Connection, Proxy-Authorization, Proxy-Connection và Transfer-Encoding;
- transport không dùng proxy từ environment;
- chỉ header nằm trong allowlist được gửi.

### Response hoặc request quá lớn

- giới hạn request body;
- giới hạn response body;
- response vượt trần bị coi là failure, không chỉ im lặng truncate rồi tuyên bố thành công;
- raw response body không được đưa vào Mind, chỉ ghi status, số byte và digest.

### Duplicate execution và stale owner

- SQLite idempotency claim;
- fencing generation;
- heartbeat;
- stale owner không ghi durable receipt được.

## Rủi ro còn lại

- External service vẫn có thể thực hiện side effect trước khi local receipt ghi xong. Cần idempotency phía server.
- Operator có thể cấu hình sai allowlist hoặc bật private network.
- Shared filesystem của keyring phải đáng tin cậy.
- Rotate đồng thời bởi nhiều operator chưa dùng distributed lock.
- Sandbox không thay container/VM và không ngăn mọi syscall của process con.
- Windows chưa có Job Object hard limit trong bundle này.
