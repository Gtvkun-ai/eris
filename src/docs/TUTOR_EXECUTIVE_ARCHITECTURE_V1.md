# Tutor Executive V1 — kiến trúc tutor agent cho Eris

## 1. Mục tiêu

Tutor không nên là một chuỗi `if mastery < x -> explain` và cũng không nên để LLM tự ý quyết định mọi thứ.
Kiến trúc này tách **semantic intelligence** khỏi **learning truth** và **delivery runtime**.

```text
USER TURN
   │
   ▼
TutorExecutive
   │
   ├─ OBSERVE ───────────────► context bounded
   │
   ├─ DIAGNOSE ──────────────► LearnerHypothesis[]
   │                              │
   │                              └─ chỉ là giả thuyết mềm
   │
   ├─ LearningService.next_tutor_step()
   │          │
   │          └─ deterministic: probe / teach / assess / review / advance
   │
   ├─ TutorGuardrailPolicy
   │          │
   │          └─ tạo MoveEnvelope: model được phép làm gì trong turn này
   │
   ├─ TutorReasoner.choose_move()
   │          │
   │          └─ semantic strategy: Socratic / counterexample / analogy / practice...
   │
   ▼
TeachingMove
   │
   ▼
Writer / PedagogicalRuntime
   │
   ▼
USER RESPONSE
   │
   ▼
TutorReasoner.assess_response()
   │
   ▼
SemanticAssessment
   │
   ├─ confidence thấp / uncertain ─► KHÔNG commit mastery
   │
   └─ đủ chắc ─────────────────────► LearningService.commit_evidence()
                                      │
                                      ├─ append-only evidence
                                      ├─ recompute mastery
                                      └─ update spaced review
```

## 2. Owner của từng trách nhiệm

| Thành phần | Sở hữu | Không được sở hữu |
|---|---|---|
| `LearningService` | path, evidence, mastery, SRS, pending interaction | câu chữ, semantic strategy |
| `TutorExecutive` | tutor loop, session hypothesis, orchestration | mastery truth, public rendering |
| `TutorReasoner` | diagnosis semantic, teaching strategy, semantic assessment | commit DB trực tiếp |
| `TutorGuardrailPolicy` | phase constraints deterministic | hiểu nội dung học |
| `PedagogicalRuntime` | dwell, claim, receipt, delivery lifecycle | learner truth |
| Writer | biến `TeachingMove` thành lời nói tự nhiên | đổi mastery / tự chấm user |

## 3. Vì sao cách này giống tutor người hơn

Tutor tốt không chỉ hỏi “đúng hay sai?”. Tutor duy trì một mô hình mềm:

- user đang biết gì;
- user đang nhầm boundary nào;
- đây là thiếu kiến thức hay thiếu prerequisite;
- nên giải thích, hỏi ngược, đưa counterexample hay bắt thực hành;
- phản ứng của user có xác nhận giả thuyết trước đó không.

`LearnerHypothesis` tồn tại chính cho lớp suy luận này. Nó **không phải learner truth lâu dài**. Nếu user chứng minh hiểu, hypothesis được resolve để tránh tutor “đóng khung” người học.

## 4. Hai lớp quyết định thay vì một state machine khổng lồ

### Lớp 1 — Learning policy deterministic

`LearningService.next_tutor_step()` quyết định phase:

```text
probe -> teach -> practice/assess -> advance
                  ↑
                review
```

Lớp này cố ý boring, test được, không phụ thuộc model.

### Lớp 2 — Semantic teaching strategy

Trong phase `teach`, model vẫn có thể chọn:

```text
explain
analogy
worked_example
counterexample
Socratic question
repair misconception
```

Nhưng model chỉ được chọn trong `MoveEnvelope` do policy cấp.

Kết quả: **linh hoạt như agent nhưng không mất kiểm soát như agent tự do hoàn toàn**.

## 5. Invariant quan trọng

1. LLM chỉ đề xuất; deterministic layer mới commit.
2. `expected_answer` không xuất hiện trong `TeachingMove` hay writer context.
3. Semantic assessment confidence thấp không được đổi mastery.
4. Một user interruption không tự động bị xem là câu trả lời tutor; caller phải xác nhận `response_to_previous_move`.
5. “Đã generate lời dạy” không đồng nghĩa “đã dạy”: `commit_delivery()` chỉ chạy sau receipt thành công.
6. Tutor hypothesis có thể sai, phải có lifecycle `active -> resolved/rejected`.
7. Không lưu chain-of-thought; chỉ lưu structured diagnosis summary ngắn để debug/audit.

## 6. Trạng thái integration hiện tại

Đã làm trong V1:

1. Coordinator tạo đúng một `LearningService` + `TutorExecutive` bằng `build_tutor_runtime()`.
2. `RuntimeTutorReasoner` đã nối vào `AIRuntimeModelRouter.invoke_structured_worker()`.
3. `AdaptiveEngineeringLearning` khi được Coordinator inject kernel đã trở thành adapter/projection: demonstration và misconception đi qua append-only evidence; không tự mutate mastery nữa. Caller/test legacy không inject kernel vẫn giữ compatibility mode tạm thời.
4. Delivery commit đã idempotent theo `move_id`; semantic response cũng có dedupe trong session.

Còn phải nối vào **hot path** trước khi gọi tutor hoàn tất:

1. Foreground orchestrator gọi `TutorExecutive.process_turn()` khi learning activation active.
2. Writer nhận `TutorDecision.to_writer_context()` thay vì để planner tự phát minh teaching strategy.
3. Sau public receipt thành công, gọi `TutorExecutive.commit_delivery()`.
4. Khi episode đang `waiting_user`, turn kế tiếp gọi với `response_to_previous_move=True`.
5. Nối deterministic `PendingInteraction` cho multiple-choice/true-false; semantic assessor chỉ xử lý câu trả lời tự do.
6. Sau khi hot path mới ổn định, xóa compatibility branch mutate mastery của `AdaptiveEngineeringLearning` và chạy migration JSON -> SQLite một lần.

## 7. Không nên làm

- Không gộp `TutorExecutive` vào `LearningService`: sẽ trộn reasoning semantic với truth deterministic.
- Không để writer chấm user.
- Không persist mọi hypothesis như một profile vĩnh viễn.
- Không tạo thêm persona “Tutor” tách khỏi Eris; đây là cognitive mode của cùng một Eris.
- Không để `next_tutor_step()` quyết định luôn wording/strategy; như vậy sẽ mechanical.
