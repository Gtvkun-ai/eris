# ERIS V40 — Cognitive Continuity / Active Concern

## Mục tiêu

V40 không thêm một “bộ nhớ concern” mới. Repo đã có `PrivateConcern`, `ThoughtStream`, `InternalAgenda` và motive/Subject Core; tạo thêm database nữa chỉ khiến một chuyện bị nhớ thành nhiều bản sao.

V40 thêm **projection `ActiveConcern`** để các subsystem hiện có cùng nhìn thấy một câu hỏi đơn giản: *chuyện nào đang thật sự sống trong đầu ERIS, nó đã sống bao lâu, có biến đổi gì mới, đã nói ra mấy lần và hiện có đáng phá im lặng không?*

Nguyên tắc chính:

- concern **không tự cấp quyền nói**;
- recurrence không đồng nghĩa novelty;
- mutation/evidence mới mới làm novelty hồi lại;
- nói cùng một concern nhiều lần tạo habituation;
- silence không xóa concern;
- user turn vẫn là foreground authority trong direct chat;
- Neuro vẫn là nơi quyết định action cuối, không có downstream “hội đồng cấm nói”.

## Kiến trúc

```text
PrivateConcern ─┐
ThoughtStream  ─┼─> ActiveConcern projection ─> planner / Neuro
InternalAgenda ─┘            │
                             ├─> seed generator context
                             └─> direct chat continuity context
```

`ActiveConcern` là **view**, không phải persistence store. `PrivateConcern` vẫn là persistent concern authority. `ThoughtStream` và `InternalAgenda` chỉ được project tạm thời, không bị copy vào `ConcernStore`.

## Lifecycle mới

Mỗi concern có các signal như:

- `activation`
- `persistence`
- `tension`
- `novelty`
- `habituation`
- `speech_pressure`
- `interruption_cost`
- `recurrence`
- `mutation_count`
- `surfaced_count`
- `trajectory = rising | stable | cooling`
- `state = simmering | reactivated | habituated | watching | blocked`

### Recurrence khác mutation

Nếu cùng một ý quay lại mà không có evidence/câu hỏi/hypothesis mới:

```text
recurrence += 1
reactivation_count += 1
mutation_count giữ nguyên
```

Nếu có evidence/câu hỏi/hypothesis mới:

```text
mutation_count += 1
novelty có thể hồi lại
```

Mục đích là không thưởng cho rumination như thể đó là insight mới.

## Seed không còn là vé xin phát biểu

Một random-chat seed đủ chất lượng có thể được **absorb vào `PrivateConcern` trước khi Neuro chọn speak/silence**. Seed được nhập concern không có nghĩa là được nói ngay.

Seed paraphrase khác ID được semantic-merge vào concern đang có, để “một chuyện” giữ một identity thay vì reservoir đổi vài chữ rồi đẻ một concern mới.

Seed generator cũng nhìn `active_concerns`:

- được phép collision bằng association, contradiction, evidence mới hoặc câu hỏi mới;
- không được chỉ paraphrase concern cũ;
- concern đã habituated mà không mutation nên ưu tiên `decision=none` hoặc khám phá event khác;
- recurrence tự nó không phải novelty.

## Neuro nhìn continuity trước commit

`AutonomousProposalSource` semantic-match proposal với active concern. Nếu match, proposal mang thêm:

- `active_concern_id`
- `concern_state`
- `concern_trajectory`
- `concern_activation`
- `concern_novelty`
- `concern_habituation`
- `concern_speech_pressure`
- `concern_mutation_count`

Các signal này điều chỉnh **utility/cost trước Neuro commit**. Không có hard gate mới.

Seed vừa mới nhập concern còn non-urgent nhận một incubation bias mềm, đủ để “ủ” ý thay vì cứ seed → nói ngay. Urgency cao vẫn có thể thắng.

## Sau khi thực sự nói

Chỉ khi public speech commit thành công, concern persistent mới nhận receipt:

```text
surfaced_count += 1
last_surfaced_at = now
pressure *= 0.82
```

Concern không bị auto-resolve. Lần sau cùng concern sẽ có habituation cao hơn nếu chưa có mutation mới.

## Direct chat

Direct chat nhận cùng `active_concerns` snapshot với autonomous. Đây chỉ là continuity context.

User turn hiện tại vẫn là foreground authority. Concern không được quyền lôi chuyện cũ ra thay cho việc trả lời user.

## Log đáng xem

V40 thêm log dạng:

```text
[active concern] absorbed id=... source=seed kind=...
[active concern] top id=... state=... activation=... novelty=... habituation=... speech=... trajectory=... sources=...
[active concern] surfaced id=... count=... pressure=...
```

Khi test dài, dấu hiệu tốt là cùng một `concern_id` có thể sống qua nhiều tick, reactivated/mutate rồi mới surface, thay vì mỗi tick một seed ID khác nhau.

## File chính thay đổi

- `cortex/active_concern.py` — projection/model/semantic merge V40.
- `runtime/active_concern_runtime.py` — tích hợp host, absorb seed, snapshot, public-surface receipt.
- `cortex/private_mind/contracts.py` — tách recurrence/reactivation khỏi mutation.
- `cortex/private_mind/concern_store.py` — lifecycle metadata + semantic merge judgment.
- `runtime/subject_proposals.py` — đưa concern features vào proposal trước Neuro.
- `runtime/subject_ingress.py` — truyền planning context cho proposal source.
- `runtime/ai_orchestrated/self_context.py` — active concerns vào self context.
- `runtime/ai_orchestrated/self_turn_pipeline.py` — absorb seed trước Subject/Neuro và ghi surface receipt sau commit.
- `runtime/ai_orchestrated/orchestrator.py` — direct chat đọc cùng projection.
- `runtime/ai_orchestrated/random_chat_seed_service.py` — seed worker nhìn concern history thay vì chỉ recent seeds.
- `runtime/coordinator_bootstrap.py` — khởi tạo `ActiveConcernRuntime`.
- `tests/test_v40_active_concern.py` — regression V40.

## Deploy

Sau khi copy source V40 vào repo thật, chạy một lần:

```bat
src\tools\prepare_v40_runtime.bat
```

Kỳ vọng:

```text
[V40 PREFLIGHT] PASS: eris.cognitive_continuity.v40.active_concern | eris.affective_voice.v39.state_authority
```

Sau đó mới chạy `run_eris.bat`.

## Test thủ công quan trọng nhất

1. Nói một chủ đề có open question thật.
2. Kết thúc chat và để im.
3. Quan sát một seed liên quan được absorb thành concern nhưng **không nhất thiết nói ngay**.
4. Đưa evidence/context mới vài phút sau.
5. Kiểm tra cùng concern ID được reactivated/mutate.
6. Khi Eris nói, kiểm tra `surfaced_count` tăng.
7. Nếu cùng concern lại xuất hiện mà không có mutation mới, `habituation` phải tăng và `speech_pressure` giảm.

Golden behavior là: **một ý có thể tồn tại, đổi hình, nguội đi, bật lại và chỉ đôi khi mới trở thành lời nói.**

## Validation tại thời điểm đóng gói

- V40 focused regression: 10/10 pass.
- Broad Neuro/seed/Surface/social/V38/V39 regression: 161/161 pass sau thay đổi recurrence/mutation cuối.
- Full suite của repo vẫn có failure baseline đã biết ở `test_deepseek_multi_worker_base.py::test_research_client_no_longer_falls_back_to_main_or_fallback`; V40 không sửa lane research vì ngoài scope.

