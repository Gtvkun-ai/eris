# Implementation Plan — Phase 2: Meaning & Theory of Mind

## Overview

Triển khai Phase 2 theo hướng test-driven, từng bước tăng tiến. Trình tự: dựng nền tảng dùng chung (dataclasses, `clamp01`, errors, `Taxonomy`, `FrameReadView`/`ReadContract`, `StageLedger`, config object, hypothesis `frames` strategy) trước; sau đó hiện thực từng stage theo **đúng thứ tự pipeline bắt buộc** (`WorldSceneBuilder → WorldInterpreter → SocioculturalContext → MeaningHypothesisEngine → PragmaticIntentEngine → TheoryOfMindCore → OverreadBrake → SurfaceMeaningPolicy → Debug`), rồi wiring facade + integration.

`MeaningHypothesisEngine` **bọc** (`wrap`) `SemanticHypothesisEngine` (`semantic_hypothesis.py`) và `MeaningLayer` (`meaning.py`) — không reimplement scoring (R5.7).

Quy ước test: `pytest` + `hypothesis`, mỗi file test mở đầu bằng `sys.path.insert(0, "src")` để import `cortex.*`; mỗi property-based test cấu hình `@settings(max_examples=100)` tối thiểu và gắn comment `# Feature: phase2-meaning-tom, Property {n}: {text}`. 32 correctness property = đúng 32 property-based test.

## Tasks

- [x] 1. Dựng package scaffolding và data models nền tảng
  - [x] 1.1 Tạo cấu trúc package và test helper
    - Tạo `src/cortex/meaning/__init__.py`, `src/cortex/tom/__init__.py` và các file module rỗng theo package layout của design
    - Thêm helper import dùng chung cho test: chèn `sys.path.insert(0, "src")` theo quy ước `tests/test_pbt_*.py`
    - _Requirements: 1.1_

  - [x] 1.2 Hiện thực shared dataclasses, `clamp01`, errors và `tom/contracts.py`
    - Trong `src/cortex/meaning/` định nghĩa các `@dataclass(slots=True)`: `WorldSceneElement`, `WorldScene`, `Observation`, `ContextAnnotation`, `MeaningHypothesis`, `PragmaticIntent`, `EvaluatedConclusion`, `SurfaceDecision`, `Phase2Result`, `StageDebug`; alias `Conclusion`
    - Trong `src/cortex/tom/contracts.py` định nghĩa `MentalStateInference`, `ToMHistory`, và các lỗi contract ToM
    - Thêm helper `clamp01` (nguồn duy nhất) clamp `confidence`/`ambiguity`/`overread_risk` về [0.0, 1.0] tại điểm khởi tạo
    - Định nghĩa exceptions: `RawWorldAccessError`, `InvalidWorkspaceFrameError`, `WorldSceneValidationError`, `ToMOrderingViolation`, `ConfigurationError`
    - _Requirements: 1.5, 8.5, 9.5_

  - [x]* 1.3 Viết unit test cho `clamp01` và việc clamp khi khởi tạo dataclass
    - Đặt trong `tests/test_phase2_integration.py`; kiểm giá trị ngoài [0,1] bị kẹp đúng biên
    - _Requirements: 1.5_

- [x] 2. Hiện thực Taxonomy registry và startup validation
  - [x] 2.1 Implement `taxonomy.py`
    - Khai báo `MEANING`/`INTENT`/`MENTAL_STATE` từ `tuple` nguồn rồi đóng băng thành `frozenset` (mỗi set ≥ 1 category)
    - `validate_on_startup()` so độ dài tuple với độ dài set để phát hiện trùng id → `ConfigurationError(id, set)`
    - `require(set_name, category_id)` là cổng bắt buộc trước mọi gán category; id không hợp lệ → `ConfigurationError(category_id, set_name)`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x]* 2.2 Viết Taxonomy smoke test (uniqueness + ba set hiện diện)
    - Đặt trong `tests/test_phase2_integration.py`; kiểm `validate_on_startup` chặn trùng id và cả ba set không rỗng
    - _Requirements: 11.1, 11.4_

- [x] 3. Hiện thực config object và StageLedger
  - [x] 3.1 Implement `Phase2Config` và `StageLedger`
    - `Phase2Config`: nguồn duy nhất của mọi threshold (`max_hypotheses=4`, `ambiguity_margin=0.08`, `meaning_low_conf=0.2`, `interpreter_low_conf=0.5`, `overread_reduction_threshold=0.70`, `overread_suppression_threshold=0.90`, `reduced_conf_cap=0.50`, `min_evidence_count=2`, `surface_conf_threshold`, `ambiguity_threshold`)
    - `StageLedger.record(stage, frame_id)` / `has(stage, frame_id)` cho ToM-after-Meaning guard
    - _Requirements: 7.2_

  - [x]* 3.2 Viết unit test cho `StageLedger.record`/`has`
    - Đặt trong `tests/test_theory_of_mind.py`; kiểm record/has theo từng `frame_id`
    - _Requirements: 7.2_

- [x] 4. Hiện thực ReadContract guard (WorkspaceFrame-only enforcement)
  - [x] 4.1 Implement `read_contract.py` với `FrameReadView`
    - `FrameReadView` chỉ expose getter cho field nằm trong `downstream_contract[module]`; mỗi getter gắn tên module gọi (R1.3)
    - Field ngoài hợp đồng hoặc bất kỳ kênh Raw_World → ném `RawWorldAccessError(module_name, field_name)`; lần đọc trả dữ liệu không mutate; ghi `debug.contract_violations`
    - Không import bất kỳ symbol Raw_World (`raw_signals`/evidence thô/memory thô)
    - _Requirements: 1.1, 1.2, 1.3_

  - [x]* 4.2 Viết unit test `RawWorldAccessError` cho field ngoài hợp đồng
    - Đặt trong `tests/test_world_scene_builder.py`; xác nhận đọc field ngoài `downstream_contract` ném `RawWorldAccessError` chỉ rõ tên module + field, dữ liệu không bị mutate
    - _Requirements: 1.2_

  - [x]* 4.3 Viết AST no-direct-read scan test
    - Đặt trong `tests/test_phase2_integration.py`; quét AST mọi module trong `src/cortex/meaning/` và `src/cortex/tom/` khẳng định không import/tham chiếu symbol Raw_World
    - _Requirements: 13.5_

- [x] 5. Hiện thực shared hypothesis `frames` strategy
  - [x] 5.1 Viết generator `frames` dùng chung cho property tests
    - Đặt trong `tests/conftest.py` (hoặc module helper được các test import): sinh `WorkspaceFrame` hợp lệ (random `frame_id`/`timestamp`/`budget_mode`, 0..N `WorkspaceItem` với `evidence_ids` không rỗng, `priority`/`confidence` ∈ [0,1], `kind` thuộc literal set, optional `dominant_thread` lấy từ `active_threads`, optional `social_hypotheses`, `forbidden_assumptions`, `downstream_contract`)
    - Thêm strategy dẫn xuất: frame `broadcast_items` rỗng (P9), frame thiếu field bắt buộc (P6), tập hypothesis near-tie (P18/P31), candidate không có evidence (P1/P11), conclusion trải các band ngưỡng OverreadBrake (P27–29)
    - _Requirements: 13.8_

- [x] 6. Hiện thực WorldSceneBuilder (stage 1)
  - [x] 6.1 Implement `world_scene_builder.py` `build(view)`
    - Chỉ đọc field trong `downstream_contract["WorldSceneBuilder"]`; có `broadcast_items` → đúng một `WorldScene` với `entities`/`salient_signals`/`active_threads`, mỗi element `confidence ∈ [0,1]`; bảo toàn nguyên vẹn `evidence_ids`; `dominant_thread` → đúng một element `is_dominant_focus=True`; `view is None` → scene rỗng `confidence=0.0` + reason; `broadcast_items` rỗng → một scene rỗng có reason; frame malformed → `InvalidWorkspaceFrameError`; thiếu field bắt buộc → cap `confidence ≤ 0.5` + ghi tên field, gắn `frame_id` vào artifact
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x]* 6.2 Viết property test — Property 7
    - **Property 7: WorldScene structure and confidence bounds** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 2.1, 2.2**

  - [x]* 6.3 Viết property test — Property 8
    - **Property 8: Exactly one dominant focus when dominant_thread present** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 2.3**

  - [x]* 6.4 Viết property test — Property 9
    - **Property 9: Empty-frame yields exactly one empty scene** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 2.4**

  - [x]* 6.5 Viết property test — Property 10
    - **Property 10: Evidence_id preservation** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 2.5**

  - [x]* 6.6 Viết property test — Property 5
    - **Property 5: Frame_id traceability** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 1.5, 12.4**

  - [x]* 6.7 Viết property test — Property 6
    - **Property 6: Missing-field confidence cap** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 1.6**

  - [x]* 6.8 Viết unit test edge cases cho WorldSceneBuilder
    - `build(None)` → scene rỗng confidence 0.0 (R1.4); frame malformed → `InvalidWorkspaceFrameError` (R2.6)
    - File `tests/test_world_scene_builder.py`
    - _Requirements: 1.4, 2.6_

- [x] 7. Hiện thực WorldInterpreter (stage 2)
  - [x] 7.1 Implement `world_interpreter.py` `interpret(scene, low_conf_threshold)`
    - Scene ≥1 element → 0..n `Observation`, mỗi cái `confidence ∈ [0,1]` + ≥1 `evidence_id` + `source_element_id`; element `confidence < threshold` → observation `low_confidence=True`; candidate không gắn được evidence → loại; **không** sinh intent/mental-state; scene rỗng/None/sai cấu trúc → `WorldSceneValidationError`, observation cũ giữ nguyên
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x]* 7.2 Viết property test — Property 11
    - **Property 11: Observations are well-formed and traceable** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 3.1, 3.4, 3.6**

  - [x]* 7.3 Viết property test — Property 12
    - **Property 12: WorldInterpreter stays in scope** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 3.2**

  - [x]* 7.4 Viết property test — Property 13
    - **Property 13: Low-confidence propagation** (file `tests/test_world_scene_builder.py`)
    - **Validates: Requirements 3.3**

  - [x]* 7.5 Viết unit test scene invalid cho WorldInterpreter
    - Scene rỗng/None/sai cấu trúc → `WorldSceneValidationError`, observation cũ giữ nguyên
    - File `tests/test_world_scene_builder.py`
    - _Requirements: 3.5_

- [x] 8. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Hiện thực SocioculturalContext (stage 3)
  - [x] 9.1 Implement `sociocultural_context.py` `annotate(observations, view)`
    - Đủ ba ngữ cảnh (relationship/register/social-norm) → annotate cả ba cho mỗi observation, mỗi annotation `confidence ∈ [0,1]`; `social_hypotheses` đưa vào `unconfirmed` (không coi là fact); thiếu loại nào → áp neutral default + ghi `defaults_applied`; observation set rỗng → không annotation, không lỗi
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x]* 9.2 Viết property test — Property 14
    - **Property 14: Full sociocultural annotation when contexts present** (file `tests/test_sociocultural_context.py`)
    - **Validates: Requirements 4.1, 4.5**

  - [x]* 9.3 Viết property test — Property 15
    - **Property 15: Social hypotheses remain unconfirmed** (file `tests/test_sociocultural_context.py`)
    - **Validates: Requirements 4.2**

  - [x]* 9.4 Viết property test — Property 16
    - **Property 16: Neutral defaults applied and recorded** (file `tests/test_sociocultural_context.py`)
    - **Validates: Requirements 4.3, 4.4**

  - [x]* 9.5 Viết unit test observation set rỗng
    - Kết thúc không lỗi, không annotation (file `tests/test_sociocultural_context.py`)
    - _Requirements: 4.6_

- [x] 10. Hiện thực AmbiguityModule
  - [x] 10.1 Implement `ambiguity.py` `compute(hypotheses)`
    - ≥2 hypothesis → `ambiguity ∈ [0,1]`; đúng 1 không đối thủ → `[0.0, 0.1]`; `|Δconf| top-2 ≤ 0.05` → `[0.9, 1.0]`; 0 hypothesis → `0.0` + chỉ báo "no hypotheses"; có `confidence` ngoài [0,1] → từ chối tập, chỉ báo invalid, giữ nguyên ambiguity trước đó
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x]* 10.2 Viết property test — Property 31
    - **Property 31: Ambiguity computation bounds** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 9.1, 9.2, 9.3**

  - [x]* 10.3 Viết unit test invalid-input retention và 0-hypothesis
    - Input invalid → giữ ambiguity trước (R9.5); 0 hypothesis → 0.0 + chỉ báo (R9.4)
    - File `tests/test_phase2_integration.py`
    - _Requirements: 9.4, 9.5_

- [x] 11. Hiện thực MeaningHypothesisEngine (stage 4 — WRAP, không reimplement scoring)
  - [x] 11.1 Implement `meaning_hypothesis.py` adapter bọc engine hiện hữu
    - Inject `SemanticHypothesisEngine` (`semantic_hypothesis.py`) + `MeaningLayer` (`meaning.py`) + `AmbiguityModule`; gọi `compare/compare_many` lấy `SemanticHypothesisReport`, lấy meaning-slot từ `MeaningLayer`; **adapt** `SemanticHypothesis` → `MeaningHypothesis` (giữ `confidence`, dùng `report.ambiguity` cho `ambiguity`, suy `overread_risk`); gán `category` qua `Taxonomy.require`
    - Sinh 1..`max_hypotheses` (default 4); mỗi hypothesis `evidence_ids` không rỗng + ba chỉ số ∈ [0,1]; hai+ hypothesis `|Δconf| ≤ margin` → tăng `ambiguity` (≤1.0); không hypothesis nào được evidence chống đỡ → đúng một "insufficient evidence" với `confidence < low_conf_threshold`; xếp giảm dần `confidence`, tie-break tăng dần `ambiguity`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x]* 11.2 Viết property test — Property 17
    - **Property 17: Meaning hypotheses count and metric bounds** (file `tests/test_meaning_hypothesis.py`)
    - **Validates: Requirements 5.1, 5.2**

  - [x]* 11.3 Viết property test — Property 18
    - **Property 18: Near-tie hypotheses raise ambiguity** (file `tests/test_meaning_hypothesis.py`)
    - **Validates: Requirements 5.3**

  - [x]* 11.4 Viết property test — Property 19
    - **Property 19: Insufficient-evidence fallback** (file `tests/test_meaning_hypothesis.py`); bao gồm case R5.4
    - **Validates: Requirements 5.4**

  - [x]* 11.5 Viết property test — Property 20
    - **Property 20: Meaning hypotheses ordering** (file `tests/test_meaning_hypothesis.py`)
    - **Validates: Requirements 5.5, 5.6**

  - [x]* 11.6 Viết delegation spy test (xác nhận WRAP)
    - Dùng spy/mock khẳng định `MeaningHypothesisEngine` delegate tới `SemanticHypothesisEngine` và `MeaningLayer`, không reimplement scoring
    - File `tests/test_meaning_hypothesis.py`
    - _Requirements: 5.7_

- [x] 12. Hiện thực PragmaticIntentEngine (stage 5)
  - [x] 12.1 Implement `pragmatic_intent.py` `derive(hypotheses, frame_id)`
    - Ranked không rỗng → 1..8 intent, mỗi cái đúng một category trong `Taxonomy.INTENT` (qua `require()`); chỉ suy từ `MeaningHypothesis` (không Raw_World); mỗi intent `confidence ∈ [0,1]` + ≥1 `supporting_meaning_ids` (giữ cả khi `confidence==0.0`); có supporter `ambiguity > 0.7` → intent nhận `confidence` **nghiêm ngặt thấp hơn**; tập rỗng → 0 intent + chỉ báo "no pragmatic intent"
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x]* 12.2 Viết property test — Property 21
    - **Property 21: Pragmatic intent count and valid categories** (file `tests/test_pragmatic_intent.py`)
    - **Validates: Requirements 6.1, 11.2**

  - [x]* 12.3 Viết property test — Property 22
    - **Property 22: Intents retain supporting references and confidence bounds** (file `tests/test_pragmatic_intent.py`)
    - **Validates: Requirements 6.3**

  - [x]* 12.4 Viết property test — Property 23
    - **Property 23: High ambiguity lowers intent confidence** (file `tests/test_pragmatic_intent.py`)
    - **Validates: Requirements 6.4**

  - [x]* 12.5 Viết unit test tập hypothesis rỗng
    - 0 intent + chỉ báo "no pragmatic intent" (file `tests/test_pragmatic_intent.py`)
    - _Requirements: 6.5_

- [x] 13. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Hiện thực Theory of Mind (stage 6)
  - [x] 14.1 Implement `tom_history_adapter.py` `ToMHistoryAdapter.load(view)`
    - Chỉ lấy history từ `WorkspaceFrame`; thiếu history → `ToMHistory(available=False)` + ghi "history unavailable", ToM vẫn chạy tiếp
    - _Requirements: 7.5, 7.8_

  - [x] 14.2 Implement `theory_of_mind.py` `TheoryOfMindCore.infer(...)` với ledger guard
    - Mở đầu kiểm `StageLedger`: nếu `MeaningHypothesisEngine` hoặc `PragmaticIntentEngine` chưa có entry cho `frame_id` → từ chối, trả tập rỗng, ghi `ToMOrderingViolation(missing_stage, frame_id)`; chữ ký chỉ nhận `meaning`/`intents` (không tham số câu thô); mỗi inference category ∈ `Taxonomy.MENTAL_STATE`, `confidence ∈ [0,1]`, có `supporting_meaning_ids`; không gắn được tham chiếu → vẫn sinh nhưng `unsupported=True`
    - _Requirements: 7.1, 7.2, 7.6, 7.7_

  - [x] 14.3 Implement `mental_state_ranker.py` `MentalStateRanker.rank()`
    - Giảm dần theo `confidence`; bằng confidence → `overread_risk` thấp hơn xếp trên
    - _Requirements: 7.3_

  - [x] 14.4 Implement `counterfactual_corrector.py` `CounterfactualCorrector.correct()`
    - Tồn tại giải thích phản thực `confidence ≥ threshold` → giảm `confidence` (không dưới 0.0) + ghi `counterfactual_reason`
    - _Requirements: 7.4_

  - [x]* 14.5 Viết property test — Property 24
    - **Property 24: Mental-state inferences are bounded and supported** (file `tests/test_theory_of_mind.py`)
    - **Validates: Requirements 7.6, 7.7, 11.2**

  - [x]* 14.6 Viết property test — Property 25
    - **Property 25: Mental-state ranking order** (file `tests/test_theory_of_mind.py`)
    - **Validates: Requirements 7.3**

  - [x]* 14.7 Viết property test — Property 26
    - **Property 26: Counterfactual reduction stays in range and is recorded** (file `tests/test_theory_of_mind.py`)
    - **Validates: Requirements 7.4**

  - [x]* 14.8 Viết unit test ordering violation, history-absent, positive ordering
    - ToM chạy trước Meaning/Pragmatic → `ToMOrderingViolation` + tập rỗng (R7.2, R13.3); thiếu history → ToM vẫn chạy (R7.8); ToM-after-Meaning hợp lệ chạy đúng (R13.4)
    - File `tests/test_theory_of_mind.py`
    - _Requirements: 7.2, 7.8, 13.3, 13.4_

- [x] 15. Hiện thực OverreadBrake (stage 7)
  - [x] 15.1 Implement `overread_brake.py` `evaluate(conclusions, forbidden_assumptions)`
    - Áp cho mọi `Conclusion`: `reduction ≤ overread_risk < suppression` → giảm `confidence ≤ reduced_conf_cap`; `overread_risk ≥ suppression` → `overread_suppressed=True`; `len(evidence_ids) < min_evidence_count` → suppressed; khẳng định `forbidden_assumption` như fact → suppressed + ghi lý do; mọi giảm/suppress ghi `reason`/`metric_name`/`metric_value`; conclusion suppressed được giữ trong debug kèm `original_confidence` + metric gốc
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x]* 15.2 Viết property test — Property 27
    - **Property 27: Overread confidence reduction band** (file `tests/test_overread_brake.py`)
    - **Validates: Requirements 8.1**

  - [x]* 15.3 Viết property test — Property 28
    - **Property 28: Overread suppression conditions** (file `tests/test_overread_brake.py`)
    - **Validates: Requirements 8.2, 8.3, 8.6, 13.6**

  - [x]* 15.4 Viết property test — Property 29
    - **Property 29: Non-suppression below threshold** (file `tests/test_overread_brake.py`)
    - **Validates: Requirements 13.7**

  - [x]* 15.5 Viết property test — Property 30
    - **Property 30: Brake records and preserves originals** (file `tests/test_overread_brake.py`)
    - **Validates: Requirements 8.4, 8.5**

- [x] 16. Hiện thực SurfaceMeaningPolicy (stage 8)
  - [x] 16.1 Implement `surface_meaning_policy.py` `partition(evaluated, frame_id)`
    - Phân mỗi conclusion vào đúng một trong {surfaced, withheld} theo thứ tự ưu tiên: suppressed → withheld; không evidence → withheld; `ambiguity == 1.0` → withheld; `confidence < surface_conf_threshold` → withheld; `≥ threshold` và `ambiguity ∈ [ambiguity_threshold, 1.0)` → surfaced tentative; `≥ threshold` và `ambiguity < ambiguity_threshold` → surfaced asserted; trả `Phase2Result` ghi cả hai tập + đúng một `SurfaceDecision`/conclusion; bất biến: mọi phần tử `surfaced` có ≥1 evidence
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [x]* 16.2 Viết property test — Property 2
    - **Property 2: Surface partition is total and disjoint** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 10.1, 10.5**

  - [x]* 16.3 Viết property test — Property 3
    - **Property 3: Surface classification rules hold** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.6, 10.7**

- [x] 17. Hiện thực DebugRender và ToMDebug
  - [x] 17.1 Implement `debug_render.py` (`DebugRender`) và `tom/tom_debug.py` (`ToMDebug`)
    - Bản ghi người-đọc-được: mỗi stage kèm ba chỉ số ∈ [0,1] (thiếu → "unavailable"); mọi conclusion suppressed/withheld kèm lý do; `frame_id` của run (thiếu → "frame_id unavailable"); `ToMDebug` render mỗi inference + `supporting_meaning_ids`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x]* 17.2 Viết property test — Property 32
    - **Property 32: Debug record completeness** (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4**

  - [x]* 17.3 Viết unit test "unavailable" handling
    - Thiếu chỉ số ở stage → ghi "unavailable" vẫn render tiếp (R12.5); không có `frame_id` → "frame_id unavailable" (R12.6)
    - File `tests/test_phase2_integration.py`
    - _Requirements: 12.5, 12.6_

- [x] 18. Wiring facade và integration
  - [x] 18.1 Implement `Phase2MeaningPipeline` facade trong `meaning/__init__.py`
    - Khởi tạo `Phase2Config` + `StageLedger`, wrap `WorkspaceFrame` trong `FrameReadView`, chạy đúng thứ tự pipeline bắt buộc, ghi ledger sau mỗi stage (đặc biệt Meaning/Pragmatic trước ToM), trả `Phase2Result`; export pipeline + facade
    - _Requirements: 1.1, 7.2, 13.2_

  - [x]* 18.2 Viết property test — Property 1 (flagship no-overread, ≥100 frames)
    - **Property 1: Surfaced conclusions always carry evidence** — chạy đầy đủ pipeline trên ≥100 `WorkspaceFrame` sinh ngẫu nhiên, mọi conclusion trong `surfaced` có ≥1 evidence (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 10.8, 13.8**

  - [x]* 18.3 Viết property test — Property 4
    - **Property 4: WorkspaceFrame-only boundary** — mutate field ngoài `downstream_contract` của stage không làm đổi output stage đó (file `tests/test_phase2_integration.py`)
    - **Validates: Requirements 1.1, 1.3, 6.2, 7.1, 7.5**

  - [x]* 18.4 Viết integration test end-to-end
    - Một lần chạy `WorkspaceFrame → SurfaceMeaningPolicy → Phase2Result` qua facade (file `tests/test_phase2_integration.py`)
    - _Requirements: 13.2_

- [x] 19. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Task gắn hậu tố `*` là optional (test) và có thể bỏ khi cần MVP nhanh; task không có `*` là core implementation phải làm.
- Mỗi task tham chiếu requirement cụ thể để truy vết; 32 correctness property = đúng 32 property-based test (`@settings(max_examples=100)` tối thiểu), đặt sát stage implementation nhưng ghi đúng file đích theo Test File Mapping của design.
- `MeaningHypothesisEngine` WRAP `SemanticHypothesisEngine` + `MeaningLayer` — task 11.6 là delegation spy test xác nhận không reimplement scoring (R5.7).
- Hai cơ chế cưỡng chế xương sống: `FrameReadView` ném `RawWorldAccessError` + AST scan (task 4); `StageLedger` ToM-after-Meaning guard + ordering-violation test (task 14).
- Property 1 (flagship) là bất biến no-overread trên ≥100 `WorkspaceFrame` (task 18.2).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1", "4.1", "5.1"] },
    { "id": 3, "tasks": ["1.3", "2.2", "3.2", "4.2", "6.1"] },
    { "id": 4, "tasks": ["4.3", "6.2", "6.3", "7.1"] },
    { "id": 5, "tasks": ["6.4", "6.5", "7.4", "9.1"] },
    { "id": 6, "tasks": ["6.6", "6.7", "6.8", "7.5", "10.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "9.4", "9.5", "11.1"] },
    { "id": 8, "tasks": ["7.2", "11.2", "11.3", "12.1"] },
    { "id": 9, "tasks": ["7.3", "11.4", "11.5", "11.6", "12.2"] },
    { "id": 10, "tasks": ["10.2", "12.3", "12.4", "12.5", "14.1"] },
    { "id": 11, "tasks": ["10.3", "14.2"] },
    { "id": 12, "tasks": ["14.3", "14.4"] },
    { "id": 13, "tasks": ["14.5", "14.6", "14.7", "14.8", "15.1"] },
    { "id": 14, "tasks": ["15.2", "15.3", "15.4", "15.5", "16.1"] },
    { "id": 15, "tasks": ["16.2", "17.1"] },
    { "id": 16, "tasks": ["16.3", "17.3", "18.1"] },
    { "id": 17, "tasks": ["17.2"] },
    { "id": 18, "tasks": ["18.2"] },
    { "id": 19, "tasks": ["18.3"] },
    { "id": 20, "tasks": ["18.4"] }
  ]
}
```
