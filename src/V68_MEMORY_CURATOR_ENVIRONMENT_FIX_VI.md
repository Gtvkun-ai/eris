# ERIS V68 - DeepSeek Memory Curator Authority + Environment Semantic Edge

## Mục tiêu

V68 xử lý hai lỗi có cùng một gốc kiến trúc: **state nội bộ bị đối xử như raw record/event**.

1. Living User Memory từng phơi raw record ra UI và curator bị hạn chế quyền dọn những record có authority evidence.
2. Environment `self_relevant_inspection` từng bị đối xử như một public event lặp lại, làm Eris nói nhiều lần biến thể của “bạn đang xem thứ gì đó về Eris”.

V68 chuyển cả hai sang semantic ownership rõ ràng.

---

## 1. DeepSeek Curator có toàn quyền với working memory structure

DeepSeek được phép cấu trúc lại **mọi** record đang sống, kể cả record từng được user xác nhận hoặc sinh từ behavior rule:

- archive
- delete
- weaken
- merge
- rewrite
- hide
- canonicalize / move sang path canonical

`user-confirmed` vẫn là evidence có authority cao nhất về **meaning**, nhưng không còn biến path/value hiện tại thành vật bất khả xâm phạm.

Store vẫn giữ audit/history/evidence. Nói ngắn gọn: DeepSeek có root đối với **representation**, không có giấy phép bịa fact trái evidence.

### Canonicalization

- Cho phép gom record khác path khi cùng một semantic concept.
- Tự hấp thụ record đang tồn tại ở target path/scope để không tạo hai canonical record.
- Hợp nhất evidence IDs, recurrence, last-confirmed và provenance.
- Record canonical được đánh dấu `canonical_user_memory=True`.
- UPR/path kỹ thuật, duplicate, parser debris được ưu tiên đưa lên đầu review batch.
- Batch mặc định 80 record, reviewer budget 3600 tokens.

### Open loops

`open_loops.*` và `goals.open_loops` bị xóa khỏi Living User Profile theo rule deterministic.
Open loop thuộc conversation/action continuity, không phải “ERIS nhớ gì về bạn”. Dreamer cũng không tạo chúng vào user profile nữa.

---

## 2. Memory panel chỉ là canonical user-facing projection

Màn “ERIS nhớ gì về bạn?” không còn là raw DB browser.

UI loại:

- UPR/technical IDs
- open loops
- runtime/tracking/telemetry/debug state
- null/unknown values
- record `hidden_from_ui`
- raw memory feed trace

Nếu curator đã tạo canonical records, panel chỉ đọc canonical projection. Feed trace vẫn tồn tại cho developer/audit nhưng không nằm trong payload user-facing.

Label UI đổi từ “DeepSeek Memory Curator” sang “DeepSeek quản lý ký ức”.

---

## 3. Fix lặp “bạn đang xem Eris”

### Root cause cũ

`SELF_RELEVANT_INSPECTION` là một **semantic state**, nhưng pipeline cũ có hai vấn đề:

1. revision phụ thuộc evidence refs, nên cùng một màn hình đứng yên có thể trông như event mới khi UIA/accessibility phát ref mới;
2. Subject Initiative biến self-relevance thành một motive public riêng `environment_self_relevance`, rồi Surface được giao semantic target kiểu “nói về Eris mà user đang xem”.

Kết quả: screen state cướp commitment của thought nội tại và lặp các câu gần như giống nhau.

### V68

- `EnvironmentMeaning.semantic_key` chỉ phụ thuộc `kind + normalized semantic object`, không phụ thuộc event/evidence ID.
- `SemanticEnvironmentWorker` wake theo **semantic state signature**, bỏ event kind/timestamp/evidence khỏi identity.
- Task affordance public chỉ edge-trigger khi semantic task đổi.
- `self_relevant_inspection` **không còn là public motive/target**.
- Self-relevance chỉ là context boost cho `self_expression` đã thực sự bắt nguồn từ Eris.
- `InitiativeArbiter` chỉ coi `environment_shared_task` là environment action target.
- Surface có rule first-person: khi nói về ERIS với tư cách chính mình thì dùng “tôi/em/mình” theo voice hiện tại, không nói như đang mô tả người thứ ba.
- Executive semantic critic được yêu cầu trả `reason/semantic_commitments` bằng tiếng Việt để log không tự chuyển sang tiếng Trung.

---

## 4. Observability

Memory GC report có thêm:

- `living_deleted`
- `living_canonicalized`

Log daemon hiển thị delete/canonicalize riêng thay vì giấu chúng trong tổng `applied`.

---

## 5. Áp dụng

Đây là **change-only trên nền V67**.

Giải nén/overlay vào project V67 rồi restart Eris. Không có file legacy cần xóa ở V68.

Memory cũ không cần user tự dọn. Chạy “DeepSeek dọn ngay” một lần để canonicalize profile hiện tại; daemon sau đó tiếp tục duy trì working profile.

---

## 6. Kiểm thử

Direct regression batch: **104/104 PASS**.

Bao gồm:

- curator được delete/restructure user-authority representation;
- cross-path canonicalization + evidence preservation;
- canonical target collision absorption;
- open-loop removal;
- panel không dump UPR/open-loop/feed trace;
- environment semantic key ổn định khi evidence ref đổi;
- self-relevant environment không tạo public motive riêng;
- semantic wake signature bỏ telemetry noise;
- initiative/environment/expression V67 regression vẫn pass.
