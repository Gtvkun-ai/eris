# ERIS V77 - Continuous Self Dynamics

## Mục tiêu

V77 xử lý lỗ kiến trúc lớn còn lại sau V76: ERIS đã có memory, drives, Life-Horizon,
ConversationTrajectory, PrivateMind, RelationalPlan, InteractionEcology và Neuro, nhưng các
subsystem đó vẫn dễ hoạt động như nhiều state chuyên biệt được gọi khi có event. V77 thêm một
**self-process liên tục có lịch sử nhân quả**, để một trạng thái đang tồn tại của ERIS có thể sống
qua nhiều tick, nhiều khoảng im lặng và restart.

V77 **không tuyên bố ERIS có consciousness/personhood**. `ContinuousSelfState` là state vận hành
có causal history, dùng để làm hành vi ổn định và giải thích được hơn.

## Xương sống mới

```text
OBSERVATION
    |
    v
CONTINUOUS SELF
    |-- concerns
    |-- commitments
    |-- unfinished private thoughts
    |-- tensions
    |-- public action pressure
    |-- private cognition pressure
    |-- orientation / dominant motive
    |
    v
MOTIVE / COMMITMENT
    |
    v
PLAN + INTERACTION ECOLOGY
    |
    v
ACTION OPPORTUNITY
    |
    v
EXECUTIVE / NEURO
    |
    +--> SPEAK
    +--> BODY ONLY
    +--> SILENCE
    |
    v
OUTCOME
    |
    +----------------------> CONTINUOUS SELF
```

Điểm khác cốt lõi: private cognition và public speech không còn là cùng một áp lực. ERIS có thể
nghĩ rất nhiều nhưng vẫn có `public_action_pressure` thấp và im.

## State mới

`runtime/continuous_self_dynamics.py` thêm bốn loại state causal:

- `SelfConcern`: concern nhẹ có provenance, decay theo thời gian.
- `SelfCommitment`: cam kết nhiều lượt như `mood_lift`, không reset sau một câu Surface.
- `UnfinishedThought`: thought private có thể phát triển, simmer, settled hoặc dormant mà không surface.
- `SelfTension`: hai motive cùng hợp lệ nhưng kéo hành vi theo hai hướng khác nhau.

`ContinuousSelfState` giữ thêm:

- `orientation`;
- `dominant_motive`;
- `public_action_pressure`;
- `private_cognition_pressure`;
- `continuity_strength`;
- `social_availability`;
- causal trace ngắn để audit.

## Nguyên tắc chống self-loop

1. User/external evidence thật được phép làm commitment mạnh lên.
2. Private development có thể giữ một thought sống nếu semantic gain thật sự cao.
3. Assistant public speech **tiêu public pressure**.
4. Assistant public speech **không recharge commitment/concern**.
5. Nhiều autonomous public attempts không có user support làm commitment yếu/simmering.
6. Thought được surface thì pressure giảm; nó không quay lại hàng đợi với nguyên áp lực.

Nhờ đó ERIS không thể tự nói một câu rồi dùng chính câu đó như bằng chứng rằng mình cần nói tiếp.

## Continuous update khi user im

`PersistentIndividualRuntime.projection_for_host()` bridge state hiện hữu vào self-process:

- PersistentInternalState / affect / fatigue / restraint;
- Endogenous drives;
- InteractionEcology;
- RelationalPlan;
- ConversationTrajectory;
- ActiveConcern.

`ContinuousSelfDynamics.tick()` làm concern, thought, tension và commitment decay theo half-life
khác nhau, rồi cập nhật orientation và hai pressure. Vì thế hai giờ im không còn tương đương với
“đóng băng snapshot rồi chờ message tiếp theo”.

State được checkpoint tối đa một lần/phút trong idle projection để restart không xóa mất quá trình
đã xảy ra, nhưng cũng không ghi disk ở mọi cheap tick.

## SELF -> MOTIVE -> CANDIDATE

V77 không chỉ chấm candidate sau khi chúng đã sinh. `subject_initiative_runtime.py` nhận bounded
projection của Continuous Self và có thể materialize tối đa **một** action opportunity có provenance:

- `mood_lift` -> ambient mutter/comment, không hỏi user;
- `keep_company` -> quiet company, không tạo reply debt;
- `reduce_questions` -> inhibition-only, không biến thành speech;
- unfinished thought có gain/pressure đủ cao -> một `share_self_originated_thought`.

Nếu `public_action_pressure` thấp, **không sinh speech candidate**, dù private pressure đang cao.

## Executive / Neuro

Executive semantic appraisal đọc Continuous Self sau handoff, trajectory và Interaction Ecology.
Nó:

- boost silence/body-only khi public pressure thấp;
- giảm social speech khi self-state đang quiet/private;
- không suppress task/repair;
- không suppress direct user turn;
- cho preferred modes của active commitment một soft bias;
- vẫn để Neuro là final arbiter.

Semantic commitments mới:

- `respect_continuous_self_state`;
- `private_cognition_does_not_imply_public_speech`;
- `assistant_output_cannot_self_recharge_motive`.

## PrivateMind / Mental Material

Mỗi mental material thật sự được sinh sẽ gửi một **private-development receipt** vào Persistent
Individual Runtime. Receipt này có summary, cause, source refs, semantic gain và topic id.

Nó không sinh ExpressionUrge. Một thought có thể:

```text
born -> develop -> simmer -> settle -> dormant
```

mà user không bao giờ nghe thấy. Đây là điều cố ý. PrivateMind không còn bị coi như phòng chờ TTS.

## Persistence và migration

State mới mặc định ở:

`<ERIS_HOME>/state/persistent_individual_v77.json`

Nếu chưa có V77 nhưng có `persistent_individual_v76.json`, runtime migrate state V76 sang schema
V77 và tạo `continuous_self` rỗng an toàn. Memory/user model cũ không bị xóa hay copy sang DB mới.

Feature flag:

`ERIS_V77_CONTINUOUS_SELF=1`

Hai đường learning dài hạn từ V76 vẫn mặc định OFF:

`ERIS_V76_SELF_MODEL_LEARNING=0`
`ERIS_V76_HABIT_LEARNING=0`

V77 không tự ý bật personality/habit drift chỉ vì đã có self-process.

## Những gì V77 chưa giả vờ giải quyết

- Không chứng minh ERIS có ý thức.
- Không tạo một self-model ngôn ngữ tự do có quyền sửa core values.
- Không cho LLM tự đổi policy production.
- Không biến curiosity thành quyền hỏi user.
- Không tạo attachment/possessiveness để ép tương tác.
- Không đảm bảo developmental learning tháng/năm đã an toàn; phần đó vẫn cần soak và longitudinal test.

## Cách đánh giá đúng V77

Ngoài unit test, cần quan sát runtime dài:

- user im 2h: self-state có thay đổi mà không spam speech không;
- user nói “làm tôi vui lên”: commitment có sống qua nhiều tick nhưng tự nguội nếu không có support không;
- private thought gain thấp: có chết trong private không;
- private pressure cao/public pressure thấp: Neuro có chọn silence được không;
- restart: commitment/thought/tension causal có giữ được không;
- autonomous speech: public pressure có giảm thay vì tự tăng không;
- direct user request: Continuous Self có bao giờ cản task/repair không.

Đây là bước chuyển từ “nhiều module thông minh” sang một agent có **state trung tâm liên tục và có
nhân quả qua thời gian**. Nó vẫn là software. Ít nhất bây giờ software không cần triệu tập cả quốc hội
mỗi lần user im ba phút rồi giả vờ vừa mới sinh ra.
