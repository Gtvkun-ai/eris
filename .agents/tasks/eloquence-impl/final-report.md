# ERIS Eloquence — Báo cáo cuối

Branch: `feat/eris-eloquence` trong worktree `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence`
Base: `main` @ `cb4e51dc` (rebase là no-op — branch đã nằm thẳng trên main hiện tại).

Chốt từ hội thoại với user: **cách 2** — bỏ pha viết-lại, để não (Root) viết thẳng câu cuối, writer vẫn giữ nhưng **bật thinking** cho câu public; viết lại prompt dạy-nói-hay lên đầu, cắt lệnh gò phong cách, giữ lệnh an toàn; hạ đuôi ですね; giọng Nhật giữ nguyên; style INFJ giữ. Mốc "20–30%" cho đuôi ですね → chốt **0.25**.

---

## 4 việc đã làm

### 1. Writer prompt viết lại — human, INFJ-first
Commit `74d0d095`. File: `src/runtime/ai_orchestrated/model_router.py:1691-1721` (hàm `_public_reply_prompt`).

- Mở đầu bằng 3 câu dạy-nói-tự-nhiên (ERIS đang ngồi cạnh người thật, để tâm trạng/sự tinh ý/chiều sâu thấm vào câu, điềm và ấm nhưng không phô) thay cho câu thủ tục cũ `"...trong một lượt chat. Trả đúng MỘT JSON."`.
- Dồn khối metadata/soft-field (claim_manifest, semantic_frame, assistant_act, self_capability_claims, performance_hint...) xuống **cuối**, gộp một đoạn, viết gọn lại.
- Giữ nguyên khối an toàn + stance: `STANCE_PUBLIC_RULES_VI` (từ `social_stance_policy.py`) và quy tắc không-tự-xin-lỗi khi user chỉ bất đồng chủ quan.
- Giữ nguyên core/style contract (`CHAT_VOICE_CORE_V39`, `CHAT_STYLE_RULES_V39` từ `eris_voice_contract.py`) — **không đụng** các constant chia sẻ này.

### 2. Bật thinking cho câu public
Commit `1c639658`. File: `src/runtime/conversation/runtime_writer.py:331-341`.

- `thinking_mode`: default `"disabled"` → `"enabled"`.
- `reasoning_effort` giữ `"low"` — cố ý không mở reasoning_effort cao để tránh một vòng cognition dài thứ hai sau Root; chỉ bật thinking để pha chọn chữ cuối mượt hơn. (Khớp ý user: Whale chỉ có nút thinking, không ghim v4-pro.)

### 3. Hạ đuôi ですね (desu-ne signature)
Commit `04cffff5`. File: `src/runtime/speech_persona_polish.py:174-196`.

- Default rate `0.55` → `0.25` (hai chỗ: giá trị đọc runtime và clamp fallback).
- Giữ nguyên cap `0.12` cho câu rất ngắn (<8 ký tự) và cơ chế `_stable_roll`.

### 4. Fix drop_if_busy cho writer public (câu user thà chờ còn hơn fallback thô)
Commit `afc02d90`. File: `src/llm/deepseek_workers.py:416-419`.

- Default drop set: `{"inner", "seed", "surface"}` → `{"inner", "seed"}`. Surface (writer public) không còn tự drop khi actor bận; lượt user chờ actor rảnh thay vì rơi câu fallback thô.
- Env override `ERIS_DS_SURFACE_DROP_IF_BUSY=1` vẫn bật lại được (có test riêng).

---

## So sánh prompt cũ vs mới

Full prompt mới (đã assemble, 5261 ký tự) ở: `c:\Users\Gtvkun\Documents\GitHub\eris\.agents\tasks\eloquence-impl\new_prompt.txt`.
Prompt cũ assemble ra 6043 ký tự → mới gọn hơn ~780 ký tự nhưng đọc "người" hơn.

**Bỏ / cắt:**
- Câu mở thủ tục `"Bạn đang là giọng nói trực tiếp của ERIS trong một lượt chat. Trả đúng MỘT JSON."`.
- Các lệnh gò lặp: `"HARD DISPLAY LANGUAGE LOCK"`, `"Không markdown, không reasoning, không stage direction..."` (đã được tầng sanitizer/contract lo) — gộp còn một câu khóa ngôn ngữ nhẹ nhàng.
- Đoạn liệt kê dài `"Không được tự quyết nên giữ continuity, kéo lại topic cũ..."` + `"RootAgent đã quyết định toàn bộ ý nghĩa... Writer CHỈ hiện thực ROOT_CONVERSATION_MOVE_V12..."` → nén thành 3 câu nói Root quyết ý, writer nói cho hay, được phép phản xạ người.
- Khối soft-metadata trước nằm rải giữa prompt → gom xuống cuối, một đoạn.

**Giữ nguyên:**
- Toàn bộ `CHAT_VOICE_CORE_V39` + `CHAT_STYLE_RULES_V39` (affect-authoritative, dry humor, relationship bandwidth, chống mở/kết máy móc).
- Toàn bộ `STANCE_PUBLIC_RULES_VI` (nói thẳng lập trường khi stance_contest, không tự rút lời).
- Lệnh trung thực: không bịa grounding/memory/capability, không nhận hoàn tất tool khi chưa có receipt, EVIDENCE_ENRICHMENT_V73 dùng đúng phạm vi.
- Hợp đồng public text ưu tiên số một; soft metadata best-effort.

**Viết lại giọng gì:**
Từ giọng "spec/điền form, cấm đoán liệt kê" → giọng "người đang nói, chỉ dẫn bằng cảm". Lệnh cấm chuyển từ mệnh lệnh cứng ("tuyệt đối không...", "CHỈ hiện thực...") sang hướng dẫn mềm ("đừng...", "cứ để bật ra khi cảm xúc thật đang có"). Dạy-nói lên đầu, cấm-đoán xuống cuối, bỏ phần trùng sanitizer.

---

## Kết quả test (THẬT)

Lệnh: `python -m pytest src/tests/conversation src/tests/test_eloquence_public_prompt.py src/tests/test_eloquence_signature_rate.py src/tests/test_deepseek_multi_worker_base.py -o addopts="" -k "model_router or eris_voice_contract or speech_persona_polish or social_stance_policy or eloquence or writer or runtime_writer or conversation or deepseek"`

Trên `feat/eris-eloquence` (sau rebase):
- **341 passed, 2 failed** trong 17.23s.

Hai fail:
1. `src/tests/conversation/test_root_session_bootstrap_v12.py::test_root_preflight_allows_large_self_but_writer_cap_unchanged`
2. `src/tests/test_deepseek_multi_worker_base.py::test_research_client_no_longer_falls_back_to_main_or_fallback`

**Cả hai là pre-existing fail, KHÔNG liên quan eloquence.** Chứng minh: checkout detached `main` @ `cb4e51dc` (worktree tạm `_basecheck`, đã xóa) chạy đúng 2 test đó → **2 failed in 3.33s**, cùng y hệt AssertionError (`writer != original` và `research_client is None`).

Lý do không liên quan: 2 test này đụng `llm/token_budget.py` (preflight), `runtime/inference_broker.py`, `llm/service.py` (research_client) — **không có file nào trong số đó bị 4 commit eloquence chạm tới**. Các file eloquence sửa: `deepseek_workers.py`, `model_router.py`, `runtime_writer.py`, `speech_persona_polish.py` + test đi kèm.

Test eloquence mới đều xanh: `test_eloquence_public_prompt.py`, `test_eloquence_signature_rate.py`, các test drop_if_busy surface mới trong `test_deepseek_multi_worker_base.py`, và `test_runtime_writer_v12.py`.

---

## Điểm user cần để mắt khi review

1. **Gu giọng văn**: đọc `new_prompt.txt` để duyệt — đây là chuỗi prompt MỚI đầy đủ đã assemble. Nếu thấy câu mở ("đang ngồi cạnh một người thật...") hơi quá tình cảm so với ý muốn, chỉnh trực tiếp trong `model_router.py` hàm `_public_reply_prompt`.
2. **Thinking bật mặc định cho public**: tăng chút độ trễ pha wording. Nếu Whale quá chậm, có thể tắt qua `thinking_mode` ở runtime_context.
3. **ですね 0.25**: nếu vẫn thấy nhiều/ít, chỉnh runtime `signature_ending_rate`. Con số hiện tại là default; runtime override vẫn thắng.
4. **drop_if_busy**: surface giờ chờ actor (tối đa ~2s theo `_actor_acquire_timeout`). Nếu thấy lượt user bị treo lâu khi actor bận, cân nhắc hạ timeout thay vì bật lại drop.
5. **2 pre-existing fail**: không do task này, nhưng user nên biết chúng đang đỏ trên main (research_client fallback + root preflight writer cap).

---

## Nhắc orchestrator

Branch `feat/eris-eloquence` trong `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence` đã rebase sạch trên `main` (cb4e51dc), working tree clean, 4 commit sẵn sàng. Vì git không cho di chuyển branch đang checkout ở worktree khác (và không được đụng main của user), **orchestrator** cần tự fast-forward `main` lên `feat/eris-eloquence` và dọn worktree. Agent này **không** merge, **không** push, **không** xóa worktree.
