# ERIS V45 — Causal Mental Material / Associative Seed Refactor

## Vì sao có V45

V42–V44.1 đã sửa lần lượt causality, mood và expression urge, nhưng nguồn material phía trên vẫn mang kiến trúc cũ của `random_chat_seed`: reservoir thiếu loại nào thì model tạo loại đó, rồi chính model vừa nghĩ premise vừa tự khai `why_now`, motive, opening move và desired response.

Kết quả là topic nhìn đa dạng nhưng nguyên nhân sinh thought vẫn giống một topic generator. V45 đổi ownership:

```text
CausalMotive (runtime, có trước)
        ↓
Associative material worker
        ↓
MentalMaterial
   ├─ fade
   ├─ thought
   ├─ concern
   └─ expression
        ↓
ExpressionUrge
        ↓
Neuro
        ↓
Surface
```

Nguyên tắc: **model được đề xuất “cái gì vừa nảy ra”, nhưng không được tự cấp giấy chứng nhận “tại sao tôi muốn nghĩ cái này”.**

## 1. CausalMotive có trước material

`cortex/mental_material.py` tạo `CausalMotive` deterministically từ state đã tồn tại:

- user event mới/gần đây;
- ActiveConcern;
- private thought/workspace không phải output seed worker;
- memory context;
- self outcome nếu có source thật.

Relationship/contact pressure chỉ modulation strength. Nó không được tự phát minh semantic focus.

```text
connection_pressure=1.0 + không có semantic source
→ không có CausalMotive
→ không gọi generator chỉ để lấp kho
```

Mỗi cause có `generation_budget` riêng. Cùng một event không thể hết TTL rồi tiếp tục sinh vô hạn paraphrase bằng seed ID mới.

## 2. DFU seed đổi vai trò: associative material, không phải autonomous topic card

Schema V45 của seed worker chỉ còn các field material:

- `material_kind`;
- `premise`;
- `topic_tags`;
- `epistemic_mode`;
- `open_loop`;
- `expected_update`;
- uncertainty/confidence/TTL.

Model **không còn sở hữu**:

- `eris_motive`;
- `why_now`;
- `opening_move`;
- `desired_response`;
- source refs/provenance public authority.

Runtime gắn motive, cause và refs sau khi model trả material.

## 3. Diversity vẫn giữ, nhưng không còn là nguyên nhân

Các material kind gồm:

```text
observation
opinion
association
memory_callback
unfinished_thought
desire
plan
reaction
question
playful_impulse
small_contact
self_reflection
hunch
```

Reservoir vẫn có thể ưu tiên loại đang thiếu, nhưng chỉ **bên trong một causal source đã tồn tại**.

Sai:

```text
kho thiếu opinion
→ hãy nghĩ ra một opinion bất kỳ
```

Đúng:

```text
user vừa nâng cấp ERIS
→ cause đã tồn tại
→ trong các material hợp cause này, reaction/opinion/association... có thể cạnh tranh
```

Cùng một cause có thể sinh reaction rồi opinion dù topic tags giống nhau. Duplicate chỉ chặn khi semantic object thật sự giống.

## 4. MentalMaterial có lifecycle riêng

`runtime/mental_material_runtime.py` là projection session-local, không tạo database mới.

Một material có thể:

```text
fade       → thoáng qua rồi mất
thought    → còn sống nhưng chưa đủ tension/urge
concern    → đáng được ConcernStore giữ continuity
expressible→ có lực muốn mang sang user
```

`thought tồn tại` và `thought muốn nói` là hai quyền khác nhau, nên runtime project riêng:

- concern ingress affordances;
- expression ingress affordances.

Một material không tự trở thành speech candidate chỉ vì generator đã tạo nó.

## 5. Question và small talk cùng tồn tại

V45 không cấm small talk.

`small_contact` là material hợp pháp nếu nó bám một context/cause thật. Nó không cần giả vờ có information gain lớn.

Question thì khác: nếu model tạo `question`, nó phải khai `expected_update`, ví dụ:

```text
relationship.autonomy_tolerance
user.preference_for_unsolicited_initiative
project.design_tradeoff
```

Question không có state nào dự kiến thay đổi bị hạ quality đủ mạnh để bình thường không vào reservoir.

Nhờ vậy:

```text
small_contact → có thể chỉ để chạm nhẹ vào user
question      → nên xuất phát từ gap thật
opinion       → có stance
reaction      → phản ứng trực tiếp
playful       → banter/tease
```

Không còn bắt mọi nội tâm phải biến thành “Liệu X có phải Y hay Z?”.

## 6. Cắt đường tắt reservoir → social initiative

Material seed V45 có `material_only=True`.

`SocialInitiativeEngine` không được đọc nó thành public affordance trực tiếp:

```text
reservoir
  X→ social candidate
```

Nó phải qua:

```text
reservoir
→ MentalMaterialRuntime
→ lifecycle
→ concern/ExpressionUrge
→ Neuro
```

Legacy seed path vẫn còn để compatibility test/caller cũ không vỡ, nhưng production V45 dùng material-only path.

## 7. Public expression quay receipt về material gốc

Khi material thành ExpressionUrge, urge giữ `source_material_id`.

Sau public commit thật:

```text
ExpressionUrge.satisfaction ↑
MentalMaterial.satisfaction ↑
MentalMaterial.freshness ↓
```

Nếu chỉ làm urge nguội mà material gốc vẫn tưởng “chưa từng nói”, nó có thể projection lại và tạo replay kín. V45 có regression riêng cho boundary này.

## 8. CognitiveEvent vẫn là authority causality của V42

Material concern projection mang event identity:

```text
cogevt:material:<material_id>
```

Project lại cùng material ở tick sau không tạo cognition mới. Concern ingress được phép retry-safe, còn V42 ledger đảm bảo idempotency.

## 9. Những thứ cố ý không sửa trong V45

Theo scope đã chốt, V45 không sửa:

- DeepSeek/local semantic fallback;
- force-speak semantics;
- claim manifest/grounding policy;
- V43 affect dynamics;
- V44.1 Neuro readiness lifecycle.

Đây là refactor nguồn mental material, không phải bản “sửa tất cả cho xanh”.

## 10. Log nên xem khi test runtime

Tìm các dòng:

```text
[associative material] stocked seed=... material=... cause=... motive=...
[mental material] born id=... kind=... cause=... motive=...
[mental material] top id=... state=... activation=... concern=... express=... fresh=...
[cognitive event] applied id=cogevt:material:...
[expression urge] top id=... pressure=... priority=... fresh=...
[mental material] expressed id=... satisfaction=...
```

Behavior tốt:

1. Không có event/concern/memory source mới thì reservoir không tự sản xuất topic chỉ vì còn slot.
2. Một user event có thể sinh reaction/opinion/association khác nhau, nhưng bị giới hạn bởi cause budget.
3. Question có gap/update thật, small talk nhẹ vẫn tồn tại như `small_contact`.
4. Material có thể chỉ là thought rồi fade mà không trở thành concern/speech.
5. Material đã nói ra phải nguội cả ở material lẫn urge.
6. Seed không xuất hiện trực tiếp như social candidate.

## 11. Preflight

Sau khi copy V45 vào repo:

```bat
src\tools\prepare_v45_runtime.bat
```

Kỳ vọng:

```text
[V45 PREFLIGHT] PASS: eris.mental_material.v45.causal_association | eris.initiative.v44_1.contentful_urge_lifecycle | eris.cognition.v42.event_driven
```
