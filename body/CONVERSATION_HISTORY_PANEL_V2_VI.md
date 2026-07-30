# Conversation History Panel v2

Bản này chỉ sửa panel **Lịch sử hội thoại**. ChatPanel cũ vẫn giữ nguyên và tiếp tục dùng để nhập tin nhắn.

## Các lỗi đã sửa

- Thêm `ConversationHistoryPanel` vào `UpdateMousePassthrough()`. Trước đây khi chỉ mở lịch sử, overlay vẫn bật click-through nên nút đóng, cuộn và click trong panel lúc được lúc không.
- Làm lại mouse routing theo quy ước của các panel ổn định khác:
  - panel chính bắt chuột;
  - phần trang trí dùng `MouseFilter.Ignore`;
  - `ScrollContainer` và nút đóng dùng `MouseFilter.Stop`;
  - chỉ vùng header mới bắt đầu kéo panel.
- Bỏ kích thước cứng 360/330 px của từng message bubble. Bubble co theo chiều rộng thực tế nên không còn tràn hoặc ép layout trên màn hình hẹp.
- Panel tự co theo viewport, ẩn sidebar khi không đủ chỗ và cập nhật lại khi kích thước cửa sổ thay đổi.
- Thêm empty state, sidebar có scroll riêng, giới hạn số dòng của topic để nội dung không đè footer.
- Khi mở panel, panel được đưa lên trước, cập nhật mouse passthrough ngay và cuộn xuống cuối.
- Nếu đóng panel lúc đang kéo, drag state được hủy sạch.
- Chống ghi trùng phản hồi chỉ trong cửa sổ 5 giây. Cùng một câu được Eris nói lại sau đó vẫn được lưu.
- Reset đúng khi sang ngày mới và ghi file JSON bằng file tạm rồi thay thế để giảm nguy cơ file lịch sử bị dở dang.

## File thay đổi

- `body/UdpListener.ConversationUi.cs`
- `body/UdpListener.cs`

Không thay đổi backend trong `src`.
