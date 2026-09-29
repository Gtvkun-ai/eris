# ERIS V8 — Agent-owned Long-term Speech Plan

## 1. Mục tiêu

V8 giải quyết đúng một vấn đề kiến trúc: **runtime không được quyết định nội dung hội thoại thay ERIS**.

Từ V8:

- Root `TurnAgentLoop` tự quyết định mình muốn nói gì ở lượt hiện tại.
- Root `TurnAgentLoop` tự lập kế hoạch nói dài hạn cho các lượt sau.
- Runtime chỉ persist kế hoạch, ghi lifecycle, hẹn wake và gọi lại agent.
- Runtime không tự chọn `planned_threads[0]`, không tự cắt beat, không tự viết câu tiếp theo.
- Writer là owner của wording public.
- TTS chỉ phát nguyên public wording đã commit.

Nguyên tắc ngắn gọn:

```text
AGENT quyết định
RUNTIME ghi nhớ + gọi lại
WRITER diễn đạt
TTS phát nguyên văn
```

---

## 2. ConversationSpeechPlan

`runtime/agent_loop/contracts.py`

Plan dài hạn là dữ liệu public-safe, không phải chain-of-thought:

```python
ConversationSpeechPlan(
    plan_id="...",
    topic="INTP 538",
    conversation_goal="phân tích cùng user thay vì dump encyclopaedia",
    current_thread="khác stereotype INTP",
    discussed=("tổng quan", "core 5"),
    planned_threads=("fix 3", "fix 8", "INTJ comparison"),
    next_intent="đào nhánh INTJ nếu user bắt đúng nhánh đó",
    continuation_mode=SpeechContinuationMode.YIELD_USER,
    resume_trigger="user_reply",
    pause_seconds=0.0,
)
```

Điều cực kỳ quan trọng:

- `planned_threads` KHÔNG phải queue câu nói.
- `next_intent` KHÔNG phải public text.
- Runtime không được materialize chúng.
- Turn sau AgentLoop đọc lại plan rồi quyết định lại từ đầu dựa trên user steering mới.

---

## 3. Ba continuation mode

### NONE

Agent không cam kết nối tiếp.

```text
public turn
→ audio done
→ lifecycle done
```

### YIELD_USER

Agent chủ động nói một nhịp rồi nhường user.

```text
AgentLoop
→ speech_plan.continuation_mode = yield_user
→ Writer
→ TTS
→ UI: Eris • đang chờ bạn
→ user turn mới
→ plan cũ được đưa lại cho AgentLoop
→ Agent tự re-plan
```

### AUTO_CONTINUE

Agent tự quyết rằng mình còn muốn nói tiếp sau một nhịp.

```text
AgentLoop
→ continuation_mode = auto_continue
→ next_intent + planned_threads + pause_seconds
→ Writer
→ TTS
→ audio done
→ SpeechPlanLedger chỉ schedule wake
→ tới hạn
→ gọi lại TurnAgentLoop
→ Agent đọc plan cũ + recent history
→ Agent tự quyết lại: nói tiếp / đổi hướng / yield / huỷ
→ Writer mới render public text mới
```

Không có bước nào runtime lấy sẵn câu hoặc thread rồi tự phát.

---

## 4. SpeechPlanLedger

`runtime/agent_loop/speech_plan.py`

Ledger chỉ sở hữu lifecycle cơ học:

```text
planned
→ delivered_waiting_audio
→ waiting_user
hoặc
→ auto_continue_scheduled
→ claimed
```

Ledger được phép thay đổi:

- `status`
- `due_at`
- `claim_token`
- receipt metadata

Ledger KHÔNG được thay đổi semantic plan:

- topic
- goal
- current thread
- planned threads
- next intent

User luôn thắng auto-continuation. Khi user chen vào:

```text
scheduled continuation
→ user turn
→ timer/claim bị huỷ
→ semantic plan vẫn còn
→ AgentLoop nhận cả user mới + plan cũ
→ agent tự re-plan
```

---

## 5. AUTO_CONTINUE thực sự gọi lại AgentLoop

`runtime/ai_orchestrated/self_turn_pipeline.py`

`_run_due_agent_speech_continuation()` không biết ý tiếp theo là gì.

Nó chỉ:

1. kiểm tra agent có `AUTO_CONTINUE` đến hạn không;
2. claim ledger để tránh chạy hai lần;
3. gọi `TurnAgentRuntime.prepare_continuation_turn()`;
4. root agent tự re-evaluate plan;
5. nếu agent vẫn chọn public beat thì mới đưa beat mới cho writer;
6. nếu agent đổi ý không nói thì dừng.

Đây là invariant bắt buộc:

```text
runtime wake ≠ runtime speak
```

---

## 6. UI trạng thái

Runtime được phép hiển thị **operational state**, không được public reasoning.

Các trạng thái V8:

```text
Eris • đang suy nghĩ…
Eris • đang chuẩn bị nói…
Eris • đang nói…
Eris • đang chờ bạn
Eris • còn một ý…
```

Ý nghĩa:

- `đang suy nghĩ`: root AgentLoop đang xử lý.
- `đang chuẩn bị nói`: public writer đang render wording.
- `đang nói`: audio playback đã bắt đầu.
- `đang chờ bạn`: agent đã chọn `YIELD_USER`.
- `còn một ý`: agent đã chọn `AUTO_CONTINUE`; runtime chỉ đang chờ tới lúc wake lại agent.

Không được hiển thị hidden reasoning như:

```text
Đang so sánh Ti-Ne với Ni-Te...
```

---

## 7. Ownership cuối cùng

```text
TurnAgentLoop
    ├─ cognitive plan
    ├─ execution/action plan
    ├─ public beats hiện tại
    ├─ long-term speech plan
    ├─ yield / auto-continue / complete
    └─ tutor role coordination

SpeechPlanLedger
    └─ persist + lifecycle + idempotent claim

ConversationDirector
    └─ validation/projection thuần

Writer
    └─ public wording

TTS
    └─ playback

Runtime status UI
    └─ coarse phase only
```

Không có một `ConversationDirector` bí mật đứng sau chọn nội dung nữa.

---

## 8. Tutor phối hợp với SpeechPlan

Tutor vẫn không sở hữu root loop.

```text
TutorRole
→ đề xuất pedagogical intent
→ root AgentLoop quyết public move
→ root AgentLoop lập speech plan
→ Writer
→ WAIT_USER nếu cần
```

Nếu tutor đang chờ câu trả lời:

- `AUTO_CONTINUE` bị validation từ chối;
- agent phải lập lại plan;
- chỉ user mới được tiếp tục interaction.

---

## 9. Test chứng minh

`tests/test_agent_speech_plan_v8.py`

Các invariant được test:

1. long-term plan được persist qua nhiều turn;
2. runtime không biến `planned_threads` thành public beat;
3. audio receipt của `AUTO_CONTINUE` chỉ schedule wake;
4. wake gọi lại chính root AgentLoop;
5. public beat thứ hai là quyết định mới của agent;
6. user chen vào preempt auto-continue nhưng plan cũ vẫn còn cho re-plan.

Regression đã chạy:

```text
65 passed — agent/disclosure/tutor/pacing core
136 passed — public-output/pedagogy/lifecycle regression
```
