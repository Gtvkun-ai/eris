# Live Self prefix readout — đọc log runtime thật

Ngày đọc log: điều tra READ-ONLY. Không sửa code/log/store, không build, không restart.

## (0) Tóm tắt câu trả lời

Trên request LIVE của bản portable `C:/Users/Gtvkun/Documents/eris/Eris.exe` (phiên
15:06:40–15:15:38 ngày 2026-11-03), khối **Self prefix đã co lại đáng kể** so với con số
~140k ký tự user báo lúc đầu: Self prefix chỉ còn khoảng **37.000–38.000 ký tự**
(`full Self loaded ... chars=37383 → 38226`), và tổng request đỉnh khoảng
**28.000–29.000 token ước lượng** (`estimated_tokens` đỉnh 28997, estimator `chars3`).
Không thấy con số 140k nào trong phiên này.

Phần nặng nhất của Self prefix, xếp theo leaf thật (bỏ container cha để tránh đếm trùng):

1. **`living_user.profile` = 9.568** ký tự — nặng nhất.
2. **`self.mind_state` = 7.182 → 10.732** ký tự (runtime-only, tăng khi phiên ấm; lần đầu đo được số thật).
3. **`memory.internal_state` = 5.828** ký tự (chỉ xuất hiện ở snapshot prime đầu tiên; biến mất ở các snapshot sau).
4. **`memory.agent_mind` = 4.189** ký tự.
5. **`memory.semantic_memory` = 3.749** ký tự.
6. **`living_user.actions` = 3.328** ký tự.
7. **`memory.active_state` = 96 → 3.085** ký tự (nhỏ lúc startup, nở sau khi có hoạt động).
8. **`memory.procedural_memory` = 1.119** ký tự.
9. **`self.subject_self` = 248** ký tự (runtime-only, giờ mới đo được — rất nhỏ, KHÔNG phải phần nặng).

Hai nhánh runtime-only mà đo tĩnh trước không đo được:
**`mind_state` nặng thật (7k–11k)** nhưng **`subject_self` nhỏ xíu (248)**.

Bản portable đang chạy **ĐÃ nhận các bản vá cắt**: `agent_mind`=4189, `active_state` đỉnh 3085,
`semantic_memory`=3749 — tất cả khớp (hoặc thấp hơn) số "sau cắt" trong brief.

## (a) File log đã đọc + timestamp

- Đường dẫn: `C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261103_150640.txt`
  (thư mục là `Documents\eris\logs` — số nhiều, không phải `Documents\eris\log`).
- Kích thước: 51.138 byte. File run log mới nhất theo LastWriteTime trong thư mục.
- Header file: `Bat dau : 2026-11-03 15:06:40`, `Exe : C:/Users/Gtvkun/Documents/eris/Eris.exe`,
  `Editor : False`, `OS : Windows`.
- Kết thúc phiên: `15:15:38 [RunLogger] Ket thuc phien chay.` (thoát sạch qua context-menu
  exit, không crash). → Đây là phiên **vừa chạy xong**, đúng loại user yêu cầu đọc.
- Trong cùng thư mục còn `eris_observability.jsonl` (142 MB, cập nhật gần như cùng lúc) —
  KHÔNG đọc file này vì run log .txt đã chứa đủ các dòng `[root-session]` cần thiết và
  file jsonl quá lớn + có thể chứa transcript cá nhân.

Xác định process/bản chạy: run log ghi rõ exe portable `Documents/eris/Eris.exe` và
`[root-session]` do `vision.py` (PID 21944) phát. Phù hợp bài học runtime: đã xác định
đúng file/process/bản runtime trước khi kết luận.

## (b) Dòng `self_component_chars` nguyên văn (lần gần nhất)

Lần ghi `self_component_chars` GẦN NHẤT trong file là lúc **15:10:55.942** (sau đó
không có dòng self_component_chars nào nữa trong phiên; các lượt sau chỉ log `request_size`
với Self cache đã prime):

```
15:10:55.942 [root-session] self_component_chars={"self.mind_state":10682,"self.subject_self":248,"self.memory_state":25631,"self.long_term_memory":255,"memory.event_ledger":2,"memory.active_state":3085,"memory.episodic_memory":2,"memory.semantic_memory":3749,"memory.relational_memory":2,"memory.affective_residue_memory":2,"memory.procedural_memory":1119,"memory.repair_memory":2,"memory.memory_candidate":2,"memory.belief_core":2,"memory.worldview_memory":2,"memory.sociocultural_memory":2,"memory.spatial_memory":2,"memory.temporal_rhythm_memory":2,"memory.body_rhythm_memory":2,"memory.tom_history":2,"memory.self_continuity":2,"memory.homeostatic_baseline":2,"memory.agent_mind":4189,"memory.living_user":12919,"memory.persisted_mind_variants":123,"living_user.profile":9568,"living_user.actions":3328}
```

Snapshot prime ĐẦU TIÊN (15:06:53, lúc startup, để đối chiếu biến thiên):

```
15:06:53.275 [root-session] self_component_chars={"self.mind_state":7182,"self.subject_self":248,"self.memory_state":28338,"self.long_term_memory":255,"memory.event_ledger":2,"memory.active_state":96,"memory.episodic_memory":2,"memory.semantic_memory":3749,"memory.relational_memory":2,"memory.affective_residue_memory":2,"memory.procedural_memory":1119,"memory.repair_memory":2,"memory.memory_candidate":2,"memory.belief_core":2,"memory.worldview_memory":2,"memory.sociocultural_memory":2,"memory.spatial_memory":2,"memory.temporal_rhythm_memory":2,"memory.body_rhythm_memory":2,"memory.tom_history":2,"memory.self_continuity":2,"memory.homeostatic_baseline":2,"memory.agent_mind":4189,"memory.living_user":12919,"memory.internal_state":5828,"living_user.profile":9568,"living_user.actions":3328}
```

Có 4 lần log `self_component_chars` trong phiên: 15:06:53, 15:08:55, 15:09:22, 15:10:16, 15:10:55.
Biến thiên chính giữa các lần: `mind_state` 7182→10732→10682, `active_state` 96→3085,
`internal_state` 5828 (chỉ lần đầu) rồi thay bằng `persisted_mind_variants` 123 từ 15:09:22.

### Lưu ý cấu trúc để đọc đúng bảng (quan trọng, tránh đếm trùng)

Theo source `src/runtime/conversation/root_session.py` dòng ~300–311, breakdown log 3 prefix
trên các object LỒNG NHAU, nên có cha-con:

- `self.*` = các key cấp cao nhất của Self → **`self.memory_state` là CONTAINER CHA**, bằng tổng
  gần đúng của mọi `memory.*`.
- `memory.*` = các key bên trong `memory_state` → **`memory.living_user` là CHA** của `living_user.*`.
- `living_user.*` = các key bên trong `memory_state.living_user` (profile + actions).

→ Để không đếm trùng: dùng các key `self.*` làm leaf, trong đó `self.memory_state` được mở ra
thành các `memory.*`, và `memory.living_user` được mở ra thành `living_user.*`.

## (c) Bảng kích thước từng key, xếp giảm dần (snapshot gần nhất 15:10:55)

### Bảng LEAF thật (đã bỏ container cha self.memory_state và memory.living_user)

| Hạng | Key (leaf) | Ký tự | Ghi chú |
|---|---|---:|---|
| 1 | `living_user.profile` | 9.568 | Hồ sơ Living User — nặng nhất |
| 2 | **`self.mind_state`** | **10.682** (đỉnh 10.732) | **runtime-only, giờ mới đo; tăng theo phiên** |
| 3 | `memory.agent_mind` | 4.189 | đã qua bản vá cắt |
| 4 | `memory.semantic_memory` | 3.749 | |
| 5 | `living_user.actions` | 3.328 | 8 action gần nhất |
| 6 | `memory.active_state` | 3.085 | nở từ 96 lúc startup |
| 7 | `memory.procedural_memory` | 1.119 | |
| 8 | `self.long_term_memory` | 255 | |
| 9 | **`self.subject_self`** | **248** | **runtime-only, giờ mới đo — RẤT NHỎ** |
| 10 | `memory.persisted_mind_variants` | 123 | chỉ xuất hiện khi phiên ấm |
| 11 | `memory.event_ledger` + 17 nhánh memory rỗng | 2 mỗi cái | tất cả `=2` (object rỗng `{}`/`[]`) |

> Ở snapshot prime đầu tiên 15:06:53, thay vì `persisted_mind_variants` có
> **`memory.internal_state` = 5.828** (sẽ xếp hạng 3 nếu tính snapshot đó). Nhánh này
> biến mất ở các snapshot sau — cần xác minh thêm vì sao (xem mục g).

### Nhấn mạnh hai nhánh runtime-only (brief yêu cầu)

- **`mind_state`**: 7.182 ký tự lúc startup → **10.732 ký tự** khi phiên ấm. Đây là phần
  tĩnh-trước-đây KHÔNG đo được; giờ xác nhận nó **nặng thật**, đứng thứ 2 và đang tăng.
- **`subject_self`**: **248 ký tự** — rất nhỏ, không đáng lo, KHÔNG phải nguồn phình.

### Bảng CONTAINER (để tham chiếu, KHÔNG cộng chung với leaf)

| Key container | Ký tự | Là tổng của |
|---|---:|---|
| `self.memory_state` | 25.631 (đỉnh startup 28.338) | toàn bộ `memory.*` |
| `memory.living_user` | 12.919 | `living_user.profile` + `living_user.actions` (+overhead) |

## (d) `request_size` tổng (message_chars + estimated_tokens)

`request_size` là payload gửi model Root. `message_chars[1]` chính là Self prefix.

Lần `request_size` có full Self lớn nhất (15:13:58, phiên ấm, 11 message):

```
15:13:58 [root-session] request_size messages=11 message_chars=[10207, 38176, 42, 96, 35, 92, 39, 196, 280, 178, 37438] estimated_tokens=28970 estimator=chars3
```

Đọc các phần tử:
- `message_chars[0]` = **10.207** = system prompt.
- `message_chars[1]` = **38.176** = **Self prefix** (khớp `full Self loaded ... chars=38176` ở 15:11:00).
- Các phần tử nhỏ (42, 96, 35, 92, 39, 196, 280, 178) = các lượt chat/ack ngắn.
- `message_chars[-1]` = **37.438** = bản chiếu lịch sử/turn cuối (projection) — gần bằng Self prefix.
- Tổng ký tự ≈ **86.777**; `estimated_tokens=28970` (estimator `chars3` ≈ chars/3).

Đỉnh `estimated_tokens` trong phiên = **28997** (15:13:13). Các lần prime 2-message
(`request_size messages=2`) chỉ ~15.000–16.000 token.

**Đối chiếu con số ~140k user báo ban đầu:** KHÔNG tái hiện trong phiên này. Tổng ký tự
request đỉnh ≈ 87k, và Self prefix đơn lẻ chỉ ~38k. Nếu 140k là số cũ trước các bản vá cắt,
thì bản portable hiện tại đã nhỏ hơn rõ rệt. (Chưa có log cũ 140k trong tay để so trực tiếp —
xem mục g.)

## (e) Bản portable đang chạy ĐÃ nhận các bản vá cắt chưa?

**ĐÃ nhận.** Đối chiếu với số "sau cắt" trong brief:

| Thành phần | Số "sau cắt" (brief) | Số LIVE đo được | Kết luận |
|---|---:|---:|---|
| `agent_mind` | ~4.189 | **4.189** | Khớp chính xác → đã vá |
| `active_state` | ~3.102 | 96 → đỉnh **3.085** | Khớp (≤ ngưỡng) → đã vá |
| `semantic_memory` | ~1.646 | **3.749** | LỚN hơn số brief (xem ghi chú) |
| `living_user` (profile) | ~7.675 (cả living_user) | profile 9.568 / living_user 12.919 | Xem ghi chú |

Ghi chú:
- `agent_mind` khớp đúng từng ký tự với số sau-cắt → bằng chứng mạnh rằng bản portable
  đang chạy KHÔNG phải bản cũ chưa vá (nếu cũ, agent_mind sẽ lớn hơn 4189).
- `semantic_memory`=3749 LỚN hơn ~1646 trong brief. Hai khả năng: (1) ngưỡng brief đo ở
  trạng thái store khác; (2) semantic đã tích thêm nội dung thật giữa các phiên. Đây là
  nội dung động theo store, không nhất thiết là "chưa vá". Cần đối chiếu commit/bản vá
  cụ thể của semantic để kết luận chắc.
- `memory.living_user`=12.919 (profile 9.568 + actions 3.328) cao hơn mốc ~7.675 trong
  brief. Đây là **phần nặng nhất thật sự** của request LIVE và là ứng viên cắt tiếp theo.

→ Theo bài học runtime ("sửa source dev không chứng minh bản portable đã nhận"): ở đây
agent_mind khớp đúng số sau-cắt là bằng chứng bản portable ĐÃ nhận vá agent_mind/active_state.
Nhưng living_user và semantic hiện LỚN hơn mốc brief — không kết luận chúng "chưa vá";
nhiều khả năng là nội dung động của store lớn lên, cần đối chiếu riêng.

## (f) Kết luận: phần nặng nhất thật sự trên request LIVE

Trên request Root LIVE, theo leaf thật:

1. **`living_user.profile` (9.568) + `living_user.actions` (3.328) = ~12.9k** trong container
   `memory.living_user` — **khối Living User Memory là phần nặng nhất của Self prefix.**
2. **`mind_state` (7k → ~10.7k, đang tăng theo phiên)** — phần nặng thứ hai, và là nhánh
   runtime-only trước đây không đo được. Đáng chú ý vì nó TĂNG trong phiên (7182→10732),
   nên là rủi ro phình theo thời gian chạy.
3. `agent_mind` (4.189), `semantic_memory` (3.749), `active_state` (lên tới 3.085).

`subject_self` (248) KHÔNG phải vấn đề. 18 nhánh memory khác đều rỗng (`=2`), không tốn gì.

Ngoài Self prefix, `request_size` còn một message cuối ~37k (history projection) gần bằng
Self prefix — tổng request ~87k ký tự / ~29k token. Nếu muốn giảm token Root, hai đòn bẩy
lớn nhất là: (a) **nén/cắt `living_user` (profile+actions)**, (b) **chặn `mind_state` phình
theo phiên**, (c) rà message history projection cuối (~37k) vì nó lặp lại gần như toàn bộ Self.

## (g) Điều CHƯA xác minh (ghi rõ)

1. **Vì sao `internal_state` (5.828) chỉ có ở snapshot prime đầu rồi biến mất**, thay bằng
   `persisted_mind_variants` (123) từ 15:09:22? Chưa đọc source để biết đây là đổi tên field,
   gộp, hay nhánh bị drop. Nếu internal_state bị chuyển vào mind_state thì giải thích một phần
   việc mind_state tăng 7182→10732.
2. **Con số 140k ký tự gốc** không có log trực tiếp trong phiên này để so sánh 1-1; kết luận
   "đã nhỏ hơn" dựa trên số LIVE hiện tại (~38k Self / ~87k tổng), không dựa trên log cũ 140k.
3. **`semantic_memory`=3749 vs ~1646 brief** và **`living_user`=12919 vs ~7675 brief**: chưa
   đối chiếu commit/diff bản vá cụ thể cho hai nhánh này, nên không khẳng định "chưa vá" hay
   "đã vá nhưng nội dung lớn lên". Cần xem bản vá cắt từng nhánh + trạng thái store.
4. **`mind_state` tăng theo phiên**: phiên này chỉ ~9 phút. Chưa đo trên phiên dài để biết
   mind_state có trần hay tiếp tục phình.
5. **File `eris_observability.jsonl` (142 MB)** chưa đọc — có thể chứa breakdown chi tiết hơn
   theo từng record, nhưng run log .txt đã đủ cho mục tiêu và file jsonl rủi ro chứa nội dung
   cá nhân nên bỏ qua theo ràng buộc READ-ONLY/privacy.
6. Phiên có nhiều `writer_failed ... v03_missing_public_surface` và fallback 429/401
   (DS2API rate limit → official API key invalid) — KHÔNG liên quan kích thước Self, chỉ ghi
   nhận để không nhầm nguyên nhân; không điều tra sâu ở task này.

## Phụ lục: các dòng bằng chứng chính (nguyên văn, trích log)

- `15:06:58 [root-session] full Self loaded; sections=4 chars=37383 fingerprint=600fb78a747ba092`
- `15:09:24 [root-session] full Self loaded; sections=4 chars=38226 fingerprint=ad23d4a8dd7629da`
- `15:11:00 [root-session] full Self loaded; sections=4 chars=38176 fingerprint=231eda1395ca059d`
- `15:13:13 [root-session] request_size messages=10 message_chars=[...] estimated_tokens=28997`
- `15:13:58 [root-session] request_size messages=11 message_chars=[10207,38176,42,96,35,92,39,196,280,178,37438] estimated_tokens=28970`

Nguồn cấu trúc breakdown: `src/runtime/conversation/root_session.py` dòng ~300–311
(`_prime` → vòng lặp 3 prefix `self`/`memory`/`living_user`, log `self_component_chars`).
