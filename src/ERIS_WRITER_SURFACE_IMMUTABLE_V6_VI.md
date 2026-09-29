# ERIS V6 — Public Writer Surface Immutable

## Quy tắc gốc

Sau khi public writer đã sinh `text` và `speech_text`, runtime **không được** cắt, rút gọn, nối dấu `…`, đổi từ, hoặc viết lại câu chỉ để đạt word/time/TTS cap.

Pacing được xử lý **trước writer** ở mức semantic:

1. Agent loop phân tích sâu.
2. ConversationDirector chọn beat nào nói ở lượt này.
3. Các beat còn lại được lưu vào `deferred_threads`.
4. Writer tự diễn đạt beat đã chọn bằng câu tự nhiên.
5. Runtime chỉ đo thời lượng để telemetry; không sửa public wording.

## Vì sao thay đổi

Hard clip sau writer làm câu mất duyên, mất ngữ điệu và có thể đổi ý nghĩa. Ví dụ một câu tự nhiên có thể bị cắt thành một fragment cụt. Điều đó phá đúng mục tiêu hội thoại nhiều lượt.

## Boundary

- `max_beats`: semantic disclosure policy; được phép dùng để quyết định *ý nào* nói ở lượt hiện tại.
- `target_words`, `target_seconds`, `hard_max_*`: schema legacy / telemetry / gợi ý; không có authority chỉnh public text.
- `speech.py`: observer thuần. Legacy `enforce_public_speech_budget()` được giữ API nhưng không clip nữa.
- `orchestrator.py`: không còn post-writer speech mutation.

## Safety / grounding

Thay đổi này chỉ loại bỏ **pacing-based rewriting**. Grounding/capability safety vẫn có quyền reject/suppress một output không hợp lệ theo contract riêng; chúng không được dùng như công cụ rút gọn văn phong.

## Invariant kiểm thử

`max_beats` là semantic disclosure, không phải giới hạn độ dài câu. Nếu một beat cần 3–5 câu để nói có duyên và trọn ý, writer được phép làm vậy. Runtime chỉ lưu các beat chưa nói sang lượt sau.
