# Eris P2 — Identity → Executive → Work → Outcome (CHANGE-ONLY)

**Nền bắt buộc:** Eris Runtime Reconstruction + bản vá P0 + bản vá P1, theo đúng thứ tự. 
**Đây là gói cập nhật mã nguồn, không phải Full Source.**

## Kết quả đã kiểm chứng

- Subject Core tạo `PendingIntention` từ động cơ sẵn có.
- Trong autonomous heartbeat, `IdentityGoalDriver` dùng **MindLoop và ExecutiveCortex đang có** để chuẩn bị/finalize lựa chọn `pursue_goal`; nó không tự làm semantic selector thứ hai.
- Kiểm chứng commit thật bằng `decision.arguments.executive_commit`, bao gồm `commit_id`, `source`, `selected_proposal_ref`. Chỉ winner đúng goal mới được ghi vào `GoalEventLedger`.
- Goal ở trạng thái `active` tự được giao cho singleton `UnifiedAgentSessions`, với `Work Lane` chạy nền. Không yêu cầu user tạo job bằng chat.
- Khi Work kết thúc, P1 ghi outcome vào Goal Ledger, P2 gửi outcome về `SubjectService.observe_outcome()` và dùng MindLoop thật để đánh giá tiếp tục/tạm dừng/hoàn thành. Goal có thể chạy nhiều Work Session, không còn bị giới hạn một job/goal.
- Không bao giờ lấy `complete` của model làm bằng chứng đạt mục tiêu: muốn `achieved` phải có receipt công cụ trong `last_evidence`, sau đó Subject/Executive mới chọn `achieve_goal`.
- V103 expression motor không có quyền chiếm quyết định **structured goal work**. Các đường autonomous speech khác vẫn dùng V103 như cũ.
- Chống job cũ tiếp tục sau suspend/resume bằng `goal_epoch`, chống chạy nhiều job cùng goal bằng claim SQLite. Sau crash ở đoạn không rõ side effect, giữ `needs_review` thay vì replay.
- Mặc định gọi P2 qua heartbeat hiện hữu; V3 sandbox-pilot không còn được pump song song. `Goal` không phát Bubble/TTS từ Work Lane.

## Áp dụng bản vá

1. Sao lưu source Eris bạn đang thử nghiệm.
2. Bảo đảm đã ghép **Runtime Reconstruction + P0 + P1**.
3. Giải nén `Eris_P2_Identity_Executive_Work_CHANGE_ONLY.zip` vào **thư mục gốc Eris**, giữ nguyên đường dẫn `src/` và `tools/`.
4. Không chép lên bản Eris V4/V5/V6 nguyên thủy nếu chưa có P0/P1.

## Kiểm thử

```powershell
$env:PYTHONPATH = "src;."
py -m pytest -q src/tests/agent_harness/test_identity_goal_integration.py
py tools/p2_identity_goal_probe.py
```

Probe này gọi SubjectService, MindLoop, ExecutiveCortex và MathWorkspace/worker SymPy **thật**, sử dụng một `PendingIntention` mẫu để không phụ thuộc prompt hay token online. Đầu ra có `goal_status: achieved`, `executive_source`, artifact toán và `subject_feedback: learned`. Các SQLite, output PNG và logs được lưu trong `logs/eris_p2_identity_probe/<run-id>/`.

Để dùng model thực trong Eris: chạy ứng dụng như bình thường và quan sát log `[eris-goal]`; Work Lane lấy `ai_model_router` hiện hành qua P0/P1. Khi Root tạo goal hoặc đang làm việc, xem `parallel_work` `goals`, `goal_status`, `recent` để truy vấn tiến độ. **Không cần bật thêm feature flag** cho P2 trong autonomous runtime.

## Ngân sách thí nghiệm

`ERIS_GOAL_MAX_JOBS` (mặc định **6**) là giới hạn số Work Session cho một goal trước khi Subject phải cân nhắc tạm dừng; ví dụ:

```powershell
$env:ERIS_GOAL_MAX_JOBS = "4"
```

Không phải quy tắc cá tính/im lặng; chỉ để tránh job vô hạn khi worker chỉ trả `complete` không evidence.

## Ranh giới kiểm chứng

- Đã chạy thực tế Python/SQLite/SymPy, **không** gọi LLM trả phí hay ElevenLabs và không build Godot trên Windows trong môi trường kiểm thử này.
- Commit qua **Neuro/Executive local thật** đã kiểm chứng, kể cả đường ExecutiveCortex. Quyết định goal ở production với V103 enabled, provider DeepSeek thật và nhiều sự kiện đồng thời chưa được đo bằng log máy Windows.
- `SubjectService` còn được sử dụng bởi các đường chat/observer khác; thế hệ stale frame bị MindLoop loại, nhưng chưa chứng minh mọi store mutation đồng thời có tính transaction. Giới hạn này tồn tại ở kiến trúc Subject hiện tại.
- Feedback đang mang mức `PARTIAL` cho Work completion; mục tiêu chỉ được đánh dấu achieved khi có tool receipt và một quyết định review tiếp theo.
- Sau crash giữa khâu feedback và Subject persistence, record bị giữ `needs_review` để không học trùng một outcome. Có thể xem trong bảng `autonomy_subject_feedback`.

## Hạng mục code thay đổi

- `src/runtime/agent_harness/identity_goal_driver.py` (mới): Subject → Executive → goal → Work → feedback/review.
- `src/runtime/agent_harness/identity_goal_runtime.py` (mới): gắn một lần với Coordinator đang có.
- `src/runtime/agent_harness/goal_session_bridge.py`: đa Work Session / goal, history, epoch fence và budget.
- `src/runtime/agent_harness/unified_sessions.py`: lệnh `continue_goal`.
- `src/runtime/ai_orchestrated/executive_cortex.py`: tách scope V103 expression khỏi structured goal.
- `src/runtime/autonomous_loop_runtime.py`: pump P2 thay cho V3 pilot.
- `src/runtime/coordinator_shutdown.py`: đóng worker P2 khi dừng.
- `src/tests/agent_harness/test_identity_goal_integration.py` (mới): hồi quy.
- `tools/p2_identity_goal_probe.py` (mới): probe end-to-end bằng toán thật.

**Không thay đổi** UI Godot, Writer, SpeechAuthority hoặc thẩm quyền quyết định nội dung của Root.
