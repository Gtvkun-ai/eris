# V85 — Mentor Calibration & Trust

## 1. Vì sao cần V85?

Sau V84, Eris đã có đủ các mảnh chính:

```text
V79  Coding Observation
V80  Engineering Mentor
V80.1 Intervention Gate
V81  Adaptive Learning
V82  Tool Literacy
V83  Cross-environment Supervisor
V84  One-Eris role orchestration
```

Nhưng nếu Eris chỉ đánh giá user mà **không tự bị evidence đánh giá ngược lại**, Mentor vẫn có một lỗi kiến trúc: nó có thể ngày càng tự tin về chính phán đoán của mình.

V85 đóng feedback loop:

```text
intervention
   ↓
explicit feedback / observable learning evidence
   ↓
MentorOutcome
   ↓
calibration metrics
   ↓
confidence / friction policy
```

Không có LLM judge mới. Không có một “agent chấm agent”.

---

## 2. MentorOutcome: chỉ ghi thứ observable

V85 hỗ trợ các outcome hẹp:

```text
helpful
user_corrected_eris
user_already_knew
mentor_opt_out
too_verbose
teachback_evidence
unknown
```

Điểm quan trọng:

- user đổi chủ đề **không** đồng nghĩa ignored;
- im lặng **không** đồng nghĩa useful;
- hết 30 phút không có feedback → `unknown`, không phải failure;
- `helpful` chỉ đến từ feedback explicit kiểu “đúng rồi / tìm ra rồi / fix được rồi”;
- teach-back chỉ dựa trên evidence V81 đã nhận diện.

Không persist raw `user_text`.

---

## 3. User sửa Eris thì chuyện gì xảy ra?

Ví dụ:

```text
Eris: Có vẻ bạn đang yếu failure localization.
User: Không. Cái này tôi biết, hôm đó tôi chỉ lười.
```

V85 không làm:

```text
skill.level += vì user tự nói mình biết
```

và cũng không làm:

```text
Eris bảo vệ estimate cũ
```

Nó làm:

```text
outcome = user_already_knew
skill.level = giữ nguyên
skill.confidence = giảm
```

Tức user correction sửa **độ chắc chắn của belief**, không tự biến self-report thành mastery proof.

Nếu cùng turn user còn đưa grounded technical evidence, evidence đó vẫn được V80/V81 xử lý độc lập.

---

## 4. Confidence decay

Skill model trước đây có thể giữ confidence mãi dù evidence rất cũ.

V85 thêm `last_calibrated_at` và decay chậm:

```text
half-life ≈ 90 ngày
```

Quy tắc:

- `level` không tự giảm theo thời gian;
- `confidence` giảm;
- evidence mới reset calibration anchor;
- không decay liên tục mỗi lần UI đọc profile.

Điều này giúp Eris nói:

> “Tôi từng thấy bạn làm phần này khá ổn, nhưng evidence đó cũ nên tôi không chắc mức hiện tại.”

thay vì coi estimate 3 tháng trước là chân lý.

---

## 5. Mentor calibration directive

Từ outcome gần đây, V85 tạo directive:

```text
confidence_mode = normal | cautious
reduce_proactive_friction = true | false
```

Nếu user sửa Eris nhiều lần gần đây:

```text
confidence_mode = cautious
```

Public writer phải:

- nói dưới dạng hypothesis/evidence;
- chừa đường cho user sửa;
- không dùng skill estimate như fact.

Nếu user opt-out / chê dài nhiều:

```text
reduce_proactive_friction = true
```

Eris giảm proactive mentoring. Explicit `chỉ tôi / giải thích / review` vẫn được quyền đi qua.

---

## 6. Mentor Profile user-visible

Endpoint read-only mới:

```text
GET /v1/mentor/profile
```

Projection ví dụ:

```json
{
  "schema": "eris.mentor_profile.v1",
  "skills": [
    {
      "skill_id": "debugging.failure_localization",
      "label_vi": "khá",
      "estimate": 0.61,
      "confidence": 0.42,
      "evidence_count": 8
    }
  ],
  "ai_operation": {
    "overreliance_risk": 0.18
  }
}
```

Không expose internal notes.

### Tại sao endpoint vẫn read-only?

Eris Link hiện là loopback opt-in nhưng chưa có auth write-channel đủ sạch. V85 không mở:

```text
POST /v1/mentor/profile
```

vì process local khác có thể giả user correction/reset.

Thay vào đó có trusted **in-process API**:

```python
mentor.reset_skill_estimate(skill_id)
mentor.reset_mentor_profile()
```

để UI/chat user-control layer gọi sau khi đã xác định đúng user intent.

---

## 7. Offline Golden Replay

File:

```text
src/evals/mentor_golden_v85.json
src/evals/run_mentor_eval_v85.py
```

20 scenario cố định bao phủ:

- non-engineering → silent;
- explicit learning → Mentor-first;
- verification → Supervisor-first;
- fast execution bình thường → Companion-first;
- blind delegation lặp → strict Mentor;
- patch-before-inspection → challenge;
- heated bug language → Companion-first;
- scope expansion / missing verification;
- status check;
- grounded hypothesis;
- candidate misconception;
- old coding flow không được giả làm context hiện tại.

Runner không gọi model/provider. Vì vậy policy refactor có deterministic regression gate.

### Finding thật từ V85

Golden suite đã bắt một lỗi logic của V84:

```text
EngineeringTeachingPolicy: verification -> mode=guide
RoleOrchestrator: mode=guide -> Mentor-first
```

nên explicit verification bị nuốt bởi generic guide branch.

V85 sửa priority:

```text
explicit learning / candidate misconception -> Mentor-first
explicit verification/status             -> Supervisor-first
```

Đây là ví dụ lý do cần replay thay vì “nhìn có vẻ tự nhiên”.

---

## 8. Metrics

V85 aggregate local:

```text
interventions
helpful
user_corrected_eris
user_already_knew
mentor_opt_out
too_verbose
teachback_evidence
unknown
usefulness_rate
user_correction_rate
annoyance_rate
false_positive_criticism_proxy
```

`false_positive_criticism_proxy` chỉ là proxy:

> warn/challenge gần đó + user correction explicit

Không được gọi nó là bằng chứng tuyệt đối rằng Mentor sai.

---

## 9. Boundary

V85 KHÔNG:

- gọi GitPilot;
- sửa code;
- chạy test/debugger/profiler;
- approve task;
- thêm LLM judge;
- psychological profile user;
- block user vì vibe-code;
- gửi private skill model sang coding provider.

Kiến trúc vẫn là:

```text
GitPilot = coding authority
Eris    = observe + understand + teach + calibrate
User    = authority cuối cùng đối với correction và cách học
```

---

## 10. State

```text
<ERIS_HOME>/mentor/engineering_mentor_calibration.json
```

State chỉ chứa intervention/outcome metadata, không raw chat/source code/chain-of-thought.

Public writer prefix vẫn giữ `ENGINEERING_MENTOR_V84` để backward-compatible; payload có `release=V85`.
