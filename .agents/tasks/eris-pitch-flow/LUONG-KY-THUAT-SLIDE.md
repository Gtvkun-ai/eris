# ERIS: LUỒNG KỸ THUẬT CHO SLIDE (file để bạn tự chỉnh)

Mọi code trong file này copy từ repo. Chỗ nào có `...` nghĩa là tôi bỏ dòng, không viết lại.
Chỗ nào ghi [CHƯA KIỂM] là tôi chưa đối chiếu với code hôm nay.

---

## 0. ĐÁNH GIÁ BẢN DECK TRƯỚC

**Đọc "sao sao" vì 4 lỗi:**

1. **Không có một luồng chung.** Slide 4 vẽ 8 trạm, ba slide sau nói ba cơ chế, nhưng không slide nào chỉ ra cơ chế đó nằm ở trạm nào. Người nghe nhận ba mẩu rời, không nhận một cỗ máy.
2. **Ba thứ bạn gọi tên không có sơ đồ.**
   - Hệ thần kinh nhận thức (lane): chỉ có bảng 2 cột.
   - Vòng nhận thức có kiểm soát (Root loop): bị nén thành một dòng chữ.
   - Learning kernel: 3 ô mũi tên, không cho thấy kernel chặn cái gì.
3. **Vài câu nói quá tay so với code:**
   - "Không bao giờ tắt tiếng": chỉ đúng khi TTS còn chạy. Đường báo lỗi cố định chỉ kích hoạt ở lượt `user_turn` (kernel.py gọi `_deliver_runtime_failure` trong nhánh `user_turn`).
   - "Chỉ 2 trạm gọi model": sai. Localizer (trong Writer), Tutor reasoner và observer nền cũng gọi model. Đúng là 5 trạm điều phối (ngõ vào, kernel, ngữ cảnh, kiểm cuối, cửa phát) là code thuần. Trạm ngữ cảnh tôi vừa grep `context_assembler.py`, không có lời gọi model.
   - "Phần lớn AI né bằng cách không dám tự chủ": không kiểm chứng được, bỏ.
4. **Code trên slide đã bị tôi rút gọn.** Dòng `if move.kind in { "explain", "repair", ... }` do tôi viết lại, không phải nguyên văn. Giám khảo bảo mở file là lộ.

**Đáng giữ:** khung "ba lỗi của AI tự chủ" (nói đè / nói dối / im lặng), timeline generation, máy trạng thái biên nhận, câu chuyện HOTFIX.

**Cách ghép với ba cụm từ của bạn:**

| Cụm từ bạn dùng | Chặn lỗi nào | Nằm ở đâu trên luồng |
|---|---|---|
| Vòng nhận thức có kiểm soát | nói đè, nói dối | Root, Kernel, biên nhận |
| Hệ thần kinh nhận thức | im lặng | mọi lời gọi model |
| Learning kernel deterministic | nói dối trong hồ sơ học | gia sư, ghi tiến độ |

Khung "ba lỗi" là lý do. Ba cụm từ của bạn là lời giải. Hai lớp này không chồng nhau.

---

## 1. SƠ ĐỒ TỔNG: MỘT LƯỢT NÓI, VÀ BA CƠ CHẾ NẰM Ở ĐÂU

```
NGƯỜI HỌC (chat / giọng nói)
   │
   ▼
┌─ ① KERNEL ───────────────────────────────────────────────┐
│ generation + 1 ngay lập tức → lượt cũ hết hiệu lực        │ ◄── [A] vòng nhận thức:
│ hủy nói tiếp · cấp run_id                                 │      chống NÓI ĐÈ
└──────────────────────────────────────────────────────────┘
   │  ngữ cảnh: danh tính · trí nhớ · bằng chứng (code thuần)
   ▼
┌─ ② ROOT · mỗi bước đúng 1 hành động ─────────────────────┐
│ nhớ lại │ nghĩ thêm (≤2) │ ghi chú │ GỌI GIA SƯ ──┐       │ ◄── [A] phanh:
│ trước mỗi bước: lượt này còn hiệu lực không?       │       │      12 bước · 2 bước
│ chốt: move { ý định · điều cần nói · sau đó } / im  │       │      không tiến triển
└────────────────────────────────────────────────────┼───────┘
   │ move                                              ▼
   │                                    ┌─ ③ LEARNING KERNEL ─────────────┐
   │                                    │ model đề xuất → khung ép →       │ ◄── [C] LLM đề xuất,
   │                                    │ kernel chốt (ngưỡng 0,68)        │      kernel chốt
   ▼                                    └──────────────┬──────────────────┘
④ WRITER (chữ Việt + giọng Nhật)                       │ TutorAdvice (không kèm đáp án)
   │ delivery_id cấp TRƯỚC khi viết                    │
   ▼                                                    │
⑤ KIỂM CUỐI: generation / run_id còn khớp? lệch → hủy   │
   ▼                                                    │
⑥ CỬA PHÁT DUY NHẤT: TTS + Live2D + phụ đề             │
   ▼                                                    │
⑦ BIÊN NHẬN: delivered? ──────► Tutor.commit_delivery ◄─┘   ◄── [A] chống NÓI DỐI:
                      └──────► về Root ở bước/lượt sau            "đã dạy" chỉ khi phát xong

╔══ [B] HỆ THẦN KINH NHẬN THỨC: chạy dưới TẤT CẢ các ô có chữ "model" ══╗
║ mỗi lời gọi model được xếp làn theo VAI TRÒ → làn bắt buộc không bị cắt  ║
╚═════════════════════════════════════════════════════════════════════════╝
```

Cách dùng trên slide: vẽ sơ đồ này làm slide "luồng tổng". Ba slide sau phóng to từng ô [A], [B], [C], mỗi slide giữ đúng nhãn đã đánh ở đây.

---

## 2. CƠ CHẾ A: VÒNG NHẬN THỨC CÓ KIỂM SOÁT

### A1. Root loop (slide "Root không trả lời, Root quyết từng bước")

```
            ┌────────────── kết quả + biên nhận ──────────────┐
            ▼                                                  │
 ngữ cảnh ─► [ BƯỚC k ] ── chọn đúng 1 hành động ──┬─ recall_memory ───┤ đọc trí nhớ, public-safe
              │ lượt còn hiệu lực?                  ├─ use_capability ──┤ tutor · research · work · action
              │ user chen lời → NoReply             ├─ continue_thinking (≤ 2 lần, không phát lời)
              ▼                                     └─ set_note / clear_note
        CHỐT: move { intent · say · delivery · after }   hoặc   no_reply
```

**Ba phanh:**

| Phanh | Điều kiện | Nguồn |
|---|---|---|
| Trần cứng | tối đa 12 bước, mặc định 8, tối thiểu 2 | `max(2, min(12, int(max_root_steps or 8)))` |
| Cắt sớm | 2 bước liền không có kết quả có nghĩa | `stop = streak >= 2` |
| Nghĩ thầm | `continue_thinking` tối đa 2 lần | `reflection_state["count"] > 2` |

Code nguyên văn (`src/runtime/conversation/agent.py`):

```python
# max_root_steps là trần CỨNG TUYỆT ĐỐI: clamp 2..12, không bao giờ bỏ.
self.max_root_steps = max(2, min(12, int(max_root_steps or 8)))
...
reflection_state["count"] = reflection_state.get("count", 0) + 1
if reflection_state["count"] > 2:
    ...
    return {"kind": "reflection_result", "status": "limit_reached", "next": "finalize"}
...
_NON_PROGRESS_STATUSES = frozenset(
    {"duplicate", "empty", "failed", "limit_reached", "unavailable", "invalid"}
)
```

Điểm nói: "trần cứng là phanh tài nguyên, không phải giới hạn văn phong". Câu này nằm ngay trong docstring của class.

### A2. Chen lời: generation (slide timeline)

```
Lượt cũ  gen 7:  Root đang chờ model ─► TTS đang đọc ─► callback TTS tới trễ ✗ bị loại
User chen lời :  gen 7 → 8 NGAY ───────► lượt mới chạy sạch
```

Code nguyên văn (`src/runtime/conversation/kernel.py`, nhánh `user_turn`):

```python
# Đổi generation TRƯỚC: callback TTS cũ tới đồng thời sẽ bị loại
# ngay cả khi chưa kịp lấy delivery lock để discard.
state = self.store.mutate(
    ...
    lambda prior, now: replace(
        prior,
        ...
        generation=prior.generation + 1,
        active_run_id=run_id,
```

Cổng mà Root gọi trước mỗi bước:

```python
def root_run_active() -> bool:
    ...
    current_run = self.store.load(sid)
    return current_run.generation == state.generation and current_run.active_run_id == run_id
```

Điểm nói: không khóa, không hủy từng tác vụ; so sánh một con số là đủ để mọi thứ của lượt cũ tự rụng.

### A3. Biên nhận: định nói ≠ đã nói ≠ đã dạy (slide máy trạng thái)

```
preparing ─► queued_for_audio ─► delivering ─► delivered ✓
(định nói)   (chưa có tiếng)     (đang phát)   (đã phát xong)
                  ↘ bị ngắt: cancelled (không tự phát lại)
                  ↘ crash giữa chừng: unconfirmed_after_restart
```

`VALID_STATUSES` trong `move_outcomes.py` có đúng 8 trạng thái: `preparing`, `queued_for_audio`, `delivering`, `delivered`, `failed_before_delivery`, `delivery_failed`, `cancelled`, `unconfirmed_after_restart`.

Docstring của `recover_inflight_on_restart`:

> SQLite biết move từng ở preparing/delivering nhưng không thể chứng minh TTS đã đến tai người dùng trước crash. Ghi UNKNOWN thay vì delivered, ... tuyệt đối không phát lại từ ledger.

Điểm nói: trạng thái "đã dạy" là sự kiện có biên nhận, không phải lời model tự nhận.

---

## 3. CƠ CHẾ B: HỆ THẦN KINH NHẬN THỨC (LANE)

```
mọi lời gọi model
   │ gắn 3 nhãn ĐỘC LẬP
   ├─ cognitive_lane : request đang làm VAI TRÒ gì   (root_conversation · tutor:* · public_reply · post_observer …)
   ├─ backend        : đi cổng nào
   └─ resource_class : có chiếm VRAM máy không
   ▼
_run_inference: xét VAI TRÒ trước, nhãn tier cũ (inference_tier) sau
   │
   ├─ LÀN BẮT BUỘC (không nằm trong tập optional → máy bận vẫn chạy)
   │     chat_tool_required   Root · Tutor (tutor:*) · turn_executive
   │     chat_main            Writer (public_reply)
   │     capability_deliberation_required
   │
   └─ LÀN NỀN (optional: hoãn / gộp / bỏ khi máy bận)
         post_observer · autonomous · tutor_background
         neuro_continuation · neuro_deliberation · capability_deliberation
```

Điểm nói:
- Nhiều lane có thể dùng cùng một model. Routing theo vai trò, không theo tên model.
- Cùng một model: Root bật thinking, Writer và Localizer tắt (trace phiên 15/10, theo `docs/knowledge/2026-10-14-eris-runtime-lessons.md` mục 8). Đừng nói mức thinking cụ thể.
- Hơn chục luồng nghĩ nền (khoảng 15 theo `lane-map-report.md`) chỉ đề xuất. Chỉ `RuntimeConversationDeliveryAdapter.deliver` gọi xuống `_send_decision_to_body` cho lời nói.

**Câu chuyện HOTFIX** (`src/runtime/ai_orchestrated/model_router.py`, comment nguyên văn, đã bỏ dòng đầu):

```python
# ... Trước đây lane này rơi xuống post_observer vì
# inference_tier=subconscious_4b => optional/preemptible. Khi chat
# đang xử lý, broker có thể loại chính bước kiểm bắt buộc, khiến
# writer nhận UNKNOWN, thử lại và Eris im lặng.
# Không đổi model, nội dung lời hay điều kiện receipt PASS.
lane = "chat_tool_required"
```

Cách kể đúng: bước bị cắt là **bước kiểm bắt buộc trước khi phát**, không phải "Root". Cơ chế bảo vệ nay áp cho cả Root và Tutor vì cả hai vẫn gửi nhãn `subconscious_4b` (agent.py, root_session.py, tutor/model_reasoner.py) nhưng vai trò được xét trước.

**Fail-soft** (`kernel.py`):
- Docstring `_deliver_runtime_failure`: "Thông báo offline không gọi Root/Writer/localizer, chỉ qua delivery chuẩn."
- Chỉ gọi khi `normalized_event.kind == "user_turn"` và Root hoặc Writer lỗi provider.
- Nói: "model lỗi thì Eris báo lỗi bằng giọng, không đơ". Không nói "luôn có tiếng".

---

## 4. CƠ CHẾ C: LEARNING KERNEL DETERMINISTIC

```
RuntimeTutorReasoner (model)          TutorGuardrailPolicy              LearningService
đề xuất nước dạy                      ép về khung theo pha              cửa DUY NHẤT ghi sự thật học
chấm câu trả lời tự do      ───►      kind ∉ allowed → allowed[0]  ───► mastery · bằng chứng · lịch ôn
                                      max_sentences = min(model, khung)  chỉ khi qua cổng:
                                                                         ① chấm đủ chắc: không "uncertain" và ≥ 0,68
                                                                         ② lời dạy đã PHÁT THÀNH CÔNG
```

**Khung ép theo pha** (`src/runtime/tutor/policy.py`, `MoveEnvelope`):

| Pha | Loại move được phép | Tối đa câu | Buộc người học trả lời |
|---|---|---|---|
| probe | probe_question, socratic_question | 2 | có |
| teach | explain, analogy, worked_example, socratic_question | theo ngân sách | không (Socratic vẫn buộc) |
| teach, đang hiểu sai | counterexample, socratic_question, repair, explain | min(ngân sách, 4) | không |
| practice | guided_practice, socratic_question | 3 | có |
| assess | assessment, guided_practice | 2 | có |
| review | review, assessment, socratic_question | 2 | có |
| advance | transition | 2 | không |
| complete | complete | 3 | không |

Code nguyên văn:

```python
# policy.py
kind = move.kind if move.kind in envelope.allowed_kinds else envelope.allowed_kinds[0]
...
max_sentences=min(move.max_sentences, envelope.max_sentences),

# executive.py
if assessment.verdict == "uncertain" or assessment.confidence < self.semantic_commit_confidence:   # mặc định 0.68
    ...
    return False

# executive.py · commit_delivery
"""Commit side-effect chỉ sau khi public delivery thực sự thành công.
Điều này giữ invariant: Eris *định nói* không đồng nghĩa Eris *đã dạy*."""
if not successful:
    ...
    return

# tutor/contracts.py
def to_writer_dict(self) -> dict[str, Any]:
    """Projection an toàn cho writer; cố ý không có expected_answer."""

# learning_core/service.py (docstring module, giữ nguyên không dấu)
# Quy tac cot loi: "LLM de xuat; deterministic kernel commit". Nho boundary nay,
# ... DeepTutor-derived logic chi la learning kernel ben trong Eris, khong tro thanh
# mot agent thu hai tranh quyen voi root TurnAgentLoop.
```

**Lịch ôn** (`learning_core/scheduler.py`): SM-2 biến thể, nửa đời quên 14 ngày, khoảng ôn tối đa 180 ngày, hệ số ease khống chế 1,3 đến 5,0. Tính bằng **ngày**, tách hẳn khỏi continuation lease tính bằng **giây** (30 giây, trễ 1,2 giây, tối đa 24 lần hoặc 120 giây một chuỗi).

**Chạy được cả khi không có model:** `composition.py` chỉ nối `RuntimeTutorReasoner` khi router có `invoke_structured_worker`. Không có thì dùng `ConservativeTutorReasoner`: vẫn đi theo khung, chỉ mất phần chấm câu tự do.

---

## 5. DÀN SLIDE ĐỀ XUẤT (12 slide, mỗi slide một sơ đồ)

| # | Slide | Hình chính | Điểm |
|---|---|---|---|
| 1 | Bìa | ảnh Eris | Trình bày |
| 2 | Ba lỗi của AI tự chủ: nói đè / nói dối / im lặng | 3 thẻ | Giải quyết vấn đề |
| 3 | Vấn đề thật + định vị: gia sư AI giỏi mà không ai mở (số Khanmigo, xem `TAC-DONG-BANG-CHUNG.md`) | 2 cột + 1 con số | Giải quyết vấn đề, Sáng tạo |
| 4 | Luồng tổng một lượt nói | **sơ đồ mục 1**, đánh nhãn [A][B][C] | Khả thi |
| 5 | Root loop và ba phanh | **sơ đồ A1** + 3 dòng code | Khả thi, Công nghệ |
| 6 | Chen lời → generation | **timeline A2** + code kernel.py | Công nghệ |
| 7 | Định nói ≠ đã nói ≠ đã dạy | **máy trạng thái A3** | Khả thi, Sáng tạo |
| 8 | Hệ thần kinh nhận thức (lane) | **sơ đồ mục 3** + HOTFIX | Công nghệ |
| 9 | Learning kernel | **sơ đồ mục 4** + bảng khung pha | Sáng tạo, Công nghệ |
| 10 | Tác động: nhân vật giữ người (Neuro-sama, Duolingo) × gia sư bị bỏ (Khanmigo) = Eris. Số liệu và nguồn trong `TAC-DONG-BANG-CHUNG.md` | Venn + 3 con số | Tác động |
| 11 | Bộ ba khác biệt + lộ trình cắm thêm | 3 thẻ + chuỗi | Tác động |
| 12 | Chốt: model sẽ thay, ba lời hứa ở lại | ảnh Eris | Chốt |

Slide 5 đến 9 chính là năm slide kỹ thuật. Mỗi slide: 1 câu to, 1 sơ đồ, tối đa 1 khối code 3 đến 5 dòng có ghi tên file.

---

## 6. CÂU KHÔNG NÓI / PHẢI SỬA

| Câu cũ | Sửa thành |
|---|---|
| "Không bao giờ tắt tiếng" | "Model lỗi thì Eris báo lỗi bằng giọng, không đơ" |
| "Chỉ 2 trạm gọi model" | "Năm trạm điều phối là code thuần; model chỉ ở Root, Gia sư, Writer, observer" |
| "Root từng bị cắt" | "Bước kiểm bắt buộc trước khi phát từng bị xếp nhầm vào làn nền" |
| "Cổng kiểm claim chạy mỗi lượt" | không nói. Lane và class có, nhưng grep 16/10 chỉ thấy tool nghiên cứu gọi `CharacterClaimVerifier` |
| "Phần lớn AI né bằng cách không dám tự chủ" | bỏ |
| "Đã hoàn thiện" bất kỳ phần nào | "kiến trúc đã có khớp nối; phần còn lại là bước thực thi" |

---

## 7. ĐIỂM YẾU BIẾT TRƯỚC (cho 2 phút phản biện)

Theo `docs/knowledge/2026-10-14-eris-runtime-lessons.md` (tình trạng 15/10) và grep trước đó. [CHƯA KIỂM LẠI hôm nay, trừ mục đầu]

- `register_path` và `activate_path` (nhập giáo trình) mới có call site trong test, chưa có trong luồng chat.
- Lỗi prepare trước khi phát chưa được báo ngược về Root ở request kế tiếp (phiên 16:47 ngày 15/10).
- "ô" chưa nằm trong danh sách tiếng phụ họa; `chat_start` có thể hủy audio trước khi phân loại.
- Hủy TTS từng bị tính như lỗi provider và có thể mở circuit breaker.

Cách trả lời: "Đã khoanh vùng, biết nằm ở khớp nào, nằm trong lộ trình."
