# Random Chat Seed V27: ego, độ liều và học sở thích

## Mục tiêu

Vá nguyên nhân gốc của random chat chung chung: Surface không còn phải tự nghĩ chủ đề từ một lệnh rỗng. Trước khi Surface viết câu public, một DeepSeek seed call tạo premise typed từ memory người dùng, shared context và self-context public-safe của ERIS.

## Luồng mới

```text
cơ hội autonomous
  -> RandomChat Seed Generator (DeepSeek)
  -> seed typed: premise + mode + ERIS motive + risk
  -> seed validation / duplicate / boundary gate
  -> Initiative Governor
  -> Surface Worker viết câu public
  -> lưu receipt
  -> user phản hồi
  -> cập nhật affinity và strategy fit
  -> đủ bằng chứng mới promote vào Living User Memory
```

Seed API thay nhánh random-chat của selector; nó không thêm một model call thứ ba. Khi seed trả `none`, runtime im thật và không dựng lại câu presence/check-in.

## Ba lực chọn seed

- **User affinity**: chủ đề, kiểu trêu và opening move từng được đón nhận.
- **ERIS ego**: điều ERIS thực sự muốn chia sẻ, biểu đạt, thử hoặc làm user bật cười.
- **Daring**: ngân sách thử sai xã hội có giới hạn, tách khỏi temperature và không được vượt privacy/boundary.

Mode gồm `user_led`, `shared`, `eris_led`, `experimental`. Seed `eris_led` bắt buộc có `personal_stake` và `authenticity`, tránh biến cá tính thành một lớp tối ưu engagement lịch sự đến vô hồn.

## Học phản hồi

State mới lưu riêng:

- `affinities`: user/strategy fit theo topic tag, mode và opening move;
- `eris_interests`: salience và authenticity của điều ERIS thích chia sẻ;
- `recent`: seed receipt và outcome;
- `pending`: seed vừa nói đang chờ phản hồi.

Phản hồi âm hạ user/strategy fit nhưng **không xóa ERIS interest**. Im lặng là neutral. Preference chỉ được ghi vào Living User Memory khi user nói rõ thích, hoặc có ít nhất ba outcome tích cực độc lập.

## Boundary chính

- chặn seed presence/check-in chung chung;
- chặn intrusion risk cao, daring ngoài lane và ERIS-led không có ego stake;
- chặn premise/topic lặp gần đây;
- không dùng memory nhạy cảm, không suy diễn tâm lý/kế hoạch user;
- Surface được phép nói dạng phát biểu, không phải ép thành câu hỏi hay thêm “còn bạn thì sao”.

## File thay đổi

- `runtime/ai_orchestrated/random_chat_seed.py` mới
- `runtime/ai_orchestrated/model_router.py`
- `runtime/ai_orchestrated/social_initiative.py`
- `runtime/ai_orchestrated/initiative.py`
- `runtime/ai_orchestrated/surface_intent.py`
- `runtime/ai_orchestrated/self_turn_pipeline.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/ai_orchestrated/bootstrap.py`
- `runtime/ai_orchestrated/social_candidate.py`
- `memory/living_user/service.py`
- `tests/test_random_chat_seed_v27.py`

## Cấu hình

- `ERIS_RANDOM_CHAT_SEED_TIMEOUT_SEC`, mặc định `45` giây, giới hạn `8..120`.
- Các cadence hiện tại vẫn quyết định khi nào mở cơ hội. Seed API quyết định có premise đủ thật để nói hay không.

## Kiểm thử

- 9 test mới cho seed contract, ego/daring, chặn generic presence, học outcome, promotion preference, no-seed silence và propagation tới Surface Intent.
- 149 test targeted liên quan social initiative, governor, social agenda, Surface và Living User Memory đạt.
- 29 test bootstrap/runtime đạt.
- Full suite không phụ thuộc thư mục `tools/`: 651 test đạt.
- 4 file test còn lại phụ thuộc các module `tools.*` không có trong source archive gốc (PDF audit/report, packaging và social-plan evaluator), nên không thể collection/chạy trong gói được cung cấp; đây không phải lỗi từ patch.
