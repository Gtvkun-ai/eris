# Opening Director đa nhịp, nhận biết ngữ cảnh

## Mục tiêu

Opening Director chạy **trước Surface Writer**. Rule layer giữ grounding, safety,
consent, cooldown và invariant; model chỉ chọn candidate typed và hiện thực hóa
câu chữ trong phạm vi đã duyệt. Startup vẫn dùng một public commit duy nhất và
vẫn giữ guard `ensure_startup_greeting_payload()` của V25 làm lớp phòng thủ cuối.

## Luồng thực thi

1. `opening_input_assembler.py` gom event, evidence có provenance, continuity theo consent,
   session state, recent moves, user signals, scene-partner và policy.
2. `opening_safety.py` quyết định eligibility và loại evidence/move không hợp lệ.
3. `opening_director.py` sinh candidate cấu trúc, chấm điểm, cho model chọn trong top candidate,
   rồi tạo `opening_plan.v1` tối đa ba beat.
4. Surface Writer nhận plan và evidence được phép. Output sai schema, thêm claim, stage direction,
   pressure hoặc quá số câu hỏi sẽ bị bỏ và dùng renderer deterministic.
5. `performance.py` dùng beat typed thay vì chia câu theo dấu chấm. Bubble Việt và transcript TTS Nhật
   được giữ riêng qua `StageFrame`.
6. Sau commit, history chỉ lưu move family, beat shape, hook class, hash và outcome. Raw OCR/URL không
   được lưu.

## Invariant chính

- Có encounter acknowledgement khi startup greeting được bật và không bị user preempt.
- Hook màn hình/continuity phải có evidence ref hợp lệ.
- Greeting beat không tạo nghĩa vụ trả lời; chỉ beat `reply_bearing=true` mới mở social invitation.
- Tối đa ba speech beat và một câu hỏi.
- Boundary, age, privacy và consent luôn thắng score/persona.
- Public text chỉ đi qua commit path hiện có.
- User bắt đầu chat/VAD thì lượt chưa commit phải nhường.

## Cấu hình

Section `opening_director` trong `settings/runtime_settings.json` có các khóa chính:
`enabled`, `mode`, `max_beats`, `max_questions`, `allow_screen_hook`,
`allow_continuity_hook`, `allow_anime_moves`, `age_band`,
`allow_romantic_flirt`, `romantic_flirt_opt_in`,
`cross_session_personalization` và các cooldown.

Mặc định cross-session personalization và romantic flirt đều tắt. Tuổi không được
suy từ avatar, giọng, màn hình hoặc phong cách viết.

## Kiểm thử và công cụ

- `pytest -q tests/test_opening_*.py`
- `python tools/check_opening_catalog.py`
- `python tools/evaluate_opening_plans.py`

Telemetry dùng namespace `eris.opening.*` và không log raw OCR/full prompt.
