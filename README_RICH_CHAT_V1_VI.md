# ERIS Rich Chat V1 — Thay tầng hiển thị, không vá công thức đơn lẻ

## Đã triển khai

**Vùng mới: cửa sổ Rich Chat chạy trên trình duyệt, kết nối Eris đang mở.** Đây không phải một chatbot khác: lịch sử lấy từ `_conversationEntries`, tin nhắn mới gọi lại `SendUserChatMessage` trên **main thread Godot**. Không thay Root, TTS, Memory, cognitive loop, socket 4243 hay Live2D.

- Mở qua nút **Rich Chat** trong thanh trên của cửa sổ Godot; trên **Windows**, mục mở lịch sử chat ở context menu của Eris và nút **Xem đầy đủ** ở bubble cũng mở Rich Chat mới.
- Local-only `127.0.0.1` trên cổng ngẫu nhiên, có token bí mật cho cả trang và API. Không gửi nội dung ra máy chủ web khác. Tự tắt server khi Eris thoát. Dùng `TcpListener`, không cần Windows URLACL.
- Lịch sử tin nhắn cũ **được dựng lại khi mở**, không cần tạo tài liệu V5/V6 hay gửi tin nhắn mới. Poll cục bộ tự cập nhật status/tin nhắn trong lúc Eris chạy.
- Markdown: tiêu đề, đoạn văn, chữ đậm/nghiêng/gạch ngang, quote, danh sách, link HTTPS, bảng, code fence có nút sao chép; phân tách đoạn nói dài để dễ đọc mà không sửa bản gốc.
- MathJax v3 SVG cục bộ: inline `$...$`, `\\(...\\)`, block `$$...$$`, `\\[...\\]` và chuyển một số tích phân Unicode dạng `∫₀¹ x dx = x²/2 |₀¹ = 1/2` sang biểu thức dựng toán thực.
- Prism cục bộ: syntax highlighting cho Python, JavaScript, TypeScript, JSON, C#, C/C++, Java, CSS, HTML và Bash. Giao diện responsive, sáng/tối, tìm nội dung, lọc ngày, copy tin nhắn/code.
- Không tải thư viện từ CDN; MathJax và Prism được **nhúng vào DLL** qua `EmbeddedResource` trong `Eris.csproj`. Giữ giấy phép bên trong `src/body/richchat/vendor`.
- Mục tiêu và nhắc nhở vẫn ở bảng Godot cũ; **phần chat** được đưa sang renderer đúng loại.

## Cách dùng

1. Sao lưu thư mục Eris hiện đang chạy. Giải nén bản full vào một thư mục riêng. Bản này kế thừa các bản chỉnh bubble và math trước đó.
2. Build lại Godot C# (dùng `build_dev_fast.bat` hoặc quy trình build dự án). `Eris.exe` cũ sẽ **không tự có Rich Chat**.
3. Chạy Eris, mở context menu chat hoặc mở panel Godot và nhấn **Rich Chat**. Trình duyệt mặc định mở trang local.
4. Thử một tin nhắn dài có `## Tiêu đề`, `$$\\frac{1}{2}$$`, bảng Markdown và ```python. Thử gửi từ ô nhập của Rich Chat: tin nhắn sẽ đi theo đúng luồng cũ của Eris.
5. Nếu trình duyệt báo không kết nối, xem `[RichChat]` trong Godot log; khởi động lại Eris. Nếu Rich Chat không thể mở, panel Godot cũ sẽ được dùng làm fallback.

## Kiểm thử đã chạy trong môi trường soạn bản

- `node --test src/body/richchat/tests/render.test.cjs` — 9/9 pass.
- Kiểm tra render bằng Chromium qua trang test nội bộ (không phải Godot runtime): MathJax sinh 9 phần tử công thức, bảng, code và đồ thị/biểu đồ SVG đều xuất hiện; đã tạo screenshot sáng/tối.
- Vẫn còn **chưa kiểm chứng**: build Godot .NET 8 trên Windows, HTTP server C# được chạy thật bởi Eris.exe, TTS và vòng đời ứng dụng. Môi trường hiện tại không có Godot/dotnet; screenshot được dựng với hội thoại giả lập để thử renderer, **không phải ảnh chụp app đang chạy**.

## Giới hạn V1 / mục tiếp theo

- Hiện là cửa sổ trình duyệt cục bộ, **chưa nhúng WebView2** vào Godot. Cách này cố ý giúp thay tầng render mà không động vào Life2D/TTS đang chạy.
- Markdown theo tập con an toàn, **chưa phải toàn bộ CommonMark/GFM** (chưa hỗ trợ danh sách lồng sâu, checkbox tương tác, ảnh đính kèm hoặc citation).
- Chưa có biểu đồ tương tác hoặc sandbox chạy code trong chat; để đạt đầy đủ mục tiêu này cần hợp đồng block/artefact và sandbox riêng. Không dùng `eval` cho code của LLM.
- Chưa tự đổi mọi ký hiệu toán Unicode sang LaTeX; tích phân có cận thông dụng được hỗ trợ, biểu thức khác cần chuẩn LaTeX.
- Chat vẫn cập nhật sau khi message được commit (không phải stream từng token), do runtime cũ phát public text sau TTS start.

## Rollback

Không cập nhật dữ liệu/hồ sơ người dùng: bản mới chỉ đọc store hội thoại và gửi vào luồng cũ. Nếu muốn quay về bản cũ, chạy lại bản Eris dự phòng. Có thể mở panel Godot từ các luồng planner/reminder như trước.

## Đồ thị và biểu đồ có dữ liệu rõ ràng

Ví dụ biểu đồ cột (nằm trong code fence `chart`):

~~~~chart
{"type":"bar","title":"Tiến độ","labels":["S1","S2","S3"],"values":[25,65,90]}
~~~~

Ví dụ đồ thị hàm số (nằm trong code fence `plot`):

~~~~plot
{"expression":"sin(x)","xmin":-6.28,"xmax":6.28}
~~~~

Các block được dựng thành SVG ở máy local; không chạy Python/JS do AI xuất ra. Biểu đồ loại `bar`/`line`; hàm hỗ trợ toán tử + - * / ^ và `sin cos tan sqrt log exp abs`, biến `x` và `pi`. Đồ thị phải được mô tả rõ trong nội dung để hiển thị; V1 chưa tự quyết định vẽ đồ thị từ một đoạn văn bình thường.
