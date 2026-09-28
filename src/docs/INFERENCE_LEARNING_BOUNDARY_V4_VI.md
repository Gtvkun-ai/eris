# ERIS V4 — Tách inference routing và khóa boundary của Learning Kernel

## 1. Vấn đề V4 giải quyết

Trước V4, nhiều nơi dùng chuỗi `subconscious_4b` như thể nó đồng thời có nghĩa:

1. đây là một loại công việc nhận thức nhẹ/chạy nền;
2. đây là model local 4B;
3. request này phải giữ VRAM/cooldown của local 4B;
4. request này nên vào broker lane background.

Bốn điều trên **không phải cùng một khái niệm**.

Ví dụ thực tế của Eris:

```text
TurnAgentLoop
    ↓
DeepSeek executive worker
    ↓
DS2API / Whale2API localhost gateway
    ↓
DeepSeek remote model
```

Gateway có thể nằm ở `127.0.0.1:6011`, nhưng inference thật không chạy trên GPU local. Nếu chỉ nhìn `subconscious_4b`, scheduler có thể giữ 2.2 GB VRAM ảo, áp cooldown 4B và xếp root executive vào background lane dù request đang phục vụ user trực tiếp.

V4 tách rõ các trục này.

---

## 2. Bốn trục inference sau V4

### 2.1 `cognitive_lane`

Trả lời câu hỏi:

> Request này đang làm **vai trò nhận thức gì**?

Ví dụ:

```text
turn_executive

tutor:eris_tutor_diagnosis
tutor:eris_tutor_move
tutor:eris_tutor_assessment
```

`cognitive_lane` ảnh hưởng **broker priority / foreground vs background**, không quyết định VRAM.

### 2.2 `backend`

Trả lời:

> Request đang đi qua transport/provider nào?

Ví dụ:

```text
ds2api_deepseek_web
openai_compatible_remote
local_gguf
```

Backend dùng cho observability, debug và ownership.

### 2.3 `resource_class`

Trả lời:

> Inference này thực sự tiêu thụ tài nguyên ở đâu?

Các giá trị V4:

```text
remote_api
local_light
local_heavy
vision_local
unknown
```

Đây mới là authority để scheduler quyết định:

- local VRAM reservation;
- local heavy-model cooldown;
- conflict với model local đang active.

### 2.4 `inference_tier` / `ModelTier`

Đây là **nhãn legacy compatibility**.

Ví dụ V4 vẫn cho phép:

```text
inference_tier = subconscious_4b
```

nhưng đồng thời:

```text
cognitive_lane = turn_executive
backend = ds2api_deepseek_web
resource_class = remote_api
```

Vì vậy tên `subconscious_4b` không còn đủ quyền để scheduler kết luận request đang dùng local 4B.

---

## 3. DS2API được nhận diện thế nào

`JsonlWorkerClient` trong `llm/deepseek_workers.py` khai báo trực tiếp:

```python
self.inference_backend = "ds2api_deepseek_web"
self.inference_resource_class = "remote_api"
```

Điều này quan trọng vì DS2API gateway thường chạy localhost. Router không được dùng quy tắc đơn giản:

```text
localhost => local model
```

vì quy tắc đó sai với kiến trúc Whale2API/DS2API.

`AIRuntimeModelRouter._client_inference_profile()` ưu tiên metadata explicit từ client. Chỉ khi client cũ chưa có metadata mới dùng compatibility inference.

---

## 4. ModelBudgetPolicy sau V4

### Trước V4

```text
subconscious_4b
    ↓
local heavy
    ↓
4B cooldown
    ↓
4B VRAM reservation
```

### Sau V4

```text
legacy tier: subconscious_4b
resource_class: remote_api
    ↓
không giữ local 4B VRAM
không làm bẩn local 4B cooldown marker
không conflict với active local-heavy lease
```

Nhưng caller legacy không truyền `resource_class` vẫn giữ semantics cũ:

```text
subconscious_4b + no profile
    ↓
local_heavy
```

Như vậy migration không làm mất guard cho model local thật.

---

## 5. Root TurnAgentLoop dùng Executive worker đúng ownership

Trước V4 `RuntimeModelTurnReasoner` ưu tiên:

```text
deep_client / social critic
```

trước dedicated executive worker.

V4 đổi thành:

```text
executive_client
    ↓ fallback
social critic / deep_client
    ↓ fallback
seed / surface / main client
```

Nếu DS2API Executive được cấu hình, root loop thực sự dùng đúng `executive` role.

Fallback vẫn giữ để Eris không chết trong rollout khi credential executive chưa có.

---

## 6. Broker lane không còn suy từ `4B`

Một lỗi tinh vi khác trước V4:

```text
inference_tier == subconscious_4b
    ↓
post_observer
    ↓
optional background lane
```

Điều này không đúng với root agent executive chạy trước public response.

V4 ưu tiên `cognitive_lane`:

```text
turn_executive
    ↓
chat_tool_required
    ↓
required foreground
```

Tutor semantic worker đang phục vụ foreground turn cũng dùng:

```text
tutor:...
    ↓
chat_tool_required
```

Do đó:

```text
vai trò nhận thức -> broker priority
resource class     -> VRAM/cooldown
backend            -> transport/observability
legacy tier        -> compatibility
```

Mỗi owner chỉ quyết đúng một việc.

---

# 7. DeepTutor trong Eris: lấy kernel, không lấy agent

## 7.1 Phần Eris giữ từ DeepTutor-derived design

`runtime/learning_core/` sở hữu các khái niệm deterministic:

```text
KnowledgePoint
LearningPath
LearningEvidence
MasteryRecord
PendingInteraction
ReviewItem

mastery/gate
navigation policy
review scheduling
deterministic choice grading
pending interaction mechanics
```

## 7.2 Phần Learning Kernel KHÔNG được sở hữu

```text
TurnAgentLoop
ConversationDirector
public writer
TTS / voice pacing
social/personality behavior
tool execution
coding/research loop
quyết định có nên tự bật tutor hay không
```

Đây là boundary bắt buộc.

---

## 8. Luồng phối hợp Agent + Tutor + Learning Kernel

```text
USER
 │
 ▼
TurnAgentLoop                       ← root lifecycle duy nhất
 │
 ├── general/coding/research roles
 │
 └── TutorRole
       │
       ▼
   TutorReasoner                    ← đề xuất pedagogical intent
       │
       ▼
ConversationDirector               ← turn này nói bao nhiêu?
       │
       ▼
Public writer / TTS
       │
       ▼
USER RESPONSE
       │
       ▼
Semantic assessor                  ← đề xuất assessment
       │
       ▼
LearningService                    ← deterministic authority
       │
       ├── append evidence
       ├── recompute mastery
       ├── update review
       └── next TutorStep
```

Quy tắc quan trọng:

> **LLM đề xuất; deterministic kernel commit.**

Không có chuyện writer vừa giảng xong rồi tự tăng mastery.

---

## 9. Vì sao không port thêm toàn bộ DeepTutor

Nếu đưa nguyên agent/planner/runtime của DeepTutor vào Eris, hệ thống sẽ có hai owner:

```text
TurnAgentLoop
vs
DeepTutor agent loop
```

Hậu quả dễ xảy ra:

- hai loop tranh quyền WAIT/RESUME;
- hai planner quyết định user đang học gì;
- tutor tự xổ nội dung vượt ConversationDirector;
- learning runtime trở thành một application nằm bên trong application.

V4 cố tình giữ DeepTutor-derived code ở tầng substrate.

---

## 10. License / attribution

Repo V4 bổ sung `THIRD_PARTY_NOTICES.md` tại root với:

- upstream: HKUDS/DeepTutor;
- referenced commit: `ef2d9e5c`;
- license: Apache License 2.0;
- vùng adaptation: `runtime/learning_core/`;
- mô tả ranh giới giữa phần derived và phần Eris-specific.

---

## 11. Compatibility

V4 không yêu cầu rewrite toàn bộ caller ngay lập tức.

Caller cũ:

```python
policy.run_queued("subconscious_4b", func)
```

vẫn được hiểu theo semantics local cũ.

Caller mới qua typed router:

```python
policy.run_queued(
    "subconscious_4b",
    func,
    resource_class="remote_api",
    backend="ds2api_deepseek_web",
    cognitive_lane="turn_executive",
)
```

có semantics chính xác hơn.

Mục tiêu migration dài hạn là giảm dần sự phụ thuộc vào tên `subconscious_4b`, nhưng V4 chưa xoá nó để tránh một big-bang refactor không cần thiết.

---

## 12. Test V4

Các regression mới kiểm tra trực tiếp:

1. DS2API localhost được nhận diện là `remote_api`.
2. `subconscious_4b + remote_api` không bị local GPU/VRAM guard.
3. Remote call không làm bẩn `last_4b_started_at/finished_at`.
4. Remote lease reserve `0 MB` local VRAM.
5. Caller legacy vẫn được hiểu là `local_heavy`.
6. TurnAgent reasoner ưu tiên dedicated `executive_client`.
7. `turn_executive` được broker xếp vào required foreground lane.
8. `learning_core` không import public writer/TTS/root loop.
9. Third-party notice và boundary docs tồn tại.

