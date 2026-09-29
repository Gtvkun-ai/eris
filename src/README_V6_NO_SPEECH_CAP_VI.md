# ERIS V6 — Bỏ speech cap, giữ nguyên lời của public writer

## Mục tiêu

Runtime không được cắt/rút gọn public text sau khi LLM writer đã sinh.

## Quy tắc ownership mới

- `TurnAgentLoop`: suy nghĩ, ACT/OBSERVE/REPLAN.
- `ConversationDirector`: chọn semantic beat nào được reveal ở lượt hiện tại.
- `Public writer`: owner duy nhất của cách diễn đạt câu public.
- `TTS/runtime`: chỉ phát/đo telemetry, không chỉnh từ ngữ vì pacing.

## Những gì đã bỏ

- post-writer hard clip theo `hard_max_words`;
- post-writer hard clip theo `hard_max_seconds`;
- fallback cắt sentence/word rồi thêm `…`;
- writer prompt bắt buộc phải đạt word/time cap.

## Những gì vẫn giữ

Progressive disclosure vẫn hoạt động ở mức semantic beat. Ví dụ agent có 5 ý nhưng conversational voice chỉ reveal 1 beat; 4 ý còn lại đi vào `deferred_threads`. Writer có thể dùng số câu cần thiết để nói beat đó tự nhiên.

Các field `target_words`, `target_seconds`, `hard_max_*` vẫn tồn tại để tương thích schema cũ và telemetry, nhưng không có authority chỉnh public wording.

## Safety / grounding

Patch này loại bỏ **pacing-based rewriting**. Các authority gate về grounding/capability vẫn có thể reject/suppress hoặc yêu cầu retry theo contract riêng; chúng không được dùng để rút gọn văn phong.

## Regression

- 38/38 test AgentLoop/Tutor/Pacing/Learning liên quan pass.
- 57/57 test Writer/PublicTurn/TTS/Discourse/Pedagogy liên quan pass.
- Tổng lượt regression đã chạy cho thay đổi này: 95 pass.
