# Requirements Document

## Introduction

Phase 2 của kiến trúc nhận thức ERIS xây dựng tầng **hiểu ý nghĩa** (meaning) và **lý thuyết tâm trí** (Theory of Mind). Mục tiêu cốt lõi: ERIS hiểu được ý nghĩa thật sự đằng sau tín hiệu/lời nói **mà không phán bậy** (không over-read, không nhảy tới kết luận khi bằng chứng chưa đủ).

Phase 2 không viết lại từ đầu. Phase 2 **nâng cấp và bọc** (elevate/wrap) các module đã có (`affect_semantics.py`, `meaning.py`, `semantic_hypothesis.py`, `content_metadata`, `continuity_threat.py`) vào các contract Phase 2 rõ ràng, đặt trong hai package mới: `src/cortex/meaning/` và `src/cortex/tom/`.

Pipeline xử lý theo thứ tự bắt buộc:

```
WorkspaceFrame
  -> WorldSceneBuilder
  -> WorldInterpreter
  -> SocioculturalContext
  -> MeaningHypothesisEngine
  -> PragmaticIntentEngine
  -> TheoryOfMindCore
  -> OverreadBrake
  -> SurfaceMeaningPolicy
  -> Debug + Test Matrix
```

Hai ràng buộc kiến trúc xương sống:

1. **WorkspaceFrame-only contract**: Mọi module downstream Phase 2 CHỈ đọc `WorkspaceFrame` (định nghĩa tại `src/cortex/global_workspace.py`), KHÔNG đọc raw world (`raw_signals`/`evidence`/`memory`) trực tiếp.
2. **ToM-after-Meaning contract**: `TheoryOfMindCore` KHÔNG suy đoán trực tiếp từ câu thô của người dùng. ToM chỉ được suy luận SAU KHI `MeaningHypothesisEngine` đã sinh ra nhiều giả thuyết, mỗi giả thuyết mang theo evidence, confidence, ambiguity và overread risk.

## Glossary

- **ERIS**: Hệ thống nhận thức tổng thể (cognitive architecture) đang được xây dựng.
- **WorkspaceFrame**: Object contract trung tâm do Global Workspace broadcast, định nghĩa tại `src/cortex/global_workspace.py`. Chứa selected_evidence, selected_memory, selected_affect, risks, social_hypotheses, forbidden_assumptions, downstream_contract, v.v.
- **Raw_World**: Dữ liệu thô gồm raw_signals, evidence chưa lọc, và memory chưa chọn — KHÔNG được downstream Phase 2 đọc trực tiếp.
- **WorldSceneBuilder**: Module dựng "cảnh thế giới" (WorldScene) có cấu trúc từ WorkspaceFrame — ai, cái gì, ở đâu, tín hiệu nào đang nổi bật.
- **WorldScene**: Object có cấu trúc mô tả cảnh hiện tại: entities, salient signals, thread đang hoạt động, độ chắc chắn của từng phần tử cảnh.
- **WorldInterpreter**: Module diễn giải WorldScene thành các quan sát ngữ nghĩa cấp thấp (observations) kèm độ tin cậy, chưa phải ý định.
- **SocioculturalContext**: Module gắn ngữ cảnh xã hội - văn hóa (quan hệ, vai vế, register, chuẩn mực giao tiếp) vào diễn giải.
- **MeaningHypothesisEngine**: Module sinh **nhiều** giả thuyết ý nghĩa (MeaningHypothesis), mỗi giả thuyết mang evidence_ids, confidence, ambiguity, overread_risk.
- **MeaningHypothesis**: Một giả thuyết ý nghĩa đơn lẻ kèm metadata định lượng.
- **PragmaticIntentEngine**: Module suy ra ý định giao tiếp (pragmatic intent: yêu cầu, than phiền, đùa, thăm dò...) từ tập MeaningHypothesis đã có.
- **TheoryOfMindCore**: Module suy luận trạng thái tâm trí của tác nhân khác (niềm tin, mong muốn, cảm xúc, ý định) — chỉ dựa trên đầu ra của MeaningHypothesisEngine, không từ câu thô.
- **MentalStateRanker**: Thành phần xếp hạng các giả thuyết trạng thái tâm trí theo độ hợp lý.
- **CounterfactualCorrector**: Thành phần kiểm tra phản thực (counterfactual) để hạ độ tin cậy của suy luận ToM dễ sai.
- **ToMHistoryAdapter**: Thành phần đưa lịch sử tương tác vào ToM mà vẫn tuân thủ WorkspaceFrame-only contract.
- **OverreadBrake**: Module "phanh phán bậy" — hạ confidence hoặc chặn các kết luận có overread_risk cao hoặc bằng chứng không đủ.
- **Overread**: Hành vi suy diễn vượt quá bằng chứng (phán bậy, đọc thừa ý).
- **SurfaceMeaningPolicy**: Module quyết định cuối cùng nội dung ý nghĩa/ý định nào được phép surface (đưa ra ngoài) và nội dung nào phải giữ ở dạng giả thuyết.
- **AmbiguityModule**: Module (`ambiguity.py`) định lượng độ mơ hồ giữa các giả thuyết cạnh tranh.
- **Taxonomy**: Bảng phân loại (`taxonomy.py`) định nghĩa các loại meaning, intent, mental state dùng chung trong Phase 2.
- **DebugRender**: Thành phần render trạng thái nội bộ Phase 2 ra dạng debug đọc được.
- **Confidence**: Số thực trong [0.0, 1.0] thể hiện độ tin cậy.
- **Ambiguity**: Số thực trong [0.0, 1.0] thể hiện độ mơ hồ giữa các giả thuyết cạnh tranh.
- **Overread_Risk**: Số thực trong [0.0, 1.0] thể hiện rủi ro suy diễn vượt bằng chứng.

## Requirements

### Requirement 1: Đọc đầu vào chỉ qua WorkspaceFrame

**User Story:** Là kiến trúc sư ERIS, tôi muốn mọi module Phase 2 chỉ đọc WorkspaceFrame, để hệ thống giữ được tính mạch lạc ngữ cảnh và không bị phân tán nguồn sự thật.

#### Acceptance Criteria

1. THE Phase2_System SHALL read all task inputs exclusively from a single WorkspaceFrame instance provided by the Global Workspace, and SHALL NOT read Raw_World data (raw_signals, evidence, or memory) from any other source.
2. IF a Phase2 module attempts to read Raw_World data directly, THEN THE Phase2_System SHALL raise a contract violation error that identifies the offending module by name, SHALL allow the in-progress read to complete without mutating the read data, and SHALL record the violation in debug output.
3. WHEN a WorkspaceFrame is provided, THE WorldSceneBuilder SHALL derive its WorldScene output using only the fields enumerated in the WorkspaceFrame downstream_contract, and SHALL ignore any field not exposed by that contract.
4. IF no WorkspaceFrame is provided, THEN THE WorldSceneBuilder SHALL produce an empty WorldScene with Confidence equal to 0.0, SHALL record a human-readable reason for the empty result in debug output, and SHALL NOT read Raw_World data.
5. WHEN the Phase2_System produces an artifact, THE Phase2_System SHALL record in that artifact the WorkspaceFrame frame_id used as input.
6. IF a required WorkspaceFrame field is absent, THEN THE Phase2_System SHALL produce a result whose Confidence (a float in [0.0, 1.0]) is capped at 0.5, and SHALL record the name of each missing field in debug output.

### Requirement 2: Dựng cảnh thế giới (WorldSceneBuilder)

**User Story:** Là ERIS, tôi muốn dựng một cảnh thế giới có cấu trúc từ WorkspaceFrame, để các tầng sau hiểu được ai/cái gì/ở đâu trước khi diễn giải ý nghĩa.

#### Acceptance Criteria

1. WHEN a WorkspaceFrame containing at least one broadcast item is received, THE WorldSceneBuilder SHALL produce, within 500 milliseconds, exactly one WorldScene containing entities, salient signals, and active threads derived from that WorkspaceFrame.
2. WHEN producing a WorldScene, THE WorldSceneBuilder SHALL assign to each WorldScene element a Confidence value represented as a float in the inclusive range 0.0 to 1.0.
3. WHERE the WorkspaceFrame exposes a dominant_thread, THE WorldSceneBuilder SHALL mark exactly one corresponding WorldScene element as the dominant focus.
4. IF the WorkspaceFrame contains no broadcast items, THEN THE WorldSceneBuilder SHALL produce one empty WorldScene that records a reason indicating the absence of broadcast items, and this empty WorldScene SHALL count as one produced WorldScene.
5. THE WorldSceneBuilder SHALL preserve, without modification, every evidence_id from the WorkspaceFrame on each WorldScene element that depends on those evidence_ids.
6. IF a received WorkspaceFrame is malformed or cannot be parsed, THEN THE WorldSceneBuilder SHALL produce no WorldScene and SHALL return an error indication identifying the WorkspaceFrame as invalid.

### Requirement 3: Diễn giải cảnh (WorldInterpreter)

**User Story:** Là ERIS, tôi muốn diễn giải cảnh thành các quan sát ngữ nghĩa cấp thấp, để tách bước "thấy gì" khỏi bước "đoán ý gì".

#### Acceptance Criteria

1. WHEN a WorldScene containing at least one element is received, THE WorldInterpreter SHALL produce a set of zero or more observations, where each observation carries a Confidence value in the range 0.0 to 1.0 inclusive and at least one supporting evidence_id.
2. THE WorldInterpreter SHALL NOT produce intent inferences or mental-state inferences. (Exception to positive-statement rule: this is a scope-boundary error guard.)
3. IF a WorldScene element has a Confidence value below the configured low-confidence threshold (default 0.5, configurable in the range 0.0 to 1.0 inclusive), THEN THE WorldInterpreter SHALL mark each observation derived from that element as low-confidence.
4. THE WorldInterpreter SHALL preserve, on each produced observation, a reference to the originating WorldScene element from which it was derived.
5. IF a received WorldScene is empty, null, or fails structural validation, THEN THE WorldInterpreter SHALL produce no observations and return an error indication identifying the validation failure, while leaving any previously produced observations unchanged.
6. WHEN a WorldInterpreter is unable to attach at least one supporting evidence_id to a candidate observation, THE WorldInterpreter SHALL discard that candidate observation and exclude it from the produced set.

### Requirement 4: Gắn ngữ cảnh xã hội - văn hóa (SocioculturalContext)

**User Story:** Là ERIS, tôi muốn gắn ngữ cảnh xã hội và văn hóa vào diễn giải, để hiểu cùng một câu khác nhau tùy quan hệ và register.

#### Acceptance Criteria

1. WHEN observations are received AND relationship context, register context, and social-norm context are all available from the WorkspaceFrame, THE SocioculturalContext SHALL annotate each received observation with all three context types (relationship, register, and social-norm).
2. WHERE the WorkspaceFrame exposes social_hypotheses, THE SocioculturalContext SHALL incorporate those social_hypotheses as context marked as unconfirmed and SHALL NOT treat them as confirmed fact.
3. IF any of the three context types (relationship, register, or social-norm) is unavailable, THEN THE SocioculturalContext SHALL apply, for each missing context type, a predefined neutral default value that applies no interpretive bias before processing the observations.
4. WHEN a neutral default value has been applied for a missing context type, THE SocioculturalContext SHALL record, per affected context type, that the default was applied.
5. WHEN a sociocultural annotation has been applied to an observation, THE SocioculturalContext SHALL assign to that annotation a Confidence value expressed as a float within the inclusive range 0.0 to 1.0.
6. IF the received observation set is empty, THEN THE SocioculturalContext SHALL produce no annotations and SHALL complete without raising an error.

### Requirement 5: Sinh nhiều giả thuyết ý nghĩa (MeaningHypothesisEngine)

**User Story:** Là ERIS, tôi muốn sinh nhiều giả thuyết ý nghĩa cạnh tranh thay vì chốt một nghĩa, để tránh hiểu sai và để các tầng sau có vật liệu suy luận.

#### Acceptance Criteria

1. WHEN context-annotated observations are received, THE MeaningHypothesisEngine SHALL produce between one and a configured maximum number of MeaningHypothesis instances (default maximum 4).
2. WHEN a MeaningHypothesis is produced, THE MeaningHypothesisEngine SHALL attach to it a non-empty set of evidence_ids, a Confidence value expressed as a float in the range 0.0 to 1.0, an Ambiguity value expressed as a float in the range 0.0 to 1.0, and an Overread_Risk value expressed as a float in the range 0.0 to 1.0.
3. WHERE two or more MeaningHypothesis instances have Confidence values whose absolute difference is less than or equal to a configured margin (default 0.08), THE MeaningHypothesisEngine SHALL increase the Ambiguity value of those competing hypotheses without exceeding the maximum Ambiguity value of 1.0.
4. IF no MeaningHypothesis can be supported by available evidence, THEN THE MeaningHypothesisEngine SHALL produce exactly one explicit "insufficient evidence" hypothesis with a Confidence value below a configured low-confidence threshold (default 0.2).
5. WHEN MeaningHypothesis instances are produced, THE MeaningHypothesisEngine SHALL rank them by Confidence value in descending order.
6. WHEN two or more MeaningHypothesis instances have equal Confidence values, THE MeaningHypothesisEngine SHALL order them by ascending Ambiguity value as a deterministic tie-break.
7. THE MeaningHypothesisEngine SHALL wrap the existing semantic_hypothesis and meaning modules rather than reimplementing their scoring logic.

### Requirement 6: Suy ra ý định giao tiếp (PragmaticIntentEngine)

**User Story:** Là ERIS, tôi muốn suy ra ý định giao tiếp từ các giả thuyết ý nghĩa, để phân biệt yêu cầu, than phiền, đùa, hay thăm dò.

#### Acceptance Criteria

1. WHEN a non-empty ranked set of MeaningHypothesis instances is received, THE PragmaticIntentEngine SHALL produce between 1 and 8 pragmatic intent hypotheses, where each hypothesis is classified as exactly one category defined in the Taxonomy.
2. THE PragmaticIntentEngine SHALL derive each pragmatic intent only from MeaningHypothesis instances, and SHALL NOT read or reference Raw_World data.
3. WHEN a pragmatic intent is produced, THE PragmaticIntentEngine SHALL attach a Confidence value in the range [0.0, 1.0] and at least one supporting MeaningHypothesis reference, and SHALL retain the supporting MeaningHypothesis references even when the Confidence value is 0.0.
4. IF any supporting MeaningHypothesis has an Ambiguity value greater than 0.7, THEN THE PragmaticIntentEngine SHALL assign the derived pragmatic intent a Confidence value strictly lower than the value it would assign for the same supporting MeaningHypothesis instances when all of their Ambiguity values are 0.7 or lower.
5. IF the received set of MeaningHypothesis instances is empty, THEN THE PragmaticIntentEngine SHALL produce zero pragmatic intent hypotheses and SHALL return an indication that no pragmatic intent could be derived.

### Requirement 7: Ràng buộc ToM-after-Meaning (TheoryOfMindCore)

**User Story:** Là kiến trúc sư ERIS, tôi muốn ToM chỉ chạy sau MeaningHypothesisEngine, để ERIS không đoán tâm trí trực tiếp từ câu thô và không phán bậy.

#### Acceptance Criteria

1. THE TheoryOfMindCore SHALL derive mental-state inferences only from the output of the MeaningHypothesisEngine and the PragmaticIntentEngine, and SHALL NOT read Raw_World data or raw user sentences. (Exception to positive-statement rule: this is the ToM-after-Meaning contract boundary guard.)
2. IF the TheoryOfMindCore is invoked before either the MeaningHypothesisEngine or the PragmaticIntentEngine has produced output for the current WorkspaceFrame frame_id, THEN THE TheoryOfMindCore SHALL refuse to run, produce no mental-state inference, and record a contract violation identifying the missing upstream stage.
3. WHEN mental-state inferences are produced, THE MentalStateRanker SHALL rank them in descending order of plausibility, where an inference with higher Confidence ranks above one with lower Confidence and, for equal Confidence, an inference with lower Overread_Risk ranks higher, with Confidence and Overread_Risk each a real number in the range 0.0 to 1.0.
4. IF a counterfactual explanation with a Confidence value at or above a configured threshold exists for a mental-state inference, THEN THE CounterfactualCorrector SHALL reduce that inference's Confidence to a value no lower than 0.0 and record the counterfactual explanation that triggered the reduction.
5. WHEN historical interaction data is needed, THE ToMHistoryAdapter SHALL supply it from the WorkspaceFrame only.
6. WHEN a mental-state inference is produced, THE TheoryOfMindCore SHALL attach to it supporting MeaningHypothesis references and a Confidence value in the range 0.0 to 1.0.
7. IF supporting MeaningHypothesis references cannot be attached to a mental-state inference, THEN THE TheoryOfMindCore SHALL still produce the inference and flag it as unsupported.
8. IF historical interaction data is needed but absent from the WorkspaceFrame, THEN THE ToMHistoryAdapter SHALL supply no history and record that history was unavailable, and THE TheoryOfMindCore SHALL continue producing inferences without it.

### Requirement 8: Phanh phán bậy (OverreadBrake)

**User Story:** Là ERIS, tôi muốn một cơ chế phanh chuyên trách, để chặn các kết luận suy diễn vượt bằng chứng trước khi chúng được surface.

#### Acceptance Criteria

1. WHEN a MeaningHypothesis, pragmatic intent, or mental-state inference carries an Overread_Risk (range [0.0,1.0]) greater than or equal to the configured overread-reduction threshold (default 0.70) and less than the configured suppression threshold, THE OverreadBrake SHALL reduce its Confidence (range [0.0,1.0]) by the configured reduction factor (default: reduce Confidence to no more than 0.50).
2. WHEN a MeaningHypothesis, pragmatic intent, or mental-state inference carries an Overread_Risk greater than or equal to the configured suppression threshold (default 0.90, range [0.0,1.0]), THE OverreadBrake SHALL mark the conclusion as overread-suppressed.
3. IF a conclusion is supported by fewer evidence_ids than the configured minimum evidence count (default 2), THEN THE OverreadBrake SHALL mark the conclusion as overread-suppressed.
4. WHEN the OverreadBrake reduces the Confidence of or suppresses a conclusion, THE OverreadBrake SHALL record, for both confidence-reduced and suppressed conclusions, the reason, the triggering metric name, and the triggering metric value.
5. THE OverreadBrake SHALL preserve suppressed conclusions in debug output, retaining their original Confidence and metric values, rather than discarding them.
6. WHERE the WorkspaceFrame exposes forbidden_assumptions, THE OverreadBrake SHALL mark as overread-suppressed any conclusion that asserts a listed forbidden assumption as fact, and SHALL record the matched forbidden assumption as the suppression reason.

### Requirement 9: Định lượng mơ hồ (AmbiguityModule)

**User Story:** Là ERIS, tôi muốn định lượng độ mơ hồ giữa các giả thuyết, để OverreadBrake và các tầng sau biết khi nào cần thận trọng.

#### Acceptance Criteria

1. WHEN a set of two or more competing hypotheses is provided, THE AmbiguityModule SHALL compute an Ambiguity value bounded between 0.0 and 1.0 inclusive for the set.
2. WHERE exactly one hypothesis exists with no competitor, THE AmbiguityModule SHALL assign an Ambiguity value in the range 0.0 to 0.1 inclusive.
3. WHEN the absolute difference in Confidence between the top two hypotheses is less than or equal to 0.05, THE AmbiguityModule SHALL assign an Ambiguity value in the range 0.9 to 1.0 inclusive.
4. IF the provided set contains zero hypotheses, THEN THE AmbiguityModule SHALL assign an Ambiguity value of 0.0 and return an indication that no hypotheses were available for comparison.
5. IF any hypothesis in the provided set has a Confidence value outside the range 0.0 to 1.0 inclusive, THEN THE AmbiguityModule SHALL reject the set, return an indication that the input is invalid, and retain the previously computed Ambiguity value without modification.

### Requirement 10: Chính sách surface ý nghĩa (SurfaceMeaningPolicy)

**User Story:** Là ERIS, tôi muốn một chính sách quyết định nội dung nào được đưa ra ngoài, để chỉ surface những ý nghĩa đủ chắc và giữ phần mơ hồ ở dạng giả thuyết.

#### Acceptance Criteria

1. WHEN conclusions that have been evaluated by the OverreadBrake are received, THE SurfaceMeaningPolicy SHALL assign each conclusion to exactly one of two sets — a surfaced set or a withheld internal-hypothesis set — such that every received conclusion appears in exactly one set.
2. IF a conclusion has a Confidence value below the configured surface Confidence threshold (a configurable value in the range 0.0 to 1.0), THEN THE SurfaceMeaningPolicy SHALL assign the conclusion to the withheld internal-hypothesis set and record the withholding reason.
3. WHEN a conclusion has a Confidence value at or above the configured surface Confidence threshold AND an Ambiguity value at or above a configured ambiguity threshold (a configurable value in the range 0.0 to 1.0) AND an Ambiguity value below the maximum value of 1.0, THE SurfaceMeaningPolicy SHALL assign the conclusion to the surfaced set marked as tentative rather than as asserted fact.
4. IF a conclusion has the maximum Ambiguity value of 1.0, THEN THE SurfaceMeaningPolicy SHALL assign the conclusion to the withheld internal-hypothesis set regardless of its Confidence value and record the withholding reason.
5. THE SurfaceMeaningPolicy SHALL produce a final Phase 2 result object that records the surfaced set and the withheld internal-hypothesis set, and that records for each conclusion its surface-or-withheld status.
6. WHEN a conclusion has a Confidence value at or above the configured surface Confidence threshold AND an Ambiguity value below the configured ambiguity threshold, THE SurfaceMeaningPolicy SHALL assign the conclusion to the surfaced set marked as an asserted conclusion.
7. IF a conclusion was marked as suppressed by the OverreadBrake, THEN THE SurfaceMeaningPolicy SHALL assign the conclusion to the withheld internal-hypothesis set regardless of its Confidence and Ambiguity values and record the withholding reason.
8. IF a conclusion has no supporting evidence_id, THEN THE SurfaceMeaningPolicy SHALL assign the conclusion to the withheld internal-hypothesis set so that every conclusion in the surfaced set carries at least one supporting evidence_id.

### Requirement 11: Phân loại dùng chung (Taxonomy)

**User Story:** Là người phát triển ERIS, tôi muốn một bảng phân loại dùng chung cho meaning, intent và mental state, để các module Phase 2 dùng thuật ngữ nhất quán.

#### Acceptance Criteria

1. THE Taxonomy SHALL define three distinct category sets (meaning categories, pragmatic intent categories, and mental-state categories), where each defined category has a unique identifier within its set and at least one category is defined in each of the three sets.
2. WHEN a Phase 2 module assigns a category to a meaning, intent, or mental-state field, THE Phase2_System SHALL verify that the assigned category identifier exists in the corresponding Taxonomy set before accepting the assignment.
3. IF a module references a category identifier not defined in the corresponding Taxonomy set, whether the reference occurs in a category assignment, a validation rule, or any other usage, THEN THE Phase2_System SHALL halt the operation, reject the reference without modifying existing state, and produce a configuration error indicating the undefined category identifier and its referenced set.
4. WHEN the Taxonomy is loaded at Phase2_System startup, THE Phase2_System SHALL validate that all category identifiers are unique within each set, and IF a duplicate category identifier is found within any set, THEN THE Phase2_System SHALL produce a configuration error indicating the duplicated category identifier and its set.

### Requirement 12: Debug và quan sát nội bộ (DebugRender / ToMDebug)

**User Story:** Là người phát triển ERIS, tôi muốn xem được toàn bộ chuỗi suy luận Phase 2 ở dạng debug, để kiểm tra vì sao ERIS hiểu/không hiểu một ý.

#### Acceptance Criteria

1. WHEN a Phase 2 pipeline run completes, THE DebugRender SHALL produce a human-readable record containing, for each pipeline stage, the stage output together with its Confidence, Ambiguity, and Overread_Risk values, each expressed as a float in the range [0.0, 1.0].
2. WHEN a Phase 2 pipeline run completes, THE DebugRender SHALL include in the record every suppressed and withheld conclusion together with its suppression reason.
3. WHEN mental-state inference for a Phase 2 pipeline run completes, THE ToMDebug SHALL produce a human-readable record of each mental-state inference and the MeaningHypothesis references that supported it.
4. WHEN a Phase 2 pipeline run completes, THE DebugRender SHALL record the WorkspaceFrame frame_id associated with that pipeline run.
5. IF a stage output is missing one or more of the Confidence, Ambiguity, or Overread_Risk values, THEN THE DebugRender SHALL record an indication that the missing value is unavailable for that stage and SHALL continue producing the record for the remaining stages.
6. IF no WorkspaceFrame frame_id is associated with the pipeline run, THEN THE DebugRender SHALL record an indication that the frame_id is unavailable.

### Requirement 13: Ma trận kiểm thử Phase 2 (Test Matrix)

**User Story:** Là người phát triển ERIS, tôi muốn một bộ kiểm thử bao phủ từng tầng và toàn pipeline, để xác nhận ERIS hiểu đúng và không phán bậy.

#### Acceptance Criteria

1. WHEN unit tests for WorldSceneBuilder, SocioculturalContext, MeaningHypothesisEngine, PragmaticIntentEngine, TheoryOfMindCore, and OverreadBrake are executed with a representative input, THE Phase2_Test_Suite SHALL pass each test when the module under test produces its specified output.
2. WHEN the integration test exercising the full pipeline WorkspaceFrame → SurfaceMeaningPolicy is executed, THE Phase2_Test_Suite SHALL pass when a final Phase 2 result object is produced.
3. IF TheoryOfMindCore is invoked before MeaningHypothesisEngine output exists for the current frame, THEN THE Phase2_Test_Suite SHALL assert that TheoryOfMindCore produces NO output and emits an ordering-error signal.
4. WHEN TheoryOfMindCore is invoked after MeaningHypothesisEngine output exists for the current frame, THE Phase2_Test_Suite SHALL assert that TheoryOfMindCore produces mental-state inference output and emits no ordering-error signal.
5. WHEN the no-direct-read test is executed, THE Phase2_Test_Suite SHALL assert that no Phase 2 module reads Raw_World data directly and SHALL fail if any direct Raw_World read is detected.
6. WHEN a conclusion's Overread_Risk (float in [0.0,1.0]) exceeds the configured suppression threshold (default 0.7), THE Phase2_Test_Suite SHALL assert that OverreadBrake marks the conclusion as overread-suppressed.
7. WHEN a conclusion's Overread_Risk is at or below the configured suppression threshold (default 0.7), THE Phase2_Test_Suite SHALL assert that OverreadBrake does NOT suppress the conclusion.
8. FOR ALL pipeline runs over a generated set of at least 100 distinct WorkspaceFrame inputs, THE Phase2_Test_Suite SHALL assert that every surfaced conclusion carries at least one supporting evidence_id and SHALL fail if any surfaced conclusion has zero supporting evidence_ids.
