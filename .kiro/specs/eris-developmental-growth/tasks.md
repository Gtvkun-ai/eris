# Implementation Plan

## Overview

Kế hoạch triển khai Hệ_Phát_Triển long-arc cho ERIS, chia thành các bước tăng dần có thể kiểm thử. Thứ tự ưu tiên dựng nền persistence + data model trước, rồi cổng bản sắc, luồng apply fail-closed, tác tử nền, điều phối, và cuối cùng là tích hợp bias vào mặt phẳng biểu đạt — để mỗi bước đều chạy test được trước khi đụng runtime thật. Mọi bước giữ nguyên các guard sự thật và không đụng layer micro-trong-phiên.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"], "dependsOn": [] },
    { "wave": 2, "tasks": ["1.1", "2"], "dependsOn": ["1"] },
    { "wave": 3, "tasks": ["2.1", "2.2", "3"], "dependsOn": ["2"] },
    { "wave": 4, "tasks": ["3.1", "4", "5"], "dependsOn": ["3"] },
    { "wave": 5, "tasks": ["4.1", "5.1", "6"], "dependsOn": ["4", "5"] },
    { "wave": 6, "tasks": ["6.1", "7"], "dependsOn": ["6"] },
    { "wave": 7, "tasks": ["8"], "dependsOn": ["7"] }
  ]
}
```

## Tasks

- [x] 1. Dựng data model và DevelopmentProfileStore (persistence nền)
  - Tạo `src/cortex/development_profile.py` với các dataclass: `AxisDelta`, `GrowthAnchor`, `NudgeProposal`, `LogEntry`, `ProfileVersion`, `GateDecision`; hằng `PERSONA_AXES`, `SCHEMA_VERSION`, `BASELINE` (mọi delta=0.0).
  - Cài `DevelopmentProfileStore`: `load`/`save` (atomic tmp+replace), `reload_if_changed` (mtime), `to_dict`/`from_dict`, `snapshot`/`restore`, `reset_to_baseline`, `identity_distance`, `commit(axis, clamped_delta)`. Mirror pattern của `PersistentAgentMindStore`.
  - `from_dict` điền safe default cho trường thiếu, ưu tiên đủ-mặc-định kể cả khi phải bỏ giá trị hỏng.
  - _Requirements: 10.1, 10.2, 10.4, 11.1, 11.4_

- [x] 1.1 Property test round-trip + persistence resilience
  - Tạo `tests/test_development_profile.py`: Property 1 (round-trip `to_dict→from_dict→to_dict`), corrupt file → baseline, baseline-fallback-fail → raise, reload-on-change.
  - _Requirements: 10.3, 10.5, 11.1, 11.2, 11.4_

- [x] 2. IdentityEnvelope + IdentityGate (cổng bản sắc)
  - Trong `src/cortex/development_profile.py` (hoặc `identity_gate.py`): `IdentityEnvelope` (nạp `stable_rules` từ `IdentityCore`, `axis_bounds`, `max_identity_distance`, `max_nudges_per_window`, `window_seconds`, `dignity_axis`).
  - Cài `IdentityGate.evaluate(proposal, profile, log, *, now)` với 8 nhánh reject theo thứ tự thiết kế; kẹp delta vào `axis_bounds` khi accept; mỗi reject trả `reason`.
  - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.2, 4.3, 4.4_

- [x] 2.1 Unit test từng nhánh reject của IdentityGate
  - Cover: sửa stable_rule, chạm truth/capability guard (mọi đường), thiếu/sai neo, vượt axis_bound, vượt ngưỡng bản sắc, vượt nhịp, đẩy dignity vào phụ thuộc/nịnh, ưu tiên giữ khoảng cách khi objectification cao.
  - _Requirements: 2.1, 2.3, 2.5, 3.2, 4.2, 4.3, 4.4_

- [x] 2.2 Property test phong bì + ngưỡng bản sắc + guard bất biến
  - Property 2 (delta luôn ∈ bound), Property 3 (identity_distance ≤ max), Property 4 (guard sự thật không đổi, proposal chạm guard luôn reject), Property 5 (đề xuất không neo bị reject + ghi Sổ).
  - _Requirements: 1.2, 1.3, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 12.2_

- [x] 3. DevelopmentLog + luồng apply/undo/reset fail-closed
  - Cài `DevelopmentLog` (serialize danh sách `LogEntry`, round-trip JSON, ghi `applied`/`rejected`/`undo`/`reset`/`steer`).
  - Cài `DevelopmentSystem.apply(proposal)`: gate → snapshot → **ghi Sổ trước** → nếu ghi fail thì `restore(snapshot)` và bỏ thay đổi → commit + save sau khi Sổ đã ghi.
  - Cài `undo_last()` và `reset()` (giữ Sổ làm lịch sử).
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.3, 12.3_

- [x] 3.1 Property test nhịp + fail-closed log + undo/reset
  - Property 6 (≤ max_nudges_per_window), Property 7 (log fail → profile không đổi), Property 8 (undo khôi phục đúng phiên trước; reset về baseline giữ Sổ).
  - _Requirements: 4.2, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 4. GrowthConsolidator (tác tử nền trên DaydreamConsolidator)
  - Tạo `src/cortex/growth_consolidator.py`: `should_run(...)` (hoãn khi user tương tác kỹ thuật/rủi ro cao, tôn trọng phủ quyết ngân sách model, chỉ chạy khi đủ ngưỡng kích hoạt).
  - `consolidate(...)`: gom bằng chứng nhiều phiên (belief/preference/habit/feedback/repair) thành packets có `evidence_ids`; tái dùng pattern validate của `DaydreamConsolidator` để loại insight thiếu/sai evidence; sinh `list[NudgeProposal]` (không tự áp); áp ngưỡng tần suất cho preference (R1.4); user_correction/steer có trọng số cao (R1.5).
  - Áp quán tính suy giảm cho tín hiệu phiên đơn lẻ (R8.3); không sinh đề xuất khi chưa đủ bằng chứng nhiều phiên đủ chất lượng.
  - _Requirements: 1.1, 1.4, 1.5, 1.6, 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 8.3, 8.4_

- [x] 4.1 Property test long-arc vs micro + phân kỳ có kiểm soát
  - Property 9 (một phiên đơn lẻ không đổi Hồ_Sơ; cần nhiều phiên đủ chất lượng), Property 10 (bằng chứng nhất quán nhiều phiên → độ lệch quan sát được trên ≥1 trục, vẫn trong phong bì).
  - _Requirements: 8.1, 8.4, 12.1, 12.2, 12.4_

- [x] 5. DevelopmentSystem orchestration + giao diện người dùng
  - `tick(now, context)`: gọi `GrowthConsolidator.should_run` → lấy proposals → `apply` từng cái.
  - `describe_for_user()`: tóm tắt tiếng Việt, KHÔNG lộ tên tham số/giá trị số thô.
  - `steer(user_direction)`: tạo `NudgeProposal` neo trọng số cao, đi qua `IdentityGate`; phần ngoài phong bì → áp phần trong, báo phần không áp được bằng ngôn ngữ tự nhiên.
  - _Requirements: 6.1, 9.1, 9.2, 9.3, 9.4_

- [x] 5.1 Unit test giao diện người dùng
  - `describe_for_user` không chứa tên trục/số thô; `steer` ngoài phong bì áp phần trong + thông báo; undo/reset gọi được từ lệnh user.
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 6. DevelopmentBias — tích hợp vào mặt phẳng biểu đạt (read-only)
  - Cài `DevelopmentSystem.development_bias()` trả struct bias.
  - Hợp `read_boldness` long-arc vào `_TOM_BOLDNESS` ở `src/cortex/meaning/pipeline.py` (vẫn tự gate theo `overread_risk`).
  - Hợp `warmth_temperature`/`preferred_distance`/`attachment_visibility` delta vào baseline mà `PersonalityLens._expression_ceiling`/`_suppression_floor`/`_suppression_pressure` đọc, và vào `ControlledSlippageProfile` (`intuition_allowance`/`friction_permission`) sau `clamp()`.
  - Bảo đảm KHÔNG có đường nào ghi `truth_guard`/`capability_guard` hay tạo public text bỏ qua SurfaceArbiter/post-gen filters.
  - _Requirements: 3.3, 3.4, 7.1, 7.2, 7.3, 7.4, 8.2_

- [x] 6.1 Integration test bias không phá guard
  - Bias làm đổi giọng/khoảng cách nhưng `truth_guard`/`capability_guard` không đổi; không có đường ra public text bỏ qua filter; micro-layer trong phiên không bị thay đổi vai trò.
  - _Requirements: 3.1, 3.3, 7.2, 7.3, 7.4, 8.2_

- [x] 7. Wiring runtime + persistence path
  - Singleton `get_default_development_system()` + cờ `development_growth_enabled()` (mặc định TẮT) + path helpers cùng thư mục memory.
  - Read-side: `_resolve_tom_boldness()` trong `meaning/pipeline.py` và `apply_to_slippage` ở cuối `resolve_controlled_slippage()` — bọc cờ + try/except + `reload_if_changed`, fail-safe.
  - Bộ phiên dịch `growth_evidence.observations_from_feedback()`: ánh xạ bảo thủ feedback thật (more_life/intrusive_question/silence_too_long) → `GrowthObservation`, gom phiên theo ngày, evidence_ids thật.
  - Autonomous tick: `ContextualAutonomyLoop._maybe_run_growth_tick()` chạy ở nhịp idle-consolidation (cùng gate daydream), bọc cờ + try/except, defer khi user high-risk.
  - _Requirements: 6.3, 6.4, 7.3, 8.1, 10.4_

- [x] 8. Chạy bộ test và xác minh không regression
  - Chạy `tests/test_development_profile.py` + các test mới; chạy lại `tests/test_personality_lens.py`, `tests/test_theory_of_mind.py`, `tests/test_internal_state.py` để chắc tích hợp bias không phá hợp đồng cũ.
  - _Requirements: 2.1, 3.1, 5.1, 7.2, 8.2_

## Notes

- Tái dùng tối đa: `DaydreamConsolidator` (gate + validate evidence), `PersistentAgentMindStore` (pattern persistence), `IdentityCore.stable_rules` (bất biến). Không dựng song song trùng lặp.
- Bốn bất biến fail-closed (ký ức không là bằng chứng hiện tại; không cửa hậu nới guard sự thật; không bỏ qua lớp an toàn nào; log hỏng → rollback) phải được test trực tiếp, không chỉ tin vào review.
- Mọi thay đổi giọng/quan hệ đi qua bias state read-only; tuyệt đối không có đường ghi vào `truth_guard`/`capability_guard` hay bỏ qua SurfaceArbiter/post-generation filters.
- Không sửa vai trò của các layer micro-trong-phiên (`MentalProcessSystem`, `disposition.py`, RelationshipDynamics theo turn).
- Cảnh báo: các property-based test (Property 1–10) dùng hypothesis; nêu rõ khi chạy để theo dõi.
