# ERIS Autonomous Initiative V17

## Mục tiêu

Tách hoàn toàn quyết định **có nói hay không** khỏi model generation để:

- tránh treo 15–90 giây rồi trả `silence`;
- giữ body animation sống ngay khi không phát lời;
- có một Surface worker duy nhất cho giọng public;
- kiểm tra grounding trước và sau Surface;
- giữ observer/inner/critic/memory đúng trách nhiệm.

## Contract mới

### `eris.cognitive_blackboard.v1`

Nguồn: `runtime/ai_orchestrated/cognitive_blackboard.py`

Chứa:

- trạng thái observer và dấu hiệu critic deep-review đã hoàn tất;
- public-safe inner seed;
- memory anchor chỉ khi có evidence/provenance;
- conversation baton;
- user busy/privacy;
- screen/activity delta;
- public-safe self seed;
- discovery readiness;
- commentary cadence;
- engagement state;
- typed anchors có evidence refs.

Không chứa:

- raw chain-of-thought;
- raw Inner Diary;
- private concerns;
- chat/mail text riêng tư;
- câu public dự thảo.

### `eris.initiative_decision.v1`

Nguồn: `runtime/ai_orchestrated/initiative.py`

```text
NO_OP | BODY_ONLY | SPEECH
```

`SPEECH` luôn kèm `eris.speech_intent.v1`.

### `eris.speech_intent.v1`

Khóa:

- `mode`;
- `anchor_type`;
- `anchor_id`;
- `evidence_refs`;
- `IntentionPlan` typed;
- số câu tối đa.

Surface Worker không được đổi các giá trị này.

## Đường production

```text
SelfTurnPipeline.run
  ├─ assemble perception/context
  ├─ build TypedCognitiveBlackboard
  │    └─ observer / critic / inner / memory chỉ góp typed signal
  ├─ InitiativeController.decide
  │    ├─ NO_OP → sleep
  │    ├─ BODY_ONLY → Live2D gesture
  │    └─ SPEECH → SpeechIntent
  ├─ GroundingValidator.validate_intent
  ├─ SurfaceIntentEngine.realize
  │    ├─ DeepSeek surface, deadline 4s, drop-if-busy
  │    └─ deterministic fallback nếu provider lỗi
  ├─ GroundingValidator.validate_surface
  └─ public commit → TTS + Live2D
```

## File thay đổi chính

- `runtime/ai_orchestrated/cognitive_blackboard.py`
- `runtime/ai_orchestrated/initiative.py`
- `runtime/ai_orchestrated/surface_intent.py`
- `runtime/ai_orchestrated/grounding_validator.py`
- `runtime/ai_orchestrated/self_turn_pipeline.py`
- `runtime/ai_orchestrated/model_router.py`
- `runtime/ai_orchestrated/bootstrap.py`
- `llm/deepseek_workers.py`

## Quy tắc fallback

Surface timeout/schema/provider lỗi **không** được:

- gọi autonomous planner cũ;
- gọi companion/main brain lần hai;
- retry JSONL thêm một vòng mặc định;
- giữ draft cũ qua attention cycle tiếp theo.

Nó chỉ được:

1. dùng local micro-line nếu SpeechIntent đã duyệt và câu không cần fact mới;
2. hoặc chuyển thành body-only;
3. hoặc no-op.
