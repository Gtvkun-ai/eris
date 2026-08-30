# V82 — Tool Literacy Mentor

## 1. Mục tiêu

V82 làm cho Eris Desktop biết **dạy user dùng đúng công cụ kỹ thuật để lấy evidence**.

Eris không cần tự viết debugger, test runner, profiler hay Git UI. Những thứ đó đã tồn tại trong VS Code, Git, Godot và GitPilot. Giá trị của Eris là biết:

- bug hiện tại cần trả lời câu hỏi gì;
- tool nào trả lời câu hỏi đó tốt nhất;
- user nên nhìn evidence nào trong tool;
- user đã quen tool đó đến đâu để điều chỉnh cách dạy.

Boundary:

```text
Eris Mentor
    ↓ tư vấn
User dùng tool có sẵn
    ↓ evidence
User + GitPilot tiếp tục phân tích/code
```

Không có:

```text
Eris Mentor → tự chạy debugger/test/git/profiler → tự code
```

## 2. Nguyên tắc "một câu hỏi — một tool chính"

V82 không quăng checklist 8–10 tool. Mỗi teachable moment chọn:

- **1 primary tool**;
- tối đa **2 supporting tools**.

Ví dụ user nói game lag:

```text
Câu hỏi cần trả lời:
CPU/frame time đang bị tiêu ở đâu?

Primary:
Profiler

Sau khi có hotspot mới đọc đúng code path đó.
```

Không nên bắt đầu bằng "đọc thử mấy file nặng nặng".

## 3. Tool catalog V82

### `code_search`
Dùng Search / References / Call hierarchy để tìm owner của behavior và trace call-flow.

### `vscode_diagnostics`
Dùng Problems/LSP/compiler diagnostics cho lỗi static/type/import/compile.

### `git_diff`
Dùng để review chính xác AI vừa đổi gì, có vượt scope hay không.

### `targeted_tests`
Dùng test nhỏ nhất tái hiện bug trước, rồi regression gần nhất sau fix.

### `stack_log`
Dùng stack trace/runtime log để tìm frame đầu tiên thuộc code dự án.

### `debugger`
Dùng breakpoint/watch/call stack để tìm state divergence trước/sau mutation.

### `profiler`
Dùng khi vấn đề là lag/FPS/performance. Đo trước khi tối ưu.

### `godot_remote_scene`
Dùng Remote Scene Tree khi node/transform/collision/process state lúc runtime có thể khác editor.

### `godot_debugger`
Dùng Godot Debugger/Errors/Monitors cho runtime error, physics/process spike hoặc engine warning.

## 4. Mapping từ V79 flow sang tool

Một số finding đã có evidence rõ nên được ưu tiên hơn keyword chat:

```text
review_not_observed / scope_expansion
→ git_diff

repeated_test_failure
→ targeted_tests

no_structured_verification
→ targeted_tests

patch_before_inspection
→ code_search

repeated_same_failure
→ debugger + stack/log
```

V82 không nói "agent ngu" rồi sửa tiếp. Nó dạy user cách lấy evidence tốt hơn.

## 5. Điều chỉnh theo khả năng user

State mới:

```text
<ERIS_HOME>/mentor/engineering_tool_literacy.json
```

Mỗi tool chỉ giữ metadata:

```text
stage
exposures
demonstrated_count
confidence
last_recommended_at
last_demonstrated_at
```

Không lưu raw chat/source code.

Stage:

```text
unobserved
introduced
demonstrated
familiar
```

Nếu `unobserved/introduced`:
- Eris chỉ một bước mở tool cơ bản;
- nói phải nhìn evidence nào.

Nếu `demonstrated/familiar`:
- bỏ tutorial UI;
- nói thẳng câu hỏi cần kiểm chứng và evidence cần tìm.

## 6. Evidence user thật sự biết dùng tool

Chỉ nhắc tên tool không đủ.

```text
"Debugger dùng sao?"
```

→ không tăng demonstrated count.

Ví dụ evidence hợp lệ hơn:

```text
"Tôi mở git diff và thấy hunk ở shadow.gd đổi anchor ngoài scope."
```

→ có action + tool + observed result, nên V82 ghi một demonstration event.

V82 vẫn không semantic-grade toàn bộ câu trả lời user. Đây chỉ là signal hẹp để tránh tự tin giả.

## 7. Quan hệ với V80/V81

```text
V79 Coding Observation
        ↓
V80 Teaching Policy
        ↓
V80.1 Intervention Gate
        ↓
V81 Adaptive Learning
        ↓
V82 Tool Literacy
        ↓
Public writer của Eris
```

V82 dùng cùng intervention gate. Nếu V80.1 quyết định im, V82 cũng im.

V82 không tạo một "Tool Agent" mới.

## 8. Hard boundaries

Public writer nhận directive phải tuân thủ:

- không claim đã mở Problems/debugger/profiler/diff/test/Godot Remote Scene nếu không có observation thật;
- không tự tạo tool mới khi IDE/engine/git/test tool đã giải được;
- không dump checklist chung chung;
- tool recommendation phải gắn với một câu hỏi evidence cụ thể;
- không giành GitPilot coding authority;
- không coi user không biết tool là bằng chứng user kém toàn diện.

## 9. Ví dụ

### Runtime state bug

User:

```text
Giá trị đúng lúc đầu mà sau animation lại sai.
```

Eris có thể dạy:

```text
Đừng đọc thêm file vội. Câu hỏi cần trả lời là state đổi sai ở mutation nào.
Đặt breakpoint ngay trước chỗ state bị đổi, xem value trước/sau và call stack.
Khi biết frame đầu tiên lệch rồi mới trace ngược code path.
```

### Godot collision lệch

```text
Godot slime collision lệch sprite lúc chạy.
```

Eris ưu tiên Remote Scene Tree thay vì chỉ đọc `.tscn`, vì node có thể được scale/spawn/chỉnh transform lúc runtime.

### AI patch quá rộng

```text
GitPilot sửa 7 file, task ban đầu chỉ fix một bug.
```

Eris ưu tiên Git diff: xem hunk nào phục vụ intent, file nào là scope creep, rồi mới quyết định test hay rollback.

## 10. Không làm trong V82

- Không tự mở tool trên máy user.
- Không điều khiển GitPilot.
- Không thêm debugger wrapper của Eris.
- Không thêm profiler wrapper của Eris.
- Không chạy homework/background scheduler.
- Chưa ghép live desktop/Godot state sâu; đó là hướng V83 cross-environment supervisor.
