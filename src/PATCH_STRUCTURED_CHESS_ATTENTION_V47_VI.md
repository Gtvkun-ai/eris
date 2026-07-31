# ERIS Structured Chess Attention v47

Bản này thay đường cờ từ “extension gửi FEN rồi model tự đoán nên nói gì” thành một pipeline có typed attention:

1. **Extension là nguồn foreground có thẩm quyền**
   - Gửi thêm `player_side`, trạng thái tab và board focus.
   - Khi engagement cờ foreground đang hoạt động, OCR/window inventory không được tranh topic với cờ.

2. **Vai trò cờ được lưu và sửa giữa phiên**
   - Phân biệt `spectator`, `coach`, `opponent`, `companion`.
   - Câu sửa như “em làm khán giả, chỉ xem tui chơi” cập nhật ngay engagement hiện tại.
   - Spectator không tự đưa best move/hint khi người dùng chưa hỏi.

3. **Structured chess attention policy**
   - Xác định bên người dùng, bên vừa đi và actor là user/opponent.
   - Chấm `speech_priority` theo game start/end, evaluation swing, move quality, check, mate, capture, castle, promotion và actor.
   - Mọi nước vẫn được lưu vào state, nhưng autonomous chỉ được đánh thức ở nhịp đáng bình luận.

4. **Chess giữ độc quyền foreground**
   - Khi đang xem cờ, discovery, generic presence, private seed và screen/OCR anchor không được mở chủ đề khác.
   - Active chess dùng event-driven cadence; im lặng lâu không tự sinh câu xã giao ngoài ván.

5. **Surface nhận directive có cấu trúc**
   - Nhận `speech_reason`, `speech_act`, `actor`, `companion_mode`, `commentary_focus` và typed board state.
   - Surface chỉ viết câu; không tự đổi vai trò hay chuyển chủ đề.

## Kiểm thử

- 77/77 test trọng tâm cho chess, grounding, initiative, engagement và shared cognition passed.
- 589 test passed trong lượt suite rộng.
- 9 lỗi còn lại là baseline môi trường/source đầu vào: thiếu `body/`, thiếu `tools/`, và hai test ElevenLabs phụ thuộc quota tài khoản.
- Một test archive không collection được vì source đầu vào thiếu `tools.package_source`.
