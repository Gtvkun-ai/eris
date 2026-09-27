# ERIS Unified Agent + Tutor + Conversation Pacing V2

## 1. Mục tiêu

Bản này giải quyết một vấn đề rất cụ thể:

> ERIS có thể suy nghĩ sâu, có thể có một learning plan dài, nhưng **không được vì thế mà nói hết mọi thứ trong một lượt**.

Một turn public và một turn reasoning là hai khái niệm khác nhau.

- **Reasoning rhythm**: ERIS cần suy nghĩ bao nhiêu vòng để hiểu vấn đề.
- **Pedagogical rhythm**: nếu đang dạy, user đang hiểu đến đâu và bước sư phạm tiếp theo là gì.
- **Conversation rhythm**: lượt này ERIS nên nói bao nhiêu để user còn theo kịp và còn cơ hội chen vào.

Ba nhịp trên được phối hợp, nhưng không được nhập thành một owner khổng lồ.

---

## 2. Architecture chốt

```text
                              USER TURN
                                  │
                                  ▼
                         ConversationRuntime
                                  │
                    load DisclosureArc trước đó
                                  │
                                  ▼
                    ╔════════════════════════╗
                    ║     TURN AGENT LOOP    ║
                    ║   root loop duy nhất   ║
                    ╚═══════════╤════════════╝
                                │
                             observe
                                │
                         SituationModel
                                │
                         CognitivePlan
                                │
                         ExecutionPlan
                                │
                   ┌────────────┼────────────┐
                   │            │            │
                general       coding       tutor
                                            │
                                            ▼
                                   TutorRoleCoordinator
                                            │
                              ┌─────────────┴─────────────┐
                              │                           │
                       TutorExecutive               LearningService
                       soft reasoning               durable truth
                              │                           │
                       TeachingMove                 evidence/mastery
                              │                           │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                                    root loop re-plan
                                            │
                                            ▼
                                      DiscoursePlan
                                            │
                                            ▼
                                   ConversationDirector
                                            │
                              ┌─────────────┼─────────────┐
                              │             │             │
                       disclosure mode   speech budget  continuation
                              │             │             │
                              └─────────────┼─────────────┘
                                            │
                                      1..N DialogueBeat
                                            │
                                            ▼
                                       Public Writer
                                            │
                                            ▼
                                      exact public text
                                            │
                               delivery receipt / TTS
                                            │
                         ┌──────────────────┴──────────────────┐
                         │                                     │
                    tutor receipt                      DisclosureArc commit
                         │                                     │
              exact delivered text                    deferred threads
                         │                                     │
                         └──────────────────┬──────────────────┘
                                            │
                                      HARD TURN STOP
                                            │
                                            ▼
                                           USER
```

### Quy tắc quan trọng nhất

**Chỉ có một root loop: `TurnAgentRuntime`.**

Tutor không có quyền tạo một conversation loop song song. Coding cũng không. Research cũng không.

Các hệ đó là **role/capability** cung cấp dữ liệu hoặc action cho root loop.

---

## 3. Vì sao cần ba loại plan

### CognitivePlan — ERIS cần hiểu gì?

Ví dụ user hỏi:

> INTP 538 là gì?

ERIS có thể cần hình thành analysis map:

```text
- lõi 5
- ảnh hưởng fix 3
- ảnh hưởng fix 8
- vì sao khác stereotype INTP
- vì sao dễ giống INTJ
- Ti/Ne biểu hiện ra sao
- Fe yếu trông như thế nào
- stress pattern
```

Danh sách này là **cognitive coverage**, không phải danh sách bắt buộc phải đọc ra.

### ExecutionPlan — ERIS còn phải làm gì?

Ví dụ với repo:

```text
- inspect orchestrator
- tìm state owner
- so với coding loop
- verify completion
- run tests
```

ExecutionPlan quyết agent có được COMPLETE chưa.

### DiscoursePlan — ERIS nên nói gì *lúc này*?

Đây là phần V2 siết mạnh.

```text
CognitivePlan biết 8 ý.
DiscoursePlan turn này chỉ reveal 1 ý.
7 ý còn lại vẫn được giữ.
```

Không còn giả định:

```text
biết => phải nói
```

---

## 4. DisclosureMode

### `conversational`

Dùng cho hội thoại khám phá bình thường.

Ví dụ:

> “INTP 538 là gì?”

ERIS có thể biết cả profile nhưng chỉ nói:

```text
INTP 538 khá khác stereotype INTP. Core 5 vẫn rất rõ,
nhưng 3 với 8 làm kiểu này chủ động và cứng hơn bình thường;
bởi vậy nhìn ngoài đôi lúc còn giống INTJ.
```

Rồi dừng.

Không tự thêm:

- tình yêu;
- công việc;
- điểm mạnh;
- điểm yếu;
- stress;
- 20 bullet khác.

### `deep_dialogue`

User muốn đào sâu, nhưng vẫn muốn trao đổi qua lại.

Mỗi turn được vài beat liên quan, sau đó dừng ở breakpoint tự nhiên.

### `report`

Chỉ dùng khi user thật sự yêu cầu kiểu:

- “viết full cho tôi”;
- “làm báo cáo đầy đủ”;
- “phân tích tất cả trong một lần”.

Report được budget lớn hơn.

---

## 5. Speech budget khác token budget

`TurnSpeechBudget` gồm:

```python
TurnSpeechBudget(
    target_words=...,
    hard_max_words=...,
    max_beats=...,
    target_seconds=...,
)
```

### Voice/TTS

Với `conversational + voice`:

```text
max_beats = 1
hard_max_words ~= 120
```

Với `deep_dialogue + voice`:

```text
max_beats = 2
hard_max_words ~= 180
```

Report voice vẫn lớn hơn, nhưng bị giới hạn rõ ràng.

Lý do: 1.600 chữ text có thể đọc lướt. 1.600 chữ TTS là một bài lecture mà user rất khó chen vào.

### Nguyên tắc

> **ERIS nghĩ dài, có kế hoạch dài, nhưng nói theo nhịp ngắn.**

---

## 6. Deferred không có nghĩa forgotten

`ContinuationPlan`:

```python
ContinuationPlan(
    active_thread="INTP 538 khác stereotype",
    deferred_threads=(
        "fix 3",
        "fix 8",
        "vì sao dễ nhầm INTJ",
    ),
    continuation_anchor="538 làm Ti-dom trông cứng hơn bình thường",
    next_if_continue="giải thích INTJ mistype",
)
```

Lượt này writer chỉ được dùng `beats` đã reveal.

`deferred_threads` là **phần cấm dump trong reply hiện tại**.

Lượt sau user hỏi:

> sao giống INTJ?

Root loop nhận lại DisclosureArc cũ và thấy đây chính là latent thread đã có.

Nó có thể tiếp tục từ đó thay vì bắt đầu phân tích lại từ số 0.

---

## 7. Không tự nói tiếp khi đã để dành ý

Repo cũ có `social continuation` và `conversation_arc` có thể tự schedule afterbeat sau audio.

Điều đó xung đột trực tiếp với progressive disclosure:

```text
ERIS: “Tôi để ý này cho lượt sau.”
        ↓
runtime cũ 0.6s sau tự nói tiếp chính ý đó
```

V2 thêm khái niệm:

```python
AgentTurnResult.reserves_user_floor
```

Nếu:

- `disclosure_mode` là conversational/deep_dialogue;
- có deferred thread; hoặc
- tutor đang chờ user trả lời;

thì autonomous afterbeat/conversation arc bị suppress.

ERIS **thật sự nhường lượt cho user**.

---

## 8. Tutor phối hợp với root loop như thế nào

### Sai

```text
TurnAgentLoop
TutorLoop
ConversationLoop
```

Ba loop độc lập sẽ tranh state, tranh writer và tranh quyền WAIT.

### Đúng

```text
TurnAgentLoop
    │
    └── TutorRoleCoordinator
            │
            └── TutorExecutive
```

Tutor đóng góp **pedagogical intent**, không public text.

Ví dụ:

```text
TutorExecutive:
    move = socratic_question
    kp = Ti vs Te
    requires_user_response = true
```

Root loop đọc move đó.

ConversationDirector quyết:

```text
voice mode
+ requires response
=> max_beats = 1
=> nói đúng một câu hỏi
=> HARD WAIT
```

---

## 9. Pending tutor response không được chấm bừa

Khi tutor đang chờ user trả lời, generic root executive phân loại user turn:

```text
answer
clarification
interrupt
none
```

### `answer`

Được đưa cho semantic assessor.

### `clarification`

Không tạo LearningEvidence.

ERIS chỉ làm rõ/rephrase câu hỏi rồi tiếp tục chờ.

### `interrupt`

Không chấm.
Không kéo lesson trở lại ngay.
Root conversation chuyển theo user.

Đây là invariant quan trọng để câu:

> “khoan, nói chuyện khác trước”

không bị tutor hiểu thành một câu trả lời sai.

---

## 10. Exact delivery binding

Một lỗi rất dễ xảy ra ở tutor LLM:

```text
Tutor intent: hỏi A
Writer diễn đạt: thành câu B
Assessor turn sau: lại chấm theo A
```

V2 bind receipt:

```text
TeachingMove
    ↓
Writer
    ↓
EXACT PUBLIC TEXT
    ↓
TutorState.last_delivery_text
    ↓
Semantic assessor turn sau
```

Assessor được chỉ thị:

> Nếu wording thực tế khác intent trước writer, chấm theo câu user đã thực sự nhận.

Receipt vẫn giữ invariant:

```text
planned speech != delivered speech
```

`note_taught()` chỉ chạy sau public commit thành công.

---

## 11. Learning truth vẫn deterministic

Tutor không được tự tăng mastery.

```text
semantic model
    ↓
suggest assessment
    ↓
TutorExecutive confidence gate
    ↓
LearningService.commit_evidence()
    ↓
recompute mastery
```

`AdaptiveEngineeringLearning` khi được inject `LearningService` chỉ còn là compatibility projection/cache.

Không còn hai durable mastery truth chạy song song.

---

## 12. Lifecycle ví dụ hoàn chỉnh

### Turn 1

User:

> INTP 538 là gì?

Root loop phân tích nhiều nhánh.

```text
CognitivePlan:
    8 nhánh

DiscoursePlan:
    reveal: overview
    defer: 3, 8, INTJ, Fe, stress...

voice budget:
    1 beat
```

Public:

```text
INTP 538 khá khác stereotype INTP. Lõi 5 vẫn rất rõ,
nhưng 3 với 8 làm kiểu này chủ động và cứng hơn bình thường;
bởi vậy nhìn ngoài đôi lúc còn giống INTJ.
```

STOP.

### Turn 2

User:

> sao giống INTJ?

DisclosureArc cũ:

```text
active_thread = INTP 538
latent/deferred contains INTJ mistype
```

Root loop chọn đúng thread đó.

Nói 1-2 ý.

STOP.

### Turn 3

User:

> tôi vẫn không hiểu Ti với Te khác ở đâu

Root loop kích hoạt tutor role mạnh hơn.

Tutor:

```text
move = socratic_question
requires_user_response = true
```

ConversationDirector:

```text
1 beat only
```

ERIS hỏi một câu.

HARD WAIT.

### Turn 4

User trả lời.

Root executive:

```text
tutor_response_relation = answer
```

Tutor assessor nhìn:

- KP;
- TeachingMove;
- **exact last_delivery_text**;
- câu user hiện tại.

Nếu đủ confidence -> evidence.

Tutor tạo move tiếp.
Root loop re-plan.
ConversationDirector lại quyết nói bao nhiêu.

---

## 13. Ownership table

| Concern | Owner |
|---|---|
| Có cần loop thêm không? | `TurnAgentRuntime + CompletionGate` |
| ERIS cần hiểu gì? | root semantic executive / `CognitivePlan` |
| Tool/coding/research work còn gì? | `ExecutionPlan` + capability runtime |
| User đang hiểu bài ra sao? | `TutorExecutive/TutorReasoner` |
| Mastery/evidence thật | `LearningService` |
| Lượt này nói gì? | `ConversationDirector` |
| Lượt này nói bao nhiêu? | `TurnSpeechBudget` |
| Ý nào để dành? | `ContinuationPlan/DisclosureArcLedger` |
| Câu chữ public cuối | Public Writer |
| Đã thật sự nói chưa? | public delivery receipt |
| Có tự afterbeat tiếp không? | root `reserves_user_floor` gate |

Không owner nào được tự kiêm hết các quyền trên.

---

## 14. Files chính

```text
runtime/agent_loop/
├── contracts.py      # typed plan + speech/continuation contracts
├── reasoner.py       # structured Turn Executive model boundary
├── completion.py     # deterministic stop gate
├── director.py       # disclosure + voice pacing
├── pacing.py         # state qua nhiều turn
├── tutor_role.py     # bridge generic loop <-> tutor
└── runtime.py        # ROOT LOOP

runtime/tutor/
├── contracts.py
├── policy.py
├── reasoner.py
├── model_reasoner.py
├── executive.py
└── composition.py
```

Integration:

```text
runtime/ai_orchestrated/orchestrator.py
runtime/ai_orchestrated/model_router.py
runtime/ai_orchestrated/planner.py
runtime/coordinator.py
runtime/engineering_mentor.py
runtime/adaptive_engineering_learning.py
runtime/learning_core/service.py
```

---

## 15. Tests khóa invariant

Test mới kiểm tra trực tiếp:

- voice conversational: 3 ý biết nhưng chỉ nói 1 beat;
- phần còn lại đi vào deferred thread;
- deep-dialogue voice chỉ nói tối đa 2 beat;
- report text có thể reveal nhiều hơn;
- turn sau nhận lại DisclosureArc trước đó;
- tutor answer được assess rồi root loop re-plan;
- tutor question tạo HARD WAIT;
- tutor interrupt không bị chấm thành evidence;
- exact public tutor text được bind vào TutorState;
- progressive turn reserve user floor, chặn autonomous afterbeat;
- legacy learning/pedagogical/chat/TTS tests quanh vùng sửa vẫn xanh.

Targeted suite hiện tại:

```text
212 passed
```

Full suite của source không thể dùng làm green gate hiện tại vì source gốc đã có lỗi độc lập, ví dụ:

```text
ModuleNotFoundError: tools.run_v103_nervous_replay
```

và runtime scenario đầu tiên được kiểm tra cũng fail y hệt trên source gốc (`foreground.kind` missing).

---

## 16. Invariant ngắn gọn để review code sau này

```text
1. Mỗi user turn = một TurnAgentLoop.
2. Tutor là role, không phải root loop thứ hai.
3. Cognitive coverage != public disclosure.
4. deferred != forgotten.
5. Voice budget != token budget.
6. Tutor requires response => một move => hard stop.
7. User interrupt không được biến thành learning evidence.
8. planned move != delivered text.
9. Assessor chấm theo exact delivered text.
10. LearningService là mastery truth duy nhất.
11. Progressive disclosure reserve floor cho user.
12. Existing autonomous afterbeat không được phá hard stop/pacing.
```


## 17. Giới hạn hiện tại và lý do cố ý giữ rõ ràng

### 17.1 Conversation identity qua restart

`DisclosureArcLedger` có thể persist bằng SQLite, nhưng persistence chỉ có ý nghĩa khi runtime đưa vào một `session_id` ổn định. Orchestrator hiện resolve theo thứ tự:

```text
conversation_id
    ↓ nếu chưa có
thread_id
    ↓ nếu chưa có
runtime_session_id
    ↓
default
```

Nếu deployment hiện tại chỉ có `runtime_session_id` và ID đó đổi sau process restart, arc cũ vẫn còn trong store nhưng turn mới không tự biết phải nối vào key cũ. Đây là vấn đề identity của ConversationRuntime, **không phải reason để nhét heuristic đoán thread vào agent loop**. Khi host expose stable `conversation_id`, V2 tự dùng nó mà không cần đổi contract.

### 17.2 Public writer vẫn render một lần mỗi turn

V2 loop có thể suy nghĩ nhiều iteration và ConversationDirector có thể giữ lại nhiều latent thread, nhưng public text cuối cùng vẫn được render bởi một writer call cho các `DialogueBeat` đã được phép reveal. Đây là cố ý: trước khi chuyển sang streaming từng segment, cần giữ receipt/TTS/public-commit atomic và dễ audit.

### 17.3 Không tự nói tiếp khi user chưa trả lời

Nếu còn deferred thread trong conversational/deep-dialogue mode, V2 **giữ floor cho user** và chặn afterbeat/conversation-arc autonomous continuation cũ. Deferred thread là kế hoạch để tiếp tục khi user tương tác lại, không phải timer để ERIS tự mở miệng.
