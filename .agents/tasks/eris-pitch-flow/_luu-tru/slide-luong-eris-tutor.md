# Nội dung slide pitch Eris — phần LUỒNG HỆ THỐNG + TUTOR

Giọng văn: mô tả hệ thống *làm gì* và *chạy ra sao*, như một thiết kế sẽ được
thực thi. Không nói "đã làm / chưa làm / mất bao lâu". Mỗi khối gắn với một
tiêu chí chấm. (Khớp với code thật trong repo — xem flow-description.md.)

---

## SLIDE A — LUỒNG QUYẾT ĐỊNH CỦA ERIS
**(phục vụ: Tính khả thi 20đ + Công nghệ mới 8đ)**

**Tiêu đề:** Một bộ não điều hành quyết định từng lượt, rồi mới nói

**Luồng 5 bước:**

```
1. SỰ KIỆN          2. ROOT QUYẾT ĐỊNH     3. GỌI NĂNG LỰC
user_turn /         nói / im / nhớ /       capability chuyên môn
reminder_due        gọi capability         trả về dữ liệu + biên nhận
nhắc học            (loop nhiều bước)

        4. KẾT QUẢ VỀ ROOT          5. WRITER → DELIVERY → TTS
        quyết bước tiếp theo        diễn đạt → phát → tổng hợp giọng
        dựa trên biên nhận          (chỉ phát khi Root chốt move)
```

**Câu chốt dưới slide:**
Root sở hữu *ý nghĩa hội thoại*; Writer chỉ *diễn đạt*; Delivery/TTS chỉ *phát*.
Tách quyền quyết định khỏi quyền diễn đạt — thêm năng lực mới không phải viết
lại lõi.

**Chi tiết để nói miệng (không in lên slide):**
- Mỗi lượt, Root chạy một vòng lặp nhiều bước, mỗi bước chọn đúng một hành động:
  nói, im lặng, suy nghĩ tiếp, nhớ lại, hoặc gọi một năng lực chuyên môn.
- Mỗi hành động trả về một biên nhận (receipt) được nối vào bước kế — Root
  quyết định tiếp dựa trên bằng chứng, không bịa.
- Khi người dùng chen lời giữa chừng, hệ thống hủy đúng lượt đang xử lý và nhường.

---

## SLIDE B — TUTOR CẮM VÀO KIẾN TRÚC
**(phục vụ: Tính khả thi 20đ — slide mạnh nhất của bài)**

**Tiêu đề:** Tutor là một năng lực cắm vào bốn khớp nối có sẵn

**Sơ đồ khối:**

```
   UI / VOICE            CONVERSATION KERNEL         ROOT AGENT
   chat, bài tập,   →    sự kiện, biên nhận,    →    quyết intent, tool,
   file, giọng nói       vòng đời lượt nói           nói / im
                                                          │
                                                          ▼
   WRITER → TTS                              ┌──────────────────────────┐
   diễn đạt, giọng nói  ←──────────────      │  TUTOR CORE               │
                                             │  • LessonSession          │
   MEMORY / LEARNING STORE                   │  • LearnerModel           │
   mastery, bằng chứng,  ──────────────→     │  • EvidenceEvaluator      │
   lịch ôn (bền vững)                        │  • TeachingStrategy       │
                                             │  • ReviewPlanner          │
                                             └──────────────────────────┘
```

**Bốn khớp nối (in nhỏ dưới sơ đồ):**
1. **Đăng ký** — Tutor vào Capability Registry cạnh work / research / action.
2. **Gọi** — Root tự quyết gọi Tutor khi thấy cần dạy/đánh giá (không tự động chen).
3. **Biên nhận tư vấn** — Tutor trả đánh giá + nước đi dạy dưới dạng dữ liệu, không tự phát tiếng.
4. **Xác nhận đã dạy** — chỉ khi câu thực sự phát thành công mới ghi tiến độ học.

**Câu chốt dưới slide:**
Nguyên tắc: *Tutor không tự phát tiếng, không viết lại ý định. Root luôn chốt
hành vi.* Mô hình đề xuất — kernel deterministic commit.

---

## SLIDE C — TUTOR CORE LÀM GÌ (5 lớp)
**(phục vụ: Sáng tạo 20đ + Giải quyết vấn đề 20đ)**

**Tiêu đề:** Năm lớp biến "trả lời" thành "đồng hành học"

| Lớp | Nhiệm vụ |
|---|---|
| **LessonSession** | Giữ trạng thái một buổi dạy: đang ở bước nào, đã hỏi gì, đếm lượt — resume được sau khi đóng app |
| **LearnerModel** | Hồ sơ người học: nhịp, phong cách, mức nắm vững từng chủ đề, đường quên |
| **EvidenceEvaluator** | Chấm ngữ nghĩa câu trả lời tự do, chỉ ghi nhận "đã hiểu" khi đủ tin cậy |
| **TeachingStrategy** | Chọn nước đi sư phạm kế: hỏi, giải thích, phản ví dụ, kiểm tra — trong khung quyền có giới hạn |
| **ReviewPlanner** | Lập lịch ôn theo đường quên (spaced repetition) và chọn bước kế trên lộ trình |

**Câu chốt:**
Dữ liệu học (mastery / bằng chứng / lịch ôn) là kho bền vững, tách khỏi trí nhớ
hội thoại. Hành vi dạy ổn định theo luật, không phụ thuộc may rủi của model.

---

## GHI CHÚ XỬ LÝ CÁC SLIDE CŨ

- **Slide 10 cũ** (RootAgent trung tâm): gộp vào **Slide A**, bỏ dòng "INV-04
  xác nhận..." (đó là giọng báo cáo nội bộ, không hợp pitch).
- **Slide 11 cũ** (đề xuất Tutor Core): thay bằng **Slide B** — giữ sơ đồ nhưng
  đổi "XÂY MỚI" thành mô tả trung tính "năng lực cắm vào".
- **Slide 12-15 cũ** (đối chiếu INV/patch, 6 cổng kiểm chứng): đây là giọng
  audit nội bộ. Với pitch ý tưởng, nên chuyển thành **phụ lục** để trả lời phản
  biện, KHÔNG để trong 5 phút chính.
