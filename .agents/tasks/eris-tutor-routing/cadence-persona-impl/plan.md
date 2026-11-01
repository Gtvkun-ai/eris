# Implementation Plan — Nhịp trình bày thành cá tính + năng lực sư phạm

Worktree (đường dẫn TUYỆT ĐỐI, mọi sửa/đọc/test chạy ở đây):
`c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona` (branch `cadence-persona`).
cwd mặc định của agent là workspace gốc, KHÔNG phải worktree — luôn dùng đường dẫn tuyệt đối.

## Bối cảnh & quyết định thiết kế (đã có design duyệt — không tự quyết lại kiến trúc)

Design đã duyệt nằm trong brief + báo cáo khả thi
`c:\Users\Gtvkun\Documents\GitHub\eris\.agents\tasks\eris-tutor-routing\persona-pedagogy-cadence-feasibility.md`.
Kết luận đã chốt từ 5 vòng điều tra đọc-only (KHÔNG điều tra lại):

- Cơ chế cuốn chiếu (continuation lease, `after=may_continue`) ĐÃ tồn tại và chạy live. Đường
  nối cá tính → `after`/`say` ĐÃ đầy đủ: Root đọc `personality_context`/`affect`/`confusion_signal`
  rồi quyết cùng một action JSON gồm `intent/say/after`. Thiếu DUY NHẤT là **chỉ dẫn cadence trong
  persona còn mờ** + chưa có câu dạy Eris tách lời vì quan tâm người học.
- Vì vậy task này KHÔNG viết cơ chế mới. Chỉ: (1) sửa prose persona, (2) nới một policy tutor,
  (3) thêm một dòng log quan sát. Đây là task **vừa phải, không heavy**.

Ràng buộc bắt buộc giữ (hợp đồng runtime
`c:\Users\Gtvkun\Documents\GitHub\eris\docs\knowledge\2026-10-14-eris-runtime-lessons.md`):
text-chờ-voice (mỗi bubble commit theo `audio_start` riêng), single_writer, "không tạo người
quyết định nội dung thứ hai". TUYỆT ĐỐI KHÔNG thêm `max_sentences`/speech budget/quota số câu/flag
runtime/semantic scheduler mới ở Root; đoạn cuối `ROOT_SYSTEM_CORE` và contract cấm. KHÔNG đụng
`continuation.py`/`kernel.py`/writer/TTS. KHÔNG soft-forcing ở `agent.py` (đó là bước 3 tương lai,
KHÔNG làm trong task này).

## Trạng thái đã xác nhận bằng đọc code (grounding cho từng item)

- `root_prompt_contract.py`: `ROOT_SYSTEM_CORE` là một chuỗi literal nối nhiều dòng (dòng ~5 tới
  ~96). Các câu đích đã xác nhận có mặt verbatim:
  - Câu finalize (1a): `"...say mô tả đầy đủ điều writer cần truyền đạt nhưng không phải transcript; delivery mô tả tự nhiên cách thể hiện; after chỉ là wait_user|may_continue|continue_self."`
  - Câu "cá tính quyết nhịp" (chỗ đặt 1b): `"Chính cá tính và cảm nhận ngữ cảnh của bạn quyết số nhịp nối, không có quota ngôn ngữ..."` + câu kế `"Mỗi nhịp nối cần ý mới và chất giọng riêng (hài khô, trêu nhẹ, tự giễu, quan điểm), không phải câu đệm vô hồn để kéo hội thoại."`
  - Câu confusion (1c) ĐÃ CÓ: `"Nếu confusion_signal có repair_needed hoặc stance=confused, ưu tiên hỏi chỗ user kẹt hoặc giải thích theo ví dụ/góc nhìn MỚI thay vì lặp lại đoạn giảng dài hơn; vẫn nói bằng giọng Eris, không đổi sang giọng bot trung tính."` → KHÔNG cần thêm, chỉ giữ nguyên.
  - Câu cấm cuối: `"Không tạo floor, beat, agenda, exposure, question debt, speech budget, max_sentences, desired_shape, disclosure mode hoặc semantic scheduler..."` → GIỮ NGUYÊN.
- `tutor/policy.py` `TutorGuardrailPolicy.envelope()` đặt `max_sentences` CỨNG theo phase
  (probe=2, teach=`teach_budget` 4/5/6 theo pace, practice=3, assess=2, review=2, advance=2,
  complete=3, repair adaptive=min(3,budget), transfer/independent=2). `enforce()` ép
  `max_sentences=min(move.max_sentences, envelope.max_sentences)`.
- `tutor/contracts.py`: `MoveEnvelope.max_sentences` và `TeachingMove.max_sentences` đều bound
  `max(1, min(6, count))`. `TutorDecision.to_writer_context()` xuất
  `delivery_constraints.max_sentences`. `TeachingMove.to_writer_dict()` cũng có `max_sentences`.
- Người tiêu thụ `max_sentences` ở mạch tutor Root/writer: `capabilities/tutor.py` chỉ đọc
  `delivery_constraints.requires_user_response` (KHÔNG đọc `max_sentences` để ép cắt) rồi trả
  `teaching_move` (dict từ `to_writer_dict`, có chứa `max_sentences`) cho Root như dữ liệu tư vấn.
  → `max_sentences` của mạch tutor hiện là HINT truyền trong teaching_move, không phải trần runtime
  cắt chữ ở Root. Thứ ép cứng số câu nằm trong CHÍNH envelope/enforce của policy (giá trị thấp như
  2–3) + reasoner chép vào `instruction_vi`.
- `tutor/reasoner.py` `ConservativeTutorReasoner.choose_move` đặt `max_sentences=envelope.max_sentences`
  và `instruction_by_kind` KHÔNG nhắc số câu — phần sư phạm ("không giải hộ", "không gợi đáp án quá
  sớm", spaced retrieval) nằm ở đây và ở `policy.enforce` directives. GIỮ NGUYÊN phần sư phạm.
- Test đụng tới: `src/tests/test_tutor_executive_v1.py` (assert `max_sentences == 2`, `== 4`, `<= 4`,
  `<= 2`), `src/tests/test_learn04_adaptive_teaching.py` (`max_sentences <= 2`),
  `src/tests/test_tutor_model_reasoner_v1.py` (adapter nhận `max_sentences` từ mapping — không assert
  trần, chỉ parse). `src/tests/conversation/test_architecture_v12.py` assert chuỗi `max_sentences`
  KHÔNG xuất hiện trong `NEXT_MOVE_SCHEMA` của `agent.py` (bước 3 KHÔNG được thêm từ này vào schema).
- `agent.py`: nhánh finalize ở ~dòng 328–341; log hiện có `[root-agent] step=%d event_kind=%s action=%s`
  ở ~dòng 332–334. `after` lấy từ `raw.get("after", "wait_user")` (xác nhận cách parse ở
  `contracts.py` `NextConversationMove.from_mapping`, dòng ~86).

## Lệnh build/test của dự án (dùng cho Verify)

Dự án Python. Chạy test bằng pytest trong worktree với `PYTHONPATH=src` (các test import kiểu
`from runtime...`, `from runtime.tutor...`). Trên Windows PowerShell:

```
cd c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tests/tutor tests/test_tutor_executive_v1.py tests/test_learn04_adaptive_teaching.py tests/test_tutor_model_reasoner_v1.py tests/conversation/test_architecture_v12.py -q
```

Nếu layout import khác, dùng `python -m pytest <đường dẫn test> -q` từ thư mục `src`. Mỗi item nêu
lệnh test hẹp tương ứng. KHÔNG nới lỏng assertion để che lỗi; nếu đổi ngữ nghĩa thì sửa test cho
khớp và giải thích trong commit/PR.

---

# Implementation Plan

- [ ] 1. (BƯỚC 1a) Sửa câu finalize trong `ROOT_SYSTEM_CORE`: đổi "say mô tả đầy đủ điều writer
      cần truyền đạt" thành ý "say là MỘT nhịp / một ý người nghe nuốt được trong một hơi; không nhồi
      cả lời giải hay cả bài giảng vào một move", GIỮ nguyên vế "nhưng không phải transcript" và phần
      `delivery`/`after` của cùng câu. Khớp giọng tiếng Việt hiện có. KHÔNG thêm số/quota.
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\conversation\root_prompt_contract.py`
      Verify: từ thư mục `src` (PYTHONPATH=src) chạy
      `python -c "import runtime.conversation.root_prompt_contract as m; s=m.ROOT_SYSTEM_CORE; assert 'không phải transcript' in s; assert 'một hơi' in s; assert 'say mô tả đầy đủ điều writer' not in s; print('ok')"`
      → in `ok` (xác nhận câu cũ đã bị thay, vế transcript còn, ý "một hơi" đã vào). Chuỗi vẫn import
      được (không lỗi cú pháp literal).

- [ ] 2. (BƯỚC 1b) Thêm MỘT câu persona (giọng mô tả cá tính, KHÔNG phải luật/quota) đặt NGAY CẠNH câu
      "Chính cá tính và cảm nhận ngữ cảnh của bạn quyết số nhịp nối..." (trước hoặc sau câu "Mỗi nhịp
      nối cần ý mới..."). Nội dung đại ý: "Eris để ý người nghe có theo kịp không — như một người kể
      giỏi biết ngừng đúng chỗ. Khi một ý đã trọn mà còn ý kế (giảng bài, liệt kê bước, ra đề), nói ý
      đó bằng giọng mình rồi after=may_continue để rải tiếp, thay vì dồn một hơi khiến người ta xỉu
      chữ. Rải vì quan tâm người học, không vì bị đếm câu." Chỉnh câu chữ cho khớp văn phong hiện có.
      TUYỆT ĐỐI KHÔNG thêm `max_sentences`/beat/budget/quota.
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\conversation\root_prompt_contract.py`
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -c "import runtime.conversation.root_prompt_contract as m; s=m.ROOT_SYSTEM_CORE; assert 'may_continue' in s; assert 'theo kịp' in s; assert 'quyết số nhịp nối' in s; import re; assert s.count('max_sentences')==1; print('ok')"`
      → in `ok`. (`max_sentences` chỉ được xuất hiện ĐÚNG MỘT lần — là câu cấm ở cuối; câu persona mới
      KHÔNG được chứa từ đó.) Đồng thời chạy
      `python -m pytest tests/conversation/test_architecture_v12.py -q` (từ `src`, PYTHONPATH=src) —
      PASS, xác nhận schema `agent.py` không bị ảnh hưởng.

- [ ] 3. (BƯỚC 1c) Xác nhận câu confusion_signal đã có trong `ROOT_SYSTEM_CORE` và GIỮ NGUYÊN; không
      thêm trùng. Nếu (và chỉ nếu) nó đã bị item 1/2 vô tình chỉnh, khôi phục nguyên văn.
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\conversation\root_prompt_contract.py`
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -c "import runtime.conversation.root_prompt_contract as m; s=m.ROOT_SYSTEM_CORE; assert 'confusion_signal' in s and 'repair_needed' in s and 'ví dụ/góc nhìn MỚI' in s; print('ok')"`
      → in `ok`.

- [ ] 4. (BƯỚC 2) Nới `max_sentences` trong `tutor/policy.py` từ TRẦN CỨNG thành HINT MỀM, giữ nguyên
      phần sư phạm thật. Cách làm: trong `TutorGuardrailPolicy.envelope()`, nâng các giá trị
      `max_sentences` thấp (các 2/3 cho probe/practice/assess/review/advance/transfer/independent và
      các `min(3, teach_budget)` cho adaptive repair) lên mức rộng (ví dụ dùng chung `teach_budget`
      hoặc trần tối đa 6 của contract) để không còn cắt cá tính theo số câu — Eris tự rải nhịp như
      bước 1. GIỮ NGUYÊN: `allowed_kinds`, `requires_user_response`, `interaction_type`, `reason`,
      và mọi directive sư phạm trong `enforce()` ("không hé đáp án", "không giải hộ", spaced retrieval,
      counterexample). Đổi `enforce()` để `max_sentences` không còn là ép trần cắt lời: giữ field cho
      tương thích contract nhưng mang nghĩa GỢI Ý (ví dụ lấy thẳng `envelope.max_sentences` đã nới,
      KHÔNG `min()` xuống dưới ý định của move). Thêm comment nêu rõ "đây là hint mềm, không phải quota
      — cá tính/Root quyết nhịp".
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\tutor\policy.py`
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -m pytest tests/test_tutor_executive_v1.py tests/test_learn04_adaptive_teaching.py -q`.
      Các test sau sẽ đổi kỳ vọng vì trần cũ được nới (xử lý ở item 5): `max_sentences == 2` (probe),
      `envelope.max_sentences == 4` / `move.max_sentences <= 4` (teach fast), `move.max_sentences <= 2`
      (adaptive). Sau item 5, lệnh này PASS.

- [ ] 5. (BƯỚC 2 — test) Cập nhật các assertion `max_sentences` cứng trong test tutor cho khớp NGỮ
      NGHĨA MỚI (hint mềm, không phải quota). KHÔNG nới lỏng để che lỗi: đổi assertion phản ánh đúng
      rằng `max_sentences` giờ là gợi ý rộng (ví dụ `>= <giá trị cũ>` hoặc bỏ assertion trần nếu nó
      chỉ còn kiểm quota đã gỡ), GIỮ các assertion về `kind`, `requires_user_response`,
      `instruction_vi` chứa ràng buộc sư phạm ("BIẾN THỂ", v.v.) nguyên vẹn. Ghi chú trong test lý do
      đổi (semantic mới: cá tính quyết nhịp, không ép số câu). Các chỗ cần xem:
      `test_tutor_executive_v1.py` (`test_probe_phase_cannot_be_overridden...` dòng ~99,
      `test_learner_pace_changes_teaching_budget` dòng ~262-263),
      `test_learn04_adaptive_teaching.py` (dòng ~164).
      Files:
      `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\tests\test_tutor_executive_v1.py`,
      `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\tests\test_learn04_adaptive_teaching.py`
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -m pytest tests/test_tutor_executive_v1.py tests/test_learn04_adaptive_teaching.py tests/test_tutor_model_reasoner_v1.py -q`
      → tất cả PASS, và các assertion đã phản ánh ngữ nghĩa hint mềm (không chỉ nới số rồi bỏ qua).

- [ ] 6. (BƯỚC 2 — kiểm tra lan rộng) Rà soát `tutor/reasoner.py` xem `instruction_by_kind`/
      `choose_move` có câu nào ÉP độ dài không. Theo đọc code hiện tại KHÔNG có (chỉ `max_sentences=
      envelope.max_sentences`); nếu đúng vậy thì KHÔNG sửa reasoner. Chỉ sửa nếu phát hiện câu ép số
      câu còn sót. GIỮ nguyên câu "Giữ giọng Eris tự nhiên... không làm phẳng cá tính..." đã có.
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\tutor\reasoner.py` (chỉ nếu cần)
      Verify: từ `src` (PYTHONPATH=src) chạy `python -m pytest tests/tutor -q` (nếu thư mục tồn tại)
      + `python -m pytest tests/test_tutor_model_reasoner_v1.py -q` → PASS. Nếu không sửa gì, ghi rõ
      "reasoner không ép độ dài, giữ nguyên" trong báo cáo.

- [ ] 7. (BƯỚC 3, nhỏ — observability) Thêm MỘT dòng log LOẠI `after` quanh nhánh finalize `move` ở
      `agent.py` (cạnh log `[root-agent] step=... action=...` hiện có, ~dòng 332-334, chỉ trong nhánh
      `kind == "move"`). Chỉ log loại `after` (lấy từ `raw.get("after", "wait_user")`, chuẩn hóa về
      một trong `wait_user|may_continue|continue_self`), KHÔNG serialize nội dung `say`/`intent`.
      Ví dụ: `self._log("info", "[root-agent] finalize move after=%s", str(raw.get("after","wait_user")).strip().lower()[:24])`.
      KHÔNG thêm `max_sentences`/trường mới vào `NEXT_MOVE_SCHEMA`. Nếu thấy rủi ro/khó (ví dụ `raw`
      không phải mapping ở nhánh đó), ghi rõ và bỏ qua item này.
      Files: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona\src\runtime\conversation\agent.py`
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -c "import ast; ast.parse(open('runtime/conversation/agent.py',encoding='utf-8').read()); print('ok')"`
      (parse sạch) và `python -m pytest tests/conversation/test_architecture_v12.py -q` → PASS (xác
      nhận schema không nhiễm `max_sentences`/trường cấm).

- [ ] 8. (Kiểm chứng tổng hợp) Chạy toàn bộ test liên quan một lần cuối để xác nhận không hồi quy.
      Files: (không sửa)
      Verify: từ `src` (PYTHONPATH=src) chạy
      `python -m pytest tests/tutor tests/test_tutor_executive_v1.py tests/test_learn04_adaptive_teaching.py tests/test_tutor_model_reasoner_v1.py tests/conversation -q`
      → tất cả PASS. Nếu có test khác trong `tests/conversation` phụ thuộc `ROOT_SYSTEM_CORE` đổi vỡ,
      sửa cho khớp ngữ nghĩa mới (KHÔNG che lỗi) và giải thích.

## Ghi chú kiểm chứng cuối (ngoài phạm vi test)

Bản chất thay đổi là *bias prompt* + *nới policy* — hiệu quả thật (câu dạy dài → nhiều move nối qua
`may_continue`, mỗi bubble ngắn thay vì tường chữ ~1259 ký tự) chỉ xác nhận chắc chắn bằng **phiên
live** (DeepSeek + delivery), không phải test fixture. Dòng log `after` ở item 7 là để quan sát việc
đó khi chạy live. Báo cáo/PR nên nêu rõ: test xanh chứng minh contract + không hồi quy, CHƯA chứng
minh cảm giác cadence live; cần một phiên live với prompt "dạy tôi phân số, ra cho tôi một bài tập"
để xác nhận Eris rải nhịp thay vì đổ một bubble.
