# Threat Model: ERIS Sandbox World V3

## Tài sản cần bảo vệ

- File ngoài workspace.
- Secret trong environment.
- Quyền thực thi command.
- Network egress.
- Tính đúng của event, outcome và audit chain.
- Idempotency của action có side effect.
- Private Mind state không được gửi sang body/TTS.

## Trust boundaries

1. Mind → Actuator: dữ liệu không đáng tin, dù được tạo nội bộ.
2. Actuator → Sandbox: command typed nhưng vẫn cần authorize.
3. Sandbox → OS/network/body/TTS: side effect thật.
4. Sandbox → Repository/Audit: dữ liệu phải canonical và append-only.
5. Python → Godot/C#: protocol công khai, không chứa private state.

## Mối đe dọa và kiểm soát

| Mối đe dọa | Kiểm soát V3 | Rủi ro còn lại |
|---|---|---|
| Path traversal | resolve + workspace containment | TOCTOU hệ điều hành đặc thù |
| Symlink escape | deny symlink mặc định, revalidate | Junction/reparse point trên Windows cần test thật |
| Shell injection | argv typed, shell=false, metachar deny | Bug trong executable được allowlist |
| Executable spoofing | deny executable path mặc định | PATH search vẫn phụ thuộc môi trường hệ thống |
| Output memory blow-up | stdout/stderr vào temporary file | Process vẫn có thể dùng RAM nội bộ |
| Stale/replayed command | command age/future skew, idempotency | Cross-process race chưa có lease |
| Token dùng sai subject | subject binding | Caller bỏ trống subject_id dùng token subject |
| Token cũ dùng policy mới | policy version binding | Cần rotation/expiry vận hành |
| Network exfiltration | disabled mặc định, handler injection, host/method allowlist | DNS rebinding/IP resolution chưa xử lý |
| Idempotency tampering | result hash, request hash, append-only trigger | DB admin vẫn có thể drop trigger |
| Body private-state leak | typed allowlist frame | Transport khác có thể bỏ qua adapter |
| Audit impersonation | subject lấy từ token/command | Token issuer vẫn là root of trust |

## Quy tắc deployment

- Workspace riêng, không đặt home directory làm workspace.
- Không allowlist shell như `bash`, `cmd`, `powershell` nếu không có wrapper chuyên biệt.
- Token ngắn hạn, capability tối thiểu, prefix tối thiểu.
- Network disabled cho đến khi có DNS/IP policy và transport audit.
- Database và audit DB dùng permission riêng; application không có quyền sửa ngoài API.
- Chạy doctor và backup trước migration production.
