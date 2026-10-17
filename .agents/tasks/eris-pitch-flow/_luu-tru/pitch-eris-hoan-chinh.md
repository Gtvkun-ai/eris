# BỘ PITCH ERIS — HACKATHON SGU 2026-2027

> Nguyên tắc vàng: **gáy to, nhưng mỗi câu gáy có chân đế kỹ thuật thật.**
> Nhóm khác pitch một tính năng AI. Bạn pitch một *nền tảng agent* có runtime
> thật. Đừng so với họ bằng lời — so bằng kiến trúc.

---

# PHẦN 1 — CẤU TRÚC PITCH GỌN (10 slide cho 5 phút)

Ánh xạ thẳng vào thang điểm: Sáng tạo 20 · Khả thi 20 · Tác động 20 ·
Giải quyết vấn đề 20 · Công nghệ mới 8 · Layout 7 · Trình bày 5.

| # | Slide | Phục vụ điểm | Thời lượng |
|---|---|---|---|
| 1 | Hook + Vấn đề | Giải quyết vấn đề 20 | 40s |
| 2 | Định vị: đồng hành ≠ giao bài | Sáng tạo 20 | 30s |
| 3 | Vòng sư phạm (7 bước) | Sáng tạo + Giải quyết VĐ | 35s |
| 4 | Luồng quyết định Eris | Khả thi + CN mới | 45s |
| 5 | Tutor cắm vào kiến trúc | **Khả thi 20 (đinh)** | 45s |
| 6 | 3 kịch bản sống | Tác động + trình bày | 35s |
| 7 | Công nghệ & tích hợp mở | Công nghệ mới 8 | 30s |
| 8 | Tác động & quy mô | **Tác động 20** | 35s |
| 9 | Vì sao không ai đuổi kịp | Sáng tạo + Tác động | 30s |
| 10 | Tầm nhìn: nền tảng vô hạn | Tác động + chốt | 25s |

---

# PHẦN 2 — NỘI DUNG TỪNG SLIDE

## SLIDE 1 — HOOK + VẤN ĐỀ

**Tiêu đề:** AI dạy học hôm nay quên bạn ngay khi bạn tắt màn hình

**3 gạch đầu dòng:**
- Hỏi một câu → được một đáp án → hết. Lần sau quay lại từ số 0.
- Không ai giữ nhịp, không ai biết bạn yếu ở đâu, không ai đòi bạn chứng minh đã hiểu.
- Kết quả: học sinh có công cụ trả lời, nhưng không có **người đồng hành**.

**Câu hook nói miệng:**
"Mọi AI gia sư hiện nay đều là một cỗ máy trả lời. Hỏi — đáp — quên. Chúng tôi
hỏi một câu khác: nếu AI *ở lại* trong hành trình học thì sao?"

---

## SLIDE 2 — ĐỊNH VỊ (giữ slide 2 cũ, siết lại)

**Tiêu đề:** Một người đồng hành học, không phải máy phát bài tập

| AI GIAO BÀI | ERIS ĐỒNG HÀNH |
|---|---|
| Nhận câu hỏi → đưa lời giải | Hỏi người học đang vướng ở đâu |
| Chấm đúng/sai | Gợi ý vừa đủ để người học tự thử |
| Xong một lượt là kết thúc | Lưu tiến độ, chọn điểm cần ôn |
| Người học quay lại từ đầu | Nhắc học theo thỏa thuận, đúng thời điểm |

**Thước đo giá trị:** Người học tự giải thích và tự làm được nhiều hơn sau mỗi buổi.

---

## SLIDE 3 — VÒNG SƯ PHẠM (giữ slide 4 cũ)

**Tiêu đề:** Mỗi buổi học là một vòng lặp có bằng chứng

`Gợi lại → Chẩn đoán → Dạy đúng nhịp → Người học thử → Xem bằng chứng →
Phản hồi → Tiếp nối`

**Kết quả mỗi vòng:** một quyết định nhỏ — học tiếp, ôn lại, nghỉ, hay đổi cách dạy.

**Câu nói:** "Đây không phải chatbot. Đây là một chu trình sư phạm mà hệ thống
chạy qua từng lượt."

---

## SLIDE 4 — LUỒNG QUYẾT ĐỊNH ERIS

**Tiêu đề:** Một bộ não điều hành quyết định từng lượt, rồi mới nói

```
SỰ KIỆN  →  ROOT QUYẾT ĐỊNH  →  GỌI NĂNG LỰC  →  KẾT QUẢ VỀ ROOT  →  WRITER→TTS
user_turn   nói/im/nhớ/gọi       capability trả    quyết bước kế       diễn đạt→phát
nhắc học    (loop nhiều bước)    dữ liệu+biên nhận  theo bằng chứng     →giọng nói
```

**Câu chốt:** Root sở hữu *ý nghĩa hội thoại*; Writer chỉ *diễn đạt*; TTS chỉ
*phát*. Tách quyền quyết định khỏi quyền diễn đạt — thêm năng lực mới không phải
viết lại lõi.

**Gáy (nói miệng):** "Đây là agent loop nhiều bước có biên nhận chống bịa — kiến
trúc mà các sản phẩm production thực thụ dùng, không phải một lệnh gọi API."

---

## SLIDE 5 — TUTOR CẮM VÀO KIẾN TRÚC *(slide đinh)*

**Tiêu đề:** Tutor là một năng lực cắm vào bốn khớp nối có sẵn

```
   UI / VOICE  →  KERNEL  →  ROOT AGENT
                                  │
   WRITER→TTS ←──────────         ▼
                            ┌─────────────────────┐
   LEARNING STORE ────────→ │ TUTOR CORE          │
   mastery, bằng chứng,     │ LessonSession       │
   lịch ôn (bền vững)       │ LearnerModel        │
                            │ EvidenceEvaluator   │
                            │ TeachingStrategy    │
                            │ ReviewPlanner       │
                            └─────────────────────┘
```

**4 khớp nối:** Đăng ký → Gọi → Biên nhận tư vấn → Xác nhận đã dạy.

**Nguyên tắc:** Tutor không tự phát tiếng, không viết lại ý định. Root luôn chốt
hành vi. *Mô hình đề xuất — kernel deterministic commit.*

**Gáy:** "Chúng tôi không nhồi 'hãy làm gia sư tốt' vào một prompt. Chúng tôi
xây một giao diện năng lực chuẩn. Thêm gia sư Toán, Lý, Code, hay bất kỳ môn
nào — cùng một khớp nối, không đụng vào lõi."

---

## SLIDE 6 — BA KỊCH BẢN SỐNG (giữ slide 9 cũ)

**Tiêu đề:** Cảm giác đang học cùng một người thật

- **Người học bí:** "Em không hiểu sao vòng lặp dừng ở i=5." → Eris: "Tự đếm từ
  i=3 xem điều kiện đổi thế nào." *(gợi ý, không giải hộ)*
- **Muốn trốn học:** "Nói chuyện game đi, chán bài quá." → Eris: "Game 3 phút
  cũng được. Sau đó chọn làm thêm 1 câu hay nghỉ hẳn nhé." *(đàm phán nhịp)*
- **Nói đã xong:** "Xong rồi, giỏi chưa?" → Eris: "Đưa tôi một cách giải thích
  ngắn để tôi biết có nên tăng độ khó." *(đòi bằng chứng)*

---

## SLIDE 7 — CÔNG NGHỆ & TÍCH HỢP MỞ

**Tiêu đề:** Một nền tảng, không phải một tính năng

- **Agent loop đa bước** + capability registry có biên nhận.
- **Voice/TTS** với giao ước lượt nói: ngắt lời, phục hồi provider, đồng bộ phụ đề.
- **Learning kernel deterministic:** mastery, bằng chứng, lịch ôn spaced-repetition.
- **Tích hợp mở:** mỗi công cụ mới (SymPy, GeoGebra, Excalidraw, model mới…) là
  một capability cắm thêm — năng lực mở rộng không giới hạn ở một chuyên môn.

**Gáy:** "Mỗi đối thủ chọn một tính năng. Chúng tôi xây cái khung để *cắm vào vô
hạn tính năng*."

---

## SLIDE 8 — TÁC ĐỘNG & QUY MÔ

**Tiêu đề:** Từ một học sinh đến một hệ sinh thái học tập

- **Người dùng đầu:** học sinh/sinh viên tự học — cần người giữ nhịp và đòi bằng chứng.
- **Mở rộng chiều ngang:** thêm môn = thêm learning path + capability, không xây lại.
- **Mở rộng chiều dọc:** từ gia sư cá nhân → lớp học → nền tảng cho giáo viên theo
  dõi tiến độ cả lớp bằng dữ liệu mastery có nguồn.
- **Chuẩn mực quốc tế:** thiết kế bám EEF (metacognition, feedback) và UNESCO
  (quyền riêng tư, human agency) — không phải tự nghĩ ra.

**Gáy:** "Đây không phải app ôn thi. Đây là hạ tầng cho mọi hành trình học."

---

## SLIDE 9 — VÌ SAO KHÔNG AI ĐUỔI KỊP

**Tiêu đề:** Con đường không ai đi

| Nhóm khác | Eris |
|---|---|
| Một tính năng AI đơn lẻ | Một nền tảng agent nhiều năng lực |
| Prompt gọi API, hết lượt là quên | Runtime có trạng thái, biên nhận, trí nhớ bền vững |
| "Hãy làm gia sư tốt" nhét vào prompt | Learning kernel deterministic có luật rõ ràng |
| Khó mở rộng ngoài demo | Thêm năng lực = cắm capability, không đụng lõi |

**Gáy:** "Để làm được điều này không phải viết thêm vài prompt — phải có một
kiến trúc tách quyền quyết định khỏi quyền diễn đạt. Đó là rào cản mà một tính
năng đơn lẻ không bao giờ vượt được."

---

## SLIDE 10 — TẦM NHÌN

**Tiêu đề:** Eris là đồ án mở — tiềm năng không có trần

- Hôm nay: gia sư đồng hành có bằng chứng tiến bộ.
- Ngày mai: voice đa ngôn ngữ, vision opt-in, nhân vật trực quan, nhắc học nhiều ngày.
- Nền tảng: mỗi công cụ mới mở ra một cách mới AI hỗ trợ người học.

**Câu chốt cuối (học thuộc):**
"Các bạn khác xây một câu trả lời. Chúng tôi xây một người đồng hành — và một
nền tảng để nó lớn mãi. Eris không phải điểm đến. Eris là con đường."

---

# PHẦN 3 — SCRIPT NÓI 5 PHÚT (đọc trôi ~650-700 từ)

**[0:00–0:40] Hook**
"Thử nghĩ xem: bạn hỏi một AI một bài toán, nó giải xong, bạn tắt màn hình. Ngày
mai mở lại — nó không nhớ bạn là ai, bạn yếu chỗ nào, hôm qua học tới đâu. Mọi AI
gia sư hôm nay là một cỗ máy trả lời: hỏi, đáp, quên. Chúng tôi hỏi một câu khác:
nếu AI *ở lại* trong hành trình học thì sao? Đó là Eris."

**[0:40–1:10] Định vị**
"AI giao bài nhận câu hỏi rồi đưa lời giải. Eris thì hỏi bạn đang vướng ở đâu,
gợi ý vừa đủ để bạn tự thử, lưu lại tiến độ, và nhắc bạn ôn đúng lúc. Khác biệt
không nằm ở số bài tập sinh ra — mà ở vòng quan hệ: học, phản hồi, tự chứng minh,
tiếp nối. Thước đo của chúng tôi là: sau mỗi buổi, người học tự làm được nhiều hơn."

**[1:10–1:45] Vòng sư phạm**
"Mỗi buổi học, Eris chạy một vòng: gợi lại mục tiêu, chẩn đoán điểm kẹt, dạy đúng
nhịp, để người học thử, xem bằng chứng, phản hồi, rồi chốt điểm yếu hẹn ôn. Kết
thúc mỗi vòng là một quyết định nhỏ — học tiếp, ôn lại, hay đổi cách dạy. Đây
không phải chatbot. Đây là một chu trình sư phạm hệ thống chạy qua từng lượt."

**[1:45–2:30] Luồng quyết định (bắt đầu gáy kỹ thuật)**
"Và đây là thứ khiến Eris khác về bản chất. Mỗi sự kiện — một câu hỏi, một lời
nhắc học — đi vào một bộ não điều hành gọi là Root. Root chạy một vòng lặp nhiều
bước: nó quyết nói hay im, cần nhớ lại gì, có cần gọi một năng lực chuyên môn
không. Mỗi bước trả về một *biên nhận* — bằng chứng, để Root không bịa. Chỉ khi
Root chốt, nội dung mới đi qua lớp diễn đạt rồi tổng hợp giọng nói. Chúng tôi
tách *quyền quyết định* khỏi *quyền diễn đạt*. Đây là kiến trúc của sản phẩm
production thật, không phải một lệnh gọi API."

**[2:30–3:15] Tutor cắm vào (slide đinh)**
"Phần gia sư của Eris không phải một prompt 'hãy làm gia sư tốt'. Nó là một năng
lực cắm vào bốn khớp nối có sẵn trong kiến trúc: đăng ký, gọi, nhận biên nhận tư
vấn, và xác nhận đã dạy. Bên trong là năm lớp: phiên học giữ trạng thái buổi dạy,
hồ sơ người học theo dõi mức nắm vững, bộ chấm bằng chứng, chiến lược dạy trong
khung quyền, và bộ lập lịch ôn theo đường quên. Nguyên tắc: model *đề xuất*,
kernel deterministic *chốt*. Nghĩa là hành vi dạy ổn định theo luật — không phụ
thuộc may rủi của một câu prompt."

**[3:15–3:50] Kịch bản sống**
"Nó hoạt động thế nào? Người học bí: Eris không giải hộ, nó gợi 'tự đếm từ i=3
xem'. Người học muốn trốn: Eris đàm phán — 'game 3 phút, rồi chọn làm thêm 1 câu
hay nghỉ'. Người học nói 'xong rồi': Eris đòi bằng chứng — 'giải thích ngắn cho
tôi để biết có nên tăng độ khó'. Cảm giác là đang học cùng một người, không phải
một cái máy."

**[3:50–4:20] Công nghệ + tác động**
"Mỗi đối thủ chọn một tính năng. Chúng tôi xây cái khung để cắm vào vô hạn tính
năng — thêm môn, thêm công cụ như SymPy hay GeoGebra, thêm model mới, tất cả là
một capability cắm thêm. Từ một học sinh tự học, mở rộng tới lớp học, tới nền tảng
cho giáo viên theo dõi tiến độ bằng dữ liệu có nguồn. Thiết kế bám chuẩn EEF và
UNESCO về quyền riêng tư và quyền tự chủ của người học."

**[4:20–5:00] Chốt**
"Để làm được điều này không phải viết thêm vài prompt. Phải có một kiến trúc tách
quyền quyết định khỏi quyền diễn đạt, một learning kernel có luật, một hệ biên
nhận chống bịa. Đó là rào cản mà một tính năng đơn lẻ không bao giờ vượt. Các bạn
khác xây một câu trả lời. Chúng tôi xây một người đồng hành — và một nền tảng để
nó lớn mãi. Eris không phải điểm đến. Eris là con đường. Cảm ơn ban giám khảo."

---

# PHẦN 4 — BỘ PHẢN BIỆN (chuẩn bị cho 2 phút Q&A)

Nguyên tắc trả lời: **ngắn, có chân đế, không phòng thủ.** Nếu chưa có thì nói
"đây là thiết kế, đây là điểm móc để làm" — đừng giả vờ đã xong.

**H: "Cái này khác gì ChatGPT / Khanmigo / Gemini?"**
Đ: "Những cái đó là một model trả lời trong một lượt. Eris là một *runtime* có
trạng thái: Root quyết định nhiều bước, biên nhận chống bịa, learning kernel giữ
mastery bền vững qua các buổi. Chúng tôi không cạnh tranh ở chất lượng câu trả
lời — chúng tôi cạnh tranh ở khả năng *đồng hành có trạng thái*. Đó là tầng kiến
trúc, không phải tầng prompt."

**H: "Các em demo được phần gia sư chưa?"**
Đ: "Kiến trúc hội thoại có sẵn bốn khớp nối cho năng lực chuyên môn, và Root đã
mở khe gọi tutor trong schema quyết định. Năm lớp Tutor Core ánh xạ vào các
module learning kernel đã có cấu trúc dữ liệu. Phần chúng tôi tập trung là nối
trọn vòng từ hội thoại tới learning path — đây là điểm móc, không phải xây lại
từ đầu. Đó chính là lý do khả thi."

**H: "Chống bịa thế nào? AI vẫn hay bịa 'em làm tốt lắm'."**
Đ: "Eris phân biệt 'định nói' với 'đã dạy' bằng biên nhận. Chỉ khi một câu thực
sự phát thành công, hệ thống mới ghi nhận tiến độ. Và nguyên tắc cứng: không được
nói 'tôi thấy em làm bài' nếu chỉ có tin nhắn tự báo — bằng chứng phải qua đường
phân tích thật và có sự cho phép."

**H: "Phạm vi quá rộng, ôm đồm. Sao làm nổi?"**
Đ: "Chính vì rộng nên chúng tôi không nhồi vào một prompt. Chúng tôi xây một
*giao diện năng lực chuẩn* và một *learning kernel deterministic*. Rộng được là
nhờ kiến trúc, không nhờ cố gắng. Mỗi năng lực mới là một capability độc lập cắm
vào cùng bốn khớp nối. Đây là cách các nền tảng lớn mở rộng."

**H: "Quyền riêng tư dữ liệu học của trẻ thì sao?"**
Đ: "Trí nhớ học tách khỏi trí nhớ hội thoại, có cờ consent và hard-forget chặn
mọi đường ghi lại. Thiết kế bám UNESCO về quyền tự chủ người học. Nhắc học dùng
lịch có đồng ý riêng, không biến lời hẹn thành ép buộc."

**H: "Voice có hoạt động thật không hay chỉ slide?"**
Đ: "TTS có giao ước lượt nói: ngắt lời hủy đúng audio, phục hồi khi provider lỗi,
đồng bộ phụ đề với trạng thái phát thật. Phần này cần kiểm thử live — chúng tôi
trình bày nó như một tầng đã có cơ chế, cần nghiệm thu bằng tình huống thật."

**H: "Điểm yếu lớn nhất của dự án là gì?"** *(câu bẫy — trả thật sẽ ghi điểm)*
Đ: "Nối trọn vòng từ hội thoại tới khởi tạo learning path và kiểm thử voice
end-to-end dưới tải thật. Chúng tôi biết chính xác nó nằm ở đâu trong kiến trúc,
và đó là lý do chúng tôi tự tin — vấn đề đã được khoanh vùng, không phải ẩn số."

---

# PHẦN 5 — CHECKLIST TRÌNH BÀY (5đ kỹ năng)

- [ ] Người nói chính thuộc câu hook và câu chốt — không đọc slide.
- [ ] Slide 5 (Tutor cắm vào) là slide dừng lâu nhất — đây là đinh.
- [ ] Mỗi lần "gáy" phải kèm một danh từ kỹ thuật thật (capability registry,
      biên nhận, learning kernel) — gáy trần trụi là bị bóc.
- [ ] Dự phòng: in sơ đồ luồng ra giấy phòng khi máy chiếu lỗi.
- [ ] Giữ 2 phút phản biện: trả lời ngắn, không cướp lời giám khảo.
- [ ] Đừng bao giờ nói "đã hoàn thiện 100%" — nói "kiến trúc sẵn sàng, đây là
      con đường thực thi". Trung thực có kiểm soát ghi điểm khả thi cao hơn khoe khoang.
