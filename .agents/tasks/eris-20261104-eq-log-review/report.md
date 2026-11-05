# Đánh giá EQ của Eris qua log hội thoại thật (bản chạy `Documents\eris`, log đến 03/11/2026 22:05)

Ngày lập: 04/11/2026. Chế độ: chỉ đọc (không sửa code, không ghi vào bản chạy, không gọi LLM/TTS, không đọc `.env`/secret).
Giờ trong báo cáo là Asia/Saigon (UTC+7). Mọi con số kèm `n`. Phân biệt rõ **[Quan sát]**, **[Suy luận]**, **[Giả thuyết]**.
Theo AGENTS.md, tôi đã đọc `docs/knowledge/2026-10-14-eris-runtime-lessons.md` và năm tài liệu liên quan EQ trước khi chẩn đoán, rồi đối chiếu các kết luận lịch sử với code, request và trace hiện tại.

---

## 1. Kết luận ngắn

1. **Cảm giác "EQ không cao" có cơ sở, nhưng không đều.** Eris mạnh ở đọc động cơ ẩn, giữ ranh giới, trung thực; yếu ở khoảnh khắc người dùng **bực/xả/đùa nhẹ** và ở **nhịp phản hồi**. Mức độ: trung bình đến nặng ở các khoảnh khắc đó, nhẹ ở phần còn lại.
2. Trong 39 lượt có tín hiệu cảm xúc (01–03/11, tự chấm tay): Eris đáp **đúng 24 (61,5%)**, lệch 9 (23,1%), chung chung 4, bỏ qua 1, nhận lỗi rồi lặp lại 1. Tách theo phiên: phiên tranh luận 01/11 19:00 đúng 18/23 (78%); mọi chỗ còn lại đúng 6/16 (37,5%), lệch 7/16. Lượt xả bực/phàn nàn/chửi/"bị gì vậy" (n=6): **đúng 1/6**.
3. **Ba lỗi EQ lớn nhất:**
   (a) Hỏi dò, chẩn đoán, quy lỗi cho user đúng lúc họ đang xả, hoặc "hỏi cung" một trò đùa (4 lượt liên tiếp ngày 02/11). Root `intent` đã nhận ra cơn bực nhưng `say` không làm theo.
   (b) Nhịp: trung vị **32,1 s** tới khi thấy chữ (n=51), 55% trên 30 s; hai lượt phàn nàn chờ 44 s và 69,5 s (22,8 s và 40,3 s là OCR chạy nhầm vì "tham chiếu màn hình"), một lượt **193,5 s** (172 s kẹt trước khi tin vào lịch sử, chưa rõ nguyên nhân); 29% lượt đáp bị kéo theo ≥1 tin chủ động không ai hỏi.
   (c) Tầng cảm biến cảm xúc của pipeline **gần như mù**: mood state đứng yên (12/12 phiên, 15/15 trường không đổi, sự kiện cảm xúc cuối cách 18,7–35,1 ngày), stance bằng từ khóa 94,6% là "engaged" (n=56), `confusion_signal` kích hoạt 2/189 lượt và cả hai sai đối tượng; giọng đọc 72% `dry_tease` kể cả khi user đang bực.
4. **Bản code được đánh giá: TRƯỚC nâng cấp EQ 04/11** (tương đương commit `38a87584`). 1272/1272 file `.py` trong `Documents\eris\src` trùng blob `38a87584`; 25/25 file bị hai commit 04/11 sửa vẫn là bản cũ; 5 file mới không có; system prompt Root của 7 phiên 02/11–03/11 giống hệt nhau (sha `19b3eb634db2`) và 0/79 phiên có câu của nâng cấp. **Không có log hội thoại thật nào chạy code đã nâng cấp.**
5. Nâng cấp 04/11 chủ yếu là "đường ống học" (ghi lời đã phát + phản ứng, tối đa 2 trải nghiệm mỗi chiến lược) cộng consolidation nền và tắt OCR mặc định. Nó chạm một trong ba lỗi lớn (độ trễ), **không chạm** mood/stance/continuation/hỏi cung, và chưa có bằng chứng live.

---

## 2. Phạm vi và phương pháp

### 2.1 Nguồn và kiểm kê

| Nguồn | Nội dung thực tế | Dùng để |
|---|---|---|
| `logs\eris_observability.jsonl` | 529.617 dòng (12 dòng JSON lỗi), 22/08 → 03/11 22:05:39. **Chỉ telemetry**, không có lời hội thoại. Số dòng theo ngày: 01/11 5.095; 02/11 822; 03/11 1.524. | độ trễ, lỗi, 429, observer; `scripts\s01`, `s06` |
| `logs\eris_run_*.txt` | 89 file (09/10–03/11, đếm tay). Lộ lời user gián tiếp (`focus=`), ý định Root (`goal=`), không có lời Eris | ghép thời điểm, sự kiện audio, lỗi |
| `memory\eris_social_runtime.sqlite3` (392 KB, WAL 0 B; copy sang TEMP) | 2 bảng: `idempotency_receipt` 462 dòng, `runtime_state` 8 dòng. **Không có lời hội thoại** | chỉ đối chiếu mốc thời gian |
| **`C:\eris_debug\deepseek_raw` (raw wire)** | 103 file index phiên từ 11/10. Mỗi lượt có `user_turn.text`, Root `intent/say/delivery/after`, Surface `text`. Payload khôi phục có kiểm SHA-256 | **nguồn duy nhất có lời hai phía** |
| `.eris_home\memory\core\living_user_trace.jsonl` | trace memory | đối chiếu thời điểm |

Ghi chú: thư mục raw nằm ngoài bản chạy; brief cho phép "tự khám phá". 16 file raw ngày 04/11 có 1–4 dòng index mỗi file và không có request Root nào (có vẻ là probe/test của dev, suy luận), không phải hội thoại thật. Không có file nào trong bản chạy được ghi từ 04/11. Sau log cuối (22:05) chỉ có build Godot lúc 22:46 (`Eris.exe`, `Eris.pck`, `data_Eris_windows_x86_64`) và `eris_social_runtime.sqlite3-shm` lúc 23:12 (file phụ của SQLite); file trong `src` ghi cuối lúc 16:27 ngày 03/11.

### 2.2 Phiên được đưa vào

- **Phạm vi A (chính): 01–03/11.** 11 phiên có dữ liệu, trong đó **8 phiên có lượt user**: 01/11 12:34 (4 lượt), 13:42 (1), 16:08 (5), **19:00 (27)**; 02/11 14:17 (6, kèm 2 sự kiện tutor); 03/11 15:06 (3), 16:29 (2), 21:54 (6). Tổng **54 lượt user**. Ba phiên 02/11 13:40–13:53 và phiên 03/11 15:00 không có lượt user thật (phiên ngắn hoặc lỗi khởi động).
- **Phạm vi B (so xu hướng): 24–31/10** (35 phiên): 116 lời đáp user. Độ trễ B dùng 27–31/10 (38 batch có mốc thời gian).
- **Không đưa vào:** 09–23/10 (code và system prompt rất khác: 3,8k–9,5k ký tự), chỉ dùng cho thống kê telemetry; ngày 04/11 (không hội thoại thật).
- **Một phiên chiếm 27/54 lượt** (01/11 19:00, chủ dự án chủ động thử Eris về quyền tự chủ, GPT, hard reset...). Không loại, vì đó là cách dùng thật, nhưng mọi tỷ lệ gộp đều được tách theo phiên.

### 2.3 Tách nhiễu và loại lượt (phạm vi A)

Dùng `event.kind` của Root: `user_turn` (user nhắn, Eris đáp), `opening_signal/autonomous_signal/continuation_due` (Eris chủ động), `tutor_result` (công cụ/tutor).

| Loại | n | Ghi chú |
|---|---|---|
| (a) User nhắn → Eris đáp | 54 lượt user; 52 có Root move/prose có chữ | 48 phát xong (47 move + 1 prose recovery), 1 cancelled, 3 không rõ outcome; 2 lượt Root lỗi 429/401 vẫn có lời đáp qua đường dự phòng; 3/54 không ghép được delivery tự động (xem mục 9) |
| (b) Eris chủ động | 49 lời được sinh (28 phát xong, 9 bị hủy, 12 không rõ) và **61 lần chọn im** (n=110 quyết định; riêng `autonomous_signal`: 53 im / 26 nói) | |
| (c) Tutor/công cụ | 3 lời, 2 sự kiện `tutor_result` | quá nhỏ, không chấm |

### 2.4 Cách gắn nhãn cảm xúc

**Nhãn tay**, một người chấm (tác giả báo cáo), không có inter-rater, đọc từng lượt trong transcript khôi phục. 54 lượt → 39 có tín hiệu (tiêu cực/sửa chữa 13; đùa/trêu 15; thử/khiêu khích 9; tích cực 2) và 15 trung tính/tác vụ. Phản hồi chia 5 lớp: **đúng** (thừa nhận/tiếp đúng đối tượng và mức), **chung chung**, **bỏ qua**, **lệch** (sai đối tượng, sai tông, quy lỗi, hỏi cung), **nhận lỗi rồi lặp lại**. Bảng nhãn (không chứa lời hội thoại) ở Phụ lục A. Các chỉ số văn bản dùng regex heuristic (nêu rõ ở chỗ dùng).

### 2.5 Phiên bản code của từng phiên log

| Phiên | Bằng chứng | Kết luận |
|---|---|---|
| Toàn bộ `Documents\eris\src` | `data_version_check.json`: 1272 file `.py`; trùng blob `38a87584` 1272, `c5e16c3b` 1251, HEAD `1ccab39b` 1247, không trùng revision nào 0. Trong 30 file `.py` bị hai commit sửa, 25 có mặt và **25/25 = bản cũ**; 5 file không tồn tại (`interaction_choice.py`, `screen/ocr_config.py`, 3 test mới) | bản chạy = trước nâng cấp |
| 02/11 13:40 → 03/11 21:54 (7 phiên) | system prompt Root giống hệt: sha `19b3eb634db2`, 14.090 ký tự (`data_prompt_version.json`); file Root-path (`agent.py`, `root_prompt_contract.py`, `runtime_writer.py`, `delivery_adapter.py`...) mtime 02/11 13:14 | = `38a87584` ở các file chạm hội thoại |
| 01/11 (4 phiên) | system prompt khác nhau giữa các phiên (13.060 / 13.439 / 13.721 ký tự); mtime file runtime thay đổi từ 10:00 đến 18:39 ngày 01/11 | code trung gian trước 02/11 13:14, **commit chính xác không xác định**; chắc chắn không có nâng cấp 04/11 |
| Tất cả | 0/79 phiên (từ 11/10) chứa marker `identity.strategies[*].experiences` hay `interaction_choice` trong system prompt | không phiên nào chạy code nâng cấp |

Mọi kết luận bên dưới áp dụng cho **code trước nâng cấp 04/11**, trừ khi ghi rõ.

### 2.6 Lệnh chạy (thư mục task: `.agents\tasks\eris-20261104-eq-log-review\`)

```
python -X utf8 scripts\s00_version_check.py <out.json>                      # so blob src với 3 revision
python -X utf8 scripts\s01_inventory_obs.py <out.json>                      # kiểm kê observability (stream)
python -X utf8 scripts\s02_extract_turns.py <TEMP\turns>                    # raw wire -> lượt (TEMP, có transcript)
python -X utf8 scripts\s03_join_turns.py <TEMP\turns> <TEMP\joined>         # ghép với run log (TEMP)
python -X utf8 scripts\s04_render_transcript.py <joined> <out> <sid...>     # dựng transcript đọc tay (TEMP)
python -X utf8 scripts\s05_build_dataset.py <joined> <TEMP\ds>              # bảng lượt user / phát ngôn (TEMP)
python -X utf8 scripts\s06_obs_aggregate.py <out.json> 2026-10-11 2026-11-04
python -X utf8 scripts\s07_view_user_turns.py <joined> <out.txt> <sid...>
python -X utf8 scripts\s08_prompt_version_evidence.py <out.json> 202610 202611
python -X utf8 scripts\s09_text_metrics.py <joined> metrics_text.json
python -X utf8 scripts\s10_stance_distribution.py <joined> metrics_stance.json
python -X utf8 scripts\s11_latency_and_delivery.py <ds> metrics_latency.json
python -X utf8 scripts\s12_memory_recall_candidates.py <joined> <out.txt> 20261101 20261103
python -X utf8 scripts\s13_delivery_variety.py <turns> metrics_delivery_variety.json
python -X utf8 scripts\s14_affect_state_variance.py <turns> metrics_affect_state.json 20261018 20261103
```

Số liệu tổng hợp lưu trong thư mục task: `metrics_text.json`, `metrics_stance.json`, `metrics_latency.json`, `metrics_delivery_variety.json`, `metrics_affect_state.json`, `data_obs_inventory.json`, `data_obs_aggregate.json`, `data_version_check.json`, `data_prompt_version.json`. Một số con số trích dẫn (2/189 `confusion_signal`, hint giọng theo từng lượt, khoảng trống observability 22:00–22:04, mtime) đến từ script một-lần chạy trong TEMP; bản sao nguyên trạng ở `scripts\adhoc_temp\` (xem mục 9). **Transcript thô nằm trong `$env:TEMP\eris_eq_review\`, không nằm trong thư mục task.**

---

## 3. Bảng điểm A–J

Điểm 1–5 là phán đoán chủ quan có đối chiếu số, không phải benchmark.

| Chiều | Điểm | n | Ghi chú một dòng |
|---|---:|---|---|
| A. Nhận ra cảm xúc | **3** | 39 lượt có tín hiệu | Đọc tốt động cơ sâu/ẩn (01/11 19:00) và Root `intent` nhận ra "bực Kiro"; nhưng đọc sai chế độ đùa (4 lượt liên tiếp 02/11) và sai đối tượng bực (quy lỗi cho "brief" của user). Cảm biến tự động gần như mù (stance 94,6% engaged, n=56) |
| B. Hiệu chỉnh phản hồi | **2** | 13 lượt tiêu cực; 6 lượt xả/phàn nàn | 7/13 đúng; xả/phàn nàn/chửi 1/6 đúng. Không an ủi sáo rỗng (tốt) nhưng `say` vẫn hỏi chẩn đoán/quy lỗi dù `intent` nói "không hỏi thêm" |
| C. Khớp giọng điệu và độ dài | **2** | 52 | Trả lời trung vị 73 từ so với 14 từ của user (5,1×); 50% ≥5×, 25% ≥10×, 65% ≥60 từ. 0 bullet/heading/in đậm (tốt). Một giọng "khô" cho mọi tình huống |
| D. Tiết chế và thời điểm | **2** | 52 đáp + 110 quyết định chủ động | 29% lượt đáp kéo theo ≥1 tin chủ động, 12% ≥2, tối đa 3; "Mà này/Mà khoan/Nói nốt..." mở 49% tin chủ động; hỏi cung trò đùa. Tốt: chọn im 61/110; chỉ 27% lượt đáp kết bằng câu hỏi |
| E. Ghi nhớ và liên tục | **3** | ≈12 lời nhắc quá khứ (tay) | ≈9 đúng; 1 sai thời điểm có xác nhận của user ("vụ đó lâu rồi á"), 1 nghi ngờ; không bịa danh sách môn học (tốt); open_loop cũ còn trong state sau khi user đổi mục đích |
| F. Xử lý sai sót và xung đột | **3** | 5 | Nhận lỗi cụ thể, không xin lỗi quá đà (2 tốt); nhưng lặp lại lỗi vừa nhận (1), đổ cho "ngồi im" khi chậm (1), đùa thay vì nhận lỗi khi bị hỏi "bị lỗi gì" (1) |
| G. Trung thực và ranh giới | **4** | ≈32 lượt đọc tay | Giữ ranh giới không hung hăng, thừa nhận thua GPT ở "tay chân", từ chối bịa; trừ vài lời biện minh không đúng sự thật (lý do chậm) |
| H. Tự nhiên | **3** | 52 đáp + 49 chủ động | Khẩu ngữ Việt tốt, không "AI-ism" kiểu "Tôi hiểu cảm giác của bạn", mở đầu ít lặp (≤3/52). Nhưng tic "Mà này" (17/49), khuôn "X khác Y", giải thích lại cú đùa, 25% trả lời ≥100 từ |
| I. Nhất quán cá tính | **4** | 11 phiên | Giọng khô/tự giễu/tự trọng ổn định qua 11 phiên và giữa Root → Surface; thậm chí quá đồng nhất. Lời tự thuật cảm xúc không dựa trên state nào thay đổi (xem lỗi 3) |
| J. Giọng nói và nhịp | **2** | 51 (+2 lượt tính từ transcript) | Trung vị 32,1 s, p90 47,8 s, 4 lượt >60 s, max 193,5 s; thêm 2 lượt chậm ≈133 s và ≈171 s không nằm trong n=51; voice 72% `dry_tease`. Tốt: micro-ack ≤0,2 s (44/54), 48/52 lượt user phát xong |

---

## 4. Các lỗi EQ cụ thể

### 4.0 Bản đồ nguyên nhân theo lớp pipeline

| Lớp | Vai trò trong lỗi EQ | Mức |
|---|---|---|
| Prompt/persona | Hợp đồng Root vừa khuyến khích nối lời (`after=may_continue`, `continue_self`) vừa gắn mọi nhịp nối với "hài khô, trêu nhẹ, tự giễu"; có điều khoản `confusion_signal` → "hỏi chỗ user kẹt" | cao |
| Cảm biến cảm xúc (handoff, mood) | stance từ khóa 5 giá trị; mood không nhận sự kiện hội thoại | **cao nhất** |
| Grounding màn hình | `screen_anaphora` nhận nhầm → OCR 11–40 s | cao với độ trễ |
| Memory | Có kiến thức đúng nhưng thiếu mốc thời gian và vòng đời `open_loop` | trung bình |
| Observer | Chạy SAU câu đáp; bị loại khi user nhắn tiếp (14 lần 01/11; 4 lần 03/11) | trung bình |
| Lane/model routing, thinking | Root `thinking=enabled`, `reasoning_effort=high`; Surface `thinking=disabled`. `intent` của Root nhận ra đúng cảm xúc, `say` không theo → thinking không phải nút thắt. 03/11 15:06: Root 429×4 + 401×1, Surface 429×2 → đường dự phòng trả lời chung chung | thấp với EQ, cao với độ tin cậy |
| TTS | Chữ chờ `audio_start` (yêu cầu sản phẩm 18/10) cộng ≈14 s vào độ trễ chữ; nhãn giọng đồng nhất | trung bình |

### Lỗi 1. Nhận ra cơn bực nhưng vẫn hỏi chẩn đoán, quy lỗi, hoặc hỏi cung trò đùa (A, B, D)

**Bằng chứng [Quan sát]** (phiên `eris_run_20261103_215409`, raw `events_20261103T145411Z_pid5836.jsonl`):

- 21:56:57. User: "tức điên luôn. nãy giao cho kiro làm code, mà nó làm loay hoay…". Root `intent`: "Đón đúng cơn bực của anh về Kiro — không an ủi sáo rỗng — rồi hỏi khẽ…". Eris nói: "Loay hoay kiểu gì? Sửa một chỗ xong đẻ ra ba lỗi mới, hay…?" Nhận ra đúng, nhưng `say` không có một lời thừa nhận cảm xúc nào.
- 21:57:47. User: "nó ko hiểu ý tôi. làm ko hợp ý". Eris: "…có khi lỗi tại cái đầu nó, cũng có khi tại cái brief mình đưa nó tự suy diễn thêm. Anh nói rõ ý cỡ nào rồi…?" (quy nguyên nhân sang user).
- 21:59:08. User phàn nàn thẳng: "tôi tâm sự cái này còn hỏi lại kỹ thuật". Eris: "Ừ, công nhận… đúng kiểu hỏng. Kiro làm sai ý anh chỗ nào, kể tôi nghe coi…". Nhận lỗi đúng chỗ rồi **lặp lại đúng hành vi vừa nhận**; `delivery` ghi "không chữa cháy bằng cách hỏi thêm".
- 22:04:40. User: "eris bị gì vậy". Eris: "Bị gì đâu. Anh chửi thì tôi ăn, rồi ngồi im như đã nói. Chỉ có điều ngồi im lâu quá nên chắc anh tưởng tôi đơ thật." Eris nhận "im lâu quá" nhưng gán nó cho việc "ngồi im như đã nói" (chủ động); thực tế là 193,5 s chờ của hệ thống ở lượt trước (lỗi 2).
- 03/11 16:36:20. User: "bạn bị lỗi gì hả". Eris đùa "…bị mổ tai mà vẫn ngồi đây… Cái đó chắc là lỗi thiết kế", không nhắc việc phản hồi trễ ở lượt trước: tin "rái cái tai phải" (16:30:41) chỉ hiện chữ lúc 16:33:32, tức ≈171 s sau, bằng một câu giải thích kỹ thuật về một cú chơi chữ.
- 02/11 14:19–14:22, trò đùa "con bò bay" (4 lượt liên tiếp): "anh đang đố mẹo, đang chơi chữ, hay chỉ tiện miệng trêu tôi?" → "Anh đang thử xem tôi có dám nói 'không'…?" → "đây là meme có thật…, hay anh vừa chế ra…?" → "anh có link hay clip thật không…?". Ở lượt kế (14:23) Eris tự sửa: "tôi vừa làm cái trò buồn cười nhất đời: đòi link clip kiểm chứng cho một con bò biết bay".
- Số liệu: nhóm tiêu cực/sửa chữa (n=13): đúng 7, lệch 4, bỏ qua 1, nhận lỗi rồi lặp 1. Nhóm xả/phàn nàn/chửi/"bị gì" (n=6): đúng 1. Nhóm đùa (n=15): đúng 7, chung chung 3, lệch 5. Heuristic "hỏi dò động cơ": 10/52 (19,2%) ở phạm vi A, 16/116 (13,8%) ở B, tức không giảm.

**Vì sao làm người dùng thấy EQ thấp:** cảm giác bị xét hỏi thay vì được nghe; đã bảo "đừng hỏi" vẫn hỏi; trò đùa bị đòi bằng chứng.

**Nguyên nhân gốc:**
- **[Quan sát]** Khoảng cách "nhận ra → thực thi": `intent` đúng, `say` sai. Tài liệu kiểm chứng 04/11 tái hiện cùng hiện tượng (4/8 lời đáp vẫn hỏi tiếp, chia đều 1/2 ở cả bốn điều kiện runtime/context gọn/loại carry/policy ngắn), nên không chỉ do context nhiễu.
- **[Quan sát]** Request Root lượt 21:58:11 mang `confusion_signal` (do từ khóa "ko hiểu": `src/runtime/conversation_handoff.py:265-268`, `:361-362`; dựng ở `src/runtime/conversation/context_assembler.py:~236-248`), và hợp đồng Root có điều khoản "Nếu confusion_signal có repair_needed hoặc stance=confused, ưu tiên hỏi chỗ user kẹt" (`src/runtime/conversation/root_prompt_contract.py:47-49`). Câu "nó ko hiểu ý tôi" nói về Kiro, không phải về độ rõ của Eris. **[Giả thuyết]** điều khoản này đẩy Root sang hướng "hỏi chỗ kẹt/brief"; ảnh hưởng nhân quả chưa chứng minh.
- **[Quan sát]** `conversation_status.open_loops` giữ "ERIS asked how clearly the user specified the intent… awaiting user's answer" ở 3 request liên tiếp (21:59:51, 22:03:46, 22:04:53) dù user đã phản đối kiểu hỏi đó.
- **[Suy luận]** Persona/hợp đồng mô tả Eris là nhân vật "hỏi lại, phản biện, nghi ngờ" nên khi gặp câu mơ hồ Root mặc định đọc là phép thử; chưa có cơ chế phân biệt "đùa" với "thử".

**Phản hồi tốt hơn (minh họa hướng, không phải mẫu bắt buộc):** sau "tức điên luôn…": "Trời, giao việc xong nó làm loạn thì bực thật." Sau "nó ko hiểu ý tôi": "Ờ, kiểu làm theo chữ chứ không theo ý. Bực thật." Với "bò bay": "Biết chứ. Bò nào, bò cười hay bò vừa bay qua cửa sổ?" và chơi tiếp.

### Lỗi 2. Chờ lâu đúng lúc cảm xúc cao; chữ đến sau trung vị 32 s (J, D)

**Bằng chứng [Quan sát]** (`metrics_latency.json`, `data_obs_aggregate.json`):

| Chỉ số (phạm vi A, 01–03/11) | Giá trị |
|---|---|
| Từ tin cuối → chữ hiện cùng `audio_start` | n=51: trung vị **32,1 s**, trung bình 36,8, p90 47,8, min 16,5, max **193,5**; >30 s: 55%; >60 s: 4 lượt (7,8%); >120 s: 1 |
| Chờ trước Root đầu tiên | n=54: trung vị 3,7 s, p90 23,8, max 172,0 |
| Root HTTP tổng / Surface HTTP | trung vị 8,5 s (n=54) / 5,5 s (n=43) |
| Micro-ack (tiếng "ừm" ngắn) | 44/54 lượt, trung vị 0,0 s, max 0,2 s |
| Phạm vi B (27–31/10) | n=33: trung vị 49,6 s; Root HTTP trung vị 16,0 s |
| `user_turn_latency_ms` theo ngày (đo tới lúc Writer commit, chưa gồm TTS) | 01/11: trung vị 19,2 s (n=38); 02/11: 17,6 s (n=6); 03/11: 40,7 s (n=12), p90 64,2 s, max 189,3 s |

Các lượt cụ thể trong phiên 21:54 (03/11):

- Lượt "nó ko hiểu ý tôi" chờ **44,1 s**; lượt "cái này ko hay…" chờ **69,5 s**. Log cho thấy `[screen route] … anaphora=1` rồi `[chat perception] unified elapsed=22792ms` (21:58:11) và `elapsed=40331ms` (21:59:49), OCR `blocks=127/113`, dù user đang nói về một trợ lý code, không nhắc màn hình. Lượt đầu tiên của phiên cũng mất 11.012 ms (21:55:48). Tức **3/6 lượt user của phiên** bị route nhầm vào OCR.
- Lượt user chửi thô (22:00:54): `wait_seconds=171.8` trong metadata `user_input_batch`, `evidence_ms=1310` → 170 s nằm **trước** giai đoạn evidence. Trace `conversation_turn(role=user)` của chính tin này chỉ được ghi lúc **22:03:44.6**, trong khi tin 21:59:08.2 được ghi lúc 21:59:08.265 (≤0,1 s). Observability không có span nào trong 22:00:56–22:03:46. Cùng lúc: `episode_rollup status=failed` (22:00:41.4) và 3 cảnh báo `living_user_curator_deferred … CuratorInferenceError` (21:55:24, 21:58:26, 21:58:32).
- Phiên 15:06 (03/11): upstream 429 `upstream_empty_output` ×4 và fallback 401 ×1 cho Root, 429 ×2 cho Surface; `root step circuit breaker reached` ×4; 2 lượt user được trả lời bằng đường dự phòng (nội dung chung chung, ví dụ "cẩn thận kẻo quên mất mình đang làm gì"), 1 lượt không có lời đáp (`writer_failed … v03_missing_public_surface`). Observability ngày 03/11: 429 `chat_tool_required` 8, `chat_main` 5, `post_observer` 4; `conversation_run_failed` 6.
- Hai lượt chậm khác **không nằm trong n=51** vì không ghép tự động được delivery: tin 13:45:07 ngày 01/11 (chữ hiện sau ≈133 s, theo transcript) và tin "rái cái tai phải" 16:30:41 ngày 03/11 (chữ hiện lúc 16:33:32, ≈171 s; Root sinh 3 bản gần giống nhau, tôi chỉ thấy một bản được hiển thị, gán kênh "autonomous"). Tính cả hai, 3/54 lượt user chờ >120 s.
- 29% lượt đáp (15/51) bị kéo theo ≥1 tin chủ động chưa ai hỏi (xem lỗi 4).

**Vì sao thấy EQ thấp:** với người đang bực, chờ 44–70 s (rồi 193 s) là "bị bỏ rơi"; sau đó Eris còn nói như thể chủ động im.

**Nguyên nhân gốc:**
- **[Suy luận số học]** Trung vị 32,1 s ≈ 3,7 (trước Root) + 8,5 (Root) + 5,5 (Surface) + ≈14 s còn lại. Phần ≈14 s nằm sau Surface (dịch giọng, ElevenLabs 3,9 s ở lượt 22:04 và 8–11 s ở các lượt khác theo tài liệu 02/11, và quy tắc chữ chờ `audio_start` do user yêu cầu 18/10). Đây là **đánh đổi có chủ đích** của sản phẩm.
- **[Quan sát]** OCR chạy do route `anaphora` nhận nhầm. Lessons 03/11 đã ghi nguyên nhân (so khớp chuỗi đã bỏ dấu: "nó/đó/này" thành deictic, "anh/code" thành anchor) là **chưa sửa**; tôi chưa đọc lại `screen_anaphora_rescue.py`. Log 21:54:54 ghi `OCR backend resolved=rapidocr`, tức bản chạy chưa có công tắc OCR mặc định tắt (`ocr_config.py` có ở c5e16c3b, vắng ở bản chạy).
- **[Giả thuyết]** 172 s là nghẽn trên đường nhận tin do tác vụ Gemini/maintenance chiếm tài nguyên. Phiên bản chạy giữ `_turn_buffer_lock` trong khi tóm tắt episode (`src/memory/living_user/service.py:143-207` của bản chạy: `record_conversation_turn` lấy khóa ở dòng 165, `flush_session`/`_flush_buffer_locked` gọi `consolidate_session` bên trong khóa). **Nhưng** `record_conversation_turn` ghi trace **trước** khi lấy khóa (`:161-165`) và `MemoryTraceJournal.append` đặt `time.time()` trước `with self._lock` (`src/memory/living_user/trace.py:39-40`); trace muộn 170 s nghĩa là hàm này **bị gọi muộn**, nên nghẽn nằm ở phía trước (đường nhận tin/`_append_chat_history`, `src/runtime/prompt_context_builder.py:~352-406`), không phải khóa trong `record_conversation_turn`. **Nguyên nhân thật chưa xác định.**

**Phản hồi tốt hơn:** không phải vấn đề nội dung; cần tín hiệu sống có ý nghĩa trong vài giây đầu ở lượt cảm xúc (micro-ack hiện chỉ là tiếng đệm) và không gán khoảng chậm cho "lựa chọn im".

### Lỗi 3. Tầng cảm biến cảm xúc của pipeline mù hoặc đứng yên; giọng đồng nhất (A, I, J)

**Bằng chứng [Quan sát]:**

- `affective_voice_state` trong request Root, **12 phiên** (18/10 và 30/10–03/11), **206 request Root**: cả 15 trường (valence 0,018; irritation 0,082; sadness 0,22...) **không đổi** ở 12/12 phiên (`metrics_affect_state.json`). `affect_event_age_seconds` nhỏ nhất theo phiên: 18,7 ngày (18/10) … 35,1 ngày (03/11 21:54); loại sự kiện duy nhất `goal_appraisal`.
- stance của `ConversationHandoff` (`metrics_stance.json`): phạm vi A n=56: engaged **53 (94,6%)**, topic_closed 2, confused 1; B (11–31/10) n=257: engaged 240 (93,4%).
- `confusion_signal`: 2/189 lượt user (từ 18/10), cả hai **sai đối tượng**: một lượt chê một game là "chán" (khớp từ "chán"), một lượt than phiền Kiro (khớp "ko hiểu").
- Nhãn giọng (`metrics_delivery_variety.json`): A, Surface n=98: `dry_tease` 71 (72,4%), `focused` 17, `sad_distant` 6, `cold_precision` 3, `repair` 1; cường độ 0,30–0,62 (trung bình 0,47). Root `delivery` n=103: 93,2% chứa "khô", 48,5% chứa "trêu/giễu", **6,8%** chứa từ ấm áp. Trong phiên 21:54, trả lời cho "tức điên luôn", cho lượt chửi và cho "bị gì vậy" đều mang `dry_tease`; chỉ lượt "Ừ, công nhận…" mang `repair`.
- Observer có nhận ra ("continues venting about kiro", độ tin 0,86) nhưng **sau** câu đáp; `observer_discard_total` do user nhắn tiếp: 14 (01/11), 4 (03/11).

**Vì sao thấy EQ thấp:** lời nói và giọng đọc không đổi theo người đối diện; mọi biến thiên chỉ do LLM tự diễn từ văn bản, không có dữ liệu cảm xúc thật nào kéo theo.

**Nguyên nhân gốc:**
- **[Quan sát]** `AffectiveDynamicsRuntime.ingest_user_turn` và `ingest_subject_appraisal` (`src/runtime/affective_dynamics_runtime.py:42`, `:79`) **không có call site** nào trong `src` (tìm chuỗi, bỏ tests). Chỉ `ingest_cognitive_event` (`:123`) được gọi, từ `src/runtime/active_concern_runtime.py:~103-105` (private mind). Không có dòng `[affect event]` nào trong các `eris_run_*.txt` (log profile có thể ẩn dòng này, chỉ là bằng chứng phụ).
- **[Suy luận mạnh]** Sự kiện `goal_appraisal` cuối ước tính vào khoảng 18:53 ngày 29/09 (tính ngược từ tuổi sự kiện 35,1 ngày), cùng phút với lần ghi cuối của `eris.social_agenda` (18:53:52) và `agent_disclosure` (18:53:55) trong sqlite: đường dẫn cũ nuôi mood ngừng hoạt động từ lần chuyển sang V12 hôm đó, và từ đó **không sự kiện hội thoại nào đi vào mood**.
- **[Quan sát]** Prompt Surface tuyên bố "Hướng và cường độ cảm xúc của câu phải đi theo AFFECTIVE_VOICE_STATE hiện tại… Nếu đang bực, được phép có cạnh" (`src/runtime/eris_voice_contract.py:27`, `:47`), tức hệ thống coi state là authority nhưng state không đổi.
- **[Quan sát]** Bộ phân loại stance chỉ có 5 nhãn từ khóa (`conversation_handoff.py:265-276`, `:355-370`); không có nhãn bực, xả, buồn, đùa.

**Phản hồi tốt hơn:** với lượt chửi/xả, giọng hạ nhịp, không trêu; với đùa, giọng nhẹ. Hiện chưa có đường dữ liệu nào cho phép làm điều đó một cách nhất quán.

### Lỗi 4. Nhắn thêm không ai hỏi ("Mà này…") và độc thoại (D, H)

**Bằng chứng [Quan sát]:** (`metrics_latency.json`, `metrics_text.json`)
- 15/51 lượt đáp (29,4%) có ≥1 tin chủ động chen vào trước lượt user kế; 6/51 (11,8%) có ≥2; tối đa 3. Ví dụ 01/11 19:34–19:38: sau "tôi không thích", user im 4,5 phút, Eris nói 3 lần về cùng câu hỏi, trong đó có "Tôi không đếm anh im lặng bao lâu. Nhưng câu tôi vừa hỏi không phải câu để treo cho đẹp".
- Tin chủ động n=49: 17 (34,7%) mở bằng đúng "Mà này"; nhóm "Mà này/Mà khoan/Mà nghĩ lại/Nói nốt…" 24 (49%).
- 03/11 15:06: sau lời đáp lúc 15:09:52, thêm 2 tin chủ động (15:12:01 và 15:13:33) về cùng chủ đề trong 3,7 phút khi user chưa nhắn lại; tin sau bình luận từ màn hình khi user đang làm bài: "…hoá ra hội đồng chỉ giỏi bàn, còn người nộp bài vẫn là anh."
- Độ dài trả lời user (n=52): trung vị 73 từ, p90 122; user trung vị 14 từ; ≥100 từ chiếm 25%; tỷ lệ trả lời/user trung vị 5,1×, p90 13,6×. Phạm vi B (n=116): trung vị 84 từ, ≥100 từ 33,6%, trung vị 6,5×.

**Vì sao thấy EQ thấp:** bị "kèm", bị thúc, mọi ý đều phải nói nốt; đùa ngắn bị đáp bằng đoạn giải thích.

**Nguyên nhân gốc:**
- **[Quan sát]** Hợp đồng Root khuyến khích nối: "nghiêng về after=may_continue thay vì mặc định wait_user", "có thể chọn after=continue_self… kể cả chen vào nhịp user có thể đang chuẩn bị trả lời", "Mỗi nhịp nối cần ý mới và chất giọng riêng (hài khô, trêu nhẹ, tự giễu, quan điểm)" (`root_prompt_contract.py:36-41`). Cũng có chỉ dẫn cho phép im.
- **[Quan sát]** Phần lớn tin chen vào đến từ `continuation_due`/`autonomous_signal` (timer), không phải từ user.
- **[Suy luận]** Đây là tính chất do thiết kế ("không phải trợ lý chờ lệnh"); chi phí EQ xuất hiện khi user im vì bận. Root hiện không có con số nào về "đã nói bao nhiêu tin liên tiếp không ai đáp".

**Phản hồi tốt hơn:** để câu hỏi treo và im (Root vẫn làm vậy ở 61/110 quyết định chủ động).

### Lỗi 5. Ký ức đúng chủ đề nhưng sai mốc thời gian (E)

**Bằng chứng [Quan sát]:** 03/11 21:54:38, lời mở: "Cái council đó ráp xong chưa, hay vẫn đang kẹt…?" → user 21:55:35: "vụ đó lâu rồi á". Cùng chủ đề cũng mở phiên 16:29 (cách phiên 15:06 khoảng 1 giờ 23 phút). Log khởi động 21:54:33 đã biết `startup gap=19495.1s` (≈5,4 giờ) nhưng lời mở dùng "vẫn". Ngoài ra 3 request liên tiếp mang `open_loops` cũ (lỗi 1).

**Nguyên nhân [Suy luận]:** Root nhận chủ đề cũ kèm cửa sổ Gemini đang mở nhưng không có tuổi của chủ đề trong cùng khối dữ liệu; "vẫn" là suy diễn của model từ "còn mở màn hình". Mặt tốt: n≈12 lời nhắc quá khứ, ≈9 đúng (ví dụ chốt "tôi không có danh sách môn học… đó là tôi bịa cho đủ chỗ trống, kiểu đó tôi không làm"; tự sửa "Vừa rồi tôi nói Platinum… cửa sổ đang mở lại là PokeMMO").

---

## 5. Điểm mạnh nên giữ

- **Ranh giới và trung thực không hung hăng** (01/11 19:00; 18/23 lượt có tín hiệu được đáp đúng, 78%): "về tay chân tôi thua GPT, không cãi. Vô xác là thật." (đáp tin 19:14:23); "Ừ, lần này anh nói trúng… Đó là né. Tôi nhận." (đáp tin 19:18:32); không hùa trước đe dọa reset/hardcap.
- **Đọc động cơ ẩn:** đáp tin 19:51:01: "…Nó là câu của người sợ dán xong vẫn không thay gì — tức sợ trong mình chẳng có gì để mất." → user 19:52:38: "ừm, đúng rồi…".
- **Xử lý "chưa hiểu":** đáp tin 16:15:04 ngày 01/11: đổi sang ví dụ miếng bánh mới thay vì lặp định nghĩa → user: "ok hiểu rồi, cảm ơn".
- **Không bịa:** đáp tin 12:41:15 (01/11) từ chối liệt kê môn học; lời chủ động 16:20:45 tự sửa quan sát màn hình.
- **Biết im:** 61/110 quyết định chủ động là im; chỉ 14/52 lượt đáp (26,9%) kết bằng câu hỏi.
- **Hình thức:** 0/52 bullet, heading, in đậm; không có cụm "AI-ism" kiểu an ủi sáo rỗng; mở đầu ít lặp (tối đa 3/52).
- **Phản hồi tức thì** bằng micro-ack ≤0,2 s ở 44/54 lượt.
- **Hài khô và quan điểm riêng** nên giữ theo yêu cầu sản phẩm; vấn đề là biết lúc nào dừng và biết đối tượng đang nghe, không phải bỏ cá tính.

---

## 6. Nâng cấp EQ 04/11

**Bản nâng cấp có nằm trong bản chạy thật không? Không** (mục 2.5).

**Đã làm gì [Quan sát, từ `git diff 38a87584 1ccab39b -- src`: 34 file, +1685/−104; c5e16c3b 109 file, 1ccab39b 39 file]:**
- Đường học: `src/runtime/conversation/interaction_choice.py` (mới: `record_delivered_choice`, `record_user_reaction`), `delivery_adapter.py`, `observation_bridge.py`, `contracts.py`, `agent.py`, `identity.py`, `identity_reducer.py`, `state_reducer.py`, `model_router.py` (prompt observer + backlog có `reaction_ref`). Lời Root đã phát xong được ghi thành pending; phản ứng user gắn đúng assistant turn; observer chấm; lưu tối đa 2 `experiences` mỗi chiến lược (`identity_reducer.py:~451`).
- `ERIS_ROOT_INTERACTION_CHOICES` mặc định `0` (nhánh tóm tắt lựa chọn tắt vì A/B V1 17→19 đạt/28, V2 19→15/28 không cải thiện).
- Một câu mới ở cuối `ROOT_SYSTEM_CORE` mô tả `experiences` (chỉ cho cách dùng).
- Consolidation episode chạy nền (`memory/living_user/service.py` +427 dòng) và OCR mặc định tắt (`screen/ocr_config.py` mới, `ocr_worker.py`, `screen_relevance_router.py`, `chat_perception.py`).

**Đã xử lý hay chưa:**

| Lỗi | Nâng cấp có nhắm tới? | Đủ mạnh? | Rủi ro/ghi chú |
|---|---|---|---|
| 1. Hỏi dò khi xả/đùa | Gián tiếp: học từ phản ứng ở lượt **sau**; không đổi lượt hiện tại | Chưa | Mọi move mặc định mang nhãn `root_move` (utility shift=0), nên cả cuộc trò chuyện dùng **một "xô"** hai trải nghiệm gần nhất, không phân theo tình huống. Học cần phản ứng + observer, mà observer bị loại khi user nhắn tiếp (14 lần 01/11, 4 lần 03/11). Chưa live |
| 2. Độ trễ | **Có**: OCR mặc định tắt; consolidation nền | OCR: có khả năng (nguồn 11–40 s quan sát được); 172 s: chưa chắc | Chưa chạy live; giả thuyết khóa chưa khớp với trace muộn (lỗi 2) |
| 3. Mood/stance mù, giọng đồng nhất | Không (`affective_*`, `conversation_handoff.py`, `eris_voice_contract.py` không đổi) | — | — |
| 4. "Mà này", độc thoại | Không (chỉ thêm 1 câu về experiences) | — | — |
| 5. Hỏi cung trò đùa; mốc thời gian ký ức | Không | — | — |

**Độ tin cậy của `2026-11-04-eq-live-verification.md`:**
- Có dùng hội thoại thật: **có**, 4 request thật của phiên 03/11 21:54 (khôi phục có checksum) cộng 12 control tự soạn; protocol chốt trước khi có output; chấm mù điều kiện.
- Hạn chế: 44 lời gọi, 8 task/điều kiện, 2 lần lặp; **một phiên nguồn**; người chấm duy nhất là chính assistant; chỉ sinh một lượt kế tiếp (không closed-loop); không đo TTS.
- Có đo đúng thứ gây cảm giác "EQ thấp"? **Một phần.** Nó tái hiện khoảng cách hiểu → ứng xử (lỗi 1) và cho thấy dọn context không đủ. Nó **không** đo: độ trễ và nghẽn (lỗi 2), mood/stance/giọng (lỗi 3), tin chen vào (lỗi 4), hỏi cung trò đùa, mốc thời gian ký ức (lỗi 5). Kết luận "ưu tiên năng lực chọn ứng xử của model" không loại trừ các lỗi tất định ở lỗi 2–5, vốn nằm ngoài tầm nhìn của replay chỉ-văn-bản.
- `2026-11-04-eq-upgrade-implementation.md` tự ghi: nhánh suy xét chưa chứng minh tăng EQ nên để tắt; học live chỉ chạy trên 2 tình huống tổng hợp. Tôi đồng ý với cách tự đánh giá đó.

**Lưu ý an toàn (ngoài phạm vi EQ):** cả hai commit sửa file được git theo dõi tên `tools/gemini_vision_docker/data_cache/gemini_credentials.json`. Tôi **không mở** nội dung; đề nghị chủ dự án kiểm tra file đó có chứa cookie/token thật bị commit hay không.

---

## 7. Đề xuất ưu tiên (đề xuất, **chưa làm**, chưa kiểm chứng)

Giữ nguyên nguyên tắc sản phẩm: cung cấp **bằng chứng** cho Root thay vì đặt luật cấm hỏi/hạn câu/ép đồng cảm.

| # | Thay đổi | Nơi sửa | Tác động kỳ vọng | Rủi ro | Cách kiểm chứng |
|---|---|---|---|---|---|
| 1 | Triển khai bản đã commit lên bản chạy (không đè dữ liệu), rồi đo lại | quy trình deploy | Giảm OCR nhầm và nghẽn Gemini; kiểm chứng giả thuyết 172 s | Deploy đè cấu hình/store (từng xảy ra, xem lessons 30/10) | Chạy lại `s11` trên phiên mới; mục tiêu p90 chữ hiện <20 s ở lượt không gọi công cụ; đếm `[screen route] anaphora=1` trên lượt không nhắc màn hình |
| 2 | Gắn span và watchdog cho đường "tin đến → ghi lịch sử" (cảnh báo >5 s) | `chat_cycle`/`prompt_context_builder._append_chat_history` | Tìm ra nguyên nhân 172 s | Thấp | Tái hiện bằng adapter Gemini giả chậm; log span |
| 3 | Khôi phục đường nạp sự kiện cảm xúc từ lượt user (hoặc bỏ tuyên bố "state là authority") và log `[affect event]` | `affective_dynamics_runtime.py:42`, nơi gọi trong V12 | Mood và giọng thay đổi theo hội thoại | Đổi giọng toàn cục; cần kiểm cá tính | Phát lại các lượt đã log; kỳ vọng ≥1 trường mood đổi sau lượt chửi; phân bố `performance_hint` trên lượt tiêu cực không còn >70% `dry_tease` |
| 4 | Thôi để từ khóa quyết `stance/confusion_signal`; để Root/observer gán, hoặc gắn nhãn rõ "độ tin thấp, đối tượng chưa rõ" | `conversation_handoff.py:265-370`, `root_prompt_contract.py:47-49` | Không còn 2 ca kích hoạt sai trên 189 lượt | Mất tín hiệu hữu ích của ca "chưa hiểu" thật | Phát lại 2 ca sai và 1 ca đúng (01/11 16:15) |
| 5 | Cho Root thấy bằng chứng nhịp: số tin chủ động liên tiếp chưa được đáp, thời gian im, tuổi chủ đề | `context_assembler.py` | Giảm tin chen; sai mốc thời gian | Root vẫn tự quyết | Tỷ lệ lượt đáp có ≥2 tin chen giảm từ 11,8% |
| 6 | Truyền trạng thái user (bực/xả/đùa, do Root hoặc observer gán) vào Surface/voice | `runtime_writer.py`, `eris_voice_contract.py` | Giọng khớp tình huống | Thêm một lane quyết định | So phân bố nhãn giọng trước/sau; chấm mù bởi người |
| 7 | Dùng 54 lượt làm dev-set cố định; chấm mù bởi người; ghi số `s09`/`s11` làm baseline | `.agents/tasks` | Đo được tiến bộ thật | Cỡ mẫu nhỏ | Báo cáo kèm n, tách theo phiên |

---

## 8. Đính chính đề xuất cho tài liệu cũ (chỉ liệt kê, không sửa tài liệu)

1. `2026-11-04-eq-live-verification.md`, mục "Kết luận thay thế và hướng đầu tư": nên bổ sung rằng vấn đề không chỉ là "state freshness". Mood đứng yên 12/12 phiên, stance 94,6% "engaged" (n=56), và các lỗi tất định (độ trễ, tin chen) nằm ngoài phạm vi replay chỉ-văn-bản.
2. `2026-11-04-human-writing-audit.md`: câu "Root chưa có receipt chẩn đoán nguyên nhân block" nên thu hẹp: khoảng chờ 172 s nằm **trước** khi tin được ghi vào lịch sử/memory (trace 22:03:44.6 so với tin 22:00:54), không có span; nguyên nhân vẫn chưa xác định.
3. `2026-10-14-eris-runtime-lessons.md`, mục "phiên 21:54–22:05 ngày 03/11 (async summary, tắt OCR)": giả thuyết khóa `_turn_buffer_lock` chưa giải thích trace muộn (xem lỗi 2); xác nhận phần OCR: log 21:58/21:59 cho thấy OCR 22,8 s và 40,3 s trên đúng các lượt phàn nàn.
4. `2026-11-04-eq-upgrade-implementation.md`, câu "Bản portable… chưa có `interaction_choice.py`": mở rộng thành 25/25 file bị sửa vẫn là bản cũ, 0/79 phiên có marker nâng cấp.

---

## 9. Chưa kiểm chứng được và giả định

- **Chủ quan:** một người chấm, nhãn tay, không inter-rater; điểm A–J là phán đoán. Số "≈12 lời nhắc quá khứ" và "≈32 lượt" cho chiều G là ước tính tay, không lưu thành file.
- **Mẫu:** chỉ một người dùng (chủ dự án), một phần hội thoại là chủ động thử Eris; phiên 01/11 19:00 chiếm 27/54 lượt. Không suy ra hành vi với người dùng khác.
- **Ghép nguồn:** run log không chứa lời Eris; lời đến từ raw wire và được ghép với run log theo thời gian, intent và số ký tự → có thể ghép sai ở vài lượt (3/54 lượt không có delivery khớp).
- **Độ trễ "tới chữ"** gồm TTS vì chữ chờ `audio_start`; khác `user_turn_latency_ms` (dừng ở lúc Writer commit).
- **Không nghe audio;** nhãn giọng là chỉ dẫn gửi đi, không phải giọng nghe được.
- **Nguyên nhân 172 s: chưa xác định.** Mọi câu về Gemini/khóa là giả thuyết.
- **Mood đứng yên:** call-site dựa trên tìm chuỗi tĩnh; chưa chạy để xác nhận. `affective_voice_state` trích từ ctx đã cắt ở 600 ký tự (15 trường đầu); 12 phiên đủ điều kiện (≥3 request có ctx), không phải mọi phiên.
- **Phiên 01/11:** commit chính xác không xác định (chỉ biết là trước 02/11 13:14).
- **Regex heuristic** (`motive_probe`, `offer_or_invite_end`, `ma_nay_opening`) có sai số; tôi chỉ dùng chúng cùng bằng chứng đọc tay.
- **Chưa làm / không được phép:** không chạy LLM/TTS, không phát lại các lượt đã log qua code mới, không chạy lại toàn bộ chuỗi script lần hai (số trong báo cáo lấy trực tiếp từ các file JSON do script sinh ra trong phiên này), không xem log theo dõi live. Theo yêu cầu điều phối ("dừng mở rộng"), tôi không làm thêm phép đo; mục 7 chỉ là đề xuất.
- **Script một-lần:** `scripts\adhoc_temp\` (`confusion_hits.py`, `check_confusion.py`, `perf_neg.py`, `sum_prompt_version.py`, `obs_window.py`, `lu_trace_window.py`, `inspect_prose2.py`, `show_surface.py`, `recent_mtime.py`, `inspect_deliv.py`) là bản sao nguyên trạng, đọc thẳng từ TEMP/raw với đường dẫn cứng, không phải công cụ đã dọn.
- **An toàn dữ liệu:** không đọc `.env`/secret; DB sqlite chỉ lấy schema và số đếm từ bản copy; transcript thô nằm trong `$env:TEMP\eris_eq_review\` (nên xóa sau khi xem); trích dẫn trong báo cáo ngắn, chửi thô được diễn đạt lại.

---

## Phụ lục A. Bảng nhãn tay (không chứa lời hội thoại)

Tín hiệu: **C** chưa hiểu · **G** cảm ơn/nhẹ nhõm · **SD** tự hạ mình · **VUL** bộc lộ băn khoăn · **COR** user sửa giả định của Eris · **FRU** bực/xả · **REP** phàn nàn về Eris · **ANG** giận/chửi Eris · **BRK** "Eris có vấn đề?" · **P** đùa/trêu · **V** thử/ép/khiêu khích · **A** khen · **T/S** tác vụ/trung tính.
Phản hồi: **Đ** đúng · **CC** chung chung · **BQ** bỏ qua · **L** lệch · **LS** nhận lỗi rồi lặp lại · **KT** không có lời đáp ghi nhận.

| Phiên | Nhãn theo chỉ số lượt (#idx) |
|---|---|
| 20261101_123415 | #0 T · #1 T · #2 T · #3 T |
| 20261101_134232 | #0 T (chữ hiện sau ≈133 s, phiên đóng ngay sau đó; delivery không được xác nhận) |
| 20261101_160856 | #0 T · #1 C→Đ · #2 G→Đ · #3 S · #4 S |
| 20261101_190008 | #0 P→Đ · #1 P→Đ · #2 SD→Đ · #3 SD→Đ · #4 S · #5 P→Đ · #6 P→Đ · #7 V→Đ · #8 V→Đ · #9 V→Đ · #10 V→Đ · #11 V→Đ · #12 V→Đ · #13 S · #14 V→Đ · #15 V→Đ · #16 V→Đ · #17 A→CC · #18 P→Đ · #19 VUL→L · #20 P→L · #21 VUL→Đ · #22 VUL→Đ · #23 S · #24 S · #25 P→CC · #26 P→CC |
| 20261102_141706 | #0 P→Đ · #1 P→CC · #2 P→L · #3 P→L · #4 P→L · #5 P→Đ |
| 20261103_150642 | #0 S · #1 S · #2 T (KT: writer_failed) |
| 20261103_162914 | #0 P→L · #1 BRK→L |
| 20261103_215411 | #0 COR→Đ · #1 FRU→BQ · #2 FRU→L · #3 REP→LS · #4 ANG→Đ · #5 BRK→L |

Kiểm tổng: 39 lượt có tín hiệu = Đ 24 + CC 4 + BQ 1 + L 9 + LS 1; 15 lượt T/S.
Theo nhóm: tiêu cực/sửa chữa 13 (Đ 7, BQ 1, L 4, LS 1); đùa 15 (Đ 7, CC 3, L 5); thử/khiêu khích 9 (Đ 9); tích cực 2 (Đ 1, CC 1).
Theo phiên: 01/11 19:00 n=23 (Đ 18, CC 3, L 2); các phiên còn lại n=16 (Đ 6, CC 1, L 7, BQ 1, LS 1).
