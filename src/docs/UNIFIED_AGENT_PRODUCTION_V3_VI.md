# ERIS Unified Agent / Tutor / Conversation — Production V3

## 1. Mục tiêu của V3

V3 không thêm một “agent mới”. Nó **productionize** kiến trúc V2 để ba nhịp sau thực sự cùng sống trong foreground hot path:

1. **Reasoning rhythm** — mỗi user turn là một `TurnAgentLoop`, được quyền chạy nhiều iteration.
2. **Pedagogical rhythm** — Tutor chỉ là một role; `LearningService` giữ learning truth.
3. **Conversation rhythm** — Eris biết nhiều nhưng mỗi lượt chỉ nói lượng vừa nghe, đặc biệt khi TTS tiếng Nhật đang bật.

Câu ngắn gọn nhất để nhớ kiến trúc này:

> **Eris có thể nghĩ dài, có kế hoạch dài, nhưng nói theo từng nhịp và nhớ chính xác mình đang nói tới đâu.**

---

## 2. Owner map — lớp nào được quyền làm gì?

```text
Conversation / User turn
        │
        ▼
TurnAgentRuntime                     ROOT LOOP DUY NHẤT
        │
        ├── CognitivePlan            cần hiểu gì?
        ├── ExecutionPlan            còn việc gì phải làm?
        ├── role selection           tutor/coding/research/companion
        │
        ├── TutorRoleCoordinator     chỉ đóng góp pedagogical intent
        │       │
        │       └── TutorExecutive
        │              └── LearningService (mastery/evidence truth)
        │
        └── DiscoursePlan            lượt này nên nói gì?
                │
                ▼
        ConversationDirector         disclosure + speech pacing
                │
                ▼
            Public Writer            chỉ diễn đạt các beat đã được phép reveal
                │
                ▼
       pre-TTS Speech Hard Guard     seatbelt cuối nếu writer vẫn xổ dài
                │
                ▼
               TTS
```

### Quyền hạn cố ý tách rõ

- `TurnAgentRuntime`: quyết định loop tiếp/dừng, không viết public prose.
- `TutorExecutive`: chẩn đoán / teaching move / semantic assessment, không sở hữu public conversation.
- `LearningService`: nguồn sự thật duy nhất về mastery/evidence/path/review.
- `ConversationDirector`: quyết định **bao nhiêu ý được nói trong lượt này**.
- `Public Writer`: chỉ diễn đạt. Writer không được tự mở thêm deferred thread.
- `Speech Hard Guard`: không suy luận; chỉ chặn output voice vượt hard cap.

Không lớp nào được vừa “nghĩ”, vừa “chấm mastery”, vừa “quyết định pacing”, vừa “public text”.

---

## 3. Hot-path cutover

### Trước

```text
user
  ↓
local planner
  ↓
writer
  ↓
public
```

Ngay cả khi có subsystem agent khác, foreground chat vẫn có thể rơi về đường one-shot này.

### V3

```text
user
  ↓
TurnAgentRuntime                    bắt buộc
  ↓
agent_turn typed contract
  ↓
IntentionPlanner                    compatibility projection בלבד
  ↓
writer
```

Khi `planning_snapshot.agent_turn` tồn tại, `IntentionPlanner.plan_chat()` **không gọi planner model nữa**. Nó chỉ project objective/continuation sang `IntentionPlan` cũ để downstream chưa migration hết vẫn chạy được.

Nếu model-backed agent worker hỏng:

```text
RuntimeModelTurnReasoner fail
        ↓
DeterministicFallbackTurnReasoner
        ↓
one-iteration typed AgentTurn
        ↓
DiscoursePlan / speech budget vẫn tồn tại
```

Vì vậy lỗi worker không đồng nghĩa kiến trúc tụt ngược về planner → writer.

---

## 4. ConversationArc sống qua restart

### DisclosureArc

`DisclosureArcLedger` lưu:

```text
topic
active_thread
discussed_threads
deferred_threads
continuation_anchor
next_if_continue
```

State này dùng SQLite CAS store nếu runtime store khả dụng.

Conversation key được resolve:

```text
conversation_id
  ↓ nếu chưa có
thread_id
  ↓ nếu chưa có
foreground:primary
```

**Không dùng `runtime_session_id` làm fallback nữa**, vì ID đó đổi khi process restart.

### Ý nghĩa `deferred_threads`

```text
deferred != forgotten
deferred != queue bắt buộc phải đọc hết
deferred = Eris biết nhưng cố ý chưa nói
```

User có toàn quyền steering sang nhánh khác ở turn sau.

---

## 5. Learning path cũng sống qua restart

Trước V3:

```text
LearningStore:
    path definition        durable
    mastery                durable
    evidence               durable

LearningService:
    active_path_id         RAM
    active_kp_id           RAM
```

Điều này tạo lỗi kỳ quặc: DB nhớ user học được gì, nhưng sau restart tutor không biết đang dạy path nào.

V3 dùng `schema_meta.learning_runtime_v1` để lưu:

```json
{
  "active_path_id": "...",
  "active_kp_id": "..."
}
```

`LearningService.__init__()` tự rehydrate pointer nếu path/KP vẫn hợp lệ.

Mastery tuyệt đối không lấy từ metadata này.

---

## 6. Tutor session cũng sống qua restart

`TutorSessionLedger` lưu bounded session projection:

```text
TutorState
├── session_id
├── path_id / kp_id
├── hypotheses
├── last_move
├── last_delivery_text
├── turn_count
└── stalls

+ committed_move_ids
+ assessed_response_keys
```

### Tại sao `last_delivery_text` quan trọng?

Planned move:

```text
“Hỏi user về transaction boundary.”
```

Writer thực tế có thể nói:

```text
“Nếu Kafka đã nhận message rồi DB rollback, consumer có biết không?”
```

Turn sau assessor phải chấm user theo **câu thật user đã nghe**, không phải abstract intent ban đầu.

### Không lưu gì?

- chain-of-thought;
- hidden reasoning trace;
- mastery copy;
- expected answer public projection.

---

## 7. User interrupt thật sự hủy pending tutor move

Một bug tinh vi của V2:

```text
Tutor hỏi câu A
↓
user: “thôi nói chuyện khác”
↓
turn hiện tại không chấm
↓
nhưng last_move A vẫn còn trong TutorState
↓
turn sau có nguy cơ lại bị hiểu là answer cho A
```

V3 thêm `TutorExecutive.suspend_pending_move()`.

Khi root loop phân loại:

```text
response_relation = interrupt
```

TutorRoleCoordinator sẽ:

```text
không assess
không plan tiếp lesson trong turn đó
clear pending last_move
persist TutorState
```

Như vậy user interrupt thắng **qua cả turn sau**, không chỉ là một local flag.

---

## 8. TTS-aware speech budget thật

Token budget không phải speech budget.

V3 có `runtime/agent_loop/speech.py`.

### Speech estimator

Nó hỗ trợ hai dạng text:

- Latin/Vietnamese/English → words/minute;
- Japanese/CJK → characters/minute.

Có thêm pause punctuation và `tts.speed`.

Ví dụ:

```text
tts.speed = 0.85
→ cùng 20 giây chỉ được ít chữ hơn

tts.speed = 1.15
→ cùng 20 giây có thể nói nhiều hơn một chút
```

### Director dùng time budget

Conversational voice mặc định gần:

```text
target ~20s
hard max ~30s
max beat = 1
```

Deep dialogue voice:

```text
target ~28s
hard max ~40s
max beat = 2
```

Report voice vẫn được dài hơn, nhưng có hard cap.

### Chọn beat theo thời gian

Không còn chỉ:

```text
visible_beats < max_beats
```

Mà còn:

```text
estimated_current_seconds + estimated_next_beat_seconds
    > target_seconds
→ giữ beat tiếp theo vào deferred_threads
```

---

## 9. Pre-TTS hard guard

Director + writer prompt là lớp chính. Nhưng model có thể fail instruction.

Do đó sau writer, trước Stage/TTS:

```text
actual writer text
    ↓
estimate speech duration
    ↓
within budget? ── yes → tiếp tục
    │
    no
    ↓
clip tại sentence boundary
    ↓
sync top-level + nested utterance surface
    ↓
TTS
```

Hard guard chỉ active khi TTS bật. Text-only report không bị cắt máy móc.

Guard này là **seatbelt**, không phải cách viết chính.

Writer vẫn phải tự viết đúng nhịp ngay từ đầu.

---

## 10. Ví dụ đúng case “INTP 538”

Agent có thể lập internal analysis map:

```text
1. core 5
2. fix 3
3. fix 8
4. khác stereotype INTP
5. INTJ mistype
6. Ti/Ne
7. Fe
8. stress
```

Voice + conversational:

```text
Turn 1:
  reveal: tổng quan khác stereotype
  defer : 2..8
  stop
```

Public có thể chỉ là:

```text
“INTP 538 khá khác stereotype INTP. Core 5 vẫn rất rõ,
nhưng 3 với 8 làm kiểu này chủ động và cứng hơn nhiều;
bề ngoài đôi khi còn dễ bị nhầm với INTJ.”
```

User:

```text
“sao giống INTJ?”
```

Turn 2 load arc:

```text
active/deferred thread có INTJ mistype
```

Agent re-plan đúng nhánh user vừa chọn.

Nó **không phải** đọc tiếp tuần tự fix3 → fix8 chỉ vì đó là backlog.

---

## 11. Tutor + Agent + Conversation phối hợp

Ví dụ user không hiểu Ti/Te:

```text
TurnAgentLoop
    ↓
TutorRole: nên probe
    ↓
TutorExecutive: Socratic question, requires_response=True
    ↓
root agent re-plan
    ↓
ConversationDirector:
    max_beats=1
    short speech budget
    ↓
writer hỏi đúng một câu
    ↓
commit exact delivered text
    ↓
status=waiting_user
    ↓
reserve user floor
    ↓
HARD STOP
```

Turn sau:

```text
user response
    ↓
root semantic relation:
    answer / clarification / interrupt
```

- `answer` → semantic assessor → evidence → mastery recompute.
- `clarification` → giải thích lại, không chấm.
- `interrupt` → clear pending tutor move, không chấm.

---

## 12. Autonomous afterbeat không được phá pacing

Nếu progressive conversation còn deferred thread hoặc tutor đang chờ user:

```text
agent_turn_result.reserves_user_floor = True
```

thì:

```text
social continuation schedule = blocked
conversation_arc autonomous speech = blocked
```

Agenda/memory update vẫn được phép.

Chỉ **speech continuation tự động** bị chặn.

---

## 13. Eval harness

Chạy:

```bash
PYTHONPATH=. python tools/run_agent_conversation_eval.py
```

Harness hiện kiểm tra offline:

1. `INTP 538` voice → 1 beat public, các ý sau deferred.
2. turn sau → prior DisclosureArc xuất hiện trong context.
3. `WAIT_USER` → hard stop sau một iteration.
4. explicit report text → được phép nhiều beat.
5. writer quá dài → pre-TTS guard clip.

Harness không gọi provider nên chạy nhanh, deterministic và thích hợp CI.

---

## 14. Test status

### Main targeted regression

```text
182 passed
```

### Additional related regression

```text
61 passed
1 deselected
```

Test deselected:

```text
test_random_chat_seed_v27.py::test_governor_preserves_seed_in_surface_intent_and_plan
```

Lý do: test này fail **y hệt trên source gốc** với:

```text
candidate_without_expression_commitment
```

Nó không phải regression của Unified Agent patch.

### Productionization-specific

```text
5 passed
```

Bao gồm:

- active learning path/KP restore sau restart;
- TutorSessionLedger restore exact delivered move;
- speech hard guard;
- TTS speed ảnh hưởng word budget;
- IntentionPlanner không re-own semantic planning khi có `agent_turn`.

---

## 15. Invariant cần giữ từ giờ trở đi

1. Mỗi foreground user turn phải có `AgentTurn` typed contract.
2. Planner cũ không được trở thành semantic owner lần hai.
3. Tutor là role, không phải root chat loop.
4. LearningService là mastery/evidence truth duy nhất.
5. `deferred_threads` là intentional withholding, không phải quên.
6. User được steering; deferred list không phải queue bắt buộc.
7. Voice budget tính theo speech time, không chỉ token/word.
8. Writer vượt hard cap phải bị chặn trước TTS.
9. Tutor question cần response → một move → hard wait.
10. Interrupt không được bị chấm ở turn hiện tại **hoặc turn sau**.
11. Exact delivered question phải sống qua restart nếu tutor vẫn chờ answer.
12. Progressive conversation reserve floor cho user; afterbeat không được chen.
13. Không persist chain-of-thought.
14. Model proposes; deterministic runtime commits.
15. Catastrophic agent-loop failure phải telemetry rõ, không im lặng giả vờ normal.

---

## 16. Những gì V3 cố ý chưa làm

V3 vẫn dùng **một public writer call cho một turn**. Nó đã giới hạn beat và có hard speech guard, nhưng chưa render kiểu:

```text
beat 1 → writer segment 1 → runtime review → beat 2 → writer segment 2
```

Đó là một bước khác vì nó đụng transaction/streaming/TTS receipt sâu hơn.

V3 hiện đã giải quyết phần quan trọng hơn trước: root-loop ownership, durable continuity và speech pacing thật.
