# ERIS V69 - Expression Consummation / Residual Tension

## Mục tiêu

V69 sửa rumination ở tầng state, không dùng topic blacklist/cooldown. Một concern có thể tiếp tục sống trong private cognition nhưng phần **nhu cầu biểu đạt công khai** của nó có thể đã hoàn tất.

Pipeline mới:

```text
Concern / Mental Material
        ↓
Expression Urge
        ↓
Consummation assessment
(epistemic / expressive / relational completion)
        ↓
Residual tension + receptivity + habituation + self-commitment
        ↓
chỉ desire còn chưa consummate mới thành ExpressionCommitment
        ↓
Neuro / Surface
        ↓
Public receipt
        ↺ cập nhật completion
```

## Ba trục completion

- `epistemic`: Eris đã hiểu vấn đề tới đâu.
- `expressive`: Eris đã nói điều mình muốn nói tới đâu.
- `relational`: trạng thái hiểu nhau / phản hồi từ user đã hoàn tất tới đâu.

Điểm quan trọng: `expressive_completion` chỉ hạ `speech_pressure`, không xóa `activation` hay `persistence` của concern. Vì vậy Eris có thể tiếp tục nghĩ riêng mà không bị ép nói lại.

## Semantic family thay vì duplicate sentence

V69 lưu `SemanticConsummationTrace`. Một paraphrase mới có thể kế thừa completion của ý đã nói nếu:

- semantic concept đủ gần; hoặc
- cùng concern; hoặc
- có provenance nội bộ chung đủ mạnh.

ID nội bộ (`concern`, `material`, `urge`) chỉ được dùng để nhận identity, **không** được tính là evidence mới. Evidence mới phải đến từ user/environment/memory/action/goal/runtime event thật.

## User receptivity

User response cập nhật state của semantic family gần nhất:

- user yêu cầu đổi chủ đề / nói rằng lặp lại nhàm → receptivity giảm, relational completion + habituation tăng;
- user sửa Eris → epistemic completion hạ và reopen credit tăng;
- user chủ động hỏi tiếp đúng semantic family → reopen credit tăng;
- acknowledgement → expressive/relational completion tăng.

Đây không phải `if bored: ban_topic()`. Receptivity tự hồi phục theo thời gian và user/evidence mới có thể mở lại topic.

## Self-commitment

Nếu sau khi user yêu cầu đổi chủ đề Eris nói kiểu "tôi sẽ rẽ sang hướng khác", câu đó trở thành state `self_commitment_away` của semantic family cũ. Candidate cùng family sau đó có commitment conflict cho tới khi user thực sự mở lại hoặc state decay.

Tức là Eris phải chịu trách nhiệm với lời chính mình, thay vì câu "tôi sẽ đổi chủ đề" chỉ là wording đẹp rồi não quay lại nói y hệt một phút sau.

## Concern persistence

`ActiveConcernRuntime.note_public_surface()` ghi completion vào metadata của ConcernStore. Một semantic mutation/evidence mới thật trong `ConcernStore.ingest_cognitive_event()` sẽ giảm completion để concern có thể mở lại tự nhiên.

## Replay case từ log 2026-08-13

Với semantic family "truy vấn trí nhớ có hai lớp":

- sau public expression đầu tiên: residual tension ~0.08;
- sau user nói nghe miết nhàm + yêu cầu đổi chủ đề + Eris tự cam kết rẽ hướng: residual tension ~0.02, self-commitment conflict ~0.88;
- user chủ động mở lại cùng semantic family thì reopen credit hạ inherited satisfaction và bỏ commitment conflict.

## Invariant V67/V68 được giữ

V69 không thêm speech threshold downstream. Một candidate đã có typed `ExpressionCommitment` vẫn thuộc speech family như V67. Consummation diễn ra **trước** bước materialize commitment, vì một desire đã thỏa mãn thì không còn là desire-to-speak nữa.
