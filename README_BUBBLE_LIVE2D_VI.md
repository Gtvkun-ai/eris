# Eris — Bubble Live2D Companion (29/10/2026)

Đây là bản sửa **source Godot C#** lấy từ `eris-ai-20261029_140824_164.zip`.
Thay diện mạo và cách trình bày bubble **chế độ Live2D**; UI bubble kiểu 2D cũ được giữ lại để giảm rủi ro.

## Thay đổi

- Bubble mới có nền xanh than, viền nhẹ, bo góc 23px, chữ sáng dễ đọc (16px), chấm trạng thái và nút đóng nhỏ.
- Chiều rộng tối đa 384px, điều chỉnh theo viewport; chiều cao theo nội dung thay vì cố định 500x174px.
- Đuôi thoại bám theo phía Eris đang đứng; ưu tiên cạnh phải/trái, có fallback nếu màn hình hẹp.
- Hiện/ẩn bằng fade + dịch dọc 8px, không đổi dữ liệu lời thoại.
- Bubble chỉ hiển thị đoạn ngắn, tối đa ~176 ký tự tùy màn hình. Khi câu dài, nó có nút **Xem đầy đủ ↗** mở lịch sử, tự bung toàn bộ câu dài tương ứng.
- Nếu có nhiều câu dài và TTS đang chạy, bubble theo câu đang được đọc nhưng không tô tối các câu khác.
- Trạng thái dịu hơn: `trò chuyện`, `đang nói…`, `vừa nói`, `giọng bị ngắt`.
- Text đầy đủ vẫn được commit vào lịch sử qua luồng hiện có; **không cắt nội dung gửi sang TTS**.
- Giữ nguyên quy tắc chờ `audio_start` phía Python để công bố text, không thêm đường phát lời mới.
- Bubble Live2D tự ẩn sau khoảng đọc (`BubbleReadSeconds`, mặc định 20 giây), nhưng không ẩn khi đang playback. `BubbleReadSeconds=0` giữ trạng thái không tự ẩn.

## File chỉnh

1. `src/body/UdpListener.SpeechBubbleUi.cs` — giao diện Live2D mới (file mới).
2. `src/body/UdpListener.cs` — kết nối presenter với TTS, preview và timer.
3. `src/body/UdpListener.Live2D.cs` — vị trí, neo đuôi thoại, fallback màn hình hẹp.
4. `src/body/UdpListener.ConversationUi.cs` — đồng bộ khi đổi renderer, lịch sử đầy đủ.

## Áp dụng

1. **Sao lưu source và bản chạy Eris hiện có**.
2. Dùng `eris_bubble_live2d_full.zip` làm source hoàn chỉnh **hoặc** giải nén `eris_bubble_live2d_patch.zip` vào thư mục cha chứa `eris/` (đúng phiên bản source trong ZIP đầu vào).
3. Cần build lại Godot C# / Eris, không thể chỉ thay `.cs` trong file `.exe` đã đóng gói.
4. Nếu dùng pipeline build của repo, kiểm tra `.venv`, Godot .NET SDK và môi trường Windows, sau đó chạy `build_dev_fast.bat`. Pipeline này có thể cần thêm dependencies/config riêng của máy.
5. Khởi động Eris, chuyển sang Live2D và thử các lượt hội thoại ngắn/dài.

## Checklist kiểm thử trên Windows

- Lời 1 câu ngắn: bubble nhỏ, bo góc và fade, không cắt chữ.
- Lời 2–3 câu tổng cộng <=176 ký tự: đủ nội dung, không dim chữ.
- Lời dài >176 ký tự: hiện `Xem đầy đủ`, nút dẫn đến message gốc; >450 ký tự được mở bung trong history.
- Khi `audio_start`: status `đang nói…`, bubble không mất khi audio đang phát.
- Khi `audio_done`: status `vừa nói`, hết thời gian đọc thì tự ẩn.
- Đổi Live2D ↔ 2D khi bubble còn hiện: chế độ 2D phải giữ **toàn bộ** text.
- Kéo nhân vật sang hai mép desktop và thử màn hình hẹp: bubble không tràn viền, tail đổi hướng.
- Bấm `×`: chỉ ẩn bubble, không làm mất history và không dừng TTS.
- Bấm `Xem đầy đủ`: mở panel history; không tạo lượt AI mới.

**Trạng thái kiểm chứng:** đã kiểm tra cấu trúc file/ngoặc và luồng kết nối tĩnh. Chưa biên dịch Godot C# và chưa thử trên desktop Live2D thực tế do môi trường xuất gói không có Godot/.NET. Nếu Godot báo lỗi compile hoặc layout, cần xử lý theo log trên máy chạy.
