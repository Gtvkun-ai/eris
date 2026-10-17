# SLIDE PHỤ LỤC KỸ THUẬT — phần "mở mắt giám khảo"

Đây là đạn dược cho phần trình bày sâu + 2 phút phản biện. Rút từ
`deep-architecture.md`. Mỗi slide một nguyên lý đắt, mỗi câu gáy có chân đế code.

> Cách dùng: KHÔNG nhồi hết vào 5 phút chính. Để 3 slide này ở cuối (phụ lục).
> Khi giám khảo hỏi "sâu hơn đi" hoặc "làm sao khả thi" — lật ra. Đó là lúc hạ bệ.

---

## SOUNDBITE MỞ MÀN (học thuộc 3 câu này)

1. **"Eris tách bốn trục quyền lực — quyết định, diễn đạt, phát, ghi nhớ — và
   tách vai trò nhận thức khỏi model khỏi VRAM. Nhóm khác gọi một model, lấy
   string, đọc lên."**

2. **"Eris phân biệt 'định nói' ≠ 'đã nói' ≠ 'đã dạy' bằng biên nhận có chữ ký,
   không bằng niềm tin của model. Đây là chống bịa cấp hệ thống."**

3. **"Eris luôn có tiếng kể cả khi LLM chết — có một đường phát không đi qua
   model."**

---

## SLIDE PL-1 — LANE ROUTING: HỆ THẦN KINH NHẬN THỨC

**Tiêu đề:** Không chọn model — phân bổ sự chú ý theo vai trò

**Nguyên lý (in to):**
Một request suy luận được định danh bằng *ba trục trực giao*, không bằng "model nào":

```
cognitive_lane  (VAI TRÒ nhận thức)   → turn_executive, root_conversation,
                                         tutor:*, public_claim_verifier...
backend         (đường truyền)        → ds2api, openai_compatible...
resource_class  (VRAM cục bộ?)        → remote_api, local_light, vision_local...
```

**Bất biến then chốt:**
Lane foreground (chat, kiểm claim) **không bao giờ** nằm trong tập "có thể cắt".
Cùng một model vừa là "bộ não bắt buộc" của lượt này, vừa là "worker nền có thể
bỏ" của lượt khác — broker đối xử đúng theo *vai trò*, không theo tên model.

**Câu chuyện hạ bệ (kể miệng — đây là phần đắt nhất):**
"Chúng tôi từng để Eris *im lặng*. Lý do: một nhãn tài nguyên cũ vô tình kéo
bước điều hành bắt buộc xuống nhóm 'có thể cắt', nên khi quá tải broker loại
chính nó. Chúng tôi không vá triệu chứng — chúng tôi đóng băng một bất biến:
vai trò nhận thức được ưu tiên trước nhãn tài nguyên. Đây là bài học chỉ có khi
bạn *vận hành thật*, không phải làm demo."

*(Chân đế: `model_router.py` `_run_inference` — comment HOTFIX, tập `optional`.)*

---

## SLIDE PL-2 — AGENT LOOP: VÒNG NHẬN THỨC CÓ KIỂM SOÁT

**Tiêu đề:** 'Định nói' ≠ 'đã nói' ≠ 'đã dạy'

**Nguyên lý (in to):**
Model không được tự tuyên bố "mình đã làm". Trạng thái đó là *sự kiện vật lý có
biên nhận*: câu đã thực sự phát audio thành công hay chưa.

**Vòng trạng thái một lời nói:**
```
preparing → queued_for_audio → delivering → delivered
   (định nói)   (vào hàng đợi)   (đang phát)   (đã phát xong)
                        ↓ user chen vào
                     cancelled  (KHÔNG tự phát lại)
```

**Ba bất biến đắt:**
- **Chống bịa cấp hệ thống:** Root chỉ được nói "đã dạy" khi có biên nhận
  `delivered` của đúng run. Biên nhận gắn event/run/generation, không ghi đè.
- **Preemption bằng generation:** user chen lời → một con số `generation` tăng
  NGAY → mọi callback TTS của thế hệ cũ tự chết. Không race, không hủy từng cái.
- **Restart không nói dối:** sau crash, ghi UNKNOWN thay vì giả vờ "đã phát" —
  tuyệt đối không phát lại từ sổ cái.

**Hai tầng phanh vòng lặp:** trần cứng 2–12 bước + cắt sớm khi "không tiến triển"
2 lần liên tiếp. Suy nghĩ thầm giới hạn 2 lượt.

*(Chân đế: `move_outcomes.py` MoveOutcomeLedger; `kernel.py` generation+1;
`agent.py` max_root_steps clamp, _advance_progress_and_maybe_finalize.)*

---

## SLIDE PL-3 — TUTOR: LEARNING KERNEL DETERMINISTIC

**Tiêu đề:** LLM đề xuất — kernel deterministic chốt

**Nguyên lý (in to):**
Model chỉ được *gợi ý* nước đi dạy và *chấm* câu trả lời. Ghi nhận tiến độ học
là việc của một kernel có luật. Nhờ ranh giới này, Tutor không bao giờ thành
"agent thứ hai" tranh quyền với Root.

```
RuntimeTutorReasoner (model) ──đề xuất──►  GuardrailPolicy ──ép về envelope──►
                                           LearningService ──commit có luật──► MasteryRecord
                              (model bịa cũng không ghi thẳng vào hồ sơ học)
```

**Bốn bất biến đắt:**
- **Một cửa commit:** chỉ LearningService ghi sự thật học tập. Nó không viết lời,
  không gọi TTS, không tự bật tutor.
- **Qua ngưỡng tin cậy:** câu tự do chỉ thành bằng chứng khi độ tin cậy ≥ ngưỡng
  (mặc định 0.68). Model "uncertain" → không ghi.
- **Writer không bao giờ thấy đáp án:** đáp án chỉ ở server. Câu hỏi Socratic
  mới có nghĩa.
- **Chạy cả khi không có model:** thiếu reasoner → vẫn chạy policy deterministic,
  chỉ mất năng lực chấm câu tự do. Không có "màn hình trắng".

*(Chân đế: `learning_core/service.py` + BOUNDARY_VI.md; `tutor/policy.py`
GuardrailPolicy; `tutor/contracts.py` to_writer_dict bỏ expected_answer;
`composition.py` Conservative vs Runtime reasoner.)*

---

## SLIDE PL-4 — LỘ TRÌNH TUTOR: TIỀM NĂNG VÔ HẠN, CẮM VÀO ĐIỂM MÓC THẬT

**Tiêu đề:** Mỗi nâng cấp cắm vào khớp nối có sẵn — không viết lại lõi

| Hướng mở rộng | Cắm vào khớp nối nào | Giữ bất biến nào |
|---|---|---|
| **Nhiều môn song song** (tutor:math, tutor:english) | Capability Registry + lane `tutor:*` đã nhận tiền tố | Root vẫn là bộ não duy nhất chọn gọi môn nào |
| **Vision chấm ảnh bài làm** | `resource_class=vision_local` đã có + evidence contract + receipt | Ảnh là bằng chứng có scope, không tự thành fact |
| **Nhắc học nhiều ngày** | ReviewScheduler (SM-2, tính theo ngày) + event nền riêng | KHÔNG kéo continuation lease (vài giây) thành lịch nhiều ngày |
| **LearnerModel dự đoán điểm yếu** | MasteryRecord + forgetting curve (thay công thức) | Dự đoán vẫn phải qua gate để thành bằng chứng |
| **Multi-agent tutor** (planner + executor) | Tách RuntimeTutorReasoner thành 2 vai trong 1 capability | Chỉ Root finalize lời public; guardrail là van cuối |

**Câu chốt (gáy):**
"Đây là lý do Eris là đồ án mở không có trần. Thêm bao nhiêu năng lực — môn mới,
vision, nhắc nhiều ngày, nhiều tutor — tất cả cắm vào cùng bốn khớp nối và giữ
nguyên các bất biến. Chúng tôi không mở rộng bằng cách viết thêm; chúng tôi mở
rộng bằng cách *cắm vào*."

---

## SLIDE PL-5 (CHỐT PHỤ LỤC) — VÌ SAO KHÔNG AI BẮT CHƯỚC ĐƯỢC

**Tiêu đề:** Năm rào cản kỹ thuật

1. **Tách tám trục** (4 quyền lực × 4 routing). Nhóm "gọi API rồi đọc lên"
   không có chỗ cài luật preemption, chống bịa, hay degradation — mọi thứ dính
   vào một lời gọi.
2. **Chống bịa cấp hệ thống**, không cấp prompt. State machine + biên nhận gắn
   ID, không ghi đè. Không thể giả.
3. **Concurrency bằng generation đơn điệu** — tư duy hệ phân tán, không phải tư
   duy chatbot.
4. **Learning kernel tách khỏi model** — model bịa cũng không nhiễm độc hồ sơ
   học. Đối thủ "một tính năng tutor" thường để model tự chấm tự ghi.
5. **Fail-soft có thật** — một đường phát không qua LLM. Chi tiết chỉ xuất hiện
   sau khi vận hành thật và vấp lỗi thật.

**Câu kết đinh:**
"Mỗi rào cản này không phải một tính năng — nó là một *quyết định kiến trúc* sinh
ra từ việc chạy thật. Nhóm khác xây một câu trả lời trong hai tuần. Chúng tôi xây
một hệ điều hành nhận thức, và mỗi bất biến là một vết sẹo của việc vận hành thật."
