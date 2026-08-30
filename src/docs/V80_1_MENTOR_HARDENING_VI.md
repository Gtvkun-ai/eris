# V80.1 — Mentor Hardening

## V80.1 giải quyết chuyện gì?

V80 đã cho Eris biết **khi nào một tình huống coding có giá trị để dạy user**. Nhưng nếu cứ thấy một vấn đề là Eris chen vào giảng, nó sẽ nhanh chóng thành một ông thầy lắm mồm.

V80.1 không làm Eris code giỏi hơn. Nó làm Eris **biết lúc nào nên im**.

Luồng vẫn giữ nguyên:

```text
GitPilot -> Coding Observation V79 -> Engineering Mentor V80/V80.1 -> public conversation
```

Eris không được quyền điều khiển GitPilot, approve tool, sửa file hoặc chạy terminal từ Mentor.

---

## 1. Policy và delivery được tách riêng

Có hai câu hỏi khác nhau:

1. **Có điều gì đáng dạy không?** — `EngineeringTeachingPolicy`
2. **Có nên nói nó ngay lúc này không?** — `MentorInterventionLedger`

Ví dụ GitPilot vừa patch trước khi inspect. Policy kết luận đây là một teachable failure. Nhưng nếu Eris vừa giải thích đúng bài đó cách đây hai phút, delivery gate sẽ chọn **im**.

Điều này quan trọng vì "Eris hiểu" không đồng nghĩa với "Eris phải nói".

---

## 2. Chống lặp bài giảng

Mỗi bài dạy được tạo một `lesson signature` từ:

- reason;
- skill đang tập trung;
- coding-flow finding.

Không dùng raw chat để tạo journal học tập.

Mặc định, cùng một lesson signature chỉ được proactive nhắc lại sau **20 phút**.

User chủ động hỏi kiểu:

- "chỉ tôi";
- "giải thích";
- "review giúp";
- "tại sao";

thì cooldown không chặn. User muốn học thì Eris vẫn dạy.

---

## 3. Intervention budget

Trong một cửa sổ 30 phút, Eris chỉ được chủ động chen tối đa **3 mentor interventions**.

Mục tiêu không phải giới hạn khả năng trả lời. Khi gate suppress mentor, Eris vẫn chat bình thường; chỉ phần "stance của thầy" không được inject vào public writer.

Một `warn` quan trọng có thể vượt budget một lần, nhưng cùng warning vẫn bị lesson cooldown chặn để Eris không mắng lặp.

---

## 4. User có thể bảo Eris bớt dạy

Nếu sau một intervention user nói gần nghĩa:

```text
đừng giảng
khỏi dạy
biết rồi
cứ làm đi
```

V80.1 coi đây là feedback cho mentor, không phải bằng chứng user kém.

Kết quả:

- proactive mentoring pause 30 phút;
- explicit learning vẫn hoạt động bình thường;
- câu "cứ làm đi" trong ngữ cảnh từ chối bài giảng không làm tăng `overreliance_risk`.

Đây là điểm quan trọng: **user từ chối một bài giảng không đồng nghĩa user đang vibe-code mù**.

---

## 5. User có thể yêu cầu nói ngắn

Nếu user phản hồi kiểu:

```text
nói ngắn thôi
ngắn thôi
dài quá
gọn thôi
```

mentor chuyển sang `verbosity=compact` trong phiên hiện tại.

Directive cho public writer là:

- tối đa một ý dạy chính;
- một hành động cụ thể;
- không lặp lecture vừa nói.

Eris vẫn có thể trả lời dài ở các chủ đề khác; đây chỉ là preference tạm thời cho Engineering Mentor.

---

## 6. Session-aware

V80.1 dùng session mềm theo thời gian.

Nếu user không tương tác hơn **2 giờ**, mentor mở session mới và reset:

- lesson cooldown;
- proactive intervention budget;
- pause tạm thời;
- compact preference tạm thời.

Không cần tạo thêm account/session service.

---

## 7. Feedback loop nhưng không tự chấm điểm user bừa

V80.1 nhận một số feedback rất hẹp:

- `mentor_opt_out`;
- `mentor_prefer_concise`;
- `mentor_understood`.

`mentor_understood` chỉ có nghĩa user nói họ đã hiểu. Nó **không tự động tăng skill score**. Muốn tăng skill vẫn cần evidence như hypothesis kỹ thuật, trace cụ thể hoặc verification behavior.

Nhờ vậy Eris không tự phong user thành expert chỉ vì user nói "ừ hiểu rồi".

---

## 8. Evaluation log

File mặc định:

```text
<ERIS_HOME>/mentor/engineering_mentor_evaluation.jsonl
```

Nó chỉ lưu metadata như:

```json
{
  "event": "decision",
  "allowed": false,
  "signature": "...",
  "mode": "challenge",
  "suppression_reason": "same_lesson_cooldown"
}
```

Hoặc feedback:

```json
{
  "event": "feedback",
  "signals": ["mentor_prefer_concise"]
}
```

Không lưu:

- raw chat;
- source code;
- chain-of-thought;
- token/API key.

Evaluation log được rotate khi đạt khoảng **2 MiB**, chỉ giữ một backup `.1` để không tăng dung lượng vô hạn.

---

## 9. State để audit

`GET /v1/mentor/state` từ V80 vẫn dùng được. Snapshot V80.1 có thêm:

```text
runtime
├─ session_serial
├─ session_started_at
├─ proactive_pause_until
├─ compact_until
├─ recent_interventions
└─ recent_feedback
```

Endpoint vẫn read-only. V80.1 không thêm write/control route.

---

## 10. Boundary cần giữ cho V81

V80.1 chỉ harden delivery. Không nên nhét teach-back, quiz, spaced repetition vào đây.

Bước V81 sau này mới có thể dùng các signal `mentor_understood`, lesson history và user skill evidence để tạo adaptive learning.

Nguyên tắc giữ nguyên:

> Eris quan sát, hiểu, dạy và quản lý việc học. GitPilot vẫn là coding brain.
