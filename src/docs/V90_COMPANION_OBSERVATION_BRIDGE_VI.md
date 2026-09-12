# V90 — Companion Observation Bridge

## Vấn đề V90 giải quyết

V89 giúp Eris ước lượng user tốt hơn, nhưng nếu Eris Desktop và GitPilot là hai runtime tách biệt thì Eris vẫn có thể “mù” với công việc user đang làm.

V90 áp dụng nguyên tắc:

> Tách quyền thực thi, không tách nhận thức.

GitPilot/agent khác vẫn code. Eris chỉ quan sát bằng chứng đã xảy ra và dùng nó để đồng hành/dạy user.

## Ba nguồn evidence

1. **User intent** — câu user vừa gửi coding agent. Đây là nguồn duy nhất từ bridge được phép đi vào skill model.
2. **Agent telemetry** — task/phase/tool/file/test/review nếu coding agent có adapter.
3. **Workspace telemetry** — active file, save/create/delete/rename, diagnostics, terminal command result. Chỉ giúp hiểu tình hình, không chứng minh authorship hay skill.

## Khi GitPilot thật sự tách biệt

V90 không yêu cầu Eris sở hữu GitPilot. Có hai lớp:

- nếu GitPilot đi qua Eris Code client hiện tại, SSE được normalize như V79;
- nếu một coding extension khác có integration, nó có thể gọi `erisCode.companion.observeExternalAgent` để phát event chuẩn hóa;
- nếu không có adapter nào, Eris vẫn nhìn được workspace metadata và terminal/diagnostics nên không hoàn toàn mù.

Không có public API nào để Eris điều khiển coding agent.

## Companion projection

Desktop giữ projection `eris.companion.workspace.v1` gồm:

- workspace/session;
- active file + recent files;
- recent terminal commands và exit status;
- diagnostics gần nhất;
- current user intent;
- current task/agent actor/status;
- provenance source đã quan sát.

Projection này được đưa vào Engineering Mentor prompt context khi còn tươi.

## Skill boundary

`editor_focus`, `file_saved`, `terminal_command` không được dùng để tăng/giảm skill. VS Code không chứng minh ai đã tạo activity đó — có thể là user, formatter, agent hoặc extension.

`user_intent` là lời user explicit nên Mentor có thể dùng để nhận signal như hypothesis, scope, boundary reasoning, verification intent… với evidence ref độc lập.

## Reliability

Transport dùng bounded queue 160 event. Khi nghẽn, metadata dễ tái tạo như focus/diagnostics/save bị drop trước; user intent và agent lifecycle được ưu tiên. Desktop không chạy không được làm coding chậm.
