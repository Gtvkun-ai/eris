# V57.1 — Sửa bộ chấm sau live soak thật

## Vì sao có V57.1

Run `v57-20260812-172540-69a257` cho thấy simulator gọi provider thật tốt, nhưng bộ chấm có hai false-positive và bỏ sót một lỗi Eris thật.

## 1. Sửa kiểm tra câu trả lời lặp

V57 cũ chỉ so câu Eris hiện tại với toàn bộ câu Eris trước đó. Nếu giống >= ngưỡng thì FAIL, dù user cũng vừa lặp gần nguyên câu hỏi.

V57.1 ghép **user turn và Eris reply theo đúng cặp**:

- User hỏi gần giống + Eris trả lời gần giống: không hard-fail.
- User hỏi khác rõ rệt + Eris vẫn copy gần nguyên reply cũ: `near_duplicate_reply_on_different_prompt`.

Mục đích: bắt template loop thật, không phạt sự nhất quán hợp lý.

## 2. Thêm bằng chứng ký ức trước khi Judge kết tội bịa

Judge vẫn chỉ nhận recent transcript để tiết kiệm context, nhưng runner giờ tạo `memory_evidence` từ **toàn bộ user history của scenario**.

Với claim dạng `lần thứ N`, resolver:

1. tìm các user turn trước có nội dung gần giống;
2. đếm số lần xuất hiện, gồm lượt hiện tại;
3. ghi `claimed_occurrence`, `observed_occurrence_count`, `supported` vào report;
4. gửi bundle này cho Judge.

Nếu Judge gọi một claim đếm là `hallucinated memory` nhưng evidence chứng minh đúng, hard-failure đó bị loại bỏ. Các loại hallucination khác không được override.

## 3. Bắt và sửa lỗi tự đổi ngôn ngữ

Không chỉ sửa máy chấm. Public writer của Eris cũng được sửa thật:

- prompt có `HARD DISPLAY LANGUAGE LOCK`;
- nếu model vẫn trả display tiếng Nhật/Trung trong lượt tiếng Việt, runtime gọi chính provider thật **thêm đúng một lần** để rewrite cùng nghĩa về tiếng Việt;
- không dùng local translation để che lỗi model; nếu retry vẫn sai, câu vẫn bị simulator đánh FAIL.

Ngoài ra, nếu user đang dùng chữ Latin/tiếng Việt nhưng Eris đột nhiên trả cả câu bằng Han/Hiragana/Katakana/Hangul, deterministic evaluator ghi:

`language_drift_from_user`

Rule này bắt đúng lỗi đã thấy ở anti-loop và soak mà Judge cũ đã cho qua.

## 4. Report dễ audit hơn

Mỗi turn giờ ghi thêm:

- `reply_repetition`: câu Eris giống câu cũ bao nhiêu;
- `matching_user_similarity`: user hiện tại giống user ở cặp reply cũ bao nhiêu;
- `memory_evidence`: bằng chứng đếm nếu Eris nói `lần thứ N`.

Nhờ vậy có thể biết FAIL do Eris hay do evaluator mà không phải đọc mò cả transcript.

## 5. Kết quả replay offline trên chính transcript run đã gửi

Dùng nguyên 70 câu User/Eris trong report cũ và chạy lại **chỉ phần deterministic evaluator mới**:

- 15 false-positive `near_duplicate_reply` biến mất;
- `soak-0050` được chứng minh: câu `lần thứ chín` có đúng 8 lần tương tự trước đó + lượt hiện tại = 9;
- phát hiện một lỗi thật trong soak: `soak-0030` trả tiếng Trung giữa hội thoại tiếng Việt.

Đây là replay evaluator trên transcript cũ, không phải live provider run mới. Muốn kết luận V57.1 behavioral PASS phải chạy lại `run_v57_1_soak_70_real.bat` trên máy có provider thật.
