# ERIS V38 — INFJ voice / natural public wording

## Mục tiêu

V38 này không thêm một “persona rewriter” sau câu trả lời. Nó sửa đúng tầng sinh lời:

- direct chat writer nhận **voice contract dương tính**, không chỉ một rừng điều cấm;
- autonomous Surface giữ **cognitive shape** của seed thay vì ép tất cả thành “one concise line”;
- personality seed không còn đồng nhất “kín” với “lạnh”;
- technical precision không còn được mô tả như một persona lạnh riêng;
- live personality vẫn là authority về mức ấm/lạnh/gần/xa. V38 chỉ giữ identity of delivery nhất quán.

## Những gì đã đổi

### 1. `runtime/eris_voice_contract.py`

Nguồn canonical mới cho public voice V38:

- guarded warmth = bộc lộ có chọn lọc, **không phải cold brevity**;
- quan tâm rò qua chi tiết, cadence và cách giữ thể diện;
- INFJ seed được phép nhìn tầng nghĩa nhưng không triết lý hóa mọi câu;
- dry humor là phản ứng theo tình huống, không phải preset;
- độ dài theo semantic load, không theo mục tiêu “càng ngắn càng tốt”;
- câu không cần kết thúc bằng support offer/check-in hoặc câu hỏi xã giao;
- autonomous seed giữ hình dạng nhận thức: curiosity / association / opinion / memory callback không bị surface thành cùng một khuôn.

### 2. Direct chat

`runtime/ai_orchestrated/model_router.py`, `llm/prompt_compaction.py`, `llm/service.py`:

- bỏ framing “public writer” ở prompt chính, đổi sang “giọng nói trực tiếp của ERIS”;
- personality context được nói rõ là **expressive authority**, phải ảnh hưởng cadence và mức tự bộc lộ;
- temperature wording tăng nhẹ `0.48 -> 0.56`; semantic/grounding authority không đổi;
- technical turn giữ personality context lớn hơn để không đổi giọng thành ticket support khi vào code/runtime.

### 3. Autonomous Surface

`runtime/ai_orchestrated/surface_intent.py` và Surface prompt:

- bỏ `Write one concise public line`;
- thay bằng “natural public utterance trong sentence budget đã được upstream duyệt”;
- `max_sentences` vẫn là hard budget, nhưng **brevity không còn là objective**;
- seed không được đánh bóng thành aphorism;
- tránh collapse tất cả autonomous line vào `Tôi đang nghĩ...` / `Tôi tự hỏi...`;
- followup phải nghe như continuity của unresolved point, không như notification template.

### 4. Personality seed / legacy path

`llm/contracts.py`, `runtime/voice_policy.py`:

- bỏ `Guarded warmth: ... ấm rất ít`;
- thay bằng “kín ở mức tự bộc lộ, lớp ngoài vẫn ấm và tinh tế”;
- bỏ `cold precision in technical tasks`, đổi thành `warm clarity`;
- voice constraint ghi rõ `clarity is not coldness`.

## Cái V38 cố ý KHÔNG làm

- không đổi Neuro authority;
- không nới grounding;
- không cho Surface bịa environment;
- không thêm một LLM polish pass;
- không thêm regex “humanizer” sau output;
- không sửa screen-router `nhắc lại -> vision` trong cùng patch vì test đó đã fail trên baseline upload và là bug độc lập.

## Test

Focused V38: `9/9 pass`.

Compatibility quanh public writer / personality / Surface / seed / voice: `98/98 pass`.

Grounding / semantic / startup prompt liên quan: `12/12 pass`.

Tổng nhóm regression đã chạy cho patch này: **119 pass**.

Ngoài scope có test `tests/test_run_20260811_repairs.py::test_plain_nhac_lai_is_not_routed_as_music_or_screen` fail cả trên baseline upload (`vision` thay vì `none`). Không tính là regression V38.

## Deploy

Sau khi chép source V38 vào repo thật, chạy một lần:

```bat
src\tools\prepare_v38_runtime.bat
```

Kỳ vọng:

```text
[V38 PREFLIGHT] PASS: eris.voice.v38.inflective_infj
```

Sau đó mới chạy `run_eris.bat`.

## Test người nên chạy đầu tiên

Đừng test bằng câu “hãy nói như INFJ”. Hãy test bằng các tình huống không nhắc style:

1. Chat kỹ thuật ngắn: xem nó có chính xác nhưng còn cùng giọng ERIS không.
2. User trêu nhẹ: xem dry humor có nảy tự nhiên hay không.
3. User nói một câu hơi buồn/riêng tư: xem warmth có hiện qua cadence chứ không thành therapist/support bot.
4. Autonomous curiosity / association / opinion liên tiếp: kiểm tra rhetorical shape có thực sự khác nhau.
5. Một seed rất ngắn: Surface không được biến nó thành châm ngôn dài.
6. Một câu cần trả lời dài: direct chat không được tự nén thành “một câu cho gọn”.

Điểm cần nghe nhất: **ERIS có cùng một nhịp người khi chuyển từ đời thường sang kỹ thuật hay không.** Nếu vào code là lập tức biến thành tài liệu API, V38 chưa đạt.
