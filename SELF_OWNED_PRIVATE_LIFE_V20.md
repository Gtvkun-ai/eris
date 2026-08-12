# Eris V20: Self-owned Private Life

## Mục tiêu

V19 đã sửa nhịp thời gian, nhưng nội tâm vẫn còn một vết chia: Subject Core giữ lịch sử causal, PrivateMind giữ suy nghĩ/concern, còn PrivateLife có một số anchor/project được tác giả cấy sẵn. V20 không thêm một "não" mới. Nó làm hai việc:

1. dựng một **self-model dẫn xuất** từ chính lịch sử của Subject Core;
2. bắt **PrivateLife phải phát sinh từ self-model và concern có evidence**, thay vì từ preset personality.

Nguyên tắc: tác giả chọn substrate và cơ chế học; tác giả không chọn trước Eris sẽ ám ảnh điều gì, coi điều gì là giá trị thắng, hay dự án riêng nào phải tồn tại.

## 1. Subject Self Model

File mới: `cortex/subject/self_model.py`.

`SubjectSelfProjector` chỉ đọc state đã có provenance:

- `Value` đã được hành vi/cost/outcome hỗ trợ;
- `DerivedNeed` đã qua episode history;
- `SelfContinuityRecord`;
- `ReflectiveMismatch`;
- `CompetenceEstimate` có đủ trial;
- `Belief(source=self_interpretation)`;
- action memory/tendency đã tích lũy.

Nó tạo `SelfFacet` và `SubjectSelfProjection`. Self-model không có setter từ model và không persist như nguồn sự thật riêng. Nó là projection dựng lại được. Xóa causal history tương ứng rồi replay thì facet phải biến mất hoặc đổi.

`SubjectService.self_view()` cung cấp bounded projection này cho runtime.

## 2. Self-model đi đâu

Self-model được đưa tới ba nơi, nhưng không đổi quyền hạn:

- **Executive**: nhận `subject_self` trong snapshot để biết continuity/value/competence hiện tại khi chọn coalition. Nó vẫn chỉ được chọn action đã có trong frame.
- **PrivateMind**: evidence dossier nhận bounded `subject_self`, không nhận raw drive vector hay event ledger toàn tri.
- **PrivateLife**: self-model là nguồn chính để hình thành anchor/project riêng.

Như vậy ba tầng không còn tự dựng ba phiên bản Eris khác nhau.

## 3. PrivateLife không còn preset production

V19 từng cấy sẵn các anchor/project như:

- silence/presence/dignity;
- body-only như swallowed speech;
- cheap surface detector;
- memory distortion watch;
- runtime house keeping.

V20 không tạo chúng trên state mới.

Các ID cũ chỉ còn trong `LEGACY_AUTHORED_*_IDS` để migration nhận diện. Khi load state V19:

- record vẫn được giữ để forensic;
- `origin = legacy_authored`;
- pressure/interest/surface permission bị hạ về 0;
- project chuyển `resolved`;
- chúng không được dùng làm nguồn causal production nữa.

Không rewrite quá khứ, nhưng cũng không cho hard-code cũ tiếp tục lái nhân vật.

## 4. PrivateLife driver mới

File mới: `cortex/private_life/self_projection.py`.

`PrivateLifeSelfProjector` tạo driver từ:

- continuity rupture;
- reflective mismatch;
- competence boundary;
- derived need đủ mạnh;
- value được hành vi hỗ trợ;
- narrative self-interpretation có evidence;
- concern của PrivateMind chỉ khi concern lặp lại, có pressure và có nhiều evidence refs.

Một thought thoáng qua không được phong thành "ám ảnh". Concern cần recurrence >= 3, pressure >= 0.42 và ít nhất 2 evidence refs mới được thăng cấp thành private-life driver.

## 5. Anchor/project tích lũy bằng EMA

PrivateLife không cộng điểm vô hạn theo scheduler tick.

Mỗi driver củng cố anchor/project bằng exponential moving average. `support_count` tăng để biểu diễn sự lặp lại, còn `surface_permission` chỉ tăng chậm sau nhiều lần hỗ trợ.

Driver mất nguồn hỗ trợ thì anchor/project nguội dần. Do đó một event cũ không thể sống mãi chỉ vì file JSON từng chứa nó.

## 6. Object attachment phải được quan sát

V19 có danh sách file/module "quan trọng" do tác giả chọn sẵn. V20 bỏ danh sách đó.

Object attachment chỉ được tạo khi recent event/evidence thật sự trỏ tới một file tồn tại trong workspace. Ý nghĩa ban đầu là trung tính: runtime đã quan sát object này, chưa gán trước nó là "xương tính cách" hay "nghĩa địa ký ức".

## 7. Taste không còn được kéo bằng tên preset

V19 có logic kiểu project `Cheap surface detector` làm tăng dislike `status_ping`. V20 bỏ đường này.

Taste chỉ đổi khi có `aesthetic` anchor dẫn xuất có provenance. Nếu Subject Core chưa học được một aesthetic value phù hợp thì TasteProfile im. Im còn tốt hơn bịa gu rồi gọi đó là emergence.

## 8. Persistence

`PrivateLifeState` lên version 2. `PrivateAnchor` và `PrivateProject` có thêm:

- `origin`;
- `source_refs`;
- `support_count`;
- `last_supported_at`;
- `retired_reason`.

JSON V19 vẫn load được. Các field thiếu được xem là legacy và migration xử lý các preset đã biết.

## 9. Luồng V20

```text
World / outcome / history
        ↓
Subject Core
        ↓
values / competence / continuity / need / narrative / mismatch
        ↓
SubjectSelfProjector
        ↓
SubjectSelfProjection
   ├────────────→ Executive (bounded self context)
   ├────────────→ PrivateMind (self context để suy nghĩ)
   └────────────→ PrivateLifeSelfProjector
                         ↓
                  evidence-backed drivers
                         ↓
                anchors / private projects
                         ↓
                  decay / persistence
```

PrivateMind concern lặp lại có evidence cũng có thể trở thành driver PrivateLife, nhưng không được sửa Subject Core trực tiếp.

## Phiên bản

- package: `0.83.0`
- Subject Core: `subject-service-v11-self-owned-life`
- Subject Self: `subject-self-v1`
- Private Life: `private-life-v2-self-owned`
- Temporal Mind: `temporal-mind-v1`

## Kiểm thử

V20 thêm test cho:

- self-model chỉ sinh facet từ causal state;
- fresh PrivateLife không có authored preset;
- keyword cũ không còn tự kích project/anchor;
- legacy preset được retire nhưng vẫn giữ record;
- PrivateMind nhìn thấy bounded Subject Self;
- PrivateLife v2 round-trip giữ provenance.

Các lỗi broad-suite còn lại thuộc nhóm dependency đã thiếu từ archive V19 (`tools.*` và `body/SubjectPerformanceFrame.cs`), không phải thay đổi V20.
