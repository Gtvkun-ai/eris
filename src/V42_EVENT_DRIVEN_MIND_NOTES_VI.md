# V42 Event-Driven Mind

## Mục tiêu

V42 không thêm cooldown, blacklist câu chữ hay một lớp “humanizer”. Bản này đổi quan hệ nhân quả của autonomous cognition để cùng một dữ liệu không thể tự được tính là một sự kiện mới chỉ vì scheduler nhìn thấy nó lần nữa.

Luồng chính:

```text
user / seed / memory / world / internal semantic mutation
                         ↓
                   CognitiveEvent
                         ↓
                    Concern state
                         ↓
                       Neuro
                ┌────────┼────────┐
             silence  body_only  speak
                                  ↓
                           SemanticIntent
                                  ↓
                               Surface
```

Nguyên tắc: **một chuyện mới chỉ làm đầu óc Eris đổi đúng một lần**. Tick không phải event.

## 1. CognitiveEvent và idempotency

File mới `cortex/cognitive_event.py` tạo `CognitiveEvent` có `event_id` ổn định và `CognitiveEventLedger` bounded trong session.

Seed `seed.X` luôn thành `cogevt:seed:seed.X`. Scheduler nhìn lại cùng seed không thể tăng recurrence, activation hay pressure lần nữa. ConcernStore còn giữ receipt event trong metadata để chống replay sau khi runtime object được dựng lại.

PrivateMind fragment cũng đi theo cùng tinh thần: cùng `ThoughtFragment.id` quay lại không được tính là một lần suy nghĩ mới.

## 2. Concern: merge chặt, liên quan thì link

V40 gom quá rộng các ý cùng “vibe”, dẫn tới một concern nuốt im lặng, hiện diện, maybe, khoảng trống và các câu hỏi khác nhau.

V42 tách hai thao tác:

- `merge`: chỉ khi gần như là cùng một concern hoặc có provenance độc lập đủ mạnh.
- `link`: hai concern có liên quan nhưng vẫn giữ identity riêng bằng `related_concern_ids`.

Không còn mega-concern chỉ vì embedding thấy chúng thơ giống nhau.

## 3. Echo không phải insight

Một event mới nhưng không có evidence/detail mới là `echo`:

- `echo_streak` tăng;
- pressure giảm;
- uncertainty nhích lên;
- habituation tăng ở projection;
- novelty bị phạt.

Mutation chỉ xảy ra khi có evidence độc lập mới hoặc thought engine chủ động đánh dấu `semantic_mutation=true`. Paraphrase khác chữ không được tự phong thành insight.

## 4. Cắt vòng Surface → seed → Surface

Seed generator chỉ lấy public history từ role `user/human`. Public prose Eris vừa nói không được đưa lại làm cognitive evidence.

Mental event trong PrivateLife có `origin_source=seed_worker` vẫn có thể tồn tại để audit/continuity, nhưng seed worker **không được đọc lại output của chính nó** để tạo seed kế tiếp. Memory resonance/internal event từ nguồn khác vẫn được phép vào context.

`note_public_surface()` chỉ ghi receipt đã surfaced và giảm pressure. Nó không biến câu Surface thành sự kiện nhận thức.

## 5. Neuro là authority thật sự cho social timing

Các yếu tố sau được chuyển thành feature/cost **trước Neuro**:

- `reply_expected`;
- user busy;
- post-user timing;
- cooldown;
- repetition;
- budget pressure;
- recent unsolicited speech.

`InitiativeController.policy_signals()` chỉ tạo typed cost. `SubjectProposal` mang cost đó vào Neuro.

Khi Neuro đã commit `speak`, production path gọi InitiativeController với `committed_by_neuro=True`; controller không được đổi lại thành silence vì cooldown/reply baton nữa.

`AutonomousGroundingValidator` cũng không dùng `reply_expected` làm veto sau Neuro. Sau commit, validator chỉ còn nhiệm vụ provenance/integrity.

## 6. Semantic appraisal timeout không fail-open

V40 có đường:

```text
remote semantic appraisal timeout
→ use fast-gate speak
```

V42 đổi thành:

```text
remote semantic appraisal timeout
→ local typed semantic appraisal
→ merge delta vào Neuro
→ Neuro commit lại một lần
```

Local fallback chỉ đọc state có cấu trúc như interruption cost, reply baton, concern novelty, grounding availability, uncertainty. Nó không giả vờ “hiểu ngôn ngữ” thay DeepSeek.

## 7. Surface chỉ được sáng tạo cách nói, không sáng tạo sự thật

File mới `runtime/claim_domain_contract.py` định nghĩa typed claim domains, ví dụ:

- `internal_state`
- `conversation_history`
- `user_statement`
- `memory`
- `verified_runtime_clock`
- `grounded_environment`
- `opinion`
- `hypothetical`

Cả autonomous Surface và direct chat writer phải trả `claim_manifest`.

Ví dụ một câu về môi trường hiện tại phải khai báo `grounded_environment` và dùng đúng evidence ref được intent/grounding cấp. Không có evidence thì runtime không cho phát.

Không có blacklist “quạt”, “trời”, “phòng”. Runtime kiểm **loại claim + provenance**, không kiểm vài chữ dễ đoán.

Public text có mà thiếu `claim_manifest` cũng fail closed và chỉ được wording retry đúng một lần.

Regex grounding cũ vẫn còn như compatibility backstop, không phải kiến trúc chính V42.

## 8. Dọn trạng thái “Đang chuẩn bị nói...”

Background cognition và random seed reservoir không còn phát public status như:

- `Đang chuẩn bị nói...`
- `Đang nghĩ xem có nên nói...`
- `Đang chuẩn bị chuyện để nói...`

Eris có thể nghĩ nền hoặc im lặng mà không cần treo biển báo 24/7 rằng nó đang cân nhắc có nên mở miệng.

Các status thuộc **public lifecycle thật** như audio buffering sau khi đã có utterance vẫn giữ, vì đó là trạng thái người dùng thực sự cần biết.

## 9. Những gì V42 cố ý không sửa

- Không tiếp tục tune V39 voice prompt.
- Không thêm phrase blacklist/humanizer.
- Không giải bài toán mood dynamics bị gần-frozen trong run V40; affective voice contract vẫn được giữ nguyên. Nếu runtime mới vẫn cho thấy affect state không đổi trước event cảm xúc rõ, đó nên là một bản riêng về mood dynamics, không trộn vào cognitive causality của V42.
- V41 Memory Hygiene + DeepSeek cleanup + Memory Feed Trace được giữ nguyên.

## 10. Log nên quan sát

Tìm các dòng:

```text
[cognitive event] applied ... outcome=created
[cognitive event] applied ... outcome=echo
[cognitive event] applied ... outcome=mutated
[active concern] top ... novelty=... habituation=...
[neuro-commit] ...
[surface claims] ...
[chat claims] ...
```

Behavior tốt cần thấy:

1. cùng một seed chỉ `applied` một lần;
2. tick sau chỉ decay/age, không absorb lại;
3. paraphrase không evidence mới trở thành echo hoặc concern liên quan;
4. echo làm habituation tăng và speech pressure giảm;
5. evidence/internal mutation mới mới có quyền làm concern sống lại;
6. Neuro không commit speak rồi bị social timing veto ở downstream;
7. writer không thể thêm claim môi trường hiện tại nếu intent không cấp domain/evidence.

## 11. Preflight

Sau khi copy source vào repo thật:

```bat
src\tools\prepare_v42_runtime.bat
```

Kỳ vọng:

```text
[V42 PREFLIGHT] PASS: eris.cognition.v42.event_driven | eris.cognitive_continuity.v42.event_driven_concern | eris.claim_domains.v42.typed_surface
```
