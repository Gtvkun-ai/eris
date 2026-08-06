# Tích hợp Executive trung tâm với Subject Core V17

## Mục tiêu

Bản này không giản lược Subject Core và cũng không biến Executive thành một router chọn tool.
Luồng quyết định được tách thành ba trách nhiệm rõ ràng:

1. **Subject Core chuẩn bị nền**: substrate, appraisal, need activation, belief/value refs, proposal và coalition.
2. **Executive điều khiển và cam kết**: chọn đúng một coalition đã được cung cấp, có thể yêu cầu tối đa một vòng review nhận thức bounded.
3. **Subject Core finalize và học**: tạo `MindDecision`, mở authorship record, quan sát outcome và cập nhật lịch sử.

```text
WorldObservation
    -> SubjectService.prepare_deliberation()
    -> SubjectDeliberationFrame
    -> ExecutiveCortex.commit_subject_frame()
    -> SubjectExecutiveCommit
    -> SubjectService.finalize_deliberation()
    -> MindDecision / ActionAuthorship
    -> Actuator hoặc Dialogue
    -> WorldOutcome
    -> SubjectService.observe_outcome()
```

## Những thay đổi chính

### 1. Coalition không còn tự xưng là quyết định

`CoalitionArbiter.rank()` chỉ dựng và chấm `CoalitionCandidate`.
`CoalitionArbiter.build_decision()` chỉ được gọi sau khi có lựa chọn từ Executive.
API `choose()` vẫn được giữ để tương thích và unit test, nhưng authorship ghi rõ đó là fallback.

### 2. Frame quyết định bounded

`SubjectDeliberationFrame.public_view()` chỉ đưa cho Executive:

- substrate vận hành cần thiết;
- appraisal đã chuẩn hóa;
- need activation;
- coalition và điểm thành phần;
- refs của belief/value liên quan.

Raw private evidence và toàn bộ dashboard nội tâm không bị dump vào model Executive.

### 3. Executive có quyền cam kết thật

`SubjectExecutiveCommit` chứa:

- coalition và primary proposal được chọn;
- semantic commitments;
- cognitive requests;
- lý do và confidence;
- điều kiện review.

Subject Core từ chối commit trỏ tới coalition hoặc proposal không được cung cấp.

### 4. Một vòng review nhận thức có kiểm soát

Executive có thể yêu cầu đúng một vòng review với các phép biến đổi allowlist:

- `verify_evidence`
- `reduce_intrusion`
- `preserve_continuity`
- `estimate_capability`
- `inspect_dissent`

Mỗi phép biến đổi có biên số học, để lại audit event `deliberation_review`, không sửa substrate hay evidence gốc. Không có vòng lặp suy nghĩ vô hạn.

### 5. Chat và autonomous dùng chung một trung tâm

- Chat: ingress dựng frame, Executive commit, rồi mới sinh subject decision.
- Autonomous: mọi affordance được chuyển thành proposal; silence và body-only cũng là proposal có cost/need, không còn là absence khó truy nguyên.
- Capability: chỉ được chọn để thực hiện subject decision đã cam kết, không được đổi motive ở vòng chọn công cụ.

### 6. Bỏ prior hành động cố định ở chat ingress

`SubjectIngress` không còn inject hai proposal `speak/investigate` với score hard-code.
Proposal chat được sinh từ need activation, substrate, uncertainty, competence/history và value projection.

### 7. Authorship phân biệt nguồn quyền lực

`ActionAuthorship.selected_by` ghi một trong các nguồn:

- `executive_cortex:<commit_id>`
- `executive_policy_fallback:<...>` thông qua commit có source tương ứng
- `coalition_arbiter:<coalition_id>` chỉ ở API tương thích không có Executive

## Tương thích và migration

- Không đổi schema SQLite trong bản này.
- Algorithm version của SubjectService: `subject-service-v9-executive-center`.
- Runtime settings vẫn kế thừa bản v16 của startup memory callback.
- `SubjectRuntime.bind_executive()` được gọi sau khi AI orchestrated bootstrap hoàn tất để tránh dependency vòng.

## Kiểm thử

- 62 test Subject Core, Executive Cortex và startup callback: pass.
- Hồi quy rộng có lọc các test thiếu file ngoài archive: 829 pass, 5 deselected.
- `compileall`, AST parse và `git diff --check`: pass.

Các test toàn archive không thể chạy sạch tuyệt đối vì gói nguồn ban đầu thiếu một số module `tools.*` và file C# `body/SubjectPerformanceFrame.cs`. Đây là thiếu đầu vào của archive, không phải lỗi của thay đổi V17.

## Giới hạn còn lại

- Review nhận thức hiện là phép biến đổi typed trong Subject Core, chưa gọi observer/memory/critic worker thành một graph lặp nhiều bước.
- Autonomous capability được biểu diễn bằng một coalition route tổng quát vì exact capability chỉ xuất hiện sau giai đoạn discovery.
- Executive model failure dùng policy fallback nằm trong Executive boundary và được audit với confidence `0.0`; không giả là lựa chọn có suy luận đầy đủ.
