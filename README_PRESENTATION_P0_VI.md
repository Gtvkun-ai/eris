# Eris Presentation — P0 (29/10/2026)

**Đã làm:** Adapter cho `math_workspace` và `document_source`, giao thức `ArtifactEnvelope v1`, `PresentationIntent v1`, `RendererFeedback v1`, validation và JSON sidecar có ID ổn định. Không tạo loop mới, không thay Root/TTS/UDP cũ.

**Bật thử:** thêm `ERIS_ARTIFACT_PROTOCOL_V1=1` vào biến môi trường trước khi mở Eris. Khi math tool hoặc committed document chạy, JSON bundle được ghi dưới `logs/eris_artifacts/presentation_v1/*.json` (hoặc đường dẫn `ERIS_ARTIFACT_WORKSPACE`). Bật cờ không tự mở Rich Chat mới hoặc thay cách render.

**Tắt/rollback:** `ERIS_ARTIFACT_PROTOCOL_V1=0` (mặc định), không ghi sidecar. Không cần sửa lịch sử hội thoại. Xóa `presentation_v1/` nếu muốn dọn output thử nghiệm.

**Biên P0/P1:** Adapter toán chưa có `turn_id` thật từ Root thì tạo `job:<job_id>` và gắn `turn_binding=job_provisional`; document thiếu turn thì tạo `document:<id>`. **Không được công bố artifact đó như gắn vào conversation turn thật** cho tới khi P1 truyền turn_id chuẩn. P0 chưa có renderer ACK thực; UDP legacy ACK chỉ là trạng thái của Workspace cũ.

**P1 tiếp theo:** Nhận `artifact_refs` và turn_id từ Root, `PresentationRuntime` giữ state/revision, Rich Chat nhận event + trả ACK có thể kiểm chứng. Khi đó mới có thay đổi giao diện/hành vi đầu-cuối.

Kiểm thử P0: `python -m pytest -q src/tests/test_p0_artifact_protocol.py`.
