# ERIS V44 Typed Discourse hoàn thiện

Bản này thay tầng continuity V43 bằng contract typed hoàn chỉnh. Mục tiêu là
không còn một semantic frame dưới dạng `dict[str, Any]` chạy xuyên runtime, không
để resolver viết câu public, và không để memory parser đọc lại raw user text sau
khi main model đã phân loại ý nghĩa.

## Kiến trúc mới

```text
Provider JSON
    ↓
SemanticFrame + AssistantAct validator
    ↓
DiscourseResolver
    ↓
DiscourseAction thuần dữ liệu
    ├── DiscourseSurfaceRenderer
    └── Structured MemoryQuery executor
    ↓
Orchestrator tạo Decision và commit ledger
```

## Các thay đổi chính

### 1. Một contract typed duy nhất

`runtime/semantic_frame.py` định nghĩa toàn bộ enum và dataclass:

- `SemanticFrame`
- `DiscourseReference`
- `ReplyObligation`
- `MemoryQueryFrame`
- `AssistantAct`

Các object vẫn hỗ trợ `Mapping` để code cũ gọi `dict(frame)` trong giai đoạn
chuyển đổi, nhưng enum và compatibility rule không còn bị khai báo lặp ở
`discourse_state.py`.

### 2. Compatibility matrix theo reference kind

Mỗi `reference.kind` khóa speaker và operation hợp lệ. Ví dụ:

- `recent_user_turn` luôn trỏ user;
- `assistant_proposition` luôn trỏ assistant;
- `long_term_memory` không có speaker/turn locator;
- `turn_index` và `turn_offset` không được dùng cùng lúc.

Payload mâu thuẫn bị sửa có log violation, không được âm thầm đổi nghĩa theo
field bất kỳ.

### 3. Boolean parse chặt

Chuỗi `"false"` không còn bị Python coi thành `True`. Chỉ boolean thật hoặc số
`0/1` được chấp nhận. Giá trị sai kiểu quay về default an toàn và có violation.

### 4. Resolver không biết câu chữ hoặc animation

`runtime/discourse_state.py` chỉ trả `DiscourseAction`. Câu tiếng Việt exact hoặc
fallback nằm trong `runtime/discourse_surface.py`. `Decision`, animation và stage
hint thuộc orchestrator.

### 5. Proposition model đúng chủ thể

Assistant turn không còn lưu semantic frame của user. Nó lưu `assistant_act` riêng:

- acknowledgement/social không tạo proposition mới;
- assertion/explanation/opinion/answer tạo root mới;
- confirmation/repair có thể nối root hiện tại;
- assistant question được đánh dấu open question;
- câu non-propositional chỉ mang tiếp active root, không tự biến thành root.

### 6. Memory query có cấu trúc

Khi `reference.kind=long_term_memory`, model phải điền:

```json
{
  "memory_query": {
    "intent": "recall_fact",
    "subject": "user",
    "predicate_hint": "user.name",
    "object_hint": "",
    "temporal_scope": "current",
    "answer_mode": "exact",
    "confidence": 0.95
  }
}
```

Runtime chuyển object này thành `MemoryQueryIR` và thực thi trực tiếp. Raw user
text chỉ còn dùng cho debug/evidence, không được parser thứ hai dùng để đoán lại
predicate.

### 7. Không gửi lịch sử hai lần

`discourse_context` chỉ chứa `history_turn_map`, candidate index và metadata act.
Raw text đã nằm trong `chat_history`, nên không bị lặp thêm trong JSON discourse.

## File chính

- `runtime/semantic_frame.py`
- `runtime/discourse_state.py`
- `runtime/discourse_surface.py`
- `runtime/conversation_continuity.py`
- `runtime/ai_orchestrated/model_router.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/memory_recall_adapter.py`
- `runtime/state_commit_service.py`

## Kiểm thử

Bộ test mới khóa các hành vi sau:

- reference speaker/operation mâu thuẫn;
- locator `turn_index + turn_offset`;
- boolean string;
- acknowledgement không thành proposition;
- confirmation nối proposition root;
- exact repeat thắng wording model;
- structured memory query không gọi compiler raw text;
- open question đã trả lời không còn được xem là open;
- discourse prompt không chứa raw chat text;
- module state không phụ thuộc `Decision` hoặc câu public.
