# Scripted Take: reaction arc có cảm giác đang hiểu

Beat `tutor_reaction` không đọc nguyên văn kết quả Tutor. Nó dựng một đường phản ứng:

1. `lead_in`: phản ứng cực ngắn, ví dụ `À...`.
2. `expectation`: điều Eris vừa nghĩ sai hoặc chưa đủ trước khi biết đáp án.
3. `locked_summary`: cách Eris nói lại phần kiến thức đã kiểm tra.
4. `afterthought`: nhận xét nhỏ mang giọng Eris, không thêm dữ kiện mới.

Ví dụ:

```json
{
  "kind": "tutor_reaction",
  "lead_in": "À...",
  "expectation": "Tôi cứ tưởng ánh sáng ấy chỉ là một sản phẩm phụ.",
  "locked_summary": "Nhưng ở một số loài, nó có thể thu hút côn trùng; rồi những vị khách đó lại góp phần mang bào tử đi xa hơn.",
  "afterthought": "Một cái biển quảng cáo sống. Khá gian, với một cây nấm.",
  "response_hold_ms": 480,
  "pause_after_ms": 920,
  "close_panel": true
}
```

## Quy tắc dùng khi quay chính thức

- Giữ `Tutor` làm đạo cụ tra cứu nhưng dùng `locked_summary` đã kiểm tra để lời thoại ổn định giữa nhiều take.
- `fallback_answer` chỉ chứa evidence, không chứa giọng diễn.
- Không đặt `À. {{tutor_answer}}` trong bản quay chính thức. Runtime vẫn hỗ trợ cú pháp cũ để tương thích, nhưng đã dọn bullet, link và dòng nguồn trước TTS.
- `use_model_rewrite: true` hợp cho rehearsal hoặc chủ đề động. Take chính thức nên khóa câu nói để API không tự đổi nhịp và tính cách giữa hai lần quay.
- `expectation` không phải lời thú nhận cảm xúc. Nó là dấu vết của một giả định vừa được cập nhật, giúp reaction có diễn tiến nhận thức nhìn thấy được.

## Đồng bộ sân khấu

Khi TTS hoạt động, text, motion và `body_timeline` chỉ được gửi sang Godot tại `audio_start` của từng segment. Stage bus vẫn nhận trước toàn bộ segment để queue và debug. Nhờ vậy bubble không nhảy tới câu cuối và body không phát nhiều cue cùng lúc.
