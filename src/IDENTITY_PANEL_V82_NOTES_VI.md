# Identity Panel V82 — SELF / INNER / TRACE

## Đã đổi

- Gộp Identity thành **một panel duy nhất với 3 tab**:
  - `SELF`: current form, self-interpretation, Desire / Tension / Core.
  - `INNER//`: các mảnh Want / Unsaid / Concern / Memory Echo, bố cục lệch kiểu diary dossier.
  - `TRACE•`: Then → Now, thread còn tồn tại và timeline ngắn.
- Bỏ TURN/STATE và phần lớn score/progress bar khỏi UI thường. Raw state vẫn giữ trong backend để debug.
- Footer `GEMMA // OBSERVER` cố định ở cả 3 tab.

## Gemma Observer

Không mở thêm API call.

Cùng request Gemma đang dùng để cập nhật 5 thought-shards, schema giờ cho phép trả thêm:

```json
{
  "observer_comment": {
    "text": "...",
    "atom_ids": ["..."]
  }
}
```

`ThoughtShardStore` chỉ nhận comment nếu `atom_ids` thật sự tồn tại trong packet. Comment được persist cùng shard state và Body đọc trực tiếp từ private-mind snapshot.

Nếu Gemma chưa có comment mới, UI fallback sang shard thật (`now/reflection/concern/next`) hoặc identity interpretation. Không bịa telemetry thành lời bình.

## Asset tùy chọn

Patch **không nhét ảnh AI-generated vào repo**. Nếu asset không tồn tại, UI dùng glyph/shape fallback.

Có thể tự vẽ và thả các file sau vào `res://asset/`:

- `identity_portrait.png` — portrait Eris, quan trọng nhất.
- `identity_brand.png` — biểu tượng cạnh `ERIS / IDENTITY_01`.
- `identity_observer_crystal.png` — crystal ở footer Gemma.
- `identity_core_crystal.png` — crystal trung tâm tab INNER.
- `identity_tab_self.png`
- `identity_tab_inner.png`
- `identity_tab_trace.png`
- `identity_action_freeze.png`
- `identity_action_export.png`

Không cần đủ toàn bộ. Asset thiếu sẽ tự fallback.

## Test

Đã chạy:

```text
pytest -q tests/test_v79_inner_diary_residue_curator.py \
          tests/test_v80_inner_diary_shards_deep_reflection.py \
          tests/test_identity_panel_v81_just_enough.py

17 passed
```

Checker duplicate C# vẫn báo `body/` trùng với `integration/body_contracts/`, nhưng ZIP gốc trước patch cũng báo đúng 3 duplicate đó, nên không phải regression của V82.
