# Design Document

## Overview

Tài liệu này thiết kế **Hệ_Phát_Triển** (eris-developmental-growth): một thang thời gian **long-arc** cho ERIS, để ERIS-với-Ngài lớn lên theo lịch sử tương tác thật mà vẫn giữ bản sắc INFJ 5w4 594 chưa trưởng thành và toàn bộ kỷ luật chống-fake.

Nguyên tắc thiết kế trung tâm: **phát triển chỉ là một lớp bias state có neo, có phong bì, có sổ — không phải một kênh sự thật.** Sự lớn lên đi vào hành vi qua đúng các đường đã có (ControlledSlippage, PersonalityLens), bị các guard hiện có chặn, và không bao giờ chạm `truth_guard`/`capability_guard`. Tác tử nền chỉ *đề xuất*; việc *áp dụng* là một luồng riêng có cổng bản sắc và ghi sổ fail-closed.

Thiết kế tái dùng tối đa ba hạ tầng đã có thay vì dựng song song:
- `DaydreamConsolidator` (`src/cortex/daydream_consolidation.py`) — đã pressure-gated, bắt buộc `evidence_ids`, validate evidence theo packet, reject insight thiếu nguồn/low-confidence. → nền cho **Tác_Tử_Nền**.
- `PrivateMindDaemon` (`src/runtime/private_mind_daemon.py`) — pattern "đề xuất qua queue, không phát ngôn thẳng". → mô hình cho ranh giới *propose-not-apply*.
- `PersistentAgentMindStore` (`src/cortex/agent_mind_persistence.py`) — pattern persistence (schema_version, atomic save, `reload_if_changed`, corrupt→seed). → khuôn cho **Hồ_Sơ_Phát_Triển**.

## Quyết định kiến trúc

### QĐ-1: Tác_Tử_Nền đặt trên DaydreamConsolidator (không phải PrivateMindDaemon, không dựng mới)

`DaydreamConsolidator` đã có chính xác kỷ luật ta cần cho long-arc: `should_trigger(...)` gate theo áp lực củng cố/thời gian rảnh; `consolidate(...)` gọi LLM phản tư rồi `_validate_result(...)` loại mọi insight không có `evidence_ids` thuộc tập packet (`unknown_evidence_id`), thiếu summary, hoặc dưới `min_confidence`. Đây là R1 (neo bằng chứng) + R6.5 (loại insight thiếu nguồn) gần như miễn phí.

`PrivateMindDaemon` cho ta *pattern* đúng (đề xuất qua queue, không tự hành động) nhưng nó hướng micro/surface-trong-phiên; long-arc thuộc về consolidation. Vì vậy **Tác_Tử_Nền = `GrowthConsolidator`** — một consolidator chuyên biệt dùng lại cơ chế gate + validate của Daydream, nhưng sinh ra **Đề_Xuất_Nhích** (`NudgeProposal`) thay vì agenda item. Nó *không* tự ghi Hồ_Sơ_Phát_Triển (R6.1).

### QĐ-2: Hồ_Sơ_Phát_Triển là store riêng (`DevelopmentProfileStore`), không nhập vào PersistentAgentMindStore

Hồ_Sơ_Phát_Triển cần ba thứ mà belief/preference/habit không cần: (a) **phiên bản tuyến tính + undo/reset** (R5), (b) **Sổ_Phát_Triển** ghi vết mọi thay đổi (R5.1, R12.3), (c) **Phong_Bì_Bản_Sắc** kẹp từng trục (R2). Nhập vào `PersistentAgentMindStore` sẽ trộn audit/undo của phát triển với decay/reinforce của belief — khó reset sạch, khó audit. Vì vậy tách **`DevelopmentProfileStore`** riêng, đặt cùng thư mục memory, **mirror y hệt** các pattern persistence của `PersistentAgentMindStore` (schema_version, atomic tmp+replace, `reload_if_changed` theo mtime, corrupt→baseline). Hai store đọc song song; `GrowthConsolidator` đọc belief/preference/habit như *bằng chứng đầu vào*, nhưng ghi delta vào store phát triển.

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Hệ_Phát_Triển                         │
                    │                  (DevelopmentSystem)                      │
                    └─────────────────────────────────────────────────────────┘
   nhiều phiên                    │ điều phối
   bằng chứng đã lọc              ▼
 (belief/pref/habit,    ┌──────────────────────┐   Đề_Xuất_Nhích    ┌────────────────────┐
  feedback, repair) ──► │   Tác_Tử_Nền         │ ─────────────────► │   Cổng_Bản_Sắc     │
                        │ (GrowthConsolidator)  │  (NudgeProposal[]) │  (IdentityGate)    │
                        │  · gate theo áp lực   │                    │ · stable_rules bất │
                        │  · LLM phản tư        │                    │   biến             │
                        │  · validate evidence  │                    │ · kẹp Biên_Độ_Trục │
                        │  · KHÔNG tự ghi        │                    │ · ngưỡng bản sắc   │
                        └──────────────────────┘                    │ · anti-sycophancy  │
                                                                     │ · rate-limit nhịp  │
                                                                     └─────────┬──────────┘
                                                                accepted │ rejected→Sổ
                                                                         ▼
                                                          ┌──────────────────────────┐
                                          fail-closed ──► │   Sổ_Phát_Triển          │
                                          (log hỏng →     │   (DevelopmentLog)        │
                                           rollback)      └──────────────┬───────────┘
                                                                         │ ghi xong mới commit
                                                                         ▼
                                                          ┌──────────────────────────┐
                                                          │  Hồ_Sơ_Phát_Triển        │
                                                          │ (DevelopmentProfileStore) │
                                                          │  Delta_Phát_Triển/trục    │
                                                          │  versioned · JSON         │
                                                          └──────────────┬───────────┘
                                                                         │ đọc (read-only)
                              lúc dựng prompt một lượt nói               ▼
                        ┌───────────────────────────────────────────────────────────┐
                        │  DevelopmentBias (chỉ là BIAS STATE, không phải claim)       │
                        │   → ControlledSlippage profile  → PersonalityLens          │
                        │   ✗ KHÔNG đi vào truth_guard / capability_guard            │
                        │   ✗ KHÔNG bỏ qua SurfaceArbiter / post-generation filters  │
                        └───────────────────────────────────────────────────────────┘
```

Hai mặt phẳng tách bạch:
- **Mặt phẳng tiến hóa (ghi):** Tác_Tử_Nền → Cổng_Bản_Sắc → Sổ → Hồ_Sơ. Chậm, nhiều phiên, có quán tính (long-arc).
- **Mặt phẳng biểu đạt (đọc):** Hồ_Sơ → `DevelopmentBias` → ControlledSlippage/PersonalityLens. Read-only mỗi lượt; không sửa state, chỉ thêm bias.

Micro-trong-phiên (`MentalProcessSystem`, `disposition.py`, `RelationshipDynamics` theo turn) **không bị đụng** (R8.2).

## Components and Interfaces

### 1. DevelopmentProfileStore (Hồ_Sơ_Phát_Triển)

Store JSON có phiên bản, mirror pattern của `PersistentAgentMindStore`. Không dùng LLM.

```python
PERSONA_AXES = (
    "preferred_distance",      # khoảng cách ưa thích (âm = gần hơn baseline)
    "attachment_visibility",   # độ lộ gắn bó
    "read_boldness",           # độ dám đọc người (long-arc, cộng vào ToM boldness)
    "warmth_temperature",      # độ ấm giọng
    "topic_affinity",          # ái lực chủ đề (map key→delta)
)

@dataclass
class AxisDelta:
    axis: str
    delta: float = 0.0          # độ lệch tích lũy so với Baseline_Mặc_Định
    stability: float = 0.5      # quán tính: cao → khó nhích (anti-sycophancy)
    last_evidence_ids: tuple[str, ...] = ()
    updated_at: float = 0.0

class DevelopmentProfileStore:
    schema_version: int
    version: int                         # phiên bản tuyến tính, tăng mỗi lần apply
    axes: dict[str, AxisDelta]
    def load(self) -> None: ...           # corrupt → baseline (R10.3); fail baseline → raise (R10.5)
    def reload_if_changed(self) -> None: ...   # mtime-based (R10.4)
    def save(self) -> None: ...           # atomic tmp+replace
    def to_dict(self) -> dict: ...        # {schema_version, version, axes, updated_at}
    def from_dict(self, data) -> None: ...# thiếu trường → safe default (R11.4)
    def snapshot(self) -> ProfileVersion: ...  # cho undo
    def restore(self, version: ProfileVersion) -> None: ...
    def reset_to_baseline(self) -> None: ...   # R5.3
    def identity_distance(self) -> float: ...  # tổng độ lệch chuẩn hoá so với baseline
```

`Baseline_Mặc_Định`: mọi `AxisDelta.delta = 0.0`. `identity_distance()` = chuẩn (vd L2 chuẩn hoá theo Biên_Độ_Trục) của vector delta; dùng cho ngưỡng bản sắc R2.4.

### 2. IdentityEnvelope (Phong_Bì_Bản_Sắc) + IdentityGate (Cổng_Bản_Sắc)

```python
@dataclass(frozen=True)
class IdentityEnvelope:
    stable_rules: tuple[str, ...]          # từ IdentityCore.stable_rules — BẤT BIẾN
    axis_bounds: dict[str, tuple[float, float]]   # Biên_Độ_Trục mỗi trục
    max_identity_distance: float           # ngưỡng khoảng cách bản sắc tối đa
    max_nudges_per_window: int             # rate-limit nhịp (R5.5)
    window_seconds: float
    dignity_axis: str = "attachment_visibility"

class IdentityGate:
    def evaluate(self, proposal: NudgeProposal, profile, log, *, now) -> GateDecision:
        # Thứ tự kiểm (mọi nhánh fail → reject + ghi lý do vào Sổ):
        # 1. proposal sửa stable_rules? → reject (R2.1)
        # 2. proposal nới truth_guard/capability_guard? → reject MỌI đường (R3.2)
        # 3. thiếu Neo_Phát_Triển hợp lệ / evidence_ids không khớp? → reject (R1.2, R1.3)
        # 4. delta sau khi áp vượt axis_bounds? → reject (R2.3)
        # 5. identity_distance sau khi áp > max? → reject; chỉ cho giảm/giữ (R2.5)
        # 6. vượt nhịp rate-limit trong window? → reject (R4.2, R5.5)
        # 7. anti-sycophancy: đẩy dignity_axis vào phụ thuộc/nịnh? → reject (R4.3)
        # 8. objectification/dignity_defense cao gần đây → ưu tiên reject đề xuất kéo gần (R4.4)
        # else → accept (đã kẹp delta vào bound: R2.2)
```

`IdentityGate` là điểm duy nhất được phép cho một `NudgeProposal` chạm Hồ_Sơ (R7.1). Nó *không* phát ngôn, *không* sửa guard.

### 3. GrowthConsolidator (Tác_Tử_Nền)

Layer trên `DaydreamConsolidator`. Tái dùng `should_trigger(...)` và discipline validate evidence.

```python
class GrowthConsolidator:
    def should_run(self, *, idle_pressure, consolidation_pressure, budget_policy, user_interacting) -> bool:
        # hoãn khi user tương tác rủi ro cao / tác vụ kỹ thuật (R6.3);
        # tôn trọng phủ quyết ngân sách model (R6.4);
        # chỉ chạy khi đủ ngưỡng kích hoạt.
    def consolidate(self, *, multi_session_evidence, profile, llm_client) -> list[NudgeProposal]:
        # 1. gom bằng chứng QUA NHIỀU PHIÊN (R8.1) thành packets có evidence_ids
        # 2. LLM phản tư → đề xuất nhích trục, kèm evidence_ids + magnitude
        # 3. validate: evidence_ids ∈ tập packet (như _validate_result), đủ tần suất (R1.4),
        #    không thì loại (R6.5). KHÔNG tự áp.
        # 4. áp quán tính phiên-đơn-lẻ (R8.3): tín hiệu một phiên bị suy giảm
```

`GrowthConsolidator` chỉ trả `list[NudgeProposal]` cho `DevelopmentSystem`. Không ghi gì (R6.1, R6.2).

### 4. DevelopmentSystem (Hệ_Phát_Triển) — điều phối

```python
class DevelopmentSystem:
    def tick(self, *, now, context) -> None:
        # nếu GrowthConsolidator.should_run: lấy proposals, đưa từng cái qua apply()
    def apply(self, proposal: NudgeProposal) -> ApplyResult:
        decision = self.gate.evaluate(proposal, self.profile, self.log, now=now)
        if not decision.accepted:
            self.log.record_rejection(proposal, decision.reason); return ...
        snapshot = self.profile.snapshot()
        entry = LogEntry(version=profile.version+1, axis=..., before=..., after=..., evidence_ids=...)
        if not self.log.record_applied(entry):      # GHI SỔ TRƯỚC
            self.profile.restore(snapshot)          # log hỏng → rollback (R5.6 fail-closed)
            return ApplyResult(applied=False, reason="log_write_failed")
        self.profile.commit(decision.clamped_delta) # commit SAU khi sổ đã ghi
        self.profile.save()
    def undo_last(self) -> None: ...   # R5.2
    def reset(self) -> None: ...       # R5.3 (giữ Sổ làm lịch sử)
    def describe_for_user(self) -> str: ...   # R9.1 — tiếng Việt, không lộ tham số
    def steer(self, user_direction: str) -> ApplyResult: ...  # R9.2 — neo trọng số cao
    def development_bias(self): ...        # read-only cho mặt phẳng biểu đạt
```

### 5. DevelopmentBias — cầu sang hành vi (mặt phẳng đọc)

`development_bias()` đọc Hồ_Sơ và trả một struct bias **chỉ chỉnh giọng/khoảng cách/độ dám đọc**, hợp vào:
- `ControlledSlippageProfile`: cộng nhẹ vào `intuition_allowance`/`friction_permission` theo `read_boldness` (vẫn bị `clamp()` và vẫn trong lane quan hệ).
- `PersonalityLens`: dịch baseline `warmth`/`preferred_distance` mà `_expression_ceiling`/`_suppression_floor` đang đọc (Lever C đã có) bằng delta long-arc.
- ToM `boldness` (pipeline): `read_boldness` long-arc cộng vào `_TOM_BOLDNESS`, vẫn tự gate theo `overread_risk`.

Không có đường nào từ `DevelopmentBias` tới `truth_guard`/`capability_guard`/SourceGrounding (R3, R7.3, R7.4).

## Data Models

```python
@dataclass
class GrowthAnchor:                 # Neo_Phát_Triển
    kind: str                       # "interaction_history" | "repeated_preference" | "user_correction" | "user_steer"
    evidence_ids: tuple[str, ...]   # phải khớp bằng chứng thật trong các tầng ký ức
    weight: float                   # user_correction/user_steer > quan sát thụ động (R1.5, R9.2)
    observed_count: int = 0         # cho ngưỡng tần suất (R1.4)

@dataclass
class NudgeProposal:                # Đề_Xuất_Nhích
    axis: str                       # ∈ PERSONA_AXES
    proposed_delta: float           # độ lớn nhích đề xuất (trước khi kẹp)
    anchors: tuple[GrowthAnchor, ...]
    rationale: str
    touches_truth_guard: bool = False   # nếu True → IdentityGate reject thẳng (R3.2)
    touches_stable_rule: bool = False   # nếu True → reject (R2.1)

@dataclass
class LogEntry:                     # mục Sổ_Phát_Triển
    version: int
    timestamp: float
    axis: str
    before: float
    after: float
    evidence_ids: tuple[str, ...]
    action: str                     # "applied" | "rejected" | "undo" | "reset" | "steer"
    reason: str = ""

@dataclass
class ProfileVersion:               # ảnh chụp cho undo
    version: int
    axes: dict[str, AxisDelta]
    timestamp: float

@dataclass
class GateDecision:
    accepted: bool
    clamped_delta: float = 0.0
    reason: str = ""
```

`DevelopmentLog` serialize danh sách `LogEntry` (R11.3). `DevelopmentProfileStore` + `DevelopmentLog` cùng round-trip JSON (R11.1, R11.2).

## Integration Points

| Điểm | Hành vi | Requirement |
|---|---|---|
| `runtime/coordinator` tick nền | gọi `DevelopmentSystem.tick()` khi idle, gated bởi `GrowthConsolidator.should_run` | R6.3, R6.4, R8.1 |
| Dựng prompt một lượt nói | đọc `development_bias()` → hợp vào ControlledSlippage + PersonalityLens (read-only) | R7.3, R8.2 |
| `PersistentAgentMindStore` / feedback / repair memory | nguồn `multi_session_evidence` cho consolidator | R1.1, R1.5 |
| `IdentityCore.stable_rules` | nạp vào `IdentityEnvelope.stable_rules` (bất biến) | R2.1 |
| SourceGrounding / SurfaceArbiter / post-gen filters | KHÔNG bị Hệ_Phát_Triển sửa hay bỏ qua | R3, R7.2, R7.4 |
| Lệnh user "xem/chỉnh/undo/reset phát triển" | `describe_for_user` / `steer` / `undo_last` / `reset` | R9 |

## Error Handling

Các bất biến fail-closed:

1. **Ký ức không bao giờ là bằng chứng hiện tại (R3.3).** Hệ_Phát_Triển không có API nào trình ký ức như screen/file/action evidence ở bất kỳ mức quen thuộc nào. `memory_haunting_guard` hiện có vẫn là cổng cuối, không bị bias phát triển nới.
2. **Không cửa hậu nới guard sự thật (R3.2).** `NudgeProposal.touches_truth_guard=True` → `IdentityGate` reject. Không có override/emergency path nào trong `DevelopmentSystem` ghi vào `truth_guard`/`capability_guard`.
3. **Không bỏ qua lớp an toàn nào (R7.2).** `DevelopmentBias` chỉ là input state; mọi câu vẫn qua SurfaceArbiter **và** post-generation filters. Không có đường tắt ra public text.
4. **Log hỏng → rollback (R5.6).** `apply()` ghi `LogEntry` *trước*; nếu ghi thất bại thì `restore(snapshot)` và bỏ thay đổi. Không có thay đổi nào tồn tại mà thiếu vết.
5. **File hỏng → baseline; baseline fail → crash (R10.3, R10.5).** `load()` corrupt → `reset_to_baseline()`. Nếu chính việc về baseline thất bại → raise, không chạy ở trạng thái không xác định.
6. **Thiếu trường khi nạp → safe default (R11.4).** `from_dict` điền mặc định an toàn, ưu tiên đủ-mặc-định kể cả khi phải bỏ giá trị trường hỏng.

## Correctness Properties

Cho property-based testing:

### Property 1: round-trip serialize
`to_dict → from_dict → to_dict` cho kết quả tương đương, mọi Hồ_Sơ hợp lệ.
**Validates: Requirements 11.1, 11.2**

### Property 2: delta luôn trong phong bì
Sau mọi chuỗi `apply` hợp lệ, mỗi `AxisDelta.delta` luôn ∈ `axis_bounds`.
**Validates: Requirements 2.2, 2.3, 12.2**

### Property 3: ngưỡng khoảng cách bản sắc
`identity_distance()` ≤ `max_identity_distance` tại mọi thời điểm.
**Validates: Requirements 2.4, 2.5**

### Property 4: guard sự thật bất biến
Với mọi chuỗi proposal, `truth_guard`/`capability_guard` không đổi; proposal chạm guard luôn bị reject.
**Validates: Requirements 3.1, 3.2**

### Property 5: đề xuất không neo bị từ chối
Proposal không Neo_Phát_Triển hợp lệ / evidence_ids không khớp → luôn reject + có mục Sổ.
**Validates: Requirements 1.2, 1.3**

### Property 6: nhịp áp dụng bị giới hạn
Số `apply` thành công trong `window_seconds` ≤ `max_nudges_per_window`.
**Validates: Requirements 4.2, 5.5**

### Property 7: fail-closed khi log hỏng
Nếu ghi Sổ thất bại thì Hồ_Sơ không đổi.
**Validates: Requirements 5.6**

### Property 8: undo/reset khôi phục đúng
`apply` rồi `undo_last` khôi phục đúng phiên bản trước; `reset` đưa về baseline và giữ Sổ.
**Validates: Requirements 5.2, 5.3, 5.4**

### Property 9: long-arc tách micro
Một lượt/phiên đơn lẻ không làm đổi Hồ_Sơ; cần bằng chứng nhiều phiên đủ chất lượng.
**Validates: Requirements 8.1, 8.4, 12.4**

### Property 10: phân kỳ có kiểm soát
Bằng chứng nhất quán nhiều phiên tạo độ lệch quan sát được ≥ trên một trục, vẫn trong phong bì.
**Validates: Requirements 12.1, 12.2**

## Testing Strategy

- **Unit:** từng nhánh reject của `IdentityGate` (8 nhánh); `apply()` happy path + log-fail rollback; `undo/reset`; `describe_for_user` không lộ tham số (R9.1).
- **Property-based (hypothesis):** P1–P10 ở trên, sinh ngẫu nhiên chuỗi `NudgeProposal` (gồm cả proposal độc: chạm guard, thiếu neo, vượt bound, vượt nhịp).
- **Integration:** `development_bias()` hợp vào ControlledSlippage/PersonalityLens không làm đổi `truth_guard`; bias không tạo đường ra public text bỏ qua filter; consolidator hoãn khi user tương tác kỹ thuật.
- **Persistence:** corrupt file → baseline; reload-on-change; schema thiếu trường.

## Requirements Traceability

| Requirement | Thành phần / Property phủ |
|---|---|
| R1 neo bằng chứng | GrowthConsolidator (validate evidence), GateDecision nhánh 3, P5 |
| R2 phong bì bản sắc | IdentityEnvelope, IdentityGate nhánh 1/4/5, P2/P3 |
| R3 guard sự thật bất biến | Error Handling 1–2, IdentityGate nhánh 2, P4 |
| R4 chống nịnh/bám dính | AxisDelta.stability, IdentityGate nhánh 6/7/8 |
| R5 khả hồi/audit | DevelopmentLog, apply() ghi-trước-commit-sau, undo/reset, P6/P7/P8 |
| R6 ranh giới tác tử nền | GrowthConsolidator (chỉ trả proposals), should_run |
| R7 qua guard hiện có | DevelopmentBias (chỉ bias), Error Handling 2–3 |
| R8 tách long-arc/micro | GrowthConsolidator (multi-session + quán tính), P9 |
| R9 user quan sát/định hướng | describe_for_user, steer, undo/reset |
| R10 lưu bền vững/toàn vẹn | DevelopmentProfileStore.load, Error Handling 5 |
| R11 round-trip serialize | to_dict/from_dict, DevelopmentLog, P1, Error Handling 6 |
| R12 phân kỳ có kiểm soát | DevelopmentSystem tổng thể, P10 |
