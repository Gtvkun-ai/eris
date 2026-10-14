# Verification — gói eloquence (iteration đầu)

Môi trường: Windows PowerShell. Terminal báo `Exit Code: -1` sai cho mọi lệnh; đánh
giá qua stdout thật (dòng `N passed`), ghi output ra file rồi đọc. Venv:
`c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe`. Worktree:
`c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence`, branch `feat/eris-eloquence`,
base HEAD `cb4e51dc`.

## Thay đổi theo từng việc

### Việc 1 — viết lại `_public_reply_prompt`
`src/runtime/ai_orchestrated/model_router.py` (`_public_reply_prompt`). Chỉ đổi NỘI DUNG
chuỗi trả về; giữ nguyên chữ ký hàm, 2 tham số (`display_language_hint`,
`speech_language_hint`), mọi biến nội suy (`display_language`, `speech_language`,
`style_rules`), và nhúng nguyên văn `CHAT_VOICE_CORE_V39`, `CHAT_STYLE_RULES_V39`,
`STANCE_PUBLIC_RULES_VI`. Vẫn trả `str` → `generate_public_reply` nối `+=` hợp lệ.

Hình dạng mới 5 khối: (1) vào vai "chính ERIS đang nói, ngồi cạnh người thật" + V39;
(2) hai bề mặt text/speech_text + khoá ngôn ngữ gọn; (3) ý do Root quyết, writer nói tự
nhiên không tự đẻ intent + phản xạ nhỏ được phép; (4) lằn ranh trung thực (grounding/
memory/capability/receipt/EVIDENCE_ENRICHMENT_V73) + STANCE_PUBLIC_RULES_VI + xin lỗi;
(5) soft metadata tùy chọn + public text ưu tiên số một + "Return JSON only." + 3 field.

Đã bỏ/gọn: `HARD DISPLAY LANGUAGE LOCK` (→ câu thường vẫn khoá ngôn ngữ), "không markdown/
không reasoning/không stage direction" (sanitizer lo), các câu lặp ý "writer chỉ hiện thực"
gộp còn ~2 câu giọng người. Giữ đầy đủ ý lằn ranh trung thực, KHÔNG làm yếu.

Nguyên văn prompt mới (render `_public_reply_prompt("vi","ja")`) đã dán ra
`.agents/tasks/eloquence-impl/new_prompt.txt` để user duyệt gu.

### Việc 2 — bật thinking cho writer public
`src/runtime/conversation/runtime_writer.py`: default `thinking_mode` `"disabled"` →
`"enabled"` (vẫn `runtime_context.get(...)` nên override được). KHÔNG đổi `reasoning_effort`
(vẫn `"low"`). Comment cập nhật cho khớp.

Deadline writer: `_public_writer_deadline_seconds()` vẫn 24s. Khi thinking bật, provider ép
`max_tokens>=2048` + bỏ temperature sampling. Writer chỉ wording MỘT move đã khóa (không
reasoning dài), nên một pass thinking ngắn vẫn vừa 24s. Rủi ro: dưới tải nặng có thể gần
deadline; nếu time out thực tế, env `ERIS_PUBLIC_WRITER_DEADLINE_SEC` nới được mà không đổi code
(ghi nhận, không làm trong gói này).

### Việc 3 — hạ default đuôi ですね
`src/runtime/speech_persona_polish.py` `_signature_ending_policy`: đổi CẢ HAI literal 0.55 →
0.25 (`_runtime_float("signature_ending_rate", 0.25)` và `round(_clamp01(rate, 0.25), 3)`).
Giữ nguyên mode-gating: technical/boundary tắt; soft `min(0.58, rate+0.08)`; dry `min(rate,0.24)`;
fragment `<8` `min(rate,0.12)`. KHÔNG đổi `_runtime_float`/`_clamp01`.

### Việc 4 — surface không drop mặc định
`src/llm/deepseek_workers.py`: default droppable set `{"inner","seed","surface"}` → `{"inner","seed"}`.
Env `ERIS_DS_SURFACE_DROP_IF_BUSY` vẫn override (first arg `_env_flag` không đổi). Timeout chờ
actor `_actor_acquire_timeout` default 2s (`ERIS_DS_ACTOR_WAIT_TIMEOUT_S`/
`ERIS_DS_SURFACE_ACTOR_WAIT_TIMEOUT_S`), clamp ≤ request timeout ≤ deadline 24s. Rủi ro: dưới
tải nặng lượt user chờ thêm tối đa ~2s (actor rảnh) thay vì rơi fallback thô — đổi có chủ đích.

## Test đã chạy (đọc stdout thật)

Lệnh (từ cwd = worktree root, `-o addopts=""`), ghi ra file rồi đọc:

Nhóm targeted (task1-4):
`src/tests/test_eloquence_public_prompt.py src/tests/test_eloquence_signature_rate.py
test_v38_infj_voice_contract.py test_v39_affective_voice_state.py
conversation/test_runtime_writer_v12.py test_deepseek_multi_worker_base.py`
→ **53 passed, 1 failed** (`pytest_task1_4.txt`). Fail duy nhất:
`test_research_client_no_longer_falls_back_to_main_or_fallback` — PRE-EXISTING.

Regression tổng:
`src/tests/conversation test_v38_infj_voice_contract.py test_v39_affective_voice_state.py
test_architecture_c_runtime_regressions.py test_public_turn_runtime.py
test_public_writer_recovery_v6.py test_public_turn_trace_v97.py
test_eloquence_public_prompt.py test_eloquence_signature_rate.py test_deepseek_multi_worker_base.py`
→ **444 passed, 2 failed** (`pytest_regression.txt`).

## Hai test fail đều PRE-EXISTING (chứng minh trên base HEAD cb4e51dc)

Stash toàn bộ thay đổi rồi chạy lại từng test (xem `pytest_base_research.txt`,
`pytest_base_preflight.txt`, `stash.txt`, `stash2.txt`):

1. `test_deepseek_multi_worker_base.py::test_research_client_no_longer_falls_back_to_main_or_fallback`
   — fail trên base (`1 failed`). Về `LlmService.research_client`, không liên quan 4 việc.
2. `conversation/test_root_session_bootstrap_v12.py::test_root_preflight_allows_large_self_but_writer_cap_unchanged`
   — fail trên base (`1 failed`). Về `llm.token_budget.preflight` cap, không liên quan 4 việc.

Không có test nào fail do thay đổi của gói này.

## Test cập nhật có chủ đích (không phải regression mới)

`test_deepseek_multi_worker_base.py`: test cũ `test_surface_worker_drops_when_actor_is_busy_by_default`
khẳng định hành vi CŨ (surface drop mặc định) — mâu thuẫn trực tiếp với Việc 4. Đã thay bằng
`test_surface_worker_waits_instead_of_dropping_by_default` (surface chờ, không drop) +
`test_surface_worker_drop_if_busy_env_override_still_works` (env bật lại drop vẫn hoạt động).

## Test mới

- `src/tests/test_eloquence_public_prompt.py`: prompt chứa mảnh bắt buộc (CHAT_VOICE_CORE_V39,
  STANCE_PUBLIC_RULES_VI, tiếng Việt/tiếng Nhật, should_speak/text/speech_text, grounding/
  capability/receipt/EVIDENCE_ENRICHMENT_V73, vào-vai ERIS/người thật, Return JSON only) và
  KHÔNG còn chuỗi đã bỏ (HARD DISPLAY LANGUAGE LOCK, không reasoning, stage direction,
  "public writer cho một lượt chat", "one concise", "ấm kín").
- `src/tests/test_eloquence_signature_rate.py`: default rate ~0.25 ở mode neutral; dry ≤0.24;
  technical tắt (selected False, rate 0.0).
- `conversation/test_runtime_writer_v12.py`: thêm 2 test — thinking_mode default "enabled",
  vẫn override được "disabled".
