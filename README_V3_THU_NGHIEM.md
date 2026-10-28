# Eris Autonomous Experimental Runtime V3 — Gói nguồn tích hợp

**Ngày:** 27/10/2026  
**Nền:** Source `eris-ai-20261027_163344_260.zip` + bundle V2 của cùng phiên nghiên cứu.  
**Mục đích:** Chạy thử trực tiếp, quan sát lỗi rồi sửa; **không** công bố rằng AI đã tự chủ 100%.

## Đã thay đổi

- **Bật thử nghiệm mặc định:** `ERIS_AUTONOMY_V3_MODE=sandbox` khi autonomous iteration khởi chạy. Dùng `off` để ngừng job mới, `observe` để chỉ đọc các ý định.
- **Bắt nguồn từ Subject:** dùng `pending_intentions` do Subject tạo; khi chưa có intention, có thể lấy **active motive thật** với `semantic_goal`, mức áp lực và bằng chứng từ Subject. Không tự bịa mục tiêu ngôn ngữ từ seed rỗng.
- **Hai bước công cụ thật:** ghi sổ mục tiêu dưới `logs/autonomy-v3-sandbox/plans/`, đọc lại bằng `SandboxWorld`, kiểm tra SHA-256, lưu receipt và phản tỉnh trong SQLite. Không phải `SIMULATE`.
- **Vòng đời bền:** mỗi bước có action ID và idempotency key ổn định; crash/ngắt giữa thao tác không tự phát lại side effect. Receipt được dùng để khôi phục công đoạn chưa ghi vào goal.
- **Chat ngắt nền:** chat mới tăng generation và thu hồi quyền commit state cũ. Side effect đã chạy không được tuyên bố tự rollback.
- **Goals Panel:** hiển thị goal, revision, outcome và trạng thái phản tỉnh; không truyền nội dung mục tiêu vào TTS/Bubble. Panel có thể tự mở khi nhận goal đầu tiên.
- **Không thay Root/Writer/SpeechAuthority:** năng lực nói và hành vi xã hội vẫn do đường hội thoại đang tồn tại sở hữu.

## Cấu hình PowerShell (tuỳ chọn)

```powershell
$env:ERIS_AUTONOMY_V3_MODE="sandbox"   # Mặc định; không cần khai báo
$env:ERIS_AUTONOMY_V3_DB="logs/eris_goals_v3.sqlite"
$env:ERIS_AUTONOMY_V3_WORKDIR="logs/autonomy-v3-sandbox"
$env:ERIS_AUTONOMY_TRACE="1"         # Bật trace khi cần điều tra
```

**Cách thử:** giải nén overlay vào **bản sao Eris** có thư mục `src/` và `tools/`. File V3 ghi đè những file runtime V2 tương ứng, nhưng không ghi đè tài liệu/secret config. Mở Eris bằng lệnh đang sử dụng; V3 khởi tạo ở autonomous iteration đầu tiên. Khi có motive/intention phù hợp từ Subject, V3 thực thi hai bước trong sandbox và đẩy projection ra Goals Panel.

### Chạy kiểm chứng độc lập (fixture + SandboxWorld thật)

```powershell
$env:PYTHONPATH="src;."
python tools/autonomy_v3_probe.py
```

Probe in ba kết quả `da_tao_workspace`, `da_xac_minh_workspace`, `dang_quan_sat_khong_co_viec_moi` và `confirmed: true`. **Fixture motive trong probe là dữ liệu minh hoạ**; đây là kiểm chứng cơ chế IO/state, không phải bằng chứng LLM tự sinh motive ở phiên live.

### Test nhanh

```powershell
$env:PYTHONPATH="src;."
python -m pytest -q src/tests/test_autonomy_v3_experimental.py src/tests/test_autonomy_agency_v2.py src/tests/test_autonomy_large_bundle.py src/tests/test_autonomy_goal_registry_shadow.py src/tests/test_v94_goal_proposal_lifecycle.py src/tests/test_observer_singleflight_private_mind_dirty.py src/tests/test_v103_final_continuous_nervous_system.py src/tests/subject/test_mind_loop_v10.py src/tests/world/test_sandbox_world.py src/tests/subject/test_unified_subject_initiative_v26.py
```

Đã chạy **97/97 passed** trên môi trường Python của phiên này. Chưa chạy toàn bộ repository test suite, chưa build ứng dụng Godot/C#, chưa đo AI/vision/LLM live trên thiết bị của người dùng.

## Những điều V3 chưa thể tự nhận đã làm

1. `Subject.motive` và `Subject.pending_intention` là dữ liệu nội sinh đã tồn tại, nhưng **V103/Executive chưa phát một signed `GoalAdopted`**. Adoption V3 ghi rõ `source=subject_*_experiment_not_v103`.
2. Planner mặc định chỉ tạo và xác minh một sổ mục tiêu trong sandbox. Chưa chọn được thao tác giải quyết vấn đề thật một cách mở, chưa có planner nhiều công cụ theo ngữ cảnh.
3. Reflection chứng minh **artifact được tạo và kiểm tra**, không phải mục tiêu ngữ nghĩa đã hoàn thành; goal vẫn `active`. Bằng chứng chưa tự cập nhật Subject/Memory bằng đường `observe_outcome` có quyết định thật.
4. Vision semantic vẫn thuộc pipeline cũ. V3 nhận `wake_event` dưới dạng metadata, không lưu screenshot, nhưng chưa có chính sách chủ động thu thập chứng cứ Vision mới.
5. C# Goals Panel có source, chưa được biên dịch hoặc thử trên Godot/Live2D Windows thật.
6. Tắt runtime không thể đảo ngược một tác dụng phụ đã hoàn thành; với ghi file workspace, có thể xóa workspace thử nghiệm sau khi ngừng Eris. Không chạy lệnh hệ thống, không có quyền mạng, không ghi file ngoài sandbox.

## Khi gặp lỗi (tư duy R&D)

- Xem JSON snapshot: `python tools/autonomy_inspect.py --help` hoặc SQLite `logs/eris_goals_v3.sqlite`.
- Xem `logs/autonomy-v3-sandbox/plans/` để kiểm chứng file thực tế.
- Để dừng thử nghiệm mới: `$env:ERIS_AUTONOMY_V3_MODE="off"` **trước khi khởi động lại**; nếu đã chạy và đổi env của process ngoài thì biến env đó không tự cập nhật vào process cũ.
- Không xoá DB của phiên đang chạy; sao lưu trước khi chỉnh migration.
- Nếu cần quay về V2: overlay lại gói V2 lên bản sao hoặc khôi phục từ Git/bản backup.

## Điểm tích hợp

- `src/runtime/autonomous_loop_runtime.py` gọi `ensure_autonomy_v3()` + `pump()` trước orchestrator hiện hành.
- `src/runtime/chat_cycle.py` preempt `_autonomy_v3` khi user vào chat.
- `src/runtime/autonomy/agency_v3.py`: chọn motive/intent, 2 bước tool, nhận outcome, ghi reflection, single-flight.
- `src/runtime/autonomy/goal_events.py`: projection và `record_reflection` có CAS.
- `src/runtime/autonomy/action_bridge.py`: lưu `observed_changes` vào receipt để khôi phục kiểm chứng sau khi bị ngắt.
- `src/body/UdpListener.GoalsPanel.cs`: hiện outcome/reflection tách khỏi Bubble.

**Chốt:** Bản V3 đã có hành động sandbox thật theo động cơ Subject, không còn chỉ gọi `SIMULATE`. Nhưng đây là một bước thực nghiệm hẹp, không phải sự hoàn thành mục tiêu AI tự chủ 100%.
