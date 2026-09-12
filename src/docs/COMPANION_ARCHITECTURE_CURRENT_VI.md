# Kiến trúc Companion hiện hành của Eris

> Tài liệu này là source-of-truth sau đợt **Companion Consolidation**. Các tài liệu V79–V91 cũ vẫn có giá trị lịch sử, nhưng nếu mâu thuẫn với file này thì ưu tiên file này.

## 1. Eris và coding extension là hai sản phẩm độc lập

Nguyên tắc cứng:

- **Eris Desktop không cần Eris Code/GitPilot để hoạt động.**
- **Eris Code/GitPilot không cần Eris Desktop để code/test/review.**
- Eris không tự nhận workspace/file/terminal/GitPilot telemetry để hiểu user.
- Nếu user muốn Eris xem repo, diff, log hoặc kết quả agent, user chủ động đưa evidence qua kênh Eris.
- Các module V79/V90 về CodingObservation/Eris Link được giữ ở trạng thái legacy để đọc journal cũ/rollback/test compatibility; normal runtime không boot chúng.

## 2. Ai sở hữu cái gì?

### `runtime/adaptive_companion.py` — DELIVERY AUTHORITY

Đây là **bộ phận duy nhất được quyết định cách Eris phản ứng** ở mức companion/peer/teaching:

- trả lời như companion bình thường;
- bỏ qua tutorial cơ bản khi evidence đủ mạnh;
- dạy có hướng dẫn khi user chủ động muốn học;
- challenge nhẹ khi user đang học đúng chủ đề và có dấu hiệu outsource reasoning quá mức;
- phát `teasing_opportunity`, nhưng **không tự cấp quyền mỉa**.

Nó không chấm mastery bằng self-report và không đọc hidden coding telemetry.

### `runtime/engineering_mentor.py` — TECHNICAL EVIDENCE PROVIDER

Mentor không còn là delivery brain thứ hai.

Nó sở hữu:

- skill evidence kỹ thuật;
- confidence/evidence count/counter-evidence;
- adaptive engineering learning;
- tool literacy;
- mentor calibration/outcome;
- cross-environment correlation nếu có evidence được cung cấp rõ.

Nó trả block `ENGINEERING_EVIDENCE`, **không chọn persona/role/teasing style**.

Quan trọng: Mentor chỉ *đề xuất* learning/tool hint trong lúc dựng evidence. Hint đó
chưa được tính là một lần dạy. Sau khi `AdaptiveCompanion` chọn stance, Companion
gọi handshake một chiều `note_companion_delivery(...)`; chỉ `teach_light`,
`teach_guided` hoặc `challenge_light` mới commit learning prompt/tool recommendation
và calibration intervention. Nhờ vậy thống kê không còn ghi "Eris đã dạy" khi
Companion thực tế chọn im hoặc chỉ trả lời bình thường.

### `runtime/adaptive_engineering_learning.py` — LEARNING EVIDENCE

Theo dõi concept kỹ thuật, candidate misconception, teach-back/application evidence.
Không tự quyết user có phải học ngay hay không.

### Living User Memory — DURABLE USER CONTEXT AUTHORITY

`memory/living_user/` là source-of-truth bền vững cho những gì user đang nói rõ về chính mình, gồm cả:

- `learning.active_topics`: chủ đề user đang học/tìm hiểu;
- `projects.current_activities`: project/công việc user đang làm;
- profile, episode và action memory đã có evidence/audit/correction.

`AdaptiveCompanion` **không còn tự ghi một file user-memory riêng**. Nó chỉ giữ hot cache trong process để nối khoảng trễ của background curator và chỉ đọc file V91 cũ như migration fallback. Self-report/current activity chỉ là context, không phải mastery evidence.

### Living User ActionMemory — EXPLICIT WORK AUTHORITY

Sở hữu mục tiêu/cam kết/workflow mà user đã nói rõ. Đây là memory của *việc user đã nêu*, không phải bộ lập ưu tiên chiến lược.

### `runtime/life_horizon.py` — PRIORITY / HORIZON AUTHORITY

Sở hữu projection ưu tiên H0–H4 và next-action coordination. Life Horizon có thể dùng goal/project context nhưng không thay thế ActionMemory và không biến goal thành mastery. Hai tầng được giữ riêng có chủ đích: **ActionMemory nhớ lời cam kết; LifeHorizon sắp ưu tiên.**

### Relationship + Affective Voice — TONE AUTHORITY

Mức thân mật, playful, irritation, teasing thực tế vẫn do relationship/affective voice quyết định.
`teasing_opportunity` của Companion chỉ là gợi ý an toàn.

### Conversation trajectory / handoff — CONTINUITY AUTHORITY

Sở hữu continuity của conversation/topic. Không chấm skill và không quyết teaching policy.

## 3. Module nào đã bị hạ khỏi active path?

### `runtime/companion_mentor_orchestrator.py`

V84 role router giờ là **legacy utility**. EngineeringMentor không gọi nó trong active path nữa.
Lý do: nếu cả V84 router và AdaptiveCompanion cùng chọn stance thì Eris có hai bộ não quyết cách nói.

### `runtime/project_trajectory.py`

V88 ProjectTrajectory giờ là **legacy/manual analytics**. Coordinator không boot service này, orchestrator không inject nó vào prompt, Capability Panel không tự decorate bằng CodingObservation nữa.

### `runtime/coding_observation.py` và `runtime/eris_code_observer_link.py`

Giữ cho compatibility/journal migration. Normal runtime không dùng làm nguồn hiểu user.

### `EngineeringMentor.observe_companion_context()` / `observe_external_user_intent()`

Giữ signature để caller cũ không crash, nhưng giờ là **no-op**. Hidden extension data không thể âm thầm mutate skill model.

## 4. Luồng hiện tại

```text
USER ↔ ERIS CONVERSATION
        │
        ├── Conversation trajectory / handoff  → đang nói tiếp chuyện gì
        ├── Living User Memory               → context bền vững: đang học/đang làm gì
        ├── ActionMemory + Life Horizon       → goal đã nói + ưu tiên H0-H4
        ├── Engineering Mentor                → evidence kỹ thuật / learning hint / calibration
        ├── Adaptive Companion                → QUYẾT cách phản ứng
        │       └── delivery handshake         → chỉ commit intervention thật sự đã xảy ra
        └── Relationship + Affective Voice    → QUYẾT tone/thân mật/mỉa thực tế
                         │
                         ▼
                    PUBLIC WRITER
```

Coding extension nằm ngoài luồng này:

```text
USER ↔ ERIS CODE / GITPILOT ↔ REPO
```

Hai hệ thống có thể cùng phục vụ user nhưng không phụ thuộc runtime lẫn nhau.

## 5. Policy dạy user hiện tại

- `làm luôn đi` không tự động đồng nghĩa user yếu hoặc cần lecture.
- `tại sao / vì sao / giải thích` bình thường → **trả lời**, không tự biến thành tiết học.
- Chỉ tín hiệu học rõ như `dạy tôi / tôi đang học / muốn học / giải thích kỹ-sâu` mới mở teaching guided.
- Từ domain như `machine learning / deep learning` không được coi là learning intent chỉ vì có chữ `learning`.
- Evidence mạnh ở skill liên quan → có thể nói kiểu technical peer và skip basics.
- Nếu calibration cho thấy Eris gần đây bị user sửa nhiều → không tự tin dùng estimate cũ để skip basics.
- Nếu calibration cho thấy mentoring gây phiền → giảm proactive teaching; explicit learning của user vẫn thắng.
- Overreliance risk chỉ được dùng để challenge khi turn hiện tại overlap đúng learning topic đang active.
- Self-report `tôi hiểu rồi` không phải mastery evidence.

## 6. Quy tắc để không tái tạo kiến trúc rối

Khi thêm feature mới:

1. **Không tạo thêm module chọn role/stance.** Hãy bổ sung input cho `AdaptiveCompanion`.
2. **Không cho skill model quyết tone.** Skill model chỉ trả evidence/confidence.
3. **Không lấy coding extension telemetry làm dependency bắt buộc.**
4. **Không biến Life Horizon thành skill model.** Goal là goal; mastery là evidence khác.
5. **Không để teasing marker vượt Relationship/Affective Voice.**
6. **Không tạo shadow user-memory trong Companion.** Durable learning/activity phải về Living User Memory.
7. **Không dùng profile experience/self-report làm mastery authority.** Technical competence thuộc evidence-based skill model.
8. Nếu cần project/repo context, ưu tiên evidence user chủ động đưa cho Eris.

## 7. Acceptance quan trọng

- Eris Desktop chạy khi không cài extension.
- Extension chạy khi Eris Desktop tắt.
- Hidden extension observation API không mutate skill model.
- EngineeringMentor không inject `role_orchestration` vào writer nữa.
- ProjectTrajectory/CodingObservation không tự đi vào public conversation nữa.
- AdaptiveCompanion là delivery owner duy nhất nhưng **không sở hữu durable user memory**.
- Living User Memory là durable authority cho `learning.active_topics` và `projects.current_activities`.
- Câu hỏi giải thích bình thường không tự ép `teach_guided`; explicit learning intent mới được phép làm vậy.
- Living User profile có competence claim thì writer nhận boundary: claim đó không được quyết mức dạy/skip-basics.
- EngineeringMentor dựng evidence không tự tăng `interventions`; chỉ delivery thật do Companion chọn mới được ghi.
- Learning/tool hint của một turn bị clear nếu Companion không dạy, không được rò sang turn sau.
