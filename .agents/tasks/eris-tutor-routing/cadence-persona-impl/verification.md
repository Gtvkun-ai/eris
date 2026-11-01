# Verification — Nhịp trình bày thành cá tính + năng lực sư phạm

Worktree: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\cadence-persona` (branch `cadence-persona`).
Python: `c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe`, `PYTHONPATH=<worktree>\src`.
Vòng: ĐẦU (không có `review.json`).

## Files đã đổi

- `src/runtime/conversation/root_prompt_contract.py` — BƯỚC 1a + 1b (prose persona/cadence trong `ROOT_SYSTEM_CORE`). 1c giữ nguyên (câu confusion_signal đã có).
- `src/runtime/tutor/policy.py` — BƯỚC 2: `max_sentences` từ TRẦN CỨNG → HINT MỀM.
- `src/runtime/conversation/agent.py` — BƯỚC 3: thêm một dòng log LOẠI `after` quanh nhánh finalize move.
- `src/tests/test_tutor_executive_v1.py` — cập nhật assertion `max_sentences` theo ngữ nghĩa hint mềm.
- `src/tests/test_learn04_adaptive_teaching.py` — cập nhật assertion `max_sentences` theo ngữ nghĩa hint mềm.

## Nội dung thay đổi (tóm tắt)

- 1a: câu finalize — "say là MỘT nhịp, một ý người nghe nuốt được trong một hơi, không phải transcript
  và cũng không phải chỗ nhồi cả lời giải hay cả bài giảng vào một move". Giữ vế "không phải transcript"
  và phần `delivery`/`after`.
- 1b: thêm một câu persona (giọng cá tính, không luật/quota) cạnh câu "quyết số nhịp nối": Eris để ý
  người nghe có theo kịp không, khi một ý đã trọn mà còn ý kế thì nói bằng giọng mình rồi
  `after=may_continue` để rải tiếp; rải vì quan tâm người học, không vì bị đếm câu. KHÔNG thêm
  `max_sentences`/beat/budget (`ROOT_SYSTEM_CORE.count('max_sentences') == 1`, vẫn là câu cấm cuối).
- BƯỚC 2 (policy.py): thêm hằng `_SOFT_CADENCE_HINT = 6` (trần rộng nhất contract cho phép). `envelope()`
  dùng `hint` cho mọi phase thay cho các trần cứng 2/3/4/5. `enforce()` đổi
  `max_sentences=min(move, envelope)` → `max(move, envelope)` để KHÔNG kéo move xuống dưới ý định của
  chính nó (hint mềm, không cắt lời). GIỮ NGUYÊN: `allowed_kinds`, `requires_user_response`,
  `interaction_type`, mọi directive sư phạm ("không hé đáp án", "không giải hộ", spaced retrieval,
  counterexample/BIẾN THỂ). Bỏ biến `teach_budget` nay không còn dùng.
- reasoner.py: KHÔNG sửa — `instruction_by_kind`/`choose_move` không ép độ dài (chỉ
  `max_sentences=envelope.max_sentences`); giữ câu "Giữ giọng Eris tự nhiên... không làm phẳng cá tính".
- BƯỚC 3 (agent.py): `self._log("info", "[root-agent] finalize move after=%s", ...)` chỉ log loại `after`
  (`wait_user|may_continue|continue_self`), KHÔNG serialize `say`/`intent`. KHÔNG thêm trường vào schema.

## Kiểm tra prose (import ROOT_SYSTEM_CORE)

Các assert đều PASS (`ok`): `'không phải transcript' in s`, `'một hơi' in s`,
`'say mô tả đầy đủ điều writer' not in s`, `'may_continue' in s`, `'theo kịp' in s`,
`'quyết số nhịp nối' in s`, `s.count('max_sentences') == 1`,
`'confusion_signal'/'repair_needed'/'ví dụ/góc nhìn MỚI' in s`.

## Lệnh test + kết quả

Lệnh (chạy từ venv, `PYTHONPATH=<worktree>\src`, `pytest -q -p no:cacheprovider`):

Chạy theo nhóm (shell foreground của môi trường không ổn định; dùng background + file output):

- `test_tutor_executive_v1.py` → **12 passed**
- `test_learn04_adaptive_teaching.py` + `test_tutor_model_reasoner_v1.py` + `conversation/test_architecture_v12.py` → **30 passed**
- `test_tutor_learning_p1_domains.py` → **7 passed**
- `test_tutor_learning_integration_v1.py` → **33 passed**
- `test_root_orchestrated_learner_v1.py` + `conversation/test_context_assembler_v12.py` → **12 passed**

Tổng: **94 passed, 0 failed.** (gồm trọn bộ 4 file VERIFY bắt buộc + các test tutor policy/reasoner bị
ảnh hưởng bởi BƯỚC 2 + test prompt-contract/schema `test_architecture_v12.py`.)

## Ruff

`python -m ruff check` trên 5 file đã sửa: sau khi bỏ `teach_budget` còn **1 lỗi DUY NHẤT** là
`F401 runtime.tutor.adaptive_policy.choose_adaptive_step imported but unused` ở
`test_learn04_adaptive_teaching.py:14`. Đây là **PRE-EXISTING** (git diff xác nhận chỉ đổi dòng
161-166, không đụng import dòng 14) → KHÔNG sửa vì ngoài phạm vi task. Code do task này thêm:
ruff sạch.

## Giới hạn kiểm chứng (user cần xác minh live)

Hiệu quả cadence THẬT (câu dạy dài → nhiều move nối qua `may_continue`, mỗi bubble ngắn thay vì một
tường chữ) là **lựa chọn của model trong khoảng tự do prompt** — test fixture KHÔNG tái hiện được.
Test xanh chỉ chứng minh: contract không vỡ, không hồi quy, schema không nhiễm từ cấm. CHƯA chứng minh
cảm giác cadence live. Cần một phiên live (DeepSeek + delivery) với prompt kiểu "dạy tôi phân số, ra cho
tôi một bài tập" để xác nhận Eris rải nhịp thay vì đổ một bubble. Dòng log `after` ở BƯỚC 3 dùng để
quan sát việc đó khi chạy live.
