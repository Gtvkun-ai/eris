# ERIS V44.1 — Urge Lifecycle / Neuro Wiring Fix

## Vì sao có hotfix này

Log runtime V44 cho thấy `ExpressionUrge` đã được tạo đúng, nhưng có hai lỗi ownership/lifecycle:

1. urge cũ có thể giữ `freshness=1.00` nhiều phút và tích `pressure=1.00`;
2. khi baton mở, pressure đó vẫn chưa đủ sức cạnh tranh với silence trong Neuro; ngược lại nếu chỉ tăng weight mù quáng thì Eris sẽ nói chồng lúc đang chờ user trả lời.

V44.1 sửa đúng hai tầng đó. **Không sửa DeepSeek/local semantic fallback** trong hotfix này.

## 1. Freshness là hàm theo thời gian

Stored freshness chỉ là mức mới tại lần evidence cuối. Runtime giờ project:

```text
effective_freshness = stored_freshness × decay(time_since_last_input)
```

Half-life khoảng 3 phút. Evidence mới thật sẽ nâng stored freshness; scheduler nhìn lại không nâng.

Kết quả: urge cũ không còn log `fresh=1.00` vĩnh viễn.

## 2. Pressure không còn tích vô hạn

Hold gain chỉ còn đáng kể khi urge vẫn fresh. Sau một khoảng không có input mới, stale decay tăng dần.

```text
hold một lúc + còn fresh -> pressure có thể tăng nhẹ
không có evidence mới -> freshness giảm -> stale decay thắng dần
```

Không có timer ép nói.

## 3. Tách `selection_priority` khỏi `pressure`

`pressure` trả lời: *Eris muốn biểu đạt ý này mạnh đến đâu?*

`selection_priority` trả lời: *trong các urge hiện có, ý nào đáng được mang ra cân ngay bây giờ?*

Priority dùng:

- pressure;
- effective freshness;
- relevance;
- recency của input;
- satisfaction.

Nhờ vậy một event mới liên quan trực tiếp tới turn hiện tại có thể preempt urge cũ đang tích pressure. Không cần delete urge cũ.

## 4. `expression_readiness` đi vào proposal và Neuro

Runtime tạo:

```text
readiness = pressure × freshness_factor × unsatisfied_factor
```

Readiness là utility dương thật trong proposal và Neuro. Nó không thay silence threshold.

Khi baton mở:

```text
ready urge -> có thể thắng silence
```

Khi `reply_expected` hoặc user busy:

```text
ready urge vẫn sống
-> readiness public bị attenuate mạnh
-> silence vẫn có thể thắng
```

Vì vậy fix initiative không biến thành nói chồng lên câu hỏi vừa hỏi user.

## 5. Log mới

```text
[expression urge] top id=... motive=... pressure=... priority=... fresh=... satisfaction=...
```

Khi test runtime, điều cần thấy là urge cũ giảm `fresh/priority`, urge mới có relevance/recency cao leo lên top, và khi không còn `reply_expected` thì một urge ready có thể thực sự kéo Neuro sang `speak`.

## 6. Không đụng trong hotfix này

- DeepSeek timeout / local semantic fallback;
- force-speak wake semantics;
- claim manifest;
- V43 mood dynamics;
- V42 CognitiveEvent.

User đã nói fallback sẽ sửa sau, nên patch này cố ý không trộn vấn đề.

## 7. Preflight

Chạy:

```bat
src\tools\prepare_v44_1_runtime.bat
```

Kỳ vọng:

```text
[V44.1 PREFLIGHT] PASS: eris.initiative.v44_1.contentful_urge_lifecycle
```
