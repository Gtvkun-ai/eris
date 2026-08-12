# ERIS V41 — Memory Hygiene + DeepSeek Cleanup + Memory Feed Trace

## Mục tiêu

V41 sửa đúng một vấn đề kiến trúc: **không để thứ “trông giống memory” tự động có quyền đi vào cognition/prompt**.

Repo vẫn được phép giữ audit/runtime trace rất chi tiết để debug. V41 không xóa `subject.db` chỉ vì nó có nhiều event. Thay vào đó, retrieval và prompt feed có một admission boundary riêng. Audit là audit; memory là memory. Hai đứa có thể ở cùng ổ đĩa nhưng không được dùng chung hộ chiếu.

## Data classes thực dụng

V41 phân biệt bốn vai trò:

1. **User memory** — fact/preference/episode có provenance, Living User profile.
2. **Durable cognitive memory** — semantic/episodic/relational/procedural/repair canonical.
3. **Transient cognition** — thought stream, hypothesis, concern chưa promote.
4. **Audit/runtime** — deliberation frame, executive commit, behavior observation, telemetry, idempotency/runtime receipts.

Chỉ (1) và (2) có quyền được admission vào prompt bình thường. (3) chỉ đi qua khi có explicit promotion/epistemic confirmation. (4) không được prompt admission.

## Memory admission

`memory/memory_admission.py` chạy **sau retrieval discovery nhưng trước MemoryScorer/activation**.

Nó không đánh relevance và không mutate store. Nó chỉ kiểm provenance/classification:

```text
store scan/vector hit
       ↓
MemoryCandidate
       ↓
MemoryAdmissionPolicy
  ├─ reject audit/runtime/transient chưa promote
  └─ admit canonical/provenanced
       ↓
MemoryScorer
       ↓
WorkingMemoryGate
       ↓
prompt
```

Living User Profile có admission tương tự trước `ProfileContextCompiler` scoring. Inferred memory có evidence vẫn có thể vào mode `clarify`; admission không tự biến suy luận thành fact.

## Memory Feed Trace

File mặc định:

```text
memory_core/memory_feed_trace.jsonl
```

Trace **không lưu nguyên text memory hoặc query của user**. Nó chỉ giữ query hash/độ dài + ID/layer/reason/score:

```text
[memory feed] channel=canonical retrieved=12 admitted=4 rejected=8 rendered=3 reject_reasons=...
[memory feed] channel=living_user retrieved=7 admitted=2 rejected=5 rendered=2 reject_reasons=...
```

Panel hiển thị bản gọn:

```text
Feed 12 → nhận 4 / loại 8 → prompt 3
```

Nhờ vậy khi Eris trả lời kỳ, có thể xác định memory nào thật sự vào cognition thay vì đoán từ file store.

## Behavior observations

`memory_core/behavior_observations.jsonl` từ V41 mặc định:

- không persist nguyên `public_text`;
- lưu `public_text_hash` để forensic/dedupe;
- đánh `prompt_eligible=false`, `source_class=audit_runtime`;
- TTL mặc định 72 giờ;
- cleanup rewrite file và loại record hết TTL.

Prompt aftermath chỉ dùng consequence/hint có cấu trúc, không nhét lại câu public lỗi cũ.

Có thể bật lưu raw text bằng `ERIS_BEHAVIOR_STORE_PUBLIC_TEXT=1` cho forensic đặc biệt, nhưng mặc định tắt.

## Thought stream

`memory_core/thought_stream.jsonl` là transient cognition, không phải semantic memory.

V41 thêm TTL/compaction:

- resolved: khoảng 12 giờ;
- drifting: khoảng 36 giờ;
- open: mặc định 7 ngày;
- open pressure/confidence cao có thể sống lâu hơn;
- thought confidence/pressure quá thấp không được feed lại vào prompt continuity.

Concern/durable memory promotion vẫn là pipeline riêng. Sống lâu không tự biến suy đoán thành sự thật.

## DeepSeek cleanup

Repo đã có `MemoryGCService` + DeepSeek `curator/critic`. V41 biến nó thành một control plane thật cho panel.

DeepSeek có quyền:

- review semantic candidates;
- review Living User duplicates/inference yếu;
- đề xuất archive/weaken/merge/drop trong schema giới hạn.

DeepSeek **không ghi trực tiếp**. Runtime deterministic validator/store API mới apply operation hợp lệ.

Cleanup còn chạy deterministic hygiene cho:

- behavior observation TTL/public-text decontamination;
- thought stream TTL;
- canonical maintenance/prune;
- anchor journal compaction.

## Panel “ERIS nhớ gì về bạn?”

V41 thêm:

- `Tự động dọn` — công tắc persist `memory_cleanup_settings.json`;
- `DeepSeek dọn ngay` — enqueue background cleanup, không block chat/UDP;
- status/report cleanup;
- Memory Feed Trace gần nhất.

Panel chỉ gửi protocol request. Nó không mở JSON/SQLite để tự xóa.

## Log nên xem khi chạy thật

```text
[memory feed] channel=canonical ...
[memory feed] channel=living_user ...
[memory_gc] manual cleanup finished ...
[behavior-observation] committed=...
```

Nếu user hỏi current screen/file mà semantic memory bị feed làm bằng chứng hiện tại thì vẫn là fail; grounding contract phía sau tiếp tục giữ authority.

## Deploy

Sau khi copy V41:

```bat
src\tools\prepare_v41_runtime.bat
```

Kỳ vọng:

```text
[V41 PREFLIGHT] PASS: eris.memory_hygiene.v41.admission | eris.memory_feed_trace.v41 | deepseek_cleanup_control
```

## Validation phát hành

- V41 focused + panel/GC: **18/18 PASS**.
- Memory-focused suite: **60/60 PASS**.
- V38/V39/V40 + Neuro/seed/Surface/social + V41 integration: **114/114 PASS**.
- Python compile/import preflight: **PASS**.
- Hai failure legacy `tests/test_living_user_memory.py` được xác nhận fail y hệt trên baseline V40, không phải regression V41.
