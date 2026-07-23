# ERIS - ghi chú tái cấu trúc một lần

Bản này áp dụng trực tiếp các hạng mục trọng tâm trong báo cáo PDF **"Tái kiến trúc ERIS để giảm độ trễ..."**. Các đoạn thay đổi quan trọng trong mã đều có chú thích `PDF annotation` kèm số trang để lần ngược quyết định kiến trúc, thay vì để người bảo trì tương lai đoán ý đồ như một nghi lễ khảo cổ phần mềm.

## Những phần đã triển khai

### 1. InferenceBroker trung tâm

File mới: `runtime/inference_broker.py`.

Broker là cửa vào chung cho remote inference, với:

- lane priority và optional/required policy;
- reservation RPM/TPM/ITPM/OTPM trước khi gửi request;
- bounded queue và concurrency gate;
- deadline-aware admission;
- coalescing job nền cùng loại;
- preemption khi user turn mới bắt đầu;
- cancel scope cho observer/background work;
- cooldown theo `retry-after`;
- cập nhật động từ rate-limit headers;
- settle reservation bằng usage thật khi provider trả token usage; reserve dư được hoàn, usage vượt reserve trở thành debt trong cửa sổ;
- `CancellationToken` và deadline được truyền xuống adapter để chặn retry/child request và rút timeout còn lại;
- snapshot, queue và inflight telemetry.

Các lane chính đã nối: `chat_main`, `chat_tool_required`, `tts_current_turn`, `speech_localizer`, `semantic_shadow`, `post_observer`, `memory_digest`, `private_mind`, `tutor_background`, `micro_presence`, `autonomous`, `vision_ambient`.

### 2. Transport remote đi qua broker

- `llm/client.py`: mọi request OpenAI-compatible, Groq và Gemini REST đều reserve qua broker trước HTTP.
- `runtime/tts_engine.py`: Gemini TTS, TTS localizer và romaji localizer dùng broker.
- `runtime/speech_localizer.py`: Google GenAI SDK không còn là đường vòng né admission control.
- `actions/executor.py`: Gemini weather grounding không còn gọi `requests.post()` trực tiếp ngoài broker.
- `memory/memory_ai_curator.py`, `runtime/tutor_wiring.py`, `runtime/private_mind_loop.py`: gắn đúng lane, optionality, deadline và coalesce key.

### 3. Sửa prompt hard-cap

- Sửa lỗi control-flow trong `llm/token_budget.py`.
- Không có cấu hình tường minh thì dùng headroom theo provider.
- Giá trị runtime mặc định đổi từ `0` sang `5100`, tương đương 85% trần Groq 6000 TPM.
- `0` chỉ còn mang nghĩa vô hạn khi được đặt tường minh; có thể dùng `ERIS_DISABLE_PROMPT_HARD_CAP=1` để tắt rõ ràng.

### 4. Một semantic authority cho chat

- File mới: `runtime/semantic_frame.py`.
- `generate_public_reply` trả cả `semantic_frame.v1` và public wording trong cùng lượt model.
- Ở chế độ production `primary_model`, legacy discourse/semantic/social classifier đã bị cắt khỏi critical path; chỉ còn sau cờ `legacy` để rollback.
- Normal chat bỏ remote planner nối tiếp; planner remote chỉ giữ cho action/tool turn thực sự cần thiết.
- Invariant logic xử lý target, continuation, ambiguity owner, missing evidence và tool obligation mà không tạo thêm regex semantic.
- Nếu wording/grounding gate yêu cầu retry, runtime khóa nguyên semantic frame và chỉ gọi schema viết lại wording; model không được phân loại lại lượt user.

### 5. Background chuyển sang delta/admission driven

- Vision ambient: chu kỳ mặc định 45 giây, tối thiểu 30 giây; remote summarize chỉ chạy khi frame delta đạt ngưỡng mặc định `0.15`.
- PrivateMind: debounce tối thiểu 30 giây, mặc định 45 giây; chỉ chạy khi state signature đổi hoặc đến idle consolidation 3-5 phút.
- Observer: đợi user turn kết thúc, có deadline/cancel scope, không chen vào critical path.
- Tutor, memory digest, autonomous/localizer lanes: optional và bị shed/coalesce khi chat đang hoạt động hoặc provider nóng.
- Tutor background có cooldown theo topic và coalesce key theo topic cho cả question generation lẫn distillation.
- TTS/current-turn audio là lane có điều kiện, được bỏ trước khi ảnh hưởng chat.

### 6. Đo acceptance theo đúng chỉ tiêu PDF

- `runtime/chat_cycle.py` ghi `user_turn_latency_ms` cho toàn lượt, không chỉ thời gian HTTP.
- Broker ghi `remote_calls_per_user_turn`, queue wait, reject reason, token thực dùng theo lane/provider.
- `tools/report_pdf_acceptance.py` đọc JSONL và xuất P50/P95/P99, remote calls/turn, 429 theo lane và pass/fail cho các ngưỡng có thể kiểm tra trong một cửa sổ log.


## Phần làm tiếp trong bản này

Bản tiếp tục này hoàn thiện thêm các hạng mục P2 và một lỗi điều phối chưa lộ ra trong unit test cũ:

- **Loại head-of-line blocking giữa provider:** queue vẫn giữ priority trong từng quota domain, nhưng một request OpenAI đang cooldown không còn chặn request Gemini/Groq độc lập phía sau.
- **Project budget nội bộ:** broker hỗ trợ RPM/TPM/ITPM/OTPM theo project bằng biến môi trường, đồng thời settle/refund cùng usage thật. Đây là vùng đệm thấp hơn trần organization như PDF đề xuất ở trang 19.
- **Provider heat chủ động:** optional lane bị shed khi mức dùng RPM/TPM/ITPM/OTPM vượt ngưỡng nóng, thay vì đợi 429 rồi mới biết hệ thống đã cư xử như một đám người cùng lao qua một cánh cửa.
- **Per-lane SLO:** priority, deadline, queue bound và concurrency có thể chỉnh riêng theo lane mà không sửa caller.
- **Adaptive background:** Vision và PrivateMind tăng cooldown/ngưỡng delta theo áp lực provider; Tutor có cả cooldown thích nghi và rolling budget theo từng topic.
- **Fast-path đúng vai trò:** local degraded reply chỉ chạy sau khi remote authority thất bại và chỉ nhận exact greeting/acknowledgement; các câu mở như `hôm nay em sao` tuyệt đối không bị regex fast-path diễn giải.
- **Acceptance before/after:** `tools/report_pdf_acceptance.py` nhận thêm `--baseline` để tính thật mức giảm 429 optional lane và pass/fail mốc 80%.

### Cấu hình bổ sung

```dotenv
# Ngưỡng provider nóng; có thể override riêng từng lane.
ERIS_BROKER_HOT_UTILIZATION=0.82
ERIS_BROKER_HOT_UTILIZATION_VISION_AMBIENT=0.75

# SLO riêng theo lane.
ERIS_BROKER_PRIORITY_VISION_AMBIENT=95
ERIS_BROKER_MAX_QUEUED_VISION_AMBIENT=1
ERIS_BROKER_DEADLINE_SEC_VISION_AMBIENT=18
ERIS_BROKER_LANE_CONCURRENCY_VISION_AMBIENT=1

# Project budget nội bộ. Tên provider/project được viết hoa và thay ký tự lạ bằng dấu gạch dưới.
ERIS_BROKER_PROJECT_RPM_OPENAI_ALPHA=20
ERIS_BROKER_PROJECT_TPM_OPENAI_ALPHA=4000
ERIS_BROKER_PROJECT_ITPM_OPENAI_ALPHA=3200
ERIS_BROKER_PROJECT_OTPM_OPENAI_ALPHA=900

# Tutor rolling budget theo topic.
ERIS_TUTOR_TOPIC_MAX_CALLS_PER_HOUR=2
ERIS_TUTOR_DISTILL_TOPIC_MAX_CALLS_PER_HOUR=1

# Chỉ là degraded/offline escape hatch.
ERIS_DEGRADED_CHAT_FASTPATH=1
```

So sánh acceptance trước/sau:

```bash
python tools/report_pdf_acceptance.py \
  --baseline logs/before_refactor.jsonl \
  --input logs/after_refactor.jsonl \
  --output logs/pdf_acceptance_comparison.json
```

## File thay đổi chính

- `runtime/inference_broker.py` - mới
- `runtime/semantic_frame.py` - mới
- `runtime/degraded_chat_fastpath.py` - mới, chỉ dùng khi remote thất bại
- `runtime/topic_budget.py` - mới, rolling budget theo topic
- `llm/client.py`
- `llm/service.py`
- `llm/token_budget.py`
- `llm/token_pressure.py`
- `runtime/ai_orchestrated/model_router.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/ai_orchestrated/planner.py`
- `runtime/ai_orchestrated/observer.py`
- `runtime/coordinator.py`
- `runtime/private_mind_loop.py`
- `runtime/tutor_wiring.py`
- `runtime/tts_engine.py`
- `runtime/speech_localizer.py`
- `runtime/affect_self_read.py`
- `runtime/memory_semantic_parser_adapter.py`
- `runtime/project_operations.py`
- `cortex/daydream_consolidation.py`
- `cortex/vision_semantic_compressor.py`
- `memory/memory_ai_curator.py`
- `runtime/runtime_settings_store.py`
- `settings/runtime_settings.json`
- `tests/test_pdf_inference_refactor.py` - mới
- `tools/report_pdf_acceptance.py` - mới

## Cấu hình mới/hữu ích

```dotenv
ERIS_INFERENCE_BROKER_ENABLED=1
ERIS_BROKER_RPM_GROQ=30
ERIS_BROKER_TPM_GROQ=6000
ERIS_BROKER_ITPM_GROQ=5000
ERIS_BROKER_OTPM_GROQ=1200
ERIS_BROKER_CONCURRENCY_GROQ=2
ERIS_VISION_FACTS_INTERVAL=45
ERIS_VISION_SCREEN_DELTA_THRESHOLD=0.15
ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC=45
ERIS_PRIVATE_MIND_IDLE_CONSOLIDATION_SEC=240
ERIS_POST_OBSERVER_DEADLINE_SEC=4
ERIS_TUTOR_TOPIC_COOLDOWN_SEC=180
ERIS_TUTOR_DISTILL_TOPIC_COOLDOWN_SEC=300
```

Không cần chép tất cả vào `.env`; đây là các giá trị mặc định hoặc núm chỉnh khi đo canary.

## Kiểm thử đã chạy

```text
python -m compileall -q .       PASS
python -m pytest -q             186 passed
```

Bộ test khóa split ITPM/OTPM, settle usage thật, cancellation, wording-only retry, project budget, proactive shedding, cross-provider queue fairness, per-lane SLO, Tutor topic budget, degraded fast-path và baseline 429 comparison.

## Giới hạn cần biết

- Chưa thể khẳng định P50/P95 thực tế nếu không chạy trên máy của bạn với provider, key pool, model và log thật. Unit/integration hiện tại xác nhận logic, không giả vờ biến benchmark thành phép bói.
- Một HTTP/SDK request đã thực sự on-wire không phải lúc nào cũng cưỡng bức dừng được nếu thư viện provider không hỗ trợ abort. Broker hiện truyền cancellation/deadline xuống adapter, giới hạn timeout còn lại, ngăn retry/child request tiếp theo và bỏ kết quả quá hạn.
- Khi provider không trả usage, broker vẫn phải giữ reservation bảo thủ; khi có usage, reservation được settle tự động.
- P50/P95 và mức giảm 429 chỉ có thể kết luận sau khi chạy workload thật. Tool báo cáo đã có, nhưng máy tính vẫn chưa học được cách benchmark một mạng chưa từng được kết nối.
- Thư mục `body` không chứa remote inference pipeline nên được giữ nguyên; nó vẫn được đóng chung trong gói để thay project một lần.

## Cách dùng gói

1. Sao lưu project ERIS hiện tại.
2. Thay thư mục `src` bằng thư mục `src` trong gói.
3. Thay/đồng bộ thư mục `body` nếu project của bạn tách riêng Live2D body.
4. Giữ API key trong `.env` cục bộ; gói không thêm key mới.
5. Chạy `python -m pytest -q` trước khi chạy app thật.
6. Theo dõi log `broker_*`, 429 theo lane và latency trước/sau trong một phiên canary.

## Full-PDF V6

- Required lane adaptive degradation được áp trước khi queue theo TPM/ITPM/OTPM còn lại.
- Broker chỉ degrade khi transport khai báo có khả năng sửa payload thật.
- `_brokered_post()` rút messages và output cap theo effective reservation.
- In-flight optional preemption chuyển từ global sang đúng provider/project/model-family domain.
- Concurrency key chuẩn hóa theo model family.
- Acceptance report bổ sung degradation/preemption diagnostics.
- Regression suite hiện có 206 test pass.
