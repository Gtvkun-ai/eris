# Eris V18: MindLoop thống nhất Executive và Subject Core

## Mục tiêu

V17 đã sửa đúng quan hệ quyền lực: Subject Core cung cấp nền, Executive chọn và cam kết. Tuy nhiên orchestration còn lặp ở nhiều nơi, cognitive review vẫn là chuỗi lệnh được `SubjectService` tự diễn giải, và `SubjectRuntime.bind_executive()` tạo mutable wiring sau bootstrap.

V18 refactor các phần đó mà không làm giảm độ sâu của hệ.

## Luồng production mới

```text
WorldObservation
    ↓
SubjectService.prepare_deliberation()
    ↓
DeliberationSession(PREPARED)
    ↓
Executive.commit_subject_frame()
    ├─ commit ngay
    └─ yêu cầu cognitive review bounded
           ↓
       SubjectCognitionPort.execute()
           ↓
       CognitiveReviewResult có kiểu + evidence
           ↓
       SubjectService.integrate_cognitive_results()
           ↓
       DeliberationSession(REVISED)
           ↓
       Executive commit lại trên frame mới
    ↓
SubjectService.finalize_deliberation(commit bắt buộc)
    ↓
MindDecision + AuthorshipDraft
    ↓
Dialogue hoặc Actuator → WorldOutcome → learning
```

`MindLoop` chỉ là coordinator. Nó không giữ motive, belief hay value và không phải một “siêu Executive” mới.

## Thay đổi kiến trúc

### 1. Một MindLoop duy nhất

File mới: `runtime/mind_loop.py`.

Cả chat, autonomous và `SubjectRuntime.handle()` đều dùng cùng một vòng:

- prepare;
- gọi Executive;
- thực hiện tối đa một review bounded;
- yêu cầu Executive commit lại;
- finalize;
- abandon fail-closed khi không có commit hợp lệ.

Orchestration không còn bị sao chép trong `SubjectIngress` và `SubjectRuntime`.

### 2. Bỏ `bind_executive()`

`SubjectRuntime` không còn method mutable binding.

Composition root inject một `executive_provider` vào `MindLoop` ngay khi dựng Subject Core:

```python
executive_provider=lambda: getattr(host, "ai_executive_cortex", None)
```

Provider được resolve tại thời điểm deliberation. Vì vậy Executive có thể được bootstrap sau Subject Core mà không cần cắm dependency trở lại bằng setter.

### 3. Cognitive review có kiểu

Các file mới:

- `cortex/subject/deliberation.py`
- `runtime/subject_cognition.py`

Executive vẫn yêu cầu các capability như:

- `verify_evidence`;
- `reduce_intrusion`;
- `preserve_continuity`;
- `estimate_capability`;
- `inspect_dissent`.

Nhưng `SubjectService` không còn xử lý chuỗi request và tự cộng/trừ scalar. Cognitive adapter trả:

```text
CognitiveReviewResult
  request_kind
  confidence
  evidence_refs
  ProposalAdjustment[]
```

Domain integrator kiểm tra:

- result có nhắm đúng frame không;
- proposal có thật trong frame không;
- delta có nằm trong biên không;
- giá trị sau tích hợp vẫn ở `[0, 1]`;
- cognitive layer không được tạo proposal mới hoặc đổi `action_kind`.

### 4. Finalize bắt buộc có Executive commit

Chữ ký mới:

```python
await SubjectService.finalize_deliberation(frame, commit)
```

`commit` không còn nullable. Fallback cho test/caller độc lập được triển khai như một `FallbackSubjectExecutive`, tức vẫn tạo commit explicit và để authorship ghi đúng nguồn.

Production không còn cửa để Subject Core tự chọn rồi tự nhận quyền tác giả.

### 5. Autonomous dùng DeliberationSession

`self_turn_pipeline.py` không còn tự quản `frame → commit → finalize`.

Nó:

1. tạo `prepare_autonomous_session()`;
2. cho Executive deliberation trên `session.frame`;
3. gọi `complete_autonomous_turn()`;
4. nếu review làm coalition ID đổi, commit được build lại từ cùng Executive outcome trên frame mới.

Điều này tránh dùng một commit đã hết hiệu lực sau khi rerank.

### 6. Proposal source tách khỏi ingress

File mới: `runtime/subject_proposals.py`.

Affordance, silence, body-only và đường capability-grounded đều được chuyển thành cùng proposal schema qua `AutonomousProposalSource`.

`SubjectIngress` chỉ còn:

- tạo `WorldObservation`;
- tạo session;
- chuyển session cho `MindLoop`.

### 7. Audit và authorship

Audit vẫn phân biệt rõ:

```text
raw_observation
substrate_projection
appraisal_projection
need_activation
deliberation_frame
cognitive review result
deliberation_review
executive_commit
mind_decision
authorship_draft
world_outcome
learning
```

`selected_by` dùng `commit.source`, nên fallback, compatibility adapter và Executive thật không bị trộn thành cùng một nguồn quyền lực.

## API migration

### Production

Dùng `SubjectIngress` được tạo với `components.mind_loop`:

```python
components = build_subject_core_components(
    executive_provider=lambda: host.ai_executive_cortex,
)

ingress = SubjectIngress(
    components.subject_service,
    mind_loop=components.mind_loop,
)
```

### Adapter V17 còn giữ tạm

Các method sau vẫn tồn tại để module cũ chuyển dần:

- `prepare_user_turn()` trả frame;
- `prepare_autonomous_turn()` trả frame;
- `finalize(frame, commit)`;
- `abandon(frame, reason=...)`.

Đường production mới không dùng các adapter này.

## Phiên bản

```text
subject-service-v10-mind-loop
```

## Kiểm thử

Kết quả trên archive được cung cấp:

- 64 test trực tiếp cho Subject Core, Executive, MindLoop và opening callback: pass.
- Toàn bộ suite có thể thu thập từ archive: 835 pass.
- 3 file test không thể collect do archive thiếu `tools.package_source` và `tools.evaluate_social_plan_activation`.
- 6 test còn lại thất bại vì archive thiếu các module `tools.*` khác và file ngoài archive `body/SubjectPerformanceFrame.cs`.

Các lỗi thiếu file/module này đã tồn tại ở đầu vào V17 và không liên quan thay đổi V18.
