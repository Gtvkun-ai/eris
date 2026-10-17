# ERIS: SCRIPT THUYẾT TRÌNH (khớp dàn 12 slide trong LUONG-KY-THUAT-SLIDE.md)

Lời nói nằm trong các dòng bắt đầu bằng `>`. Chỉ đếm các dòng đó. `[…]` là một nhịp ngừng.
Số liệu bên ngoài lấy từ TAC-DONG-BANG-CHUNG.md. Muốn nói số nào thì xem nguồn trong file đó.

**Thời lượng:** xem mục "Đếm từ" cuối file. Tốc độ 215 từ mỗi phút là con số tôi giả định, chưa đo.
Bấm giờ đọc thật một lần rồi chỉnh.

---

## Slide 1 · Bìa (Eris nói một câu trước)

> Kính chào ban giám khảo. Thứ các thầy cô vừa nghe là Eris, một nhân vật có giọng nói và tính cách. Nhưng điều em muốn các thầy cô nhớ không phải khuôn mặt này. Mà là bộ máy phía sau nó.

## Slide 2 · Ba lỗi của AI tự chủ

> Một AI chỉ trả lời thì khó hỏng. Nhưng một AI tự nói, tự nhắc, tự quyết thì có ba cách làm hỏng buổi học. […]
> Một: nói đè. Học sinh đang nghĩ thì nó chen vào, hoặc người học ngắt lời mà nó vẫn đọc tiếp. Hai: nói dối. Nó bảo "đúng rồi, em làm tốt" trong khi chưa chấm gì. Ba: im lặng. Máy bận hay một API lỗi là nó đơ giữa buổi. […] Eris được xây để chặn đúng ba lỗi này.

## Slide 3 · Vấn đề thật và định vị

> Nhưng vấn đề lớn nhất của gia sư AI không phải dạy dở. Một thử nghiệm hai năm ở mười tám trường cấp hai tại Tennessee cho thấy: chín mươi sáu phần trăm học sinh có thử Khanmigo, nhưng học sinh điển hình chỉ nhắn nó khoảng một phần ba số ngày luyện tập. Kết quả học không hơn nhóm không dùng AI. […]
> Gia sư giỏi mà không ai mở thì vô nghĩa. Eris đi hướng ngược lại: ở lại, chủ động, có cá tính.

## Slide 4 · Luồng một lượt nói

> Đây là đường đi của một câu nói. Kernel lập tức tăng một con số gọi là generation, nghĩa là mọi thứ của lượt trước hết hiệu lực. Ngữ cảnh được ghép bằng code, không gọi model. […]
> Rồi tới Root, bộ não duy nhất được quyết. Nó chỉ quyết ý, không viết câu. Writer mới viết thành lời, chữ tiếng Việt để hiện, giọng tiếng Nhật để nói. Trước khi phát, hệ thống kiểm lại còn đúng lượt không. Mọi lời nói chỉ ra qua một cửa duy nhất, và phát xong thì có biên nhận quay về.

## Slide 5 · Root loop

> Phóng to vào Root. Mỗi bước nó chỉ làm đúng một việc: nhớ lại, gọi gia sư, nghĩ thêm, hay chốt. Kết quả quay về kèm biên nhận rồi mới sang bước sau. […]
> Và nó có phanh: tối đa mười hai bước, hai bước liền không tiến triển là dừng, nghĩ thầm tối đa hai lần. Một AI tự chủ mà không có phanh thì không ai dám để nó tự nói.

## Slide 6 · Chen lời

> Khi người học chen lời, Eris không cần khóa hay hủy từng tác vụ. Kernel chỉ tăng generation từ bảy lên tám. Câu đọc dở của lượt cũ, so sánh thấy không khớp, tự bị loại. Một con số, và cả lượt cũ hết hiệu lực.

## Slide 7 · Định nói ≠ đã nói ≠ đã dạy

> Đây là điều em tâm đắc nhất. Định nói, đã nói và đã dạy là ba trạng thái khác nhau. Một câu đi từ đang chuẩn bị, vào hàng đợi, đang phát, rồi mới tới đã phát xong. Bị ngắt thì thành đã hủy và không tự phát lại. […]
> Nếu hệ thống sập giữa chừng, nó ghi là không xác nhận được, chứ không giả vờ đã phát. Eris chỉ ghi "đã dạy" khi biên nhận báo phát thành công. Nó không tin lời model tự nhận.

## Slide 8 · Lane

> Phía sau có hơn chục luồng nghĩ chạy nền, không luồng nào được nói, chúng chỉ đề xuất. Mỗi lời gọi model được xếp làn theo vai trò. Làn bắt buộc, gồm Root, gia sư và Writer, không bị cắt khi máy bận. Làn nền thì hoãn, gộp hoặc bỏ. […]
> Bài học này chúng em trả giá thật. Một bước kiểm bắt buộc trước khi phát từng bị xếp nhầm vào làn nền chỉ vì mang nhãn cũ. Máy bận, hệ thống bỏ luôn bước đó, và Eris im lặng. Chúng em sửa bằng một luật: vai trò được xét trước nhãn.

## Slide 9 · Learning kernel

> Còn gia sư thì sao? Model đề xuất cách dạy, nhưng không được ghi gì vào hồ sơ học. Đề xuất phải đi qua một khung: mỗi pha dạy chỉ cho phép vài loại câu, có giới hạn số câu, và câu hỏi gợi mở bắt buộc chờ người học trả lời. […]
> Rồi một bộ máy có luật mới được ghi. Câu trả lời tự do phải được chấm đủ tin cậy, ngưỡng là không phẩy sáu tám. Writer không bao giờ cầm đáp án. Nên một câu bịa của model không thể làm hỏng hồ sơ của người học.

## Slide 10 · Tác động và giao điểm

> Vậy thị trường ở đâu? Nhân vật có cá tính thì giữ được người. Neuro-sama, một VTuber AI, đầu năm 2026 là kênh Twitch có nhiều người đăng ký trả phí nhất, hơn một trăm sáu mươi nghìn, gấp hơn hai lần kênh đứng thứ hai. Theo Adweek, Duolingo đi cùng chiến lược nhân vật cú, và người dùng hằng tháng tăng từ bốn mươi triệu lên hơn một trăm mười triệu. […]
> Nhưng nhân vật thì không dạy có bằng chứng, còn gia sư có cấu trúc thì học sinh bỏ. Eris đứng giữa: nhân vật người ta muốn quay lại, đặt trên bộ não dạy học có luật.

## Slide 11 · Bộ ba và lộ trình

> Nhân vật giữ người ở lại. Learning kernel khiến họ tiến bộ thật. Kiến trúc cho phép cắm thêm: nhiều môn, chấm ảnh bài làm, nhắc học nhiều ngày, mỗi thứ vào khớp nối có sẵn và giữ nguyên các luật đã nói. […]
> Các nhóm khác ghép một con AI từ đồ có sẵn và được một thứ. Chúng em làm cả ba, và tự xây từ đầu.

## Slide 12 · Chốt

> Model rồi sẽ thay. Ba lời hứa thì ở lại: không nói đè, không nói dối, không im lặng. […]
> Chúng em không hỏi AI này trả lời có giỏi không. Chúng em hỏi: làm sao để một AI tự chủ hành động mà vẫn trung thực, biết nhường, và lớn lên mà không sụp đổ. Các nhóm khác xây một câu trả lời. Chúng em xây một cách nghĩ. […] Em cảm ơn ban giám khảo.

---

## Ghi chú nhịp

- Ba kịch bản sống (bí bài, muốn trốn, khoe xong) nên chạy **demo thật** hoặc video ngắn ở slide 10, không đọc lên. Nếu không có demo thì bỏ cả ba, không chèn vào lời.
- Nếu lố giờ, cắt theo thứ tự: (1) gộp slide 6 vào slide 5 bằng một câu; (2) bỏ câu "Kết quả học không hơn nhóm không dùng AI" ở slide 3; (3) bỏ câu Duolingo ở slide 10.
- Không cắt: slide 2, chuyện im lặng ở slide 8, câu "định nói ≠ đã nói ≠ đã dạy", số Khanmigo ở slide 3, câu chốt.
- Slide 7 và 9 dùng ký hiệu và số: đọc "khác" cho ≠, đọc "không phẩy sáu tám" cho 0,68.
- Hai chỗ chọc nhóm khác (slide 11 và 12). Một chỗ ở slide 12 là đủ nếu thấy nặng; bạn quyết.

## Đếm từ

968 từ trong các dòng lời nói (bỏ `[…]`), đếm bằng script ngày 16/10/2026. Tiếng Việt viết mỗi âm tiết một từ nên số từ gần bằng số âm tiết.
Ở 215 từ mỗi phút (giả định) là 4,5 phút, còn dư khoảng 30 giây cho demo giọng ở slide 1 và nhịp ngừng.
Nếu bạn đọc chậm hơn 190 từ mỗi phút thì sẽ vượt 5 phút: dùng thứ tự cắt ở mục Ghi chú nhịp.
