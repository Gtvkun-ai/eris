# ERIS — SCRIPT THUYẾT TRÌNH V2 (bản ý tưởng để phát triển)

> Đây KHÔNG phải ver cuối đi nộp. Đây là khung + lời để bạn sửa, cắt, thêm.
> Chỗ `【...】` là chỗ chờ bạn điền câu chuyện thật — tôi không bịa thay.
> Mọi khẳng định kỹ thuật ở đây đã đối chiếu `DIEU-TRA-LOOP-EVIDENCE.md`.
> Nguồn số liệu thị trường: `TAC-DONG-BANG-CHUNG.md`.
>
> MẠCH: Vấn đề người học → Triết lý → Vòng agent loop → Mô hình người học →
> Cơ chế tin cậy & khả thi → Giá trị & hướng phát triển.
> Nguyên tắc: dẫn bằng HỆ THỐNG CHẠY ỔN ĐỊNH trước, lỗi là một nhánh của hệ thống đó.

---

## PHẦN 0 · Mở màn (0:00–0:35)

Mục tiêu: ghim người nghe, đặt một câu hỏi mà cả bài sẽ trả lời. Chưa nói kỹ thuật.

> Kính chào ban giám khảo. Trước khi em trình bày, xin hỏi các thầy cô một câu.
> [...] Một gia sư AI trả lời đúng mọi câu hỏi — đã đủ để một học sinh giỏi lên chưa?
> [...]
> Câu trả lời là chưa. Có một thử nghiệm hai năm trên mười tám trường ở Mỹ: gần như
> toàn bộ học sinh đều thử gia sư AI, nhưng phần lớn bỏ nó sau vài ngày, và kết quả
> học cuối cùng không hơn nhóm không dùng AI.
> [...]
> Vấn đề của gia sư AI không phải trả lời dở. Là không ai ở lại đủ lâu để nó kịp dạy.
> Và sâu hơn: kể cả khi ở lại, làm sao nó biết bạn thật sự tiến bộ, hay chỉ đang gật đầu?
> [...]
> Đó là hai câu hỏi Eris được sinh ra để trả lời.

Ghi chú: số Khanmigo lấy từ `TAC-DONG-BANG-CHUNG.md` mục A. Không nói "học sinh Việt Nam
cũng vậy" — đó là học sinh yếu, một môn, một bang ở Mỹ.

---

## PHẦN 1 · Triết lý thiết kế (0:35–1:30)

Mục tiêu: kể CÁCH nhóm đi tới triết lý, không đọc khẩu hiệu. Đây là "linh hồn" của bài.

> Khi bắt đầu, chúng em không hỏi "làm sao cho AI thông minh hơn". Model nào rồi cũng
> thông minh hơn sau vài tháng. Chúng em hỏi một câu khác: một AI được phép TỰ HÀNH ĐỘNG
> thì phải bị ràng buộc thế nào để vẫn đáng tin?

> 【CHỖ KỂ CÂU CHUYỆN GỐC — bạn điền:
>   - Cú hích đầu: vì sao muốn làm gia sư mà không phải chatbot trả lời? Từng thấy AI
>     nói bừa / dạy sai / trả lời xong là xong, chẳng ai học được gì?
>   - Lần vỡ mộng: lúc xây, Eris từng làm đúng điều bạn sợ — nói "em làm rồi" khi chưa
>     làm, chen ngang lúc người ta đang gõ, hay đơ giữa buổi?
>   Tôi sẽ gọt 2-3 câu này thành đoạn dẫn. Chưa có thì để trống, tôi viết bản tạm bên dưới.】

Bản tạm (dùng nếu chưa có chuyện thật, thay sau):

> Chúng em bị thuyết phục bởi một ý rất đơn giản: đừng cố làm hệ thống BIẾT người học đã
> hiểu. Hãy làm hệ thống biết nó có BAO NHIÊU BẰNG CHỨNG để tin rằng người học đã hiểu.
> [...]
> "Đã hiểu" là một trạng thái không ai đo được — kể cả giáo viên giỏi. Nhưng "có bao nhiêu
> bằng chứng, mạnh tới đâu, từ đâu ra" thì đo được, ghi lại được, và kiểm tra lại được.
> [...]
> Từ một câu đó, mọi quyết định kiến trúc của Eris chảy ra: ai được quyết, ai chỉ được đề
> xuất, và một điều chỉ được ghi là "đã dạy" khi nào.

---

## PHẦN 2 · Vòng Agent Loop (1:30–2:30)

Mục tiêu: cho thấy một VÒNG CHẠY ỔN ĐỊNH trước. Đây là xương kỹ thuật. Dùng SƠ ĐỒ, không đọc code.

> Trái tim của Eris là một vòng lặp. Mỗi khi có sự kiện — người học nhắn, hoặc đến lúc Eris
> chủ động — một bộ não điều hành tên là Root bước vào vòng này.
> [...]
> Mỗi bước, Root chỉ được chọn đúng MỘT việc: nhớ lại điều đã biết về người học, gọi gia sư
> để dạy hoặc chấm, nghĩ thêm một nhịp, ghi chú để dùng sau, hoặc chốt một lời để nói. Rồi
> kết quả quay về, nó mới bước tiếp.
> [...]
> Và vòng này có PHANH. Tối đa mười hai bước. Hai bước liền không tiến triển là tự dừng.
> Nghĩ thầm tối đa hai lần. Một AI tự hành động mà không có phanh thì không ai dám cho nó
> tự nói — nên phanh là thứ chúng em xây trước cả tính năng.

SƠ ĐỒ slide (vẽ lại, đây là mô tả):

```
SỰ KIỆN → [ROOT: chọn 1 trong 7 việc] → kết quả + biên nhận → (lặp, có phanh) → CHỐT: nói / im
            nhớ lại · gọi gia sư · nghĩ thêm · ghi chú · chốt lời · im lặng
            phanh: ≤12 bước · 2 bước không tiến triển thì dừng · nghĩ thầm ≤2
```

Ghi chú trung thực (theo điều tra): loop này nhóm tự mô tả là "agent loop nhỏ", KHÔNG viện
dẫn ReAct trong code. Đừng nói "dựa trên ReAct". Learning kernel (phần sau) mới ghi nguồn
DeepTutor, Apache 2.0 — chỗ đó được phép nói nguồn.

---

## PHẦN 3 · Mô hình người học (2:30–3:20)

Mục tiêu: trả lời "Eris biết bạn hiểu hay chưa bằng cách nào". Đây là phần ăn điểm sáng tạo.

> Vậy Eris hiểu người học bằng cái gì? Không phải một ô "đã hiểu / chưa hiểu". Mà bằng một
> hồ sơ có bốn lớp.
> [...]
> Một: từng kỹ năng có một con số nắm vững, chạy liên tục từ không tới một — kèm một con số
> thứ hai: độ tin cậy, tức Eris chắc chắn tới đâu về nhận định đó.
> Hai: mỗi lần người học làm gì, nó để lại một mẩu bằng chứng — trả lời đúng, giải thích lại
> được, hay lộ ra một lỗi nhận thức quen thuộc.
> Ba: Eris giữ cả "điều đã có bằng chứng là hiểu" lẫn "điều còn mơ hồ" ở hai ô riêng, không
> gộp thành một phán xét.
> Bốn: nó có giả thuyết về chỗ người học đang vướng — nhưng giả thuyết độ tin cậy thấp thì
> Eris phải HỎI để kiểm, không được biến phỏng đoán thành kết luận.
> [...]
> Và đây là ranh giới quan trọng nhất: Eris chỉ ghi "đã nắm kỹ năng này" khi con số nắm vững
> vượt ngưỡng VÀ có đúng loại bằng chứng — ví dụ một khái niệm thì phải giải thích lại được,
> chứ không phải đoán trúng một lần.

SƠ ĐỒ slide: dùng đúng cái sơ đồ "Mô hình trạng thái học tập" bạn vừa gửi (Kiến thức / Sai lầm
/ Bằng chứng / Độ tin cậy → chọn chiến thuật dạy tiếp). Nó khớp 1-1 với code.

Nền code (theo điều tra, để phản biện): `MasteryRecord{mastery, confidence, stage,
error_codes, retrievability...}`; gate "đã nắm" ở `mastery.py::gate_passed` (vượt ngưỡng theo
loại tri thức + bằng chứng phù hợp). Không có cờ nhị phân.

---

## PHẦN 4 · Cơ chế tin cậy — vì sao khác chatbot tự khen (3:20–4:15)

Mục tiêu: trả lời thẳng phản biện "model tự tạo evidence, tự khen đúng thì khác gì chatbot".
Đây là phần ăn điểm khả thi + công nghệ. Dùng một LUỒNG có CỔNG GÁC trực quan.

> Câu hỏi khó nhất là: nếu chính model tự chấm, tự gắn độ tin cậy, tự xác nhận — thì khác gì
> một chatbot tự khẳng định mình đúng?
> [...]
> Câu trả lời của Eris: model KHÔNG được tự xác nhận. Model chỉ ĐỀ XUẤT. Việc một đánh giá có
> được ghi vào hồ sơ học hay không do một bộ máy có luật quyết — và nó chỉ ghi khi qua ba cổng.
> [...]
> Cổng một: đánh giá phải đủ chắc. Nếu model nói "em không chắc", hoặc độ tin cậy dưới ngưỡng,
> bằng chứng bị loại — thà không ghi còn hơn chấm bừa.
> Cổng hai: lời dạy phải thật sự đã phát tới người học và có biên nhận. Eris "định nói" không
> đồng nghĩa Eris "đã dạy".
> Cổng ba: con số nắm vững không do model gán. Nó được một hàm tính lại từ TOÀN BỘ bằng chứng
> đã tích lũy. Model không chạm được vào con số đó.
> [...]
> Và để model không thể gian lận ngay từ đầu: người viết lời cho người học KHÔNG BAO GIỜ cầm
> đáp án. Đáp án ở lại phía trong. Nên model không thể lỡ miệng đọc đáp án ra, cũng không thể
> tự nhận là đã dạy xong khi chưa.

SƠ ĐỒ slide (mô tả — đây là "luồng có cổng gác" bạn muốn):

```
MODEL ĐỀ XUẤT đánh giá
   │  (verdict + confidence)
   ▼
[CỔNG 1] confidence ≥ ngưỡng? và không "uncertain"?  ── không ─► BỎ, không ghi
   │ có
   ▼
[CỔNG 2] lời dạy đã phát, có biên nhận thành công?   ── không ─► chưa tính là "đã dạy"
   │ có
   ▼
[CỔNG 3] KERNEL tính lại con số nắm vững bằng hàm thuần từ mọi bằng chứng
   │
   ▼
GHI vào hồ sơ học  (model không gán trực tiếp)
```

Nền code (theo điều tra, để phản biện): `executive.py::_apply_semantic_assessment` (loại khi
verdict uncertain hoặc confidence < ngưỡng mặc định 0.68); `commit_delivery` (chỉ tính khi có
receipt); `service.py::compute_mastery` (hàm thuần); `to_writer_dict()` cố ý bỏ expected_answer.
Nói "ngưỡng MẶC ĐỊNH 0.68" — caller có thể đổi (clamp 0.50–0.95), đừng nói "cố định".

Câu gói lại (dùng được làm một dòng to trên slide):

> Trung thực không phải một lời dặn model. Trung thực là một đường dữ liệu có cổng gác.

---

## PHẦN 4B · Khả thi — vì sao tin nhóm này làm được (chèn 3:20 khu vực, siết giờ)

Mục tiêu: ăn trọn cột KHẢ THI 20đ. Hai thứ giám khảo cần: làm được trong tầm tay không, và
nhóm có đủ sức không. Trả lời cả hai bằng BẰNG CHỨNG, không bằng lời hứa.

Bằng chứng năng lực — câu chuyện HOTFIX (đây là thứ mạnh nhất cả bài, kéo từ phụ lục lên):

> Để các thầy cô tin đây không phải slide vẽ cho đẹp — em kể một lần Eris hỏng thật.
> [...]
> Có một bước kiểm bắt buộc trước khi Eris nói. Một lần, nó bị xếp nhầm vào nhóm "được phép bỏ
> khi máy bận". Máy bận, hệ thống bỏ luôn bước đó, và Eris đứng im giữa buổi học. [...] Chúng em
> không vá tạm. Chúng em truy ra gốc: nó bị phân loại theo một cái nhãn cũ thay vì theo vai trò.
> Và chúng em đặt thành một luật không bao giờ phá: vai trò xét trước nhãn. Bước bắt buộc thì
> không ai được cắt.
> [...]
> Một nhóm chỉ ghép API không gặp bug kiểu này, vì họ không tự xây cái vòng đó. Chúng em gặp,
> vì chúng em xây thật. Và chúng em sửa được, vì chúng em hiểu nó tới tận gốc.

Điểm nói kèm: đây là bằng chứng nhóm VẬN HÀNH thật, không chỉ viết code chạy một lần. Không đội
nào bịa được một chi tiết vận hành như vậy.

Lộ trình MVP — cho thấy biết làm gì trước, gì sau (dựng thành một slide 3 mốc):

```
ĐÃ CÓ (kiến trúc + cơ chế)        →  MVP (vòng thi / ngay sau)       →  MỞ RỘNG
· agent loop Root có phanh            · nối learning kernel vào           · thêm môn
· learning kernel (model đề xuất,       hot-path chat live               · chấm ảnh bài làm
  kernel chốt, ngưỡng, receipt)      · một môn, một nhóm người học       · nhắc học nhiều ngày
· mô hình mastery liên tục           · bật ghi evidence end-to-end       · dự đoán điểm yếu
· nhân vật: giọng + Live2D           · đo thử mastery theo thời gian
```

Trung thực có kỷ luật (nói đúng ranh giới, để phản biện không bắt bài):

> Em nói rõ đâu là đã có, đâu là bước kế. Kiến trúc và các cơ chế vừa trình bày đã nằm trong
> code. Việc nối nó chạy liên tục trong một phiên học thật và đo kết quả — đó là MVP chúng em
> đang đi tới, không phải thứ em nhận là đã xong. [...] Chúng em biết chính xác mình đang đứng
> ở đâu. Đó mới là thứ làm một dự án khả thi.

Ghi chú (theo `DIEU-TRA-LOOP-EVIDENCE.md`): KHÔNG nói "đã chạy live trên học sinh". Code có
`coordinator.py` build tutor_bundle nhưng còn fail-soft, chưa giành hot-path delivery. Nói
"kiến trúc đã có khớp nối, MVP là bước nối" — đúng và vẫn mạnh.

---

## PHẦN 5 · Giá trị & hướng phát triển (4:15–5:00)

Mục tiêu: trả lời câu "30 ngày không hơn chatbot thì có thành công không" một cách TRUNG THỰC,
rồi mở ra thị trường. Ăn điểm tác động.

Trả lời thẳng câu bẫy (tự nói trước khi giám khảo nói):

> Các thầy cô có thể hỏi: nếu học sinh dùng Eris ba mươi ngày mà không giỏi hơn một chatbot
> thường, thì dự án này có thành công không? [...] Em trả lời thật: theo thước đo kết quả học,
> là CHƯA. Và chúng em không giấu điều đó.
> [...]
> Nhưng có một khác biệt: chatbot thường không để lại gì để đo. Eris thì ghi lại từng mẩu bằng
> chứng, từng con số nắm vững, theo thời gian. Nó là hệ thống duy nhất có thể TRẢ LỜI chính câu
> hỏi đó bằng dữ liệu. Chúng em không hứa đã hơn — chúng em xây sẵn con đường để đo xem có hơn không.

Thị trường (số từ `TAC-DONG-BANG-CHUNG.md`, nói "đi cùng" không nói "nhờ"):

> Vì sao hướng này đáng đặt cược? Vì nhân vật có cá tính giữ được người. Neuro-sama, một nhân
> vật AI, đầu 2026 là kênh có nhiều người trả phí nhất trên Twitch. Duolingo đi cùng chiến lược
> nhân vật, người dùng hằng tháng tăng từ hơn bốn mươi triệu lên trên một trăm mười triệu.
> [...]
> Nhưng nhân vật thì không dạy có bằng chứng, còn gia sư có cấu trúc thì bị bỏ. Eris đứng giữa:
> một nhân vật người ta muốn quay lại, đặt trên một bộ não dạy học có luật.

Tác động — bán bằng ĐỘ MỞ của kiến trúc (đây là góc ăn điểm "tiềm năng phát triển"):

> Và đây là lý do Eris không phải một bài thi rồi cất đi. Nó là một đồ án mở — không có trần.
> [...]
> Mọi thứ các thầy cô vừa thấy đều cắm vào cùng một bộ khớp nối. Thêm một môn mới? Cắm vào.
> Cho Eris nhìn ảnh bài làm tay? Cắm vào. Nhắc học qua nhiều ngày, dự đoán học sinh sắp vấp ở
> đâu? Cùng một bộ khớp. [...] Mỗi nâng cấp KHÔNG phải viết lại lõi — nó là một mảnh cắm thêm,
> và các luật trung thực vừa nói vẫn giữ nguyên.
> [...]
> Nghĩa là Eris lớn lên mà không vỡ. Từ một người học, lên một lớp, lên một trường — cùng một
> bộ não, cùng một bộ luật, chỉ thêm khớp. Phần lớn sản phẩm AI càng thêm tính năng càng rối
> tới mức phải đập đi làm lại. Eris được thiết kế để điều ngược lại: càng thêm càng mạnh.

SƠ ĐỒ slide: một lõi ở giữa (agent loop + learning kernel + nhân vật), quanh nó là các khớp
nối cắm vào — mỗi khớp một mũi tên hướng VÀO lõi, nhãn: môn mới · vision chấm ảnh · nhắc nhiều
ngày · dự đoán điểm yếu · cá nhân → lớp → trường. Thông điệp hình: lõi không đổi, chỉ thêm khớp.

Chốt:

> Model rồi sẽ thay. Thứ ở lại là cách Eris học cách đồng hành với một người mà vẫn trung thực.
> Chúng em không hỏi AI này trả lời có giỏi không. Chúng em hỏi: làm sao để một AI tự hành động
> mà vẫn trung thực, biết nhường, và lớn lên mà không sụp đổ. [...] Em cảm ơn ban giám khảo.

---

## PHỤ LỤC · để trả lời 2 phút phản biện (không lên slide chính)

Theo `DIEU-TRA-LOOP-EVIDENCE.md`, nói được những điều này nếu bị đào:

- "Model tự khen thì sao?" → ba cổng: ngưỡng confidence, receipt delivery, mastery tính bằng
  hàm thuần. Model chỉ đề xuất.
- "Đã chạy thật trên học sinh chưa?" → trung thực: KIẾN TRÚC có cơ chế này trong code; CHƯA có
  số liệu 30 ngày, chưa xác minh một phiên chat live đã đi hết đường evidence. Đó là bước đo
  tiếp theo, không phải thứ đã xong. ĐỪNG nói "đã chạy live".
- "Evidence nằm đâu?" → trong SQLite qua LearningStore, không phải file telemetry JSONL. Đừng
  chỉ nhầm vào session-observability.jsonl (đó chỉ là metric token/queue).
- Nguồn: learning kernel port từ DeepTutor (Apache 2.0). Loop hội thoại nhóm tự thiết kế.

---

## VIỆC CÒN LẠI CHO BẠN

1. Điền `【câu chuyện gốc】` ở Phần 1 — chỉ bạn có.
2. Quyết có demo giọng/Live2D ở mở màn không. Có thì chèn 10s đầu Phần 0.
3. Bấm giờ đọc thật một lần, cắt cho vừa 5 phút.
4. Nói tôi chỗ nào giọng văn còn "ngu", tôi sửa tiếp — đây là bản để phát triển.
