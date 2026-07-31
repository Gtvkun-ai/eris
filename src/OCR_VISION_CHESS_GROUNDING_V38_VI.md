# OCR, vision và chess grounding v38

## Luồng evidence mới

1. Mỗi lượt chat đọc OCR/UIA cache tươi từ `ScreenEvidenceStore` và đưa vào grounding ở vai trò `ambient`.
2. Chat thường không cưỡng bức OCR và không chụp screenshot.
3. Khi user trỏ màn hình, router thử OCR/UIA trước. Nếu OCR đủ rõ, dùng text evidence ngay.
4. Nếu OCR mơ hồ nhưng request không bắt buộc phân tích hình/layout, runtime đặt `PendingVisionEscalation`.
5. Lượt chat kế tiếp consume escalation và gọi vision một lần nếu vẫn cùng cửa sổ hoặc cùng engagement.
6. Request trực tiếp về màu sắc, bố cục, hình ảnh vẫn được gọi vision ngay.

## Chess bridge

`ChessCompanionService.current_grounding_evidence()` xuất FEN, lượt đi, phase,
nước vừa đi và gợi ý thành source `chess_bridge` có provenance riêng.

Khi bridge còn tươi và câu user tiếp tục ngữ cảnh cờ như “nước nào”, “đi gì”,
“chỉ tui”, “ván này”, “bàn cờ”:

- `chess_bridge` trở thành primary source;
- OCR vẫn là ambient;
- vision bị bỏ qua vì extension đã cung cấp state có cấu trúc chính xác hơn ảnh.

Ở lượt không liên quan cờ, snapshot bridge vẫn nằm trong ambient evidence để giữ
continuity nhưng không được phép chen vào câu trả lời.

## Biến môi trường

```env
ERIS_CHAT_MAIN_VISION=0
ERIS_CHAT_OCR_VISION_ESCALATION_CONFIDENCE=0.62
ERIS_CHAT_VISION_PENDING_TTL_SEC=30
ERIS_VISION_COMPRESSOR=1
```

`ERIS_CHAT_MAIN_VISION=1` vẫn được giữ để debug/backward compatibility, nhưng
không nên bật trong runtime bình thường.
