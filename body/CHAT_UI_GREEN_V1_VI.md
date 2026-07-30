# Eris Chat UI xanh lá v1

## Đã thay đổi

- Khung chat chính được dựng lại thành panel hội thoại đầy đủ, tông xanh lá tối.
- Tin nhắn Eris nằm bên trái; tin nhắn người dùng nằm bên phải.
- Khi gửi tin, panel giữ nguyên thay vì đóng ngay.
- Trạng thái runtime `received`, `thinking_started`, `content_committed`, `audio_buffering`, `speaking` và `audio_playback_started` được hiển thị ngay trong panel.
- Có typing row tạm thời `Eris đang suy nghĩ···`; dòng này không được lưu như một tin nhắn.
- Sidebar `Hội thoại hôm nay` hiển thị số tin, chủ đề hiện tại và tối đa 5 mục người dùng vừa nhắc tới.
- Lịch sử trong ngày được lưu ở `user://eris_conversation_today.json`; sang ngày mới tự bắt đầu danh sách mới.
- Speech bubble của sprite 2D và Live2D đã tách thành hai component riêng:
  - 2D: bubble sáng, có đuôi chỉ về nhân vật.
  - Live2D: card tối độc lập trong Godot overlay, đặt cạnh cửa sổ model.
- Khi đổi body giữa 2D và Live2D giữa lúc đang nói, nội dung bubble hiện tại được chuyển sang presenter mới.
- Màu của runtime thinking pill cũng đổi sang xanh lá để đồng bộ.

## File thay đổi

- `body/UdpListener.cs`
- `body/UdpListener.Live2D.cs`
- `body/UdpListener.RuntimePresence.cs`
- `body/UdpListener.ConversationUi.cs` (mới)

## Cài đặt

Cách an toàn nhất là sao lưu thư mục `body`, sau đó chép đè bốn file ở trên vào `res://body/`.

Không cần sửa scene `udpListener.tscn`: code mới lấy `ChatPanel` có sẵn làm host, rồi dựng component mới lúc `_Ready()`.

## Luồng trạng thái

```text
Người dùng gửi tin
  -> UI thêm message của người dùng
  -> UI hiện “Eris đang suy nghĩ…” ngay lập tức
  -> backend gửi eris.stage lifecycle
  -> thinking row cập nhật theo backend
  -> text công khai đến
  -> UI thêm message của Eris + mở speech bubble đúng body
  -> audio_playback_started
  -> header hiển thị “Eris đang nói”
  -> audio_playback_done / done
  -> header trở về “Sẵn sàng”
```

Nếu backend không gửi lifecycle trong 45 giây, typing row tự thoát trạng thái chờ để panel không bị mắc kẹt vĩnh viễn. Vì phần mềm đã đủ ma quái mà không cần thêm một dấu ba chấm bất tử.
