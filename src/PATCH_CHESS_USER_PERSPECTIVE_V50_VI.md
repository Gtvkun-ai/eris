# PATCH CHESS USER PERSPECTIVE V50

Bản vá này sửa lỗi diễn giải evaluation khi người dùng cầm Đen.

## Quy ước

- `evaluation_cp` và `evaluation_label`: giữ tương thích ngược, luôn theo góc nhìn Trắng.
- `evaluation_cp_white`, `evaluation_label_white`: tên rõ ràng cho cùng chuẩn engine.
- `evaluation_cp_user`, `evaluation_label_user`, `user_position`: góc nhìn người dùng khi đã biết `user_side`.
- `advantage_side`: bên đang lợi thế (`white`, `black`, `equal`).

Tutor, Governor và Surface phải ưu tiên trường theo user. Nếu chưa biết người dùng cầm màu nào, chỉ được nói Trắng hoặc Đen đang hơn, không được gán lợi thế cho người dùng.

Stockfish vẫn chọn nước cho bên đang tới lượt; bản vá chỉ sửa lớp diễn giải công khai và provenance.
