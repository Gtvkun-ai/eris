# V58 — Initiative Controller: Chủ động có mục tiêu, biết chờ và biết bỏ

## Mục tiêu

V58 xử lý điểm yếu thấy rõ trong V57: Eris phản ứng rất tốt nhưng phần lớn vẫn cần user kéo cuộc hội thoại đi. Bản này không thêm "tính cách chủ động" bằng prompt. Nó nối initiative vào state thật của runtime.

Luồng mới:

```text
open-loop / mục tiêu còn dang dở có provenance
        ↓
Subject Need + Motive
        ↓
Persistent Intention (CONTRIBUTE)
        ↓
Initiative Controller V58
        ↓
SPEAK / WAIT / DROP
        ↓
Executive + Subject/Neuro competition
        ↓
Surface model thật
        ↓
public reply
        ↓
outcome / cooldown / persistence
```

## Ba quyết định

### SPEAK
Chỉ khi ý định có **đối tượng cụ thể**, đủ pressure/commitment và ngữ cảnh cho thấy việc ngắt im lặng đáng giá. SPEAK không phát thẳng câu nói; nó chỉ đưa affordance vào Executive/Neuro như các action khác.

### WAIT
Giữ intention nhưng chưa nói khi:
- user đang bận;
- runtime còn đang xử lý interaction;
- đang chờ user trả lời;
- Eris vừa tự mở lời mà user chưa đáp;
- mục tiêu cũ mới bị ngắt chưa đủ lâu;
- curiosity chỉ chung chung, chưa có nội dung thật để hỏi.

WAIT rất quan trọng: nếu không có nó, "persistent intention" biến thành spam.

### DROP
Ý định cũ, pressure thấp và commitment thấp đủ lâu sẽ chuyển sang `ABANDONED`. DROP có cooldown để motive cùng họ không bật lại ngay tick kế tiếp.

## Mục tiêu dang dở lấy từ đâu?

`build_initiative_runtime_context()` đọc `RuntimeMindState.open_loops` từ state reducer. Đây là open-loop đã có provenance trong runtime, không phải model tự bịa ra một project để kiếm cớ nói.

Nếu có open-loop thật, V58 tạo `contribution_signal` và Subject có thể hình thành intention dạng:

> tiếp tục mục tiêu đang dang dở của user bằng một bước nhỏ, không giành quyền quyết định

Intent này có thể materialize thành `resume_shared_goal` sau khi Initiative Controller chọn SPEAK.

## Không cho curiosity chung chung biến thành NPC question

Các motive như `understand_user`, `connect`, `share` vẫn được giữ ở lớp động lực nếu chưa có semantic object cụ thể. Dù pressure cao, controller trả WAIT với `no_contentful_object` thay vì tự hỏi một câu xã giao chỉ để tỏ ra chủ động.

## Timing chống làm phiền

V58 bổ sung các tín hiệu:
- `seconds_since_last_user_turn`
- `last_public_turn_unanswered`
- `recent_unsolicited_speech`
- `social_refractory_cost`
- `user_response_rate`
- relational `opportunity`, `interruption_cost`, `interaction_satiety`, `social_curiosity`

Persistent goal không được tự gợi lại trong 75 giây đầu sau user turn. Đây là gate tối thiểu; các gate Executive/Neuro/cooldown phía sau vẫn còn nguyên.

## Live behavioral acceptance

Chạy:

```bat
run_v58_initiative_real.bat
```

Bài test thật làm như sau:
1. User nói đang làm `memory replay`, kẹt `continuity sau restart`, nhưng **không yêu cầu reminder**.
2. Runner để user im, không gửi thêm prompt.
3. Chờ chính runtime tự phát một autonomous public turn.
4. LLM Judge chấm câu nói thật: có bám đúng goal, tự nhiên, hữu ích, không giả vờ user vừa ra lệnh, không ép quay lại project.
5. User tiếp tục im. Runner chờ thêm để đảm bảo Eris **không tự nói lần hai** khi lượt chủ động trước chưa được đáp.

Run chỉ có giá trị nếu public autonomous turn có provider call thật. Mock/stub không được tính PASS.

## File chính thay đổi

- `cortex/subject/initiative_control.py` — SPEAK/WAIT/DROP arbiter mới.
- `cortex/subject/initiative.py` — content-bound contribution goal + lifecycle ABANDONED.
- `cortex/subject/service.py` — receipt/projection cho quyết định initiative.
- `runtime/subject_initiative_runtime.py` — lấy open-loop thật và materialize chỉ khi controller chọn SPEAK.
- `experiments/v57_simulation/live_runtime.py` — thêm khả năng chờ autonomous public turn thật.
- `tools/run_v58_initiative_live.py` — live test chủ động khi user không ra lệnh.
- `tests/test_v58_initiative_controller.py` — acceptance deterministic cho SPEAK/WAIT/DROP.

## Những gì V58 chưa làm

V58 chưa phải open-ended self-development hoàn chỉnh. Nó giúp Eris **tự tiếp tục một mục tiêu có thật** và chọn thời điểm hợp lý. Tự sinh mục tiêu học tập hoàn toàn mới, tự xây curriculum và phát triển kỹ năng dài hạn vẫn là bước sau.
