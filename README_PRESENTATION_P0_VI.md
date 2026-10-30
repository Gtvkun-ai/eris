# Eris Presentation — P0 (29/10/2026)

**Đã làm:** Adapter cho `math_workspace` và `document_source`, giao thức `ArtifactEnvelope v1`, `PresentationIntent v1`, `RendererFeedback v1`, validation và JSON sidecar có ID ổn định. Không tạo loop mới, không thay Root/TTS/UDP cũ.

**Mặc định BẬT:** Không cần thêm biến môi trường hay chỉnh file cấu hình. Khi math tool hoặc committed document chạy, JSON bundle tự ghi dưới `logs/eris_artifacts/presentation_v1/*.json` (hoặc workspace đã được cấu hình trước). Đây là sidecar P0, chưa tự thay đổi cách Rich Chat render.

**Khôi phục khẩn cấp (chỉ khi gặp lỗi):** `ERIS_ARTIFACT_PROTOCOL_V1=0` sẽ ngừng ghi sidecar. Đây là công tắc dự phòng cho người phát triển, không phải bước cài đặt bắt buộc. Không cần sửa lịch sử hội thoại.

**Biên P0/P1:** Adapter toán chưa có `turn_id` thật từ Root thì tạo `job:<job_id>` và gắn `turn_binding=job_provisional`; document thiếu turn thì tạo `document:<id>`. **Không được công bố artifact đó như gắn vào conversation turn thật** cho tới khi P1 truyền turn_id chuẩn. P0 chưa có renderer ACK thực; UDP legacy ACK chỉ là trạng thái của Workspace cũ.

**P1 tiếp theo:** Nhận `artifact_refs` và turn_id từ Root, `PresentationRuntime` giữ state/revision, Rich Chat nhận event + trả ACK có thể kiểm chứng. Khi đó mới có thay đổi giao diện/hành vi đầu-cuối.

Kiểm thử P0: `python -m pytest -q src/tests/test_p0_artifact_protocol.py`.
