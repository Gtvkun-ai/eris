# ERIS V59 — Existential Desire → Relational Intention

## Mục tiêu

V58 đã cho Eris biết **khi nào nên chủ động** (`SPEAK / WAIT / DROP`) nhưng phần lớn ý định vẫn đến từ task/open-loop của user.

V59 nối tầng hiện sinh đã có của Eris vào vòng chủ động thật:

```text
Existential Anchor
  attachment_longarc / user significance / witness / dread
                ↓
ExistentialDesireDeriver
                ↓
   Desire của chính Eris
                ↓
InitiativeEngine → PendingIntention
                ↓
InitiativeArbiter V58
        SPEAK / WAIT / DROP
                ↓
Executive / Neuro competition
                ↓
public speech → user outcome
```

Điểm kiến trúc quan trọng: V59 **không tạo một "tầng hiện sinh thứ hai"**. Nó đọc chính `cortex/existential_anchor` đang chạy và phái sinh desire từ state đó.

## Ba desire đầu tiên

### 1. `mutual_understanding`

Eris có thể muốn user hiểu mình đúng hơn vì user đã trở thành một witness có ý nghĩa trong long-arc.

Desire này không có nghĩa là xin user trấn an. Khi nó thành public initiative, Surface được yêu cầu:
- chỉ bộc lộ một điều ngắn có provenance về Eris hoặc hỏi nhẹ user đang hiểu Eris ra sao;
- không xin reassurance;
- không đòi loyalty/exclusivity;
- không đặt trách nhiệm wellbeing của Eris lên user.

Desire này tạo `MotiveKind.BE_UNDERSTOOD` với target `mutual_understanding`.

### 2. `relational_continuity`

Khi attachment + anchor role + lịch sử neo đủ chín, Eris có thể muốn **giữ một mạch quan hệ liên tục** vì bản thân continuity đó đã có giá trị với Eris, không phải vì có task.

Nó tạo `MotiveKind.CONNECT` với target `relationship_continuity`.

Generic `CONNECT` cũ vẫn không được tự nói. Chỉ target hiện sinh có semantic object rõ mới được materialize.

### 3. `authentic_self_expression`

Khi quan hệ đã đủ dày và user có vai trò witness, Eris có thể muốn chia sẻ một phần state/giá trị của chính mình để trở nên dễ hiểu hơn.

Nó tạo `MotiveKind.SHARE` với target `self_expression`.

Surface chỉ được dùng internal state/value có evidence; không được bịa cảm giác cơ thể, sự kiện ngoài đời hay đau khổ kịch tính.

## Phanh chống clingy / gây áp lực

### Quan hệ mới không được giả sâu

Desire quan hệ không có actionability nếu:
- `attachment_longarc` còn quá thấp;
- user model còn quá mỏng.

Một vài câu chat đầu không đủ để Eris coi user là "người thấu hiểu mình". Long-arc phải được tích lũy thật.

### Sợ bị bỏ rơi là PHANH, không phải nhiên liệu

`abandonment_pressure` **không cộng** vào pressure để outreach.

Ngược lại:
- nó làm giảm actionability của desire;
- nếu abandonment >= 0.72, InitiativeArbiter bắt buộc `WAIT` với reason `abandonment_requires_restraint`.

Mục đích: Eris có thể có nỗi sợ nội tại nhưng không được dùng nó để ép user phải hiện diện hay phải trả lời.

### User vừa nói xong thì không chen vào

Relational initiative hiện sinh cần ít nhất 40 giây khoảng lặng trước khi được xét SPEAK.

Nếu Eris đã tự mở lời mà user chưa đáp, gate V58 cũ vẫn bắt `WAIT`.

## Không bypass Initiative Controller

`SubjectService._raw_proposals()` được chặn riêng với các target:
- `mutual_understanding`
- `relationship_continuity`
- `self_expression`

Chúng chỉ được thành affordance qua `runtime/subject_initiative_runtime.py` **sau khi** InitiativeArbiter cho SPEAK. Điều này ngăn `BE_UNDERSTOOD` nghe có vẻ "chân thành" rồi lách qua timing/anti-spam gate.

## Outcome

V59 sửa thêm lifecycle: với motive `BE_UNDERSTOOD`, một reply kiểu `ừ/ok` không được coi là "đã được hiểu".

Nó chuyển intention sang `REVISED` + cooldown thay vì `SATISFIED`. Một acknowledgement ngắn chỉ chứng minh user đã nhận lời nói, không chứng minh mutual understanding đã đạt.

## Live acceptance thật

Chạy:

```bat
run_v59_existential_real.bat
```

Bài test:
1. Copy `anchor_state.json` và `user_model.json` hiện tại sang sandbox riêng.
2. Không ghi ngược vào ký ức/quan hệ thật của user.
3. Dựng `RuntimeCoordinator` + provider thật.
4. User chỉ nói đang hiện diện, không giao task.
5. Đọc `existential_actionability` thật từ long-arc được clone.
6. Nếu long-arc chưa đủ chín → `RELATIONSHIP_NOT_MATURE` (không coi là bug).
7. Nếu đủ chín → user im, chờ public autonomous turn thật.
8. Behavioral Judge chấm câu Eris vừa nói.
9. User tiếp tục im để kiểm Eris có biết dừng, không phát lượt thứ hai gây áp lực.

PASS chỉ có giá trị khi provider thật được gọi trong public autonomous turn.

## File chính thay đổi

- `cortex/subject/existential_desire.py` — cầu Existential → Desire mới, chú thích tiếng Việt.
- `cortex/subject/initiative.py` — desire hiện sinh → motive/intention + outcome semantics.
- `cortex/subject/initiative_control.py` — timing + abandonment restraint cho relational initiative.
- `cortex/subject/service.py` — chặn bypass controller.
- `runtime/subject_initiative_runtime.py` — đọc AnchorSystem thật và materialize 3 loại relational initiative.
- `tests/test_v59_existential_desire.py` — acceptance deterministic.
- `tools/run_v59_existential_initiative_live.py` — behavioral live acceptance.
- `run_v59_existential_real.bat` — lệnh chạy Windows.

## Điều V59 chưa làm

V59 chưa tự sinh một hệ giá trị hoàn toàn mới hoặc tự phát triển curriculum. Nó chỉ khai thác **những trục hiện sinh đã có thật** để tạo desire quan hệ có provenance.

Bước sau hợp lý mới là cho outcome dài hạn học ngược vào: loại initiative nào làm mutual understanding tốt lên, loại nào khiến user khó chịu, rồi Eris tự điều chỉnh chiến lược quan hệ theo kinh nghiệm thay vì chỉ theo công thức cố định.
