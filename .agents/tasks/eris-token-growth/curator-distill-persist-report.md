# Báo cáo điều tra: Curator/distill memory "living user" có persist không?

Phạm vi: ĐỌC-HIỂU, không sửa code. Repo: `c:\Users\Gtvkun\Documents\GitHub\eris`.
Ngày: theo phiên điều tra hiện tại. Mọi kết luận kèm `file:dòng`. Đã đọc
`docs/knowledge/2026-10-14-eris-runtime-lessons.md` trước theo yêu cầu AGENTS.md
(mục 3 bảng vai trò: "Curator — Xây Living User Memory — kiểm admission/provenance/recall";
mục 6 ghi "Inner/observer/curator chưa audit, chọn điều tra khi có triệu chứng").
Điều tra này là audit curator theo triệu chứng user nêu.

---

## TÓM TẮT CÂU TRẢ LỜI (đọc trước)

Có **HAI hệ distill tách biệt**, không phải một:

| Hệ | Nguồn episode | Output | Persist? | Đánh dấu đã-distill episode gốc? |
|---|---|---|---|---|
| **A. living_user Dreamer** (`dreamer.py`) | `UserEpisodeStore` (`living_user_episodes.json`) | `ProfileOperation` → profile records | **CÓ persist** (profile) | **KHÔNG** |
| **B. MemoryAICurator** (`memory_ai_curator.py`) | `EpisodicMemoryStore` (`episodic_memory.json`) | semantic fact mới | **CÓ persist** (semantic) | **KHÔNG — và cơ chế dedup bị chết** |

- **Kết quả distill CÓ được ghi xuống đĩa** ở cả hai hệ. Nghi ngờ "distill xong
  rồi vứt đi, không lưu" — **SAI với output**. Fact/profile mới đúng là có file nhận.
- **NHƯNG nghi ngờ cốt lõi của user vẫn ĐÚNG ở một dạng khác và nghiêm trọng hơn:**
  **cả hai hệ KHÔNG đánh dấu episode gốc là "đã distill".** Episode gốc ở lại
  nguyên trong store. Mỗi lần maintenance (chu kỳ ~10 phút) lại đọc cùng cụm
  episode đó, cluster lại, và gọi LLM distill lại từ đầu → **re-distill lặp vô
  tận, tốn Gemini call lặp lại, memory episode không bao giờ gọn đi.**
- **Hệ B có bug cụ thể, rõ ràng:** filter chống re-distill (`"distilled" not in tags`)
  đọc một cờ mà **không có đoạn code nào ghi vào** → filter luôn pass-through →
  dedup vô hiệu 100%.

Đây đúng là triệu chứng user mô tả: *"deepseek nén xong mà cứ không chịu lưu lại
ở đâu đó lần sau tái sử dụng mà cứ viết lại"* — chính xác hơn: nén thì có lưu
output, nhưng **không đánh dấu nguồn đã nén nên lần sau nén lại y hệt.**

> Lưu ý thuật ngữ: curator Eris dùng **Gemini Web** (`GeminiWebUserProfileAdapter`),
> không mượn account DeepSeek — xem `memory_ai_curator.py:_call_llm` dòng ~470-476
> và knowledge doc. "DeepSeek curator" trong mô tả user là cách gọi dân dã; thực
> thể distill memory là Gemini Web curator.

---

## (a) Chuỗi gọi curator/dreamer/distill + khi nào chạy

### Hệ B — MemoryAICurator (episodic → semantic)

```
MemoryGCService (daemon thread, chu kỳ ~10 phút)
  runtime/coordinator_bootstrap.py:811-822  → build_memory_gc_service(...).start()
  runtime/memory_gc_service.py:33           _DEFAULT_INTERVAL_SEC = 10*60
  runtime/memory_gc_service.py:186          _enabled = env ERIS_MEMORY_GC_ENABLED (default True)
  runtime/memory_gc_service.py:320-351      _loop(): startup delay 120s, chạy lặp
  runtime/memory_gc_service.py:387-392      MemoryMaintenanceRunner(...).run(budget="normal", destructive=True)
        │
        ▼
MemoryMaintenanceRunner.run()
  memory/memory_maintenance.py:96-106       nếu budget in {normal,deep} và có llm_service:
  memory/memory_maintenance.py:99-101         curator = MemoryAICurator(...); curator.run_distillation(budget)
        │
        ▼
MemoryAICurator.run_distillation()
  memory/memory_ai_curator.py:187            items = memory_core.episodic.load()   (EpisodicMemoryStore)
  memory/memory_ai_curator.py:192            clusters = _cluster_episodes(items, limit)
  memory/memory_ai_curator.py:195-205        mỗi cluster ≥3: _distill_cluster → _commit_semantic_fact
        │
        ▼
_commit_semantic_fact()  memory/memory_ai_curator.py:375-404
  → memory_core.commit(request target="semantic_memory")
  → memory/memory_cognition.py:341-343  semantic.apply_commit(request)
  → memory/semantic_memory.py:727+      ... self.save(items)  (atomic_write_json)
```

Chạy: **nền, theo chu kỳ ~10 phút** (không phải mỗi lượt chat). Budget `normal`
trong GC periodic nên nhánh AI curator **luôn kích hoạt** khi có `llm_service`.

### Hệ A — living_user Dreamer (episode → profile)

```
MemoryKernel.maintain()  memory/memory_kernel.py:499-525
  → MemoryMaintenanceRunner.run(...)   (step 1-6, gồm cả Hệ B nếu đi qua đây)
  → nếu living_user.config.auto_dream_on_maintenance (default True): living_user.dream(reason)
        │
        ▼
LivingUserMemoryService.dream()  memory/living_user/service.py:447-479
  service.py:463   episodes = episode_store.recent(limit=12, scope)
  service.py:465   report = dreamer.consolidate(episodes, semantic_operations=..., reason, scope)
  service.py:466   profile_store.decay()
  service.py:468   episode_store.compact()    ← chỉ merge episode >45 ngày, KHÔNG liên quan distill
        │
        ▼
UserProfileDreamer.consolidate()  memory/living_user/dreamer.py:38-59
  dreamer.py:52    result = self.store.apply(ops, checkpoint_reason=f"dream:{reason}")
        │
        ▼
UserProfileStore.apply()  memory/living_user/store.py:117-145
  store.py:142-144   if config.autosave: self.save()   (autosave default True, store.py:38)
  store.py:777-778   save() → atomic_write_json(self.path, self.to_dict())
```

Cũng còn một đường nữa: `consolidate_session(... run_dream=True)`
(`service.py:422-446`) gọi `dreamer.consolidate((saved,), reason="session_end")`
khi kết một session — cùng cơ chế apply+save.

Ngoài ra `MemoryGCService` còn có **living-user curator riêng** (step 3,
`memory_gc_service.py:412-416`, dùng `LivingUserMemoryCurator` trong
`living_user/curator.py` — Gemini Web gom cụm rồi store áp dụng). Đây là lớp
dọn/dedup profile records, không phải distill episode; nằm ngoài trọng tâm
nhưng xác nhận có đường persist qua store.

---

## (b) CÂU TRỌNG TÂM: kết quả distill CÓ persist không?

**CÓ — output được ghi xuống đĩa ở cả hai hệ.** (Một phần: output persist, nguồn thì không.)

Bằng chứng ghi đĩa:

- **Hệ A (profile):** `dreamer.consolidate` → `store.apply(ops)`
  (`dreamer.py:52`) → bên trong `apply`, khi có thay đổi và `config.autosave=True`
  (default, `store.py:38`) gọi `self.save()` (`store.py:142-144`) →
  `atomic_write_json(self.path, self.to_dict())` (`store.py:777-778`). File đích:
  `living_user_profile.json` (`service.py:43` profile_filename).
- **Hệ B (semantic fact):** `_commit_semantic_fact` →
  `memory_core.commit(request)` (`memory_ai_curator.py:393`) →
  `MemoryCognition.commit` route target `"semantic_memory"` →
  `semantic.apply_commit(request)` (`memory_cognition.py:341-343`) →
  trong `apply_commit` có `self.save(items)` cả nhánh merge lẫn tạo mới
  (`semantic_memory.py` quanh dòng 787 trở đi; `save()` dòng 640-660 dùng
  `atomic_write_json`). Curator đếm `distilled += 1` chỉ khi
  `outcome in {"accepted","tentative"}` (`memory_ai_curator.py:398-404`).

→ Vậy phần "LLM trả fact xong bị bỏ đi, không lưu" là **SAI**: fact/profile mới
có đường persist rõ ràng. DreamReport/operations thực sự được commit (không chỉ
trả report rồi caller bỏ qua) — `consolidate` tự gọi `store.apply` bên trong,
không phụ thuộc caller (`dreamer.py:52`).

**Vì sao user vẫn thấy "không lưu, cứ viết lại":** xem (c) và (d). Vấn đề không
nằm ở output mà ở **nguồn**: episode gốc không bị đánh dấu, nên công việc distill
bị lặp lại — biểu hiện ra ngoài giống hệt "nén xong không lưu".

---

## (c) Sau distill, episode gốc có bị xóa/archive/đánh-dấu không?

**KHÔNG — ở cả hai hệ. Đây là mắt xích hỏng.**

### Hệ B (episodic → semantic): dedup có khung nhưng CHẾT

- Filter chống re-distill tồn tại:
  `undistilled = [d for d in dicts if "distilled" not in (d.get("tags") or [])]`
  (`memory_ai_curator.py:259`).
- **Nhưng không có chỗ nào ghi tag `"distilled"` vào episode.** Grep toàn
  `src/memory/**` cho `distilled`: mọi kết quả chỉ là (1) filter đọc ở
  `:259`, (2) field đếm `CuratorResult.distilled` (`:62,70,203`), (3) chuỗi
  note `f"distilled:..."` (`:204`), (4) chữ trong prompt/log. **Không có lệnh
  `tags.append("distilled")` hay `episodic.save(...)` nào sau distill.**
- `_commit_semantic_fact` chỉ ghi **semantic fact mới**, không đụng tới
  `EpisodicMemoryItem` nguồn (`memory_ai_curator.py:375-404`). Episode gốc vẫn
  nằm nguyên trong `episodic_memory.json`.
- `EpisodicMemoryItem` CÓ field `tags` (`episodic_memory.py:258,276`) nên về
  kỹ thuật có thể gắn cờ — nhưng khi commit, tag được đặt cứng là
  `["commit", target]` (`episodic_memory.py:358`), không bao giờ là `"distilled"`.

→ Kết luận Hệ B: **cờ `"distilled"` là code chết. Filter luôn trả về toàn bộ
episode. Mỗi 10 phút GC chạy lại, cùng cụm episode bị cluster lại và distill lại.**

### Hệ A (episode → profile): không hề có khái niệm "đã distill"

- `dreamer.consolidate` đọc `episode_store.recent(limit=12)` (`service.py:463`),
  tạo ops, apply vào profile. **Không ghi gì ngược lại episode.**
- `UserEpisode` model **không có field `tags`/`distilled`/`consolidated`** nào
  (liệt kê field đầy đủ: `models.py:316-335` — id, session_id, title, summary,
  outcome, topics, entities, decisions, open_loops, user_signals, evidence_ids,
  importance, scope, started_at, ended_at, source, metadata). `to_dict`
  (`models.py:354-375`) cũng không phát ra cờ consolidated.
- `UserEpisodeStore` không có method mark-consolidated. Các method ghi file chỉ
  là: `add` (`episode_store.py:28`), `compact` (merge theo tuổi/similarity,
  `episode_store.py:131-194`), `scrub_evidence` (xóa theo privacy,
  `episode_store.py:196-215`). Không method nào do distill kích hoạt.

→ Kết luận Hệ A: `recent(limit=12)` trả cùng tập episode gần nhất mỗi lần dream.
Chừng nào chúng còn trong top-12 recent, chúng bị feed vào `_model_ops` (gọi LLM
qua `model_adapter.propose_profile_operations`, `dreamer.py:109-132`) lặp lại.
Có `_dedupe` ops (`dreamer.py:148-157`) và store-level dedup
(`store.py` nhánh `duplicate_evidence`/`same_value`) chặn **ghi trùng profile**,
nhưng **không chặn việc gọi LLM distill lại** — token vẫn bị tốn mỗi vòng.

---

## (d) Có re-distill vô tận không?

**CÓ — xác nhận ở cả hai hệ, với hai mức độ.**

- **Hệ B: re-distill vô tận hoàn toàn.** Không cờ nào chặn. Cụm episode có
  summary token-overlap ≥0.40 và ≥3 thành viên (`memory_ai_curator.py:280-286`)
  sẽ bị distill lại mỗi lần GC chạy (~10 phút). Mỗi lần tốn 1 Gemini call/cluster
  (`_distill_cluster` → `_call_llm`, `memory_ai_curator.py:336-345`). Semantic
  store sẽ liên tục nhận commit cùng claim — may là `apply_commit` merge theo
  `fact_key`/similarity nên **semantic file không phình** (merge target,
  `semantic_memory.py` nhánh `_find_merge_target`), nhưng **LLM call thì lặp vô
  ích** và episode store không gọn đi.
- **Hệ A: re-distill lặp trên cửa sổ recent.** `recent(limit=12)` nên khi có
  episode mới đẩy episode cũ ra khỏi top-12 thì cũ thôi bị distill; nhưng episode
  "gần đây + quan trọng" bị distill lại mỗi vòng cho tới khi rơi khỏi cửa sổ.
  `compact()` chỉ dọn episode >45 ngày không open-loop (`episode_store.py:131-137`),
  không giải quyết lặp ngắn hạn.

So với mô tả user ("phình ra vô tận", "episode nên nén thành 1 summary chứ không
kèm evidence/id"): phần episode store **có** cap (`max_items=240`,
`episode_store.py:19`) và `compact` theo tuổi, nên không phình file vô hạn; nhưng
**công việc distill thì lặp vô hạn**, đúng nỗi lo lãng phí token.

---

## (e) Nếu có lỗi thật: thiếu chính xác ở đâu (để fix nhắm đúng)

Xếp theo mức độ chắc chắn và tác động:

1. **[Chắc chắn nhất — Hệ B] Thiếu bước ghi cờ `"distilled"` + save episode sau distill.**
   Vị trí fix: `memory_ai_curator.py:run_distillation` ngay sau
   `committed = self._commit_semantic_fact(...)` thành công (`:202-205`). Cần:
   gắn `"distilled"` (hoặc id cụm) vào `tags` của từng `EpisodicMemoryItem` trong
   cluster rồi `memory_core.episodic.save(items)`. Hiện filter `:259` đã sẵn sàng
   đọc cờ này — chỉ thiếu đường ghi. Đây là **một-dòng-logic bị bỏ quên**, không
   phải thiếu kiến trúc.
   - Phụ: `_cluster_episodes` nhận `dict` qua `to_dict()` (`:255-257`); muốn ghi
     lại cờ phải giữ tham chiếu tới object `EpisodicMemoryItem` gốc, không chỉ
     dict rời.

2. **[Chắc chắn — Hệ A] Thiếu khái niệm "episode đã consolidated".**
   `UserEpisode` (`models.py:316`) không có field cờ; `UserEpisodeStore` không có
   method mark. Fix cần: thêm field (vd `consolidated_at`/`dream_version`) + để
   `dream()` sau `consolidate` ghi lại các `report.episode_ids`
   (`service.py:465`, DreamReport đã trả `episode_ids`, `dreamer.py:54`) và cho
   `recent()`/`_model_ops` bỏ qua episode đã consolidated trừ khi có signal mới.

3. **[Thiết kế — khớp yêu cầu user] Episode nên nén thành summary, bỏ
   evidence/id khỏi payload gửi Root.** Điều này thuộc context_compiler (nằm
   ngoài curator persist), nhưng liên quan: nếu (1)(2) được sửa, episode đã
   distill có thể rơi khỏi context đắt và chỉ còn semantic/profile fact gọn —
   giảm cả token lẫn re-distill. (Chưa truy context_compiler trong điều tra này.)

Không cần "thêm save" cho output (output đã save). Trọng tâm fix là
**mark-consolidated + dedup nguồn**, đúng như user suy đoán về bản chất.

---

## (f) Phần CHƯA XÁC MINH

- **Hệ A và Hệ B dùng kho episode khác nhau — đã xác nhận là HAI kho tách biệt**
  (`EpisodicMemoryStore` ở `memory_cognition.py:213` vs `UserEpisodeStore` khởi
  tạo trong `LivingUserMemoryService`). **Chưa xác minh** hai kho có nội dung
  trùng lặp/đồng bộ hay không (có `auto_sync_semantic`, `service.py:40`); nếu
  trùng, một episode có thể bị distill ở cả hai đường — làm lãng phí nặng hơn.
  Cần đọc đường sync để kết luận.
- **Chưa chạy live.** Mọi kết luận là đọc source checkout hiện tại; chưa quan sát
  GC daemon chạy thật, chưa đếm số Gemini call lặp trong log. Để xác nhận lãng
  phí thực tế, cần xem log `memory_gc` (`memory_gc_service.py:332-348`) qua nhiều
  chu kỳ xem `distilled=` có lặp trên cùng cụm không.
- **"Self updates ~14,5k mỗi lượt" (câu hỏi 6):** liên kết **chỉ là giả thuyết,
  chưa có bằng chứng code trực tiếp.** Phần self_changes_since_bootstrap được
  build ở lớp context/bootstrap mà điều tra này chưa truy. Không khẳng định nó
  do re-distill. Mối liên hệ hợp lý về mặt lý thuyết (công việc lặp lại không
  được chốt) nhưng **chưa xác minh** đường code nối hai thứ.
- **`GeminiWebUserProfileAdapter.create_if_available()`** (`memory_ai_curator.py:473`)
  trả `None` khi service không sẵn → khi đó `_call_llm` trả `None`, distill bị
  skip. **Chưa xác minh** adapter có available trong runtime thật hay không; nếu
  không available, Hệ B thực tế không chạy (không lặp, nhưng cũng không distill).
  Cần kiểm live để biết hệ nào đang thực sự hoạt động.

---

## Phân biệt tầng bằng chứng (theo AGENTS.md)

- **Đọc được trong source (chắc):** cả hai đường có `atomic_write_json` cho
  output; cờ `"distilled"` chỉ được đọc, không được ghi; `UserEpisode` không có
  field cờ consolidated; GC chạy chu kỳ 10 phút budget normal.
- **Suy luận từ source (hợp lý, chưa chạy live):** re-distill lặp mỗi chu kỳ;
  lãng phí Gemini call; semantic file không phình nhờ merge nhưng công việc lặp.
- **Chưa xác minh (cần live/đọc thêm):** liên hệ với self-updates 14,5k; adapter
  Gemini có available thật không; hai kho episode có trùng không; số lần lặp
  thực tế trong log.
