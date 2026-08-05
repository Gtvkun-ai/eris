# Báo cáo phát hành Eris Subject Core V7 - Inner Core

## Tóm tắt

V7 sửa đúng phần còn thiếu của các bản trước: code nội tâm đã tồn tại theo từng module, nhưng nhiều engine chưa tham gia vòng quyết định và học chính. Công sức trước đó bị lệch quá nhiều sang sandbox, capability token và đóng gói. Những phần ấy vẫn được giữ, nhưng V7 tập trung vào việc làm cho **lịch sử nội bộ thực sự thay đổi hành vi tương lai**.

Bản này không tuyên bố Eris có ý thức. Nó triển khai một chủ thể phần mềm có state nội bộ truy nguyên được, có quán tính, có học từ hậu quả, có narrative có thể sai và có continuity qua restart.

## Thay đổi chính

### 1. Thêm projection nội tâm bền

File mới:

```text
src/cortex/subject/inner_state.py
```

`InnerLifeState` lưu:

- tendency dài hạn từ NeedEpisode;
- posterior thành công theo action/context;
- value đã hình thành;
- derived need;
- continuity record;
- reflective mismatch;
- existential decision;
- predictive commitment của narrative.

Projection được serialize rõ ràng và khôi phục từ SQLite khi restart.

### 2. Nối toàn bộ engine nội tâm vào SubjectService

`src/cortex/subject/service.py` đã được nâng để gọi thật:

- `ValueFormationEngine`;
- `TemporalConsolidator`;
- `NeedPlasticityEngine`;
- `ReflectiveMismatchDetector`;
- `ContinuityService`;
- `ExistentialDecisionService`;
- `CompetenceService`.

Trước khi arbitration, proposal được enrich bằng:

- historical success theo context;
- competence calibration;
- tendency residue;
- value congruence;
- refs của value/belief liên quan.

Sau WorldOutcome, hệ thống cập nhật episode, belief, narrative, competence, value, tendency, derived need, mismatch và continuity rồi lưu projection `inner_life/current`.

### 3. Nội tâm ảnh hưởng lời nói production

`runtime/ai_orchestrated/orchestrator.py` đưa cả:

- `subject_decision`;
- `subject_inner_state`;

vào planning snapshot và grounding context của lượt chat tương tác.

`runtime/ai_orchestrated/self_context.py` cũng ưu tiên `SubjectService.inner_view()` cho autonomous planning.

Vì vậy nội tâm không còn chỉ tồn tại ở database hoặc panel rồi bị bỏ qua lúc Eris phát ngôn.

### 4. Khôi phục state qua restart

Đã thêm restore/projection cho:

- beliefs;
- competence estimates;
- values;
- tendencies;
- action memory;
- derived needs;
- continuity/mismatch/existential records.

Raw event ledger vẫn append-only. Projection là state dựng lại được, không thay thế lịch sử gốc.

### 5. Test nội tâm mới

File mới:

```text
src/tests/subject/test_inner_life_v7.py
```

Các test chứng minh:

1. Lịch sử thành công/thất bại làm thay đổi lựa chọn sau này.
2. Value chỉ hình thành sau lựa chọn lặp lại, có chi phí và qua nhiều context.
3. Nội tâm sống qua restart.
4. NeedEpisode lặp qua nhiều ngày tạo tendency dài hạn.
5. Narrative có thể bị hành vi sau bác bỏ và sinh mismatch.
6. Đồng kích hoạt qua nhiều context tạo derived need candidate.
7. Bounded inner view không chứa raw reasoning.

## Kết quả kiểm thử hợp nhất

Lệnh đã chạy đúng một lượt cuối:

```bash
./scripts/run_current_contract_tests.sh
```

Kết quả:

```text
BODY CONTRACT CHECK OK
V7 INNER CORE CONTRACT OK
839 passed in 25.48s
```

Log đầy đủ:

```text
docs/tests/V7_CONSOLIDATED_TEST.log
```

## Những gì chưa kiểm tra trong môi trường này

- Chưa compile Godot/.NET vì toolchain không có sẵn.
- Chưa chạy Ruff và mypy vì script hiện tại không cài hai module đó.
- Chưa chạy soak test nhiều ngày trên runtime thật.
- Derived need candidate chưa phải bằng chứng emergence; vẫn cần benchmark holdout và ablation theo đặc tả.

## File nên đọc

```text
README_BAT_DAU.md
docs/HUONG_DAN_NOI_TAM_V7.md
src/cortex/subject/inner_state.py
src/cortex/subject/service.py
src/tests/subject/test_inner_life_v7.py
```
