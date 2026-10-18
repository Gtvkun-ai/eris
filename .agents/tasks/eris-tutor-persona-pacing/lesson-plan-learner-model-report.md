# Báo cáo điều tra: Learning Path / Lesson Plan + Learner Model trong Eris

Phiên tham chiếu người dùng nêu: `eris-run-20261017-221337` (user hỏi bài logic → nói "chưa hiểu" → Eris giảng lại một phát, không có dấu hiệu learning path/learner model chạy).
Điều tra **READ-ONLY**, không sửa code. Workspace: `c:/Users/Gtvkun/Documents/GitHub/eris`.

Quy ước bằng chứng:
- **[CODE]** = đọc trực tiếp source hiện tại, có file + hàm + dòng.
- **[SUY LUẬN]** = suy ra từ code, chưa trace/live.
- **[KHÔNG TÌM THẤY]** = đã tìm nhưng không có cơ chế tương ứng.

Đã đọc trước:
- `docs/knowledge/2026-10-14-eris-runtime-lessons.md` (bản đồ vai trò + đính chính; nguyên tắc "module import/config có field ≠ chức năng được gọi production"; "background lane chạy xong ≠ nội dung đúng"; curator = Living User Memory).
- `.agents/tasks/eris-tutor-persona-pacing/investigation-report.md` (báo cáo trước: lớp tutor chỉ bật khi có learning path active VÀ Root tự gọi `tutor.advise`).

Báo cáo này **xác nhận và mở rộng** báo cáo trước, đồng thời **đính chính một nhầm lẫn tiềm ẩn**: ngoài hệ `TutorExecutive/LearningService`, còn một hệ dạy THỨ HAI riêng biệt (`PedagogicalRuntime`) *có* xây lesson plan tự động — nhưng cả hai đều KHÔNG chạy trên chat path live hiện tại (hệ 1 không có path được tạo; hệ 2 là dead code chưa có call site + mặc định tắt).

---

## Phân biệt yêu cầu sản phẩm vs trạng thái code

- **Yêu cầu sản phẩm (từ user):** khi dạy, Eris phải có *một kế hoạch dạy liên tục qua nhiều lượt* và *mô hình hóa người dùng* (biết đang ở đâu, bước nào nắm/chưa, lần trước giải thích kiểu A hỏng thì đổi kiểu B). Không phải phản ứng từng lượt rời rạc.
- **Trạng thái code (tóm tắt):** Eris ĐÃ xây sẵn phần lớn *bộ máy* cho cả hai năng lực (learning kernel deterministic, BKT belief, adaptive policy, session hypothesis, một plan-builder sinh curriculum từ model). NHƯNG không có đường nào trong chat path production *tạo/kích hoạt* một learning path, và plan-builder tự động là dead code. Vì vậy ở runtime thực tế, Eris phản ứng từng lượt như chatbot thường — đúng như user quan sát.

---

## Tóm tắt trả lời (A / B / C / D)

### A. LEARNING PATH / LESSON PLAN — được tạo khi nào, bởi ai?

**Có HAI hệ thống path/lesson-plan tách biệt trong code:**

**Hệ 1 — `LearningService` (nguồn chân lý deterministic) + `TutorExecutive`:**
- Path được tạo qua `LearningService.register_path(...)` rồi kích hoạt qua `activate_path(path_id)` [CODE: `src/runtime/learning_core/service.py:122`, `:127`].
- **Các method này KHÔNG có bất kỳ caller nào trong `src/runtime/**` production.** Grep toàn repo: chỉ các test (`src/tests/*`, `src/runtime/learning_core/tests/*`) và một CLI mô phỏng (`src/tools/learner_simulation.py:48,50`) gọi chúng [CODE].
- Service khởi tạo với `self._active_path_id = ""` [CODE: `service.py:112-113`]. `_restore_runtime_state()` chỉ khôi phục con trỏ path nếu SQLite đã có một path được activate từ trước — mà không gì tạo ra lần đầu [CODE: `service.py:258-286`].
- Store KHÔNG seed path mặc định: schema chỉ `CREATE TABLE IF NOT EXISTS ...`, không INSERT path nào [CODE: `src/runtime/learning_core/store.py:51-70, 225`].
- **Không có cơ chế tự tạo path khi user bắt đầu hỏi một chủ đề.** [KHÔNG TÌM THẤY] bất kỳ hàm production nào sinh `LearningPath`/`KnowledgePoint` từ hội thoại cho hệ này.
- Lưu trữ: SQLite tại `default_eris_home()/mentor/learning.sqlite3` [CODE: `store.py:146-147`]. Con trỏ active path/kp lưu ở meta key `learning_runtime_v1` [CODE: `service.py:289-310`]. **Bền qua nhiều phiên** — *nếu* path từng được tạo/activate (hiện không bao giờ xảy ra production).
- Hệ quả đúng như báo cáo trước: `plan_next_move` → `active_path()` trả None → trả None ngay → toàn bộ lớp dạy tắt [CODE: `src/runtime/tutor/executive.py:97-99`].

**Hệ 2 — `PedagogicalRuntime` + `TeachingPlanBuilder` (episode/directive):**
- Hệ này *CÓ* logic tự xây lesson plan: khi user gửi câu chứa marker học tường minh (`"day toi"`, `"teach me"`, `"i want to learn"`, `"giai thich sau"`, ...), `_prepare_pedagogical_turn` gọi `TeachingPlanBuilder.build(...)` để model sinh curriculum, rồi `start_teaching_episode` + `runtime.start_episode(...)` [CODE: `src/runtime/ai_orchestrated/orchestrator.py:447-457` markers, `:498-572` build flow].
- **NHƯNG hệ này không chạy:**
  1. **Dead code ở tầng call-graph:** `_prepare_pedagogical_turn`, `_commit_pedagogical_receipt`, `_notify_pedagogical_audio_finished` chỉ được *định nghĩa* trong `orchestrator.py`, **không có call site nào trong toàn `src/`** (grep toàn repo chỉ trả về các dòng định nghĩa) [CODE]. Không method nào của `AIChatOrchestrator` gọi chúng.
  2. **Mặc định tắt:** gate `_pedagogy_enabled(host)` đọc `runtime_bool("pedagogy","enabled", default=False)` → mặc định False [CODE: `orchestrator.py:441-445`; mapping env `ERIS_PEDAGOGICAL_CONTROLLER_ENABLED` tại `runtime_settings_store.py:374`].
  3. Coordinator ghi chú rõ hệ này "chưa giành hot-path delivery" trong bước migration [CODE: `src/runtime/coordinator.py:303-304`].

**Kết luận A:** Không hệ nào tạo lesson plan trong chat path live. Hệ 1 có đủ API tạo/activate path nhưng không ai gọi; hệ 2 có plan-builder tự động nhưng là dead code + tắt mặc định. Path (hệ 1) bền qua phiên *về nguyên tắc*, nhưng thực tế không bao giờ tồn tại.

### B. LEARNER MODEL / MÔ HÌNH HÓA NGƯỜI DÙNG — thật hay khung rỗng?

**Bộ máy learner model đã được xây khá đầy đủ (không phải placeholder rỗng), nhưng chỉ được nuôi dữ liệu KHI có learning interaction chạy — mà điều đó không xảy ra production.**

- **BKT belief (`p_known`) là mô hình thật, không phải khung rỗng:** `compute_belief(kp_id, evidences, ...)` chạy cập nhật Bayesian từng evidence (prior/guess/slip/learn), chiết khấu evidence trùng interaction/turn, theo dõi `independent_count`, `transfer_observed`, `needs_probe`, `uncertainty` [CODE: `src/runtime/learning_core/belief_model.py:72-145`]. Đây là một BKT replay deterministic thực sự.
- **Mastery** tính lại từ evidence: `compute_mastery(...)` + gate (`service.py:_commit_evidence_locked`, `store.commit_evidence_bundle`) [CODE: `service.py:437-473`].
- **Cập nhật theo câu trả lời user:** có đường thật — `TutorExecutive.observe_response` → `reasoner.assess_response` (model chấm) → nếu đủ confidence (`semantic_commit_confidence` mặc định 0.68) thì `commit_evidence` ghi vào ledger, rồi recompute mastery + belief [CODE: `executive.py:149-218`, `:400-420`]. Guard chặn: verdict `uncertain` hoặc confidence thấp thì KHÔNG commit [CODE: `executive.py:401-403`].
- **Nhớ lỗi trước để đổi chiến thuật (adaptive):**
  - `LearnerHypothesis` lưu misconception theo KP, có lifecycle active/resolved [CODE: `executive.py:_merge_hypotheses:356-385`, `_update_hypotheses_from_assessment:422-455`].
  - `adaptive_policy.choose_adaptive_step(...)` đổi bước dạy theo lịch sử evidence: lỗi tái diễn → `adaptive_repair_repeated_error`; đúng ổn định → `adaptive_independent_practice`/`adaptive_transfer_probe` [CODE: `src/runtime/tutor/adaptive_policy.py:58-120`].
  - `repeated_error_patterns(kp_id)` đọc từ SQLite [CODE: `service.py:475-484`].
  - Đây CHÍNH là năng lực "lần trước kiểu A hỏng thì đổi kiểu B" mà user mong — **đã có code, nhưng chỉ chạy bên trong một tutor session có path active.**
- **Bền qua lượt/phiên:** belief lưu bảng `learner_beliefs`, mastery `mastery_records`, review `review_memory`/`review_items`, interaction `interactions`, session tutor qua `TutorSessionLedger` [CODE: `store.py:70-143`, `executive.py:_persist_session_locked`]. Bền — *nếu* có evidence được commit.
- **Liên kết với Living User Memory (curator):** TÁCH BIỆT về nguồn chân lý nhưng CÓ một chiều đọc. `learner_profile_from_living_user(...)` chỉ ĐỌC các preference user xác nhận (preferred_pace/style, native_language, goal) từ `living_user.profile_store` để tạo `LearnerProfile` [CODE: `src/runtime/tutor/learner_context.py:55-131`]. Evidence/mastery/BKT thì do LearningService/SQLite sở hữu, KHÔNG nằm trong Living User Memory [CODE: docstring `learner_context.py:3-10`]. Khớp bản đồ docs (curator = Living User Memory, learning kernel là store riêng).
- **Phơi bày cho Root:** `learner_continuity_snapshot(...)` chiếu mastery/belief/review ra cho Root đọc [CODE: `learner_context.py:134-182`] và được chèn vào payload Root qua `context_assembler` key `learner_continuity` [CODE: `src/runtime/conversation/context_assembler.py:220-228`, danh sách field `agent.py:813-817`]. **NHƯNG snapshot này trả `{}` khi `active_path() is None`** [CODE: `learner_context.py:142-145`] → ở production luôn rỗng.

**Kết luận B:** Learner model là **mô hình thật, có cập nhật theo câu trả lời, có nhớ lỗi để adapt, bền qua phiên** — về mặt code. Nhưng toàn bộ chỉ được nuôi khi có learning interaction (path active + Root gọi tutor + response được chấm). Vì production không bao giờ có path, learner model thực tế luôn ở trạng thái trống/không được dùng. Root nhận `learner_continuity = {}`.

### C. VÌ SAO KHÔNG KÍCH HOẠT trong phiên user đang học?

Ngưỡng kích hoạt chế độ dạy **quá cao/quá thủ công**, và một nhánh tự động thì chết:

1. **Hệ 1 (tutor) cần hai điều kiện đồng thời, cả hai khó xảy ra tự nhiên:**
   - (a) Có learning path active — mà **không có đường nào tạo path** (mục A). Đây là điều kiện *không thể thỏa* ở production hiện tại.
   - (b) Root tự quyết gọi tool `tutor.advise`. Tool chỉ `available` khi `tutor_capability.executive is not None` [CODE: `orchestrator.py:810-814`]. System prompt còn dặn Root: "tutor.advise chỉ dùng khi cần dạy hoặc đánh giá người học", "nếu có dữ liệu và người học muốn học thì có thể cân nhắc gọi tutor, không tự ép học" [CODE: `src/runtime/conversation/agent.py:665-671`]. `TutorCapability` docstring: "KHÔNG được gọi ở mọi user turn" [CODE: `src/runtime/capabilities/tutor.py:7-10`].
   - Ngay cả khi Root gọi `tutor.advise`, vì không có path → `plan_next_move` trả None → advice `active=False`, `learner_state={}` [CODE: `tutor.py:95-101`]. Root không nhận được gì để vào mạch dạy.
2. **Hệ 2 (pedagogical episode) — nhánh *được thiết kế* để tự kích hoạt khi user nói "dạy tôi/teach me" — nhưng:**
   - `_prepare_pedagogical_turn` (nơi chứa logic nhận marker + build plan) **không được gọi ở đâu** [CODE: không có call site, mục A.2]. Nên dù user gõ đúng marker, không gì chạy.
   - Và gate `pedagogy.enabled` mặc định False.
3. **Hệ quả cho phiên `eris-run-...221337`:** user hỏi bài logic rồi "chưa hiểu". Không có path (hệ 1 im), không có episode (hệ 2 chết). Root chỉ còn đường chat thường → sinh một lời giải lại qua writer, không có learner model, không có kế hoạch nhiều lượt. Đúng quan sát của user. [SUY LUẬN — khớp code; chưa đọc trace nhị phân phiên này].

**Kết luận C:** Có, ngưỡng kích hoạt vừa quá thủ công (hệ 1 cần một hành động tạo path tường minh không tồn tại + Root tự chọn gọi tool) vừa bị đứt dây (hệ 2 tự động nhưng không có call site + tắt mặc định). "Chưa hiểu" một bài ngắn không đủ để bất kỳ hệ nào mở mạch dạy có kế hoạch.

### D. `adaptive_policy.py` cụ thể (file user đang mở)

- **Làm gì:** thuần policy. `choose_adaptive_step(step, *, evidence, repeated_error_count, knowledge_type)` nhận một `TutorStep` do LearningService chọn và *điều chỉnh chiến thuật* dựa trên evidence bền vững đã chấm:
  - Chỉ xét evidence đã chấm thật (`_GRADED`: quiz/feynman/application/paraphrase/misconception), bỏ "em hiểu rồi"/exposure [CODE: `adaptive_policy.py:36-40`].
  - `_recent_independent` chống đếm trùng cùng interaction/turn [CODE: `:43-72`].
  - Lỗi gần nhất → chuyển sang `teach` repair (nếu lặp lại: `adaptive_repair_repeated_error`) [CODE: `:94-100`].
  - Đúng ổn định (≥2 positive, strength≥0.65, chưa chứng minh transfer) → `assess` + `adaptive_transfer_probe`; đã đúng mà đang `teach` → `practice` độc lập [CODE: `:108-120`].
  - Không tự gọi LLM, không nâng mastery, không mở gate — chỉ đổi *cách đi trong bước chưa phát* [CODE: docstring `:4-14`].
- **Được gọi từ đâu:** đúng một call site — `TutorExecutive.plan_next_move`, sau khi `LearningService.next_tutor_step` trả step và có `step.kp_id` [CODE: `executive.py:108-115`].
- **Có wire vào chat live không:** **Có đường dây tới chat (`tutor.advise` → `plan_next_move` → `choose_adaptive_step`), nhưng đường đó không bao giờ tới được `adaptive_policy` ở production** vì `plan_next_move` thoát sớm (`active_path() is None → return None`) TRƯỚC khi gọi `next_tutor_step`/`choose_adaptive_step` [CODE: `executive.py:97-115`]. Vậy `adaptive_policy.py` là **code đúng, đã nối về mặt cấu trúc, nhưng không đạt tới ở runtime** vì thiếu path.
- **Vai trò trong adaptive teaching theo learner model:** đây chính là *bộ chọn chiến thuật thích nghi theo lịch sử evidence* (repair khi lỗi, probe transfer khi vững) — đúng tinh thần "đổi kiểu B khi kiểu A hỏng" user muốn. Nó *đã tồn tại và đúng chức năng*, chỉ thiếu điều kiện tiền đề (có path + có evidence) để phát huy.

**Kết luận D:** `adaptive_policy.py` KHÔNG phải code chết hoàn toàn (có call site thật trong `executive.plan_next_move`), nhưng *không reachable ở production* vì tầng trên (path) không tồn tại. Nó là mảnh ghép "adaptive strategy theo learner model" đã xây xong.

---

## Bằng chứng chi tiết (file + dòng)

### Cấu trúc hai hệ

| Hệ | Thư mục/file chính | Tạo plan? | Wire vào chat? | Trạng thái live |
|---|---|---|---|---|
| Learning kernel + Tutor | `src/runtime/learning_core/*`, `src/runtime/tutor/*` | qua `register_path`/`activate_path` (không caller prod) | `tutor.advise` tool + `learner_continuity` payload | **Im** (không có path) |
| Pedagogical episode | `src/runtime/pedagogical_*.py`, `orchestrator.py` helpers | `TeachingPlanBuilder` auto từ marker | `_prepare_pedagogical_turn` (không call site) | **Dead + tắt mặc định** |

### Hệ 1 — không có đường tạo path [CODE]
- `service.py:122` `register_path`, `:127` `activate_path`, `:258-310` restore/persist con trỏ meta `learning_runtime_v1`.
- Grep `activate_path|register_path|pose_interaction|upsert_path` loại trừ tests: chỉ còn `src/tools/learner_simulation.py` + chính service/store. Không có trong `src/runtime/**` ngoài định nghĩa.
- `executive.py:97-99`: `path = self.learning.active_path(); if path is None: return None`.
- `store.py:146-147` DB path; `:51-70` schema tạo bảng rỗng, không seed.

### Hệ 1 — learner model thật nhưng không được nuôi [CODE]
- `belief_model.py:72-145` BKT replay; `LearnerBeliefState` field `p_known/uncertainty/independent_count/transfer_observed/needs_probe`.
- `executive.py:149-218` `observe_response` → `assess_response` → `_apply_semantic_assessment` (commit evidence khi confidence≥0.68).
- `executive.py:356-455` hypothesis lifecycle (misconception theo KP, resolve khi pass).
- `service.py:437-473` `_commit_evidence_locked` recompute mastery+review+belief atomically.
- `learner_context.py:134-182` `learner_continuity_snapshot` → `{}` khi không path (`:142-145`).
- `context_assembler.py:220-228` chèn `learner_continuity` vào context Root.
- `agent.py:665-671` system prompt hướng dẫn đọc `learner_belief/learner_state` như ước lượng thử nghiệm, chưa calibrated; `needs_probe=true → ưu tiên probe`.

### Hệ 2 — plan-builder tự động nhưng dead/tắt [CODE]
- `orchestrator.py:447-457` markers học tường minh (`_explicit_pedagogical_activation`).
- `orchestrator.py:498-572` `_prepare_pedagogical_turn`: nếu có episode active → observe; nếu không + có marker → `TeachingPlanBuilder.build` → `start_teaching_episode` → `start_episode`.
- `pedagogical_plan_builder.py:77-80+` `TeachingPlanBuilder.build` chỉ chạy khi `explicit_plan_request is True`, fail-closed, cấm field public/CoT.
- `orchestrator.py:441-445` gate `_pedagogy_enabled` default False; `runtime_settings_store.py:374` env mapping.
- **Không call site** cho `_prepare_pedagogical_turn`/`_commit_pedagogical_receipt`/`_notify_pedagogical_audio_finished` (grep toàn `src/` chỉ trả dòng định nghĩa).
- `coordinator.py:303-304` ghi chú PedagogicalRuntime "chưa giành hot-path delivery".

### adaptive_policy.py [CODE]
- `adaptive_policy.py:58-120` `choose_adaptive_step`; call site duy nhất `executive.py:108-115` (chỉ đạt sau khi có path + step).

---

## Đánh giá: đã xây sẵn bao nhiêu vs còn thiếu

**Đã xây sẵn (dù chưa kích hoạt):**
1. Learning kernel deterministic đầy đủ: evidence ledger, mastery recompute, review scheduler (D/S/R), pending interaction grading — `learning_core/*`.
2. Learner model thật: BKT belief (`belief_model.py`), hypothesis/misconception tracking (`executive.py`), repeated-error detection (`service.repeated_error_patterns`), adaptive strategy selector (`adaptive_policy.py`). Có cập nhật theo câu trả lời, có bền qua phiên.
3. Tutor cognition loop: observe→diagnose→strategize→move→assess (`executive.py` + `model_reasoner.py` model-backed, `reasoner.py` fallback).
4. Đường phơi bày cho Root: `tutor.advise` tool + `learner_continuity` payload + guardrail prompt.
5. Một plan-builder sinh curriculum từ model (`TeachingPlanBuilder`) + episode runtime (`PedagogicalRuntime`).
6. Nhận diện ý định học tường minh (markers) ở hai nơi (`orchestrator`, `adaptive_companion`).
7. Lưu trữ bền: SQLite learning.sqlite3 + session ledger + meta con trỏ.

**Còn thiếu hoàn toàn / đứt:**
1. **Đường tạo/activate learning path từ hội thoại cho hệ 1** — [KHÔNG TÌM THẤY]. Không có hàm "user bắt đầu hỏi chủ đề X → sinh `LearningPath`/`KnowledgePoint` → `activate_path`". Đây là mắt xích thiếu then chốt làm toàn bộ hệ 1 im.
2. **Call site cho hệ 2** — `_prepare_pedagogical_turn` & bạn bè không được gọi; hệ 2 không chạy dù có plan-builder.
3. **Quyết định mặc định bật chế độ dạy** — cả hai hệ tắt/thủ công; không có chính sách tự chuyển sang mạch dạy khi phát hiện user đang học qua nhiều lượt.
4. **Cầu nối giữa "learning path (KP)" và câu hỏi tự do của user** — hiện learner model gắn với `kp_id` trong path; khi không có path thì không có KP để gắn evidence, nên dù user trả lời cũng không có gì để chấm/mô hình hóa.

Tức là: *bộ não học* đã có ~80%; *công tắc bật + đường tạo kế hoạch từ hội thoại* gần như chưa có.

---

## Đề xuất hướng (KHÔNG thực thi)

Mục tiêu user: chế độ dạy-có-kế-hoạch tự kích hoạt khi user đang học, và learner model được dùng thật để adapt. Hai hướng; nên chọn hệ 1 làm xương sống (vì learner model/adaptive đã nằm ở đó), chỉ mượn plan-builder của hệ 2.

**Hướng khuyến nghị — cấp nguồn cho hệ 1 (tutor + learner model):**
1. **Thêm đường tạo learning path từ hội thoại.** Khi phát hiện user vào một chủ đề học (markers `_explicit_pedagogical_activation` đã có, hoặc tín hiệu "chưa hiểu" lặp lại trên cùng chủ đề), sinh một `LearningPath` tối giản (1 goal + vài `KnowledgePoint`) rồi `register_path`+`activate_path`.
   - **File/hàm:** tạo một builder nhỏ (tái dùng `TeachingPlanBuilder.build` của hệ 2 để model đề xuất KP, rồi map sang `learning_core.contracts.LearningPath/KnowledgePoint`); gọi từ một nhánh mới trong `src/runtime/ai_orchestrated/orchestrator.py` (nơi hiện có `_explicit_pedagogical_activation`) hoặc từ một capability `tutor.start_path`.
   - Điểm neo đã có: `LearningService.register_path/activate_path` (`service.py:122,127`).
2. **Hạ ngưỡng Root vào mạch tutor khi đã có path.** Một khi path active, `learner_continuity` sẽ không rỗng; sửa system prompt Root để khi `learner_continuity` có `active_path_id` + user đang hỏi trong chủ đề đó thì ưu tiên gọi `tutor.advise(response_to_previous=...)`.
   - **File/hàm:** `src/runtime/conversation/agent.py` (`_system_prompt`, khối hướng dẫn `tutor.advise` quanh `:665-671`).
3. **Dùng learner model để adapt — đã sẵn, chỉ cần reachable.** Khi (1) xong, `plan_next_move` sẽ chạy qua `choose_adaptive_step` (`adaptive_policy.py`) và hypothesis tracking, tự đổi repair/probe theo lỗi. Không cần viết mới logic adapt; chỉ cần path + evidence chảy vào.
   - **File/hàm:** không đổi `adaptive_policy.py`; đảm bảo `TutorCapability.observe_delivery_receipt` + `observe_response` được gọi đúng vòng (đã có ở `tutor.py` + `executive.py`).
4. **Gắn evidence cho câu trả lời tự do.** Để learner model cập nhật khi user trả lời bài, cần Root đánh dấu `response_to_previous=true` khi lượt user là trả lời teaching move trước; `observe_delivery_receipt` set `_waiting_for_response` (đã có — `tutor.py:140-158`). Kiểm tra receipt delivery thật sự chảy vào capability.

**Hướng thay thế — kích hoạt hệ 2 (pedagogical episode):**
- Nối call site cho `_prepare_pedagogical_turn` vào vòng chat chính (trước planning) và `_commit_pedagogical_receipt` sau delivery; bật `pedagogy.enabled`.
- **File/hàm:** `src/runtime/ai_orchestrated/orchestrator.py` (gọi `_prepare_pedagogical_turn` trong method chat của `AIChatOrchestrator`), `runtime_settings_store.py` / env `ERIS_PEDAGOGICAL_CONTROLLER_ENABLED`.
- Nhược điểm: hệ 2 *không* có BKT belief/adaptive strategy như hệ 1; learner model của nó mỏng hơn (`comprehension/concept` trong episode). Nếu đi hướng này vẫn nên bắc cầu evidence về `LearningService` để tận dụng mô hình hóa người dùng.

**Cảnh báo kiểm chứng (theo docs mục 2/7):**
- Mọi kết luận trên ở tầng **đọc source**, chưa chạy live. Trước khi sửa: (a) đọc trace phiên `eris-run-20261017-221337` để xác nhận Root KHÔNG gọi `tutor.advise` và `learner_continuity` rỗng ở lượt "chưa hiểu"; (b) xác nhận bản runtime user đang chạy trùng checkout này.
- Không nâng "module có code" thành "tính năng chạy": `adaptive_policy.py`/`belief_model.py` tồn tại và đúng ≠ đang được gọi production. Bằng chứng grep ở trên cho thấy mắt xích đứt là *tạo path* (hệ 1) và *call site* (hệ 2).
- `learner_belief`/`p_known` đánh dấu `calibrated=False` trong code — đừng để UI/Root trình bày như đánh giá năng lực đã chuẩn hóa.

---

## Nguồn file đã đọc
- `src/runtime/tutor/`: `adaptive_policy.py`, `executive.py`, `learner_context.py`, `model_reasoner.py`, `reasoner.py`, `composition.py`, (+ tham chiếu `contracts.py`, `policy.py`, `session_store.py`).
- `src/runtime/learning_core/`: `service.py`, `belief_model.py`, `store.py` (schema + path ops), (+ `contracts.py`).
- `src/runtime/capabilities/tutor.py`; `src/runtime/ai_orchestrated/orchestrator.py` (tool wiring + pedagogical helpers); `src/runtime/conversation/agent.py`, `context_assembler.py`; `src/runtime/coordinator.py`; `src/runtime/pedagogical_plan_builder.py`, `pedagogical_runtime.py`; `src/runtime/runtime_settings_store.py`.
- Grep chứng minh thiếu caller: `activate_path|register_path|pose_interaction|upsert_path` (chỉ tests + tools); `_prepare_pedagogical_turn|_commit_pedagogical_receipt|_notify_pedagogical_audio_finished` (chỉ định nghĩa).
