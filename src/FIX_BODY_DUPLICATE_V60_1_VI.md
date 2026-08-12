# V60.1 — Sửa lỗi Body C# bị compile trùng

## Triệu chứng
Visual Studio Code/Godot hiển thị hàng nghìn lỗi C# dạng:

- `already contains a definition for ...`
- `already defines a member called ... with the same parameter types`

Các lỗi nổi bật xuất hiện ở `src/body/BodyAudioController.cs`, `src/body/ErisProcessManager.cs` và các partial `UdpListener.*`.

## Nguyên nhân
Body C# chính của project nằm ở `<project>/body/`. Gói source Brain lại chứa thêm một cây `src/body/`, khiến Godot/.NET nhìn thấy hai bản cùng khai báo các class toàn cục như `BodyAudioController`, `ErisProcessManager`, `UdpListener`, v.v.

Ngoài ra, `src/integration/body_contracts/UdpListener.MemoryPanel.cs` từng là bản sao byte-for-byte của Body Memory Panel. Vì phần integration nằm dưới `src`, file `.cs` này cũng có thể bị project glob đưa vào compile.

## Cách sửa trong gói này

1. Loại `src/body/` khỏi source package. Body runtime chuẩn phải ở `<project>/body/`.
2. Đổi các C# fixture trong `src/integration/body_contracts/` sang đuôi `.cs.fixture.txt` để test vẫn đọc được nội dung nhưng compiler không coi chúng là source C#.
3. Cập nhật các Python test fallback sang tên fixture mới.
4. Thêm `fix_body_duplicate_compile.bat` để dọn bản `src/body` cũ trên máy một cách có kiểm tra và backup.

## Chạy trên project thật

Đặt nội dung source này vào `<project>/src/`, sau đó chạy:

```bat
src\fix_body_duplicate_compile.bat
```

Script chỉ dọn `src/body` nếu xác nhận `<project>/body/UdpListener.cs` tồn tại. Nó backup thư mục cũ trước khi xóa khỏi đường compile.

Sau đó xóa cache build Godot/C# nếu IDE còn giữ lỗi cũ, rồi mở lại project/build lại.

## Lưu ý
Không copy lại `src/body` vào project. Nếu cần sửa UI/Body, sửa cây canonical `<project>/body/`.

## Kiểm tra trùng class sau khi dọn

Có thể chạy:

```bat
python src\tools\check_body_duplicate_compile.py .
```

Nếu không còn bản Body bị nhân đôi giữa `body/` và `src/`, script trả `[OK]`.
