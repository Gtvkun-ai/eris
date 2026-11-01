# Chẩn đoán: vì sao Root không route sang Tutor khi user xin bài học

Ngày điều tra: 2026-11-01. Chế độ: ĐỌC-ONLY (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris`, log live
`C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261101_123410.txt`, và so hash
bản deploy `C:\Users\Gtvkun\Documents\eris`.

---

## Tóm tắt câu trả lời (đọc trước)

**Tutor ĐÃ được wiring đầy đủ vào production chat path, và prompt production CÓ
nhắc tới tutor.** Đây **không** phải lỗi cấu hình bản deploy và **không** phải
thiếu wiring trong source. Năm file routing lõi trùng byte giữa checkout dev và
bản deploy (xem §6), nên hai bản chạy cùng một code.

Nguyên nhân thực: ở mọi lượt user trong phiên live, **model Root tự chọn
`kind=move` (trả lời chat trực tiếp) ngay ở step 1 thay vì chọn
`kind=use_capability capability=tutor`**. Việc phát một "tutor activity" artifact
là **một quyết định của model Root**, không phải một gate tự động bật khi câu
user chứa chữ "bài"/"toán". Prompt cho phép và mô tả tutor, schema cho phép gọi
tutor, registry có tutor — nhưng Root được tự do finalize bằng lời nói, và nó đã
làm đúng như vậy cả ba lần.

Phrasing tiếng Việt của user ("cho tôi một bài phương trình toán", "cho tôi bài
tự giải thích") **không khớp** bất kỳ marker kích hoạt sư phạm nào trong code,
nên ngay cả cơ chế auto-path (vốn chỉ âm thầm *activate* một learning path, chứ
không tự phát activity) cũng không chạy cho các câu đó.

Cảnh báo `whale2api.exe not found` **không liên quan** tới việc Tutor không được
nạp: TutorCapability/LearningService không phụ thuộc gateway đó (xem §5).

**Cần làm gì để Root route sang Tutor:** đây là vấn đề *điều khiển hành vi model*
(prompt bias + trigger từ vựng), không phải vá wiring. Khuyến nghị ở §7.

---

## Bằng chứng

### 1. TutorCapability đăng ký ở đâu — call site production thật

**Call site production (chat path, không phải test fixture):**
`src/runtime/ai_orchestrated/orchestrator.py:768-815`.

- Dòng 768: `from runtime.capabilities import ActionCapability, ResearchCapability, TutorCapability, WorkCapability`
- Dòng 776-780: tạo `TutorCapability(getattr(host, "tutor_executive", None), logger=...)`
  và gán vào `host.tutor_capability`.
- Dòng 806-811: `capability_registry = RootCapabilityRegistry({"tutor": tutor_capability, "work": ..., "research": ..., "action": ...})`.
- Dòng 854: registry được nhét vào `runtime_context["__root_capabilities"]`.

`host.tutor_executive` được wiring tại coordinator production:
`src/runtime/coordinator.py:305-317` gọi `build_tutor_runtime(...)` và gán
`self.learning_service` + `self.tutor_executive`. Composition root:
`src/runtime/tutor/composition.py:26-52`.

Root đọc registry trong agent loop:
`src/runtime/conversation/agent.py:245-247` — lấy `runtime_context["__root_capabilities"]`,
nếu không phải `RootCapabilityRegistry` thì dùng registry rỗng.
Khi model trả `kind=use_capability`, `agent.py:503-506` đọc `capability` và
`arguments`, rồi `_invoke_capability` (`agent.py:684-719`) gọi
`registry.get(name).invoke_for_root(...)`.

→ **Kết luận (đọc source):** Tutor được nạp trong đường chat production, KHÔNG
phải chỉ trong test fixture. Test (`RuntimeModelRootAgent` trong
`test_tutor_learning_*`) dùng cùng `TutorCapability.invoke_for_root`, nhưng với
một Root router giả lập điều khiển được — khác biệt duy nhất là test ÉP router
trả `use_capability`, còn production để model tự quyết.

### 2. Điều kiện nào khiến Root phát "tutor activity" thay vì chat text

Quyết định nằm ở **chính model Root**, không có flag/env bắt buộc.

- Schema `ROOT_BATCH_STEP_SCHEMA` cho phép: `src/runtime/conversation/agent.py:88-92`
  — `kind ∈ {..., "use_capability"}`, `capability ∈ {"tutor","work","research","action"}`,
  `arguments` là object tự do (nơi đặt `operation: "activity"`, `preset: ...`).
- Vòng lặp Root (`agent.py`, nhánh finalize ~dòng 350-360 trong hàm decide):
  `if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say")))`
  → finalize NGAY, không chạy thêm step. Nghĩa là nếu model trả `move` ở step 1,
  không có cơ hội nào khác để chuyển sang tutor trong lượt đó.
- Không có đoạn code nào ép `use_capability` dựa trên từ khóa "bài"/"toán"/"học"
  trong câu user. Việc chọn capability hoàn toàn do model.

`context["teaching_active"]` (allowed key tại `agent.py:742-744`) chỉ là *projection
trạng thái* để model tham khảo; nó không route và không bật tutor.

→ **Kết luận (đọc source):** không có "cầu dao" tự động. Root phải *tự chọn*
`use_capability capability=tutor operation=activity`. Không có env/flag nào phải
bật thêm để tutor khả dụng (ngược lại, `action` mới là capability có điều kiện
"chỉ khi registry đăng ký").

### 3. Prompt production có mô tả operation tutor không — so với prompt test

**CÓ.** `ROOT_SYSTEM_CORE` (`src/runtime/conversation/root_prompt_contract.py:5-...`)
mà production dùng chứa:
- Menu công cụ ngắn: "... rich_chat trình bày nội dung; **tutor hỗ trợ học**."
- "Capability hiện có: **tutor**, work, research, action (chỉ khi registry đăng ký)."
- "Khi learner_continuity có active path, bạn có thể tự dùng
  `kind=use_capability capability=tutor` để học sâu..."
- Hướng dẫn: nếu cần chi tiết arguments thì `kind=read_tool_guide` với guide là
  tên trong menu.

Chi tiết các operation tutor (advise, **activity** với preset
`math.linear|math.fractions|writing.explanation|python.*`, **start_path**,
**spaces**, **switch_path,path_id**, attempts, retention, help, sources, v.v.)
nằm trong *tool guide* tải theo yêu cầu: `src/runtime/conversation/tool_guides.py`
mục `'tutor'`. Model chỉ thấy chi tiết này SAU khi tự gọi `read_tool_guide`.

`agent.py:642-645` — `_system_prompt` **bỏ qua** registry (`del capabilities`) và
trả `ROOT_SYSTEM_CORE` tĩnh ("A stable menu; registry still owns execution
permission"). Nghĩa là danh sách operation tutor KHÔNG được bơm động vào system
prompt; model phải chủ động đọc guide để biết `operation=activity`.

**Phân biệt lane vs cái thực sự nạp (theo bài học runtime):** ở đây module import
*và* được gọi production đều đúng — registry thực sự có mặt trong `runtime_context`
lúc chạy. Điểm khác test không phải ở việc nạp, mà ở việc test điều khiển model
trả `use_capability` còn production phụ thuộc model tự quyết.

### 4. Cảnh báo whale2api.exe có liên quan tới việc Tutor không nạp không

**Không.**
- Log startup (dòng 41): `ERIS_DS2API_ENABLED=1 but whale2api.exe not found` →
  ngay dòng sau runtime fallback sang DS2API web worker `deepseek-flash`
  (dòng 42-49). Root chat vẫn chạy (các lượt `[root-agent] action=move` thành công).
- `build_tutor_runtime` (`composition.py:33-52`) chỉ cần `LearningService` +
  `TutorExecutive` + (tùy chọn) `RuntimeTutorReasoner` khi `model_router` có
  `invoke_structured_worker`. Không tham chiếu gateway whale2api.
- FSRS được import *lazily* và có guard: `src/runtime/learning_core/retention.py:13-24`
  (`readiness()` trả `available:False, mode:"shadow"` nếu thiếu `fsrs`), và
  `service.py` chỉ gọi retention khi `retention_mode == "fsrs"`. Default là
  `shadow` (composition.py:35) nên **thiếu FSRS cũng KHÔNG làm
  `build_tutor_runtime` ném lỗi**. Vì vậy `tutor_executive` gần như chắc chắn
  non-None trong phiên live.
- Log live không có dòng `[tutor-v1] tutor runtime unavailable` (dòng debug ở
  coordinator.py:318-321), phù hợp với việc tutor runtime khởi tạo thành công.

→ Gateway capability (search/thinking của whale2api) độc lập với capability
registry của Tutor.

### 5. Phrasing tiếng Việt có khớp trigger Tutor không

Trigger từ vựng duy nhất trong code là `_explicit_pedagogical_activation`
(`src/runtime/ai_orchestrated/orchestrator.py:447-457`), dùng
`normalize_vi` (`src/runtime/cognition/normalization.py`) rồi khớp các marker:
`chi toi, chi minh, day toi, day minh, teach me, tutor me, help me learn,
muon hoc, dang hoc, muon hieu, giai thich ky/chi tiet/sau, tu goc, ...`

Đối chiếu câu user trong phiên live:
- "cho tôi một bài phương trình toán" → không chứa marker nào → **False**.
- "cho tôi bài tự giải thích" → không chứa marker nào → **False**.
- "liệt kê các môn đang học" → chứa "dang hoc" (đang học) → **True** (nhưng xem bên dưới).

Trigger này CHỈ nuôi cơ chế **auto-path** (`src/runtime/tutor/auto_path.py`):
`maybe_autostart_path` được gọi tại `orchestrator.py` (ngay sau evidence
assembler) và, nếu điều kiện thỏa, chỉ **âm thầm activate một LearningPath**.
Nó KHÔNG phát activity, KHÔNG làm Root nói, KHÔNG ép `use_capability`
(auto_path.py docstring + `maybe_autostart_path` chỉ gọi `learning.activate_path`).
Với "liệt kê các môn đang học", `_intent_to_learn` có thể True, nhưng
`propose_learning_path` yêu cầu planner tạo 3-8 knowledge point hợp lệ; "liệt kê
các môn" không phải chủ đề học nên planner nhiều khả năng trả None → không path.

→ **Kết luận:** user cần hoặc (a) model tự quyết gọi tutor, hoặc (b) dùng cụm
khớp marker ("dạy tôi ...", "tôi muốn học ..."). Câu "cho tôi một bài ..." nằm
ngoài mọi trigger từ vựng, và dù có khớp thì auto-path cũng không tạo ra activity
artifact.

### 6. Bằng chứng live: Root không hề gọi tutor

Log `eris_run_20261101_123410.txt`:
- Dòng 71: `[architecture C] enabled version=ai_orchestrated.v28 ... surface=wording_only
  semantic_authority=conversation_kernel_v12.next_conversation_move single_writer=1`
  → xác nhận đây đúng là path ai_orchestrated V12 đã đọc source.
- Mỗi lượt user đều là **một** `[root-agent] step=1 event_kind=user_turn action=move`:
  dòng 142 (bài phương trình), 199, 258 (liệt kê môn), 308 (bài tự giải thích).
  Không có `read_tool_guide`, `use_capability`, hay step 2.
- Public trace cho thấy Root TỰ soạn nội dung như chat:
  - Dòng 163: `goal=Đưa cho user một bài phương trình để giải, chọn câu có bẫy — 2^x = x² ...`
  - Dòng 276: `goal=Trả lời thẳng rằng tôi không có nguồn nào liệt kê các môn user đang học ...`
  - Dòng 328: `goal=... đưa một bài có toàn bộ lời giải ... tổng harmonic không bao giờ nguyên ...`
- Không có dòng nào chứa `tutor`, `TutorCapability`, `activity`, `ERIS_LEARN`,
  `record_attempt`, `start_path`, `spaces` (grep toàn log).

**So hash dev vs deploy** (5 file routing lõi) — tất cả **SAME**:
```
SAME  src\runtime\ai_orchestrated\orchestrator.py        23C81DD1
SAME  src\runtime\conversation\root_prompt_contract.py   F3892CF9
SAME  src\runtime\conversation\agent.py                  CFC7DA4C
SAME  src\runtime\conversation\tool_guides.py            66B7E1B2
SAME  src\runtime\tutor\composition.py                   E4020634
```
→ Không phải drift bản deploy. Hành vi giống nhau ở cả hai bản.

---

## Kết luận

1. **Không phải lỗi cấu hình deploy, không phải thiếu wiring.** TutorCapability
   được đăng ký vào `RootCapabilityRegistry` trong production chat path
   (`orchestrator.py:806-854`), prompt production liệt kê tutor
   (`root_prompt_contract.py`), schema cho phép gọi tutor (`agent.py:88-92`),
   và tutor_executive được build ở coordinator (`coordinator.py:305-317`). Năm
   file lõi trùng byte giữa dev và deploy.

2. **Nguyên nhân là quyết định của model Root.** Phát activity là một lựa chọn
   `use_capability` mà model phải tự đưa ra; trong phiên live nó luôn chọn `move`
   và tự viết bài toán bằng văn bản. Không có gate từ khóa nào ép chuyển sang
   tutor, và nhánh finalize ở `agent.py` kết thúc lượt ngay khi có `move` ở step 1.

3. **Phrasing là yếu tố góp phần.** "cho tôi một bài phương trình toán" / "cho
   tôi bài tự giải thích" không khớp marker nào của `_explicit_pedagogical_activation`,
   nên auto-path cũng không chạy — mà kể cả chạy, auto-path chỉ activate path chứ
   không tạo activity.

4. **whale2api không liên quan.** Tutor không phụ thuộc gateway đó; FSRS thiếu
   cũng không chặn (shadow mode có guard).

### Phân tầng bằng chứng
- *Yêu cầu sản phẩm:* tài liệu P1 nói Root CÓ operation `tutor: spaces`,
  `tutor: switch_path,path_id`, activity, start_path (mục P1-01/P1-02).
- *Quyết định thiết kế:* `orchestrator.py:771-775` — foreground chỉ *đăng ký*
  capability, để model (DeepSeek) tự quyết gọi gì; không biến router thành
  semantic authority thứ hai.
- *Đọc source:* các call site/schema/prompt nêu trên.
- *Test giả lập:* `test_tutor_learning_*` chứng minh `invoke_for_root` chấm/giao
  bài đúng khi Root router (giả lập) trả `use_capability` — KHÔNG chứng minh
  model thật sẽ tự chọn tutor.
- *Quan sát live:* 4 lượt user, tất cả `action=move`, không có tutor (log 2026-11-01).

---

## Khuyến nghị (không triển khai trong bước này)

Vì lỗi nằm ở *điều khiển hành vi model* chứ không ở wiring, các hướng sửa khả dĩ:

1. **Tăng bias trong prompt khi có tín hiệu học.** Khi
   `_explicit_pedagogical_activation` True hoặc có active learning path, thêm một
   chỉ dẫn mạnh hơn vào context (ví dụ qua `teaching_active`/`learner_continuity`
   đã là allowed key ở `agent.py:742`) nói rõ: khi user xin "một bài/bài tập/bài
   để làm", ưu tiên `use_capability capability=tutor operation=activity` thay vì
   tự soạn đề bằng văn bản. Hiện prompt chỉ nói chung "tutor hỗ trợ học".

2. **Mở rộng tập marker.** Thêm các cụm thực tế user dùng: "cho tôi (một) bài",
   "ra cho tôi bài", "làm bài tập", "bài để tự giải", "bài tự giải thích" vào
   `_explicit_pedagogical_activation` (`orchestrator.py:450-456`). Lưu ý marker
   này hiện chỉ nuôi auto-path; để có tác dụng route cần kết hợp (1).

3. **Cân nhắc một "pedagogy hint" khi câu xin bài tập rõ ràng.** Không tạo
   semantic authority thứ hai (vi phạm design ở §kết luận 2), nhưng có thể đưa
   gợi ý vào `runtime_context` để model dễ chọn tutor. Phải kiểm bằng run live
   vì bias prompt không đảm bảo model tuân theo (bài học runtime: prompt ủng hộ
   một hành vi vẫn có thể bị model bỏ qua).

4. **Thêm observability.** Log khi registry có tutor nhưng model chọn `move` cho
   câu có vẻ xin bài, để đo tần suất "miss" trước/sau khi chỉnh prompt. Hiện
   không có dòng log nào phân biệt "model không gọi tutor" với "tutor không khả dụng".

**Lưu ý kiểm chứng:** mọi thay đổi trên phải xác nhận bằng phiên live thật (model
DeepSeek + delivery), không chỉ bằng test với router giả lập — vì bản chất vấn đề
là lựa chọn của model, thứ mà test fixture đang ép cứng chứ không tái hiện.
