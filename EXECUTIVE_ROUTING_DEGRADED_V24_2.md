# Eris V24.2 — Executive DS2API routing + Subject Core degraded authority

## Mục tiêu

V24.1 đã sửa crash chat do local `executive` chưa được bind, nhưng log production mới cho thấy một lỗi khác:

- main brain và các worker đang chạy qua DS2API/Whale2API;
- `build_executive_client()` chỉ nhìn `ERIS_REMOTE_PROVIDER`, nên khi provider vẫn là `deepseek` nó dựng Executive bằng Official DeepSeek riêng;
- Executive có thể trả payload rỗng `{}` ở cả autonomous và interactive;
- autonomous biến lỗi transport/schema đó thành `body_only/silence`, khiến hệ còn process nhưng mất chức năng initiative.

V24.2 sửa đúng hai boundary, không thêm worker nhận thức mới.

## 1. Executive đi cùng route với main brain

`llm/process_manager.py::build_executive_client()` giờ đọc cả:

- `ERIS_REMOTE_PROVIDER`;
- `ERIS_DS2API_ENABLED`;
- worker spec `executive`.

Khi provider là DeepSeek và DS2API bật, route là:

```text
Executive structured request
        ↓
DS2API / Whale2API worker role=executive
        ↓ transport/JSON/schema failure
Official DeepSeek Executive
        ↓ failure tiếp
Subject Core degraded authority
```

Official fallback dùng `ERIS_EXECUTIVE_BASE_URL` nếu khai riêng. Nếu `ERIS_REMOTE_BASE_URL` đang là localhost/port DS2API thì nó không được tái sử dụng làm "official fallback"; fallback quay về `https://api.deepseek.com`.

Nếu chỉ có DS2API mà không có official key, Executive vẫn dùng DS2API primary. Nếu DS2API không cấu hình nhưng official có key, official được dùng trực tiếp.

## 2. `{}` không còn được xem như response dùng được

DS2API Executive và Official Executive đều đi qua `JsonlWorkerClient(role="executive")`.

Với structured request, `{}` thiếu schema required fields nên bị `JsonlContractError`; `ChainedFallbackClient` thấy primary tier lỗi và chuyển sang Official tier. Chỉ khi cả hai tier đều thất bại thì Executive Cortex mới đi degraded path.

## 3. Fail-fast riêng cho Executive

`ChainedFallbackClient` trước đây có thể nâng timeout DS2API lên mặc định 90 giây. Với Executive, điều đó làm official fallback gần như vô dụng cho interactive/autonomous timing.

V24.2 thêm:

```text
ERIS_EXECUTIVE_DS2API_FAILFAST_TIMEOUT_S
```

Mặc định: `12s`.

Riêng worker role `executive`, timeout DS2API được giới hạn bằng `min(request_timeout, failfast)`. Các lane DS2API khác giữ hành vi cũ.

## 4. Subject Core degraded authority

Nếu Executive model/schema/transport không dùng được, `ExecutiveCortex.degraded_outcome()` không tự invent action và không mặc định đổi lỗi thành silence.

Nó đọc `SubjectDeliberationFrame.coalitions` theo thứ tự đã rank:

1. thử coalition đầu bảng;
2. chỉ bỏ qua coalition nếu action đó không thể materialize bằng runtime affordance hiện có;
3. bind chính xác `subject_coalition_id` và `subject_proposal_ref`;
4. `speak` chỉ được materialize khi proposal có `affordance_id` đang thật sự offered;
5. `silence` và `body_only` vẫn được giữ nếu chính Subject Core xếp chúng cao nhất.

Do đó có khác biệt forensic rõ ràng giữa:

```text
executive_model_or_schema_failure → synthetic silence
```

và:

```text
Executive unavailable
→ Subject Core coalition rank
→ subject_core_degraded:<reason>:rank=<n>
→ action tương ứng
```

Nếu Subject Core thật sự chọn silence thì Eris vẫn im, nhưng đó là quyết định grounded của subject state, không phải xác rơi từ exception/failure.

## 5. Autonomous gọi Executive boundary kể cả khi transport không có

`SelfTurnPipeline` không còn bỏ qua `ExecutiveCortex.deliberate()` chỉ vì `executive.enabled == False` do `client is None`.

Khi feature `ERIS_EXECUTIVE_CORTEX_ENABLED=1` nhưng transport không tồn tại, Executive object vẫn được gọi để materialize degraded Subject Core outcome. Nếu feature bị tắt rõ ràng, degraded authority không tự bật lại.

## 6. Quyền hạn giữ nguyên

V24.2 không cho runtime tự chọn motive hay tool semantic thay Executive:

- Subject Core vẫn sở hữu substrate/appraisal/needs/beliefs/values/coalitions;
- degraded boundary chỉ chọn trong coalition đã chuẩn bị;
- một coalition `speak` không có offered `affordance_id` không được bịa câu nói;
- capability route chưa materialize được thì không tự chọn capability thay model;
- Surface vẫn chỉ wording.

## 7. Kiểm thử

Test trực tiếp V24.2 kiểm tra:

- Executive trả `{}` → dùng đúng top Subject Core speech coalition và bind đúng coalition/proposal;
- client Executive `None` → autonomous vẫn materialize Subject Core coalition;
- nếu top coalition là silence → silence được giữ với provenance `subject_core_degraded`, không giả thành model failure;
- `ERIS_DS2API_ENABLED=1` + provider DeepSeek → route `DS2API executive → Official DeepSeek`;
- remote base localhost không bị dùng làm official fallback;
- Executive DS2API timeout obey fail-fast riêng;
- DS2API trả `{}` tại JSON boundary → official tier thật sự nhận request.

Kết quả direct regression suite: `90 passed`.

Broad suite trên cây nguồn: `861 passed`; còn 6 failure do dependency/file đã thiếu từ V24.1 (`tools.report_pdf_acceptance`, `tools.evaluate_semantic_paraphrases`, `tools.audit_remote_inference_paths`, `tools.audit_semantic_authority_paths`, `body/SubjectPerformanceFrame.cs`) và 3 collection error do `tools.package_source` / `tools.evaluate_social_plan_activation`.

## Phiên bản

- package: `0.87.2`
- Subject Core: `subject-service-v12-validated-agency-reflection` (không đổi algorithm)
- Temporal Mind: `temporal-mind-v1`
- Executive routing: `executive-routing-v24.2`
- degraded authority: `subject-core-degraded-executive-v1`
