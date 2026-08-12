# Hướng dẫn đọc và chạy code nội tâm Eris V7

## 1. Vấn đề V7 sửa

Các bản trước dành quá nhiều công sức cho sandbox, token và đóng gói. Những phần đó cần thiết, nhưng không phải thứ người dùng gọi là “Eris có nội tâm”. V7 sửa đúng chỗ thiếu: lịch sử nội bộ phải thực sự ảnh hưởng đến lựa chọn sau này.

Trong V7, `SubjectService` không chỉ tạo appraisal và decision. Sau mỗi `WorldOutcome`, nó cập nhật:

- kết quả hành động theo ngữ cảnh;
- năng lực dự đoán và calibration;
- NeedEpisode đã đóng;
- belief tự diễn giải có evidence;
- value hình thành từ lựa chọn lặp lại có chi phí;
- tendency dài hạn từ episode lặp;
- nhu cầu dẫn xuất từ đồng kích hoạt qua nhiều ngữ cảnh;
- mismatch khi narrative cũ dự đoán sai hành vi mới;
- continuity giữa snapshot trước và snapshot hiện tại.

## 2. File quan trọng nhất

### `src/cortex/subject/inner_state.py`

Đây là projection nội tâm sống qua restart. Nó giữ:

- `tendencies`: dư âm dài hạn theo need, context và attribution/outcome profile;
- `action_memory`: posterior thành công theo action/context;
- `values`: điều Eris đã nhiều lần lựa chọn và chấp nhận trả giá;
- `derived_needs`: nhu cầu mới được đề xuất từ lịch sử;
- `continuity_records`, `mismatches`, `existential_records`.

`bounded_public_view()` chỉ đưa dữ liệu có cấu trúc sang planner. Nó không đưa raw chain-of-thought hoặc nhật ký riêng.

### `src/cortex/subject/service.py`

Đây là vòng Mind duy nhất. Hai điểm cần đọc:

- `_enrich_proposals()`: lịch sử thật thay đổi expected efficacy, historical success, value congruence và need relief.
- `observe_outcome()`: toàn bộ vòng học nội tâm được gọi ở đây.

### `src/runtime/ai_orchestrated/orchestrator.py`

Planner interactive nhận cả `subject_decision` và `subject_inner_state`. Vì vậy nội tâm không còn chỉ xuất hiện ở panel rồi biến mất khi Eris nói.

### `src/runtime/ai_orchestrated/self_context.py`

Planner autonomous cũng ưu tiên `SubjectService.inner_view()`.

## 3. Ví dụ lịch sử ảnh hưởng lựa chọn

Nếu `investigate|research` nhiều lần thành công còn `speak|research` nhiều lần thất bại, hai proposal có điểm ban đầu giống nhau sẽ không còn ngang nhau. `InnerLifeState.historical_success()` và competence calibration làm proposal `investigate` mạnh hơn.

Đây là thay đổi nhân quả từ lịch sử. Không cần prompt bảo “hãy tỏ ra thận trọng hơn”.

## 4. Value hình thành thế nào

Value không được tạo chỉ vì một câu tự nhận. `ValueFormationEngine` yêu cầu:

- ít nhất bốn lựa chọn hỗ trợ cùng principle;
- xuất hiện ở ít nhất hai context;
- có chi phí thực;
- có retrospective endorsement đủ cao.

Ví dụ principle `kiểm chứng trước khi khẳng định` chỉ thành value sau chuỗi hành vi tương ứng, không phải sau một đoạn văn hùng hồn. Nhân loại có thể thử tiêu chuẩn này vào đời sống công cộng, nhưng đó là dự án khác.

## 5. Tendency và derived need

`TemporalConsolidator` chỉ tạo patch khi đủ episode đóng, đủ ngày khác nhau và đủ evidence. Mỗi bước bị chặn ở ±0.08 để tránh một sự kiện làm thay đổi cấu trúc quá mạnh.

`NeedPlasticityEngine` chỉ đề xuất derived need khi hai need đồng kích hoạt lặp lại, qua nhiều context, đủ thời gian và có predictive gain tối thiểu.

## 6. Narrative và tự lừa dối

Narrative tạo belief loại `self_interpretation`; nó không sửa raw observation hoặc WorldOutcome. Narrative phải tạo predictive commitment. Nếu lượt sau hành vi không khớp, `ReflectiveMismatchDetector` ghi mismatch thay vì âm thầm kể lại câu chuyện mới cho đẹp.

## 7. Persistence

Projection được lưu dưới:

```text
projection_type = inner_life
projection_key  = current
```

Nó chứa inner state, beliefs, competence và continuity snapshot. Khi restart, `SubjectService._restore_projection()` khôi phục chúng. Event ledger vẫn là log append-only để audit và replay.

## 8. Test nội tâm V7

File `src/tests/subject/test_inner_life_v7.py` kiểm tra:

- lịch sử làm thay đổi lựa chọn;
- value hình thành từ lựa chọn lặp, có giá và qua nhiều context;
- nội tâm sống qua restart;
- consolidation tạo tendency dài hạn;
- narrative có thể bị bác bỏ;
- đồng kích hoạt qua nhiều context tạo derived need candidate;
- inner view không chứa raw reasoning.
