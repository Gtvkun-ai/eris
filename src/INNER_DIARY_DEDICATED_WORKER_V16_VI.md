# INNER DIARY DEDICATED WORKER V16

## Mục tiêu

Giữ Inner Diary như một tính năng riêng đúng nghĩa và giao việc viết nhật ký cho đúng **một DeepSeek worker hiện có**. Không tạo thêm role mới chỉ để sơ đồ kiến trúc trông đông đúc.

## Owner

- Owner runtime: `private_mind.inner_diary`
- Worker mặc định: DeepSeek role `inner`
- Có thể chọn một role đã tồn tại bằng:

```env
ERIS_INNER_DIARY_WORKER_ROLE=inner
```

Các role hợp lệ vẫn là catalog hiện có:

```text
companion, surface, observer, critic, inner, style, research
```

Role không hợp lệ tự rơi về `inner` và ghi warning.

## Luồng dữ liệu

```text
private-mind digest đã rút gọn
        ↓
InnerDiaryWriter
        ↓
LlmService.diary_client
        ↓
một DeepSeek worker được chọn
        ↓
eris.inner_diary.v2
        ↓
Inner Diary panel
```

`diary_client` tách khỏi `inner_client`. Các evaluator, synthesizer hoặc worker khác không được âm thầm viết diary hộ.

## Không fallback chéo lane

Mặc định:

```env
ERIS_INNER_DIARY_ALLOW_FALLBACK=0
```

Khi diary worker chưa cấu hình hoặc lỗi, renderer giữ bản cache gần nhất hoặc dùng dữ kiện thô. Hệ thống không mượn companion, critic hay một provider khác rồi ghi ownership sai.

Có thể bật fallback cũ một cách chủ động bằng `ERIS_INNER_DIARY_ALLOW_FALLBACK=1`, nhưng đây là chế độ tương thích, không phải đường chạy chuẩn.

## Contract hiển thị

Digest phát:

```json
{
  "generated_at": 0,
  "inner_diary_contract": {
    "schema": "eris.inner_diary.v2",
    "owner": "private_mind.inner_diary",
    "writer": {
      "owner": "deepseek_worker",
      "role": "inner",
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "configured": true
    }
  },
  "inner_diary": {
    "title": "Inner Diary",
    "sections": [],
    "memory_echo": {},
    "writer": {}
  }
}
```

Panel giữ năm ô quen thuộc:

- Suy nghĩ hiện tại
- Suy nghĩ tương lai
- Đang bận tâm
- Phân tích gần đây
- Muốn nói

## Memory Echo

`memory_echo` chỉ được tạo khi `evidence_dossier.memory_hits` có dữ liệu. Nó mang theo `evidence_id` và `source`. Open loop hoặc discovery candidate không được giả làm ký ức.

## Quyền riêng tư

Worker chỉ nhận digest đã rút gọn và schema đầu ra. Panel không nhận raw chain-of-thought, prompt nội bộ hoặc nhật ký suy luận theo token.
