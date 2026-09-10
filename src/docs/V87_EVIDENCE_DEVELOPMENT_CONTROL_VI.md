# V87 — Evidence & Development Control

## Mục đích

V86 đã trả lời được “ERIS đang ước lượng năng lực của user ra sao?”. V87 đóng phần trust còn thiếu bằng hai câu hỏi:

1. **Tại sao ERIS nghĩ vậy?** — panel hiển thị evidence kỹ thuật gần đây đã sanitize.
2. **Nếu ERIS sai thì sao?** — user có quyền correction/reset trực tiếp từ Desktop panel.

V87 đồng thời biến recommendation dài hạn thành vòng phát triển user-controlled:

```text
Capability snapshot
      ↓
Recommendation
      ↓ user chọn
Development goal
      ↓
Task/evidence thật
      ↓
Progress
      ↓
Complete / stop / chọn lại
```

## Evidence projection

`capability_projection.py` chỉ chiếu các note runtime do ERIS tự sinh; không đưa raw chat/source lên UI. Mỗi kỹ năng chỉ hiển thị tối đa vài evidence gần nhất.

Thiếu evidence vẫn phải hiển thị **Chưa đủ dữ liệu**, không biến default model value thành % giả.

## User correction semantics

- `confirmed`: acknowledgement, không mutate skill level.
- `already_knew`: self-report/correction, hạ confidence nhẹ, không tăng mastery.
- `wrong`: correction mạnh hơn, hạ confidence estimate.
- `reset`: reset riêng skill estimate.

Điểm cốt lõi: user correction sửa **belief của ERIS**, không phải tạo một “điểm thật” mới về user.

## Development goals

User chỉ theo dõi tối đa 3 mục. Goal luôn lấy baseline tại thời điểm bấm Theo dõi và đo **delta evidence** sau đó, không lấy tổng lịch sử rồi báo hoàn thành ngay.

Metric hiện hỗ trợ:

- evidence count của nhóm kỹ năng;
- demonstrated count của tool;
- signal verification trong 30 ngày.

Goal tự complete khi delta đạt target. Không có background scheduler, notification hay homework engine.

## Security boundary

Mutation chỉ đi qua `capability_panel_request` trên kênh Desktop runtime hiện hữu. HTTP observer link không được mở write API mới.

Không có đường:

```text
Capability Panel → GitPilot command
Capability Panel → terminal
Capability Panel → write file
Capability Panel → approval
```

## File chính

- `src/runtime/development_control.py`
- `src/runtime/capability_projection.py`
- `src/runtime/engineering_mentor.py`
- `src/runtime/incoming_protocol_runtime.py`
- `src/body/UdpListener.CapabilityPanel.cs`
