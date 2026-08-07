# Eris V19: Temporal Mind

## Mục tiêu

V18 đã thống nhất quyền quyết định quanh `MindLoop`, `Subject Core` và Executive, nhưng runtime autonomous vẫn mang hình dạng **turn-based**: một thay đổi nhỏ có thể đánh thức cả chuỗi context → candidate → Executive → Subject finalize rồi mất nhiều giây chỉ để kết luận `silence`.

V19 không thêm một “bộ não” mới. Nó thêm một **state timing rẻ** đứng trước deliberation nặng để quản lý *khi nào đáng suy nghĩ sâu*, không quản lý *nên nghĩ gì*.

Nguyên tắc:

- im lặng là mặc định, không cần LLM phê duyệt;
- tín hiệu yếu tích lũy theo thời gian và tự decay;
- cùng một evidence revision không được cộng pressure vô hạn qua mỗi tick;
- nghĩa vụ rõ như `force`, `structured_due`, `followup_due` có thể wake ngay;
- user turn, public act và autonomous share cùng một temporal state;
- Temporal Mind không được tạo motive, fact, memory hay semantic commitment.

## Luồng mới

```text
cheap runtime facts
    ↓
TemporalMind.observe()
    ├─ quiet_default / cooldown
    │      ↓
    │   cheap tick 0.8–6s
    │   KHÔNG gọi Executive LLM
    │
    └─ wake
           ↓
       Executive.should_reconsider()
           ↓
       Subject Core + Executive deliberation nặng
           ↓
       speak / body_only / silence
           ↓
       TemporalMind cập nhật nhịp
```

Temporal Mind chỉ là scheduler stateful. Executive vẫn là semantic authority; Subject Core vẫn là nền nhân quả và nơi finalize/learning.

## File mới

### `runtime/temporal_mind.py`

Các type chính:

- `TemporalSignal`: envelope rẻ cho event timing;
- `PendingTemporalSignal`: residue theo kind/source/revision;
- `TemporalMindState`: activation, tension, readiness, focus và các mốc thời gian;
- `TemporalGateDecision`: wake/quiet cùng reason và thời gian check tiếp;
- `TemporalMind`: decay, accumulation, cooldown và public/user transitions.

State không chứa raw chain-of-thought hay nội dung private. `prompt_context()` chỉ xuất projection timing nhỏ, ví dụ cadence/readiness/pending event kinds.

## Thay đổi autonomous

`SelfTurnPipeline._should_deliberate()` vẫn dựng `ExecutiveEvent` có provenance như V18, nhưng trước khi hỏi policy của Executive nó chuyển các event thành `TemporalSignal`.

### Tín hiệu yếu

`attention_pressure`, `seed_available`, `scene_delta`, `activity_event` không tự động gọi Executive model. Chúng tăng activation theo trọng số và decay nếu không có bằng chứng mới.

### Dedupe theo revision

Một event `scene_delta` revision 12 xuất hiện lại ở nhiều tick không được coi là 12 sự kiện mới. Repeat contribution bị giảm mạnh; pressure cũ chỉ được duy trì rồi decay.

### Hard wake

Các event sau có thể wake ngay nếu strength đủ cao:

```text
force
user_turn
structured_due
followup_due
```

`user_turn` chủ yếu được dùng ở transition chung; direct chat vẫn đi qua chat runtime riêng.

### Sau silence

Trước V19, autonomous silence thường sleep 8–24 giây sau khi đã mất chi phí deliberation nặng. V19:

1. `mark_silence()` giảm activation;
2. tạo cooldown 8 giây;
3. loop quay về cheap tick sau khoảng 2.5 giây;
4. trong cooldown, Temporal Mind chặn deliberation nặng nhưng state vẫn decay/cập nhật.

### Sau public act

Public act tạo cooldown riêng và giảm activation thay vì coi lượt vừa kết thúc là “não đã tắt”. Autonomous quay lại cheap sensing sau khoảng 3.5 giây.

## Chat và continuity thời gian

`ChatCycleMixin` gọi `TemporalMind.note_user_turn()` ngay khi user turn bắt đầu. Public commit của cả chat và autonomous gọi `note_public_act()`.

Nhờ vậy cùng một state biết:

- user vừa chen vào lúc nào;
- public act gần nhất lúc nào;
- focus hiện tại;
- pressure nào còn dư;
- khi nào đang trong cooldown.

Chat planning nhận `timing_context` ở field riêng. Nó **không** được đưa vào `grounding_context`, vì timing không phải evidence.

Projection chỉ nhắc Surface:

- clause đầu nên ngắn và tự đủ nghĩa;
- không thêm filler chỉ để tỏ ra phản hồi nhanh;
- silence không cần lời giải thích.

## Điều V19 cố ý KHÔNG làm

### Không phát câu đệm giả trước khi hiểu

V19 không spawn thread để nói “ừm…”, “đợi chút…” trong khi model còn đang chạy. Làm vậy có thể giảm cảm giác latency nhưng tạo một nguồn public act không có semantic commitment, đúng kiểu chữa nhịp bằng cách thêm NPC filler.

### Không sửa latency của provider

Nếu một direct user turn phải chờ model/provider 10–20 giây thì V19 không thể biến network inference thành 300 ms. Nó loại bỏ **deliberation nặng không cần thiết ở autonomous** và giữ temporal continuity; TTFT direct chat vẫn cần streaming/provider optimization riêng nếu log cho thấy đó là bottleneck.

### Không đổi Subject learning

Không thay need weights, value formation, consolidation, memory retrieval hay competence. V19 chỉ đổi thời điểm cognition nặng được đánh thức.

## Tuning mặc định

```text
activation half-life = 18s
pending half-life    = 24s
wake threshold       = 0.56
heavy cooldown       = 5s
silence cooldown     = 8s
public cooldown      = 6s
max pending signals  = 12
```

Các số này là scheduling constants, không phải personality traits. Không tự học trực tiếp để tránh lịch sử âm thầm biến scheduler thành một personality knob.

## Trace mới

Autonomous trace có event:

```text
temporal_gate
  wake
  reason
  score
  activation
  dominant_kind
  pending_kinds
  next_check_seconds
```

`attention_skip` cũng đính kèm temporal snapshot rút gọn. Có thể kiểm tra trực tiếp xem một lần `silence` đắt tiền có còn xảy ra do weak repeated event hay không.

## Phiên bản

```text
package = 0.82.0
subject algorithm = subject-service-v10-mind-loop (không đổi)
temporal algorithm = temporal-mind-v1
```

## Kiểm thử

Direct regression:

```text
75 passed
```

Bao gồm TemporalMind, autonomous presence, Executive authority/Gemma hardening và toàn bộ `tests/subject`.

Broad suite có thể collect từ archive:

```text
841 passed
6 failed do input V18 thiếu file/module ngoài thay đổi V19
3 collection errors do input V18 thiếu tools modules
```

Các dependency thiếu đã có từ archive đầu vào:

- `tools.package_source`
- `tools.evaluate_social_plan_activation`
- `tools.report_pdf_acceptance`
- `tools.evaluate_semantic_paraphrases`
- `tools.audit_remote_inference_paths`
- `tools.audit_semantic_authority_paths`
- `body/SubjectPerformanceFrame.cs`

## Tiêu chí kiểm tra thực tế sau khi chạy

V19 đáng giữ nếu log production cho thấy:

1. số lượt Executive autonomous kết luận `silence` giảm mạnh;
2. weak repeated event tạo `temporal:quiet_default` thay vì model call;
3. structured continuation/follow-up vẫn wake đúng hạn;
4. user input vẫn preempt autonomous bình thường;
5. không tăng autonomous chatter;
6. CPU cheap tick chấp nhận được;
7. latency direct chat không bị tăng.

Nếu số 1–5 không đạt thì nên chỉnh state machine này, không thêm một planner mới lên đầu nó. Loài người đã thử giải coordination bằng cách thêm quản lý đủ nhiều rồi.
