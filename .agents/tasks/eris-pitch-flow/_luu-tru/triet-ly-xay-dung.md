# ERIS — TRIẾT LÝ XÂY DỰNG

> Luồng là hệ quả. Triết lý là nguyên nhân. Tài liệu này đặt **niềm tin thiết
> kế** làm trung tâm — mỗi triết lý kèm một dòng chứng minh "vì tin điều này,
> hệ thống được code ra như thế". Phần mô tả luồng để ngắn ở cuối.

---

## MỘT DÒNG ĐỊNH NGHĨA

Eris không phải một con AI biết trả lời. Eris là một **hệ điều hành nhận thức**:
một kiến trúc nơi quyền quyết định, quyền diễn đạt, quyền phát tiếng và quyền ghi
nhớ bị tách rời và ràng buộc bằng luật — để một tác nhân tự chủ có thể *hành động
mà vẫn trung thực*.

---

# NĂM TRIẾT LÝ NỀN

## Triết lý 1 — "Quyền lực phải bị chia nhỏ"

**Niềm tin:** Một tác nhân AI nguy hiểm không phải vì nó ngốc, mà vì nó *gộp quá
nhiều quyền vào một lời gọi model*. Khi một câu `generate()` vừa quyết định, vừa
diễn đạt, vừa tuyên bố "đã xong", không còn chỗ nào để cài luật.

**Nên Eris tách bốn quyền:**
- Quyền **quyết định** (Root) — chọn ý định của lượt.
- Quyền **diễn đạt** (Writer) — biến ý định thành câu.
- Quyền **phát** (Delivery/TTS) — đưa ra tai người nghe.
- Quyền **ghi nhớ** (LearningService/Memory) — commit sự thật bền vững.

Mỗi quyền là một ranh giới có thể kiểm soát độc lập. Writer không được *biết đáp
án*. Tutor không được *tự phát tiếng*. Memory không được *tự nói*. Root không
được *tự viết câu*.

**Câu gáy:** "Chúng tôi không hỏi 'model có thông minh không'. Chúng tôi hỏi
'model được phép làm gì'. Đó là khác biệt giữa một chatbot và một hệ điều hành."

---

## Triết lý 2 — "Trung thực là một thuộc tính của hệ thống, không phải của model"

**Niềm tin:** Dặn model "đừng bịa" là vô dụng. Model sẽ bịa khi nó *tin* là đã
làm. Trung thực phải được bảo chứng bằng *sự kiện vật lý có biên nhận*, không
bằng niềm tin của model.

**Nên Eris phân biệt ba trạng thái không thể giả:**
`định nói` ≠ `đã nói` ≠ `đã dạy`. Mỗi bước tiến chỉ xảy ra khi có biên nhận
(receipt) gắn mã sự kiện/lượt chạy, không ghi đè được. Sau khi crash, hệ thống
ghi "KHÔNG RÕ" thay vì giả vờ "đã phát". Tutor chỉ ghi "đã dạy" khi câu thực sự
ra tai người học.

**Câu gáy:** "Eris không được phép nói 'em đã làm bài' chỉ vì bạn nhắn thế. Phải
có bằng chứng. Chống bịa là luật của hệ thống, không phải lời khuyên cho model."

---

## Triết lý 3 — "Phân bổ sự chú ý theo vai trò, không theo sức mạnh model"

**Niềm tin:** Nghĩ theo kiểu "việc khó dùng model to" là tư duy nghèo. Cùng một
model có thể đang làm một việc *không được phép thất bại* (trả lời người dùng) và
một việc *có thể bỏ qua khi quá tải* (suy nghĩ nền). Phải phân biệt chúng bằng
*vai trò*, không bằng tên model.

**Nên Eris tách ba trục trực giao:** vai trò nhận thức / đường truyền / tài
nguyên. Lane phục vụ người dùng là **bất khả xâm phạm** — không bao giờ bị cắt.
Lane nền có thể bị gộp, bị hoãn, bị bỏ.

**Bài học thật đóng băng thành luật:** Eris từng *im lặng* vì một nhãn tài nguyên
cũ vô tình kéo bước điều hành bắt buộc xuống nhóm "có thể bỏ". Chúng tôi không vá
triệu chứng — chúng tôi nâng "vai trò nhận thức" lên trên "nhãn tài nguyên" như
một bất biến.

**Câu gáy:** "Chúng tôi không routing theo model. Chúng tôi routing theo *ý
nghĩa của việc đang làm*. Đó là lý do khi quá tải, Eris hy sinh suy nghĩ nền chứ
không bao giờ bỏ rơi người dùng."

---

## Triết lý 4 — "Tác nhân tự chủ phải fail an toàn, không fail im lặng"

**Niềm tin:** Một hệ thống chủ động (tự nói, tự nhắc, tự nghĩ) mà hỏng thì nguy
hiểm gấp đôi hệ thống bị động. Nên trước khi cho nó *chủ động*, phải có cơ chế
*hủy, phục hồi, và luôn có tiếng*.

**Nên Eris có:**
- Một đường phát **không đi qua LLM** — khi model chết, Eris vẫn lên tiếng báo
  trục trặc, không treo im lặng.
- **Preemption tức thì** — người dùng chen lời là cả một "thế hệ" cũ chết ngay,
  không cần hủy từng tiến trình.
- **Hai tầng phanh** cho vòng suy nghĩ — trần cứng số bước + cắt sớm khi quay
  vòng vô ích.
- **Fallback có nhân cách** — thiếu model chuyên môn thì chạy logic bảo thủ, chứ
  không "màn hình trắng".

**Câu gáy:** "Chúng tôi đặt cơ chế hủy, nhớ và phục hồi *trước* khi đặt tính chủ
động. Một con AI chủ động mà không biết dừng là một con AI nguy hiểm."

---

## Triết lý 5 — "Mở rộng bằng cách cắm vào, không bằng cách viết lại"

**Niềm tin:** Một nền tảng thật sự không lớn lên bằng cách nhồi thêm tính năng
vào lõi. Nó lớn bằng cách cung cấp *những khớp nối chuẩn* để năng lực mới cắm vào
mà lõi không đổi, và các bất biến không vỡ.

**Nên Eris có một giao diện năng lực chuẩn:** đăng ký → gọi → biên nhận tư vấn →
xác nhận đã làm. Tutor, nghiên cứu, hành động — tất cả là năng lực cắm vào cùng
bốn khớp. Thêm gia sư môn mới, thêm chấm ảnh bằng vision, thêm nhắc học nhiều
ngày: mỗi thứ cắm vào một điểm móc *đã tồn tại*, giữ nguyên luật chống bịa và
ranh giới quyền lực.

Và nguyên lý sâu nhất của lớp học tập: **"LLM đề xuất; kernel deterministic
chốt."** Model gợi ý cách dạy; nhưng ghi nhận tiến độ là việc của một kernel có
luật — để một câu bịa của model không bao giờ nhiễm độc hồ sơ người học.

**Câu gáy:** "Nhóm khác xây một tính năng. Chúng tôi xây cái khung để cắm vào vô
hạn tính năng. Đó là lý do Eris là đồ án mở không có trần."

---

# LUỒNG (phần phụ — mô tả ngắn)

Triết lý ở trên hiện thực hóa thành một luồng năm nhịp:

```
SỰ KIỆN → ROOT QUYẾT ĐỊNH → GỌI NĂNG LỰC → KẾT QUẢ (biên nhận) → DIỄN ĐẠT → PHÁT
 (chat,    (vòng lặp nhiều    (tutor/        (về Root quyết        (Writer)  (TTS)
 nhắc học)  bước, mỗi bước     research/      bước kế theo
            một hành động)     action)        bằng chứng)
```

- **Root** là bộ não điều hành duy nhất: mỗi lượt chạy một vòng nhiều bước, mỗi
  bước chọn đúng một hành động (nói / im / nghĩ tiếp / nhớ lại / gọi năng lực).
- **Năng lực** (như Tutor) trả về dữ liệu + biên nhận, không tự phát tiếng.
- **Writer** diễn đạt ý định thành câu; **Delivery/TTS** phát ra giọng nói.
- Mỗi lời nói đi qua vòng trạng thái có biên nhận; người dùng chen lời là hủy
  sạch thế hệ cũ.

Chi tiết kỹ thuật + bằng chứng code: xem `deep-architecture.md`.

---

# CÂU KẾT (linh hồn của pitch)

"Chúng tôi không hỏi: *AI này trả lời giỏi không?*
Chúng tôi hỏi: *làm sao để một tác nhân tự chủ hành động mà vẫn trung thực, vẫn
nhường người dùng, và vẫn lớn lên được mà không vỡ?*

Năm câu trả lời đó — chia quyền, chống bịa bằng hệ thống, phân chú ý theo vai
trò, fail an toàn, mở rộng bằng cắm vào — là triết lý xây dựng Eris. Luồng chỉ
là hệ quả của chúng.

Các bạn khác xây một câu trả lời. Chúng tôi xây một cách nghĩ."
