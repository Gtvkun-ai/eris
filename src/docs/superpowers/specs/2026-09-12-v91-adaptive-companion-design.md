# ERIS V91 — Adaptive Companion độc lập Extension

## Mục tiêu

Biến Eris thành technical companion dài hạn hiểu người dùng từ chính hội thoại và state nội bộ của Eris, **không phụ thuộc Eris Code/GitPilot** để hoạt động. Coding extension phải chạy đầy đủ khi Eris Desktop không tồn tại; Eris Desktop phải vẫn hiểu user, project và quá trình học khi coding extension không tồn tại.

## Nguyên tắc kiến trúc

1. **Tách quyền và tách runtime thật sự**: Eris Code không gọi Eris Desktop, không gửi telemetry sang Desktop, không đọc context từ Desktop, không có Eris Link trong activation path.
2. **Conversation-first companion**: Eris học “đang làm gì / đang học gì / đang quen gì” chủ yếu từ lời user, memory/life-horizon và evidence user chủ động đưa vào chat.
3. **Skill model là giả thuyết, không phải điểm số con người**: dùng để quyết định bỏ qua kiến thức cơ bản, giải thích sâu bao nhiêu, hoặc khi nào nên challenge nhẹ.
4. **Không gia sư hóa mọi turn**: giao việc nhanh bình thường không bị biến thành bài học. Mentor chỉ chen khi user chủ động học, có misconception lặp lại, hoặc đúng skill user đang muốn phát triển.
5. **Mỉa/trêu có căn cứ**: Companion Brain chỉ phát `teasing_opportunity`; relationship/affective voice vẫn là authority cuối. Không suy từ chửi tục thành đặc điểm tâm lý.
6. **Không hidden surveillance**: repo/diff/log chỉ được dùng khi user chủ động gửi/cho Eris đọc qua kênh Eris; không cần stream workspace nền từ VS Code extension.

## Thành phần

### 1. `runtime/adaptive_companion.py`

Persistent working model nhẹ gồm:
- current activities/projects user nói rõ đang làm;
- learning topics user nói rõ đang học/muốn học;
- familiarity hints (self-report không tự thành mastery);
- projection skill kỹ thuật từ EngineeringMentor nếu đủ confidence;
- response directive theo turn: `companion`, `peer`, `teach_light`, `teach_guided`, `challenge_light`.

State không cố NLP tổng quát. Chỉ lưu khi có marker explicit đủ rõ; còn inference giàu ngữ nghĩa để public model xử lý từ current conversation/memory.

### 2. Public response integration

Mỗi foreground user turn:
- AdaptiveCompanion quan sát câu user;
- đọc LifeHorizon H1/H2/H3 nếu có;
- đọc EngineeringMentor snapshot nếu có;
- xuất một prompt block nhỏ `ADAPTIVE_COMPANION_V91` vào discourse context.

Directive nói **cách cư xử**, không tự viết câu trả lời và không thêm persona mới.

### 3. Engineering Mentor compatibility

Giữ EngineeringMentor để không phá V80→V89, nhưng V91:
- không cần flow GitPilot/workspace mới hoạt động;
- passive external observation không phải input mặc định;
- skill evidence từ conversation vẫn hoạt động;
- role “supervisor” không được ưu tiên chỉ vì extension activity.

### 4. Eris Code decoupling

Loại khỏi đường chạy extension:
- `ErisObserverBridge`;
- `CompanionWorkspaceObserver`;
- `erisCode.erisLink.*` settings;
- publish coding observations sang Desktop;
- read Desktop context để ghép prompt GitPilot.

GitPilot client chỉ phụ thuộc GitPilot runtime + VS Code context local.

## Data contract

`AdaptiveCompanionDirective` tối thiểu:

```json
{
  "schema": "eris.adaptive_companion.v91",
  "stance": "companion|peer|teach_light|teach_guided|challenge_light",
  "teaching_permission": "none|answer_if_asked|light|guided|challenge",
  "explanation_depth": "minimal|normal|deep",
  "teasing_opportunity": "none|light|earned",
  "reason": "...",
  "active_learning_topics": [],
  "active_activities": [],
  "technical_assumptions": {},
  "rules": []
}
```

## Teaching policy

- “làm luôn / triển đi” đơn lẻ → companion, không lecture.
- Explicit “giải thích / tại sao / học / chỉ tôi” → teach guided tùy skill confidence.
- Skill mạnh + câu hỏi kỹ thuật cùng domain → peer; bỏ tutorial nền.
- Candidate misconception đã có evidence → teach_light / challenge_light, một ý chính.
- Repeated AI delegation chỉ đáng challenge khi trùng một learning topic đang active và reasoning-ownership risk đủ cao.
- Frustration/profanity → companion-first; có thể `teasing_opportunity=light`, nhưng không tự chẩn đoán cảm xúc.

## Persistence và privacy

State path mặc định: `${ERIS_STATE_DIR}/adaptive_companion_v91.json`.
Chỉ lưu text fragment ngắn do user nói explicit về activity/learning; không lưu raw transcript dài, source code, terminal output hay telemetry extension.

## Backward compatibility

- V80→V89 mentor API giữ nguyên.
- Capability panel tiếp tục chạy.
- Legacy V79/V90 observer modules có thể còn trong source để rollback nhưng Coordinator V91 không start listener và extension V91 không gọi chúng.
- Không đổi authority của existing memory/relationship/affective systems.

## Acceptance

1. Eris Code compile/typecheck và không chứa runtime reference đến Eris Desktop/Eris Link trong activation/coding path.
2. Eris Desktop startup không mở Eris Code observer listener.
3. Adaptive companion ghi nhận explicit learning/activity, không biến self-report thành mastery.
4. Fast delegation bình thường không trigger lecture.
5. Strong technical evidence làm response stance chuyển peer và bỏ giải thích cơ bản.
6. Teasing opportunity chỉ là cue, không override relationship/affective policy.
7. Existing mentor-focused regression vẫn pass trừ regression V90 observer được thay bằng V91 decoupling tests.
