# ERIS V91 — Adaptive Companion độc lập extension

## Một câu để hiểu V91

**Eris theo user, không theo coding agent.**

Eris Code/GitPilot là công cụ coding độc lập. Eris Desktop là companion riêng: hiểu user đang làm gì, đang học gì, thường reasoning theo kiểu nào và cần được nói chuyện/dạy ở mức nào.

## Luồng mới

```text
                     USER
              ┌───────┴────────┐
              │                │
        ERIS DESKTOP       ERIS CODE
        Companion          GitPilot client
              │                │
      conversation +       VS Code context
      memory + horizon          │
      + mentor evidence       GitPilot
              │
       Adaptive Companion
```

Không có mũi tên bắt buộc từ Eris Code sang Desktop.

## Eris biết user bằng cách nào?

### 1. Conversation hiện tại

Ví dụ user đi từ:
- "sao nó lao xuyên tường"
- "có phải perception không"
- "visibility và aggro memory nên tách"

Eris có thể dùng cách user reasoning như evidence. Không cần biết GitPilot vừa gọi tool gì.

### 2. Current activities / Life Horizon

V91 lấy active H1-H3 có sẵn của Eris làm context: project nào đang làm, conversation goal nào còn dang dở.

### 3. Explicit learning context

Khi user nói "tôi đang học C#/.NET", V91 ghi một learning topic compact. Đây chỉ là "đang học", tuyệt đối không tự biến thành mastery.

### 4. Engineering evidence đã có

Nếu EngineeringMentor đã có nhiều evidence độc lập rằng user mạnh root-cause reasoning, Adaptive Companion có thể chuyển sang **peer stance** và bỏ tutorial cơ bản.

## Eris dạy kiểu gì?

V91 không có một mode "gia sư" cố định.

- `companion`: nói trực tiếp, không lecture.
- `peer`: tranh luận ngang hàng, bỏ basic tutorial.
- `teach_guided`: user chủ động muốn học thì giải thích có cấu trúc.
- `challenge_light`: chỉ dùng khi user đang học đúng chủ đề đó nhưng liên tục outsource reasoning; yêu cầu user tự khóa đúng một mắt xích nhỏ.

Ví dụ:

> User: "làm luôn cái icon đi"
>
> Eris: không dạy. Đây không phải learning failure.

Nhưng nếu user đã nói đang học root-cause debugging và reasoning-ownership risk đã cao:

> User: "làm luôn bug root cause này đi"
>
> Eris được phép challenge nhẹ: yêu cầu user nói một hypothesis/boundary trước, rồi vẫn giúp tiếp.

## Mỉa mai/trêu

Adaptive Companion chỉ nói "đây là một cơ hội trêu nhẹ". Nó không có quyền ép Eris mỉa.

Authority cuối vẫn là:
- relationship state;
- affective voice;
- social boundary / user opt-out.

Nhờ vậy mỉa mai xuất hiện vì quan hệ/context phù hợp, không phải vì một regex thấy user chửi tục.

## Privacy / coupling boundary

Adaptive Companion state không lưu:
- raw transcript dài;
- source code;
- terminal output;
- editor focus/save telemetry;
- GitPilot hidden reasoning.

State chỉ giữ compact explicit context như learning topic/activity và technical assumptions đã được evidence model xác nhận.

## Extension V91

Eris Code 0.22.0 không biết Eris Desktop:
- không Eris Link;
- không POST telemetry;
- không GET project context từ Desktop;
- không observer workspace cho companion;
- không phụ thuộc Desktop startup/port/state.

Nếu Desktop chết, coding vẫn chạy. Nếu extension chết, Eris vẫn là Eris.
