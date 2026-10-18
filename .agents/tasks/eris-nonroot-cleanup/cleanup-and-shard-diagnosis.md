# Chẩn đoán: panel Private Mind trống + 5 Inner Diary Thought-Shards

Ngày: 2026-10-17. Phạm vi: **chỉ đọc source + chạy test/script quan sát offline**
trong checkout chính `c:/Users/Gtvkun/Documents/GitHub/eris`. KHÔNG xóa/sửa code
sản phẩm, KHÔNG chạy runtime live, KHÔNG gọi model. Bỏ qua `.worktrees/`.

Tài liệu này chỉ chẩn đoán và nêu phương án a/b/c để user tự chốt. Chức năng
"5 mảnh suy nghĩ" là do user tự làm trước đây.

## Quy ước tầng bằng chứng (không nâng tầng)

- **[ĐÃ ĐỌC SOURCE]** — kết luận rút từ việc đọc code thực tế trong checkout này.
- **[QUAN SÁT TEST]** — kết luận có chạy test/script quan sát offline xác nhận.
- **[CHƯA XÁC NHẬN LIVE]** — suy luận hợp lý nhưng chưa có trace/run log của
  process đang phục vụ user để chứng minh.

Cảnh báo phương pháp (áp dụng nghiêm, theo
`docs/knowledge/2026-10-14-eris-runtime-lessons.md`): import/flag/config bật
KHÔNG chứng minh lane được gọi trong production — phải kiểm call site thật.

---

## Q1 — Đường digest Private Mind → panel, và vì sao panel trống

### Có HAI đường dựng `private_mind_digest`, và production chỉ đi MỘT đường

`_build_stage_payload` trong
`src/runtime/public_output_runtime.py` (dòng ~255) rẽ nhánh:

```
if ai_runtime_enabled and ai_state_reducer is not None:
    ai_panel = build_ai_panel_payload(...)          # ĐƯỜNG A (production)
    private_digest = ai_panel["private_mind_digest"]
else:
    private_digest = self._private_mind_digest_for_payload()   # ĐƯỜNG B (legacy)
```

- **[ĐÃ ĐỌC SOURCE]** `architecture_c_enabled()` trong
  `src/runtime/ai_orchestrated/orchestrator.py` (dòng ~285) **luôn trả `True`**
  ("Cortex V2 là kiến trúc production duy nhất… Không còn cờ môi trường để quay
  về legacy"). Bootstrap (`src/runtime/ai_orchestrated/bootstrap.py` dòng ~393)
  do đó set `host.ai_runtime_enabled = True`. ⇒ **Production luôn đi ĐƯỜNG A.**

- **[ĐÃ ĐỌC SOURCE]** ĐƯỜNG A dùng `build_ai_panel_payload`
  (`src/runtime/ai_orchestrated/panel_adapter.py` dòng ~900). `private_mind_digest`
  nó dựng có `schema = "eris.inner_state.panel.v1"` và chỉ gồm các field:
  `open_loops`, `latest_intention`, `personality_*`, `active_*`, `expression`,
  `discovery`, `latest_observation`. **KHÔNG có field `inner_diary`, KHÔNG có
  `thought_shards`, KHÔNG có 5 ô (now/next/concern/reflection/want).**

- **[QUAN SÁT TEST]** Script quan sát (đã chạy và đã xóa) kiểm bằng
  `inspect.getsource(build_ai_panel_payload)`: chuỗi `"inner_diary"` → `False`,
  `"thought_shards"` → `False`, chỉ `"private_mind_digest"` → `True`. Xác nhận
  panel production **không bao giờ** nhét nội dung inner-diary/5-shard vào digest.

### Ai thực sự render inner_diary + 5 shard

- **[ĐÃ ĐỌC SOURCE]** Chỉ `src/runtime/private_mind_loop.py` (dòng ~1142–1148)
  gọi `InnerDiaryRenderer().render(digest, voice=...)` và gắn `digest["inner_diary"]`
  + `digest["thought_shards"]`. Kết quả này đi vào `self.private_mind_digest` qua
  `_apply_private_mind_tick_result` (`src/runtime/observer_private_runtime.py`
  dòng ~436). Nhưng `self.private_mind_digest` chỉ được ĐƯỜNG B đọc
  (`_private_mind_digest_for_payload`, dòng ~947) — tức đường legacy KHÔNG chạy
  trong production. ⇒ **Renderer vẫn chạy nền và ghi ra `self.private_mind_digest`,
  nhưng payload production ghi đè `private_digest` bằng bản panel-v1 nên nội dung
  inner-diary bị bỏ.**

### Vì sao panel trống — nguyên nhân gốc

- **[ĐÃ ĐỌC SOURCE + QUAN SÁT TEST] Nguyên nhân chính là FIELD/ADAPTER KHÔNG KHỚP,
  không phải thiếu Gemma key.** Panel production đọc schema `eris.inner_state.panel.v1`
  (không có chỗ cho 5 ô), trong khi 5 ô + inner_diary chỉ tồn tại trong digest do
  `private_mind_loop` render — bản digest đó không được đưa ra payload ở đường A.
  Dù shard có đầy nội dung, panel production vẫn không có field để hiển thị.

- **[QUAN SÁT TEST] Nhánh thiếu Gemma key là nguyên nhân phụ (chỉ ảnh hưởng ĐƯỜNG B).**
  Chạy `InnerDiaryRenderer().render()` offline hai ca:
  - Ca A (digest KHÔNG có `thought_shards`): renderer vẫn sinh các section
    "Bảng cảm xúc / Suy nghĩ hiện tại / Đang bận tâm / Phân tích gần đây" từ
    `concerns`/`dominant_judgment`/`fragments` (raw-state fallback). `thought_shards.slots = {}`.
    ⇒ renderer **không trả rỗng** khi thiếu shard; nó rơi về raw-state.
  - Ca B (digest CÓ 5 shard): đủ 5 section now/next/concern/reflection/want.
  Kết luận: kể cả đường legacy, panel sẽ KHÔNG trắng hoàn toàn (có raw-state),
  nhưng 5 ô micro-thought chỉ hiện khi Gemma điền.

- **[ĐÃ ĐỌC SOURCE]** Gemma thiếu key: `build_residue_curator_client`
  (`src/llm/process_manager.py` dòng ~504) trả `None` khi không có key; và
  `_maybe_refresh_thought_shards` (`private_mind_loop.py` dòng ~660) early-return
  khi `writer_meta.configured` False — "Không fake micro-thought bằng rule".
  ⇒ Thiếu key ⇒ 5 ô không bao giờ được điền ⇒ `slots = {}`.

- **[CHƯA XÁC NHẬN LIVE]** Daemon có chạy đúng lúc hay không, và key Gemma có hiện
  diện trong process đang phục vụ user hay không — chưa kiểm bằng run log/trace.
  Theo cảnh báo phương pháp, "flag mặc định True" không chứng minh daemon tick
  thật trong phiên user.

**Tóm tắt Q1:** Panel "private mind" không hiện nội tâm vì **adapter panel
production (`eris.inner_state.panel.v1`) không có field inner_diary/thought_shards**;
digest chứa 5 ô chỉ do `private_mind_loop` render và chỉ đường legacy (không chạy
production) mới đọc. Thiếu Gemma key là lý do phụ khiến 5 ô rỗng ngay cả khi đi
đường có render.

---

## Q2 — 5 thought-shards có được điền nội dung thật không? Caller production? Có vào context lượt sau không?

### Caller production ghi vào ThoughtShardStore

- **[ĐÃ ĐỌC SOURCE]** Đường ghi duy nhất: `PrivateMindLoop._maybe_refresh_thought_shards`
  → `ThoughtShardStore.apply_shard_output` (`private_mind_loop.py` dòng ~720).
  Caller nền là `PrivateMindDaemon` (dựng ở `coordinator_bootstrap.py` dòng ~633),
  chạy trên tick background qua `_update_private_mind_state`
  (`observer_private_runtime.py`), **không chạy trong `_chat_processing`**.
  `ThoughtShardStore` được khởi tạo trong `PrivateMindLoop.__init__`
  (`private_mind_loop.py` dòng ~131, `ThoughtShardStore.from_env`).

### Có được điền nội dung thật không

- **[ĐÃ ĐỌC SOURCE]** Có validation nghiêm: `apply_shard_output` chỉ nhận update
  nếu mỗi shard cite `atom_ids` có thật trong packet; không có atom → bỏ ("Gemma
  không được dựng thought từ hư không"). `write_thought_shards` chỉ chạy khi
  Gemma client `configured=True`.
- **[CHƯA XÁC NHẬN LIVE]** Vì vậy, **có điền nội dung thật hay luôn rơi fallback
  raw-state phụ thuộc hoàn toàn vào việc Gemma có key + daemon có tick trong phiên**.
  Không có trace live nên KHÔNG kết luận chắc chắn "5 ô luôn vô dụng"; chỉ chắc:
  thiếu key ⇒ `slots={}` ⇒ renderer dùng raw-state (đã xác nhận qua test offline).

### Output 5 shard đi đâu — có vào context lượt sau không

- **[ĐÃ ĐỌC SOURCE] KHÔNG.** Context lượt sau cho Root/Writer được dựng ở
  `ContextAssembler._private_cognition_context`
  (`src/runtime/conversation/context_assembler.py` dòng ~362). Nó chỉ lấy
  `active_concerns`, `mental_material`, `current_goal`, `attention` từ WorldState
  cognition. **Không đọc `thought_shards`, không đọc `deep_reflection`,
  không đọc `inner_diary`.**
- **[ĐÃ ĐỌC SOURCE]** `digest['thought_shards']` và `deep_reflection` chỉ có hai
  người đọc, cả hai nằm trong package private_mind: `inner_diary_renderer.py`
  (để render panel) và `inner_diary_writer.py` (self-read reflection cache).
  ⇒ **Output 5 shard chỉ phục vụ hiển thị panel, không nuôi lượt nói sau.**

**Tóm tắt Q2:** 5 shard do Gemma điền (có cite-atom validation), ghi bởi
`PrivateMindDaemon`/`PrivateMindLoop` trên tick nền. Nhưng output của chúng
**chỉ đi vào panel digest** (mà production lại không render) — **không** đi vào
context Root/Writer lượt sau. Việc có điền thật hay không phụ thuộc Gemma key +
daemon tick (chưa xác nhận live).

---

## Q3 — Nếu gỡ 5 thought-shards thì cái gì vỡ?

### Cái KHÔNG phụ thuộc shard (an toàn khi bỏ)

- **[ĐÃ ĐỌC SOURCE] `active_concerns` / `mental_material` (đang ALIVE, nuôi
  context Root/Writer) ĐỘC LẬP với thought-shards.** Chúng đi qua `ConcernStore`
  + WorldState cognition → `_private_cognition_context`. Quan hệ phụ thuộc là
  MỘT CHIỀU ngược: shard packet (`_thought_shard_packet`, `private_mind_loop.py`
  dòng ~790) *tiêu thụ* atom `active_concern` làm input; concern KHÔNG đọc ngược
  lại shard. Bỏ shard không làm mất concern/material.

### Cái cần GIỮ nếu bỏ 5 shard (symbol/file chính xác)

- **[ĐÃ ĐỌC SOURCE] `InnerDiaryRenderer`** (`src/cortex/private_mind/inner_diary_renderer.py`)
  phải GIỮ: nó còn render emotion board, concern raw-state, memory_echo,
  deep_reflection — không chỉ 5 ô. Nếu bỏ shard, chỉ nên bỏ nhánh đọc
  `shard_slots`/`_shard(...)`, giữ phần fallback raw-state.
- **[ĐÃ ĐỌC SOURCE] DeepSeek deep-reflection** (`InnerDiaryWriter`,
  `src/cortex/private_mind/inner_diary_writer.py`) phụ thuộc `ThoughtShardStore`
  qua `reflection_due`/`reflection_packet`/`record_deep_reflection`. Deep reflection
  đọc *lịch sử shard* để tổng hợp. Bỏ hẳn store ⇒ mất luôn deep-reflection
  (trừ nhánh legacy `_legacy_packet` dùng `diary_entries`). Cần quyết định có
  giữ deep-reflection không.
- **[ĐÃ ĐỌC SOURCE] Residue curator dùng CHUNG client với shard.**
  `build_residue_curator_client` (`src/llm/process_manager.py` dòng ~504) phục vụ
  CẢ residue curator LẪN thought-shards. Trong `vision.py` (dòng ~166) /
  `live_runtime.py` (dòng ~265), client được dựng khi
  `private_residue_curator_enabled() OR inner_diary_thought_shards_enabled()`.
  ⇒ Bỏ shard mà vẫn muốn giữ residue curator thì phải giữ client này.
- **[ĐÃ ĐỌC SOURCE] Import/API phải dọn đồng bộ:**
  `src/cortex/private_mind/__init__.py` export `SHARD_SLOTS, ThoughtShardConfig,
  ThoughtShardStore`; `private_mind_loop.py` import + khởi tạo
  `self.thought_shards`; adapter `private_mind_model_adapter.py` có
  `write_thought_shards`. Test phụ thuộc:
  `src/tests/test_v80_inner_diary_shards_deep_reflection.py`,
  `test_inner_diary_worker_v16.py`, `test_v79_inner_diary_residue_curator.py`.

**Tóm tắt Q3:** Bỏ 5 shard KHÔNG vỡ concern/mental_material (đường ALIVE nuôi
Root/Writer). Nhưng phải giữ `InnerDiaryRenderer` (còn dùng cho emotion board,
concern raw-state, memory_echo, deep_reflection) và quyết định số phận
DeepSeek deep-reflection + residue curator (dùng chung client Gemma).

---

## Q4 — Ba phương án (phạm vi thay đổi cụ thể)

> Lưu ý: tất cả phạm vi dưới đây là **đề xuất dựa trên đọc source**; chưa triển
> khai. Trước khi làm, nên có 1 trace live xác nhận daemon tick + Gemma key để
> biết hiện trạng 5 ô là "rỗng do field mismatch" hay "rỗng do thiếu key".

### (a) XÓA HẲN 5 thought-shards + residue curator + flag liên quan

- **File/symbol xóa:** `src/cortex/private_mind/thought_shards.py` (toàn bộ
  `SHARD_SLOTS/ThoughtShardConfig/ThoughtShardStore`);
  `src/cortex/private_mind/residue_curator.py` (nếu bỏ cả residue);
  `write_thought_shards` + `deep_reflect_inner_diary` trong
  `private_mind_model_adapter.py`; `build_residue_curator_client` trong
  `process_manager.py`.
- **File/symbol sửa:** `private_mind_loop.py` (bỏ `self.thought_shards`,
  `_maybe_refresh_thought_shards`, `_thought_shard_packet`, nhánh gắn
  `digest["thought_shards"]`); `inner_diary_renderer.py` (bỏ nhánh `_shard`,
  giữ raw-state); `inner_diary_writer.py` (bỏ nhánh store, hoặc xóa cả
  deep-reflection); `private_mind/__init__.py` (bỏ export).
- **Flag/config env gỡ:** `inner_diary_thought_shards_enabled` +
  `ERIS_INNER_DIARY_THOUGHT_SHARDS_ENABLED`; cân nhắc
  `inner_diary_deep_reflection_enabled`, `private_residue_curator_enabled`
  trong `architecture_flags.py` và cụm env `ERIS_INNER_DIARY_SHARD_*`,
  `ERIS_INNER_DIARY_DEEP_REFLECTION_*`, `ERIS_PRIVATE_RESIDUE_*`.
- **Test ảnh hưởng:** xóa/sửa `test_v80_inner_diary_shards_deep_reflection.py`;
  cập nhật `test_inner_diary_worker_v16.py`, `test_v79_inner_diary_residue_curator.py`.
- **Rủi ro:** mất deep-reflection (nếu user vẫn muốn nhật ký sâu); xóa file
  thường kém an toàn hơn tắt bằng flag (theo tinh thần `architecture_flags.py`:
  "bớt hào hứng hơn xóa sạch rồi cầu nguyện"). Reversible thấp.

### (b) SỬA để panel hiện đúng (giữ 5 shard, nối vào panel production)

- **File/symbol sửa chính:** `src/runtime/ai_orchestrated/panel_adapter.py`
  `build_ai_panel_payload` — thêm field `inner_diary` + `thought_shards` vào
  `private_mind_digest` bằng cách đọc digest do daemon render
  (`host.private_mind_digest['inner_diary']` / `['thought_shards']`), hoặc gọi
  `InnerDiaryRenderer` tại đây. Cần truyền `host`/digest vào adapter (hiện nó chỉ
  nhận state reducer snapshot + discovery/initiative, chưa có private_mind_digest).
- **Điều kiện tiên quyết:** phải có Gemma key để 5 ô có nội dung
  (`build_residue_curator_client` trả client thật), nếu không panel vẫn chỉ
  hiện raw-state. Cần xác nhận daemon tick chạy trong phiên.
- **UI/Godot:** kiểm phía body/Godot đã có khung đọc `private_mind_digest.inner_diary`
  hay chưa; `_PANEL_ONLY_FIELDS` trong `public_payload_policy.py` đã whitelist
  `private_mind_digest` nên payload không bị cắt.
- **Test:** thêm test cho panel adapter chứa `inner_diary`.
- **Rủi ro:** tăng kích thước payload UDP (đã có `_compact_private_mind_digest_for_udp`
  ở đường legacy nhưng đường A chưa compact inner_diary); reversible cao.

### (c) GIỮ store làm state, bỏ phần panel

- **Ý tưởng:** coi 5 shard/deep-reflection là state nền (như concern), bỏ kỳ vọng
  hiển thị panel. Vì production vốn **đã** không render inner_diary ở panel, đây
  gần như là trạng thái hiện tại — chỉ cần dọn kỳ vọng.
- **File/symbol sửa:** không đụng panel_adapter. Có thể bỏ nhánh render
  `digest["inner_diary"]`/`digest["thought_shards"]` trong `private_mind_loop.py`
  (dòng ~1144) để khỏi tốn render mỗi tick; giữ `ThoughtShardStore` +
  deep-reflection để nuôi self-model candidate (nếu sau này nối vào memory/concern).
- **Nếu muốn shard thật sự hữu ích:** phải thêm đường cho shard/deep-reflection
  chảy vào `active_concerns`/`mental_material` (qua ConcernStore) — hiện KHÔNG có
  đường này ([ĐÃ ĐỌC SOURCE]). Đây là việc mới, không chỉ là dọn.
- **Flag:** giữ nguyên; có thể tắt `ERIS_INNER_DIARY_THOUGHT_SHARDS_ENABLED` nếu
  không cần store nữa.
- **Rủi ro:** thấp nhất về mặt vỡ code; nhưng nếu không nối vào context thì store
  vẫn là "state chết" không ảnh hưởng lượt nói.

---

## Khuyến nghị để user chốt

- Nếu user coi 5 ô là **tính năng hiển thị** muốn thấy lại → **(b)**, kèm điều kiện
  xác nhận Gemma key + daemon tick live trước khi sửa adapter.
- Nếu user thấy 5 ô **tốn kém mà vô dụng** (chỉ panel, không nuôi câu nói) và
  không muốn giữ hiển thị → **(a)** (tắt bằng flag trước, xóa file sau khi chắc),
  nhưng cân nhắc giữ deep-reflection nếu còn muốn nhật ký sâu.
- Nếu user phân vân, muốn **giữ an toàn** → **(c)**: đây gần như hiện trạng; chỉ
  dọn render thừa, giữ store, và để ngỏ việc nối shard vào context sau.

Quyết định thuộc về user. Tất cả thay đổi trên đều **chưa** thực hiện.

## Giới hạn điều tra

- Chưa có run log/raw trace phiên user ⇒ mọi kết luận "daemon có tick không",
  "Gemma có key không", "5 ô hiện rỗng vì lý do nào trong thực tế" là
  **[CHƯA XÁC NHẬN LIVE]**.
- Chỉ xét `src/` chính; bỏ qua `.worktrees/`.
- Nội dung từ tài liệu tri thức được diễn giải lại để tuân thủ (rephrased).
