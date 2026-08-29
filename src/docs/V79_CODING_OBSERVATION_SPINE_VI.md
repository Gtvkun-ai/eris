# V79 — Coding Observation Spine

## Mục tiêu

V79 không làm Eris code giỏi hơn. V79 làm **Eris hiểu GitPilot đang làm gì** để V80 có thể trở thành mentor/gia sư.

```text
GitPilot
  ↓ AgentEventBus / SSE
Eris Code
  ↓ normalize + sanitize
CodingObservation
  ↓ Eris Link (opt-in, localhost)
Eris Desktop
  ↓
CodingObservationService
  ↓
CodingFlowInterpreter + journal
```

## Dữ liệu Eris được phép thấy

- task bắt đầu/kết thúc;
- role hiện tại: Explorer / Planner / Coder / Reviewer / Validation;
- tool nào được gọi;
- file path nào được đọc/sửa;
- command ngắn đã chạy (được redact secret pattern);
- test/diagnostics pass/fail;
- approval request/result;
- `phase_summary`: output explicit của từng specialist.

## Dữ liệu cố ý không lưu

- raw `read_file` result;
- toàn bộ source code chỉ vì muốn "quan sát";
- terminal spam dài;
- hidden chain-of-thought / verbose CrewAI reasoning log;
- API key/token/password/authorization header.

## Tool Flow Interpreter hiện phát hiện gì?

### `patch_before_inspection`

Có file mutation trước khi journal thấy read/search/list/git-diff evidence.

### `repeated_same_failure`

Cùng tool/error signature lặp ít nhất ba lần mà chưa đổi chiến lược.

### `repeated_test_failure`

Ba validation run có test fail. Đây là dấu hiệu nên quay lại giả thuyết/root cause thay vì retry mù.

### `scope_expansion`

Một task chạm từ tám file trở lên. Không khẳng định sai, chỉ đánh dấu để review scope.

### `no_structured_verification`

Task đã sửa file nhưng kết thúc mà không thấy `test_result` hoặc `diagnostics` có cấu trúc.

### `review_not_observed`

Task có mutation nhưng journal không thấy Reviewer phase.

## V79 không làm gì với warning?

Không tự stop Coder. Không redirect. Không approve/deny thay user. Không sửa prompt đang chạy.

Warning chỉ là evidence cho V80 Teaching Policy sau này quyết định:

- giải thích cho user;
- gợi ý user đọc file nào;
- yêu cầu user tự trace;
- cảnh báo vibe coding mù;
- hoặc im lặng nếu user đã đủ giỏi.

## Cách bật Eris Link

Desktop giữ endpoint opt-in để không tự mở project-memory API trên localhost.

Trước khi chạy Desktop:

```powershell
$env:ERIS_CODE_OBSERVER_LINK_ENABLED="1"
```

Trong VS Code settings:

```json
{
  "erisCode.erisLink.enabled": true
}
```

Mặc định port: `127.0.0.1:8767`.

## Boundary security

`POST /v1/coding/observations` chỉ nhận schema allow-list. Generic coding RPC không tồn tại.

```text
/v1/coding/control       ✗
/v1/coding/approve       ✗
/v1/coding/terminal      ✗
/v1/coding/write-file    ✗
```

GitPilot vẫn là coding authority duy nhất.
