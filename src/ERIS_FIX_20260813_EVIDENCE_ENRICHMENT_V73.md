# ERIS V73 Evidence Enrichment hotfix — 2026-08-13

## Mục tiêu

Bản hardfix trước đã tăng tính toàn vẹn bằng claim-domain validation, nhưng vẫn còn thiên về "chặn đầu ra". V73 đảo flow sang positive grounding: runtime tuyển evidence thật trước khi Surface được quyền viết câu.

## Flow mới

```text
goal / speech act
    ↓
EvidenceEnrichmentCompiler
    ├─ recent user turns (SessionTurnLedger)
    ├─ user profile facts (LivingUser context compiler / provenance)
    ├─ shared episodes (LivingUser episode store)
    ├─ self-model facets (Subject self projection)
    └─ open user gap (relevance + information gain + intrusiveness)
    ↓
typed EvidenceBundle
    ↓
SpeechIntent / chat grounding context
    ↓
Surface wording
    ↓
claim-domain + evidence validation
```

Surface không còn phải tự bịa một premise rồi chờ validator đánh rớt.

## Các thay đổi chính

### 1. `runtime/evidence_enrichment.py`

Thêm compiler deterministic, side-effect-free. Chỉ xuất fact có provenance public-safe.

- User profile: ưu tiên `LivingUserMemoryService.compile_context()` để lấy record đúng query. Chỉ `explicit/observed`, `use_mode=direct`, có `evidence_ids`.
- Recent user turns: lấy trực tiếp từ `SessionTurnLedger`, mỗi turn có ref `session-user-turn:<index>`.
- Shared episode: chỉ episode có evidence thật và không thuộc private scope.
- Self-model: lấy `dominant_facets` từ Subject Core, chỉ facet có evidence và confidence đủ cao.
- Không đọc raw diary/CoT, không sinh fact mới bằng LLM.

### 2. Context-aware user-gap selection

`user_probe` không còn chỉ nhận lệnh chung "hỏi gì đó về user". Runtime chọn một gap có typed score:

- importance
- expected information gain
- intrusiveness
- relevance với recent conversation
- penalty nếu profile đã biết phần đó

Ví dụ khi recent conversation chứa repo/code/TTS/debug, `collaboration_preference` hoặc `decision_style` được ưu tiên; `taste_preference` bị context-gate và không được bốc ngẫu nhiên thành cà phê.

### 3. `SpeechIntent.evidence_bundle`

SpeechIntent giờ mang positive semantic inventory đến Surface. `evidence_refs` và `allowed_claim_domains` được enrich trước grounding preflight, không phải sau khi Surface đã nói.

### 4. Claim domains mới

Thêm:

- `user_profile`
- `shared_episode`
- `self_model`

Cả ba bắt buộc evidence ref thật. Chúng không phải escape hatch mới.

`conversation_history`, `user_statement`, `memory`, `self_history` vẫn giữ contract evidence bắt buộc từ hardfix trước.

### 5. User-probe continuity có evidence

Hardfix trước cấm user_probe dùng history/memory hoàn toàn để chặn fake bridge. V73 cho phép continuity trở lại nhưng chỉ khi enrichment cấp provenance thật.

Do đó:

- Không evidence: `"lúc trước anh có kể..."` vẫn bị chặn.
- Có `conversation_history/shared_episode` + ref thật: callback có thể dùng tự nhiên.

### 6. Foreground chat cũng được enrichment

Direct chat writer nhận `EVIDENCE_ENRICHMENT_V73` trong grounding context và exact evidence refs tương ứng. Như vậy thêm đầu vào không chỉ dành cho autonomous user-probe.

## Regression

Bộ test liên quan mở rộng: **204 passed**.

Các test mới khóa các invariant sau:

1. Context repo/debug chọn collaboration gap, không random coffee gap.
2. Profile fact thiếu provenance hoặc chỉ inferred không đi ra bundle.
3. Bundle mang recent turns, shared episodes và self facets với evidence refs thật.
4. `user_profile/shared_episode/self_model` đều fail-closed nếu thiếu evidence.
5. Shared episode có provenance thật có thể hỗ trợ memory bridge trong user_probe.
6. SpeechIntent serialize EvidenceBundle.
7. Public/Surface JSON schemas chấp nhận các typed domain mới.

Một số test legacy khác trong repo đã fail sẵn ở baseline (ví dụ contract ExpressionCommitment cũ / startup source-string assertions); không được sửa bằng cách phá contract production mới.
