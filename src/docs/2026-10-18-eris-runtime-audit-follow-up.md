# ERIS runtime — bổ sung audit ngày 2026-10-18

Bản này ghi kết quả đối chiếu source trong workspace `src`, tiếp nối bàn giao
về `2026-10-14-eris-runtime-lessons.md`. Tài liệu ngày 14/10 không có trong
workspace hoặc ZIP source đi kèm, nên chưa sửa trực tiếp hay đánh dấu thay thế
các đoạn trong bản gốc. Khi ghép lại, giữ lịch sử và gắn ngày cùng phạm vi kết
luận được thay thế như dưới đây.

## Kết luận cần cập nhật trong tài liệu ngày 14/10

| Ghi nhận cũ theo bàn giao | Kết quả đối chiếu ngày 18/10 | Phạm vi thay thế |
| --- | --- | --- |
| Inner/observer/curator còn “chưa audit”. | Đã đối chiếu đường Inner Diary thought-shards → observer comment → Godot Identity. Không còn implementation `write_thought_shards`/`observer_comment` trong source Python; phần C# đọc dữ liệu đó đã được gỡ trong đợt này. | Thay trạng thái “chưa audit” cho đường shard/comment. Các worker/lane khác có cùng tên phải được đánh giá riêng. |
| Companion routing còn trong việc mở. | Bàn giao báo policy cũ đã được audit và xóa. Snapshot hiện tại vẫn có setting `companion_routing_enabled`, hook `routing_context` và test truyền routing context cho public writer. Những dấu vết này không chứng minh policy cũ còn chạy, cũng không đủ chứng minh toàn bộ routing đã bị xóa. | Ghi kết quả audit policy cũ theo bàn giao, kèm giới hạn xác minh của snapshot này; chưa đóng bằng kết luận “mọi companion routing đã bị xóa”. |
| Private mind panel không hiển thị được nội tâm. | `private_mind_digest` production dùng `eris.inner_state.panel.v1`: chiếu intention, open loops, identity, conflict/defense và discovery; chưa có trường Inner Diary, `active_concerns` hoặc `mental_material`. | Thay chẩn đoán thiếu chỗ hiển thị bằng thiếu kết nối dữ liệu ở contract/adapter. Nối nguồn đang sống vào panel là công việc riêng. |

## Thay đổi C# đã thực hiện

- Gỡ footer `GEMMA // OBSERVER`, label/meta, style riêng và lời hứa đang chờ shard.
- Gỡ `RefreshIdentityObserverV82`, `ReadGemmaObserverCommentV82`,
  `ReadGemmaThoughtShardV82`, `FindThoughtShardRootV82` và các chỗ gọi.
- Headline tiếp tục đọc `latest_observation.self_interpretation.summary`, rồi
  fallback sang `BuildIdentityHeadline(root)` trong cùng snapshot identity.
  Không còn đọc cache shard cũ hoặc gắn nhãn Gemma cho headline fallback.
- Giữ trạng thái retired của Identity UI: `UdpListener.cs` vẫn capture
  `identity_runtime`, không tạo hay expose lại DepthPanel.

Bằng chứng: [DepthPanel](../body/UdpListener.DepthPanel.cs),
[UI lifecycle](../body/UdpListener.cs),
[contract renderer](../tests/test_identity_panel_v81_just_enough.py),
[header actions](../tests/test_identity_panel_v87_composition.py),
[UI retirement](../tests/test_identity_panel_retired_v90.py).

## Các ranh giới giữ nguyên

`inner_diary_deep_reflection_enabled` và plumbing `diary_client` được giữ theo
phạm vi bàn giao. Việc tồn tại tên/flag không chứng minh có một writer diary
đang được gọi; riêng `diary_client` vẫn được `PrivateMindAdapterPool.from_env`
đọc làm bootstrap fallback cho `inner_client`.

Residue Curator là đường riêng còn hiện diện trong snapshot:
`PrivateMindLoop._maybe_consolidate_residue` vẫn có nhánh gọi `curate_residue`
khi đủ điều kiện/config, rồi deterministic consolidation khi không có output
hợp lệ. Gỡ thought-shards/observer comment không đồng nghĩa đã gỡ đường này.
Audit source ở đây không xác nhận lane nào đang chạy trên máy production.

Nguồn `active_concerns` và `mental_material` đã được
`WorldStateService._refresh_cognition_from_host` lấy qua `snapshot()`. Đợt này chưa
nối chúng vào panel adapter và không đổi schema production.

Bằng chứng: [flags](../runtime/architecture_flags.py),
[diary wiring](../llm/process_manager.py),
[adapter pool](../runtime/private_mind_model_adapter.py),
[residue loop](../runtime/private_mind_loop.py),
[world state](../runtime/world_state.py),
[panel adapter](../runtime/ai_orchestrated/panel_adapter.py),
[routing hook](../runtime/ai_orchestrated/model_router.py),
[routing setting](../runtime/runtime_settings_store.py),
[routing contract test](../tests/test_companion_model_routing_v36.py).

## Kiểm tra và giới hạn

Đã gọi trực tiếp 9 hàm kiểm tra có sẵn của ba file contract C# nêu trên bằng
Python: **8 đạt, 1 lỗi layout có sẵn**. Test
`test_v87_self_is_one_composition_not_nested_dashboard_cards` đòi
`new Vector2(760f, 428f)` trong SELF renderer; cùng assertion đã không khớp
source gốc trong `src (1).zip`, và vùng renderer đó không đổi trong đợt này.

Python mặc định chưa có `pytest`, nên đây là kết quả gọi hàm trực tiếp, không
phải một lần chạy pytest. Workspace không có `.csproj`/`.sln` hoặc Godot
project để build C# đầy đủ; chưa xác minh bằng Godot runtime.
