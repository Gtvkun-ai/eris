# ERIS — Runtime Reconstruction (bản tích hợp lớn, tiếng Việt)

## Mục đích

Sửa lỗi kiến trúc *“giải bài dài làm nghẽn cái miệng”* mà không thêm một AI có quyền nói cạnh tranh với Root.

**Đã thay đổi:** Work Lane có model inference theo bước + tool thật + sự kiện SQLite, Root giao việc/đọc tiến độ trong lúc tiếp tục chat, Workspace nhận tiến độ từ worker, `document_source` không nhập chung vào speech. Root có thể tự giải ngắn và nói thẳng; không bắt buộc gọi tool.

## File bàn giao

- **Full Source:** toàn bộ source mới nhất người dùng gửi cùng các chỉnh sửa.
- **Overlay:** chỉ các file mới/sửa trên chính `eris-ai-20261028_224738_047.zip`. Giải nén tại gốc repo Eris; không áp lên bản V5 cũ.

## Chạy probe và test (PowerShell)

```powershell
cd <duong-dan-toi-thu-muc-eris>
py -m pip install -r requirements-artifact-workspace.txt
$env:PYTHONPATH='src;.'
py tools/parallel_work_probe.py
py -m pytest src/tests/workspace/test_parallel_work_reconstruction.py -q
```

Muốn nhìn artefact trong Godot khi app đã được build và chạy:

```powershell
$env:ERIS_ARTIFACT_WORKSPACE = "$PWD\logs\parallel_work_probe\artifacts"
py tools/parallel_work_probe.py --send
```

Với runtime thật, Root có thể gọi:

```json
{"kind":"use_capability","capability":"action","arguments":{"action_id":"parallel_work","arguments":{"operation":"start","task":"Giải bài toán, kiểm chứng bằng tool và viết lời giải từng bước"}}}
```

Sau đó `operation=status` với `job_id`, hoặc `operation=recent`. `operation=resume` (kèm `answer`) khi job chờ người dùng; `operation=cancel` để hủy. Result `start` là *đã nhận việc*, tuyệt đối không có nghĩa là giải xong.

## Điều cần lưu ý

1. Conversation không đợi Work Worker, nhưng backend chỉ có 1 inference slot vẫn có thể làm chat trễ do hạ tầng. Cần đo trên máy thật.
2. Work Worker không có SpeechAuthority. Bài giải/progress sẽ hiện ở Artifact Workspace, **không tự tạo câu thoại**. Root đọc tiến độ từ context và tự chọn lúc nói.
3. `document_source` là nguồn Markdown đầy đủ Root quyết định; `say` là brief. Nếu writer không tạo speech riêng cho lượt có tài liệu, runtime từ chối candidate, không đưa code/LaTeX sang TTS.
4. V6 Presenter model và Writer-review model giờ mặc định tắt (`ERIS_V6_PRESENTATION_AGENT=0`, `ERIS_V6_WRITER_REVIEW=0`). Mặc định một semantic owner; có thể bật thủ công để thử.
5. Godot build và hành vi Root/LLM live chưa được kiểm tra trong môi trường tạo gói. **Không gọi đây là 100% tự chủ hoặc giao diện đã xong.**
6. Chú thích code và tài liệu thay đổi đều bằng tiếng Việt. Bản này ưu tiên cơ chế làm việc thật thay vì đổi số phiên bản.

## Điểm nghiệm thu trên máy bạn

Bắt đầu một bài khó → Root giao work job và nói một câu tự nhiên → Work Lane tạo tiến độ lên Panel → user hỏi “đến đâu rồi?” thì Root đọc dữ liệu thật → user đổi chủ đề thì chat vẫn phản hồi → khi kết quả xong Root tự chọn có nói/ghi thêm gì. Khi build Godot thành công và qua bài này mới đánh dấu trải nghiệm live đạt.

Chi tiết: `docs/knowledge/2026-10-28-parallel-work-runtime-reconstruction.md`.
