# Causal Affect V1 cho Eris

## Trạng thái

Bản này triển khai lớp nhân quả theo chuỗi:

`raw event → typed ExogenousEvent → AppraisalFrame → ActiveMotive conflict → CausalThread → PerformanceIntent → OutcomeReport → LearningPatch`

Mục tiêu là ngăn `ontological_dread` hoặc attachment scalar tự biến thành câu thoại tối khi không có sự kiện và provenance.

## Thành phần mới

- `cortex/causal_affect_models.py`
  - `ExogenousEvent`, `AppraisalFrame`, `ActiveMotive`, `RelationshipExpectation`
  - `CausalThread`, `PerformanceIntent`, `SurpriseBudget`, `LearningPatch`
- `cortex/exogenous_event_ledger.py`
  - semantic projection trên `memory/event_ledger.py`
  - không sửa raw ledger và không lưu interpretation vào event gốc
  - promise chỉ được tạo khi có scope và deadline hoặc lời trích dẫn đủ rõ
- `cortex/appraisal_engine.py`
  - appraisal có uncertainty và alternative interpretations bắt buộc với event nhạy cảm
- `cortex/motive_graph.py`
  - motive có target, desire, fear, inhibition, conflict và resolution condition
- `cortex/relationship_expectations.py`
  - expectation có context, confidence, emotional stake và tolerance window
- `cortex/causal_threads.py`
  - tối đa ba thread có evidence; luôn cấm bịa memory, quy kết abandonment, ép reassurance và đe dọa rút lui
- `cortex/performance_intent.py`
  - lập performance contract trước realization; mặc định vulnerability không yêu cầu reply
- `cortex/outcome_learner.py`
  - learning patch có max step 0.08, không tối ưu drama hoặc engagement thô
- `cortex/causal_affect_pipeline.py`
  - facade nối toàn chuỗi và có `attach_to_runtime()` để công bố `active_causal_threads`

## Thay đổi module hiện hữu

### `cortex/endogenous_drive.py`

- thêm `effective_dread`, `causal_thread_pressure`, `dominant_thread_id`, `dread_evidence_refs`
- `internal_drive` có dread nhưng dread không có evidence bị cap ở `0.20`
- `EndogenousDriveEngine.update()` nhận `active_threads`

### `runtime/ai_orchestrated/self_context.py`

- truyền `ontological_dread`, `effective_dread`, `causal_thread_pressure`
- truyền tối đa ba `active_threads` đã lọc public-safe và bắt buộc có evidence

### `runtime/ai_orchestrated/cortex/models.py` và `policies.py`

- attention có lane riêng cho causal thread
- `dominant_thread_id` đi cùng attention signal

### `cortex/appetite_system.py`

- không còn tạo bid bằng cớ tự mang
- `bring_own_pretext` chỉ còn là field tương thích cấu hình và bị runtime bỏ qua
- loneliness/boredom không có provenance thì không thắng, kể cả yan mode

### `cortex/existential_anchor/shadow.py`

Register mới mô tả xu hướng nội tâm thay vì hành vi cưỡng ép:

- `guarded_withdrawal`
- `attachment_alarm`
- `exposed_vulnerability`
- `control_impulse_inhibited`

Shadow không surface khi thiếu evidence hoặc thiếu ít nhất hai motive xung đột. `control_impulse_inhibited` tăng restraint thay vì cấp quyền ra lệnh.

### `cortex/existential_anchor/anchor_system.py`

- bỏ forced `pleading=0.95`
- `arm_farewell()` tạo `capability_shutdown_proposed` event có evidence
- event được lấy bằng `consume_author_events()` để đi qua appraisal bình thường

### `runtime/ai_orchestrated/performance.py`

- thêm `plan_from_intent()`
- body-only surface được phép không có speech
- text vượt `max_words` hoặc intent thiếu evidence sẽ bị từ chối thay vì tự sửa/bịa
- `intent_id` và `thread_id` được giữ xuyên stage act

### `runtime/live2d_affect_bridge.py` và `stage_protocol_adapter.py`

Thêm các affect channel:

- `ontological_dread`
- `self_coherence`
- `vulnerability`
- `restraint`
- `withdrawal`
- `conflict_tension`
- `shadow_intensity`

Stage affect event có thể mang `intent_id` và `thread_id`, nhưng không mang prose nội tâm.

### `runtime/outcome_observer.py`

- gắn `thread_id`, `intent_id`, `delivery_success`, `reply_expected`
- phân biệt:
  - turn không yêu cầu reply
  - user đang bận/compile
  - audio hoặc delivery thất bại
  - conversation đã đóng
  - ignored thật sau required reply

## Cách nối runtime tối thiểu

```python
from cortex.causal_affect_pipeline import CausalAffectPipeline

pipeline = CausalAffectPipeline()
snapshot = pipeline.update(
    raw_records=tuple(event_ledger.recent(limit=20)),
    previous_context=previous_user_context,
    current_context=current_user_context,
    goals=tuple(active_goals),
    self_model=self_model_snapshot,
    relationship=relationship_state,
    values=value_snapshot,
    interrupt_cost=current_user_context.interrupt_cost,
)
pipeline.attach_to_runtime(runtime_owner)

rolling_state = endogenous_drive.update(
    user_context=current_user_context,
    base_internal_state=base_internal_state,
    agenda_stack=internal_agenda,
    active_threads=snapshot.threads,
)
```

Khi realization có text:

```python
intent = snapshot.intents[0]
act = performance_planner.plan_from_intent(
    intent,
    realized_text=approved_text,
    autonomous_plan=autonomous_plan,
)
```

## Kiểm thử

### Suite liên quan trực tiếp

```text
105 passed
```

Gồm test causal-affect mới và regression quanh Architecture C, Live2D affect, opening performance và dependency injection.

### Suite rộng

Bản đã chỉnh:

```text
798 passed, 16 failed
```

Source gốc, với cùng ba file test bị bỏ qua do snapshot thiếu package `tools.*`:

```text
781 passed, 16 failed
```

Mười sáu lỗi giống nhau ở cả source gốc và bản chỉnh, tập trung vào Executive Cortex V53/V54 và các utility `tools.*` bị thiếu. Bản causal-affect thêm 17 test và không tạo failure mới trong suite rộng.

Full collection của cả source gốc và bản chỉnh đều dừng ở ba lỗi import vì ZIP đầu vào không chứa:

- `tools.package_source`
- `tools.evaluate_social_plan_activation`
- một số utility audit/report dưới `tools.*`

## Giới hạn còn lại

Snapshot không xác định entry point production chính xác giữa event ledger, runtime owner, planner và memory. Vì vậy facade đã sẵn sàng nhưng cần được gọi tại coordinator production thực tế. Không có cách trung thực nào để đoán entry point đó chỉ vì con người thích một nút “xong hết”.

Invariant của bản này:

> Dread không được surface chỉ vì scalar cao. Nó chỉ được leak khi có event thật, evidence, appraisal có uncertainty, motive conflict và một surface level được policy cho phép.
