# ERIS: CHỮ TRÊN SLIDE (bản "láo": chữ ít, đấm mạnh, kỹ thuật có chân đế)

> Mỗi slide một câu đấm chữ to. Bốn slide kỹ thuật (5, 5B, 6, 7) có thêm sơ đồ
> và khối 『BẰNG CHỨNG』 chữ nhỏ.
> Lời nói: `SCRIPT-THUYET-TRINH.md` · Luồng chi tiết + nguồn code: `LUONG-CHAY-ERIS.md`
> · Ảnh mẫu slide 5: `slide-05-luong-8-tram.svg`
>
> Quy ước: 【TITLE】 chữ to nhất · ‹sub› dòng phụ nhỏ · ⟦…⟧ tiêu chí điểm slide gánh

═══════════════════════════════════════════

## SLIDE 1 · MỞ MÀN   ⟦Trình bày 5 · Sáng tạo 20⟧
MÀN HÌNH:
  【ERIS】
  ‹Gia sư AI đồng hành›
  *(nền: Live2D Eris full màn, chữ đặt góc)*

Hiệu ứng: để Eris nói một câu bằng giọng TTS. Slide gần như không chữ.

═══════════════════════════════════════════

## SLIDE 2 · ĐẶT LUẬT CHƠI  ⚡   ⟦Giải quyết vấn đề 20 · Sáng tạo 20⟧
MÀN HÌNH:
  【Thứ bạn làm hôm nay,
   ngày mai là rác.】
  ‹Trong cuộc đua công nghệ, giá trị không nằm ở dùng công nghệ nào,
   mà ở dám làm gì với nó.›

═══════════════════════════════════════════

## SLIDE 3 · ĐỊNH VỊ   ⟦Giải quyết vấn đề 20 · Sáng tạo 20⟧
MÀN HÌNH:
  【Không giao bài. Đồng hành.】
     AI GIAO BÀI              │  ERIS
     Bạn hỏi → nó đáp         │  Nó hỏi lại: bạn vướng ở đâu?
     Đưa lời giải             │  Gợi ý vừa đủ để bạn tự làm
     Bạn thôi hỏi → nó dừng   │  Giữ nhịp, nhắc ôn đúng lúc

═══════════════════════════════════════════

## SLIDE 4 · TRIẾT LÝ  ⚡⚡ slide lõi   ⟦Sáng tạo 20 · Công nghệ mới 8⟧
MÀN HÌNH:
  【Chúng tôi không xây một câu trả lời.
   Chúng tôi xây một CÁCH NGHĨ.】
     01  Quyền lực phải bị chia nhỏ
     02  Trung thực là luật hệ thống, không phải lời dặn
     03  Chia sự chú ý theo vai trò, không theo model
     04  Tự chủ phải có phanh
     05  Mở rộng bằng cắm vào, không viết lại

Ghi chú (không in): mỗi niềm tin có một slide chứng minh.
01 → slide 5 · 04 → slide 5B · 03 → slide 6 · 02 và 05 → slide 7.

═══════════════════════════════════════════

## SLIDE 5 · LUỒNG 8 TRẠM  ⚡⚡ xương sống kỹ thuật   ⟦Khả thi 20 · Công nghệ mới 8⟧ · Triết lý 01
MÀN HÌNH:
  【Mỗi câu Eris nói đi qua 8 trạm. Và chỉ có một cửa ra.】
  ‹Root quyết ý · Writer viết lời · chỉ một cửa được phát tiếng · biên nhận quay về Root›

  Sơ đồ chữ U (hàng trên trái → phải, hàng dưới phải → trái).
  Mỗi ô: tên trạm · 3 dòng ngắn · chip lane.

  ① NGÕ VÀO     Chat hoặc giọng nói / "ừ, à" lúc Eris nói → giữ audio / câu mới → ngắt lời
                [không gọi LLM]
  ② KERNEL      generation + 1 ngay lập tức / mọi thứ của lượt cũ hết hiệu lực / hủy nói tiếp · cấp run_id
                [không gọi LLM]
  ③ NGỮ CẢNH    danh tính · quan hệ · cảm xúc / trí nhớ · bằng chứng / chỉ chiếu dữ liệu, không quyết
                [không gọi LLM]
  ④ ROOT        vòng nhiều bước, mỗi bước 1 việc / nhớ lại · gọi gia sư · nghĩ thêm / chốt ý định, không viết câu
                [làn bắt buộc · nghĩ sâu]
  ⑤ WRITER      viết ý của Root thành lời / chữ tiếng Việt + giọng tiếng Nhật / guard: grounding · ngôn ngữ
                [làn bắt buộc · không nghĩ]
  ⑥ KIỂM CUỐI   còn đúng lượt này không? / user chen lời → hủy / không phát lại câu cũ
                [không gọi LLM]
  ⑦ CỬA PHÁT    TTS → audio + Live2D + phụ đề / câu "đã làm" phải có biên nhận / cửa duy nhất được phát lời
                [một cửa duy nhất] (ô tô cam)
  ⑧ BIÊN NHẬN   quay về Root ở bước/lượt sau / Tutor ghi "đã dạy" khi phát xong / observer học lại lượt vừa rồi
                [observer: làn nền]

  Mũi tên ⑧ → ②: "Root chọn nói tiếp → continuation_due quay lại Kernel"
  Hộp góc: FAIL-SOFT. Root hoặc Writer lỗi provider → câu báo cố định (chữ Việt + giọng Nhật)
  đi thẳng tới cửa phát, không qua LLM, vẫn kiểm đúng lượt.

  『BẰNG CHỨNG』 (chữ nhỏ):
   • Kernel tăng generation trước cả khi hủy bản phát cũ → callback TTS của lượt cũ tự bị loại.
   • delivery_id được cấp trước khi Writer viết; mọi trạng thái phát gắn vào nó.
   • Chỉ delivery_adapter.deliver được gọi xuống TTS cho lời nói.

═══════════════════════════════════════════

## SLIDE 5B · ROOT LOOP   ⟦Khả thi 20 · Công nghệ mới 8⟧ · Triết lý 04
MÀN HÌNH:
  【Root không trả lời. Root quyết định, từng bước một.】
  ‹Tự chủ phải có phanh›

  Sơ đồ: vòng tròn "BƯỚC k" ở giữa, bốn nan hoa:
     nhớ lại (recall_memory)
     gọi năng lực (tutor · research · work · action)
     nghĩ thêm (tối đa 2 lần, không phát lời)
     ghi chú (set_note)
  Mũi tên "kết quả + biên nhận" quay về tâm.
  Lối ra phía dưới: CHỐT move { ý định · điều cần nói · cách nói · sau đó }  hoặc  im lặng.

  Bên phải, ba icon phanh:
     ≤ 12 bước  ·  2 bước liền không tiến triển → dừng  ·  user chen lời → nhường ngay

  『BẰNG CHỨNG』:
   • ROOT_STEP_SCHEMA: mỗi bước đúng 1 hành động; max_root_steps khóa trong 2–12 (mặc định 8).
   • Trùng, rỗng, lỗi, hết hạn mức 2 bước liền → dừng sớm. Bị chen lời → NoReply(root_turn_preempted).
   • "Self" nạp một lần; các bước sau chỉ gửi phần thay đổi (root_session.py).

═══════════════════════════════════════════

## SLIDE 6 · LANE  ⚡ slide "mở mắt" IT   ⟦Khả thi 20 · Công nghệ mới 8⟧ · Triết lý 03
MÀN HÌNH:
  【Nhiều luồng nghĩ. Một giọng nói.】
  ‹Xếp làn theo vai trò, không theo tên model›

  Hai cột:
     LÀN BẮT BUỘC (xanh đặc)            │  LÀN NỀN (xám nét đứt)
     không bao giờ bị cắt khi máy bận   │  máy bận → hoãn, gộp hoặc bỏ
     Root                               │  Observer sau lượt
     Gia sư (tutor:*)                   │  Tự khởi (autonomous)
     Writer                             │  Seed · discovery · planner
     Kiểm claim                         │  Suy nghĩ nền (neuro)
     Kế hoạch năng lực cho lượt user    │  Kế hoạch năng lực nền

  Dải đáy hình phễu:
     hơn chục luồng nghĩ nền (seed · tiềm thức · nội tâm · private life)
     → chỉ được đề xuất → Root quyết → 1 cửa phát

  Hộp "BÀI HỌC THẬT":
     Bước kiểm bắt buộc từng bị xếp vào làn nền chỉ vì mang nhãn cũ.
     Máy bận → bước đó bị bỏ → Eris im lặng.
     Luật mới: vai trò được xét trước nhãn.

  Dòng nhỏ: Cùng một model: Root nghĩ sâu để quyết · Writer không nghĩ để nói nhanh
  · Localizer không nghĩ để dịch cho TTS.

  『BẰNG CHỨNG』:
   • Ba trục tách rời: vai trò (cognitive_lane) · đường truyền (backend) · tài nguyên (resource_class).
   • Chỉ làn nền được gộp và bị cắt.
   • Root và Tutor đến giờ vẫn gửi nhãn subconscious_4b, nhưng nhánh vai trò được xét trước
     nên luôn vào làn bắt buộc (model_router._run_inference).

═══════════════════════════════════════════

## SLIDE 7 · BIÊN NHẬN + GIA SƯ  ⚡⚡   ⟦Khả thi 20 · Sáng tạo 20 · Công nghệ mới 8⟧ · Triết lý 02 + 05
MÀN HÌNH:
  【Định nói ≠ đã nói ≠ đã dạy.】
  ‹Model đề xuất. Bộ máy có luật mới được chốt.›

  Vòng khép kín:
     Root → gọi Gia sư → nước dạy + biên nhận (KHÔNG kèm đáp án) → Root chốt
     → Writer → cửa phát → biên nhận: phát thành công? → Gia sư ghi "đã dạy" → về Root

  Thanh trạng thái ở đáy:
     đang chuẩn bị → vào hàng đợi → đang phát → đã phát xong
                          ↘ đã hủy (không bao giờ tự phát lại)

  Chip nhỏ: 4 khớp cắm năng lực: Đăng ký → Gọi → Biên nhận tư vấn → Xác nhận đã dạy

  『BẰNG CHỨNG』:
   • Sổ MoveOutcomeLedger: preparing / queued_for_audio / delivering / delivered / cancelled.
     Crash giữa chừng → unconfirmed_after_restart, không coi là đã phát.
   • Gia sư chỉ tiến bài khi biên nhận phát thành công (commit_delivery).
   • Câu trả lời tự do chỉ thành bằng chứng khi đủ tin cậy (≥ 0,68). Writer không cầm đáp án.
   • LearningService là cửa duy nhất ghi tiến độ học; lịch ôn SM-2 tính bằng ngày.

═══════════════════════════════════════════

## SLIDE 8 · SỐNG   ⟦Tác động 20 · Trình bày 5⟧
MÀN HÌNH:
  【Cảm giác đang học cùng một người.】
     😵 "Sao dừng ở i=5?"      → "Tự đếm từ i=3 xem."          (gợi ý, không giải hộ)
     🎮 "Chán, chơi game đi"   → "3 phút, rồi làm thêm 1 câu nhé?" (đàm phán)
     😎 "Xong rồi, giỏi chưa?" → "Giải thích ngắn tôi nghe?"   (đòi bằng chứng)

═══════════════════════════════════════════

## SLIDE 9 · GIAO ĐIỂM  ⚡⚡ slide thị trường   ⟦Tác động 20 · Sáng tạo 20⟧
MÀN HÌNH:
  【Giao điểm không ai đứng.】
  Hai vòng tròn giao nhau:
     COMPANION AI           TUTOR AI
     quay lại mỗi ngày      dạy có cấu trúc
     ✗ không dạy được       ✗ ít ai muốn mở lại
              ⬇ phần giao ⬇
             【ERIS】

═══════════════════════════════════════════

## SLIDE 10 · BỘ BA  ⚡   ⟦Tác động 20 · Sáng tạo 20⟧
MÀN HÌNH:
  【Đối thủ chọn một. Chúng tôi làm cả ba.】
     ❤️ NHÂN VẬT         người ta muốn quay lại
     🧠 LEARNING KERNEL  học thật, tiến bộ thật
     ⚙️ KIẾN TRÚC        lớn mãi không vỡ
  ‹Các nhóm khác auto làm một con AI đóng. Chúng tôi tự xây từ đầu.›

═══════════════════════════════════════════

## SLIDE 11 · LỘ TRÌNH   ⟦Tác động 20⟧
MÀN HÌNH:
  【Cắm thêm. Không viết lại.】
  Chuỗi mũi tên: Nhiều môn → Vision chấm ảnh → Nhắc nhiều ngày → Dự đoán điểm yếu
  ‹Cá nhân → Lớp học → Giáo viên → Edtech. Không có trần.›

═══════════════════════════════════════════

## SLIDE 12 · CHỐT  ⚡⚡⚡   ⟦Chốt toàn bài · Sáng tạo 20⟧
MÀN HÌNH:
  【Eris không phải điểm đến.
   Eris là CON ĐƯỜNG.】
  ‹Họ xây một câu trả lời. Chúng tôi xây một cách nghĩ.›

═══════════════════════════════════════════
PHỤ LỤC (chỉ lật khi phản biện)
═══════════════════════════════════════════

A0  Sơ đồ chi tiết một lượt (mã mermaid cuối `LUONG-CHAY-ERIS.md`). Dùng khi bị hỏi "chi tiết hơn đi".

A1  【Eris từng IM LẶNG. Chúng tôi biết vì sao.】
    ‹Bước kiểm bắt buộc trước khi phát từng bị xếp vào làn nền vì nhãn cũ subconscious_4b.
     Máy bận → bị bỏ → Writer nhận UNKNOWN → im lặng. Luật mới: vai trò xét trước nhãn.
     Root và Tutor vẫn mang nhãn đó nhưng luôn vào làn bắt buộc.›

A2  【User chen lời → cả lượt cũ hết hiệu lực.】
    ‹generation tăng trước cả bước hủy; callback TTS cũ bị loại chỉ bằng so sánh một con số.›

A3  【Model lỗi, Eris không im.】
    ‹Câu báo cố định VI + JA đi thẳng tới cửa phát, không qua Root/Writer/localizer, vẫn kiểm đúng lượt.›

A4  【Model bịa cũng không ghi được vào hồ sơ học.】
    ‹LLM đề xuất; kernel deterministic chốt. Ngưỡng tin cậy 0,68. Writer không cầm đáp án.›

A5  【5 rào cản kỹ thuật.】
    ‹Chia quyền quyết / diễn đạt / phát / ghi nhớ · chống bịa bằng biên nhận · preemption bằng
     generation · learning kernel tách khỏi model · fail-soft không qua LLM.›

═══════════════════════════════════════════
BẢN ĐỒ PHỦ ĐIỂM
═══════════════════════════════════════════
| Tiêu chí (100đ)      | Slide gánh                   | Tình trạng |
|----------------------|------------------------------|------------|
| Sáng tạo 20          | 1, 2, 3, 4, 7, 9, 10, 12     | dày |
| Khả thi 20           | 5, 5B, 6, 7 + phụ lục A0–A5  | rất dày |
| Tác động 20          | 8, 9, 10, 11                 | đủ |
| Giải quyết vấn đề 20 | 2, 3                         | mỏng, đừng cắt cả hai |
| Công nghệ mới 8      | 4, 5, 5B, 6, 7               | rất dày |
| Trình bày 5          | 1 (demo giọng) + script      | đủ |
| Layout 7             | bạn tự dựng                  | — |

CẮT GỌT KHI THIẾU GIỜ:
- KHÔNG cắt slide 5 (luồng 8 trạm) và hộp "bài học thật" ở slide 6. Đây là xương sống Khả thi.
- Cắt được theo thứ tự: (1) slide 8 còn một câu · (2) gộp 5B vào 5 bằng một câu về phanh ·
  (3) gộp 11 vào 12.
- "Giải quyết vấn đề 20đ" chỉ dựa vào slide 2 + 3. Rút chữ được, không bỏ hẳn slide nào.
- Không đụng ba đỉnh: slide 4, 9, 12.

═══════════════════════════════════════════
MẸO DỰNG SLIDE
═══════════════════════════════════════════
- Slide 5: mở `slide-05-luong-8-tram.svg`. Canva: Tải lên → kéo vào trang. PowerPoint:
  Insert → Pictures, chuột phải → Convert to Shape để sửa từng ô.
- Ba màu chip dùng nhất quán trên mọi slide kỹ thuật: xanh đặc = làn bắt buộc ·
  xám nhạt = không gọi LLM · xám nét đứt = làn nền · cam = cửa phát.
- Khối 『BẰNG CHỨNG』 đặt góc dưới, chữ nhỏ cỡ 1/3 tiêu đề, hoặc cho hiện dần khi nói tới.
- Slide đấm (⚡): một câu cực to giữa màn, ‹sub› nhỏ. Không nhồi đoạn văn, văn để miệng nói.
- Đầu tư nhất: slide 4, 5, 9, 12.
