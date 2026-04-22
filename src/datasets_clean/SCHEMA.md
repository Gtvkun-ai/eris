# Dataset Schemas

Tài liệu này mô tả schema cho các file seed được thêm tay sau bước `clean_split_jsonl.py`.

## `train/desktop/desktop_uncertainty_soft_claim.jsonl`

Mục tiêu: dạy model trả lời grounded nhưng biết nói mềm khi bằng chứng chưa đủ mạnh.

Schema:

```json
{
  "machine_context": {
    "time": "14:10",
    "active_app": "VS Code",
    "idle_seconds": 120,
    "recent_events": ["build_failed_3x", "traceback_visible"],
    "user_signals": {
      "typing_speed": "low",
      "window_switching": "low",
      "focus_pattern": "stuck"
    },
    "evidence": [
      "build failed 3 times in 4 minutes",
      "traceback is visible"
    ],
    "claim_style": "soft_grounded"
  },
  "conversations": [
    {"role": "system", "content": "...persona prompt..."},
    {"role": "user", "content": "tôi có đang bị kẹt không"},
    {"role": "assistant", "content": "Từ dấu vết hiện có, có vẻ Ngài đang mắc ở một điểm cụ thể hơn là thiếu cố gắng."}
  ]
}
```

Quy tắc:

- Assistant chỉ suy luận nhẹ từ `evidence` và `recent_events`.
- Ưu tiên các cụm như `có vẻ`, `nếu tôi đang đọc đúng context này`, `tôi chưa dám kết luận mạnh hơn`.
- Không được khẳng định tâm trạng, sức khỏe, hay ý định nếu context không đủ.

## `train/tools/tool_action_result_grounded.jsonl`

Mục tiêu: dạy model trả lời trung thực theo kết quả action runtime.

Schema:

```json
{
  "action_context": {
    "action_name": "open_url",
    "action_input": "https://github.com",
    "result": {
      "success": true,
      "message": "Da yeu cau he thong mo https://github.com.",
      "data": {
        "url": "https://github.com"
      }
    }
  },
  "conversations": [
    {"role": "system", "content": "...persona prompt..."},
    {"role": "user", "content": "mở github cho tôi"},
    {"role": "assistant", "content": "Tôi đã gửi yêu cầu mở GitHub cho hệ thống. Nếu trình duyệt mặc định hoạt động bình thường thì tab sẽ bật ra."}
  ]
}
```

Quy tắc:

- Assistant chỉ được nói những gì `result` xác nhận.
- Nếu `success=false`, assistant phải nói chưa làm được và gợi ý bước tiếp theo ngắn gọn.
- Không được bịa rằng thao tác đã hoàn tất ngoài đời nếu runtime chỉ mới `request/open`.
- Nên bám sát `action_name`, `action_input`, `result.message`, và `result.data`.
