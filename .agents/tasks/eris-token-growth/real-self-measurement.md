# Đo khối Self/memory của Root trên MEMORY THẬT

Ngày đo: theo lần chạy `measure_real_self.py` gần nhất.
Phương pháp: đọc-only. Script copy nguyên thư mục `memory/core` thật sang một
thư mục temp rồi trỏ mọi store vào bản copy, nên **không ghi đè file store thật**.
Không gọi LLM, không build app, không sửa code sản phẩm. Số liệu thô nằm ở
[`real-self-measurement.raw.json`](real-self-measurement.raw.json); script ở
[`measure_real_self.py`](measure_real_self.py).

Ký tự = `len(json.dumps(..., ensure_ascii=False, separators=(",",":")))` — đúng
cách runtime serialize prefix Self. Token = `llm.token_budget.estimate_tokens`
(heuristic chars/3 + overhead; là **ước lượng**, không phải token thật của model).

Report chỉ ghi KÍCH THƯỚC (ký tự/token/số record), không dán nội dung cá nhân.

## (a) Đường dẫn store thật tìm được

Base dir thật resolve giống `vision.py`: `ErisHome` → `~/Documents/ErisLive`
(trừ khi set env `ERIS_HOME`), rồi `/memory/core`. Thực tế:

`C:\Users\Gtvkun\Documents\ErisLive\memory\core`  (tồn tại, có dữ liệu thật)

File liên quan tới khối Self (byte trên đĩa):

| File | Bytes | Vào Self qua |
|---|---:|---|
| `living_user_profile.json` | 156 249 | living_user.profile |
| `living_user_episodes.json` | 27 727 | living_user.recent_episodes (qua rollup view) |
| `living_user_actions.json` | 6 752 | living_user.actions |
| `living_user_episode_rollups.json` | *(không tồn tại)* | episode_recap (nên rỗng) |
| `semantic_memory.json` | 4 946 | memory_state (nhánh khác, chưa đo riêng) |
| `relational_memory.json` | 1 047 | memory_state (nhánh khác) |
| `episodic_memory.json` | 763 | memory_state (nhánh khác) |
| `affective_residue_memory.json` | 34 | memory_state (nhánh khác) |
| `repair_memory.json` | 34 | memory_state (nhánh khác) |
| `tom_history.json` | 61 | memory_state (nhánh khác) |
| `agent_mind.json` | 11 076 | memory_state.agent_mind |
| `active_state_snapshot.json` | 9 268 | memory_state.active_state |

Lưu ý: byte trên đĩa KHÁC kích thước vào prompt. `living_user_profile.json`
nặng 156 KB trên đĩa nhưng chỉ **11 record** và sau khi `snapshot(limit=80)` +
cắt metadata còn ~2,8 KB vào prompt. 156 KB phần lớn là lịch sử/nội bộ của store,
không phải thứ đẩy vào Root. Các file như `living_user_trace.jsonl` (1,28 MB),
`memory_feed_trace.jsonl` (610 KB), `inner_diary*.json`, `anchor_journal.jsonl`
là nhật ký/trace nội bộ, **không đi vào prompt Self** — chúng không giải thích
token hội thoại, chỉ là dung lượng đĩa.

## (b) Bảng ký tự/token theo từng phần Self — DỮ LIỆU THẬT

Nhánh `living_user` dựng đúng như `_read_self`: `service.summary(limit=80)` rồi
overlay `episode_prompt_view()`, sau đó chạy `project_self_view()` thật.

### Dạng HIỆN TẠI (sau khi đã cắt metadata)

| Phần Self | Ký tự | Token (ước) |
|---|---:|---:|
| living_user.profile | 2 830 | ~947 |
| living_user.recent_episodes | 2 (`[]`) | ~4 |
| living_user.episode_recap | 2 (`""`) | ~4 |
| **living_user.actions** | **4 782** | **~1 598** |
| **living_user TỔNG (projected)** | **7 675** | **~2 562** |

### Dạng NẶNG CŨ (không qua compact_profile/compact_episode) — cùng dữ liệu thật

| Phần Self | Ký tự | Token (ước) |
|---|---:|---:|
| living_user.profile (raw to_dict) | 9 072 | ~3 028 |
| living_user.recent_episodes (raw `recent(limit=8)`, 8 ep) | 7 423 | ~2 478 |
| living_user.actions (không có pass compact) | 4 782 | ~1 598 |

### Bản vá cắt được bao nhiêu trên dữ liệu thật

- **Profile:** 9 072 → 2 830 ký tự. Cắt được **6 242 ký tự (~69%)** nhờ bỏ
  `evidence_ids`, 4 epoch timestamp và `metadata` khỏi mỗi record + gom default.
- **Episodes:** dạng cũ raw 8 episode = 7 423 ký tự. Đây chính là khối ~7,4k
  mà bạn than phiền. Hiện tại nó **= 0** (xem mục c bên dưới), nên phần này đã
  được dọn triệt để bởi đường rollup/fading mới — không còn nhồi 8 episode kèm id.
- **Actions:** **chưa được cắt gì** — 4 782 ký tự ở cả hai dạng. `project_self_view`
  không chạy `compact_*` cho actions.

## (c) Số record / episode thật

| Chỉ số | Giá trị thật |
|---|---:|
| Profile record (snapshot limit=80) | **11** |
| Profile record tổng trên đĩa | 11 |
| Episode tổng trên đĩa | 17 |
| Episode vào recent_episodes của prompt | **0** |
| episode_recap | rỗng (không có file rollup) |
| Commitments (actions) | 7 (tất cả `active`) |
| Goals / Workflows | 0 / 0 |

Đối chiếu con số bạn từng báo ("38 record / 8 episode"): hiện store thật chỉ còn
**11 profile record** (không phải 38) và **17 episode** lưu trữ nhưng **0 episode
vào prompt** (không phải 8). Khối "8 episode kèm evidence" là **dạng cũ** đã bị
thay. Không có bằng chứng 38 record ở checkout/thời điểm này; có thể số 38 là của
phiên/trạng thái trước đã được nén/decay, hoặc đếm gộp cả phần khác — chưa kiểm
chứng được từ dữ liệu hiện tại, ghi nhận là chưa đối chiếu được.

## (d) Chỗ nào còn nặng nhất và có dọn được không

Trong nhánh living_user (phần vừa sửa), xếp theo ký tự thật:

1. **actions — 4 782 ký tự (~1 598 token): nặng nhất, và CHƯA được cắt.**
   - 7 commitment `active`; mỗi record vẫn mang `evidence_ids`, `created_at`,
     `updated_at`, `completed_at`, `due_at`, `metadata`, `scope`.
   - Đo thật: **1 697 ký tự** trong khối actions là các field audit/provenance
     — đúng loại field mà `compact_profile`/`compact_episode` đã bỏ ở hai nhánh
     kia. Chạy cùng kiểu `compact_*` cho actions sẽ cắt ~1,7k ký tự (~35% khối
     actions) mà **không** đụng tới title/action/status/next_actions — tức không
     mất "điều đáng kể", chỉ bỏ id và mốc epoch thô.
   - `snapshot()` còn gồm `include_inactive=True` (completed/cancelled/archived).
     Ở store này hiện 0 record inactive nên không ảnh hưởng ngay, nhưng về sau
     actions sẽ phình theo lịch sử completed nếu không lọc status khi vào prompt.
   - **Kết luận: đây là chỗ dọn được rõ nhất tiếp theo** — áp đúng pattern cut
     metadata đã dùng cho profile/episode sang actions, và cân nhắc chỉ đưa
     record còn mở (active/blocked) vào prompt.

2. **profile — 2 830 ký tự (~947 token): đã được cắt tốt.** Còn room nhỏ nếu
   muốn, nhưng mỗi record đã chỉ còn path/value + qualifier nhẹ. Không nên cắt
   sâu hơn vì sẽ chạm "điều đáng kể".

3. **recent_episodes / episode_recap — 0 ký tự hiện tại.** Đường fading đang
   hoạt động đúng hướng: KHÔNG nhồi 8 episode kèm evidence nữa.
   **Nhưng phát hiện một tác dụng phụ cần biết (đo được, không suy đoán):**
   cả 17 episode đều **73–81 ngày tuổi**, trong khi `recent()` chỉ giữ episode
   `<= recent_days (7 ngày)`, và `render()` chỉ phát recap khi có entry rollup
   hợp lệ. Vì **không có file `living_user_episode_rollups.json`** (maintenance
   rollup chưa từng chạy/commit trên store này), nên Root **không thấy episode
   nào lẫn recap nào** — ký ức quá khứ hiện không tới Root qua nhánh này.
   Đây là điều cần kiểm ở bước sau: xác nhận maintenance có thực sự gọi
   `rollup_episodes()` và ghi được file rollup; nếu không, "nhớ mơ hồ quá khứ"
   mà bạn muốn sẽ rỗng thay vì có recap ngắn. Việc này nằm ngoài phạm vi đo
   token (đo xong: phần này nhẹ), nhưng là rủi ro về *mất ký ức*, không phải *token*.

### Ràng buộc sản phẩm có bị vi phạm không

Cắt actions theo kiểu bỏ `evidence_ids`/epoch/`metadata` **không** vi phạm
`SELF_BOOTSTRAP_INSTRUCTION` (root_session_projector.py): instruction yêu cầu
Root thấy đủ belief trái chiều/giá trị yếu/khuynh hướng chưa chắc trong Self và
không tự chọn top-k. Các field audit của actions không phải belief — chúng là
id/mốc thời gian nội bộ, không định hướng câu trả lời. Giữ nguyên title/action/
status/next_actions là giữ nguyên "điều đáng kể". Vậy việc cắt metadata actions
cùng loại với bản vá profile/episode, tương thích ràng buộc sản phẩm.

## (e) Những gì CHƯA đo được (ghi rõ lý do)

- **mind_state:** cần `ai_state_reducer.snapshot().to_dict()` từ một
  `RuntimeCoordinator` đang chạy. Không dựng lại được chỉ từ file `memory/core`,
  nên chưa đo. Đây có thể là phần nặng của Self prefix nhưng cần runtime sống để
  đo — không nâng thành con số phỏng đoán.
- **subject_self:** cần `host.subject_service.self_view()` từ runtime; không có
  file store độc lập để đọc. Chưa đo.
- **memory_state các lớp khác** (semantic/episodic/relational/procedural/
  affective/repair/belief/worldview/... + agent_mind + active_state): đi vào Self
  prefix qua `MemoryCognitionCore.load()` nhưng nằm ngoài nhánh living_user mà
  script này cô lập. Chưa đo kích-thước-vào-prompt của chúng; chỉ có byte trên
  đĩa ở bảng (a). Đáng chú ý: `agent_mind.json` (11 KB) và `active_state_snapshot.json`
  (9,3 KB) có thể đóng góp đáng kể — nên đo tiếp bằng cách dựng
  `MemoryCognitionCore(real_base).load()` đầy đủ (script hiện chỉ dựng nhánh
  living_user để tránh nạp embedding/registry nặng).

## Tóm tắt một dòng

Trên memory thật: nhánh living_user vào Root ≈ **7,7k ký tự / ~2,6k token**.
Bản vá đã cắt profile ~69% và episode xuống 0. **Chỗ dọn được tiếp theo rõ nhất
là `actions`** (nặng nhất còn lại, ~1,7k ký tự audit chưa cắt). Rủi ro kèm theo
cần kiểm riêng: episode fading hiện trả rỗng vì không có rollup — là vấn đề mất
ký ức, không phải token.
