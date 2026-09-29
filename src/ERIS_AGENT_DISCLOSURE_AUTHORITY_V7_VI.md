# ERIS V7 — Root Agent sở hữu toàn bộ disclosure

## 1. Vấn đề của V6

V6 đã bỏ việc **cắt câu sau writer**, nhưng vẫn còn một lỗi ownership lớn:

```text
Root Agent tạo nhiều DialogueBeat
        ↓
ConversationDirector nhìn voice/text mode
        ↓
Runtime tự quyết chỉ reveal 1/2/N beat
        ↓
Writer
```

Như vậy runtime vẫn đang quyết **ý nào được nói**, dù không còn cắt chữ.
Đây là sai kiến trúc vì pacing hội thoại là một quyết định semantic/social.
Nó phải thuộc về agent đang reasoning, không thuộc về plumbing runtime.

## 2. Boundary V7

Từ V7:

```text
USER
  ↓
TurnAgentLoop / Root Executive
  ↓
Cognitive Plan
Execution Plan
Discourse Plan
  ↓
Root Executive tự quyết:
  - beat nào say_now=true
  - beat nào say_now=false
  - deferred_threads là gì
  - continuation_anchor là gì
  - WAIT hay COMPLETE
  ↓
Runtime validation
  ↓
Projection cơ học say_now=true
  ↓
Writer
  ↓
Public text immutable
```

### Quy tắc cứng

**Agent quyết định; runtime thi hành.**

Runtime KHÔNG được:

- tự chọn conversational = 1 beat;
- tự chọn deep dialogue = 2 beat;
- tự truncate beat vì voice mode;
- tự dedupe rồi bỏ một claim;
- tự chuyển beat không nói sang deferred;
- tự tạo continuation;
- tự tạo fallback public proposition;
- tự sửa public wording sau writer.

## 3. `DialogueBeat.say_now` là authority semantic

Ví dụ executive trả:

```json
{
  "dialogue_beats": [
    {"proposition": "538 khác stereotype INTP khá rõ.", "say_now": true},
    {"proposition": "Core 5 giải thích phần quan sát.", "say_now": false},
    {"proposition": "Fix 8 làm nó cứng hơn.", "say_now": false}
  ],
  "continuation": {
    "deferred_threads": [
      "Core 5 giải thích phần quan sát.",
      "Fix 8 làm nó cứng hơn."
    ]
  }
}
```

Writer chỉ nhận beat đầu.

Nhưng nếu executive quyết:

```json
{
  "dialogue_beats": [
    {"proposition": "A", "say_now": true},
    {"proposition": "B", "say_now": true},
    {"proposition": "C", "say_now": true}
  ]
}
```

thì dù `voice_mode=true`, runtime **phải giao cả A, B, C cho writer**.
Runtime không được tự nghĩ “voice thì chỉ nên một beat”.

## 4. ConversationDirector V7

`ConversationDirector` vẫn giữ tên để tránh phá API cũ, nhưng đã bị hạ quyền.

Nó chỉ còn:

```text
accept_agent_snapshot()
project_for_writer()
validate_agent_plan()
```

### `accept_agent_snapshot()`

Iteration mới nhất của root executive là snapshot discourse authoritative.
Runtime không merge semantic beat từ iteration cũ.

Lý do: nếu agent ở vòng 1 muốn nói A, sau đó vòng 2 phát hiện A không còn phù hợp,
runtime không được cố giữ A chỉ vì “đã thấy ở iteration trước”.

### `project_for_writer()`

Chỉ làm:

```python
public_beats = [beat for beat in beats if beat.say_now]
```

Đây không phải policy; đây là thực thi trực tiếp cờ mà agent đã quyết.

### `validate_agent_plan()`

Runtime được quyền nói:

```text
contract này invalid
```

nhưng không được nói:

```text
để tôi tự sửa hộ agent
```

Ví dụ COMPLETE mà không có public beat:

```text
runtime -> agent_disclosure_feedback
agent -> re-plan
```

Tutor WAIT mà executive chọn sai số teaching beat cũng tương tự.

## 5. Multi-iteration semantics

Mỗi iteration phải trả lại **toàn bộ discourse snapshot hiện tại**.

Không còn:

```text
iteration 1: A
iteration 2: B
iteration 3: C
runtime merge -> A+B+C
```

Mà là:

```text
iteration 1:
  current plan = A

iteration 2:
  current plan = A+B

iteration 3:
  current plan = B+C

final public plan = B+C
```

Agent có quyền đổi ý khi observation/reasoning thay đổi.

## 6. Voice/TTS

`voice_mode` vẫn được đưa vào context cho executive.

Nhưng nó chỉ là **evidence cho agent reasoning**:

```text
voice_mode=true
→ executive tự cân nhắc nhịp nói
→ có thể 1 beat
→ có thể 2 beat
→ có thể 3 beat nếu cần để câu có duyên
```

Không còn luật runtime:

```text
voice = 1 beat
```

`speech_budget` hiện chỉ là field compatibility/telemetry cũ.
Nó không có authority đối với semantic disclosure hay public wording.

## 7. Tutor phối hợp

Tutor không được cướp root loop.

```text
TutorRole
  ↓
pedagogical intent
  ↓
Root Executive thấy intent
  ↓
Root Executive tự tạo teaching DialogueBeat
  ↓
Runtime validate
  ↓
Writer
  ↓
WAIT_USER lifecycle
```

Nếu tutor cần một câu hỏi mà root executive trả 3 public beat:

```text
runtime KHÔNG cắt còn 1 beat
runtime trả validation error
root executive phải re-plan
```

Đây là ownership đúng.

## 8. Writer boundary

Writer nhận chính xác plan đã được root agent chọn.

Sau writer:

```text
public text = immutable
```

Không word cap, không second cap, không sentence clipping.

Grounding/safety nếu fail phải **reject/retry**, không biên tập phong cách hộ writer.

## 9. Test V7

Các invariant mới có test:

- agent chọn 3 beat trong voice -> runtime giữ đủ 3;
- `legacy max_beats=1` không được cắt 3 beat agent đã chọn;
- beat `say_now=false` không tự bị runtime thêm vào deferred;
- COMPLETE không có public beat -> feedback về agent -> agent re-plan;
- tutor answer -> assessment -> root re-plan -> WAIT;
- V6 public text immutable vẫn giữ nguyên.

Regression liên quan sau V7:

```text
87 passed
```

## 10. Câu chốt ownership

```text
LearningService quyết sự thật học tập.
TutorRole đề xuất pedagogical intent.
TurnAgentLoop quyết agent sẽ làm gì và NÓI GÌ ở lượt này.
Writer quyết cách diễn đạt câu đã được chọn.
Runtime chỉ thực thi, validate, persist và route.
TTS chỉ phát lời.
```

Không còn lớp nào phía dưới root executive được quyền “thấy nhiều ý rồi chọn hộ ý nào nên nói”.
