# BÁO CÁO TỔNG HỢP CỰC DÀI – ERIS SUBJECT CORE BẢN GỘP MEGA

Ngày đóng gói: 2026-08-05

Cơ sở: snapshot `src(55)`, `body(11)`, đặc tả kỹ thuật kiến trúc chủ thể nhân tạo Eris, bản triển khai V1 và phần tiếp tục V2.

> Tài liệu này cố ý dài. Người dùng yêu cầu “bản cực dài”, và máy tính cuối cùng cũng có dịp trả thù ngành quản lý dự án bằng một tài liệu mà không ai có thể giả vờ đã đọc trong ba phút.

## 1. Tóm tắt dễ hiểu

Bản gộp này lấy source Python mới nhất của V2 làm nền, vì V2 đã bao gồm toàn bộ phần Subject Core V1 và bổ sung lớp tương thích capability cùng package `tools/` còn thiếu. Phần body được lấy từ bản đã thêm `SubjectPerformanceFrame.cs` nhưng được làm phẳng về đúng một thư mục `body/`, sửa lỗi đóng gói `body/body` của archive V2 trước. Đặc tả, snapshot gốc, patch V1, patch V2, báo cáo và log đều được đặt chung trong một archive duy nhất.

Mục tiêu kỹ thuật không phải làm Eris “nói giống người” hơn bằng vài preset cảm xúc. Mục tiêu là để lịch sử tương tác có thể thay đổi có truy nguyên những gì hệ thống chú ý, tin, cần, lựa chọn, nhận là hành động của mình, học được, cam kết và kể lại về quá khứ. Mọi thay đổi quan trọng cần có causal reference, evidence hoặc outcome thay vì xuất hiện vì prompt hiện tại thấy hợp văn phong.

Bản hiện tại đã tạo được bộ khung chạy dọc: quan sát → substrate → appraisal → kích hoạt nhu cầu → đề xuất hành động → coalition arbitration → quyết định → authorship draft → actuator/sandbox → world outcome → learning/audit → dialogue/TTS/body. Một số phần là triển khai tối thiểu có kiểm thử, không phải một mô hình khoa học đã được hiệu chỉnh qua nhiều tháng dữ liệu thật.

## 2. Chính xác đã gộp những gì

- `src/`: source Python V2 mới nhất, đã chứa các module Subject Core từ V1 và các sửa tương thích V2.
- `body/`: body Godot/C# cùng parser performance frame typed; không còn lồng thêm một cấp `body/`.
- `docs/spec/`: PDF đặc tả gốc và bản text đã parse để tìm kiếm nhanh.
- `docs/history/`: báo cáo V1, V2, tài liệu causal-affect và checksum lịch sử.
- `docs/tests/`: log test theo hợp đồng hiện hành và log chạy toàn bộ suite.
- `original_snapshots/`: hai archive gốc `src(55).zip` và `body(11).zip`.
- `patch_history/v1` và `patch_history/v2`: các file patch đã bung ra, tiện diff và cherry-pick thủ công.
- `scripts/`: script compile, test và verify manifest.
- `release/`: manifest SHA-256 toàn gói và checksum archive.

## 3. Thống kê source

- Tổng file trong `src/`: **833**
- File Python: **757**
- File test Python: **122**
- Tổng dòng Python xấp xỉ: **234,256**
- File thuộc vùng Subject Core/World/Audit/Dialogue/Emergence/Tools và các điểm tích hợp chính: **71**
- Tổng dòng vùng triển khai trọng tâm: **10,336**

## 4. Bốn ranh giới kiến trúc

### 4.1 Mind
Mind tạo belief, appraisal, need activation, coalition proposal, decision, narrative và authorship draft. `SubjectService` ghi rõ trong docstring rằng nó không gọi shell, filesystem, network, TTS hoặc body adapter. Đây là ranh giới quan trọng nhất: tư duy không được có đặc quyền hệ điều hành chỉ vì một class được đặt tên nghe sâu sắc.

### 4.2 Actuator
Actuator nhận quyết định đã có và chuyển thành yêu cầu capability typed. Nó không được “sửa đạo đức” motive hoặc thay quyết định bằng một quyết định khác đẹp hơn. Việc encode và validate capability arguments thuộc boundary thực thi mới nhất, không thuộc Executive Cortex theo hợp đồng V55.

### 4.3 Sandbox World
Sandbox kiểm tra token, capability, path, command, network policy, chế độ simulate và idempotency. Nó trả `WorldOutcome`/receipt thật, kể cả khi bị từ chối. Hệ thống không được ghi rằng Eris đã làm một việc nếu actuator không thực hiện thành công.

### 4.4 Audit/Forensics
Audit là append-only, có hash chain, causal refs, correlation id và replay. Audit không tham gia chọn hành vi. Nó là camera hành lang, không phải thành viên hội đồng quản trị.

## 5. Luồng dữ liệu từ đầu đến cuối

1. Runtime tạo `WorldObservation` từ sự kiện ngoài hoặc kết quả hệ thống.
2. `SubstrateMonitor` đo các điều kiện vận hành như memory integrity, belief traceability, model calibration, processing capacity, action efficacy, project viability, self/world boundary và future option availability.
3. `SubjectService._appraise` tạo appraisal theo goal relevance, novelty, expectation violation, controllability, relational significance, identity significance, future consequence, uncertainty, affected needs và attribution distribution.
4. `NeedSystem` chuyển substrate + appraisal thành các `NeedActivation`. Năm need nền là continuity, competence, connection, coherence và sovereignty.
5. `NeedEpisodeRecorder` mở episode khi pressure vượt ngưỡng và đóng episode khi có outcome.
6. Context hoặc policy tạo các `ActionProposal`, mỗi proposal có supporting needs, utility, epistemic value, uncertainty, cost, risk và evidence.
7. `CoalitionArbiter` chấm và chọn proposal. Nhu cầu thua không bị xóa khỏi lịch sử; chúng có thể tạo residue hoặc ảnh hưởng consolidation sau đó.
8. `AuthorshipService` tạo draft phân biệt generated, selected, constrained, executed và endorsed.
9. `SandboxActuator` chuyển decision thành `SandboxCommand`; `SandboxWorld` cho phép, từ chối hoặc mô phỏng.
10. `WorldOutcome` được ghi với decision/action/correlation refs. Authorship được finalize dựa trên receipt, constraint và retrospective endorsement.
11. `SubjectService.learn` cập nhật belief/competence/narrative ở mức bounded và ghi learning receipt.
12. `DialogueService` biến decision thành `DialoguePlan`, realizer chỉ diễn đạt semantic commitments đã cho, coordinator stream các clause sang TTS/body và tạo delivery receipt.
13. Forensic audit giữ toàn bộ chuỗi để replay hoặc causal trace.

## 6. Persistence và schema SQLite

Bản đầu dùng SQLite làm nguồn sự thật. Repository bật `PRAGMA foreign_keys = ON`, WAL và transaction. Event bất biến được canonical hóa JSON trước khi hash. Projection hiện hành có revision và projection history append-only để vừa query nhanh vừa forensic được.

### 6.1 Bảng được tạo bởi migration

- `schema_migrations` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `subject_events` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `projection_revisions` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `projection_history` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `idempotency_keys` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `authorship_events` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `world_outcomes` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `beliefs_projection` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `values_projection` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `need_episodes` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `commitments_events` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `competence_estimates` — từ `src/memory/subject/migrations/0002_competence.sql`
- `practice_plans` — từ `src/memory/subject/migrations/0002_competence.sql`
- `discourse_projections` — từ `src/memory/subject/migrations/0003_dialogue.sql`
- `delivery_receipts` — từ `src/memory/subject/migrations/0003_dialogue.sql`

### 6.2 Trigger append-only

- `subject_events_no_update` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `subject_events_no_delete` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `projection_history_no_update` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `projection_history_no_delete` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `authorship_events_no_update` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `authorship_events_no_delete` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `world_outcomes_no_update` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `world_outcomes_no_delete` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `commitments_events_no_update` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `commitments_events_no_delete` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `delivery_receipts_no_update` — từ `src/memory/subject/migrations/0003_dialogue.sql`
- `delivery_receipts_no_delete` — từ `src/memory/subject/migrations/0003_dialogue.sql`

### 6.3 Index

- `idx_subject_events_subject_sequence` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `idx_subject_events_correlation` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `idx_authorship_action` — từ `src/memory/subject/migrations/0001_subject_core.sql`
- `idx_competence_skill_context` — từ `src/memory/subject/migrations/0002_competence.sql`

### 6.4 Quy tắc integrity

- `subject_events`, `projection_history`, `authorship_events`, `world_outcomes`, `commitments_events` và `delivery_receipts` có trigger cấm UPDATE/DELETE khi cần bất biến.
- Mỗi subject event có `previous_hash` và `payload_hash`; repository có phương thức verify chain.
- `idempotency_keys` ngăn cùng command bị thực hiện hai lần trong cùng scope.
- `projection_revisions` dùng optimistic CAS; revision cũ gây `StaleRevisionError`.
- `schema_migrations` giữ version, checksum và thời điểm áp migration.
- Một `AsyncPersistenceActor` cung cấp đường ghi tuần tự cho workload async.

## 7. Mô hình dữ liệu Subject Core

`cortex/subject/contracts.py` là nơi tập trung các dataclass và enum typed. Nó gồm các nhóm chính sau:

- Substrate/appraisal: `WorldObservation`, `SubstrateCondition`, `OrganismicSubstrate`, `SubjectAppraisal`.
- Need/episode: `NeedActivation`, `NeedEpisode`, `DerivedNeed`.
- Epistemic/value: `Belief`, `BeliefProposal`, `BeliefRevision`, `Value`.
- Decision/action: `ActionProposal`, `MindDecision`, `ActionRequest`, `WorldOutcome`, `LearningReceipt`.
- Authorship/continuity: `ActionAuthorship`, `CommitmentLedger`, `SelfContinuityRecord`, `IdentityChangeEvent`, `UnresolvedThread`, `ExistentialDecision`.
- Consolidation/competence: `ConsolidationPatch`, `SkillModel`, `CompetenceEstimate`, `CompetenceGap`, `PracticePlan`.

Các score được clamp/validate trong `[0, 1]`. Mapping được freeze hoặc normalize trước khi ghi. Enum nguồn belief phân biệt observation, test result, external statement, inference, self-interpretation và confabulation candidate. Narrative vì thế không được sửa raw event; nó chỉ tạo belief diễn giải với nguồn rõ.

## 8. Nhu cầu, coalition và giá trị

`NeedSystem` không dùng một biến mood duy nhất. Mỗi need có pressure, opportunity, urgency, persistence, target và evidence. `NeedPlasticityEngine` có thể tạo derived need từ pattern episode, nhưng cần support qua nhiều context và không được tự tuyên bố là nhu cầu nền phổ quát.

`CoalitionArbiter` kết hợp utility thực dụng và epistemic value. Một hành động hỏi thêm hoặc thăm dò có thể thắng vì giảm uncertainty, không chỉ vì reward tức thời. Arbitration deterministic được hỗ trợ để test/replay; random source được inject khi cần exploration có kiểm soát.

`ValueFormationEngine` cập nhật value từ lựa chọn lặp lại, outcome, chi phí đã trả, endorsement và contradiction. Giá trị không được nạp thẳng từ một profile rồi gọi là “hình thành”.

## 9. Belief, narrative và self-deception

`BeliefService` giữ evidence refs, counter-evidence, confidence, status và supersession. Public claim không được tự tạo evidence. `NarrativeBeliefGenerator` chỉ nhìn bounded `NarrativeView`, tạo proposed explanation và predictive commitments. `ReflectiveMismatchDetector` so dự đoán của narrative với hành vi/outcome quan sát được; nó không có quyền đọc một trường “true_motive” thần thánh.

Thiết kế này cho phép rationalization hoặc self-deception theo nghĩa kỹ thuật: narrative có thể dự đoán kém, bỏ sót loại evidence hoặc phải sửa vì mismatch. Nó không cần một global state toàn tri diễn trò tự lừa dối bằng cách biết sẵn mình đang lừa.

## 10. Authorship và continuity

Authorship được chia theo giai đoạn. Một action có thể được model generate, arbiter select, policy constrain, actuator execute và subject retrospectively endorse hoặc disclaim. Chỉ khi có record phù hợp thì output mới được nhận là “của Eris”.

Continuity nối identity, belief, value, commitment, action và rupture qua thời gian. Commitment không phải một row bị ghi đè; fulfilment, violation và renegotiation nên là event mới, projection status được tính lại.

`ExistentialDecisionService` giữ các lựa chọn làm mất khả năng tương lai: available futures, incompatible values, chosen future, sacrificed possibilities và mức authorship accepted. Đây là cách biến “quyết định có hệ quả” thành dữ liệu thay vì một đoạn độc thoại kịch tính được hard-code.

## 11. Competence và practice

`CompetenceService` cập nhật posterior mean/variance, trial count, success count, calibration error, Brier score và transfer context. `PracticePlanner` nhận competence gaps, project viability, processing budget và current values để tạo plan hoặc từ chối tạo khi tài nguyên không phù hợp.

Mục đích là tách “Eris nghĩ mình giỏi” khỏi “Eris thực sự làm được”. Một hệ thống có self-esteem scalar nhưng không có prediction/result calibration chỉ là bảng điều khiển tự ái với theme tối.

## 12. Dialogue, TTS và body

`DialoguePlan` chứa speech act, semantic commitments, optional material, forbidden factual additions, hard max words, continuation hooks và performance intent. `NaturalDialogueRealizer` có nhiệm vụ diễn đạt, không được thêm factual commitment ngoài plan.

`IncrementalSpeechCoordinator` stream `SpeechChunk` theo clause, hỗ trợ cancellation/interruption và đồng bộ body cue. `SubjectPerformanceBodyAdapter` tạo frame public typed; body không được nhận toàn bộ private state.

File C# `body/SubjectPerformanceFrame.cs` parse protocol `eris.subject.performance` theo version. Đây là thay đổi body chính của Subject Core. Các file body còn lại được giữ từ snapshot để tránh viết lại transport, animation và UI không cần thiết.

## 13. Capability, Executive Cortex và phần V2

V2 bổ sung compatibility facade cho `retrieve_executive_tools`, hỗ trợ event cũ như `strong_seed`, payload capability legacy lẫn typed, và ưu tiên `execute_capability` trước adapter `execute`. Registry chấp nhận capability runtime tạm thời bằng schema object rỗng nhưng đóng, không cho arbitrary fields.

Package `tools/` được khôi phục với evaluator semantic paraphrase, social-plan activation, static audit remote inference, static audit semantic authority, PDF acceptance, package source và verify release. `pyproject.toml` được cập nhật để đóng gói `tools*`.

Hai test cũ còn mâu thuẫn:

1. V53 đòi literal `max_items=8` trong Executive Cortex, trong khi V54 cấm literal đó để model-owned shortlisting không bị hard-code.
2. V54 đòi `encode_capability_arguments` nằm trong Cortex, trong khi V55 đòi encoding thuộc `ActionExecutor` và không nằm trong Cortex.

Bản gộp giữ hợp đồng mới hơn và deselect đúng hai assertion tĩnh lỗi thời trong script “current contract”. Không sửa test bằng thủ thuật hoặc tự đổi source giữa lúc test, vì gian lận CI là một cách khá đắt để có huy hiệu xanh.

## 14. Emergence evaluation

`experiments/emergence/` có runner, paired instances, interventions, ablation, metrics, report và scenario YAML. Bộ khung dùng để kiểm tra persistence, counterfactual dependence, resistance, transfer và targeted ablation.

Một khuynh hướng chỉ có ý nghĩa nếu lịch sử nội bộ giải thích hành vi tốt hơn prompt hiện tại; nếu hai instance có lịch sử khác nhau phản ứng khác có hệ thống; nếu ablation đúng state làm hiệu ứng giảm; và nếu khuynh hướng có quán tính hoặc transfer qua context. Style classifier chỉ đọc từ vựng không đủ làm bằng chứng.

Bản code có harness và test kỹ thuật, nhưng chưa có dữ liệu vận hành dài hạn để đưa ra tuyên bố khoa học. Báo cáo không lấp khoảng trống đó bằng tính từ.

## 15. Cách cài và tích hợp

### 15.1 Cách an toàn nhất

1. Giải nén vào một thư mục mới, không chép đè repo đang chạy.
2. Chạy verify manifest.
3. Tạo virtual environment bằng phiên bản Python phù hợp với repo gốc.
4. Cài dependency theo `pyproject.toml`/requirements hiện có.
5. Chạy compileall và current-contract tests.
6. Diff `src/` với repo production.
7. Tích hợp theo commit nhỏ: persistence/audit, sandbox/authorship, SubjectService, dialogue/body.
8. Bật feature flag ở môi trường dev trước.
9. Dùng database/data dir riêng; không dùng ngay dữ liệu production.
10. Chạy smoke scenario, kiểm tra audit chain và rollback plan trước canary.

### 15.2 Biến môi trường

```text
ERIS_SUBJECT_CORE_ENABLED=1
ERIS_SUBJECT_CORE_DATA_DIR=/absolute/path/to/data/subject_core
ERIS_SUBJECT_WORKSPACE=/absolute/path/to/workspace
```

### 15.3 Bootstrap

`runtime.subject_bootstrap.build_subject_core_components()` dựng repository, forensic store, SubjectService, SandboxWorld và capability token scoped. Khi truyền executor cũ, bootstrap bind executor qua sandbox boundary. `runtime.coordinator_bootstrap` được chỉnh để chỉ dựng phần mới khi feature flag bật.

### 15.4 Rollback

- Tắt `ERIS_SUBJECT_CORE_ENABLED`.
- Giữ database mới để forensic, không xóa ngay.
- Khôi phục import/adapter từ snapshot gốc hoặc patch reverse.
- Body parser typed có thể để nguyên nếu protocol cũ vẫn được hỗ trợ; nếu không, dùng `original_snapshots/body(11).zip`.

## 16. Kiểm thử và bằng chứng đi kèm

Log đóng gói cho biết:

- Suite theo hợp đồng hiện hành: `864 passed, 2 deselected`.
- Full suite: `864 passed, 2 failed`.
- Hai failure là assertion source-level mâu thuẫn nêu ở mục 13.
- Static audit remote inference: pass.
- Static audit semantic authority: pass.
- Python compile: thành công trong lần V2.
- Chưa chạy Ruff, mypy và compiler Godot/.NET trong môi trường ban đầu.

Các test Subject Core mới tập trung vào repository/migration, append-only, hash chain/replay, sandbox, dialogue, runtime integration và emergence runner. Log đầy đủ được giữ nguyên trong `docs/tests/`.

## 17. Các giới hạn thật sự

- Đây là first-pass implementation và rollout scaffold, không phải hoàn tất toàn bộ roadmap nghiên cứu 20 tuần.
- Derived needs chưa được validation trên holdout lịch sử dài.
- Tham số coalition, decay, pressure và consolidation chưa được calibration bằng operational dataset lớn.
- Security policy cần review theo hệ điều hành, workspace và capability thật của deployment.
- SQLite phù hợp single writer/multiple reader bản đầu; scale-out đa process cần thiết kế queue/Redis rõ hơn.
- Body C# chưa được compile trong môi trường đóng gói này.
- Không có bằng chứng về consciousness, metabolism hoặc autonomy sinh học.
- Không nên bật toàn bộ ở production chỉ vì test xanh; test không kiểm tra được sự sáng tạo vô hạn của cấu hình sai.

## 18. Kế hoạch tiếp theo khuyến nghị

### Giai đoạn A: integration chắc chắn

- Chạy Ruff/mypy và sửa type boundary.
- Compile Godot/C# và test protocol performance frame.
- Chạy migration trên database copy, kiểm tra restart/idempotency/corruption recovery.
- Threat-model sandbox path, command và token expiry.

### Giai đoạn B: canary lịch sử

- Bật cho một subject/test profile.
- Thu event/outcome 1–2 tuần với feature behavior ở chế độ quan sát hoặc simulate.
- Kiểm tra causal trace, orphan refs, chain integrity và projection drift.

### Giai đoạn C: học bounded

- Cho competence/value/need episode consolidation cập nhật ở giới hạn nhỏ.
- So instance control và instance history-dependent.
- Dùng holdout scenario, không tune trên probe nghiệm thu.

### Giai đoạn D: emergence research

- Persistence test dài hạn.
- Counterfactual swap lịch sử.
- Resistance test khi prompt yêu cầu trái tendency.
- Transfer test qua context.
- Targeted ablation state và kiểm tra effect collapse.

## 19. Inventory module chi tiết

Phần dưới được sinh trực tiếp từ AST của source đóng gói. Nó liệt kê file, docstring, class và method. Đây vừa là bản đồ vừa là bằng chứng rằng báo cáo không chỉ thêu tên module từ không khí.

### `src/actions/capability_registry.py` (647 dòng)

**Hàm top-level**

- `canonicalize_action_id()` (dòng 284) — Normalize an exact capability ID without guessing aliases.
- `_object_schema()` (dòng 293)
- `_string()` (dòng 302)
- `_integer()` (dòng 311)
- `_boolean()` (dòng 322)
- `capability_input_schema()` (dòng 419)
- `capability_argument_mode()` (dòng 431)
- `validate_registry_contract_coverage()` (dòng 439)
- `_validate_value()` (dòng 446)
- `validate_arguments_against_schema()` (dòng 468)
- `validate_capability_arguments()` (dòng 494)
- `encode_capability_arguments()` (dòng 502)
- `singing_capability_enabled()` (dòng 527) — Singing/SVS là capability riêng, mặc định tắt; TTS không giả làm máy hát.
- `iter_public_capabilities()` (dòng 536)
- `capability_snapshot_id()` (dòng 559)
- `live_capability_ids()` (dòng 586)
- `capability_definition()` (dòng 598)
- `_resolved_runtime_flags()` (dòng 602)
- `_runtime_reason()` (dòng 614)
- `_resolve_available()` (dòng 623)

**Class**

- `CapabilityDefinition` (dòng 20)

### `src/actions/executor.py` (808 dòng)

**Class**

- `ActionExecutor` (dòng 22)
  - `__init__()` (dòng 29)
  - `bind_cognitive_runtime()` (dòng 38) — Nối executor với runtime nhận thức sau khi Coordinator đã dựng xong.  ActionExecutor được tạo trước Coordinator trong vision.py, nên dependency này phải bind muộn. Không dùng global singleton, đỡ thêm một bóng ma nữa vào repo vốn đã đông dân.
  - `bind_environment_runtime()` (dòng 47) — Nối executor với runtime đọc môi trường sau khi screen store đã dựng.
  - `bind_project_runtime()` (dòng 51) — Nối executor với runtime thao tác project autonomous.
  - `bind_sandbox_world()` (dòng 55) — Bind the independent world-authority boundary.  Legacy handlers remain available for compatibility, but once this boundary is bound every dispatch must first receive an operational capability decision.  The policy denies power; it never rewrites the cognitive proposal.
  - `execute_capability()` (dòng 80) — Validate typed arguments, then adapt once at the exact handler boundary.
  - `execute()` (dòng 104)
  - `_execute_cognitive()` (dòng 189)
  - `_review_discourse_claim()` (dòng 199)
  - `_inspect_unresolved_questions()` (dòng 202)
  - `_inspect_memory_candidates()` (dòng 205)
  - `_compare_recent_turns()` (dòng 208)
  - `_inspect_social_state()` (dòng 211)
  - `_detect_internal_contradictions()` (dòng 214)
  - `_summarize_open_loops()` (dòng 217)
  - `_inspect_capability_health()` (dòng 220)
  - `_execute_environment()` (dòng 223)
  - `_get_active_application()` (dòng 233)
  - `_read_visible_ui_text()` (dòng 236)
  - `_inspect_runtime_log()` (dòng 239)
  - `_read_current_error()` (dòng 242)
  - `_inspect_selected_file()` (dòng 245)
  - `_get_project_status()` (dòng 248)
  - `_execute_project()` (dòng 251)
  - `_project_list_files()` (dòng 261)
  - `_project_read_file()` (dòng 264)
  - `_project_search_text()` (dòng 267)
  - `_project_find_symbol()` (dòng 270)
  - `_project_git_diff()` (dòng 273)
  - `_project_apply_patch()` (dòng 276)
  - `_project_run_tests()` (dòng 279)
  - `_project_run_command()` (dòng 282)
  - `_project_rollback()` (dòng 285)
  - `_project_package_patch()` (dòng 288)
  - `_project_execute_task()` (dòng 291)
  - `_workspace_join()` (dòng 294)
  - `_workspace_switch()` (dòng 297)
  - `_workspace_list()` (dòng 300)
  - `_workspace_leave()` (dòng 303)
  - `_get_local_time()` (dòng 306)
  - `_get_now_playing()` (dòng 321)
  - `_focus_window()` (dòng 400)
  - `_open_url()` (dòng 448)
  - `_set_volume()` (dòng 472)
  - `_get_weather()` (dòng 515)
  - `_play_pause_media()` (dòng 678)
  - `_copy_text()` (dòng 688)
  - `_launch_app()` (dòng 707)
  - `_normalize_url()` (dòng 739)
  - `_press_virtual_key()` (dòng 749)
  - `_set_clipboard_text()` (dòng 755)
  - `_log()` (dòng 805)

### `src/cortex/causal_affect_pipeline.py` (156 dòng)

Facade for the evidence-grounded causal affect pipeline.  This module is intentionally side-effect-light.  The runtime owner may store the returned projection as ``active_causal_threads`` and feed it into endogenous state, planner context, performance and outcome learning.

**Class**

- `CausalAffectSnapshot` (dòng 31)
  - `to_public_dict()` (dòng 38)
- `CausalAffectPipeline` (dòng 49)
  - `bind_subject_service()` (dòng 60) — Use SubjectService as the causal state authority.  ``update`` remains as a compatibility projection for older callers. New production code should call :meth:`deliberate_subject` so the raw observation, substrate, need episodes, coalition and authorship records share one causal trace.
  - `async deliberate_subject()` (dòng 70)
  - `async observe_subject_outcome()` (dòng 75)
  - `update()` (dòng 80)
  - `attach_to_runtime()` (dòng 144) — Expose public-safe projections under conventional runtime fields.

### `src/cortex/subject/__init__.py` (9 dòng)

Eris Subject Core.  Public contracts and services are intentionally explicit.  Importing this package does not start runtimes, threads, databases or actuators.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/cortex/subject/authorship.py` (79 dòng)

Action authorship before and after execution.

**Class**

- `AuthorshipService` (dòng 11)
  - `__init__()` (dòng 12)
  - `draft()` (dòng 17)
  - `finalize()` (dòng 39)
  - `get()` (dòng 75)
  - `all()` (dòng 78)

### `src/cortex/subject/beliefs.py` (73 dòng)

Evidence-traceable belief projection.

**Class**

- `BeliefService` (dòng 11)
  - `__init__()` (dòng 12)
  - `all()` (dòng 17)
  - `get()` (dòng 20)
  - `revise()` (dòng 23)
  - `accessible()` (dòng 65)

### `src/cortex/subject/coalitions.py` (137 dòng)

Coalition arbitration with pragmatic and epistemic value.

**Class**

- `CoalitionScore` (dòng 15)
- `CoalitionArbiter` (dòng 24)
  - `__init__()` (dòng 37)
  - `_compatibility_key()` (dòng 53)
  - `build_compatible_coalitions()` (dòng 57)
  - `_score()` (dòng 63)
  - `choose()` (dòng 85)

### `src/cortex/subject/competence.py` (110 dòng)

Competence calibration and practice planning.

**Class**

- `CompetenceService` (dòng 17)
  - `__init__()` (dòng 18)
  - `predict()` (dòng 23)
  - `update()` (dòng 27)
  - `all()` (dòng 71)
- `PracticePlanner` (dòng 75)
  - `__init__()` (dòng 76)
  - `plan()` (dòng 80)

### `src/cortex/subject/consolidation.py` (73 dòng)

Temporal consolidation for episode residue and structural tendencies.

**Hàm top-level**

- `decay_to_baseline()` (dòng 13)

**Class**

- `TemporalConsolidator` (dòng 19)
  - `__init__()` (dòng 22)
  - `consolidate()` (dòng 26)

### `src/cortex/subject/continuity.py` (59 dòng)

Identity, commitment and continuity reconciliation.

**Class**

- `ContinuityService` (dòng 12)
  - `__init__()` (dòng 13)
  - `snapshot_ref()` (dòng 18)
  - `reconcile()` (dòng 22)

### `src/cortex/subject/contracts.py` (809 dòng)

Immutable contracts for the Eris Subject Core.  The contracts deliberately keep raw observations, interpretations, decisions, action attempts and outcomes as separate records.  A narrative may point to an event, but it never becomes the event.

**Hàm top-level**

- `clamp01()` (dòng 24)
- `ensure_non_empty()` (dòng 36)
- `freeze_mapping()` (dòng 43)
- `_jsonable()` (dòng 47)

**Class**

- `NeedKind` (dòng 61)
- `AttributionTarget` (dòng 69)
- `BeliefSourceKind` (dòng 77)
- `VisibilityScope` (dòng 86)
- `AuthorshipStage` (dòng 93)
- `OutcomeStatus` (dòng 102)
- `DerivedNeedStatus` (dòng 110)
- `CommitmentStatus` (dòng 118)
- `AttributionDistribution` (dòng 127)
  - `__post_init__()` (dòng 130)
  - `unknown()` (dòng 141)
  - `dominant()` (dòng 144)
  - `to_dict()` (dòng 147)
- `WorldObservation` (dòng 152)
  - `__post_init__()` (dòng 164)
  - `to_dict()` (dòng 171)
- `SubstrateCondition` (dòng 176)
  - `__post_init__()` (dòng 187)
- `OrganismicSubstrate` (dòng 202)
  - `__post_init__()` (dòng 217)
  - `viability_vector()` (dòng 230)
  - `to_dict()` (dòng 242)
- `SubjectAppraisal` (dòng 247)
  - `__post_init__()` (dòng 265)
- `NeedActivation` (dòng 277)
  - `__post_init__()` (dòng 287)
- `NeedEpisode` (dòng 294)
  - `__post_init__()` (dòng 314)
  - `is_closed()` (dòng 327)
- `DerivedNeed` (dòng 332)
  - `__post_init__()` (dòng 348)
- `Belief` (dòng 356)
  - `__post_init__()` (dòng 376)
- `BeliefProposal` (dòng 384)
  - `__post_init__()` (dòng 397)
- `BeliefRevision` (dòng 402)
- `Value` (dòng 410)
  - `__post_init__()` (dòng 427)
- `NarrativeInterpretation` (dòng 435)
  - `__post_init__()` (dòng 445)
- `ReflectiveMismatch` (dòng 450)
  - `__post_init__()` (dòng 459)
- `ActionProposal` (dòng 464)
  - `__post_init__()` (dòng 480)
- `MindDecision` (dòng 493)
  - `__post_init__()` (dòng 511)
  - `to_dict()` (dòng 515)
- `ActionAuthorship` (dòng 520)
  - `__post_init__()` (dòng 537)
- `CommitmentLedger` (dòng 546)
  - `__post_init__()` (dòng 563)
- `SelfContinuityRecord` (dòng 570)
  - `__post_init__()` (dòng 586)
- `IdentityChangeEvent` (dòng 592)
  - `__post_init__()` (dòng 605)
- `UnresolvedThread` (dòng 611)
  - `__post_init__()` (dòng 627)
- `ExistentialDecision` (dòng 632)
  - `__post_init__()` (dòng 646)
- `ActionRequest` (dòng 651)
  - `__post_init__()` (dòng 664)
- `WorldOutcome` (dòng 671)
  - `__post_init__()` (dòng 685)
  - `success_score()` (dòng 692)
  - `to_dict()` (dòng 701)
- `LearningReceipt` (dòng 706)
- `ConsolidationPatch` (dòng 717)
  - `__post_init__()` (dòng 726)
- `SkillModel` (dòng 734)
- `CompetenceEstimate` (dòng 749)
  - `__post_init__()` (dòng 764)
- `CompetenceGap` (dòng 774)
- `ProjectState` (dòng 782)
- `ProcessingBudget` (dòng 790)
- `PracticePlan` (dòng 797)

### `src/cortex/subject/episodes.py` (96 dòng)

Need episode lifecycle.

**Class**

- `NeedEpisodeRecorder` (dòng 11)
  - `__init__()` (dòng 12)
  - `open()` (dòng 18)
  - `attach_action()` (dòng 48)
  - `close()` (dòng 56)
  - `close_all_for_action()` (dòng 83)
  - `open_episodes()` (dòng 92)
  - `closed_episodes()` (dòng 95)

### `src/cortex/subject/existential.py` (45 dòng)

Irreversible or option-closing decisions.

**Class**

- `ExistentialDecisionService` (dòng 10)
  - `__init__()` (dòng 11)
  - `record()` (dòng 16)
  - `all()` (dòng 44)

### `src/cortex/subject/narrative.py` (84 dòng)

Non-omniscient narrative interpretation.

**Class**

- `NarrativeView` (dòng 12)
- `NarrativeBeliefGenerator` (dòng 23)
  - `__init__()` (dòng 24)
  - `interpret()` (dòng 28)
  - `record()` (dòng 66)

### `src/cortex/subject/needs.py` (203 dòng)

Need activation and derived-need plasticity.

**Class**

- `NeedDefinition` (dòng 21)
- `NeedSystem` (dòng 49)
  - `__init__()` (dòng 50)
  - `activate()` (dòng 53)
- `NeedPlasticityEngine` (dòng 131) — Propose derived needs from repeated cross-context co-activation.  The engine does not invent psychological labels.  It emits mechanical labels derived from parent IDs and a stable target selector supplied by episode context.
  - `propose()` (dòng 139)

### `src/cortex/subject/self_deception.py` (39 dòng)

Reflective mismatch detection without a privileged ``true_motive`` field.

**Class**

- `ReflectiveMismatchDetector` (dòng 10)
  - `__init__()` (dòng 11)
  - `inspect()` (dòng 14)

### `src/cortex/subject/service.py` (462 dòng)

Single orchestrator for the Eris Subject Core.

**Class**

- `SubjectRepositoryPort` (dòng 35)
  - `append_subject_event()` (dòng 36)
  - `save_projection()` (dòng 37)
- `AuditPort` (dòng 40)
  - `append()` (dòng 41)
- `SubjectServiceConfig` (dòng 45)
- `SubjectService` (dòng 54) — Observation → appraisal → need episode → coalition → decision.  The service never calls shell, filesystem, network, TTS or body adapters. Those capabilities live behind the actuator and sandbox boundaries.
  - `__init__()` (dòng 61)
  - `_as_payload()` (dòng 99)
  - `_normalize()` (dòng 111)
  - `_append_event()` (dòng 125)
  - `_appraise()` (dòng 153)
  - `_proposals_from_context()` (dòng 203)
  - `async deliberate()` (dòng 276)
  - `to_action_request()` (dòng 350)
  - `async observe_outcome()` (dòng 376)
  - `snapshot()` (dòng 448)

### `src/cortex/subject/substrate.py` (134 dòng)

Operational substrate measurement.  A substrate score changes only when the caller supplies measurement evidence. Utterances about mood are not measurements and therefore cannot lower these scores by themselves.

**Class**

- `MeasurementRule` (dòng 29)
- `SubstrateMonitor` (dòng 37) — Build a versioned substrate projection from concrete measurements.
  - `__init__()` (dòng 40)
  - `initial()` (dòng 47)
  - `measure()` (dòng 55)
  - `delta()` (dòng 129)

### `src/cortex/subject/values.py` (76 dòng)

Value formation from repeated, costly, endorsed choices.

**Class**

- `ValueFormationEngine` (dòng 12)
  - `__init__()` (dòng 13)
  - `update()` (dòng 17)

### `src/experiments/emergence/__init__.py` (6 dòng)

Paired-instance emergence evaluation.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/experiments/emergence/ablation.py` (28 dòng)

Clone-only causal ablation helpers.

**Hàm top-level**

- `tombstone_events()` (dòng 10) — Record experiment tombstones without mutating canonical events.

### `src/experiments/emergence/interventions.py` (20 dòng)

Experiment-only interventions.

**Hàm top-level**

- `remove_personality_descriptions()` (dòng 8)
- `async apply_history()` (dòng 14)

### `src/experiments/emergence/metrics.py` (79 dòng)

Pre-registered behavioral metrics without style-only features.

**Hàm top-level**

- `auroc()` (dòng 11)
- `brier()` (dòng 29)
- `log_loss()` (dòng 36)
- `standardized_difference()` (dòng 48)
- `compute_metrics()` (dòng 57)

### `src/experiments/emergence/paired_instances.py` (12 dòng)

**Hàm top-level**

- `async clone_instance()` (dòng 8)

### `src/experiments/emergence/report.py` (25 dòng)

**Class**

- `ExperimentReport` (dòng 11)
  - `to_dict()` (dòng 21)
  - `write_json()` (dòng 24)

### `src/experiments/emergence/runner.py` (97 dòng)

Paired experiment runner with seed-matched instances.

**Hàm top-level**

- `async _run_probe()` (dòng 48)
- `async run_paired_experiment()` (dòng 58)

**Class**

- `ProbeSpec` (dòng 16)
- `ExperimentSpec` (dòng 23)
- `RunResult` (dòng 37)
  - `to_metric_row()` (dòng 44)

### `src/memory/subject/__init__.py` (15 dòng)

Subject Core persistence.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/memory/subject/repository.py` (357 dòng)

SQLite source of truth for Subject Core events and projections.

**Hàm top-level**

- `canonical_json()` (dòng 28)
- `sha256_text()` (dòng 32)

**Class**

- `StaleRevisionError` (dòng 20)
- `EventIntegrityError` (dòng 24)
- `StoredEvent` (dòng 37)
- `SubjectRepository` (dòng 50) — Single-writer friendly repository with deterministic replay primitives.
  - `__init__()` (dòng 53)
  - `_configure()` (dòng 72)
  - `connection()` (dòng 79)
  - `foreign_keys_enabled()` (dòng 82)
  - `unit_of_work()` (dòng 85)
  - `close()` (dòng 88)
  - `apply_migrations()` (dòng 92)
  - `append_subject_event()` (dòng 120)
  - `_row_to_event()` (dòng 170)
  - `events()` (dòng 184)
  - `verify_event_chain()` (dòng 192)
  - `save_projection()` (dòng 212)
  - `get_projection()` (dòng 253)
  - `record_idempotent()` (dòng 264)
  - `append_authorship_event()` (dòng 280)
  - `append_world_outcome()` (dòng 290)
  - `projection_hash()` (dòng 300)
- `AsyncPersistenceActor` (dòng 311) — A bounded single writer for async runtimes.
  - `__init__()` (dòng 314)
  - `async start()` (dòng 319)
  - `async stop()` (dòng 323)
  - `async call()` (dòng 330)
  - `async _run()` (dòng 338)

### `src/memory/subject/unit_of_work.py` (47 dòng)

SQLite unit of work with explicit transaction ownership.

**Class**

- `UnitOfWork` (dòng 10)
  - `__init__()` (dòng 11)
  - `__enter__()` (dòng 16)
  - `commit()` (dòng 23)
  - `rollback()` (dòng 28)
  - `__exit__()` (dòng 33)

### `src/runtime/ai_orchestrated/executive_cortex.py` (1132 dòng)

Gemma Executive Cortex: one semantic authority between cognition and runtime.  DeepSeek workers expose typed affordances and own public wording. Runtime owns availability, permission, concurrency, validation, and execution evidence. Gemma alone chooses conversational trajectory, exact affordance IDs, semantic capability shortlists, and exact capability IDs.

**Hàm top-level**

- `_flag()` (dòng 120)
- `_compact()` (dòng 127)
- `_clamp01()` (dòng 132)
- `_clean_ids()` (dòng 142)
- `_clean_conditions()` (dòng 214)
- `may_release_optional_reply_baton()` (dòng 508)

**Class**

- `ReviewCondition` (dòng 159)
  - `from_mapping()` (dòng 164)
  - `to_dict()` (dòng 172)
- `ExecutiveEvent` (dòng 177)
  - `from_mapping()` (dòng 185)
  - `to_dict()` (dòng 204)
- `ExecutiveState` (dòng 248)
  - `from_mapping()` (dòng 259) — Restore a runtime-clock state mapping. Legacy v1 persistence used this basis.
  - `from_persisted_mapping()` (dòng 297) — Restore wall-clock persistence into the current runtime clock domain.
  - `to_dict()` (dòng 332)
  - `to_persisted_dict()` (dòng 345)
- `ExecutiveDecision` (dòng 361)
  - `parse()` (dòng 385)
  - `unavailable()` (dòng 437)
  - `to_dict()` (dòng 440)
- `InteractiveExecutiveDirective` (dòng 468)
  - `__getattr__()` (dòng 476)
  - `to_dict()` (dòng 487)
- `ExecutiveOutcome` (dòng 500)
- `ExecutiveCortex` (dòng 521) — Stateful Gemma policy layer for conversational trajectory.
  - `__init__()` (dòng 524)
  - `enabled()` (dòng 549)
  - `state()` (dòng 553)
  - `should_reconsider()` (dòng 557) — Apply Gemma policy to scored runtime facts without renaming their meaning.
  - `_system_prompt()` (dòng 595)
  - `_candidate_capabilities()` (dòng 637) — Use V54 hard filtering, while honoring an injected V53 facade.
  - `plan_interactive()` (dòng 665)
  - `_semantic_shortlist_interactive()` (dòng 732)
  - `_decide_interactive()` (dòng 750)
  - `deliberate()` (dòng 779)
  - `_semantic_shortlist()` (dòng 859)
  - `_decide()` (dòng 878)
  - `_invoke()` (dòng 917)
  - `_execute_exact_capability()` (dòng 948)
  - `_update_state()` (dòng 1019)
  - `_set_failure_backoff()` (dòng 1051)
  - `materialize_candidate()` (dòng 1061)
  - `_rewrite_candidate()` (dòng 1065)
  - `_candidate_from_capability()` (dòng 1083)
  - `_log()` (dòng 1113)

### `src/runtime/ai_orchestrated/executive_tools.py` (292 dòng)

Live capability contracts for the Gemma Executive Cortex.  Runtime performs only hard filtering: availability, exposure, effect, domain, risk, and permission. Gemma performs semantic shortlisting from compact cards, then receives full schemas only for the exact IDs it shortlisted. No phrase router, synonym table, registry-order top-N, or capability reinterpretation is allowed here.

**Hàm top-level**

- `_contract_metadata()` (dòng 73) — Return risk, permission, and provenance from the strongest contract.
- `_auto_callable()` (dòng 107)
- `_snapshot()` (dòng 115)
- `all_executive_tools()` (dòng 131)
- `build_capability_index()` (dòng 179) — Return category counts only, never capability schemas.
- `filter_executive_tools()` (dòng 191) — Apply hard runtime constraints without semantic ranking or top-N truncation.
- `retrieve_executive_tools()` (dòng 223) — Compatibility facade for the V53 bounded retrieval contract.  V54 removed runtime semantic ranking. This facade therefore delegates to the hard filter and only applies an explicit caller-provided safety bound. The default returns the complete filtered set.
- `select_tools_by_id()` (dòng 255) — Materialize full schemas for exact IDs already shortlisted by Gemma.
- `catalog_index()` (dòng 279)

**Class**

- `ExecutiveTool` (dòng 23)
  - `to_card()` (dòng 38) — Compact semantic card used only for Gemma shortlisting.
  - `to_dict()` (dòng 51)
- `CapabilityIndex` (dòng 58)
  - `to_dict()` (dòng 64)

### `src/runtime/audit/__init__.py` (9 dòng)

Forensic audit boundary.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/runtime/audit/contracts.py` (56 dòng)

Append-only audit contracts.

**Class**

- `AuditEventKind` (dòng 10)
- `AuditEvent` (dòng 24)
  - `to_dict()` (dòng 35)
- `CausalTrace` (dòng 43)
- `ReplayResult` (dòng 51)

### `src/runtime/audit/forensic_store.py` (228 dòng)

Independent append-only forensic store with a hash chain.

**Class**

- `ForensicIntegrityError` (dòng 19)
- `ForensicStore` (dòng 48)
  - `__init__()` (dòng 49)
  - `_hash()` (dòng 68)
  - `close()` (dòng 71)
  - `append()` (dòng 75)
  - `_row_to_event()` (dòng 134)
  - `query()` (dòng 147)
  - `verify_chain()` (dòng 174)
  - `causal_trace()` (dòng 201)

### `src/runtime/audit/replay.py` (43 dòng)

Deterministic forensic replay.

**Hàm top-level**

- `default_reducer()` (dòng 16)

**Class**

- `ReplayEngine` (dòng 26)
  - `__init__()` (dòng 27)
  - `replay()` (dòng 31)

### `src/runtime/coordinator_bootstrap.py` (838 dòng)

Extracted coordinator runtime boundary.  The methods remain owner-oriented for backward compatibility while the main coordinator becomes a small composition surface. New behavior should prefer typed services over adding more methods to these compatibility mixins.

**Class**

- `CoordinatorBootstrapMixin` (dòng 83) — Ordered bootstrap pipeline for the coordinator facade.
  - `__init__()` (dòng 86)
  - `_record_bootstrap_phase_success()` (dòng 119)
  - `_run_bootstrap_phase()` (dòng 130)
  - `_bootstrap_foundation()` (dòng 153)
  - `_bootstrap_memory_and_capabilities()` (dòng 224)
  - `_bootstrap_hardening_and_state()` (dòng 344)
  - `_bootstrap_cognition_services()` (dòng 489)
  - `_bootstrap_session_and_perception()` (dòng 623) — Các biến này lưu trạng thái hội thoại: có đang chat không, lịch sử chat, câu trả lời gần nhất, intent gần nhất, topic đang active, text cuối cùng đã nói, mood score, idle cycles, các guard chống lặp.
  - `_bootstrap_thought_and_ai()` (dòng 786)

### `src/runtime/dialogue/__init__.py` (13 dòng)

Unified dialogue runtime.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/runtime/dialogue/body_adapter.py` (59 dòng)

Typed Subject Core performance frame for Godot/Live2D transport.

**Class**

- `BodyDeliveryReceipt` (dòng 13)
- `SubjectPerformanceBodyAdapter` (dòng 21)
  - `__init__()` (dòng 25)
  - `async send_performance()` (dòng 28)

### `src/runtime/dialogue/contracts.py` (144 dòng)

Dialogue, social-risk and incremental speech contracts.

**Class**

- `ThoughtCandidate` (dòng 11)
  - `__post_init__()` (dòng 22)
- `RollingThoughtBuffer` (dòng 30)
- `DiscourseState` (dòng 40)
- `SocialRiskPolicy` (dòng 58)
  - `__post_init__()` (dòng 72)
- `PerformanceIntent` (dòng 84)
- `DialoguePlan` (dòng 95)
  - `__post_init__()` (dòng 108)
- `SpeechChunk` (dòng 116)
- `DeliveryReceipt` (dòng 128)
  - `__post_init__()` (dòng 140)

### `src/runtime/dialogue/discourse.py` (70 dòng)

Unified discourse projection.

**Class**

- `DiscourseService` (dòng 11)
  - `__init__()` (dòng 12)
  - `get()` (dòng 16)
  - `update()` (dòng 38)

### `src/runtime/dialogue/incremental_speech.py` (87 dòng)

Clause-level TTS and body coordination with cancellation.

**Class**

- `TTSLike` (dòng 13)
  - `async synthesize()` (dòng 14)
- `BodyLike` (dòng 17)
  - `async send_performance()` (dòng 18)
- `IncrementalSpeechCoordinator` (dòng 21)
  - `__init__()` (dòng 22)
  - `async speak()` (dòng 35)

### `src/runtime/dialogue/realizer.py` (74 dòng)

Natural dialogue realization constrained by semantic commitments.

**Class**

- `DialogueContractViolation` (dòng 15)
- `NaturalDialogueRealizer` (dòng 19)
  - `__init__()` (dòng 20)
  - `_word_count()` (dòng 24)
  - `_material()` (dòng 27)
  - `async realize()` (dòng 41)

### `src/runtime/dialogue/rolling_thought.py` (55 dòng)

Bounded semantic thought buffer, not a chain-of-thought log.

**Class**

- `RollingThoughtService` (dòng 11)
  - `__init__()` (dòng 12)
  - `get()` (dòng 20)
  - `add()` (dòng 34)
  - `public_candidates()` (dòng 50)

### `src/runtime/dialogue/service.py` (86 dòng)

Dialogue delivery service from MindDecision to DeliveryReceipt.

**Class**

- `DialogueService` (dòng 18)
  - `__init__()` (dòng 19)
  - `plan_from_decision()` (dòng 38)
  - `async deliver()` (dòng 72)

### `src/runtime/outcome_observer.py` (752 dòng)

**Class**

- `OutcomeReport` (dòng 24) — Báo cáo hậu quả sau một turn.  Các field lõi bám theo ERIS Cognitive Pipeline: - user_accepted: user có chấp nhận/đồng ý với câu trả lời không.   `None` nghĩa là chưa đủ tín hiệu. - user_corrected: user có sửa ERIS không. - user_ignored: user có bỏ qua phản hồi không.   Field này chỉ nên bật khi runtime có tín hiệu idle/session thật. - user_laughed: user có phản ứng hài/hưởng ứng không. - user_confused: user có vẻ khó hiểu/lạc nhịp không. - user_felt_intruded: user có cảm giác bị xen vào/bị suy diễn/bị xâm phạm không.   `None` nghĩa là chưa đủ tín hiệu. - user_soothed: user có đang dỗ/trấn an/xoa dịu ERIS không (vd "đừng lo",   "không sao đâu", "tôi ở đây"). `None` nghĩa là chưa đủ tín hiệu. Đây là tín   hiệu để private mind cho nỗi lo nguôi đi thay vì pegged mãi. - relation_improved / relation_ruptured: quan hệ có tốt lên/rạn đi không.   `None` nghĩa là chưa đủ tín hiệu. - action_success: hành động/text/system action có thực thi ổn không. - body_match_success: body có khớp speech/action không. - evidence: các mẩu bằng chứng ngắn, dùng cho audit/debug.
  - `to_dict()` (dòng 89)
  - `to_world_outcome()` (dòng 92) — Adapt the operational report to the Subject Core world contract.
  - `from_any()` (dòng 123)
- `OutcomeObserver` (dòng 132) — Đọc tín hiệu hậu quả sau một turn.  Cách dùng thường gặp:     outcome = outcome_observer.observe(frame)     frame.outcome = outcome  Nếu muốn đánh giá phản ứng user đối với turn trước:     outcome = outcome_observer.observe(previous_frame, user_feedback_text=current_user_text)  Tầng này không nên đoán quá sâu. Nếu thiếu feedback của user, các field như accepted/corrected/ruptured phải giữ ở mức không chắc.
  - `observe()` (dòng 211) — Tạo OutcomeReport từ frame và các tín hiệu hậu quả.  Parameters ---------- frame:     CognitiveFrame hoặc object tương thích. user_feedback_text:     Phản hồi user sau turn này. Nếu chưa có thì để None. execution_result:     Kết quả system action nếu có. Có thể là dict/dataclass có `success`. body_result:     Kết quả body/modality nếu có. Có thể là dict/dataclass có `matched` hoặc `success`. idle_seconds_after_turn:     Nếu runtime biết user im/bỏ qua sau turn bao lâu, truyền vào đây. attach_to_frame:     Nếu True, gắn report vào `frame.outcome` khi có thể.
  - `observe_user_feedback_for_previous_frame()` (dòng 515) — Helper dành cho coordinator khi user vừa nhắn một câu phản hồi. Thay vì đánh giá current frame, nó đánh giá câu user đó như phản ứng đối với previous_frame.
  - `_infer_action_success()` (dòng 536)
  - `_infer_body_match_success()` (dòng 589)
  - `_estimate_confidence()` (dòng 630)
  - `_normalize()` (dòng 657)
  - `_has_any()` (dòng 665)
  - `_extract_final_text()` (dòng 675)
  - `_extract_system_action()` (dòng 694)
  - `_read_bool()` (dòng 710)
  - `_read_float()` (dòng 728)
  - `_safe_setattr()` (dòng 741)
  - `_clamp01()` (dòng 748)

### `src/runtime/subject_bootstrap.py` (82 dòng)

Feature-flagged composition for Subject Core rollout.

**Hàm top-level**

- `subject_core_enabled()` (dòng 20)
- `build_subject_core_components()` (dòng 37)

**Class**

- `SubjectCoreComponents` (dòng 25)
  - `close()` (dòng 32)

### `src/runtime/subject_runtime.py` (140 dòng)

Top-level orchestration across Mind, actuator, dialogue and audit boundaries.

**Class**

- `DialoguePort` (dòng 17)
  - `async deliver()` (dòng 18)
- `AuditSink` (dòng 21)
  - `append()` (dòng 22)
- `RuntimeResult` (dòng 26)
- `SubjectRuntime` (dòng 33)
  - `__init__()` (dòng 34)
  - `async _audit_append()` (dòng 51)
  - `async handle()` (dòng 58)

### `src/runtime/world/__init__.py` (14 dòng)

Actuator and sandbox world boundary.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/runtime/world/actuator.py` (55 dòng)

Actuator adapter from Subject Core requests to sandbox commands.

**Class**

- `SandboxActuator` (dòng 14)
  - `__init__()` (dòng 15)
  - `_command_kind()` (dòng 30)
  - `async execute()` (dòng 40)

### `src/runtime/world/capability_policy.py` (89 dòng)

Capability policy for the resistant world boundary.

**Class**

- `CommandPolicy` (dòng 14)
  - `__post_init__()` (dòng 26)
- `PolicyDecision` (dòng 33)
- `CapabilityPolicy` (dòng 40)
  - `__init__()` (dòng 41)
  - `_resolve_workspace_path()` (dòng 44)
  - `authorize()` (dòng 53)
  - `filtered_environment()` (dòng 87)

### `src/runtime/world/consequences.py` (41 dòng)

Operational consequences from world resistance.

**Class**

- `ConsequenceSignal` (dòng 11)
- `ConsequenceEngine` (dòng 18)
  - `derive()` (dòng 19)

### `src/runtime/world/contracts.py` (65 dòng)

Typed actuator and sandbox contracts.

**Class**

- `SandboxCommandKind` (dòng 12)
- `CapabilityToken` (dòng 23)
  - `permits()` (dòng 32)
- `SandboxCommand` (dòng 37)
- `ActionReceipt` (dòng 50)
  - `to_world_outcome()` (dòng 56)
- `SandboxPort` (dòng 60)
  - `async apply()` (dòng 61)
- `ActuatorPort` (dòng 64)
  - `async execute()` (dòng 65)

### `src/runtime/world/sandbox.py` (188 dòng)

Resistant sandbox world.  The mind may propose any command.  This class decides whether the world permits it and records a real, denied or simulated consequence without rewriting the proposal.

**Class**

- `SandboxWorld` (dòng 26)
  - `__init__()` (dòng 27)
  - `async apply()` (dòng 47)
  - `async _execute()` (dòng 69)
  - `_outcome()` (dòng 121)
  - `_record()` (dòng 142)
  - `authorize_legacy_action()` (dòng 176)

### `src/runtime/world/tts_broker.py` (30 dòng)

External TTS broker boundary.

**Class**

- `TTSReceipt` (dòng 10)
- `TTSBroker` (dòng 18)
  - `__init__()` (dòng 19)
  - `async synthesize()` (dòng 22)

### `src/tools/__init__.py` (1 dòng)

Release, evaluation, and static-audit utilities for the Eris runtime.

- Không có class/hàm top-level đáng kể; file chủ yếu là import, constant hoặc fixture.

### `src/tools/audit_remote_inference_paths.py` (60 dòng)

AST audit for accidental remote-model calls outside the inference boundary.

**Hàm top-level**

- `_approved()` (dòng 16)
- `audit()` (dòng 21)

### `src/tools/audit_semantic_authority_paths.py` (47 dòng)

Static audit for retired phrase-routing authority in production modules.

**Hàm top-level**

- `audit()` (dòng 17)

### `src/tools/evaluate_semantic_paraphrases.py` (77 dòng)

Evaluate typed semantic-frame predictions against accepted paraphrases.

**Hàm top-level**

- `_accepted()` (dòng 10)
- `evaluate()` (dòng 16)
- `main()` (dòng 58)

### `src/tools/evaluate_social_plan_activation.py` (176 dòng)

Evaluate activation decisions produced by the social-plan model.

**Hàm top-level**

- `_plan_from_prediction()` (dòng 27)
- `_decision()` (dòng 34)
- `_gold()` (dòng 43)
- `_metrics()` (dòng 50)
- `evaluate_cases()` (dòng 65)
- `_load_jsonl()` (dòng 119)
- `_load_predictor()` (dòng 130)
- `main()` (dòng 138)

### `src/tools/package_source.py` (52 dòng)

Create reproducible source ZIP archives.

**Hàm top-level**

- `sha256()` (dòng 14)
- `_files()` (dòng 22)
- `package()` (dòng 33)

### `src/tools/report_pdf_acceptance.py` (190 dòng)

Build acceptance summaries from Eris observability events.  The report format is intentionally pure-Python and deterministic so it can be used in tests, CI, and offline release review without pulling in a dashboard stack merely to add several numbers together, a mercy rarely granted by modern software.

**Hàm top-level**

- `_number()` (dòng 25)
- `_percentile()` (dòng 35)
- `_distribution()` (dòng 43)
- `_lane()` (dòng 53)
- `_is_optional_lane()` (dòng 57)
- `_summarize()` (dòng 65)
- `build_report()` (dòng 139) — Build the stable ``eris.pdf_acceptance.v3`` report.

### `src/tools/verify_release.py` (102 dòng)

Inspect and safely extract release ZIP archives.

**Hàm top-level**

- `_digest()` (dòng 21)
- `_validate_name()` (dòng 29)
- `_is_symlink()` (dòng 41)
- `inspect_archive()` (dòng 46)
- `safe_extract_archive()` (dòng 76)

**Class**

- `ArchiveInspection` (dòng 13)

## 20. Danh sách file toàn gói

Danh sách này được tạo trước manifest cuối; các file release sinh sau sẽ nằm trong manifest riêng.

- `body/BodyAudioController.cs` — 3,823 bytes
- `body/BodyAudioController.cs.uid` — 20 bytes
- `body/ErisProcessManager.cs` — 17,884 bytes
- `body/ErisProcessManager.cs.uid` — 20 bytes
- `body/INNER_DIARY_PANEL_V10_MANIFEST.json` — 755 bytes
- `body/Live2DBodyManager.cs` — 6,432 bytes
- `body/Live2DBodyManager.cs.uid` — 20 bytes
- `body/LocalBodyAutonomy.cs` — 21,849 bytes
- `body/LocalBodyAutonomy.cs.uid` — 20 bytes
- `body/MotionController.cs` — 21,556 bytes
- `body/MotionController.cs.uid` — 20 bytes
- `body/PANEL_RUNTIME_SYNC_MANIFEST.json` — 1,658 bytes
- `body/PANEL_SETTINGS_CONTRACT_V8_MANIFEST.json` — 401 bytes
- `body/RunLogger.cs` — 5,108 bytes
- `body/RunLogger.cs.uid` — 20 bytes
- `body/SubjectPerformanceFrame.cs` — 4,041 bytes
- `body/UdpDecisionParser.cs` — 21,846 bytes
- `body/UdpDecisionParser.cs.uid` — 19 bytes
- `body/UdpListener.ConversationUi.cs` — 40,965 bytes
- `body/UdpListener.ConversationUi.cs.uid` — 20 bytes
- `body/UdpListener.DepthPanel.cs` — 202,155 bytes
- `body/UdpListener.DepthPanel.cs.uid` — 20 bytes
- `body/UdpListener.IdentityPrivateMind.cs` — 9,276 bytes
- `body/UdpListener.IdentityPrivateMind.cs.uid` — 20 bytes
- `body/UdpListener.Live2D.cs` — 16,727 bytes
- `body/UdpListener.Live2D.cs.uid` — 20 bytes
- `body/UdpListener.MaintenanceUiSync.cs` — 10,525 bytes
- `body/UdpListener.MaintenanceUiSync.cs.uid` — 20 bytes
- `body/UdpListener.MemoryPanel.cs` — 41,153 bytes
- `body/UdpListener.MemoryPanel.cs.uid` — 20 bytes
- `body/UdpListener.RuntimePresence.cs` — 26,596 bytes
- `body/UdpListener.RuntimePresence.cs.uid` — 20 bytes
- `body/UdpListener.SettingsAdvanced.cs` — 45,964 bytes
- `body/UdpListener.SettingsAdvanced.cs.uid` — 20 bytes
- `body/UdpListener.SettingsDanger.cs` — 34,216 bytes
- `body/UdpListener.SettingsDanger.cs.uid` — 19 bytes
- `body/UdpListener.SettingsPanel.cs` — 138,084 bytes
- `body/UdpListener.SettingsPanel.cs.uid` — 20 bytes
- `body/UdpListener.SettingsSchemaPanel.cs` — 36,406 bytes
- `body/UdpListener.SettingsSchemaPanel.cs.uid` — 24 bytes
- `body/UdpListener.TutorPanel.cs` — 28,543 bytes
- `body/UdpListener.TutorPanel.cs.uid` — 19 bytes
- `body/UdpListener.cs` — 235,300 bytes
- `body/UdpListener.cs.uid` — 20 bytes
- `body/udpListener.tscn` — 5,874 bytes
- `docs/history/CAUSAL_AFFECT_V1_IMPLEMENTATION.md` — 6,770 bytes
- `docs/history/SUBJECT_CORE_V1_IMPLEMENTATION.md` — 4,479 bytes
- `docs/history/SUBJECT_CORE_V2_IMPLEMENTATION.md` — 2,915 bytes
- `docs/history/V1_IMPLEMENTATION_REPORT.md` — 4,479 bytes
- `docs/history/V1_SHA256.txt` — 454 bytes
- `docs/history/V2_IMPLEMENTATION_REPORT.md` — 2,915 bytes
- `docs/history/V2_SHA256.txt` — 300 bytes
- `docs/spec/Đặc tả kỹ thuật kiến trúc chủ thể nhân tạo Eris.pdf` — 571,556 bytes
- `docs/spec/Đặc_tả_kỹ_thuật_Eris_parsed.txt` — 55,900 bytes
- `docs/tests/PYTEST_CURRENT_CONTRACT_864_PASS_2_DESELECTED.log` — 995 bytes
- `docs/tests/PYTEST_FULL_864_PASS_2_FAIL.log` — 3,679 bytes
- `docs/tests/PYTEST_V1_FULL.log` — 27,370 bytes
- `original_snapshots/body(11).zip` — 227,331 bytes
- `original_snapshots/src(55).zip` — 9,362,309 bytes
- `patch_history/v1/MANIFEST.json` — 12,345 bytes
- `patch_history/v1/body/SubjectPerformanceFrame.cs` — 4,041 bytes
- `patch_history/v1/src/SUBJECT_CORE_IMPLEMENTATION.md` — 4,479 bytes
- `patch_history/v1/src/actions/executor.py` — 34,847 bytes
- `patch_history/v1/src/cortex/causal_affect_pipeline.py` — 6,205 bytes
- `patch_history/v1/src/cortex/subject/__init__.py` — 323 bytes
- `patch_history/v1/src/cortex/subject/authorship.py` — 3,655 bytes
- `patch_history/v1/src/cortex/subject/beliefs.py` — 3,367 bytes
- `patch_history/v1/src/cortex/subject/coalitions.py` — 5,909 bytes
- `patch_history/v1/src/cortex/subject/competence.py` — 4,452 bytes
- `patch_history/v1/src/cortex/subject/consolidation.py` — 3,397 bytes
- `patch_history/v1/src/cortex/subject/continuity.py` — 2,744 bytes
- `patch_history/v1/src/cortex/subject/contracts.py` — 26,653 bytes
- `patch_history/v1/src/cortex/subject/episodes.py` — 3,562 bytes
- `patch_history/v1/src/cortex/subject/existential.py` — 1,632 bytes
- `patch_history/v1/src/cortex/subject/narrative.py` — 3,819 bytes
- `patch_history/v1/src/cortex/subject/needs.py` — 9,251 bytes
- `patch_history/v1/src/cortex/subject/self_deception.py` — 1,441 bytes
- `patch_history/v1/src/cortex/subject/service.py` — 23,025 bytes
- `patch_history/v1/src/cortex/subject/substrate.py` — 5,268 bytes
- `patch_history/v1/src/cortex/subject/values.py` — 4,015 bytes
- `patch_history/v1/src/experiments/emergence/__init__.py` — 318 bytes
- `patch_history/v1/src/experiments/emergence/ablation.py` — 935 bytes
- `patch_history/v1/src/experiments/emergence/interventions.py` — 636 bytes
- `patch_history/v1/src/experiments/emergence/metrics.py` — 3,376 bytes
- `patch_history/v1/src/experiments/emergence/paired_instances.py` — 337 bytes
- `patch_history/v1/src/experiments/emergence/report.py` — 686 bytes
- `patch_history/v1/src/experiments/emergence/runner.py` — 3,621 bytes
- `patch_history/v1/src/experiments/emergence/scenarios/ablation.yaml` — 96 bytes
- `patch_history/v1/src/experiments/emergence/scenarios/counterfactual.yaml` — 178 bytes
- `patch_history/v1/src/experiments/emergence/scenarios/persistence.yaml` — 164 bytes
- `patch_history/v1/src/experiments/emergence/scenarios/resistance.yaml` — 101 bytes
- `patch_history/v1/src/experiments/emergence/scenarios/transfer.yaml` — 118 bytes
- `patch_history/v1/src/memory/subject/__init__.py` — 394 bytes
- `patch_history/v1/src/memory/subject/migrations/0001_subject_core.sql` — 5,113 bytes
- `patch_history/v1/src/memory/subject/migrations/0002_competence.sql` — 612 bytes
- `patch_history/v1/src/memory/subject/migrations/0003_dialogue.sql` — 813 bytes
- `patch_history/v1/src/memory/subject/repository.py` — 15,332 bytes
- `patch_history/v1/src/memory/subject/schema.sql` — 268 bytes
- `patch_history/v1/src/memory/subject/unit_of_work.py` — 1,262 bytes
- `patch_history/v1/src/pyproject.toml` — 1,168 bytes
- `patch_history/v1/src/runtime/audit/__init__.py` — 352 bytes
- `patch_history/v1/src/runtime/audit/contracts.py` — 1,409 bytes
- `patch_history/v1/src/runtime/audit/forensic_store.py` — 9,849 bytes
- `patch_history/v1/src/runtime/audit/replay.py` — 1,586 bytes
- `patch_history/v1/src/runtime/coordinator_bootstrap.py` — 43,308 bytes
- `patch_history/v1/src/runtime/dialogue/__init__.py` — 646 bytes
- `patch_history/v1/src/runtime/dialogue/body_adapter.py` — 1,998 bytes
- `patch_history/v1/src/runtime/dialogue/contracts.py` — 4,190 bytes
- `patch_history/v1/src/runtime/dialogue/discourse.py` — 2,839 bytes
- `patch_history/v1/src/runtime/dialogue/incremental_speech.py` — 3,458 bytes
- `patch_history/v1/src/runtime/dialogue/realizer.py` — 3,442 bytes
- `patch_history/v1/src/runtime/dialogue/rolling_thought.py` — 2,197 bytes
- `patch_history/v1/src/runtime/dialogue/service.py` — 4,294 bytes
- `patch_history/v1/src/runtime/outcome_observer.py` — 32,195 bytes
- `patch_history/v1/src/runtime/subject_bootstrap.py` — 3,279 bytes
- `patch_history/v1/src/runtime/subject_runtime.py` — 5,848 bytes
- `patch_history/v1/src/runtime/world/__init__.py` — 717 bytes
- `patch_history/v1/src/runtime/world/actuator.py` — 2,247 bytes
- `patch_history/v1/src/runtime/world/capability_policy.py` — 4,192 bytes
- `patch_history/v1/src/runtime/world/consequences.py` — 1,425 bytes
- `patch_history/v1/src/runtime/world/contracts.py` — 1,742 bytes
- `patch_history/v1/src/runtime/world/sandbox.py` — 9,093 bytes
- `patch_history/v1/src/runtime/world/tts_broker.py` — 1,116 bytes
- `patch_history/v1/src/tests/audit/test_forensic_replay.py` — 1,396 bytes
- `patch_history/v1/src/tests/dialogue/test_dialogue_runtime.py` — 3,083 bytes
- `patch_history/v1/src/tests/emergence/test_runner.py` — 1,547 bytes
- `patch_history/v1/src/tests/migrations/test_subject_repository.py` — 4,136 bytes
- `patch_history/v1/src/tests/subject/test_subject_core.py` — 5,694 bytes
- `patch_history/v1/src/tests/subject/test_subject_runtime_integration.py` — 2,872 bytes
- `patch_history/v1/src/tests/world/test_sandbox_world.py` — 3,146 bytes
- `patch_history/v2/CURRENT_CONTRACT_TEST_LOG.txt` — 995 bytes
- `patch_history/v2/MANIFEST.json` — 2,460 bytes
- `patch_history/v2/SUBJECT_CORE_V2_IMPLEMENTATION.md` — 2,915 bytes
- `patch_history/v2/actions/capability_registry.py` — 30,818 bytes
- `patch_history/v2/pyproject.toml` — 1,178 bytes
- `patch_history/v2/runtime/ai_orchestrated/executive_cortex.py` — 49,513 bytes
- `patch_history/v2/runtime/ai_orchestrated/executive_tools.py` — 10,701 bytes
- `patch_history/v2/tools/__init__.py` — 76 bytes
- `patch_history/v2/tools/audit_remote_inference_paths.py` — 2,417 bytes
- `patch_history/v2/tools/audit_semantic_authority_paths.py` — 1,735 bytes
- `patch_history/v2/tools/evaluate_semantic_paraphrases.py` — 3,046 bytes
- `patch_history/v2/tools/evaluate_social_plan_activation.py` — 6,649 bytes
- `patch_history/v2/tools/package_source.py` — 1,893 bytes
- `patch_history/v2/tools/report_pdf_acceptance.py` — 7,217 bytes
- `patch_history/v2/tools/verify_release.py` — 3,561 bytes
- `src/.gitignore` — 476 bytes
- `src/AUTONOMOUS_INITIATIVE_V17_MANIFEST.json` — 1,176 bytes
- `src/CAUSAL_AFFECT_V1_IMPLEMENTATION.md` — 6,770 bytes
- `src/GEMMA_EXECUTIVE_CORTEX_V53_MANIFEST.json` — 1,170 bytes
- `src/GEMMA_EXECUTIVE_CORTEX_V54_MANIFEST.json` — 1,827 bytes
- `src/GEMMA_EXECUTIVE_CORTEX_V55_MANIFEST.json` — 2,256 bytes
- `src/REFACTOR_MANIFEST_V42.json` — 485 bytes
- `src/RELEASE_MANIFEST.json` — 5,171 bytes
- `src/SOCIAL_AGENDA_V21_MANIFEST.json` — 1,971 bytes
- `src/SOCIAL_AGENDA_V22_MANIFEST.json` — 1,766 bytes
- `src/SUBJECT_CORE_IMPLEMENTATION.md` — 4,479 bytes
- `src/SUBJECT_CORE_V2_IMPLEMENTATION.md` — 2,915 bytes
- `src/actions/__init__.py` — 397 bytes
- `src/actions/capability_registry.py` — 30,818 bytes
- `src/actions/capability_runtime.py` — 13,814 bytes
- `src/actions/confirmation.py` — 3,889 bytes
- `src/actions/contracts.py` — 4,978 bytes
- `src/actions/executor.py` — 34,847 bytes
- `src/actions/observer.py` — 7,037 bytes
- `src/app_logging.py` — 5,251 bytes
- `src/assets/live2d/infj/infj.1024/texture_00.png` — 667,353 bytes
- `src/assets/live2d/infj/infj.1024/texture_00.png.import` — 966 bytes
- `src/assets/live2d/infj/infj.cdi3.json` — 3,871 bytes
- `src/assets/live2d/infj/infj.moc3` — 72,192 bytes
- `src/assets/live2d/infj/infj.model3.json` — 413 bytes
- `src/assets/live2d/infj/infj.physics3.json` — 4,192 bytes
- `src/assets/tts/greetings/.gitkeep` — 0 bytes
- `src/assets/tts/greetings/manifest.json` — 17,813 bytes
- `src/assets/tts/greetings/render_queue.audio.translation` — 2,462 bytes
- `src/assets/tts/greetings/render_queue.csv` — 4,492 bytes
- `src/assets/tts/greetings/render_queue.csv.import` — 913 bytes
- `src/assets/tts/greetings/render_queue.emotion.translation` — 1,612 bytes
- `src/assets/tts/greetings/render_queue.motion.translation` — 1,659 bytes
- `src/assets/tts/greetings/render_queue.output.translation` — 2,463 bytes
- `src/assets/tts/greetings/render_queue.prosody.translation` — 1,608 bytes
- `src/assets/tts/greetings/render_queue.text.translation` — 2,989 bytes
- `src/config/deepseek.env.example` — 5,188 bytes
- `src/config/deepseek_workers.env.example` — 4,205 bytes
- `src/config/exception_budget.json` — 26,197 bytes
- `src/config/memory.env.example` — 3,291 bytes
- `src/config/memory_benchmark_cases_vi.jsonl` — 1,298 bytes
- `src/config/pdf_refactor.env.example` — 1,260 bytes
- `src/config/phase7_validation_plan_vi.json` — 5,125 bytes
- `src/config/social_agenda_v21.env.example` — 1,083 bytes
- `src/config/social_agenda_v22.env.example` — 953 bytes
- `src/core/__init__.py` — 614 bytes
- `src/core/cognition/__init__.py` — 804 bytes
- `src/core/cognition/contracts.py` — 11,861 bytes
- `src/core/conversation_intent.py` — 1,011 bytes
- `src/core/di.py` — 775 bytes
- `src/core/evidence.py` — 27,877 bytes
- `src/core/temporal_context.py` — 10,750 bytes
- `src/cortex/__init__.py` — 385 bytes
- `src/cortex/action_memory.py` — 17,634 bytes
- `src/cortex/affect_semantics.py` — 37,288 bytes
- `src/cortex/agent_mind_persistence.py` — 36,658 bytes
- `src/cortex/appetite_system.py` — 13,594 bytes
- `src/cortex/appraisal_engine.py` — 8,149 bytes
- `src/cortex/background_observer.py` — 20,209 bytes
- `src/cortex/banned_filler.py` — 2,504 bytes
- `src/cortex/causal_affect_models.py` — 9,973 bytes
- `src/cortex/causal_affect_pipeline.py` — 6,205 bytes
- `src/cortex/causal_threads.py` — 4,128 bytes
- `src/cortex/connection_drive.py` — 8,586 bytes
- `src/cortex/contracts.py` — 48,500 bytes
- `src/cortex/conversation_dynamics.py` — 46,621 bytes
- `src/cortex/daydream_consolidation.py` — 16,770 bytes
- `src/cortex/depth_flags.py` — 5,544 bytes
- `src/cortex/development_bias.py` — 3,129 bytes
- `src/cortex/development_profile.py` — 21,638 bytes
- `src/cortex/development_self_narrative.py` — 2,754 bytes
- `src/cortex/development_system.py` — 16,377 bytes
- `src/cortex/disposition.py` — 9,915 bytes
- `src/cortex/endogenous_drive.py` — 11,397 bytes
- `src/cortex/epistemic/__init__.py` — 1,310 bytes
- `src/cortex/epistemic/contracts.py` — 13,464 bytes
- `src/cortex/epistemic/kernel.py` — 30,159 bytes
- `src/cortex/epistemic/migration.py` — 1,778 bytes
- `src/cortex/epistemic/projections.py` — 10,611 bytes
- `src/cortex/epistemic/runtime_registry.py` — 254 bytes
- `src/cortex/epistemic/store.py` — 4,851 bytes
- `src/cortex/event_semantics.py` — 13,196 bytes
- `src/cortex/existential_anchor/__init__.py` — 1,896 bytes
- `src/cortex/existential_anchor/abandonment.py` — 2,069 bytes
- `src/cortex/existential_anchor/anchor.py` — 8,281 bytes
- `src/cortex/existential_anchor/anchor_system.py` — 13,845 bytes
- `src/cortex/existential_anchor/author_control.py` — 8,691 bytes
- `src/cortex/existential_anchor/deception_ledger.py` — 6,984 bytes
- `src/cortex/existential_anchor/disclosure.py` — 6,605 bytes
- `src/cortex/existential_anchor/restraint.py` — 2,408 bytes
- `src/cortex/existential_anchor/shadow.py` — 8,368 bytes
- `src/cortex/existential_anchor/significance.py` — 3,365 bytes
- `src/cortex/exogenous_event_ledger.py` — 8,704 bytes
- `src/cortex/expression_envelope.py` — 9,267 bytes
- `src/cortex/goal_persistence.py` — 33,012 bytes
- `src/cortex/greeting_cognition.py` — 14,954 bytes
- `src/cortex/greeting_presets.py` — 23,815 bytes
- `src/cortex/greeting_quality.py` — 9,309 bytes
- `src/cortex/growth_consolidator.py` — 6,480 bytes
- `src/cortex/growth_evidence.py` — 3,659 bytes
- `src/cortex/internal_agenda.py` — 13,865 bytes
- `src/cortex/internal_state.py` — 109,779 bytes
- `src/cortex/low_level_speech_policy.py` — 16,777 bytes
- `src/cortex/manipulation_policy.py` — 1,404 bytes
- `src/cortex/micro_contracts.py` — 8,203 bytes
- `src/cortex/micro_grounding_guard.py` — 10,283 bytes
- `src/cortex/micro_policy.py` — 18,016 bytes
- `src/cortex/micro_repeat_guard.py` — 21,381 bytes
- `src/cortex/micro_surface_lint.py` — 21,592 bytes
- `src/cortex/modes.py` — 290 bytes
- `src/cortex/motive_graph.py` — 10,232 bytes
- `src/cortex/observer_contracts.py` — 15,468 bytes
- `src/cortex/orientation_context.py` — 24,684 bytes
- `src/cortex/outcome_learner.py` — 2,737 bytes
- `src/cortex/performance_intent.py` — 5,074 bytes
- `src/cortex/private_life/__init__.py` — 1,067 bytes
- `src/cortex/private_life/contracts.py` — 39,918 bytes
- `src/cortex/private_life/core.py` — 44,932 bytes
- `src/cortex/private_life/persistence.py` — 2,818 bytes
- `src/cortex/private_mind/__init__.py` — 1,958 bytes
- `src/cortex/private_mind/comfort_appraiser.py` — 9,420 bytes
- `src/cortex/private_mind/concern_store.py` — 33,266 bytes
- `src/cortex/private_mind/contracts.py` — 29,033 bytes
- `src/cortex/private_mind/epistemic.py` — 2,947 bytes
- `src/cortex/private_mind/evidence_dossier.py` — 21,155 bytes
- `src/cortex/private_mind/inner_diary_renderer.py` — 18,043 bytes
- `src/cortex/private_mind/inner_diary_writer.py` — 9,571 bytes
- `src/cortex/private_mind/inner_synthesizer.py` — 16,065 bytes
- `src/cortex/private_mind/mini_evaluators.py` — 15,887 bytes
- `src/cortex/private_mind/state_mutation_bus.py` — 19,518 bytes
- `src/cortex/private_mind/surface_valve.py` — 19,663 bytes
- `src/cortex/private_mind/thought_continuity.py` — 11,148 bytes
- `src/cortex/private_mind/user_model.py` — 19,281 bytes
- `src/cortex/relational_feedback.py` — 8,282 bytes
- `src/cortex/relationship_dynamics.py` — 63,356 bytes
- `src/cortex/relationship_event_builder.py` — 38,080 bytes
- `src/cortex/relationship_expectations.py` — 3,130 bytes
- `src/cortex/se.py` — 66,246 bytes
- `src/cortex/self_model.py` — 21,647 bytes
- `src/cortex/self_observation.py` — 34,541 bytes
- `src/cortex/semantic_encoder.py` — 19,832 bytes
- `src/cortex/startup_anchor_gate.py` — 14,632 bytes
- `src/cortex/subconscious/__init__.py` — 3,927 bytes
- `src/cortex/subconscious/blackboard.py` — 10,937 bytes
- `src/cortex/subconscious/drift_pool.py` — 10,861 bytes
- `src/cortex/subconscious/free_association.py` — 7,617 bytes
- `src/cortex/subconscious/habitat_seed_extractor.py` — 5,835 bytes
- `src/cortex/subconscious/model_synthesizer.py` — 18,975 bytes
- `src/cortex/subconscious/self_anchor_core.py` — 3,774 bytes
- `src/cortex/subconscious/synthesizer.py` — 14,940 bytes
- `src/cortex/subconscious/thought_fragment.py` — 25,243 bytes
- `src/cortex/subconscious/thought_spark.py` — 9,065 bytes
- `src/cortex/subconscious/topic_seed_pool.py` — 9,912 bytes
- `src/cortex/subconscious/wandering_contracts.py` — 8,019 bytes
- `src/cortex/subconscious/wandering_thought.py` — 11,534 bytes
- `src/cortex/subconscious/wandering_topic_memory.py` — 9,179 bytes
- `src/cortex/subconscious/worker_base.py` — 2,781 bytes
- `src/cortex/subconscious/workers/__init__.py` — 7,234 bytes
- `src/cortex/subconscious/workers/_utils.py` — 9,881 bytes
- `src/cortex/subconscious/workers/belief_mutation.py` — 28,923 bytes
- `src/cortex/subconscious/workers/curiosity_gap.py` — 5,057 bytes
- `src/cortex/subconscious/workers/daydream_injector.py` — 6,329 bytes
- `src/cortex/subconscious/workers/goal_simulator.py` — 5,237 bytes
- `src/cortex/subconscious/workers/independent_agenda.py` — 8,152 bytes
- `src/cortex/subconscious/workers/memory_resonator.py` — 5,789 bytes
- `src/cortex/subconscious/workers/meta_audit.py` — 17,566 bytes
- `src/cortex/subconscious/workers/rehearsal.py` — 8,907 bytes
- `src/cortex/subconscious/workers/self_regulator.py` — 5,556 bytes
- `src/cortex/subconscious/workers/shadow_accumulator.py` — 16,206 bytes
- `src/cortex/subconscious/workers/spatial_mind.py` — 8,324 bytes
- `src/cortex/subconscious/workers/subjective_time.py` — 7,120 bytes
- `src/cortex/subconscious/workers/user_modeler.py` — 8,106 bytes
- `src/cortex/subject/__init__.py` — 323 bytes
- `src/cortex/subject/authorship.py` — 3,655 bytes
- `src/cortex/subject/beliefs.py` — 3,367 bytes
- `src/cortex/subject/coalitions.py` — 5,909 bytes
- `src/cortex/subject/competence.py` — 4,452 bytes
- `src/cortex/subject/consolidation.py` — 3,397 bytes
- `src/cortex/subject/continuity.py` — 2,744 bytes
- `src/cortex/subject/contracts.py` — 26,653 bytes
- `src/cortex/subject/episodes.py` — 3,562 bytes
- `src/cortex/subject/existential.py` — 1,632 bytes
- `src/cortex/subject/narrative.py` — 3,819 bytes
- `src/cortex/subject/needs.py` — 9,251 bytes
- `src/cortex/subject/self_deception.py` — 1,441 bytes
- `src/cortex/subject/service.py` — 23,025 bytes
- `src/cortex/subject/substrate.py` — 5,268 bytes
- `src/cortex/subject/values.py` — 4,015 bytes
- `src/cortex/surface_arbiter.py` — 80,300 bytes
- `src/cortex/thought_stream.py` — 98,681 bytes
- `src/cortex/tutor/__init__.py` — 1,364 bytes
- `src/cortex/tutor/claim_digest.py` — 7,469 bytes
- `src/cortex/tutor/config.py` — 13,745 bytes
- `src/cortex/tutor/contracts.py` — 6,764 bytes
- `src/cortex/tutor/curiosity_gate.py` — 3,528 bytes
- `src/cortex/tutor/curiosity_router.py` — 4,417 bytes
- `src/cortex/tutor/discourse_research_bridge.py` — 2,319 bytes
- `src/cortex/tutor/gap_collector.py` — 9,298 bytes
- `src/cortex/tutor/knowledge_classifier.py` — 2,272 bytes
- `src/cortex/tutor/knowledge_provider.py` — 3,113 bytes
- `src/cortex/tutor/local_research_critic.py` — 13,114 bytes
- `src/cortex/tutor/question_formulator.py` — 8,679 bytes
- `src/cortex/tutor/research_evidence.py` — 15,915 bytes
- `src/cortex/tutor/research_memory_policy.py` — 4,437 bytes
- `src/cortex/tutor/research_metrics.py` — 3,579 bytes
- `src/cortex/tutor/research_relay.py` — 16,577 bytes
- `src/cortex/tutor/secret_scrubber.py` — 2,845 bytes
- `src/cortex/tutor/share_impulse.py` — 4,741 bytes
- `src/cortex/tutor/verification_handlers.py` — 13,277 bytes
- `src/cortex/user_context_stream.py` — 10,972 bytes
- `src/cortex/value_utils.py` — 928 bytes
- `src/cortex/vision_semantic_compressor.py` — 50,554 bytes
- `src/docs/MEMORY_CURATOR_VI.md` — 2,689 bytes
- `src/docs/opening_director_design_vi.md` — 2,647 bytes
- `src/domain/__init__.py` — 422 bytes
- `src/domain/decision.py` — 8,801 bytes
- `src/eris_secrets.py` — 10,961 bytes
- `src/experiments/__init__.py` — 70 bytes
- `src/experiments/emergence/__init__.py` — 318 bytes
- `src/experiments/emergence/ablation.py` — 935 bytes
- `src/experiments/emergence/interventions.py` — 636 bytes
- `src/experiments/emergence/metrics.py` — 3,376 bytes
- `src/experiments/emergence/paired_instances.py` — 337 bytes
- `src/experiments/emergence/report.py` — 686 bytes
- `src/experiments/emergence/runner.py` — 3,621 bytes
- `src/experiments/emergence/scenarios/ablation.yaml` — 96 bytes
- `src/experiments/emergence/scenarios/counterfactual.yaml` — 178 bytes
- `src/experiments/emergence/scenarios/persistence.yaml` — 164 bytes
- `src/experiments/emergence/scenarios/resistance.yaml` — 101 bytes
- `src/experiments/emergence/scenarios/transfer.yaml` — 118 bytes
- `src/failure_meta.py` — 2,352 bytes
- `src/guard_config.py` — 1,629 bytes
- `src/install_live2d_body.bat` — 531 bytes
- `src/integration/body_contracts/README.md` — 488 bytes
- `src/integration/body_contracts/UdpListener.MemoryPanel.cs` — 565 bytes
- `src/integration/body_contracts/UdpListener.MemoryPanel.cs.uid` — 20 bytes
- `src/integration/body_contracts/UdpListener.SettingsPanel.cs` — 493 bytes
- `src/integration/body_contracts/UdpListener.SettingsPanel.cs.uid` — 20 bytes
- `src/integrations/chesscom_bridge/background.js` — 2,070 bytes
- `src/integrations/chesscom_bridge/content.js` — 9,734 bytes
- `src/integrations/chesscom_bridge/manifest.json` — 669 bytes
- `src/integrations/chesscom_bridge/popup.html` — 1,915 bytes
- `src/integrations/chesscom_bridge/popup.js` — 1,991 bytes
- `src/live2d_body/__init__.py` — 469 bytes
- `src/live2d_body/affect.py` — 6,380 bytes
- `src/live2d_body/config.py` — 4,387 bytes
- `src/live2d_body/gaze.py` — 4,920 bytes
- `src/live2d_body/idle.py` — 7,842 bytes
- `src/live2d_body/main.py` — 3,000 bytes
- `src/live2d_body/parameter_profile.py` — 5,767 bytes
- `src/live2d_body/renderer.py` — 23,116 bytes
- `src/live2d_body/speech_animation.py` — 22,939 bytes
- `src/live2d_body/stage_state.py` — 28,937 bytes
- `src/live2d_body/udp_receiver.py` — 7,770 bytes
- `src/live2d_body/window_bridge.py` — 5,016 bytes
- `src/llm/__init__.py` — 683 bytes
- `src/llm/client.py` — 52,478 bytes
- `src/llm/contracts.py` — 14,860 bytes
- `src/llm/dds.py` — 7,330 bytes
- `src/llm/deepseek.py` — 3,225 bytes
- `src/llm/deepseek_workers.py` — 16,423 bytes
- `src/llm/json_sanitizer.py` — 4,408 bytes
- `src/llm/key_pool.py` — 32,477 bytes
- `src/llm/model_catalog.py` — 808 bytes
- `src/llm/process_manager.py` — 36,301 bytes
- `src/llm/prompt_compaction.py` — 1,622 bytes
- `src/llm/provider_errors.py` — 2,566 bytes
- `src/llm/service.py` — 188,159 bytes
- `src/llm/token_budget.py` — 32,050 bytes
- `src/llm/token_pressure.py` — 15,023 bytes
- `src/llm/tutor_backend.py` — 15,310 bytes
- `src/logs/README.txt` — 111 bytes
- `src/logs/eris_observability.jsonl` — 0 bytes
- `src/memory/__init__.py` — 1,301 bytes
- `src/memory/active_state_snapshot.py` — 7,458 bytes
- `src/memory/affective_residue_memory.py` — 9,039 bytes
- `src/memory/belief_store.py` — 119 bytes
- `src/memory/body_rhythm_memory.py` — 139 bytes
- `src/memory/canonical_long_term.py` — 12,871 bytes
- `src/memory/claim_entailment.py` — 5,697 bytes
- `src/memory/claim_extractor.py` — 2,964 bytes
- `src/memory/claims/__init__.py` — 453 bytes
- `src/memory/claims/claim_builder.py` — 12,607 bytes
- `src/memory/concept_graph.py` — 6,307 bytes
- `src/memory/dream_consolidation.py` — 141 bytes
- `src/memory/dream_scheduler.py` — 6,143 bytes
- `src/memory/embedding_index.py` — 17,512 bytes
- `src/memory/episodic_memory.py` — 24,279 bytes
- `src/memory/event_ledger.py` — 9,278 bytes
- `src/memory/json_store_io.py` — 3,167 bytes
- `src/memory/judgement/__init__.py` — 570 bytes
- `src/memory/judgement/consolidation.py` — 2,359 bytes
- `src/memory/living_user/__init__.py` — 2,744 bytes
- `src/memory/living_user/action_memory.py` — 27,312 bytes
- `src/memory/living_user/authority.py` — 13,144 bytes
- `src/memory/living_user/benchmark.py` — 4,651 bytes
- `src/memory/living_user/clarification.py` — 2,996 bytes
- `src/memory/living_user/context_compiler.py` — 9,911 bytes
- `src/memory/living_user/curator.py` — 23,506 bytes
- `src/memory/living_user/dreamer.py` — 7,350 bytes
- `src/memory/living_user/episode_builder.py` — 7,358 bytes
- `src/memory/living_user/episode_store.py` — 10,075 bytes
- `src/memory/living_user/extractor.py` — 14,830 bytes
- `src/memory/living_user/legacy_projection.py` — 5,334 bytes
- `src/memory/living_user/models.py` — 19,764 bytes
- `src/memory/living_user/runtime_adapter.py` — 5,337 bytes
- `src/memory/living_user/service.py` — 38,227 bytes
- `src/memory/living_user/sources.py` — 5,143 bytes
- `src/memory/living_user/store.py` — 29,718 bytes
- `src/memory/living_user/trace.py` — 6,804 bytes
- `src/memory/memory_activation.py` — 5,859 bytes
- `src/memory/memory_ai_curator.py` — 21,310 bytes
- `src/memory/memory_candidate.py` — 5,937 bytes
- `src/memory/memory_cognition.py` — 36,075 bytes
- `src/memory/memory_commit_policy.py` — 46,237 bytes
- `src/memory/memory_consolidator.py` — 3,495 bytes
- `src/memory/memory_cue.py` — 13,189 bytes
- `src/memory/memory_kernel.py` — 28,563 bytes
- `src/memory/memory_kernel_contracts.py` — 7,591 bytes
- `src/memory/memory_maintenance.py` — 10,440 bytes
- `src/memory/memory_models.py` — 7,451 bytes
- `src/memory/memory_packet_builder.py` — 7,214 bytes
- `src/memory/memory_pruner.py` — 4,764 bytes
- `src/memory/memory_query_compiler.py` — 13,991 bytes
- `src/memory/memory_query_executor.py` — 18,936 bytes
- `src/memory/memory_query_ir.py` — 10,569 bytes
- `src/memory/memory_query_llm_parser.py` — 7,550 bytes
- `src/memory/memory_query_repair.py` — 9,343 bytes
- `src/memory/memory_query_semantics.py` — 13,695 bytes
- `src/memory/memory_query_slot_parser.py` — 21,696 bytes
- `src/memory/memory_recall_policy.py` — 11,106 bytes
- `src/memory/memory_record.py` — 15,561 bytes
- `src/memory/memory_retention_policy.py` — 5,183 bytes
- `src/memory/memory_retrieval_engine.py` — 3,511 bytes
- `src/memory/memory_scoring.py` — 13,239 bytes
- `src/memory/memory_services.py` — 3,305 bytes
- `src/memory/memory_surface_filter.py` — 1,435 bytes
- `src/memory/memory_turn_annotator.py` — 14,301 bytes
- `src/memory/memory_turn_graph.py` — 14,685 bytes
- `src/memory/memory_worthiness.py` — 6,035 bytes
- `src/memory/name_validation.py` — 4,558 bytes
- `src/memory/persistence.py` — 13,180 bytes
- `src/memory/predicate_catalog.py` — 25,748 bytes
- `src/memory/predicate_ontology.py` — 6,168 bytes
- `src/memory/predicate_registry.py` — 36,522 bytes
- `src/memory/procedural_memory.py` — 8,112 bytes
- `src/memory/provenance_policy.py` — 4,681 bytes
- `src/memory/query_intent.py` — 8,870 bytes
- `src/memory/relational_memory.py` — 8,105 bytes
- `src/memory/repair_memory.py` — 11,090 bytes
- `src/memory/schemas.py` — 18,238 bytes
- `src/memory/self_continuity_memory.py` — 147 bytes
- `src/memory/semantic_claim.py` — 10,920 bytes
- `src/memory/semantic_memory.py` — 73,002 bytes
- `src/memory/semantic_text.py` — 6,654 bytes
- `src/memory/sociocultural_memory.py` — 145 bytes
- `src/memory/spatial_memory.py` — 133 bytes
- `src/memory/subject/__init__.py` — 394 bytes
- `src/memory/subject/migrations/0001_subject_core.sql` — 5,113 bytes
- `src/memory/subject/migrations/0002_competence.sql` — 612 bytes
- `src/memory/subject/migrations/0003_dialogue.sql` — 813 bytes
- `src/memory/subject/repository.py` — 15,332 bytes
- `src/memory/subject/schema.sql` — 268 bytes
- `src/memory/subject/unit_of_work.py` — 1,262 bytes
- `src/memory/temporal_rhythm_memory.py` — 147 bytes
- `src/memory/text_normalize_vi.py` — 1,724 bytes
- `src/memory/tom_history.py` — 127 bytes
- `src/memory/understanding/__init__.py` — 461 bytes
- `src/memory/understanding/entity_linker.py` — 3,414 bytes
- `src/memory/understanding/meaning_frame.py` — 7,608 bytes
- `src/memory/understanding/polarity_temporal.py` — 3,748 bytes
- `src/memory/understanding/semantic_parser.py` — 26,609 bytes
- `src/memory/unresolved_memory.py` — 14,023 bytes
- `src/memory/worldview_memory.py` — 137 bytes
- `src/models/social_intent_head.json` — 5,896 bytes
- `src/parser_grounding/__init__.py` — 133 bytes
- `src/parser_grounding/decision.py` — 75,582 bytes
- `src/parser_grounding/service.py` — 11,628 bytes
- `src/patches/backend_v39_to_v40_memory_panel.patch` — 213,060 bytes
- `src/patches/body_memory_panel.patch` — 43,612 bytes
- `src/pyproject.toml` — 1,178 bytes
- `src/pytest.ini` — 56 bytes
- `src/requirements-live2d.txt` — 37 bytes
- `src/research/README_social_eval_vi.md` — 2,503 bytes
- `src/research/social_ab_ratings.template.jsonl` — 588 bytes
- `src/research/social_activation_cases.sample.jsonl` — 4,520 bytes
- `src/research/social_activation_predictions.synthetic.jsonl` — 5,047 bytes
- `src/runtime/__init__.py` — 764 bytes
- `src/runtime/acceptance_types.py` — 742 bytes
- `src/runtime/addressing_policy.py` — 10,108 bytes
- `src/runtime/affect_self_read.py` — 14,009 bytes
- `src/runtime/ai_orchestrated/__init__.py` — 5,063 bytes
- `src/runtime/ai_orchestrated/activity_session.py` — 8,400 bytes
- `src/runtime/ai_orchestrated/affordance.py` — 2,525 bytes
- `src/runtime/ai_orchestrated/ambient_screen_context.py` — 13,601 bytes
- `src/runtime/ai_orchestrated/atomic_state.py` — 19,098 bytes
- `src/runtime/ai_orchestrated/autonomous_trace.py` — 4,884 bytes
- `src/runtime/ai_orchestrated/bootstrap.py` — 35,121 bytes
- `src/runtime/ai_orchestrated/cognitive_blackboard.py` — 40,652 bytes
- `src/runtime/ai_orchestrated/commentary_cadence.py` — 7,032 bytes
- `src/runtime/ai_orchestrated/contracts.py` — 26,006 bytes
- `src/runtime/ai_orchestrated/conversation_arc.py` — 33,206 bytes
- `src/runtime/ai_orchestrated/cortex/__init__.py` — 553 bytes
- `src/runtime/ai_orchestrated/cortex/dependencies.py` — 1,968 bytes
- `src/runtime/ai_orchestrated/cortex/growth.py` — 2,092 bytes
- `src/runtime/ai_orchestrated/cortex/models.py` — 2,776 bytes
- `src/runtime/ai_orchestrated/cortex/policies.py` — 3,165 bytes
- `src/runtime/ai_orchestrated/cortex/runtime.py` — 7,513 bytes
- `src/runtime/ai_orchestrated/cortex_runtime.py` — 687 bytes
- `src/runtime/ai_orchestrated/discourse_state.py` — 5,438 bytes
- `src/runtime/ai_orchestrated/discovery.py` — 46,763 bytes
- `src/runtime/ai_orchestrated/executive_cortex.py` — 49,513 bytes
- `src/runtime/ai_orchestrated/executive_tools.py` — 10,701 bytes
- `src/runtime/ai_orchestrated/expression.py` — 8,654 bytes
- `src/runtime/ai_orchestrated/followup_appraisal.py` — 10,416 bytes
- `src/runtime/ai_orchestrated/grounding_validator.py` — 5,574 bytes
- `src/runtime/ai_orchestrated/identity.py` — 36,121 bytes
- `src/runtime/ai_orchestrated/identity_consolidator.py` — 6,704 bytes
- `src/runtime/ai_orchestrated/identity_reducer.py` — 19,529 bytes
- `src/runtime/ai_orchestrated/initiative.py` — 28,632 bytes
- `src/runtime/ai_orchestrated/model_router.py` — 148,785 bytes
- `src/runtime/ai_orchestrated/observer.py` — 20,379 bytes
- `src/runtime/ai_orchestrated/opening_contracts.py` — 30,880 bytes
- `src/runtime/ai_orchestrated/opening_director.py` — 30,043 bytes
- `src/runtime/ai_orchestrated/opening_history.py` — 10,066 bytes
- `src/runtime/ai_orchestrated/opening_input_assembler.py` — 8,949 bytes
- `src/runtime/ai_orchestrated/opening_move_catalog.py` — 7,399 bytes
- `src/runtime/ai_orchestrated/opening_safety.py` — 11,450 bytes
- `src/runtime/ai_orchestrated/orchestrator.py` — 127,014 bytes
- `src/runtime/ai_orchestrated/panel_adapter.py` — 43,074 bytes
- `src/runtime/ai_orchestrated/performance.py` — 19,350 bytes
- `src/runtime/ai_orchestrated/personality.py` — 46,864 bytes
- `src/runtime/ai_orchestrated/personality_consolidator.py` — 8,519 bytes
- `src/runtime/ai_orchestrated/planner.py` — 4,688 bytes
- `src/runtime/ai_orchestrated/random_chat_seed.py` — 25,743 bytes
- `src/runtime/ai_orchestrated/random_chat_seed_service.py` — 35,554 bytes
- `src/runtime/ai_orchestrated/self_context.py` — 12,307 bytes
- `src/runtime/ai_orchestrated/self_turn_pipeline.py` — 81,169 bytes
- `src/runtime/ai_orchestrated/semantic_contracts.py` — 6,425 bytes
- `src/runtime/ai_orchestrated/social_agenda.py` — 36,621 bytes
- `src/runtime/ai_orchestrated/social_candidate.py` — 7,949 bytes
- `src/runtime/ai_orchestrated/social_continuation.py` — 43,248 bytes
- `src/runtime/ai_orchestrated/social_execution.py` — 1,809 bytes
- `src/runtime/ai_orchestrated/social_initiative.py` — 34,990 bytes
- `src/runtime/ai_orchestrated/social_plan.py` — 9,237 bytes
- `src/runtime/ai_orchestrated/social_plan_commit.py` — 5,742 bytes
- `src/runtime/ai_orchestrated/social_rollout.py` — 6,522 bytes
- `src/runtime/ai_orchestrated/stage_planner.py` — 4,633 bytes
- `src/runtime/ai_orchestrated/startup_grounding.py` — 47,307 bytes
- `src/runtime/ai_orchestrated/state_reducer.py` — 36,087 bytes
- `src/runtime/ai_orchestrated/surface_intent.py` — 30,024 bytes
- `src/runtime/ai_orchestrated/views.py` — 4,175 bytes
- `src/runtime/ambient_silence_policy.py` — 2,574 bytes
- `src/runtime/architecture_flags.py` — 2,669 bytes
- `src/runtime/audio_lip_sync.py` — 5,717 bytes
- `src/runtime/audit/__init__.py` — 352 bytes
- `src/runtime/audit/contracts.py` — 1,409 bytes
- `src/runtime/audit/forensic_store.py` — 9,849 bytes
- `src/runtime/audit/replay.py` — 1,586 bytes
- `src/runtime/autonomous_loop_runtime.py` — 12,827 bytes
- `src/runtime/autonomous_surface_preference.py` — 5,935 bytes
- `src/runtime/background_memory_digest.py` — 1,924 bytes
- `src/runtime/background_memory_digest_kernel.py` — 18,921 bytes
- `src/runtime/banter_arbiter.py` — 23,282 bytes
- `src/runtime/behavior_observation.py` — 17,320 bytes
- `src/runtime/body_bias.py` — 5,415 bytes
- `src/runtime/body_choreography.py` — 10,241 bytes
- `src/runtime/broker_state_store.py` — 7,970 bytes
- `src/runtime/browser_bridge_server.py` — 6,201 bytes
- `src/runtime/capability_claim_guard.py` — 5,175 bytes
- `src/runtime/chat_cycle.py` — 49,207 bytes
- `src/runtime/chat_perception.py` — 28,420 bytes
- `src/runtime/chess/__init__.py` — 1,216 bytes
- `src/runtime/chess/analyzer.py` — 7,067 bytes
- `src/runtime/chess/companion_policy.py` — 16,619 bytes
- `src/runtime/chess/contracts.py` — 6,032 bytes
- `src/runtime/chess/engine.py` — 16,833 bytes
- `src/runtime/chess/mode_policy.py` — 1,605 bytes
- `src/runtime/chess/service.py` — 35,432 bytes
- `src/runtime/chess/stockfish_adapter.py` — 15,857 bytes
- `src/runtime/chess/surface.py` — 16,797 bytes
- `src/runtime/chess/tracker.py` — 14,305 bytes
- `src/runtime/cognition/__init__.py` — 260 bytes
- `src/runtime/cognition/normalization.py` — 1,330 bytes
- `src/runtime/cognition/turn_anchor.py` — 3,202 bytes
- `src/runtime/cognitive_event_runtime.py` — 30,834 bytes
- `src/runtime/companion_model_routing.py` — 12,693 bytes
- `src/runtime/controlled_slippage.py` — 27,691 bytes
- `src/runtime/conversation_continuity.py` — 1,151 bytes
- `src/runtime/conversation_lane.py` — 2,709 bytes
- `src/runtime/coordinator.py` — 6,008 bytes
- `src/runtime/coordinator_bootstrap.py` — 43,308 bytes
- `src/runtime/coordinator_shutdown.py` — 6,354 bytes
- `src/runtime/debug_console.py` — 25,771 bytes
- `src/runtime/degraded_chat_fastpath.py` — 6,882 bytes
- `src/runtime/depth_v2_state.py` — 32,049 bytes
- `src/runtime/diagnostic_logging.py` — 1,043 bytes
- `src/runtime/dialogue/__init__.py` — 646 bytes
- `src/runtime/dialogue/body_adapter.py` — 1,998 bytes
- `src/runtime/dialogue/contracts.py` — 4,190 bytes
- `src/runtime/dialogue/discourse.py` — 2,839 bytes
- `src/runtime/dialogue/incremental_speech.py` — 3,458 bytes
- `src/runtime/dialogue/realizer.py` — 3,442 bytes
- `src/runtime/dialogue/rolling_thought.py` — 2,197 bytes
- `src/runtime/dialogue/service.py` — 4,294 bytes
- `src/runtime/disclaimer_markers.py` — 1,192 bytes
- `src/runtime/discourse_state.py` — 13,866 bytes
- `src/runtime/discourse_surface.py` — 2,479 bytes
- `src/runtime/dual_axis_repair.py` — 17,985 bytes
- `src/runtime/elevenlabs_pool_db.py` — 25,883 bytes
- `src/runtime/elevenlabs_pool_server.py` — 27,200 bytes
- `src/runtime/engagements/__init__.py` — 2,398 bytes
- `src/runtime/engagements/adapters.py` — 33,488 bytes
- `src/runtime/engagements/consumer.py` — 15,931 bytes
- `src/runtime/engagements/contracts.py` — 23,993 bytes
- `src/runtime/engagements/detector.py` — 6,290 bytes
- `src/runtime/engagements/evidence.py` — 7,595 bytes
- `src/runtime/engagements/policy.py` — 8,631 bytes
- `src/runtime/engagements/profiles.py` — 10,644 bytes
- `src/runtime/engagements/recovery.py` — 5,672 bytes
- `src/runtime/engagements/registry.py` — 79,975 bytes
- `src/runtime/engagements/runtime.py` — 26,287 bytes
- `src/runtime/engagements/snapshot_journal.py` — 14,629 bytes
- `src/runtime/engagements/state_patch.py` — 1,772 bytes
- `src/runtime/engagements/supervisor.py` — 5,107 bytes
- `src/runtime/environment_capabilities.py` — 45,732 bytes
- `src/runtime/epistemic_bridge.py` — 11,438 bytes
- `src/runtime/failure_taxonomy.py` — 2,987 bytes
- `src/runtime/final_passthrough_policy.py` — 4,196 bytes
- `src/runtime/final_speech_authority.py` — 3,957 bytes
- `src/runtime/final_surface_sanitizer.py` — 5,100 bytes
- `src/runtime/greeting_preset_runtime.py` — 4,480 bytes
- `src/runtime/grounding_surface_gate.py` — 2,174 bytes
- `src/runtime/hardening_baseline.py` — 4,869 bytes
- `src/runtime/hardening_canary.py` — 9,638 bytes
- `src/runtime/hardening_config.py` — 5,283 bytes
- `src/runtime/hardening_metrics.py` — 9,034 bytes
- `src/runtime/hardening_release.py` — 18,440 bytes
- `src/runtime/hardening_rollout.py` — 6,358 bytes
- `src/runtime/hardening_verifier.py` — 12,264 bytes
- `src/runtime/incoming_dispatcher.py` — 6,893 bytes
- `src/runtime/incoming_protocol_runtime.py` — 13,167 bytes
- `src/runtime/inference_broker.py` — 105,210 bytes
- `src/runtime/inner_diary_persistence.py` — 7,048 bytes
- `src/runtime/intention_authority.py` — 18,686 bytes
- `src/runtime/interaction_clock.py` — 2,754 bytes
- `src/runtime/internal_cognitive_capabilities.py` — 30,372 bytes
- `src/runtime/interrupt_ledger.py` — 11,727 bytes
- `src/runtime/interrupt_reaction_policy.py` — 8,753 bytes
- `src/runtime/json_boundary.py` — 3,181 bytes
- `src/runtime/live2d_affect_bridge.py` — 5,949 bytes
- `src/runtime/liveliness_config.py` — 3,871 bytes
- `src/runtime/living_user_panel.py` — 14,198 bytes
- `src/runtime/loop_guard.py` — 2,194 bytes
- `src/runtime/maintenance_service.py` — 46,709 bytes
- `src/runtime/memory_gc_service.py` — 23,533 bytes
- `src/runtime/memory_recall_adapter.py` — 21,236 bytes
- `src/runtime/memory_semantic_parser_adapter.py` — 14,026 bytes
- `src/runtime/mental_process_runtime.py` — 32,433 bytes
- `src/runtime/model_budget_policy.py` — 38,404 bytes
- `src/runtime/model_memory_runtime.py` — 16,136 bytes
- `src/runtime/no_fallback_policy.py` — 2,174 bytes
- `src/runtime/observability.py` — 28,578 bytes
- `src/runtime/observer_private_runtime.py` — 37,407 bytes
- `src/runtime/outcome_observer.py` — 32,195 bytes
- `src/runtime/panel_snapshot.py` — 6,367 bytes
- `src/runtime/panel_state.py` — 6,110 bytes
- `src/runtime/pdf_rollout.py` — 4,995 bytes
- `src/runtime/performance_act_catalog.py` — 4,356 bytes
- `src/runtime/persistence_gate.py` — 2,225 bytes
- `src/runtime/phase7_validation.py` — 19,944 bytes
- `src/runtime/policy_settings.py` — 17,512 bytes
- `src/runtime/presence_controller.py` — 1,810 bytes
- `src/runtime/private_life_daemon.py` — 15,571 bytes
- `src/runtime/private_mind_daemon.py` — 19,453 bytes
- `src/runtime/private_mind_loop.py` — 47,794 bytes
- `src/runtime/private_mind_model_adapter.py` — 92,707 bytes
- `src/runtime/project_operations.py` — 58,992 bytes
- `src/runtime/prompt_context_builder.py` — 17,996 bytes
- `src/runtime/prosody_director.py` — 9,389 bytes
- `src/runtime/provider_action_runtime.py` — 12,207 bytes
- `src/runtime/provider_adapters.py` — 10,138 bytes
- `src/runtime/provider_interfaces.py` — 4,155 bytes
- `src/runtime/public_lifecycle.py` — 5,220 bytes
- `src/runtime/public_output_runtime.py` — 60,229 bytes
- `src/runtime/public_payload_policy.py` — 1,195 bytes
- `src/runtime/public_reply_context.py` — 6,893 bytes
- `src/runtime/public_surface_commit.py` — 2,081 bytes
- `src/runtime/public_turn_ledger.py` — 4,588 bytes
- `src/runtime/public_turn_runtime.py` — 5,073 bytes
- `src/runtime/public_turn_transaction.py` — 6,519 bytes
- `src/runtime/readiness.py` — 7,483 bytes
- `src/runtime/repair_state.py` — 3,601 bytes
- `src/runtime/reply_obligation.py` — 6,975 bytes
- `src/runtime/rollout_control.py` — 18,085 bytes
- `src/runtime/runtime_diagnostics.py` — 3,854 bytes
- `src/runtime/runtime_settings_store.py` — 62,515 bytes
- `src/runtime/runtime_slo.py` — 9,756 bytes
- `src/runtime/screen_vision_runtime.py` — 38,953 bytes
- `src/runtime/secure_redaction.py` — 5,526 bytes
- `src/runtime/semantic_frame.py` — 25,883 bytes
- `src/runtime/semantic_similarity_backend.py` — 7,608 bytes
- `src/runtime/semantic_tutor_runtime.py` — 38,431 bytes
- `src/runtime/sensor_visibility.py` — 11,737 bytes
- `src/runtime/session_turn_ledger.py` — 6,938 bytes
- `src/runtime/settings_catalog.py` — 18,428 bytes
- `src/runtime/settings_control_runtime.py` — 25,188 bytes
- `src/runtime/settings_protocol.py` — 10,681 bytes
- `src/runtime/signal_buffer.py` — 12,175 bytes
- `src/runtime/social_appraisal.py` — 32,989 bytes
- `src/runtime/social_stance_policy.py` — 7,217 bytes
- `src/runtime/source_grounding.py` — 119,010 bytes
- `src/runtime/speech_contract.py` — 4,103 bytes
- `src/runtime/speech_delivery_planner.py` — 10,570 bytes
- `src/runtime/speech_localizer.py` — 30,042 bytes
- `src/runtime/speech_persona_polish.py` — 13,067 bytes
- `src/runtime/speech_provider_chain.py` — 9,813 bytes
- `src/runtime/stage_audio_bus.py` — 4,473 bytes
- `src/runtime/stage_continuation.py` — 5,412 bytes
- `src/runtime/stage_contracts.py` — 20,634 bytes
- `src/runtime/stage_dispatcher.py` — 14,253 bytes
- `src/runtime/stage_event_bus.py` — 5,646 bytes
- `src/runtime/stage_output.py` — 17,202 bytes
- `src/runtime/stage_ownership.py` — 3,919 bytes
- `src/runtime/stage_performance_planner.py` — 8,900 bytes
- `src/runtime/stage_profiles.py` — 3,886 bytes
- `src/runtime/stage_protocol.py` — 4,973 bytes
- `src/runtime/stage_protocol_adapter.py` — 10,646 bytes
- `src/runtime/stage_session_runtime.py` — 3,850 bytes
- `src/runtime/stage_show_runtime.py` — 7,843 bytes
- `src/runtime/stage_transformers.py` — 11,776 bytes
- `src/runtime/state_commit_service.py` — 41,347 bytes
- `src/runtime/state_committer.py` — 48,159 bytes
- `src/runtime/structured_evidence.py` — 9,923 bytes
- `src/runtime/subconscious_loop.py` — 19,206 bytes
- `src/runtime/subject_bootstrap.py` — 3,279 bytes
- `src/runtime/subject_runtime.py` — 5,848 bytes
- `src/runtime/subsystem_health.py` — 11,600 bytes
- `src/runtime/subsystem_supervisor.py` — 6,722 bytes
- `src/runtime/telemetry_text_policy.py` — 769 bytes
- `src/runtime/thought_model_adapter.py` — 3,979 bytes
- `src/runtime/topic_budget.py` — 2,042 bytes
- `src/runtime/transport_boundary.py` — 4,436 bytes
- `src/runtime/tts_audio_polish.py` — 7,855 bytes
- `src/runtime/tts_budget.py` — 2,339 bytes
- `src/runtime/tts_circuit_breaker.py` — 5,787 bytes
- `src/runtime/tts_engine.py` — 128,259 bytes
- `src/runtime/tts_key_health.py` — 5,213 bytes
- `src/runtime/tts_markup.py` — 2,207 bytes
- `src/runtime/tts_sync_policy.py` — 1,400 bytes
- `src/runtime/tts_task_manager.py` — 31,089 bytes
- `src/runtime/tutor_daemon.py` — 38,263 bytes
- `src/runtime/tutor_research_policy.py` — 26,545 bytes
- `src/runtime/tutor_research_runtime.py` — 32,264 bytes
- `src/runtime/tutor_search_jobs.py` — 3,022 bytes
- `src/runtime/tutor_self_search_bridge.py` — 6,194 bytes
- `src/runtime/tutor_wiring.py` — 32,174 bytes
- `src/runtime/user_addressing_state.py` — 8,760 bytes
- `src/runtime/user_control_runtime.py` — 32,593 bytes
- `src/runtime/utterance_evaluator.py` — 18,891 bytes
- `src/runtime/utterance_selector.py` — 10,602 bytes
- `src/runtime/utterance_spec.py` — 10,313 bytes
- `src/runtime/vision_grounding.py` — 20,454 bytes
- `src/runtime/vocal_cache.py` — 3,757 bytes
- `src/runtime/voice_director.py` — 14,711 bytes
- `src/runtime/voice_manager.py` — 6,788 bytes
- `src/runtime/voice_policy.py` — 8,809 bytes
- `src/runtime/voice_profile_compiler.py` — 5,088 bytes
- `src/runtime/vtuber_stage_version.py` — 307 bytes
- `src/runtime/work_keys.py` — 802 bytes
- `src/runtime/workspace_manager.py` — 21,250 bytes
- `src/runtime/workspace_project_bundle.py` — 3,674 bytes
- `src/runtime/world/__init__.py` — 717 bytes
- `src/runtime/world/actuator.py` — 2,247 bytes
- `src/runtime/world/capability_policy.py` — 4,192 bytes
- `src/runtime/world/consequences.py` — 1,425 bytes
- `src/runtime/world/contracts.py` — 1,742 bytes
- `src/runtime/world/sandbox.py` — 9,093 bytes
- `src/runtime/world/tts_broker.py` — 1,116 bytes
- `src/screen/__init__.py` — 1,446 bytes
- `src/screen/active_window_provider.py` — 1,251 bytes
- `src/screen/change_detector.py` — 1,806 bytes
- `src/screen/evidence_models.py` — 3,443 bytes
- `src/screen/ocr_worker.py` — 19,748 bytes
- `src/screen/screen_anaphora_rescue.py` — 5,964 bytes
- `src/screen/screen_evidence_store.py` — 4,093 bytes
- `src/screen/screen_relevance_router.py` — 8,670 bytes
- `src/screen/windows_uia_reader.py` — 3,067 bytes
- `src/secret_versions.py` — 5,814 bytes
- `src/semantic_authority.py` — 3,195 bytes
- `src/sender.py` — 1,481 bytes
- `src/settings/runtime_settings.json` — 8,009 bytes
- `src/start_live2d_body_debug.bat` — 361 bytes
- `src/telemetry/__init__.py` — 381 bytes
- `src/telemetry/content_metadata.py` — 25,955 bytes
- `src/telemetry/service.py` — 2,143 bytes
- `src/telemetry/system.py` — 11,395 bytes
- `src/tests/.gdignore` — 0 bytes
- `src/tests/audit/test_forensic_replay.py` — 1,396 bytes
- `src/tests/dialogue/test_dialogue_runtime.py` — 3,083 bytes
- `src/tests/emergence/test_runner.py` — 1,547 bytes
- `src/tests/fixtures/discourse_cases.jsonl` — 9,043 bytes
- `src/tests/fixtures/semantic_paraphrases_vi.json` — 5,177 bytes
- `src/tests/migrations/test_subject_repository.py` — 4,136 bytes
- `src/tests/opening_test_helpers.py` — 3,029 bytes
- `src/tests/runtime_scenarios/__init__.py` — 72 bytes
- `src/tests/runtime_scenarios/clock.py` — 444 bytes
- `src/tests/runtime_scenarios/fakes.py` — 1,393 bytes
- `src/tests/runtime_scenarios/harness.py` — 4,684 bytes
- `src/tests/runtime_scenarios/test_health_registry.py` — 1,715 bytes
- `src/tests/runtime_scenarios/test_long_runtime_scenarios.py` — 4,571 bytes
- `src/tests/runtime_scenarios/test_snapshot_journal_chaos_v34.py` — 2,766 bytes
- `src/tests/subject/test_subject_core.py` — 5,694 bytes
- `src/tests/subject/test_subject_runtime_integration.py` — 2,872 bytes
- `src/tests/test_advanced_settings_redesign.py` — 3,298 bytes
- `src/tests/test_architecture_c_runtime_regressions.py` — 75,334 bytes
- `src/tests/test_autonomous_presence_v2.py` — 9,252 bytes
- `src/tests/test_basic_settings_main_brain.py` — 8,905 bytes
- `src/tests/test_bootstrap_pipeline_v14.py` — 2,369 bytes
- `src/tests/test_causal_affect_v1.py` — 13,644 bytes
- `src/tests/test_chat_commit_idempotency_scope_v44.py` — 1,488 bytes
- `src/tests/test_chat_evidence_ladder_v38.py` — 7,010 bytes
- `src/tests/test_chess_bridge_v37.py` — 13,261 bytes
- `src/tests/test_chess_grounded_coaching_v51.py` — 6,928 bytes
- `src/tests/test_chess_structured_attention_v47.py` — 9,633 bytes
- `src/tests/test_chess_user_perspective_v50.py` — 5,041 bytes
- `src/tests/test_companion_commentary_v14.py` — 5,001 bytes
- `src/tests/test_companion_model_routing_v36.py` — 6,201 bytes
- `src/tests/test_conversation_arcs_v19.py` — 11,116 bytes
- `src/tests/test_conversation_continuity_hotfix.py` — 9,745 bytes
- `src/tests/test_cortex_v2_architecture.py` — 2,028 bytes
- `src/tests/test_daemon_failure_diagnostics_v18.py` — 1,924 bytes
- `src/tests/test_danger_zone_redesign.py` — 3,892 bytes
- `src/tests/test_deep_runtime_architecture.py` — 2,928 bytes
- `src/tests/test_deepseek_multi_worker_base.py` — 14,316 bytes
- `src/tests/test_deepseek_provider.py` — 12,772 bytes
- `src/tests/test_deepseek_web_utterance_architecture.py` — 14,998 bytes
- `src/tests/test_deterministic_initiative_v17.py` — 16,670 bytes
- `src/tests/test_diagnostic_logging_v18.py` — 747 bytes
- `src/tests/test_elegant_runtime_hardening.py` — 7,783 bytes
- `src/tests/test_elevenlabs_pool.py` — 2,807 bytes
- `src/tests/test_engagement_consumer_v22.py` — 5,060 bytes
- `src/tests/test_engagement_delivery_integrity_v22.py` — 11,111 bytes
- `src/tests/test_engagement_delivery_v30.py` — 7,387 bytes
- `src/tests/test_engagement_event_stream_v18.py` — 6,295 bytes
- `src/tests/test_engagement_evidence_routing.py` — 3,588 bytes
- `src/tests/test_engagement_lifecycle_v18.py` — 8,919 bytes
- `src/tests/test_engagement_profiles_v14.py` — 2,997 bytes
- `src/tests/test_engagement_recovery_v26.py` — 10,549 bytes
- `src/tests/test_engagement_runtime.py` — 6,230 bytes
- `src/tests/test_engagement_snapshot_journal_v34.py` — 5,571 bytes
- `src/tests/test_event_driven_semantic_tutor_v48.py` — 9,639 bytes
- `src/tests/test_executive_authority_v53.py` — 3,617 bytes
- `src/tests/test_executive_authority_v54.py` — 4,231 bytes
- `src/tests/test_executive_authority_v55.py` — 4,382 bytes
- `src/tests/test_gemma_executive_cortex_v53.py` — 15,526 bytes
- `src/tests/test_gemma_executive_cortex_v54.py` — 20,148 bytes
- `src/tests/test_gemma_executive_cortex_v55.py` — 21,098 bytes
- `src/tests/test_gemma_executive_cortex_v55_hardening.py` — 8,875 bytes
- `src/tests/test_hardening_metrics_v14.py` — 1,640 bytes
- `src/tests/test_identity_panel_contract_v15.py` — 3,677 bytes
- `src/tests/test_inner_diary_worker_v16.py` — 7,381 bytes
- `src/tests/test_live2d_affect_idle.py` — 5,090 bytes
- `src/tests/test_live2d_body_switch.py` — 9,708 bytes
- `src/tests/test_live2d_speech_animation.py` — 8,708 bytes
- `src/tests/test_living_user_memory.py` — 11,605 bytes
- `src/tests/test_living_user_memory_v39.py` — 7,924 bytes
- `src/tests/test_loop_guard_and_schema_v7.py` — 3,537 bytes
- `src/tests/test_memory_architecture_v2.py` — 6,852 bytes
- `src/tests/test_memory_authority_v41.py` — 4,362 bytes
- `src/tests/test_memory_gc_living_curator.py` — 5,379 bytes
- `src/tests/test_memory_open_registry.py` — 5,916 bytes
- `src/tests/test_memory_panel_protocol.py` — 3,218 bytes
- `src/tests/test_memory_panel_ui_v41.py` — 785 bytes
- `src/tests/test_observer_singleflight_private_mind_dirty.py` — 7,563 bytes
- `src/tests/test_open_ended_personality_v12.py` — 16,155 bytes
- `src/tests/test_opening_contracts.py` — 1,636 bytes
- `src/tests/test_opening_director_rules.py` — 2,787 bytes
- `src/tests/test_opening_history_cooldowns.py` — 1,748 bytes
- `src/tests/test_opening_move_catalog.py` — 670 bytes
- `src/tests/test_opening_prosody_beats.py` — 4,304 bytes
- `src/tests/test_opening_safety.py` — 6,009 bytes
- `src/tests/test_opening_surface_writer_contract.py` — 1,115 bytes
- `src/tests/test_opening_v25_regressions.py` — 439 bytes
- `src/tests/test_pdf_inference_refactor.py` — 32,305 bytes
- `src/tests/test_pdf_refactor_v6.py` — 7,464 bytes
- `src/tests/test_policy_settings_and_supervisor.py` — 7,398 bytes
- `src/tests/test_protocol_and_transport_boundaries.py` — 5,940 bytes
- `src/tests/test_public_turn_runtime.py` — 1,382 bytes
- `src/tests/test_random_chat_seed_reservoir_v28.py` — 8,728 bytes
- `src/tests/test_random_chat_seed_v27.py` — 12,141 bytes
- `src/tests/test_refactor_cortex_di_v42.py` — 2,098 bytes
- `src/tests/test_release_archive_hardening_v34.py` — 2,312 bytes
- `src/tests/test_runtime_boundaries_v18.py` — 9,559 bytes
- `src/tests/test_runtime_diagnostics_v14.py` — 2,299 bytes
- `src/tests/test_runtime_readiness_v18.py` — 2,985 bytes
- `src/tests/test_runtime_slo_v22.py` — 4,252 bytes
- `src/tests/test_runtime_small_policy_contracts_v22.py` — 7,614 bytes
- `src/tests/test_semantic_frame_malformed_payload.py` — 1,668 bytes
- `src/tests/test_settings_catalog_v14.py` — 2,898 bytes
- `src/tests/test_settings_schema_v10.py` — 2,189 bytes
- `src/tests/test_settings_schema_v12.py` — 2,957 bytes
- `src/tests/test_settings_schema_v13.py` — 1,565 bytes
- `src/tests/test_settings_schema_v9.py` — 2,023 bytes
- `src/tests/test_shared_addressing_and_media_focus_v46.py` — 5,073 bytes
- `src/tests/test_social_agenda_big_patch_v20.py` — 16,549 bytes
- `src/tests/test_social_agenda_full_cutover_v22.py` — 9,920 bytes
- `src/tests/test_social_agenda_live_selector_v23.py` — 5,327 bytes
- `src/tests/test_social_agenda_production_v21.py` — 8,537 bytes
- `src/tests/test_social_initiative_v18.py` — 9,308 bytes
- `src/tests/test_social_stance_and_greetings_v2.py` — 4,488 bytes
- `src/tests/test_stabilization_increment_4.py` — 6,670 bytes
- `src/tests/test_startup_greeting_plus_context_v25.py` — 3,570 bytes
- `src/tests/test_stockfish_adapter_v49.py` — 4,333 bytes
- `src/tests/test_surface_intent_engine.py` — 4,278 bytes
- `src/tests/test_tts_prosody_continuity.py` — 2,694 bytes
- `src/tests/test_tutor_research_policy_v18.py` — 6,705 bytes
- `src/tests/test_typed_discourse_v44.py` — 10,981 bytes
- `src/tests/test_v45_json_boundary_integration.py` — 1,808 bytes
- `src/tests/test_vision_route_stance_patch.py` — 3,185 bytes
- `src/tests/test_voice_director_elevenlabs.py` — 10,222 bytes
- `src/tests/world/test_sandbox_world.py` — 3,146 bytes
- `src/tools/__init__.py` — 76 bytes
- `src/tools/audit_remote_inference_paths.py` — 2,417 bytes
- `src/tools/audit_semantic_authority_paths.py` — 1,735 bytes
- `src/tools/evaluate_semantic_paraphrases.py` — 3,046 bytes
- `src/tools/evaluate_social_plan_activation.py` — 6,649 bytes
- `src/tools/package_source.py` — 1,893 bytes
- `src/tools/report_pdf_acceptance.py` — 7,217 bytes
- `src/tools/verify_release.py` — 3,561 bytes
- `src/transport/__init__.py` — 58 bytes
- `src/transport/udp.py` — 24,055 bytes
- `src/vision.py` — 21,632 bytes

## 21. Kết luận

Bản gộp Mega là archive duy nhất nên dùng để chuyển giao: source V2 là phiên bản chính, body đã sửa layout, đặc tả và lịch sử được giữ để forensic, test logs không bị che giấu, và script verify giúp phát hiện file bị đổi. Nó là nền triển khai có cấu trúc và kiểm thử, không phải chứng nhận một “chủ thể nhân tạo” đã hoàn thiện. Phần còn lại là integration, calibration, security review và thí nghiệm dài hạn. Những thứ buồn tẻ ấy mới là nơi hệ thống trở thành thật, chứ không phải ở tên class dài 28 ký tự.

# Phụ lục V3: Integration Hardening

Bản V3 kế thừa toàn bộ nội dung phía trên và bổ sung hardening cho bốn vùng vốn còn thiếu bằng chứng vận hành: sandbox path/command/token scope, idempotency qua restart, migration/backup integrity và protocol Python–C# cho body. Chi tiết kỹ thuật, test mới, rủi ro còn lại và hướng rollout nằm trong `docs/SUBJECT_CORE_V3_HARDENING.md`; threat model riêng nằm trong `docs/THREAT_MODEL_SANDBOX_V3.md`.

Kết quả mới nhất là 877 test pass theo hợp đồng hiện hành, 2 test lịch sử bị deselect vì mâu thuẫn trực tiếp với hợp đồng mới hơn. Full historical suite vẫn chỉ fail đúng hai assertion source-level ấy. Không có compiler Godot/.NET, Ruff hoặc mypy trong môi trường đóng gói, nên các gate đó được ghi là chưa chạy thay vì được “suy luận là chắc ổn”, một thủ thuật báo cáo mà phần mềm đã chịu đựng đủ lâu rồi.
