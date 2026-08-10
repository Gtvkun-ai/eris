# ERIS Mental Workspace V29

Mục tiêu của thay đổi này là tận dụng `cortex/private_life` như **đời sống bền của Eris**, thay vì để random-chat seed chỉ sống vài phút trong reservoir rồi biến mất.

## Nguyên tắc

- Vẫn chỉ dùng **một DeepSeek seed worker** như trước.
- Seed worker không viết câu public. Nó sinh **MentalEvent** typed.
- MentalEvent được lưu trong `private_life_state.json`, có salience, novelty, curiosity, decay, open-loop và epistemic stance.
- `Surface` phải bảo toàn epistemic stance. Suy đoán vẫn là suy đoán; tưởng tượng vẫn là tưởng tượng; opinion không bị nâng thành fact.
- `Grounding` không được mở rộng thành lưới cấm mọi suy đoán. Fact và bounded inference vẫn phải có kỷ luật, nhưng speculation/imagination/question/research intent là những hoạt động nhận thức hợp lệ.
- Reservoir vẫn nhỏ và nhanh. `private_life` mới là nơi giữ continuity dài hơn.

## MentalEvent mới

Các loại event hiện hỗ trợ:

- `thought`
- `curiosity_question`
- `knowledge_gap`
- `discovery_impulse`
- `speculation`
- `imagination`
- `opinion`
- `association`
- `memory_callback`
- `playful_probe`
- `micro_challenge`
- `unfinished_loop`
- `creative_impulse`
- `self_reflection`
- `prediction`
- `surprise`
- `contradiction_notice`

Epistemic modes:

- `grounded_fact`
- `bounded_inference`
- `speculation`
- `imagination`
- `opinion`
- `question`
- `research_intent`

## Luồng mới

```text
DeepSeek seed worker x1
        |
        v
RandomChatSeed
(event_kind + epistemic_mode + open_loop)
        |
        +--> reservoir 2-4 candidate, session-local
        |
        +--> PrivateLife MentalWorkspace, persistent
                    |
                    +--> decay / reactivation / open-loop
                    |
                    +--> context cho lần seed kế tiếp
                    |
                    +--> discovery planner nếu Eris thực sự muốn biết thứ mới

Governor -> Surface -> public speech
```

## Những hành vi mà thiết kế này cho phép

- `Có khi hôm nay trời đẹp.` là `speculation`, không cần giả thành observation.
- `Anh có biết chiêm tinh không?` có thể là `curiosity_question` từ `endogenous_curiosity`.
- `Tôi muốn xem hôm nay có vụ gì thú vị.` có thể là `discovery_impulse`, giữ open-loop và được Discovery planner nhìn thấy.
- Một chủ đề tò mò có thể quay lại sau nhiều seed nhờ reactivation theo topic tags.
- Negative user response có thể hạ strategy/event fit nhưng không xóa interest riêng của Eris.

## Persistence

`PrivateLifeState.version` được nâng từ 2 lên 3. Loader vẫn đọc state cũ vì field `mental_events` có default rỗng.

Workspace giữ tối đa 64 mental events. Event yếu sẽ chuyển `dormant`; event quá yếu và cũ có thể `expired`. Open-loop được ưu tiên giữ lâu hơn.

## Ghi chú an toàn kiến trúc

`private_life` vẫn không có quyền nói trực tiếp. Mental event chỉ là state/semantic material. Quyền public vẫn đi qua governor và Surface.
