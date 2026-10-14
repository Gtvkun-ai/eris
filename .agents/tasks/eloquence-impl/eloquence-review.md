# Eloquence pass — nâng giọng public của Eris: prompt người-hoá, thinking cho writer, hạ đuôi ですね, surface không drop

Gói này nâng chất giọng public của Eris mà không chạm vào kiến trúc semantic. Bốn thay đổi, mỗi thay đổi một commit riêng: (1) viết lại nội dung chuỗi `_public_reply_prompt` theo giọng con người, naturalness/vào-vai lên đầu và các lằn ranh dồn về cuối; (2) bật `thinking_mode` mặc định cho writer public để pha chọn chữ cuối mượt hơn; (3) hạ default tỉ lệ đuôi `ですね` từ 0.55 xuống 0.25; (4) bỏ `surface` khỏi set drop-if-busy mặc định để lượt user thà chờ còn hơn rơi fallback thô. Chữ ký hàm, hằng nhúng (V39, stance), hai bề mặt text/speech_text, khoá ngôn ngữ và mọi config khác đều giữ nguyên; hai file cấm (`eris_voice_contract.py`, `social_stance_policy.py`) không bị đụng.

Watch for: không có finding chặn. Prompt mới vẫn nhúng nguyên văn `CHAT_VOICE_CORE_V39`/`CHAT_STYLE_RULES_V39`/`STANCE_PUBLIC_RULES_VI`, giữ đủ ý các lằn ranh trung thực và giữ chất INFJ (confirmed). Hai điểm thuộc gu/vận hành đáng ghi nhận nhưng không chặn: khoá ngôn ngữ nay viết giọng thường thay vì câu `HARD DISPLAY LANGUAGE LOCK` viết hoa — ý khoá còn nguyên nhưng cường độ nhấn mạnh với model nhẹ hơn (possible); và deadline writer 24s cố định trong khi thinking giờ luôn bật mặc định (likely, có đường env nới).

**Verdict**: APPROVED

## High-level view

Trọng tâm là commit prompt. Toàn bộ chuỗi trả về của `_public_reply_prompt` được viết lại thành năm khối theo thứ tự người-đọc: vào vai → hai bề mặt + khoá ngôn ngữ → ý do Root quyết/writer chỉ nói ra → lằn ranh trung thực + stance + xin lỗi → soft metadata. Chữ ký `(_public_reply_prompt(display_language_hint="vi", speech_language_hint="ja") -> str)`, hai biến nội suy `display_language`/`speech_language`, `style_rules`, và ba hằng nhúng đều giữ nguyên, nên các phép `+=` hạ nguồn trong `generate_public_reply` vẫn hợp lệ. Chất INFJ được diễn đạt bằng "điềm, tinh ý, chiều sâu nội tâm, ấm nhưng không phô" — không trượt sang xởi lởi/trợ lý vui vẻ, và tránh đúng cụm `ấm kín` mà regression cấm.

Các regression assertion của hai test V38/V39 tự thoả vì các chuỗi chúng đòi (`AFFECTIVE_VOICE_STATE`, `preset ấm/lạnh/điềm/restrained`, `Độ dài đi theo nội dung`, `mood vui`) đều đến từ `CHAT_VOICE_CORE_V39`/`CHAT_STYLE_RULES_V39` được nhúng nguyên văn, và prompt mới không tái xuất các chuỗi bị cấm.

Writer public đổi `thinking_mode` default `disabled`→`enabled`, vẫn đọc qua `runtime_context.get` nên override được; `reasoning_effort` giữ nguyên `low` đúng yêu cầu. Deadline 24s không đổi — writer chỉ wording một move đã khoá nên một pass thinking ngắn vừa khung này, nhưng đây là điểm nên theo dõi dưới tải.

Config TTS: cả hai literal `0.55` trong `_signature_ending_policy` (call-site `_runtime_float` và clamp fallback `_clamp01`) đều về `0.25`; mode-gating (technical/boundary tắt, soft +0.08, dry cap 0.24, fragment cap 0.12) giữ nguyên.

Worker: `surface` rời set drop-if-busy mặc định, còn `{inner, seed}`; env `ERIS_DS_SURFACE_DROP_IF_BUSY` vẫn bật lại được; thời gian chờ actor mặc định ~2s nằm trong deadline.

<details>
<summary>Issues (2)</summary>

1. **Khoá ngôn ngữ hạ nhấn mạnh (không chặn)** — câu `HARD DISPLAY LANGUAGE LOCK` viết hoa đổi thành câu thường "Giữ nguyên text trong tiếng Việt...". Ý khoá còn đủ; nếu quan sát thấy model thỉnh thoảng trộn ngôn ngữ, cân nhắc nhấn lại một cụm mạnh mà không cần khôi phục chuỗi cũ.
2. **Deadline writer 24s cố định với thinking luôn bật (không chặn)** — theo dõi tỉ lệ time-out của writer dưới tải; nếu xảy ra, nới qua env `ERIS_PUBLIC_WRITER_DEADLINE_SEC` thay vì sửa code.

</details>

<details>
<summary>Details</summary>

### Prompt được viết lại giữ nguyên khung hợp đồng, chỉ đổi giọng

Chữ ký hàm, hai tham số và ba biến nội suy (`display_language`, `speech_language`, `style_rules`) không đổi, hàm vẫn trả `str`, nên `generate_public_reply` tiếp tục nối `system += ...` cho `locked_semantic_frame` và `context_parts`. `f"{CHAT_VOICE_CORE_V39} {style_rules} "` và `+ STANCE_PUBLIC_RULES_VI + " "` giữ nguyên văn — xác nhận bằng blob committed tại HEAD, không chỉ bằng diff. Khối mở đầu vào vai vẫn chứa cụm `giọng nói trực tiếp của ERIS` mà test V38 đòi; khối ba gộp các câu lặp ý "Root quyết, writer chỉ nói ra, không tự đẻ intent/câu hỏi/CTA" còn hai câu kèm cho phép phản xạ nhỏ rất người.

Chất INFJ diễn đạt bằng "điềm và ấm nhưng không phô, đọc được không khí", không trượt sang giọng trợ lý xởi lởi. Bản viết lại tránh đúng cụm `ấm kín` (hai từ liền) mà `test_v39` cấm — "ấm" không đứng ngay trước "kín".

### Lằn ranh trung thực giữ nguyên ý, chỉ mượt câu

Toàn bộ bề mặt an toàn còn đủ: không bịa grounding/memory/capability; `EVIDENCE_ENRICHMENT_V73` dùng làm positive input đúng scope mà không nâng unknown thành fact hay dựng cầu nối ký ức giả; không nhận đã hoàn tất tool khi chưa có receipt; thiếu ref thì không khẳng định chắc; `claim_manifest`/`self_capability_claims` chỉ dùng ref/capability_id được cấp. Khối cuối giữ bất biến quan trọng: lỗi/thiếu soft metadata không bao giờ được làm bỏ `text`/`speech_text`, public text ưu tiên số một, cùng `Return JSON only.` và ba field bắt buộc. Câu xin lỗi giữ đúng phân biệt: bất đồng với ấn tượng chủ quan thì không tự nhận sai; user sửa một fact thì cập nhật gọn — bản mới rút "fact/current-world claim" còn "một fact", thu hẹp câu chữ không đổi hành vi.

Khoá ngôn ngữ chuyển từ `HARD DISPLAY LANGUAGE LOCK` viết hoa sang câu thường "Giữ nguyên text trong tiếng Việt: đừng chuyển cả câu sang một ngôn ngữ khác, một mẩu loại khác chen vào cũng không." Ý khoá còn chặt (cấm cả câu lẫn mẩu chen) nhưng cường độ nhấn với model nhẹ hơn chuỗi viết hoa cũ (possible) — lựa chọn gu đã nằm trong kế hoạch, không chặn.

### Thinking bật mặc định cho writer, reasoning_effort giữ nguyên

`thinking_mode` default `"disabled"`→`"enabled"`, vẫn đọc `runtime_context.get("thinking_mode", "enabled")` nên override được — test `test_runtime_writer_thinking_mode_still_overridable` chứng minh. `reasoning_effort` giữ `"low"` (confirmed). Deadline writer `_public_writer_deadline_seconds()` vẫn 24s cố định trong khi thinking giờ luôn bật mặc định (provider ép `max_tokens>=2048`, bỏ temperature sampling); dưới tải nặng cần theo dõi tỉ lệ time-out, nới qua env `ERIS_PUBLIC_WRITER_DEADLINE_SEC` thay vì sửa code (likely).

### Test đi kèm từng việc

Coder để lại bằng chứng verification (`verification.md` + hai test file mới + sửa hai test cũ). Nhóm targeted 53 passed / 1 failed và regression tổng 444 passed / 2 failed; cả hai fail (`test_research_client_no_longer_falls_back...`, `test_root_preflight_allows_large_self...`) được chứng minh pre-existing trên base `cb4e51dc` qua stash, không liên quan bốn việc. Test cũ `test_surface_worker_drops_when_actor_is_busy_by_default` khẳng định hành vi cũ nên được thay bằng hai test mô tả hành vi mới — đây là cập nhật có chủ đích, không phải regression. Không spot-check lại suite (coder đã chạy, bằng chứng đầy đủ); đã đối chiếu blob committed tại HEAD để chắc nội dung prompt khớp `new_prompt.txt`.

### Mỗi việc một commit riêng

Bốn commit tách bạch, message rõ, không `qq`: `74d0d095 feat(voice): rewrite public writer prompt...` (model_router.py + test prompt), `1c639658 feat(writer): enable thinking...` (runtime_writer.py + test writer), `04cffff5 feat(tts): lower desu-ne...` (speech_persona_polish.py + test rate), `afc02d90 fix(workers): drop surface...` (deepseek_workers.py + test worker). Không đổi `tts.language`, không xóa pha viết câu, không đụng hai file cấm.

</details>

<details>
<summary>File map</summary>

- `src/runtime/ai_orchestrated/model_router.py` — viết lại nội dung chuỗi `_public_reply_prompt` (giữ chữ ký, hằng nhúng, hai bề mặt, khoá ngôn ngữ, lằn ranh trung thực).
- `src/runtime/conversation/runtime_writer.py` — `thinking_mode` default `disabled`→`enabled`; `reasoning_effort` giữ `low`.
- `src/runtime/speech_persona_polish.py` — hai literal `0.55`→`0.25` trong `_signature_ending_policy`.
- `src/llm/deepseek_workers.py` — bỏ `surface` khỏi set drop-if-busy mặc định.
- `src/tests/test_eloquence_public_prompt.py` (mới) — prompt giữ mảnh bắt buộc, bỏ chuỗi cũ.
- `src/tests/test_eloquence_signature_rate.py` (mới) — default rate 0.25, gating không đổi.
- `src/tests/conversation/test_runtime_writer_v12.py` — thêm hai test thinking default/override.
- `src/tests/test_deepseek_multi_worker_base.py` — thay test drop cũ bằng test wait + test env override.

Diff đầy đủ: `git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence diff cb4e51dc HEAD`.

</details>
