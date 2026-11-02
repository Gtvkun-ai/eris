# Báo cáo: vì sao khối Self/memory của request Root nặng ~79k ký tự

Điều tra đọc-hiểu, KHÔNG sửa code. Repo: `c:\Users\Gtvkun\Documents\GitHub\eris`.
Mọi kết luận kèm trích `file:dòng`. Phân biệt rõ "đọc được trong source" với "suy đoán".

---

## 0. Trả lời ngắn gọn trước (summary answer)

**Khối Self đi vào request Root ở DẠNG NẶNG `to_dict()` đầy metadata, KHÔNG phải dạng render gọn 1-dòng.**
Đường Root dùng warm-up session (`RootConversationSession`, bật mặc định) nạp **toàn bộ Self dưới dạng JSON nguyên văn**, trong đó `living_user` là kết quả `summary(limit=80)` → `profile_store.snapshot()` → `[r.to_dict() for r in records]`. Mỗi `ProfileRecord.to_dict()` serialize đủ 22 field gồm `evidence_ids` (tới 96 id), ba mốc timestamp, `metadata`, `source`, `confidence`… Episode cũng là `UserEpisode.to_dict()` đầy đủ (summary 1200, các list topics/entities/decisions/open_loops/user_signals, `evidence_ids` tới 128 id).

**Nhánh `render_prompt_context()` gọn (1 dòng/record, bỏ hết evidence/timestamp/metadata) KHÔNG nằm trên đường Root warm-up.** Nó chỉ chạy ở nhánh one-shot `ContextAssembler._memory_context` → `MemoryCognitionCore.render_context` (fallback khi warm-up tắt/lỗi).

**Số 38 record + 8 episode không do compiler** (compiler mặc định `max_items=14`, `max_episodes=4`). Warm-up **bypass hoàn toàn compiler**: nó gọi thẳng `snapshot(limit=80)` + `episode_store.recent(limit=8)`. Vậy 38 là số record thật đang có (≤ trần 80), 8 là đúng trần `recent(limit=8)`.

**Self bị gửi lại NGUYÊN mỗi request.** Projector luôn đặt `bootstrap_content(self_ref.content_json)` (bản Self đầy đủ bất biến lúc prime) vào prefix của **mọi** lượt, rồi cộng thêm `self_changes_since_bootstrap` (chính là "Self updates ~14,5k"). Không có cơ chế tham chiếu-bằng-ID để thay nguyên khối Self — "self_ref" ở đây chỉ là tên biến giữ nguyên văn JSON, không phải một handle phía model.

Ước lượng tiết kiệm: chuyển khối Self sang dạng render gọn sẽ cắt phần lớn 79k (evidence_ids + timestamps + metadata + overhead JSON key lặp lại). Ước lượng thận trọng **~55.000–65.000 ký tự/ request** có thể cắt mà vẫn giữ nội dung lời kể. Chi tiết ở mục 4.

---

## 1. Chuỗi gọi từ request Root xuống memory

### 1a. Host nạp memory_state một lần lúc bootstrap

- `coordinator_bootstrap.py:919` — `self.memory_state = self._load_memory_state()`.
- `model_memory_runtime.py:202-209` — `_load_memory_state()` gọi `self.memory_core.load()`.
- `memory_cognition.py` `MemoryCognitionCore.load()` (khối `def load`) trả dict, trong đó:
  - `"living_user": self.living_user.summary(include_sensitive=False, limit=80)` (dòng cuối của `load()`).

→ `host.memory_state` là một dict **đầy đủ** chứa toàn bộ các store đã `to_dict()`, kèm `living_user` = summary limit 80.

### 1b. living_user.summary dựng khối nặng

- `src/memory/living_user/service.py:548-559` — `summary()`:
  - `records = self.profile_store.snapshot(include_sensitive=include_sensitive, limit=limit)` (limit=80).
  - `episodes = [x.to_dict() for x in self.episode_store.recent(limit=8)]`.
  - trả `{"profile": records, "recent_episodes": episodes, "actions": ..., "replay": ..., "last_dream_report": ..., ...}`.
- `src/memory/living_user/store.py:105-114` — `snapshot()` trả `{"records": [r.to_dict() for r in records]}` (cắt `[:limit]`).
- `src/memory/living_user/models.py` `ProfileRecord.to_dict()` (khối `def to_dict`) serialize 22 field **gồm** `evidence_ids` (list, `__post_init__` cho tới 96 id), `valid_from/valid_until/expires_at`, `created_at/updated_at/last_confirmed_at`, `metadata`, `source`, `scope` object…
- `UserEpisode.to_dict()` tương tự: `summary`(≤1200), `outcome`(≤500), `topics/entities`(≤24×100), `decisions/open_loops`(≤20×260), `user_signals`(≤24×260), `evidence_ids`(≤128).

### 1c. Root warm-up đọc memory_state và nạp nguyên văn vào prompt

- `src/runtime/conversation/root_session.py:_read_self` (dòng ~37-76):
  - lấy `result["memory_state"] = _jsonable(getattr(host, "memory_state"))` (vòng `for key in ("memory_state", "long_term_memory")`), chỉ loại `concept_graph`.
  - bình luận trong chính source dòng ~62-64: *"Không lọc theo topic hoặc lấy top-k. Có thể rất dài ở lần nạp đầu."*
  - trả `project_self_view(result)`.
- `src/runtime/conversation/self_prompt_view.py:project_self_view` chỉ bỏ vài view chẩn đoán trùng (`replay`, `last_dream_report`, `pending_turns`, `active_session_id`, `concept_graph`, `source_turns` trong episode metadata) và gọi `compact_profile`.
- `compact_profile` (`self_prompt_view.py:38-73`) — docstring nói rõ: *"Lossless defaults/aliases; keep every record, value and metadata qualifier."* Nó CHỈ rút field trùng lặp sang `defaults` cho danh sách cố định `scope/status/sensitivity/cardinality/recurrence/tier/source/value_type/valid_until/expires_at`, và alias `updated_at→last_confirmed_at`, `created_at→valid_from`. **`evidence_ids` và `metadata` KHÔNG nằm trong danh sách này → vẫn giữ nguyên trên từng record.**
- `root_session.py:_prime` (dòng ~280-300):
  - `self_context = _read_self(self._host)`
  - `content_json = json.dumps(self_context, ensure_ascii=False, separators=(",", ":"))` — bình luận: *"content_json bất biến; không tóm tắt, chọn top-k hay cắt belief."*
  - đưa vào `messages[1] = {"role":"user", "content": bootstrap_content(content_json)}`.
- `root_session_projector.py:bootstrap_content` bọc thành `{"kind":"root_session_bootstrap","eris_self_full": <self>, "instruction": SELF_BOOTSTRAP_INSTRUCTION}`.

### 1d. Mỗi lượt sau: project_root_messages tái dựng prefix = Self đầy đủ

- `root_session.py:ask` (dòng ~360-400): prefix luôn gồm
  `{"role":"user","content": bootstrap_content(state.self_ref.content_json)}` — tức **bản Self đầy đủ lại được đặt vào mỗi request**.
- `root_session_projector.py:project_root_messages` cũng tự dựng prefix với `bootstrap_content(state.self_ref.content_json)` (docstring: *"Self đầy đủ luôn nằm trong prefix; không lọc top-k"*).

**Chuỗi gọi tóm tắt:**
`coordinator_bootstrap (memory_state=load())` → `MemoryCognitionCore.load()` → `living_user.summary(limit=80)` → `profile_store.snapshot()` + `episode_store.recent(8)` (DẠNG to_dict) → lưu ở `host.memory_state` → `RootConversationSession._read_self` đọc nguyên → `project_self_view/compact_profile` (chỉ nén trùng) → `json.dumps` → `bootstrap_content` → prefix của mọi request Root.

---

## 2. Câu quyết định (Q2): dạng gọn hay dạng nặng?

**DẠNG NẶNG `to_dict()`** — xác nhận bằng call site:

1. `src/memory/living_user/store.py:113` — `"records": [r.to_dict() for r in records]` (snapshot).
2. `src/memory/living_user/service.py:550-551` — `summary()` dùng snapshot đó + `[x.to_dict() for x in self.episode_store.recent(limit=8)]`.
3. `src/memory/memory_cognition.py` `load()` — `"living_user": self.living_user.summary(..., limit=80)`.
4. `src/runtime/conversation/root_session.py:_read_self` — nhét nguyên `host.memory_state` (chứa khối trên) vào `result["memory_state"]`.
5. `src/runtime/conversation/root_session.py:_prime` — `json.dumps(self_context, ...)` rồi `bootstrap_content(...)` vào message user.

→ `evidence_ids`, ba timestamp, `metadata`, `source`, `confidence` **lọt thẳng vào text request gửi lên model** (xem Q5).

**Nhánh gọn KHÔNG dùng cho Root warm-up:** `ProfileContextPacket.render_prompt_context()` (`models.py`) in mỗi record 1 dòng `- path: value[:300] [marker; permission; scope]`, bỏ evidence/timestamp/metadata. Nó được gọi qua `ContextAssembler._memory_context` (`context_assembler.py:387-416`) → `MemoryCognitionCore.render_context` → `recall()` → `ProfileContextPacket`. Đây là đường **one-shot** (fallback), không phải đường warm-up Root đang chạy mặc định.

> Lưu ý phân tầng bằng chứng (theo AGENTS.md): việc warm-up đang CHẠY LIVE trên bản portable của user là **suy đoán từ default env** (`ERIS_ROOT_SESSION_BOOTSTRAP="1"`, `root_session.py:enabled()`), chưa có trace live trong điều tra này. Nhưng con số user báo (38 record + 8 episode, vượt trần compiler 14/4, đúng trần `recent(8)`) **chỉ khớp với đường warm-up**, không khớp đường compiler — đây là bằng chứng gián tiếp mạnh rằng đường warm-up là đường đang tạo ra request 140k.

---

## 3. Bảng nguồn đóng góp vào khối "Self" + ước lượng kích thước

Các kích thước dưới đây suy từ **trần/giới hạn trong code** (đánh dấu "trần") và từ **con số user báo** (đánh dấu "báo cáo"); chưa đo trực tiếp byte request live.

| Nguồn | Call site | Dạng | Ước lượng ký tự | Ghi chú |
|---|---|---|---:|---|
| Profile records (38) | `store.py:113` `to_dict()`, limit 80 | nặng | ~25.600 (báo cáo) | 38 record × ~674 ký tự; phần phình: `evidence_ids` ≤96, 3 timestamp, `metadata`, `source`, `confidence`, key JSON lặp |
| Recent episodes (8) | `service.py:551` `to_dict()`, `recent(8)` | nặng | ~21.600 (báo cáo) | summary ≤1200 + topics/entities/decisions/open_loops/user_signals + `evidence_ids` ≤128/episode |
| actions (goals/commitments/workflows) | `service.py:553` `action_store.snapshot()` | nặng | ~3.300 (báo cáo) | snapshot, không phải render gọn |
| mind_state (reducer) | `root_session.py:_read_self` reducer `to_dict()` | nặng | phần còn lại của 79k | beliefs (kể cả yếu/mâu thuẫn), preferences, habits, feedback, semantic/procedural/affective, mental state. `_read_self` bình luận "không lọc belief, không top-k" |
| subject_self | `root_session.py:_read_self` `subject.self_view()` | nặng | (trong 79k) | loại `generated_at` |
| long_term_memory | `root_session.py:_read_self` vòng for | nặng | (trong 79k) | nạp nguyên nếu có |
| **Tổng Self bootstrap** | | **nặng** | **~79.117 (báo cáo)** | gửi lại NGUYÊN mỗi request |
| self_changes_since_bootstrap | `root_session.py:ask` `_changed(bootstrap, now)` | merge-patch | ~14.505 (báo cáo) | delta cộng THÊM lên Self đầy đủ (xem Q4) |

Nguồn khác ngoài "Self" (để đối chiếu tổng 140k): context hiện tại ~29.504 (grounding/world/vision ở `context_assembler._world_context`, giới hạn `[:20000]`; conversation status; 10 bản ghi lượt trước), system ~14.090, chat history ~2.017, current turn ~701.

> Log có sẵn để đo thật: `root_session.py:_prime` ghi `self_component_chars=<breakdown JSON>` và `[root-session] self_component_chars=...`, và `_call` ghi `request_size messages=... message_chars=[...] estimated_tokens=...`. Dùng hai log này trên bản chạy để thay ước lượng bằng số đo.

---

## 4. Q4 — Self updates là gì + có warm-up/cache/ID-ref không?

- **"Self updates ~14.505" = `self_changes_since_bootstrap`.** `root_session.py:ask` tính `self_delta = _changed(state.bootstrap_self_snapshot, self_now)` (`_changed` = `state_difference` trong `self_prompt_view.py:21-35`, một merge-patch) rồi đặt vào `state.current_step_payload["self_changes_since_bootstrap"]`.
- **Self BỊ gửi lại nguyên mỗi request.** `ask` dựng `prefix` với `bootstrap_content(state.self_ref.content_json)` (Self đầy đủ bất biến), và `project_root_messages` cũng luôn chèn prefix này. Model nhận: **[Self đầy đủ] + [delta] + [window turns] + [step payload]** mỗi lượt. Đây đúng như user mô tả: "Self 79k vẫn gửi lại nguyên, rồi cộng thêm cập nhật 14,5k".
- **Có "warm-up" nhưng KHÔNG phải caching theo nghĩa khỏi-gửi-lại.** `RootConversationSession` warm-up chỉ để prime một lần và "acknowledge" (`_prime` yêu cầu reply `kind=no_reply`). Comment đầu file `root_session.py:1-8` nói rõ: *"gateway hiện không duy trì session bền"* → vì gateway stateless, mọi lượt phải **gửi lại toàn bộ prefix**. `self_ref` (`root_session_projector.py:SelfReference`) chỉ là nơi giữ **nguyên văn `content_json`** phía Eris, không phải handle để model tái dùng mà không nhận lại bytes.
- **Không có đường tham chiếu-bằng-ID cho khối Self.** Từ khóa `self_ref` tồn tại nhưng ngữ nghĩa là "snapshot nguyên văn", không phải reference id gửi lên model. Không tìm thấy cơ chế "gửi mã tham chiếu thay cho Self" trong `src/runtime/conversation` hay `src/memory`.

→ Kết luận Q4: **mỗi lượt trả giá đầy đủ cho Self** (full bootstrap + delta). Warm-up không giảm bytes/lượt; nó chỉ tiết kiệm một round khởi tạo.

---

## 5. Q5 — evidence_ids + metadata có thực sự lọt vào prompt không?

**CÓ, lọt vào.** Bằng chứng call site:
- `store.py:113` `[r.to_dict()]` — `ProfileRecord.to_dict()` (`models.py`) đưa `"evidence_ids": list(self.evidence_ids)` và `"metadata": dict(self.metadata)` vào dict.
- `self_prompt_view.py:compact_profile` chỉ rút field trùng cho danh sách cố định (không có `evidence_ids`, không có `metadata`) → **hai field này không bị loại**.
- `root_session.py:_prime` `json.dumps(self_context)` serialize nguyên dict đó vào message.

Để so sánh, nếu đi đường gọn `render_prompt_context()` thì `evidence_ids/timestamp/metadata` **bị bỏ** (chỉ in `path: value[:300] [marker; permission; scope]`). Nhưng đường gọn không nằm trên warm-up Root.

> "Chưa xác minh" một cách trung thực: episode `to_dict()` trong `summary()` KHÔNG bị `compact_profile` chạm (compact_profile chỉ xử lý `living["profile"]`). `project_self_view` chỉ bỏ `metadata.source_turns` của episode. Vậy `evidence_ids` (≤128) của mỗi episode **vẫn còn** trong prompt. Đã đọc được trong source (`self_prompt_view.py:project_self_view`), không phải suy đoán.

---

## 6. Kết luận: phần nào lãng phí cắt được, phần nào cần thiết

### Lãng phí cắt được (an toàn về mặt nội dung lời kể)
1. **`evidence_ids` trên mọi profile record và episode** — model không cần id audit để cá nhân hóa. 38 record × tới 96 id + 8 episode × tới 128 id là khối lớn thuần overhead. *Ước cắt: ~10.000–18.000 ký tự.*
2. **Ba mốc timestamp float mỗi record** (`created_at/updated_at/last_confirmed_at` + `valid_from/valid_until/expires_at`) — đã có `compact_profile` alias bớt 2 cái, nhưng vẫn còn nhiều. Model chỉ cần "mới/cũ" chứ không cần epoch 16 chữ số. *Ước cắt: ~4.000–7.000.*
3. **`metadata` dict + `source`/`confidence`/`scope` object dạng JSON** trên từng record — phần lớn không đổi hành vi response. *Ước cắt: ~6.000–12.000.*
4. **Overhead JSON key lặp lại** (mỗi record lặp 22 tên field) — dạng render gọn 1-dòng bỏ hết. *Ước cắt: đáng kể, gộp trong các mục trên.*
5. **Gửi lại Self đầy đủ mỗi lượt** — nếu gateway có thể giữ session bền (hoặc dùng prompt caching phía provider), có thể tránh trả giá 79k mỗi request. Hiện gateway stateless nên đây là thay đổi hạ tầng, không chỉ sửa prompt.

### Cần thiết (giữ lại)
- **Nội dung lời kể**: `path` + `value` của record, `title` + `summary` của episode, goals/commitments — đây là chất liệu cá nhân hóa thật.
- **Qualifier tối thiểu cho mỗi record**: `explicitness` (explicit/observed/inferred) và `use_mode`/scope ngắn — cần để model không biến suy đoán thành sự thật (đúng tinh thần `render_prompt_context` và COMPETENCE BOUNDARY trong `models.py`).
- **belief yếu/mâu thuẫn trong mind_state**: theo thiết kế `_read_self` và `SELF_BOOTSTRAP_INSTRUCTION`, Root được yêu cầu thấy cả belief trái chiều. Cắt cái này là đổi **yêu cầu sản phẩm**, không nên làm trong phạm vi "cắt bloat".

### Ước lượng tổng tiết kiệm
Chuyển khối `living_user` (profile + episodes) từ `to_dict()` sang một projection gọn kiểu `render_prompt_context` (giữ path/value/explicitness/scope, bỏ evidence/timestamp/metadata/key-overhead) ước cắt **~20.000–37.000 ký tự** riêng phần living_user (từ ~50k profile+episode xuống ~15–25k). Nếu áp thêm cho mind_state/subject_self cùng nguyên tắc, tổng **~55.000–65.000 ký tự/request** là khả thi trên lý thuyết — nhưng phần mind_state đụng yêu cầu sản phẩm nên cần quyết định riêng.

Nếu giải quyết cả việc **không gửi lại Self mỗi lượt** (prompt caching/session bền phía gateway), mỗi request sau lượt đầu có thể giảm thêm ~79k — đây là đòn bẩy lớn nhất nhưng là thay đổi hạ tầng gateway (`tools/whale2api`), ngoài phạm vi sửa memory/prompt.

---

## 7. Đề xuất (KHÔNG triển khai trong điều tra này)

- **Ưu tiên 1 (rẻ, an toàn):** thêm một projection gọn cho `living_user` trong `_read_self`/`project_self_view` — đưa profile về dòng `path: value [explicitness; scope]` và episode về `title: summary[:420]`, bỏ `evidence_ids`/`metadata`/timestamp. Tận dụng logic sẵn có trong `ProfileContextPacket.render_prompt_context` nhưng áp cho warm-up. Cần kiểm regression test của root_session/self_prompt_view.
- **Ưu tiên 2:** cân nhắc giảm `limit=80`/`recent(8)` trong `summary()` khi dùng cho bootstrap Root, hoặc để warm-up đi qua compiler (14/4) thay vì snapshot thô — nhưng điều này đổi hành vi "Root thấy toàn bộ Self", là quyết định thiết kế.
- **Ưu tiên 3 (hạ tầng):** prompt caching / session bền ở gateway để khỏi resend Self 79k mỗi lượt.

Mọi đề xuất trên cần đối chiếu với yêu cầu sản phẩm "Root đọc toàn bộ Self gồm belief trái chiều" (`root_session_projector.py:SELF_BOOTSTRAP_INSTRUCTION`) trước khi thực thi. Cắt evidence/metadata/timestamp **không** vi phạm yêu cầu đó; cắt belief/top-k thì có.

---

## 8. Giới hạn điều tra (trung thực về bằng chứng)

- Chưa chạy live; chưa đọc log `self_component_chars`/`request_size` thực tế của bản portable. Con số 38/8/79k/14,5k là **user báo cáo**, khớp logic code nhưng chưa đo lại trong lần này.
- Chưa xác minh `ERIS_ROOT_SESSION_BOOTSTRAP` đang bật trên process user đang chạy (chỉ đọc default `"1"` trong `enabled()`).
- `MemoryCognitionCore.load()` đọc bị cắt ở 30k ký tự; đã xác nhận dòng `"living_user": self.living_user.summary(..., limit=80)` nằm trong `load()` qua đọc trực tiếp khối `def load`. Các store khác trong `load()` cũng dùng `to_dict()` (đọc được: `[item.to_dict() for item in ...]` cho semantic/episodic/relational/...).
