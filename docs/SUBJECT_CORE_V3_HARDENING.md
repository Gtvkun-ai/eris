# ERIS Subject Core V3: Integration Hardening

## Mục tiêu

V3 không thêm một lớp “tính cách” mới. Nó làm phần ít hào nhoáng nhưng quyết định hệ thống có đáng tin hay không: ràng buộc capability, idempotency bền qua restart, migration có checksum, backup có kiểm tra, body protocol có giới hạn và test tương thích Python/C#.

Bản này tiếp tục giữ bốn ranh giới của đặc tả:

- Mind đề xuất và quyết định, không trực tiếp làm I/O.
- Actuator chuyển quyết định thành lệnh typed.
- Sandbox cho phép, từ chối hoặc mô phỏng.
- Audit ghi lại, không tham gia lựa chọn.

## 1. Sandbox policy V3

### 1.1 Token bị ràng buộc với policy

`CapabilityToken.policy_version` phải trùng `CommandPolicy.policy_version`. Token cũ không tự nhiên có quyền với policy mới chỉ vì chuỗi capability trông quen mắt.

### 1.2 Token bị ràng buộc với subject và scope

Lệnh có thể mang `subject_id`, `thread_id`, `delivery_id`. Sandbox kiểm tra subject của lệnh với subject của token và giữ thread/delivery trong `WorldOutcome`.

Scope tùy chọn hỗ trợ:

- `command_ids`
- `action_ids`
- `decision_ids`
- `workspace_prefixes`
- `network_hosts`
- `max_output_bytes`

### 1.3 Hạn tuổi lệnh

Policy từ chối lệnh quá cũ hoặc có timestamp quá xa trong tương lai. Điều này không biến timestamp thành hệ thống chống replay hoàn chỉnh, nhưng chặn lớp lỗi phổ biến khi queue cũ hoặc clock sai tiếp tục phát lệnh.

### 1.4 File boundary

- Path rỗng bị từ chối.
- NUL byte bị từ chối.
- Path ra ngoài workspace bị từ chối.
- Symlink traversal bị từ chối mặc định.
- Path được revalidate ngay trước I/O để giảm TOCTOU.
- Read chỉ đọc tối đa giới hạn, không nạp toàn bộ file rồi mới cắt.
- Write dùng temporary file, `fsync` và `os.replace` để giảm file dở dang khi crash.
- Hash trước/sau được ghi trong observed changes.

### 1.5 Command boundary

- Executable phải thuộc allowlist.
- Path executable tường minh bị từ chối mặc định, tránh `/tmp/python` lọt qua chỉ vì basename là `python`.
- `shell=False` được giữ nguyên.
- Metacharacter, newline, NUL và argv quá lớn bị từ chối.
- Output đi vào temporary file thay vì `capture_output=True`, tránh giữ output không giới hạn trong RAM.
- Timeout được chuẩn hóa thành `runtime_timeout`.

### 1.6 Network boundary

Policy kiểm tra network enabled, host allowlist, token host scope và HTTP method. Sandbox vẫn không tự mở egress: phải inject `network_handler` thật.

## 2. Idempotency bền qua restart

V2 chỉ cache outcome trong RAM. Restart đồng nghĩa sandbox quên rằng action đã chạy, một truyền thống khá nguy hiểm khi action là ghi file hoặc gọi dịch vụ.

V3:

- Tạo canonical request hash cho từng `SandboxCommand`.
- Lưu request hash cùng result trong SQLite.
- Đọc lại result khi runtime khởi động lại.
- Từ chối cùng idempotency key nếu request hash khác.
- Kiểm tra hash của result trước khi trả lại.
- Serialize các call đồng thời cùng key trong một process.
- Ghi idempotency result và `world_outcomes` trong cùng transaction.

Giới hạn còn lại: hai process riêng biệt vẫn có thể cùng thực hiện side effect trước khi một process thắng transaction cuối. Muốn exactly-once xuyên process cần claim/lease hai pha hoặc một persistence actor dùng chung. V3 không giả vờ rằng SQLite đã ban phép màu phân tán.

## 3. Persistence và migration

Migration `0004_integration_hardening.sql` thêm:

- `request_hash` cho `idempotency_keys`.
- Trigger append-only cho idempotency.
- `subject_integrity_checkpoints` append-only.

Migration runner mới đặt DDL và row checksum trong cùng SQLite transaction. Nó cung cấp:

- `migration_status()`
- `integrity_report()`
- `backup_to()`
- `get_idempotent()` có verify hash
- conflict detection cho authorship/world outcome

`integrity_report()` kiểm tra:

- `PRAGMA quick_check`
- foreign key được bật
- `PRAGMA foreign_key_check`
- migration tồn tại và checksum đúng
- event hash chain theo subject
- projection hash theo subject

## 4. Body protocol

Python `SubjectPerformanceBodyAdapter` có một đường dựng frame duy nhất qua `build_frame()` và một validator độc lập.

Giới hạn mới:

- Protocol: `eris.subject.performance`
- Schema version: `1`
- Tối đa 32 body cues
- Mỗi text field tối đa 256 ký tự
- Sequence không âm
- Các score nằm trong `[0, 1]`
- `decision_id` và `delivery_id` được truyền thật, không còn luôn rỗng

C# `SubjectPerformanceFrame.cs` dùng cùng constants và từ chối payload quá lớn, cue không đúng type, cue quá dài, cue quá nhiều hoặc plan id rỗng.

Do môi trường đóng gói không có Godot/.NET compiler, V3 có static contract checker và Python parity tests, nhưng không tuyên bố đã compile C#.

## 5. Công cụ vận hành

### Kiểm tra body contract

```bash
python scripts/check_body_contract.py
```

### Kiểm tra database

```bash
python scripts/subject_core_doctor.py /path/to/subject.db
```

### Kiểm tra và tạo backup

```bash
python scripts/subject_core_doctor.py /path/to/subject.db \
  --persist-checkpoint \
  --backup /path/to/backups/subject.db
```

Exit code:

- `0`: report OK
- `2`: integrity report không OK
- argparse/nonexistent file: lỗi thao tác

## 6. Test mới

V3 thêm 13 test, gồm:

- policy version mismatch
- token subject mismatch
- path rỗng
- executable path injection
- token workspace prefix
- concurrency cùng idempotency key
- restart idempotency
- idempotency key reuse với request khác
- symlink traversal
- migration status/checksum
- integrity checkpoint và verified backup
- tampered idempotency result
- Python/C# body contract parity

Kết quả suite theo hợp đồng hiện hành:

- **877 passed**
- **2 deselected** vì test V53/V54 mâu thuẫn trực tiếp với hợp đồng V54/V55

Full historical suite:

- **877 passed**
- **2 failed**, vẫn là đúng hai assertion source-level cũ nói trên

## 7. Những gì V3 chưa làm

- Chưa compile Godot/C#.
- Chưa chạy Ruff/mypy vì tool không có trong môi trường.
- Chưa triển khai process-wide idempotency lease.
- Chưa có OS-level container, seccomp hoặc Windows Job Object.
- `max_memory_mb` vẫn là policy metadata, chưa được enforce portable.
- Network handler thật chưa được cung cấp.
- Chưa chạy canary 1–2 tuần với dữ liệu vận hành.

## 8. Khuyến nghị rollout

1. Chạy doctor trên bản copy của database.
2. Tạo verified backup.
3. Bật Subject Core cho một test subject.
4. Giữ action nguy hiểm ở simulate.
5. Kiểm tra event chain và projection drift hằng ngày.
6. Chỉ mở write/run/network theo capability nhỏ, scope hẹp và token ngắn hạn.
7. Compile Godot project trước khi thay body parser production.
