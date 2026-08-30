# V80 — Eris Engineering Mentor

## 1. Mục tiêu

V80 không biến Eris thành coding agent thứ hai.

GitPilot vẫn sở hữu toàn bộ execution:

```text
Explorer -> Planner -> Coder -> Reviewer
```

Eris Desktop chỉ làm:

```text
observe -> hiểu flow -> hiểu cách user đang học/làm việc -> chọn cách dạy -> bàn luận với user
```

Điểm khác biệt của V80 nằm ở **human development layer**, không nằm ở patch engine/tool mới.

---

## 2. Ba khối mới

### `UserEngineeringSkillModel`

Đây là projection nhỏ về năng lực kỹ thuật có evidence. Nó không lưu raw chat và không thay thế Living User Memory.

Các skill hiện có:

```text
debugging.failure_localization
debugging.call_flow_tracing
debugging.root_cause_reasoning
verification.testing
verification.diff_review
architecture.system_boundaries
ai_operation.task_scoping
ai_operation.evidence_review
```

Mỗi skill giữ:

```text
level
confidence
evidence_count
last_observed_at
notes
```

**Quan trọng:** nhờ AI làm việc không làm tụt skill score.

Agent chạy ngu cũng không làm tụt skill score của user.

### `overreliance_risk`

Đây là một trục riêng.

Ví dụ user liên tục nói:

```text
fix code đi, làm luôn
```

mà không có review/learning/hypothesis thì risk tăng từ từ.

Nó không đồng nghĩa "user yếu".

Nếu user chủ động hỏi review/test/diff hoặc muốn hiểu cơ chế, risk giảm.

---

### `EngineeringTeachingPolicy`

Policy chọn một trong các stance:

```text
none
  không phải chuyện kỹ thuật

discuss
  bàn luận như đồng nghiệp

explain
  giải thích cơ chế rõ từ nền tảng

guide
  chỉ từng bước debug/analysis

hint
  user đã có khả năng, chỉ đưa manh mối

challenge
  bắt user tự kiểm tra mắt xích quan trọng

warn
  nói thẳng khi pattern vibe-code mù lặp lại
```

`warn` được phép tự nhiên và hơi gắt, nhưng không được xúc phạm intelligence/nhân phẩm.

Ví dụ stance đúng:

> Bạn đang giao task mù hơi nhiều rồi. Task này đọc diff trước, rồi trace call-flow của hai file này. Nếu không làm bước đó thì bạn sẽ mất dần khả năng tự định vị lỗi.

Không nên nói:

> Bạn ngu quá.

Mục tiêu là chỉnh hành vi, không hạ nhục người dùng.

---

## 3. V80 học từ evidence nào?

### Positive evidence về skill

Ví dụ user tự nêu hypothesis kèm file/symbol:

```text
Tôi nghĩ lỗi do coordinator.py gọi service sai lifecycle.
```

Đây là evidence cho root-cause reasoning/call-flow tracing.

User chủ động yêu cầu:

```text
review diff
test regression
kiểm tra verification
```

là evidence tích cực về review discipline.

### Không phải evidence user yếu

Các trường hợp sau **không được phép tự hạ skill**:

```text
user nhờ GitPilot code
GitPilot test fail
GitPilot retry ngu
Coder sửa scope rộng
user hỏi để học
```

Hỏi để học là hành vi tốt, không phải bằng chứng thiếu năng lực.

---

## 4. V79 -> V80 flow

```text
GitPilot event
   |
   v
CodingObservationService (V79)
   |
   +--> coding journal
   |
   +--> CodingFlowInterpreter
              |
              v
       flow findings
              |
              v
EngineeringMentorService (V80)
   |
   +--> UserEngineeringSkillModel
   |
   +--> EngineeringTeachingPolicy
   |
   v
ENGINEERING_MENTOR_V80 prompt context
   |
   v
Eris public writer
```

Không có arrow ngược từ Mentor sang GitPilot.

---

## 5. Freshness

Flow coding cũ không được giả làm context hiện tại.

V80 chỉ dùng flow:

- đang `running`; hoặc
- vừa kết thúc trong khoảng 6 giờ.

Một task hôm qua không được tự động kéo vào câu chuyện hôm nay.

---

## 6. Privacy / persistence

Model lưu tại:

```text
<ERIS_HOME>/mentor/engineering_skill_model.json
```

File này chỉ lưu score, confidence, evidence ref ngắn và signal label.

Không lưu nguyên câu user.

Coding journal V79 vẫn nằm riêng:

```text
<ERIS_HOME>/logs/coding_observations.jsonl
```

---

## 7. Audit

Khi Eris Link bật:

```text
GET /v1/mentor/state
```

cho phép xem read-only:

- skill projection;
- overreliance risk;
- flow gần nhất;
- mentor decision gần nhất.

Không có:

```text
POST /v1/mentor/state
POST /v1/mentor/set-level
POST /v1/mentor/force-mode
```

Skill estimate không được sửa lén qua bridge.

---

## 8. Boundary tuyệt đối

V80 không thêm:

```text
Eris Coder
Eris Planner
Eris Reviewer
Eris terminal tool
Eris patch engine
Eris code search engine
```

Nếu cần coding capability mới, ưu tiên GitPilot/upstream/MCP/LSP/VS Code API.

Eris chỉ tự xây thứ tạo khác biệt:

```text
observation
memory
interpretation
user modeling
teaching
supervision
```

---

## 9. V80 chưa làm gì?

V80 chưa phải V81 adaptive-learning hoàn chỉnh.

Chưa có:

- quiz tự động;
- teach-back scoring;
- curriculum dài hạn;
- misconception recurrence graph;
- spaced practice;
- skill decay theo thời gian;
- project-specific skill graph sâu.

V80 chỉ đặt **mentor spine đủ sạch và đủ dùng thật**.

V81 mới nên thêm deliberate practice sau khi quan sát V80 ngoài đời.
