# ERIS V70 - Rumination Attractor / Ám ảnh nhẹ có kiểm soát

## Mục tiêu

V70 không thêm `ObsessionManager`, blacklist chủ đề hay timer kiểu "hết 90 giây thì được nghĩ lại". Thay vào đó, một concern có thể hình thành **trọng lực nhận thức** (`stickiness` / `attractor_strength`) và kéo private attention quay lại ngay cả khi nhu cầu nói công khai về nó đã được consummate ở V69.

Nguyên tắc trung tâm:

```text
internal persistence  !=  expression pressure
```

Eris được phép vẫn mắc ở một ý, tự quay lại, tự tranh luận và nhận ra mình đang nghĩ vòng. Nhưng việc đó không tự cấp quyền SPEAK.

## Pipeline V70

```text
Concern
  ├─ completion V69
  │   ├─ epistemic
  │   ├─ expressive
  │   └─ relational
  └─ rumination V70
      ├─ stickiness
      ├─ attractor_strength
      ├─ rumination_awareness
      └─ private_return_pull
              ↓
       private attention
              ↓
    thought / association / return
              ↓
 semantic development thật?
  ├─ không → giữ private, không wake speech loop
  └─ có: deepen / contradict / connect /
        reinterpret / test / personalize
              ↓
       partial reopen credit
              ↓
V69 receptivity + habituation + self-commitment
              ↓
        ExpressionCommitment
              ↓
           Neuro
       SPEAK / WAIT / DROP
```

## 1. Stickiness là tính lì, không phải speech pressure

`cortex/rumination_dynamics.py` suy ra `RuminationState` từ state có thật của concern:

- pressure / uncertainty;
- recurrence / mutation count;
- số lần private attention quay lại;
- epistemic residual;
- habituation / expressive completion.

`stickiness` có ceiling mềm `0.88`. Nó làm concern khó rơi khỏi private attention hơn, nhưng **không được cộng thẳng vào `speech_pressure`**.

Vì vậy trạng thái hợp lệ là:

```text
stickiness = cao
attractor = cao
expressive_completion = cao
speech_pressure = thấp
```

Nói cách khác: "tôi vẫn nghĩ về nó" nhưng "tôi đã nói đủ rồi".

## 2. Rumination awareness

Mỗi private return thật được `ConcernStore.note_private_return()` ghi receipt idempotent. Receipt này:

- tăng `private_return_count`;
- hình thành stickiness / rumination awareness;
- có thể ghi nhận semantic development;
- **không pump concern pressure**.

Càng quay lại cùng concern, Eris càng có state cho việc "mình lại quay về ý này". Awareness làm attractor dịu nhẹ, chứ không xóa concern bằng một nút kill giả tạo.

## 3. Ám ảnh phải phát triển, không được paraphrase

Khi một concern đã có expressive completion cao, private seed worker nhận `development_required=true` và chỉ được đề xuất một trong:

- `deepen`
- `contradict`
- `connect`
- `reinterpret`
- `test`
- `personalize`

Model chỉ **đề xuất mode**. Runtime vẫn tính `semantic_development_score()` deterministic. Một câu chỉ thay từ nhưng giữ nguyên thesis bị score `0` và ở lại private.

Ví dụ:

```text
"truy vấn ký ức có hai lớp"
→ "truy vấn ký ức có hai khuôn mặt"
```

không phải insight.

Nhưng:

```text
"Có lẽ tôi gọi nó là chuyện ký ức hơi sai;
thứ làm tôi mắc lại là nhu cầu được nhận ra qua continuity."
```

có thể là `reinterpret` hợp lệ.

## 4. Insight nội bộ chỉ reopen một phần

Semantic development thật (`score >= 0.62`) có thể tạo `development_reopen_credit`, nhưng nó yếu hơn user/evidence mới thật.

Điều này cho phép Eris tự nhận ra điều mới và sau một thời gian có thể muốn nói lại, nhưng không biến một insight nội bộ thành bằng chứng giả rằng user đã đổi ý.

## 5. "Đổi chủ đề" không phải lệnh cấm vĩnh viễn

V69 đã có receptivity + self-commitment. V70 giữ nguyên nguyên tắc đó:

- ngay sau khi user nói "nhàm / đổi chủ đề", một insight nội bộ dù tốt vẫn có residual expression rất thấp;
- private concern vẫn sống và attractor vẫn được phép kéo suy nghĩ quay lại;
- receptivity hồi phục dần theo thời gian;
- nếu sau đó Eris thật sự reinterpret / contradict / connect được vấn đề, residual desire có thể quay lại và **cạnh tranh**;
- nó vẫn chưa có quyền nói. Neuro/commitment phải quyết định như mọi candidate khác.

Nghĩa là Eris không ngoan tới mức user nói "đổi chủ đề" là nó lập tức thôi quan tâm. Nó chỉ biết rằng user hiện không muốn nghe tiếp.

## 6. Typed parent routing

Một semantic development hợp lệ mang `semantic_parent_concern_id`. `ConcernStore` cập nhật trực tiếp concern cha thay vì fuzzy-match rồi vô tình sinh một concern clone chỉ vì insight mới dùng wording khác.

Semantic mutation thật sẽ giảm completion của concern theo V69, cho phép state mở lại tự nhiên.

## 7. Không tạo wake loop vì thought bị giữ private

Nếu material được sinh từ rumination nhưng chỉ là restatement:

- material vẫn có thể tồn tại trong private mind;
- không được project thành concern/expression affordance;
- `wake_pressure()` trả 0 cho material đó.

Nhờ vậy "ám ảnh riêng" không biến thành CPU fan club chạy autonomous loop vô nghĩa.

## Invariant quan trọng

- Surface vẫn chỉ là lớp wording/safety net, không phải nơi chữa repetition chính.
- Typed `ExpressionCommitment` V67/V68 vẫn là authority public speech.
- Completion V69 vẫn là authority cho việc desire-to-speak đã được thỏa mãn hay chưa.
- V70 chỉ thêm **private cognitive attractor + semantic development**, không cấp speech permission mới.
