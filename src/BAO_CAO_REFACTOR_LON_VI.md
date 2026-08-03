# Báo cáo refactor lớn

Bản này xử lý năm yêu cầu theo hướng bảo toàn hành vi thay vì đổi tên hàng loạt
rồi cầu nguyện. Phần semantic được tập trung ở composition root và các boundary;
toàn bộ source Python được quét vệ sinh định dạng.

## 1. Đổi tên nội bộ có chữ Gemma

Đã đổi các tên file, class, hàm và biến nội bộ:

- `gemma_research_critic.py` → `local_research_critic.py`
- `GemmaResearchCritique` → `LocalResearchCritique`
- `build_gemma_critic_prompt()` → `build_local_critic_prompt()`
- `run_gemma_research_critic()` → `run_local_research_critic()`
- `parse_gemma_critic_response()` → `parse_local_critic_response()`
- `GemmaInnerSynthesizer` → `LocalModelInnerSynthesizer`
- `_is_gemma()` → `_requires_open_model_hygiene()`
- `_apply_gemma_hygiene()` → `_apply_open_model_hygiene()`
- `_gemma_line()` → `_model_line()`

Chuỗi model/provider cũ được gom vào `llm/model_catalog.py`. Đây là boundary
compatibility duy nhất, không phải tên kiến trúc. Các câu test đang cố ý thảo
luận sản phẩm Gemma vẫn giữ nguyên vì đổi nội dung user mẫu sẽ làm test mất ý
nghĩa, một kiểu “sạch grep” rất đẹp nhưng vô dụng.

## 2. Xóa class và module chết

Các class không có call-site nội bộ đã được loại bỏ:

- `LexicalOrientationInterpreter`
- `RelationalFeedbackAnalyzer`
- `DreamScheduler`
- `CandidateBatch`
- `ClaimConsolidator`
- `SemanticAnswerPolicy`
- `GuardViolation`
- `LivelinessTracker`

Các module chỉ chứa đường chết tương ứng đã bị xóa khi không còn consumer:

- `memory/claim_consolidator.py`
- `memory/semantic_answer_policy.py`
- `runtime/guard_violations.py`
- `runtime/liveliness_tracker.py`

`config/exception_budget.json` đã được cập nhật để bỏ path chết và đổi path của
local research critic.

## 3. Gom folder và viết lại Cortex

Cortex heartbeat được tách khỏi file đơn khối thành package:

```text
runtime/ai_orchestrated/cortex/
├── __init__.py
├── dependencies.py
├── growth.py
├── models.py
├── policies.py
└── runtime.py
```

Ranh giới mới:

- `models.py`: contract `CortexAttentionSignal`, `CortexRuntimeTick`.
- `dependencies.py`: `CortexDependencies`, nơi tạo dependency mặc định.
- `policies.py`: attention policy và heartbeat policy thuần.
- `growth.py`: side-effect growth nền, lỗi không hạ hot path.
- `runtime.py`: pipeline update context → drive → resource → attention →
  consolidation → growth.

Cortex vẫn không có `should_speak`, không tạo public intent và không sinh câu
public. File import cũ được giữ như shim migration, không chứa logic.

## 4. Chuẩn hóa dependency injection

Đã thêm `core/di.py` với một quy tắc duy nhất:

```python
resolve_dependency(provided, factory)
```

Dependency inject chỉ bị thay khi là `None`. Mẫu cũ `provided or Default()` có
thể nuốt object falsey hợp lệ, một lỗi nhỏ rất thích xuất hiện trong production.

Kết quả quét:

- 141 call-site hiện dùng `resolve_dependency()`.
- Mẫu constructor `self.x = injected or Default()` còn lại: 0.
- Composition root, Cortex, PrivateMind, Tutor, memory, engagement, hardening,
  social appraisal và provider runtime đã đi cùng một quy ước.

## 5. Sweep source và định dạng

- Quét 670 file Python.
- Chuẩn hóa line ending về LF.
- Xóa trailing whitespace.
- Bảo đảm newline cuối file.
- Không chạy formatter phá cấu trúc hoặc reflow toàn repo khi không có Black/Ruff
  trong archive. Thay đổi hình thức được giữ tối thiểu để diff còn đọc nổi.

## Kiểm thử

- `python -m compileall -q .`: đạt.
- 695 test khả dụng: đạt.
- 5 test được bỏ qua chủ động và 3 file test không thể collect vì archive gốc
  thiếu các module `tools/*` sau:
  - `tools.package_source`
  - `tools.evaluate_social_plan_activation`
  - `tools.report_pdf_acceptance`
  - `tools.evaluate_semantic_paraphrases`
  - `tools.audit_remote_inference_paths`
  - `tools.audit_semantic_authority_paths`

Đây là giới hạn của source đầu vào, không phải lỗi sinh ra từ refactor.

## Tương thích và rollback

- Import cũ `runtime.ai_orchestrated.cortex_runtime` vẫn hoạt động.
- Model ID/provider token cũ vẫn được đọc qua `llm/model_catalog.py`.
- Feature flags của các lane legacy không bị xóa.
- Không thêm fallback chéo hoặc quyền public speech mới.
