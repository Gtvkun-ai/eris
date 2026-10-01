# ERIS V11 — Agent-owned Turn Projection

## Mục tiêu

V10 đã làm đúng phần quan trọng nhất: root `TurnAgentLoop` quyết định nội dung cần nói và kế hoạch hội thoại dài hạn; runtime không được cắt, chọn hoặc viết hộ lời của LLM.

V11 bổ sung đúng **một** khái niệm còn thiếu: **TurnProjection** — cách chính Eris muốn người dùng cảm nhận ranh giới lượt nói sau câu hiện tại.

Nó giải quyết tình huống rất đời thường:

- Eris vừa nói xong nhưng **còn định nói tiếp** → body không nên settle như đã hết lượt.
- Eris đã nói xong và **nhường user** → body nên trở về trạng thái mở/settle.
- Eris chưa giữ cũng chưa nhường mạnh → user có thể chen tự nhiên.

Điểm quan trọng: **runtime không được tự đoán trạng thái này** từ độ dài câu, voice mode, `AUTO_CONTINUE`, TTS hay số beat.

---

## 1. Ba owner tách biệt

### `ConversationSpeechPlan`
Kế hoạch semantic dài hạn của AgentLoop:

- đang nói chủ đề gì;
- đã nói gì;
- còn muốn giữ thread nào;
- nếu được wake lại thì muốn xét tiếp điều gì;
- lifecycle cognition là `none / yield_user / auto_continue`.

Đây là **kế hoạch nội dung**, không phải body language.

### `TurnProjection`
Projection của **turn hiện tại**:

```python
TurnProjection(
    floor="hold | yield | open",
    continuation_feel="neutral | thinking | eager | soft | playful",
    verbal_bridge_hint="...",
)
```

Nó là quyết định public-safe của root agent về **turn-taking**.

### Writer
Writer vẫn là owner duy nhất của câu chữ public.

`verbal_bridge_hint` chỉ giúp writer biết nhịp kết câu agent muốn tạo ra. Runtime không được tự chèn lời như:

- "à còn một cái nữa...";
- dấu `...`;
- filler;
- một câu báo continuation.

Nếu cần tín hiệu bằng lời, writer tự hiện thực nó tự nhiên trong phạm vi `public_beats` đã được agent chọn.

---

## 2. Ý nghĩa của floor

### `hold`
Eris chủ động muốn người dùng cảm nhận:

> "Tôi chưa nói xong; có khả năng tôi sẽ nói tiếp ngay sau một nhịp."

Để tránh body báo sai, V11 yêu cầu:

```text
floor=hold
    => continuation_mode=auto_continue
```

Nếu agent trả `hold` nhưng không có auto-continuation, validator trả lỗi về AgentLoop để agent tự re-plan.

### `yield`
Eris chủ động nhường lượt cho user.

Tutor đang chờ câu trả lời **bắt buộc** phải dùng `yield`.

### `open`
Eris không giữ floor cũng không ép user trả lời.

Đây là trạng thái tự nhiên cho các câu hoàn chỉnh nhưng conversation vẫn mở. Nó cũng phù hợp khi Eris có thể được wake lại sau đó nhưng không muốn người dùng cảm thấy phải im lặng chờ.

---

## 3. `continuation_mode` và `floor` không phải cùng một thứ

```text
ConversationSpeechPlan.continuation_mode
→ cognition có được wake lại hay đang chờ user?

TurnProjection.floor
→ user nên cảm nhận ranh giới lượt nói như thế nào?
```

Runtime không được suy cái này từ cái kia.

Validator chỉ làm nhiệm vụ phát hiện cặp tự mâu thuẫn:

- `hold` nhưng không `auto_continue` → invalid;
- `auto_continue + yield` → invalid;
- tutor `WAIT_USER` mà không `yield` → invalid.

Validator **không sửa** projection. Nó trả lỗi để AgentLoop tự quyết lại.

---

## 4. Lifecycle thực tế

```text
USER
  ↓
TurnAgentLoop
  ├── CognitivePlan
  ├── ExecutionPlan
  ├── ConversationSpeechPlan
  ├── PublicBeats
  └── TurnProjection
         ↓
Stage projection event
         ↓
Writer
  ↓
TTS
  ↓
audio_done
  ├── floor=hold
  │     ├── UI: "Eris • còn một ý…"
  │     └── Live2D giữ pose chuẩn bị nói tiếp
  │
  ├── floor=yield
  │     ├── UI: "Eris • đang chờ bạn"
  │     └── Live2D settle
  │
  └── floor=open
        └── settle bình thường
```

Nếu speech plan là `auto_continue`, runtime chỉ schedule **wake cognition**.

```text
runtime wake
    ≠ runtime speak
```

Sau wake, AgentLoop được gọi lại và có quyền:

- tiếp tục;
- đổi hướng;
- bỏ ý cũ;
- yield;
- im lặng.

---

## 5. Live2D cue

`continuation_feel` chỉ ảnh hưởng presentation, không ảnh hưởng semantics.

Mapping hiện tại:

| feel | Live2D motion | emotion |
|---|---|---|
| `thinking` | `thinking_small` | `thinking` |
| `eager` | `lean_in_small` | `curious` |
| `soft` | `lean_in_small` | `warm_soft` |
| `playful` | `tilt_head` | `mischief_soft` |
| `neutral` | `thinking_small` | `focused` |

Khi `floor=hold`, sau `audio_playback_done` Live2D **không settle về `stand` ngay**. Nó giữ pose projection cho tới cognition tiếp theo hoặc user turn mới.

Khi user nói, public lifecycle mới bắt đầu và projection cũ hết hiệu lực; semantic `SpeechPlan` vẫn còn để root agent re-plan.

---

## 6. UI trạng thái

Operational UI sẵn có vẫn giữ:

```text
Eris • đang suy nghĩ…
Eris • đang chuẩn bị nói…
Eris • đang nói…
```

Sau audio, UI không còn đoán từ `continuation_mode`:

```text
TurnProjection HOLD
→ Eris • còn một ý…

TurnProjection YIELD
→ Eris • đang chờ bạn

TurnProjection OPEN
→ không giữ status giả
```

Đây là **mirror của quyết định AgentLoop**, không phải runtime policy.

---

## 7. Verbal bridge

Agent có thể trả:

```json
{
  "floor": "hold",
  "continuation_feel": "eager",
  "verbal_bridge_hint": "kết hơi mở vì còn một liên hệ muốn nói tiếp"
}
```

Writer có thể tự nhiên viết kiểu:

> “Nhưng chỗ thú vị hơn lại nằm ở cái fix 8...”

hoặc một cách diễn đạt khác hợp personality.

Runtime **không** được lấy `verbal_bridge_hint` rồi biến thành câu public.

---

## 8. Tutor

Tutor không có root floor riêng.

```text
TutorRole
  → pedagogical intent

TurnAgentLoop
  → public beat
  → TurnProjection
```

Nếu tutor đang chờ user trả lời:

```text
waiting_for_user = true
floor = yield
```

Agent không được báo body “tôi còn muốn nói” rồi lại bắt user trả lời.

---

## 9. Persistence

`SpeechPlanLedger` vẫn là một ledger duy nhất cho conversation continuity.

V11 lưu thêm **projection gần nhất** trong cùng snapshot để `audio_done` biết chính agent đã muốn giữ/yield floor ra sao.

Khi user turn mới tới:

- projection reset về `open` vì tín hiệu presentation cũ đã hết hạn;
- speech plan semantic **không bị xóa**.

Nhờ đó runtime không tạo thêm một `TurnProjectionLedger` thứ hai.

---

## 10. Invariant quan trọng

1. Root AgentLoop là semantic authority duy nhất của floor.
2. Runtime không suy floor từ voice/TTS/length/continuation.
3. Writer là owner duy nhất của public wording.
4. Runtime không chèn verbal bridge.
5. `hold` phải có auto-continuation thật.
6. Tutor WAIT phải yield floor.
7. Live2D/UI chỉ mirror projection.
8. User input luôn preempt continuation.
9. Raw chain-of-thought không đi vào `TurnProjection`.

---

## 11. Test V11

`tests/test_agent_turn_projection_v11.py` kiểm tra:

- projection tách khỏi SpeechPlan;
- validator chặn lifecycle mâu thuẫn;
- `hold` bắt buộc có auto-continue;
- ledger persist projection nhưng reset projection khi user lấy floor;
- stage adapter mirror exact agent choice;
- Live2D HOLD không settle sau audio;
- Live2D YIELD settle bình thường.
