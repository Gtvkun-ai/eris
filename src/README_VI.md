# ERIS Unified Agent + Tutor + Conversation Pacing V2

## Bản này làm gì?

Bản patch này hợp nhất ba cơ chế thành **một lifecycle foreground duy nhất**:

1. **TurnAgentLoop** — mọi user turn đều là một agent run; agent được phép lặp nhiều iteration để phân tích, kiểm tra và lập kế hoạch.
2. **TutorRole** — tutor là role bên trong root loop, không tạo conversation loop thứ hai; `LearningService` vẫn là nguồn sự thật về evidence/mastery.
3. **Conversation pacing** — ERIS có thể biết/phân tích rất nhiều, nhưng mỗi turn chỉ public lượng thông tin phù hợp. Phần cố tình chưa nói được giữ thành `deferred_threads` để dùng ở lượt sau.

Mục tiêu thực tế: **ERIS nghĩ dài, có kế hoạch dài, nhưng nói theo nhịp người nghe**. Đặc biệt trong voice/TTS, turn public được cắt theo *speech budget*, không phải token budget.

---

## Lifecycle một turn

```text
USER
  ↓
load DisclosureArc của conversation
  ↓
TurnAgentRuntime                         ← root loop duy nhất
  ↓
CognitivePlan  : cần hiểu gì?
ExecutionPlan  : còn phải làm gì?
  ↓
TutorRoleCoordinator (nếu cần)
  ├─ answer        → semantic assess → evidence
  ├─ clarification → không chấm
  └─ interrupt     → không chấm, nhường user
  ↓
root loop re-plan
  ↓
DiscoursePlan : nên nói gì lúc này?
  ↓
ConversationDirector
  ├─ DisclosureMode
  ├─ TurnSpeechBudget
  └─ ContinuationPlan/deferred_threads
  ↓
Public writer
  ↓
EXACT public text
  ├─ bind về TutorState để lần sau assessor chấm đúng câu đã nghe
  └─ commit DisclosureArc
  ↓
HARD TURN STOP / chờ USER
```

---

## Ba nhịp được tách riêng

### 1. Reasoning rhythm
Agent có thể chạy nhiều iteration nội bộ. Đây là nơi phân rã vấn đề, verify, xử lý tool result và chống premature completion.

### 2. Pedagogical rhythm
Tutor quyết định user đang cần `probe`, `teach`, `practice`, `assess`, `review`... nhưng **không tự public response**. Nếu tutor hỏi một câu cần user trả lời thì turn chuyển sang `waiting_user` và chỉ public một teaching move.

### 3. Conversation rhythm
`ConversationDirector` quyết định turn này reveal bao nhiêu ý. Một analysis map có 8 ý không có nghĩa response phải xổ 8 ý.

```text
8 ý ERIS đã hiểu
  ↓
voice + conversational
  ↓
public 1 beat
  ↓
7 ý giữ trong deferred_threads
  ↓
user phản ứng
  ↓
turn sau re-plan từ đúng thread
```

---

## Disclosure modes

- `conversational`: ưu tiên đối thoại qua lại; voice thường chỉ 1 beat.
- `deep_dialogue`: nói 1–2 beat liên quan rồi dừng ở breakpoint tự nhiên.
- `report`: user thật sự muốn câu trả lời đầy đủ trong một lượt, nên budget được nới rộng.

Model có thể đề xuất budget **thấp hơn**, nhưng không được tự nới vượt guardrail mặc định của runtime.

---

## Tutor phối hợp thế nào?

Tutor không còn là root loop. `TutorRoleCoordinator` chỉ đóng góp pedagogical intent vào generic turn state.

- User đang trả lời câu tutor trước → `response_relation=answer` → mới được semantic assess.
- User hỏi lại → `clarification` → không tạo evidence.
- User đổi chủ đề → `interrupt` → không chấm và không kéo bài học quay lại.
- Teaching move yêu cầu response → public tối đa 1 beat → `waiting_user` → hard stop.
- Assessor được đưa **exact delivered text**, không chỉ planned `TeachingMove`, nên tránh bug “hỏi câu B nhưng chấm theo ý định A”.

---

## Learning truth

`LearningService` vẫn authoritative:

```text
LLM/Tutor proposes
        ↓
semantic/deterministic assessment
        ↓
LearningEvidence append-only
        ↓
LearningService recompute mastery
```

`AdaptiveEngineeringLearning` khi được inject `LearningService` chỉ còn là adapter/projection, không tự tăng giảm durable mastery.

---

## Chặn hệ thống cũ tự chen lời

Repo đã có social `afterbeat` / `conversation_arc` có thể tự nói tiếp sau audio. V2 chặn continuation cũ khi:

- turn còn `deferred_threads` trong progressive conversation; hoặc
- tutor đang `waiting_user`.

Nếu không làm bước này thì speech pacing sẽ vô nghĩa: V2 vừa giữ ý lại xong, subsystem cũ lại tự nói tiếp ngay sau đó.

---

## Conversation identity

Disclosure state ưu tiên key theo:

```text
conversation_id → thread_id → runtime_session_id → default
```

`DisclosureArcLedger` có SQLite persistence nếu runtime có `SQLiteAtomicStateStore`. Continuity qua process restart chỉ thực sự đầy đủ khi host expose một `conversation_id`/`thread_id` ổn định. Patch **không đoán thread bằng heuristic** vì dễ nối nhầm hai cuộc hội thoại.

---

## File quan trọng

```text
runtime/agent_loop/
├── contracts.py      # typed contracts: plan, beat, speech budget, continuation
├── completion.py     # deterministic completion gate
├── director.py       # public pacing / progressive disclosure
├── pacing.py         # DisclosureArc per conversation
├── reasoner.py       # structured model decision contract
├── runtime.py        # ROOT LOOP duy nhất
└── tutor_role.py     # bridge TutorExecutive -> root loop

runtime/tutor/
├── contracts.py
├── executive.py
├── reasoner.py
├── model_reasoner.py
├── policy.py
└── composition.py

runtime/ai_orchestrated/orchestrator.py
runtime/ai_orchestrated/model_router.py
runtime/ai_orchestrated/planner.py
```

Tài liệu đầy đủ: `docs/UNIFIED_AGENT_TUTOR_CONVERSATION_V2_VI.md`.

---

## Test

Targeted regression suite quanh vùng thay đổi:

```text
212 passed
```

Nó khóa các case quan trọng:

- conversational voice: 3 beat model đề xuất → chỉ 1 beat được public;
- phần còn lại thành deferred thread và xuất hiện lại trong turn context sau;
- deep-dialogue voice tối đa 2 beat;
- report text được phép reveal nhiều hơn;
- tutor answer → assess → root re-plan;
- tutor clarification/interrupt không bị ghi nhầm evidence;
- tutor question → một move → hard wait;
- exact delivered tutor text được lưu để chấm turn sau;
- progressive turn reserve user floor, chặn afterbeat tự nói tiếp.

Full suite của source gốc **không thể dùng làm green gate** vì baseline đang có lỗi độc lập, gồm thiếu `tools.run_v103_nervous_replay`; một runtime scenario kiểm tra thêm cũng fail giống hệt trên source gốc.

---

## 12 invariant phải giữ khi phát triển tiếp

1. Mỗi user turn = một `TurnAgentLoop`.
2. Tutor/Coding/Research là role/capability, không phải root conversation loop riêng.
3. Cognitive coverage **không đồng nghĩa** public disclosure.
4. `deferred_threads` = cố tình chưa nói, **không phải đã quên**.
5. Voice/speech budget tách khỏi reasoning/token budget.
6. Tutor cần response → một teaching move → hard stop.
7. User interrupt/clarification không được biến thành learning evidence.
8. Planned teaching move không đồng nghĩa exact delivered text.
9. Semantic assessor phải biết câu user thực sự đã nhận.
10. `LearningService` là durable mastery truth duy nhất.
11. Progressive disclosure phải giữ floor cho user.
12. Autonomous afterbeat cũ không được phá hard stop/pacing của root loop.
