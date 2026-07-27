# ERIS V43 - Typed Discourse Resolver

## Mục tiêu

Bản này loại bỏ hoàn toàn việc nhận dạng continuity bằng danh sách câu mẫu như
`thật hong`, `thật cái gì`, `hả`, `tôi vừa nói gì`.

Ý định hội thoại hiện đi theo một authority duy nhất:

```text
User turn
  -> main model sinh semantic_frame.reference
  -> runtime resolve reference bằng session turn index
  -> exact session recall / long-term memory / public wording
```

## Contract mới

`semantic_frame.reference` gồm:

```json
{
  "kind": "assistant_proposition",
  "speaker": "assistant",
  "operation": "clarify",
  "turn_index": 5,
  "turn_offset": 0,
  "confidence": 0.94
}
```

Các `kind` hỗ trợ:

- `none`
- `recent_user_turn`
- `recent_assistant_turn`
- `assistant_proposition`
- `open_question`
- `long_term_memory`
- `current_message`

Các thao tác hỗ trợ:

- `repeat`
- `recall`
- `clarify`
- `confirm`
- `repair`
- `answer`

## Điểm quan trọng

1. Runtime không đọc keyword để đoán ý định.
2. Model nhận `discourse_state.v1` có turn index thật của các lượt gần nhất.
3. Exact recall dùng ledger nên không bịa lại câu user.
4. Assistant response nối tiếp giữ `proposition_root_turn_index`, vì vậy một câu
   xác nhận ngắn không làm mất phát biểu gốc.
5. Long-term memory chỉ được intercept khi frame chọn `long_term_memory`.
6. Reference confidence thấp không được phép override câu model.
7. Turn index sai không bị runtime âm thầm đổi sang một turn khác.
8. Payload `semantic_frame` sai kiểu vẫn bị hạ cấp an toàn, không làm chết loop.

## Cách chép

Giải nén ZIP vào thư mục `src`, cho phép ghi đè file cùng tên. ZIP chỉ chứa các
file đã sửa hoặc thêm, không chứa toàn bộ source.

## Kiểm tra

```text
439 tests passed
compileall passed
không còn phrase-marker classifier trong core/memory/runtime
```
