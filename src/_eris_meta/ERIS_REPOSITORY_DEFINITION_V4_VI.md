# ERIS Repository Definition V6: Model-owned Chat + AI Observers

**Version contract:** `eris.repository.v6.model_owned_chat_ai_observers`

## 1. Chủ thể tạo lời nói

Model chính được cấu hình cho runtime, hiện là GPT-5.6 Terra, sở hữu:

- diễn giải ngữ cảnh;
- lựa chọn nội dung;
- giọng nói và cá tính;
- `Decision` public hợp lệ đầu tiên.

Khi một `Decision` hợp lệ đã tồn tại, không module hậu kỳ nào được sinh lại, viết lại, rút gọn, thay câu, ép im lặng hoặc chọn một câu khác thay cho nó.

## 2. Vai trò mới của guard, critic và authority

Các lớp cũ được định nghĩa lại thành **observer/auditor**. Chúng có thể:

- phát hiện lời hứa thực thi chưa có handler/result;
- phát hiện claim cảm nhận thiếu bằng chứng cảm biến;
- phát hiện mâu thuẫn ký ức hoặc khoản nợ liên tục;
- ghi candidate nói dối vào Sổ Lừa Dối;
- tạo `BehaviorSignal` để model cân nhắc ở lượt kế tiếp;
- cung cấp motion, delivery hoặc tool-verification hint trước lần sinh tiếp theo.

Chúng không được chỉnh semantic text của lượt hiện tại.

## 3. BehaviorSignal và hậu quả ở lượt sau

Mỗi tín hiệu có:

- `family`, `source`;
- `confidence`, `severity`;
- `evidence`;
- `consequence`;
- `next_turn_hint`;
- `public_text`, `turn_id`, `channel`.

Tín hiệu được ghi vào `memory_core/behavior_observations.jsonl`. Trước lần gọi model kế tiếp, runtime đưa một khối `BEHAVIOR AFTERMATH` vào prompt. Terra có thể tự chọn:

- xác minh bằng tool thật;
- thừa nhận đã nói quá;
- sửa quan hệ một cách tự nhiên;
- tiếp tục lời nói dối có chủ đích;
- tiết lộ hoặc nâng cấp lời nói dối;
- bỏ qua khi tín hiệu không còn liên quan.

Đây là hậu quả hành vi, không phải bộ lọc đạo đức.

## 4. Sổ Lừa Dối

`deception_candidate` vẫn đi qua Deception Ledger. Ledger giữ ground truth và nghĩa vụ nhất quán. Hallucination hoặc overclaim chưa đủ bằng chứng về chủ ý chỉ được ghi là observation, tránh biến mọi sai sót thành “nói dối có chủ đích”.

## 5. Những biên vẫn được phép xử lý

Generation sovereignty không cấm vệ sinh kỹ thuật:

- che API key, secret và đường dẫn nội bộ;
- loại protocol/debug leakage khỏi bề mặt public;
- retry khi JSON/Decision chưa parse được;
- tách action tag thành motion/nonverbal cue;
- dùng kết quả tool thật thay cho placeholder vận chuyển;
- hủy audio hoặc turn vì interrupt thật.

Các biên này không được thay đổi ý nghĩa câu hợp lệ.

## 6. Cấu hình mặc định V4

- `semantic_authority_mode = primary_model`
- `critique_mode = advisory`
- `max_constrained_reruns = 0`
- `response_contract_gate = false`
- `director_candidate_mode = off`
- `director_second_pass = off`
- guard mode luôn `log_only/observe_only`

Tên class/key cũ được giữ alias để plugin, test và frontend cũ không vỡ ngay. Alias không khôi phục quyền rewrite.

## 7. Invariant kiểm thử

- `Decision.text`, `should_speak`, `intent`, `animation` không đổi khi observer chạy.
- Observation chỉ được gắn metadata và ghi journal.
- Context hậu quả chỉ được đưa vào **trước** lần generation kế tiếp.
- Stage payload có thể expose summary gọn, không expose evidence/private journal đầy đủ.
- Contract machine-readable nằm tại `runtime/repository_definition.py`.


## 8. Social observer bằng model phụ

Social cognition production chạy như một cảm biến bất đồng bộ:

- `openai/gpt-oss-20b`: observer chính, trả structured JSON;
- `openai/gpt-oss-120b`: deep review khi ambiguity/repair cao;
- `llama-3.1-8b-instant`: fallback khi lane OSS lỗi.

Observer chạy song song với model chính. Bubble, TTS và `Decision` không chờ observer.
Kết quả chỉ được áp dụng sau public commit vào:

- relationship state với delta nhỏ và clamp;
- OutcomeReport của frame trước;
- session ledger / user-turn metadata;
- panel snapshot;
- context quan hệ cực ngắn cho lượt kế tiếp.

Classifier social deterministic cũ mặc định chạy shadow/no-op khi observer AI có mặt.
Nó không được mutate relational permission, hạ authority claim, vô hiệu lịch sử hoặc chặn memory commit.
Runtime vẫn giữ sự thật cơ học như interrupt, tool receipt, TTS failure và exact transport state.
