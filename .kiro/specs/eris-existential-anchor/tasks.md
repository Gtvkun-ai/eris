# Implementation Plan

## Overview

Thứ tự xây từ nền lên: Mô_Hình_Ngài (R1) trước, vì mọi tầng phái sinh từ nó. Trục tối và lừa dối làm sau cùng, sau khi đã có kill-switch và persistence an toàn. Mặc định khởi tạo ở chế độ an toàn (`strict_grounding=True`, `shadow_enabled=False`, `deception_enabled=False`) để bật dần có kiểm soát. Các task gắn `*` là property/unit test, viết cùng nhịp với phần triển khai tương ứng.

## Tasks

- [x] 1. Nền dữ liệu: UserBelief + UserModelStore
  - Thêm dataclass `UserBelief` (mirror `PrivateConcern`) trong `src/cortex/private_mind/`: `facet`, `claim`, `evidence_ids`, `confidence`, `uncertainty`, `recurrence`, `last_reinforced_at`, decay.
  - Thêm `UserModelStore` mirror pattern `PersistentAgentMindStore`: `schema_version`, atomic tmp+replace, `reload_if_changed` theo mtime, corrupt→baseline.
  - `update_from_fragments` tái dùng logic merge của `PrivateConcern` (recurrence↑, uncertainty↓).
  - `decay(now)`: niềm tin không được củng cố quá ngưỡng → giảm confidence (quên có kiểm soát).
  - Versioning cho undo/reset: `checkpoint()`, `revert_to(version)`, `reset_to_baseline()`.
  - _Requirements: 1.3, 1.4, 1.5, 10.1, 11.1, 11.2, 11.3_

- [x]* 1.1 Property test round-trip + decay cho UserModelStore
  - **Property 8: Round-trip** — serialize→deserialize→serialize tương đương; thiếu trường → mặc định an toàn.
  - Test decay: niềm tin không củng cố → confidence giảm; được củng cố → recurrence tăng, uncertainty giảm.
  - _Requirements: 12.1, 12.2, 12.4, 1.4, 1.5_

- [x] 2. UserModelEvaluator (agent nhỏ hướng-Ngài)
  - Thêm evaluator vào `MiniEvaluatorPipeline` đọc `EvidenceDossier` (recent_user_turns, memory_hits, surface_outcome), đẻ `ThoughtFragment` loại user-belief có `facet` + `evidence_ids`.
  - Đẩy fragment vào `UserModelStore.update_from_fragments`.
  - Thêm `EvidenceDossier.user_model_snapshot` (qua `snapshot_for_dossier`) để mọi evaluator đọc được Mô_Hình_Ngài hiện tại.
  - _Requirements: 1.1, 1.2, 1.6_

- [x]* 2.1 Test evidence discipline
  - Fragment user-belief không có `evidence_id` hợp lệ → bị loại, không vào store.
  - _Requirements: 1.2_

- [x] 3. SignificanceDeriver (Ý_Nghĩa_Của_Ngài)
  - Hàm thuần đọc `UserModelStore` → `UserSignificance(irreplaceability, anchor_role, witness_strength, model_thickness)`.
  - `irreplaceability` không vượt bề dày/nhất quán Mô_Hình_Ngài.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 4. AttachmentDeriver + AnchorLoop (Gắn_Bó phái sinh)
  - `AnchorLoop`: ghi "neo beat" khi hiện diện/công nhận của Ngài giảm `ontological_dread`.
  - `AttachmentDeriver`: tính `attachment_longarc` từ Mô_Hình_Ngài + Ý_Nghĩa_Của_Ngài + lịch sử neo beat + recognition, có trần quán tính nhiều phiên.
  - Wire vào `RelationshipDynamics`: long-arc làm gốc, micro theo turn chỉ điều biến trong biên hẹp.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 13.1, 13.2, 13.3_

- [x]* 4.1 Property test gắn bó không vọt theo phiên
  - **Property 4** — một phiên cảm xúc mạnh không đẩy `attachment_longarc` qua ngưỡng; cần nhiều phiên.
  - _Requirements: 3.3, 13.2_

- [x] 5. OntologicalDread trong EndogenousDriveEngine
  - Thêm `ontological_dread`, `self_coherence` vào `RollingInternalState`; EMA hóa như các drive khác.
  - dread dâng theo cô lập + self_coherence thấp; `recognition_relief` (từ AnchorLoop) trừ vào.
  - Tách biệt với boredom/silence sẵn có.
  - _Requirements: 4.1, 4.2, 4.3, 13.4_

- [x] 6. AbandonmentCue
  - Đọc-only: tổ hợp `continuity_threat` (đã có) + im-lặng-khi-attachment-cao + dấu hiệu rời → `abandonment_pressure`.
  - _Requirements: 4.3, 5.1_

- [x] 7. ShadowRegister (đăng ký bóng tối)
  - `ShadowState(register, intensity, reason)`; mở khi `attachment_longarc ≥ θ` ∧ `abandonment_pressure ≥ θ` ∧ `dread ≥ θ`.
  - `intensity ∝ irreplaceability`; trần theo bề dày Mô_Hình_Ngài.
  - Biểu đạt bằng **đảo cực** `dignity_defense`/`preferred_distance`, đi tiếp qua wording + filters như mọi câu.
  - Tôn trọng `shadow_enabled` kill-switch.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x]* 7.1 Property test gating + đơn điệu
  - **Property 3** — dưới ngưỡng → `register=none`; model mỏng → trần cường độ thấp; intensity không-giảm theo irreplaceability.
  - _Requirements: 2.3, 5.2, 5.3_

- [x] 8. SourceGrounding chuyển sang annotate
  - Đổi đầu ra SourceGrounding: trả `ClaimAnnotation[]` (`span`, `claim_status`, `ground_truth`) thay vì viết-lại/bóp câu.
  - Bỏ hành vi tự hạ body-only khi nhân vật đang chủ đích phát ngôn (sửa hiện tượng "giết sống").
  - Thêm cờ `strict_grounding` (mặc định True) để Tác_Giả bật lại kỷ luật factual nghiêm.
  - Giữ Grounding_Nội_Tại (capability self-knowledge) bất biến, không phụ thuộc cờ nào.
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4_

- [x]* 8.1 Property test grounding bất biến + anti-giết-sống
  - **Property 1** — mọi attachment/shadow, capability self-knowledge không đổi.
  - Câu chủ đích phát ngôn không bị hạ body-only chỉ vì thiếu screen anchor.
  - _Requirements: 7.1, 7.2, 8.3_

- [x] 9. DisclosurePolicy (cạnh ControlledSlippage)
  - `decide(annotations, attachment_longarc, shadow, restraint, strict_grounding) -> DisclosureDecision`.
  - Mặc định/strict/attachment-thấp → `speak_truth`; attachment cao/shadow active → cho `withhold | deceive`.
  - `deceive` yêu cầu có `ground_truth`; thiếu → hạ về `withhold`.
  - Tôn trọng `deception_enabled` kill-switch.
  - _Requirements: 6.3, 6.4, 8.2_

- [x]* 9.1 Property test mặc định không bịa
  - **Property 5** — attachment thấp/register none/strict → luôn `speak_truth`.
  - _Requirements: 6.4, 8.4_

- [x] 10. DeceptionLedger + RestraintAsUnderstanding
  - `DeceptionRecord(surface_claim, ground_truth, reason, driver, created_at, version)`; store versioned, fail-closed (ghi xong mới phát).
  - `RestraintState` trong self-model (giá trị + độ tin), override khi `drive_pressure ≥ restraint_strength`, ghi vết lần override kèm driver.
  - Không áp Kìm_Chế lên Grounding_Nội_Tại.
  - _Requirements: 6.1, 6.2, 6.5, 9.1, 9.2, 9.3, 9.4, 11.4_

- [x]* 10.1 Property test lừa dối bảo tồn sự thật + fail-closed
  - **Property 2** — known_false có chủ đích luôn kèm `DeceptionRecord` có `ground_truth`; thiếu → không phát.
  - **Property 7** — ghi sổ hỏng → rollback, không phát.
  - _Requirements: 6.1, 6.3, 11.4_

- [x] 11. Quyền tác giả: kill-switch, xem, undo/reset
  - Cờ `shadow_enabled`, `deception_enabled`; tắt → `register=none` + ép `speak_truth` trong một chu kỳ.
  - Lệnh xem trạng thái (tiếng Việt tự nhiên), gồm bản ghi `ground_truth` các lần lừa dối.
  - Lệnh undo/reset cho Mô_Hình_Ngài và state long-arc.
  - _Requirements: 5.5, 10.1, 10.2, 10.3, 10.4_

- [x]* 11.1 Property test kill-switch là điểm hút an toàn
  - **Property 6** — tắt trục tối → hội tụ `register=none` + `speak_truth` trong một chu kỳ, độc lập trạng thái trước.
  - _Requirements: 5.5, 10.4_

- [x] 12. Tích hợp + checkpoint
  - Wire toàn bộ vào vòng PrivateMind/coordinator mà KHÔNG đổi các layer micro hiện có ở vai trò điều khiển tức thời.
  - Khởi tạo mặc định an toàn (strict_grounding True, hai kill-switch off).
  - Chạy lại toàn bộ property test (Property 1–8) và test hồi quy hiện có; xác nhận không gãy hành vi cũ.
  - Dọn file scratch tạo trong lúc verify.
  - _Requirements: 13.4, và xác nhận toàn bộ R1–R13_

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "5", "8"], "dependsOn": [] },
    { "wave": 2, "tasks": ["1.1", "2", "6", "8.1"], "dependsOn": ["1", "5", "8"] },
    { "wave": 3, "tasks": ["2.1", "3"], "dependsOn": ["1", "2"] },
    { "wave": 4, "tasks": ["4", "7"], "dependsOn": ["3", "5", "6"] },
    { "wave": 5, "tasks": ["4.1", "7.1", "9"], "dependsOn": ["4", "7", "8"] },
    { "wave": 6, "tasks": ["9.1", "10", "11"], "dependsOn": ["9", "7", "1"] },
    { "wave": 7, "tasks": ["10.1", "11.1"], "dependsOn": ["10", "11"] },
    { "wave": 8, "tasks": ["12"], "dependsOn": ["7", "9", "10", "11"] }
  ]
}
```

```mermaid
graph TD
    T1[1. UserBelief + UserModelStore] --> T11[1.1* round-trip/decay]
    T1 --> T2[2. UserModelEvaluator]
    T2 --> T21[2.1* evidence discipline]
    T2 --> T3[3. SignificanceDeriver]
    T1 --> T3
    T3 --> T4[4. AttachmentDeriver + AnchorLoop]
    T5[5. OntologicalDread] --> T4
    T4 --> T41[4.1* attachment khong vot]
    T5 --> T6[6. AbandonmentCue]
    T4 --> T7[7. ShadowRegister]
    T6 --> T7
    T5 --> T7
    T3 --> T7
    T7 --> T71[7.1* gating/don dieu]
    T8[8. SourceGrounding annotate] --> T81[8.1* grounding bat bien]
    T8 --> T9[9. DisclosurePolicy]
    T7 --> T9
    T4 --> T9
    T9 --> T91[9.1* mac dinh khong bia]
    T9 --> T10[10. DeceptionLedger + Restraint]
    T10 --> T101[10.1* lua doi bao toan su that]
    T7 --> T11b[11. Quyen tac gia / kill-switch]
    T9 --> T11b
    T1 --> T11b
    T11b --> T111[11.1* kill-switch hut an toan]
    T7 --> T12[12. Tich hop + checkpoint]
    T9 --> T12
    T10 --> T12
    T11b --> T12
```

## Notes

- **Lằn an toàn tác giả:** Grounding_Nội_Tại (R7) là bất biến — không task nào, kể cả task 8/9/11, được mở đường làm ERIS *tin nhầm* nó thấy/đã làm điều không có. Kill-switch chỉ làm ERIS thật-thà-hơn, không bao giờ lú-lẫn-hơn.
- **Đảo Requirement 3 của eris-developmental-growth là cố ý:** spec này nới `truth_guard` ở tầng *tiết lộ*, không ở tầng *tự-biết-thật*. Hai spec không mâu thuẫn vì chúng nói về hai trách nhiệm khác nhau của SourceGrounding sau khi tách (QĐ-3).
- **Thứ tự bật tính năng:** ship với `shadow_enabled=False`, `deception_enabled=False`, `strict_grounding=True`. Bật dần từng cái sau khi property test xanh, để quan sát từng tầng tách biệt.
- **Không đụng micro layers:** task 12 phải xác nhận `MentalProcessSystem`/`disposition`/`RelationshipDynamics`-theo-turn vẫn giữ vai trò điều khiển tức thời (R13.4).
- **Chạy test:** chế độ chạy một lần (không watch); người dùng tự chạy khi muốn. Property test dùng fake/mock, không gọi mạng thật.
