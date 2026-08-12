# ERIS V44 — Contentful Initiative / Expression Urge

## Mục tiêu

V43 làm mood sống lại, nhưng log thật cho thấy Eris vẫn giống NPC: relational drive rất cao mà Neuro thường chọn silence; khi được nói thì upstream lại chủ yếu đưa `contact_bid` / `user_probe`, nên Surface buộc phải sinh những câu kiểu “dạo này bạn có gì thú vị không?”.

V44 không giảm ngưỡng silence và không thêm timer ép nói. Nó đổi thứ được đưa vào cạnh tranh:

```text
thought / concern / memory / task / finding có nội dung
                     ↓
              ExpressionUrge
        content + motive + pressure
                     ↓
                    Neuro
          ┌──────────┼──────────┐
        hold       body_only   express
                                ↓
                         SemanticIntent
                                ↓
                             Surface
```

Nguyên tắc: **connection pressure chỉ làm một ý đã tồn tại mạnh/yếu hơn; nó không được tự phát minh topic để bắt chuyện.**

## 1. Không tạo “desire database” mới

`ExpressionUrgeRuntime` là projection ngắn hạn trong session trên:

- `ActiveConcern` đã có;
- seed/thought/affordance có semantic content thật;
- mood hiện tại của V43;
- relational state hiện tại.

Urge không được persist thành memory chỉ vì nó chưa nói ra. Restart có thể làm mất urge ngắn hạn, còn concern/memory gốc vẫn là state bền hơn và có thể project lại sau.

## 2. Motive và content là hai tầng khác nhau

Các motive như:

- `understand_user`;
- `connect`;
- `share`;

vẫn được giữ trong Subject Core. Nhưng chúng **không tự materialize thành public speech**.

Sai:

```text
connection_pressure=.88
→ contact_bid
→ Surface phải nghĩ ra một câu hỏi xã giao
```

Đúng:

```text
connection_pressure=.88
+ một thought cụ thể còn mắc trong đầu
→ urge của thought đó mạnh hơn một chút
→ Neuro cân express/hold
```

## 3. Generic contact/probe không còn là content

Các speech act chung chung như:

- `contact_bid`;
- `user_probe`;
- `social_check_in`;
- `curiosity_bid`;

không được coi là public content chỉ vì relationship muốn tiếp xúc.

Structured continuation thật, task thật, explicit `force_speak`, conversation arc có semantic binding vẫn giữ identity riêng. V44 chỉ loại đường “muốn gần user ⇒ tự bịa câu mở đầu”.

## 4. Curiosity mặc định là chia sẻ một ý, không phải phỏng vấn user

Một curiosity có nội dung được project mặc định thành:

```text
share_self_originated_thought
```

thay vì tự động thành câu hỏi.

Surface vẫn có thể dùng câu hỏi nếu semantic intent thật sự cần user input, nhưng “tò mò” không còn đồng nghĩa “hãy hỏi user thêm một câu”.

## 5. Urge có pressure, freshness và satisfaction

Mỗi urge có tối thiểu:

- `expression_pressure`: lực muốn biểu đạt;
- `freshness`: mức còn mới;
- `satisfaction`: đã được biểu đạt/thỏa mãn đến đâu;
- `echo_count`: cùng ý bị paraphrase lại bao nhiêu lần;
- `evidence_refs`: evidence nào thực sự nuôi ý này;
- `concern_id`: nếu urge bắt nguồn từ concern.

Nếu Neuro giữ lại, pressure có thể tăng nhẹ theo thời gian. Nhưng freshness phai và echo bị trừ, nên nó không biến thành timer tăng vô hạn.

Sau public commit thật:

```text
satisfaction ↑
base_strength ↓
freshness ↓
```

Nếu Surface fail hoặc Neuro chọn silence thì urge **không** bị tính là đã nói.

## 6. Paraphrase không tạo desire mới

V42 đã chặn cùng `CognitiveEvent` bị apply nhiều lần, nhưng DeepSeek vẫn có thể đổi chữ và tạo seed ID mới quanh cùng một ý.

V44 thêm semantic merge ở tầng expression:

```text
same meaning + same evidence
→ same urge
→ echo_count ↑
→ freshness ↓
```

Có evidence mới thật:

```text
same meaning + new independent evidence
→ same urge được reinforce
→ freshness/strength có thể tăng
```

Như vậy một nhà máy seed hơi quá năng suất không tự biến thành ba coalition public cho cùng một ám ảnh.

## 7. Desire là utility dương trước Neuro

`expression_pressure` không phải telemetry trang trí. Nó được đưa vào proposal và Neuro score **trước commit**.

Urge mạnh/fresh tăng utility của speech; satisfaction làm giảm utility. Sau đó các cost V42 vẫn trừ bình thường:

- reply đang chờ;
- user busy;
- interruption;
- recent unsolicited speech;
- cooldown/repetition policy.

Không có “urge ⇒ speak”. Neuro vẫn có thể giữ lại.

Test V44 có case cố ý dựng một frame nơi silence thắng khi không có urge, nhưng cùng contentful speech thắng khi pressure đủ mạnh. Không thay silence threshold.

## 8. Mood V43 modulate desire, không tạo topic

Mood có thể điều biến urge:

- curiosity cao làm urge explore mạnh hơn;
- playfulness làm urge playful mạnh hơn;
- social energy cao/thấp đổi một phần pressure;
- relational connection/outreach làm contentful urge dễ được mang sang user hơn.

Mood **không được tự tạo content** và không nới grounding.

## 9. Temporal wake cũng chuyển sang content-first

V43 có thể wake bởi relational/initiative pressure trừu tượng. V44 bỏ đường đó.

TemporalMind chỉ nhận `expression_urge` khi đã có một urge có nội dung đủ lực. Seed mới, external event, structured continuation vẫn có wake source riêng như trước.

Không có content thì relationship pressure 0.99 vẫn có thể yên.

## 10. Subject Core không bị bỏ

Subject motives vẫn sống, tiếp tục ảnh hưởng state/needs/relationship. V44 chỉ rút quyền **tự biến motive trừu tượng thành lời**.

`be_understood`, `seek_recognition` và các intention có semantic object thật vẫn có thể materialize theo contract riêng.

## 11. Log nên xem khi test thật

Tìm:

```text
[expression urge] top id=... motive=... pressure=... fresh=... satisfaction=... echoes=... content=...
[neuro-fast] ... action=speak|silence ...
[expression urge] expressed id=... satisfaction=... remaining=...
```

Behavior tốt:

1. Eris có thought/concern cụ thể, Neuro có thể im vài tick nhưng urge vẫn còn;
2. nếu context vẫn hợp, pressure tăng nhẹ và có thể thắng silence;
3. khi nói, nội dung là chính thought/callback/opinion đó, không tự biến thành generic check-in;
4. sau khi nói, urge nguội rõ;
5. paraphrase cùng evidence không tạo thêm urge;
6. chỉ có connection pressure mà không có content thì không phát sinh `contact_bid/user_probe`;
7. user đang bận/chờ reply vẫn có thể làm Neuro chọn hold dù urge mạnh.

## 12. File chính thay đổi

- `runtime/expression_urge_runtime.py` — projection urge, semantic merge, pressure/freshness/satisfaction.
- `runtime/ai_orchestrated/self_turn_pipeline.py` — content-first shaping, wake, public receipt.
- `runtime/subject_initiative_runtime.py` — generic Subject motive không tự thành câu hỏi/contact.
- `cortex/subject/service.py` — pending generic motive không tự tạo speech proposal.
- `runtime/subject_proposals.py` — expression pressure đi vào proposal trước Neuro.
- `cortex/subject/neuro_control.py` — urge là utility dương, timing/policy cost vẫn giữ.
- `runtime/ai_orchestrated/social_initiative.py` — typed fields cho expression urge.
- `runtime/ai_orchestrated/executive_cortex.py` — giữ urge identity khi materialize committed decision.
- `runtime/coordinator_bootstrap.py` — tạo session projection runtime.
- `tests/test_v44_contentful_initiative.py` — regression mới.
- `tests/subject/test_unified_subject_initiative_v26.py` — cập nhật invariant cũ vốn bảo vệ NPC probe.

## 13. Deploy

Sau khi copy source V44 vào repo thật:

```bat
src\tools\prepare_v44_runtime.bat
```

Kỳ vọng:

```text
[V44 PREFLIGHT] PASS: eris.initiative.v44.contentful_urge | eris.affect.v43.event_driven | eris.cognition.v42.event_driven
```

## 14. V44 cố ý không làm gì

V44 không:

- giảm silence threshold;
- thêm timer “cứ N giây phải nói”;
- random chatter;
- humanizer hậu kỳ;
- phrase blacklist;
- tạo desire database mới;
- cho mood hoặc relationship tự bịa topic.

Mục tiêu không phải Eris nói nhiều. Mục tiêu là **khi Eris thật sự có một thứ muốn mang sang phía user, cái desire đó phải có lực trong quyết định; khi không có gì, im lặng vẫn tự nhiên.**
