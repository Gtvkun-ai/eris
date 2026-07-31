# PATCH V48 — EVENT-DRIVEN SEMANTIC TUTOR

## Mục tiêu

Bản vá này dùng worker DeepSeek role `tutor` như một **semantic context provider** chạy nền. Tutor không phát ngôn public và không thay Surface. Nó phân rã OCR, vision, DOM/telemetry, media metadata và structured chess state thành một `SharedContextPacket` dùng chung cho chat, chess và autonomous.

## Nguyên tắc chống spam API

Tutor không chạy phân tích sâu theo timer. Runtime chỉ xếp job khi scene bị invalidated bởi một thay đổi có ý nghĩa:

- mở hoặc chuyển ứng dụng;
- chuyển tab, URL hoặc document;
- foreground entity đổi;
- bài nhạc/video đổi;
- bắt đầu ván cờ mới hoặc phase cờ đổi;
- screen delta đủ lớn;
- user yêu cầu nhìn/phân tích màn hình;
- chess policy phát một trigger có ý nghĩa.

Các thay đổi nhỏ như con trỏ di chuyển, timer playback tăng, video progress hoặc OCR dao động nhẹ chỉ cập nhật raw cache. Chúng không gọi DeepSeek Tutor lại.

## Shared Context Packet

Packet giữ riêng:

- activity hiện tại;
- foreground summary;
- direct facts;
- bounded inferences;
- unknowns;
- conversation options;
- research queries;
- response mode scores.

Packet có `scene_id`, `version`, timestamp và TTL. Kết quả của job cũ bị bỏ nếu user đổi scene trong lúc model còn trả lời.

## Chat fallback

Chat chỉ đợi Tutor trong một budget ngắn (`ERIS_SEMANTIC_TUTOR_CHAT_WAIT_MS`, mặc định 250 ms). Nếu packet chưa sẵn sàng, chat vẫn dùng OCR/DOM/media/chess facts thô với policy `facts_only`. Chat không được suy diễn ý định hoặc cảm xúc của user trong fallback này.

Khi packet đã sẵn sàng, chat dùng nó làm nền ổn định và tự phát triển hội thoại quanh foreground. Tutor không bị gọi lại cho từng lượt chat nếu scene không đổi.

## Autonomous và Surface

Blackboard có anchor mới `semantic_scene`. Packet semantic được ưu tiên trước raw OCR khi chọn topic. Packet mới có priority cao để autonomous có thể phản ứng với content vừa đổi; packet cũ vẫn làm nền cho small talk theo cadence nhưng không tự ép hệ thống nói.

Surface chỉ diễn đạt `SpeechIntent` đã được governor duyệt. Surface phải:

- dùng fact trực tiếp như fact;
- giữ inference ở dạng dè dặt;
- không lấp unknown bằng tưởng tượng;
- không đọc lại OCR khi packet semantic đã sẵn sàng;
- không nhắc tới Tutor, packet, scene ID hoặc contract nội bộ.

## Chess

Chess bridge tiếp tục là nguồn thẩm quyền cho FEN/nước đi. Tutor nhận structured chess state để phân rã tình huống người chơi và liên hệ với context khác. Nước đi thường chỉ cập nhật raw state; Tutor chỉ phân tích sâu lại khi game/phase đổi hoặc chess policy phát trigger đáng chú ý.

## Cấu hình

```env
ERIS_DS_TUTOR_API_KEY=
ERIS_DS_TUTOR_BASE_URL=http://127.0.0.1:6014/v1
ERIS_DS_TUTOR_JSONL=1

ERIS_SEMANTIC_TUTOR_ENABLED=1
ERIS_SEMANTIC_TUTOR_CONTEXT_TTL_SEC=900
ERIS_SEMANTIC_TUTOR_CHAT_WAIT_MS=250
ERIS_SEMANTIC_TUTOR_TIMEOUT_SEC=24
ERIS_SEMANTIC_TUTOR_AUTO_SEARCH=1
ERIS_SEMANTIC_TUTOR_SCREEN_DELTA_THRESHOLD=0.35
ERIS_SEMANTIC_TUTOR_SCREEN_DELTA_COOLDOWN_SEC=30
```

Nếu `ERIS_DS_TUTOR_API_KEY` chưa được cấu hình hoặc worker lỗi, runtime vẫn chạy bằng raw facts fallback. Không có local semantic hallucination thay thế.
