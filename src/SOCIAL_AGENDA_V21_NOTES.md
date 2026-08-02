# Eris Social Agenda V21 - Production hardening và evaluation harness

## Phạm vi

V21 tiếp tục bản V20 và xử lý phần còn thiếu để đưa kiến trúc `afterbeat` → `social_exposure` → `conversation_arc` → `social_agenda` vào rollout có kiểm soát. Mục tiêu không phải làm Eris nói nhiều hơn. Mục tiêu là giữ quyền lượt, chống phát trùng, đo activation thật và có đường lui khi model bỗng quá nhiệt tình, một hiện tượng phần mềm rất giống con người nhưng kém duyên hơn.

## Thay đổi chính

### 1. Atomic persistence thật

Thêm `runtime/ai_orchestrated/atomic_state.py` với SQLite WAL, `BEGIN IMMEDIATE`, revisioned compare-and-swap và lease.

Các runtime sau dùng state bền vững khi `ERIS_SOCIAL_ATOMIC_BACKEND=sqlite`:

- `SocialContinuationRuntime`
- `ConversationArcRuntime`
- `SocialAgendaStore`
- `PublicTurnTransactionRegistry`

Hai worker không thể claim cùng một continuation trên cùng revision. Worker cũ không được hoàn tất sau khi lease hết hạn và ticket đã bị worker khác reclaim. Receipt idempotency lưu kết quả public turn để retry/restart không bình thản phát cùng một audio hai lần.

Giới hạn trung thực: SQLite không thể tạo transaction nguyên tử với loa/TTS bên ngoài. Vẫn có một crash window hẹp sau side effect và trước receipt commit. Patch loại bỏ duplicate do concurrent worker và retry thông thường, không tuyên bố đã sửa vật lý của vũ trụ.

### 2. Rollout và canary

Thêm `SocialRolloutPolicy` với assignment ổn định theo session hash:

- `off`: giữ baseline conversation arc.
- `shadow`: ghi proposal, không cấp microphone rights.
- `active`: kích hoạt theo variant.

Variant:

- `control`: conversation arc baseline.
- `afterbeat`: thêm reserved afterbeat.
- `exposure`: thêm reaction window/recovery.
- `full`: thêm social agenda.

Default V21 là `shadow`. Cấu hình mẫu nằm ở `config/social_agenda_v21.env.example`.

### 3. Voice floor signal protocol

`STAGE_PROTOCOL_VERSION` tăng lên 3 và nhận:

- `vad_start`
- `partial_asr`
- `final_asr`
- `laugh`
- `backchannel`
- `audio_playback_aborted`

Speech signal hủy continuation ngắn và arc không còn hợp lệ. Laugh/backchannel resolve reaction window thay vì đợi timer rồi tự diễn giải im lặng. Playback abort cũng invalidates ticket liên quan.

### 4. Evaluation không tiêm decision

`tools/evaluate_social_plan_activation.py` replay corpus với output model đã capture hoặc callable `module:function`. Harness đo precision/recall/F1 riêng cho bốn lane và safety over-trigger rate. Không lane nào bị ép `schedule`.

Artifact mẫu:

- `research/social_activation_cases.sample.jsonl`
- `research/social_activation_predictions.synthetic.jsonl`
- `research/README_social_eval_vi.md`

Prediction mẫu chỉ là fixture kiểm tra harness. Nó không phải kết quả model.

### 5. A/B và dashboard

- `tools/analyze_social_ab.py`: tổng hợp rating theo variant, mean, SD và CI 95%.
- `tools/export_social_dashboard.py`: xuất HTML/JSON từ telemetry và SQLite state.
- `research/social_ab_ratings.template.jsonl`: schema rating minh họa.

### 6. CI và archive portability

CI chạy compile, architecture budget, exception budget, manifest, activation fixture, focused social tests và full suite. Hai test contract Godot body có fallback tới `integration/body_contracts`, nên source archive không còn phụ thuộc một thư mục bí ẩn nằm cạnh checkout. Các file đó là fixture contract, không phải implementation Godot hoàn chỉnh để chép đè bằng niềm tin.

## Cách chạy

```bash
cp config/social_agenda_v21.env.example .env.social
python -m pytest -q tests/test_social_agenda_production_v21.py
python tools/evaluate_social_plan_activation.py \
  --cases research/social_activation_cases.sample.jsonl \
  --predictions research/social_activation_predictions.synthetic.jsonl \
  --output-dir artifacts/social_activation_fixture
python tools/export_social_dashboard.py \
  --telemetry logs/eris_observability.jsonl \
  --db memory/eris_social_runtime.sqlite3
```

## Kết quả xác minh

- Focused social/voice suite: **52 passed**.
- Full repository suite: **660 passed**.
- Full suite cũng đạt **660 passed** khi bỏ thư mục body bên ngoài, nhờ fixture contract nội bộ.
- `compileall`, architecture budget, exception budget và release manifest đều pass.
- Activation harness fixture: 12/12 case, macro F1 1.0, safety over-trigger 0. Đây chỉ chứng minh evaluator đọc và chấm đúng fixture.

## Chưa thể xác minh từ archive

Các mục sau cần hạ tầng hoặc dữ liệu thật và không được giả vờ là đã hoàn tất:

- Audition ElevenLabs bằng credential production.
- End-to-end VAD/partial ASR/laugh signal từ frontend và microphone thật.
- Precision/recall activation của model trên corpus Bunpo/Eris thật.
- Blind listening A/B với người dùng.

Code, feature flag, telemetry và harness cho các bước đó đã có. Cross-session social agenda vẫn tắt mặc định cho tới khi consent, retention, export/delete và calibration được chốt.
