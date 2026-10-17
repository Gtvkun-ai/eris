# ERIS — BỘ SLIDE HOÀN CHỈNH (bản trình bày thống nhất)

> Cấu trúc: CẢM XÚC → VẤN ĐỀ → TRIẾT LÝ → KỸ THUẬT → THỊ TRƯỜNG → TẦM NHÌN →
> PHỤ LỤC. Giám khảo nhớ cảm xúc trước, phục kiến trúc sau, tin thị trường cuối.
>
> Mỗi slide: [TIÊU ĐỀ] · nội dung lên slide · (Nói miệng) · ⟦điểm phục vụ⟧
> Layout bạn tự dựng. Phần 🎤 là lời thuyết trình, không in lên slide.
>
> BÀI CHÍNH = slide 1–12 (~5 phút). PHỤ LỤC = slide A1–A5 (lật khi phản biện).

═══════════════════════════════════════════════════════════════════
PHẦN I — MỞ BẰNG CẢM XÚC (0:00–0:50)
═══════════════════════════════════════════════════════════════════

## SLIDE 1 — ERIS (mở màn + demo nhân vật)
**Nội dung:** Live2D Eris + tên + một dòng: "Gia sư AI đồng hành."
**NẾU CÓ DEMO:** cho Eris nói một câu bằng giọng TTS ấm ngay tại đây.

🎤 "Trước khi em nói gì, hãy để em ấy tự giới thiệu." *(bật demo giọng 10s)*
"Đây là Eris. Không phải một ô chat — một nhân vật. Và hôm nay em sẽ cho thấy
vì sao phía sau khuôn mặt này là một kiến trúc mà một tính năng AI không chạm tới."
⟦Trình bày 5 · Sáng tạo 20⟧

---

## SLIDE 2 — VẤN ĐỀ (cuộc đua công nghệ + câu hạ bệ)
**Tiêu đề:** Trong cuộc đua công nghệ, thứ bạn làm hôm nay — ngày mai là rác
**Nội dung (3 gạch):**
- AI mạnh lên mỗi tháng. Model nào, API nào hôm nay cũng sẽ lỗi thời.
- Vậy giá trị thật không nằm ở *công nghệ nào* — mà ở *dám làm gì với nó*.
- Phần lớn chọn con đường an toàn: ghép một con AI đóng từ đồ có sẵn.

🎤 "Trong một cuộc đua công nghệ, mọi thứ bạn làm hôm nay — dù xịn đến mấy — ngày
mai là rác. Các nhóm khác đang đua nhau ghép một con AI đóng từ đồ có sẵn. Chúng
tôi không đua công nghệ. Chúng tôi đi ra ngoài, làm thứ không ai dám làm."
⟦Giải quyết vấn đề 20 · Sáng tạo 20⟧

> 💥 CÂU HẠ BỆ (nói chậm, nhấn): "Cho dù các bạn khác làm gì, ghép gì — những
> thứ đóng, chạy theo cái có sẵn — rồi cũng chỉ là một mớ rác công nghệ. Chỉ có
> người dám đi ra ngoài, xây một thứ khác biệt, mới còn lại."

═══════════════════════════════════════════════════════════════════
PHẦN II — ĐỊNH VỊ & TRIẾT LÝ (0:50–2:00)
═══════════════════════════════════════════════════════════════════

## SLIDE 3 — ĐỊNH VỊ
**Tiêu đề:** Một người đồng hành học, không phải máy phát bài tập
| AI GIAO BÀI | ERIS ĐỒNG HÀNH |
|---|---|
| Nhận câu hỏi → đưa lời giải | Hỏi bạn đang vướng ở đâu |
| Chấm đúng/sai | Gợi ý vừa đủ để bạn tự thử |
| Xong một lượt là kết thúc | Lưu tiến độ, chọn điểm cần ôn |
| Người học quay lại từ đầu | Nhắc học đúng thời điểm |

🎤 "Khác biệt không ở số bài tập AI sinh ra — mà ở vòng quan hệ: học, phản hồi,
tự chứng minh, tiếp nối. Thước đo của chúng tôi: sau mỗi buổi, bạn tự làm được
nhiều hơn."
⟦Sáng tạo 20 · Giải quyết vấn đề 20⟧

---

## SLIDE 4 — TRIẾT LÝ XÂY DỰNG (slide linh hồn)
**Tiêu đề:** Chúng tôi không xây một câu trả lời — chúng tôi xây một cách nghĩ
**Nội dung (5 niềm tin, mỗi cái 1 dòng):**
1. **Quyền lực phải bị chia nhỏ** — quyết định / diễn đạt / phát / ghi nhớ tách rời.
2. **Trung thực là thuộc tính của hệ thống** — chống bịa bằng biên nhận, không bằng lời dặn.
3. **Phân chú ý theo vai trò** — không theo sức mạnh model.
4. **Tự chủ phải fail an toàn** — hủy/nhớ/phục hồi trước khi cho chủ động.
5. **Mở rộng bằng cắm vào** — không bằng viết lại.

🎤 "Chúng tôi không hỏi model có thông minh không. Chúng tôi hỏi model được phép
làm gì. Năm niềm tin này là linh hồn của Eris — và mọi dòng code là hệ quả của chúng."
⟦Sáng tạo 20 · Công nghệ mới 8⟧

═══════════════════════════════════════════════════════════════════
PHẦN III — KIẾN TRÚC (2:00–3:20)
═══════════════════════════════════════════════════════════════════

## SLIDE 5 — LUỒNG QUYẾT ĐỊNH
**Tiêu đề:** Một bộ não điều hành quyết định từng lượt, rồi mới nói
```
SỰ KIỆN → ROOT QUYẾT ĐỊNH → GỌI NĂNG LỰC → KẾT QUẢ (biên nhận) → WRITER → TTS
chat,     nói/im/nhớ/gọi    tutor/        về Root quyết          diễn đạt  giọng
nhắc học  (loop nhiều bước) research...    bước kế theo bằng chứng          nói
```
**Câu chốt:** Root sở hữu *ý nghĩa*; Writer chỉ *diễn đạt*; TTS chỉ *phát*.

🎤 "Mỗi sự kiện đi vào Root — bộ não điều hành. Nó chạy vòng lặp nhiều bước, mỗi
bước trả về một biên nhận để không bịa. Đây là agent loop của sản phẩm production
thật, không phải một lệnh gọi API."
⟦Khả thi 20 · Công nghệ mới 8⟧

---

## SLIDE 6 — CHỐNG BỊA CẤP HỆ THỐNG
**Tiêu đề:** 'Định nói' ≠ 'đã nói' ≠ 'đã dạy'
```
preparing → queued_for_audio → delivering → delivered
(định nói)   (vào hàng đợi)     (đang phát)   (đã phát xong)
                    ↓ user chen vào
                 cancelled (KHÔNG tự phát lại)
```
**Nội dung:** Root chỉ được nói "đã dạy" khi có biên nhận phát thành công. Biên
nhận gắn mã sự kiện/lượt, không ghi đè. Crash → ghi UNKNOWN, không giả vờ đã phát.

🎤 "Dặn model đừng bịa là vô dụng. Trung thực phải là sự kiện vật lý có biên nhận.
Eris không được nói 'em đã làm bài' chỉ vì bạn nhắn thế — phải có bằng chứng."
⟦Khả thi 20 · Công nghệ mới 8⟧

---

## SLIDE 7 — TUTOR CẮM VÀO KIẾN TRÚC
**Tiêu đề:** Tutor là một năng lực cắm vào bốn khớp nối có sẵn
```
   UI/VOICE → KERNEL → ROOT AGENT
                           │
   WRITER→TTS ←──          ▼
                     ┌──────────────────┐
   LEARNING STORE ──→│ TUTOR CORE        │
   mastery, bằng     │ LessonSession     │
   chứng, lịch ôn    │ LearnerModel      │
                     │ EvidenceEvaluator │
                     │ TeachingStrategy  │
                     │ ReviewPlanner     │
                     └──────────────────┘
```
**4 khớp:** Đăng ký → Gọi → Biên nhận tư vấn → Xác nhận đã dạy.
**Nguyên lý:** LLM đề xuất — kernel deterministic chốt.

🎤 "Phần gia sư không phải một prompt 'hãy làm gia sư tốt'. Nó là một năng lực
cắm vào bốn khớp nối. Model gợi ý cách dạy; nhưng ghi tiến độ là kernel có luật —
nên một câu bịa không bao giờ nhiễm độc hồ sơ học của bạn."
⟦Khả thi 20 · Sáng tạo 20⟧

═══════════════════════════════════════════════════════════════════
PHẦN IV — SẢN PHẨM SỐNG & THỊ TRƯỜNG (3:20–4:20)
═══════════════════════════════════════════════════════════════════

## SLIDE 8 — BA KỊCH BẢN SỐNG
**Tiêu đề:** Cảm giác đang học cùng một người thật
- **Bí:** "Sao vòng lặp dừng ở i=5?" → "Tự đếm từ i=3 xem điều kiện đổi thế nào." *(gợi ý, không giải hộ)*
- **Trốn học:** "Nói chuyện game đi." → "Game 3 phút, rồi chọn làm thêm 1 câu hay nghỉ." *(đàm phán nhịp)*
- **Khoe xong:** "Xong rồi, giỏi chưa?" → "Giải thích ngắn cho tôi để biết có nên tăng độ khó." *(đòi bằng chứng)*

🎤 "Nó không giải hộ, không ép, không tin suông. Cảm giác là đang học cùng một
người — không phải một cái máy."
⟦Tác động 20 · Trình bày 5⟧

---

## SLIDE 9 — GIAO ĐIỂM KHÔNG AI ĐỨNG
**Tiêu đề:** Companion giữ chân nhưng không dạy — Tutor dạy nhưng không ai mở lên
```
COMPANION AI                    TUTOR AI / EDTECH
(Character.AI, Replika)         (Khanmigo, ChatGPT học)
✓ quay lại mỗi ngày             ✓ dạy có cấu trúc
✓ gắn bó cảm xúc                ✓ theo dõi tiến độ
✗ không dạy được gì             ✗ khô khan, không ai muốn mở

        ERIS = nhân vật người ta muốn quay lại
             × tutor có learning kernel thật
```

🎤 "Companion AI giữ chân nhưng không dạy. Tutor AI dạy nhưng không ai muốn mở
lên. Eris là cái duy nhất làm cả hai — nên người học *tự nguyện* quay lại, không
phải vì bị ép."
⟦Tác động 20 · Sáng tạo 20⟧

---

## SLIDE 10 — BỘ BA KHÁC BIỆT
**Tiêu đề:** Ba thứ không ai gộp được cùng lúc
| | Eris | Character.AI | Khanmigo | Nhóm hackathon khác |
|---|---|---|---|---|
| **Nhân vật** (Live2D, giọng ấm, INFJ) | ✓ | ✓ | ✗ | demo được 1 |
| **Learning kernel** (bằng chứng, chống bịa) | ✓ | ✗ | một phần | trong 2 |
| **Kiến trúc agent** (mở rộng vô hạn) | ✓ | ✗ | ✗ | thứ |

🎤 "Nhân vật giữ người ở lại. Learning kernel khiến họ tiến bộ thật. Kiến trúc
khiến nó lớn mãi không vỡ. Các nhóm khác auto làm một con AI đóng — ghép đồ có
sẵn, được một thứ. Chúng tôi làm cả ba, và tự xây từ đầu. Đó không phải may mắn,
đó là dám đi ra ngoài."
⟦Tác động 20 · Sáng tạo 20⟧

═══════════════════════════════════════════════════════════════════
PHẦN V — TẦM NHÌN & CHỐT (4:20–5:00)
═══════════════════════════════════════════════════════════════════

## SLIDE 11 — LỘ TRÌNH: TIỀM NĂNG VÔ HẠN
**Tiêu đề:** Mỗi nâng cấp cắm vào khớp nối có sẵn — không viết lại lõi
| Mở rộng | Cắm vào |
|---|---|
| Nhiều môn song song | Capability Registry + lane tutor:* |
| Vision chấm ảnh bài làm | resource_class vision + evidence contract |
| Nhắc học nhiều ngày | ReviewScheduler SM-2 + event nền riêng |
| Dự đoán điểm yếu | MasteryRecord + forgetting curve |
| Mở rộng thị trường | Cá nhân → lớp → giáo viên → B2B edtech |

🎤 "Thêm môn, thêm vision, thêm nhắc nhiều ngày, thêm thị trường — tất cả cắm vào
cùng bốn khớp nối, giữ nguyên các bất biến. Eris là đồ án mở không có trần."
⟦Tác động 20⟧

---

## SLIDE 12 — CHỐT (linh hồn)
**Tiêu đề:** Eris không phải điểm đến. Eris là con đường.
**Nội dung:** Một nhân vật người ta yêu · Một bộ não dạy học không biết nói dối ·
Một kiến trúc lớn được mãi.

🎤 "Chúng tôi không hỏi 'AI này trả lời giỏi không'. Chúng tôi hỏi 'làm sao để
một tác nhân tự chủ hành động mà vẫn trung thực, vẫn nhường người dùng, vẫn lớn
lên mà không vỡ'. Các bạn khác xây một câu trả lời. Chúng tôi xây một cách nghĩ.
Cảm ơn ban giám khảo."
⟦Chốt toàn bài⟧

═══════════════════════════════════════════════════════════════════
PHỤ LỤC — LẬT RA KHI GIÁM KHẢO ĐÀO SÂU (2 phút phản biện)
═══════════════════════════════════════════════════════════════════

## SLIDE A1 — LANE ROUTING: HỆ THẦN KINH NHẬN THỨC
Ba trục trực giao: vai trò nhận thức / đường truyền / VRAM. Lane foreground
**không bao giờ** bị cắt.
🎤 Câu chuyện HOTFIX: "Eris từng im lặng vì một nhãn tài nguyên cũ kéo bước điều
hành bắt buộc xuống nhóm có thể cắt. Chúng tôi đóng băng thành bất biến — bài học
chỉ có khi vận hành thật."

## SLIDE A2 — CONCURRENCY BẰNG GENERATION
User chen lời → một con số tăng → cả thế hệ cũ chết tức thì. Không race, không
hủy từng cái. Restart ghi UNKNOWN.
🎤 "Đây là tư duy hệ phân tán, không phải tư duy chatbot."

## SLIDE A3 — FAIL-SOFT
Một đường phát không qua LLM: khi model chết, Eris vẫn lên tiếng báo trục trặc
bằng câu cố định (display VI + speech JA).
🎤 "Một AI chủ động mà không biết dừng là một AI nguy hiểm. Chúng tôi đặt cơ chế
hủy và phục hồi trước khi cho nó chủ động."

## SLIDE A4 — LEARNING KERNEL
LLM đề xuất; kernel commit. Qua ngưỡng tin cậy mới ghi. Writer không bao giờ thấy
đáp án. Chạy cả khi không có model reasoner.

## SLIDE A5 — VÌ SAO KHÓ BẮT CHƯỚC (5 rào cản)
1. Tách 8 trục (4 quyền × 4 routing). 2. Chống bịa cấp hệ thống. 3. Concurrency
bằng generation. 4. Learning kernel tách khỏi model. 5. Fail-soft có thật.
🎤 "Mỗi rào cản không phải một tính năng — nó là một quyết định kiến trúc sinh ra
từ việc chạy thật. Mỗi bất biến là một vết sẹo của vận hành thật."

═══════════════════════════════════════════════════════════════════
CHECKLIST TRÌNH BÀY
═══════════════════════════════════════════════════════════════════
- [ ] Slide 1: nếu có demo giọng/Live2D → CHẠY NGAY, trước mọi thứ.
- [ ] Thuộc câu hook (S2) và câu chốt (S12) — không đọc slide.
- [ ] Slide 4 (triết lý) và 9 (giao điểm) dừng lâu nhất.
- [ ] Mỗi lần gáy kèm một danh từ kỹ thuật thật (biên nhận, lane, learning kernel).
- [ ] Bấm giờ: bài chính 5 phút, chừa 2 phút phản biện. Phụ lục chỉ lật khi bị hỏi.
- [ ] Câu bẫy "điểm yếu lớn nhất?" → trả thật: nối learning path từ hội thoại +
      voice end-to-end dưới tải. "Đã khoanh vùng, không phải ẩn số."
- [ ] KHÔNG nói "đã xong 100%". Nói "kiến trúc sẵn sàng, đây là con đường thực thi".

Nguồn chi tiết: triet-ly-xay-dung.md · deep-architecture.md ·
tac-dong-thi-truong.md · slide-phu-luc-ky-thuat.md
