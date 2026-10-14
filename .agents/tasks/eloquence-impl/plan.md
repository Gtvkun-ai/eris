# Implementation Plan — Gói "eloquence" (Option B)

Mục tiêu: làm câu nói public của Eris tự nhiên/có hồn hơn mà KHÔNG mất chất INFJ, KHÔNG đổi
giọng Nhật TTS, KHÔNG xóa pha viết câu. Rủi ro THẤP-TRUNG (đổi text prompt + vài config/default).

## Bối cảnh đã xác nhận (đọc code, không phải giả định)

- Worktree: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence`, branch `feat/eris-eloquence`,
  base HEAD `cb4e51dc` (= origin/main). Mọi git dùng `git -C <worktree>`.
- Python: `c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe` (xác nhận tồn tại).
- `pytest.ini`: `pythonpath = src .`; `testpaths = src/tests`; `addopts = -ra`. Import test dạng
  `from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter`. KHÔNG có conftest.py.
- `_public_reply_prompt` tại `src/runtime/ai_orchestrated/model_router.py` dòng 1672-1715
  (`@staticmethod`, chữ ký `_public_reply_prompt(display_language_hint="vi", speech_language_hint="ja") -> str`).
- Hằng nhúng (KHÔNG sửa file nguồn): `CHAT_VOICE_CORE_V39`, `CHAT_STYLE_RULES_V39` từ
  `runtime.eris_voice_contract` (import dòng 18-20); `STANCE_PUBLIC_RULES_VI` từ
  `runtime.social_stance_policy` (import dòng 16).
- Nối chuỗi hạ nguồn hợp lệ: `generate_public_reply` dòng ~1841 `system = self._public_reply_prompt(...)`
  rồi `system += "\n\n..."` khi có `locked_semantic_frame` (dòng 1842-1848) và `system += "\n\n" + ...`
  cho `context_parts`. `_public_reply_prompt` trả `str` nên các phép `+=` này giữ nguyên hợp lệ.
- Writer defaults: `src/runtime/conversation/runtime_writer.py` dòng 336-337:
  `"reasoning_effort": runtime_context.get("reasoning_effort", "low"),` và
  `"thinking_mode": runtime_context.get("thinking_mode", "disabled"),`.
- Deadline writer: `_public_writer_deadline_seconds()` (model_router dòng 164-180) default 24.0s,
  clamp `max(3.0, min(_semantic_deadline_seconds(), 60.0, raw))`.
- Signature ending: `src/runtime/speech_persona_polish.py` `_signature_ending_policy`
  (dòng ~245-283). Có HAI literal `0.55`: `rate = _runtime_float("signature_ending_rate", 0.55)`
  (dòng ~259) và `rate = round(_clamp01(rate, 0.55), 3)` (dòng ~279). Cả hàm `_runtime_float`
  (dòng ~111) cũng truyền `default` làm fallback của `_clamp01` — không đổi hàm đó, chỉ đổi
  đối số truyền vào tại call-site trong `_signature_ending_policy`.
- drop_if_busy: `src/llm/deepseek_workers.py` dòng 417-421 — CHỈ MỘT khối (báo cáo nói "2 class"
  nhưng grep xác nhận duy nhất một định nghĩa):
  `self._drop_if_busy = _env_flag(f"ERIS_DS_{self.worker_role.upper()}_DROP_IF_BUSY",
  self.worker_role in {"inner", "seed", "surface"})`. Timeout chờ: `_actor_acquire_timeout`
  (dòng ~424) default 2.0s qua `ERIS_DS_ACTOR_WAIT_TIMEOUT_S` / `ERIS_DS_SURFACE_ACTOR_WAIT_TIMEOUT_S`,
  clamp [0,120]; luôn ≤ request timeout nếu có — không vượt deadline writer 24s.

## Ràng buộc regression đã biết từ test hiện có (phải thỏa khi viết lại prompt)

- `src/tests/test_v38_infj_voice_contract.py::test_v38_chat_contract_is_positive_infj_voice_not_shortness_target`
  yêu cầu prompt CHỨA: `"giọng nói trực tiếp của ERIS"`, `"AFFECTIVE_VOICE_STATE"`,
  `"preset ấm/lạnh/điềm/restrained"`, `"Độ dài đi theo nội dung"`; và KHÔNG chứa:
  `"public writer cho một lượt chat"`, `"one concise"` (lowercase).
  → Ba chuỗi `AFFECTIVE_VOICE_STATE` / `preset ấm/lạnh/điềm/restrained` / `Độ dài đi theo nội dung`
    đến TỪ `CHAT_VOICE_CORE_V39` (giữ nhúng nguyên văn), nên tự thỏa. Chuỗi mở đầu mới PHẢI vẫn
    chứa cụm `"giọng nói trực tiếp của ERIS"`.
- `src/tests/test_v39_affective_voice_state.py::test_v39_personality_is_shape_not_static_temperature`
  yêu cầu prompt CHỨA `"AFFECTIVE_VOICE_STATE"`, `"preset ấm/lạnh/điềm/restrained"`, `"mood vui"`;
  KHÔNG chứa `"ấm kín"`, `"default surface is quietly warm"`.
  → `"mood vui"` đến từ `CHAT_VOICE_CORE_V39`; giữ nhúng là thỏa. LƯU Ý: KHÔNG được viết chữ
    `"ấm kín"` trong phần prompt mới (dù mô tả INFJ) vì vi phạm assertion này — diễn đạt INFJ bằng
    chữ khác (vd "ấm một cách kín đáo" KHÔNG được vì chứa "ấm kín"? → KHÔNG, "ấm kín" là 2 từ liền;
    tránh để "ấm" đứng ngay trước "kín". Dùng "ấm nhưng không phô", "điềm và tinh ý" v.v.).

## Thứ tự thực hiện: Việc 1 → 2 → 3 → 4, mỗi việc một commit riêng (KHÔNG đặt message 'qq').

---

- [ ] 1. (CHÍNH) Viết lại nội dung chuỗi trả về của `_public_reply_prompt` theo giọng-con-người,
      INFJ, naturalness lên đầu / ràng buộc xuống cuối; GIỮ nguyên chữ ký hàm, 2 tham số, mọi biến
      nội suy (`display_language`, `speech_language`, `style_rules`) và các hằng nhúng.
      Files: `src/runtime/ai_orchestrated/model_router.py` (method `_public_reply_prompt`, dòng 1672-1715).
      Chi tiết bắt buộc:
      - GIỮ: `f"{CHAT_VOICE_CORE_V39} {style_rules} "` (nguyên văn, nhúng cả 2 hằng V39);
        `+ STANCE_PUBLIC_RULES_VI + " "`; biến `display_language`/`speech_language`; tách hai bề mặt
        `text` (hiển thị) / `speech_text` (đọc); quy tắc không bịa grounding/memory/capability/receipt
        (giữ ĐẦY ĐỦ Ý các lằn ranh trung thực, chỉ viết mượt — KHÔNG làm yếu); logic language-lock
        (giữ Ý khoá ngôn ngữ: text đúng display language, không trộn cả câu sang ngôn ngữ khác);
        câu xin lỗi (bất đồng chủ quan → không tự nhận sai; user sửa fact → cập nhật gọn);
        soft metadata tùy chọn (performance_hint/semantic_frame/assistant_act/claim_manifest/
        self_capability_claims — thiếu KHÔNG được bỏ text/speech_text); `claim_manifest`/
        `self_capability_claims` không bịa ref/capability_id; `EVIDENCE_ENRICHMENT_V73` dùng làm
        positive input; chức năng "writer KHÔNG phải semantic authority"; `"Return JSON only."`;
        3 field bắt buộc `should_speak`, `text`, `speech_text`.
      - ĐƯỢC BỎ/GỌN: câu "Không markdown, không reasoning, không stage direction trong text, không
        ghép tiếng Nhật vào text..." (FinalSurfaceSanitizer/StageTransformer đã lo — bỏ phần
        markdown/reasoning/stage direction; GIỮ Ý không trộn ngôn ngữ cả câu nhưng viết giọng
        thường); hạ giọng gắt `"HARD DISPLAY LANGUAGE LOCK"` viết hoa → câu thường vẫn khoá ngôn ngữ;
        GỘP cụm lặp "RootAgent đã quyết định... Writer CHỈ hiện thực" + "Không tự thêm intent mới..."
        + "Không được tự quyết giữ continuity/kéo topic/đổi topic/hỏi thêm/im lặng" + "Nếu say yêu cầu
        câu hỏi thì..." → còn 1-2 câu giọng người: ý và hướng lượt do RootAgent chọn trong `say`,
        writer nói ra tự nhiên và đúng cảm, không tự đẻ chủ đề/câu hỏi/CTA mới; nhưng phản xạ nhỏ rất
        người (cảm thán, nhịp ngập ngừng, mẩu câu cụt) cứ để bật ra khi cảm xúc thật đang có.
      - HÌNH DẠNG MỚI (5 khối, theo thứ tự):
        (1) Mở đầu VÀO VAI: câu dạng "Bạn đang là chính ERIS đang nói, không phải một bộ máy điền
            form; nói như đang ngồi cạnh một người thật, để tâm trạng và sự tinh ý thấm vào câu."
            — PHẢI còn cụm `"giọng nói trực tiếp của ERIS"` ở đâu đó khối đầu (regression). Rồi
            `f"{CHAT_VOICE_CORE_V39} {style_rules} "`. (Giữ `"Trả đúng MỘT JSON"` hoặc tương đương.)
        (2) Giữa: hai bề mặt text/speech_text + khoá ngôn ngữ (gọn, giọng thường, có
            `display_language`/`speech_language`).
        (3) Giữa: khối gộp "ý đã do Root quyết, writer nói ra tự nhiên, không tự đẻ intent/câu hỏi/
            topic" + "phản xạ nhỏ được phép".
        (4) Gần cuối: lằn ranh trung thực (không bịa grounding/memory/capability/receipt; evidence
            đúng scope; EVIDENCE_ENRICHMENT_V73) + `STANCE_PUBLIC_RULES_VI` + câu xin lỗi.
        (5) Cuối: soft metadata tùy chọn + "Lỗi/thiếu soft metadata KHÔNG được bỏ text/speech_text,
            public text ưu tiên số 1" + `"Return JSON only."` + 3 field bắt buộc.
      - TRÁNH chữ `"ấm kín"` (2 từ liền), `"one concise"`, `"public writer cho một lượt chat"`
        trong chuỗi mới (regression negative asserts). INFJ diễn đạt bằng "điềm, tinh ý, chiều sâu
        nội tâm, ấm nhưng không phô, đọc được không khí, không xởi lởi/kiểu trợ lý vui vẻ".
      - CODER PHẢI dán NGUYÊN VĂN chuỗi prompt MỚI đầy đủ (phần Python literal trả về, có thể kèm
        giá trị `display_language="tiếng Việt"`, `speech_language="tiếng Nhật"` minh hoạ) ra
        `c:\Users\Gtvkun\Documents\GitHub\eris\.agents\tasks\eloquence-impl\new_prompt.txt` để user
        duyệt gu giọng văn, TRƯỚC khi commit việc 1.
      - Thêm test mới `src/tests/test_eloquence_public_prompt.py`:
        * import `from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter` và các hằng
          `from runtime.eris_voice_contract import CHAT_VOICE_CORE_V39` +
          `from runtime.social_stance_policy import STANCE_PUBLIC_RULES_VI`.
        * `p = AIRuntimeModelRouter._public_reply_prompt("vi", "ja")`.
        * assert CHỨA (positive): `CHAT_VOICE_CORE_V39[:40]` (hoặc cả hằng) in p; `STANCE_PUBLIC_RULES_VI`
          first ~30 chars in p; `"tiếng Việt"` in p; `"tiếng Nhật"` in p; `"speech_text"` in p;
          `"should_speak"` in p; `"Return JSON only."` in p; một từ khoá trung thực (vd `"grounding"`
          và `"không"` cùng xuất hiện — cụ thể assert `"grounding"` in p và `"capability"` in p);
          cụm vào-vai (vd `"ERIS"` in p và `"người thật"` in p).
        * assert KHÔNG CHỨA (regression gu, các chuỗi đã cố ý bỏ): `"HARD DISPLAY LANGUAGE LOCK"` not in p;
          `"không reasoning"` not in p; `"stage direction"` not in p; `"public writer cho một lượt chat"`
          not in p; `"one concise"` not in p.lower(); `"ấm kín"` not in p.
        * Chạy luôn 2 test cũ để chắc không vỡ.
      Verify (chạy, đọc stdout — BỎ QUA exit code -1 của PowerShell):
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" ^
        src/tests/test_eloquence_public_prompt.py ^
        src/tests/test_v38_infj_voice_contract.py ^
        src/tests/test_v39_affective_voice_state.py -q
      ```
      (chạy từ cwd = worktree root). Kỳ vọng: tất cả PASS. Nếu addopts gây nhiễu đã có `-o addopts=""`.

- [ ] 2. Bật thinking cho writer public: đổi default `thinking_mode` từ `"disabled"` → `"enabled"`.
      Files: `src/runtime/conversation/runtime_writer.py` dòng 337.
      Đổi: `"thinking_mode": runtime_context.get("thinking_mode", "disabled"),`
      → `"thinking_mode": runtime_context.get("thinking_mode", "enabled"),`
      KHÔNG đổi `reasoning_effort` (dòng 336, gateway bỏ qua). Cập nhật comment dòng 334-335 nếu cần
      cho khớp (giữ ý: writer vẫn 1 move đã khóa, nhưng cho phép pass suy nghĩ để câu mượt hơn).
      Lưu ý verification: khi thinking bật, provider ép `max_tokens>=2048` và bỏ temperature sampling.
      Deadline writer vẫn 24s (`_public_writer_deadline_seconds`) — GHI NHẬN trong report rằng 24s còn
      đủ cho một pass thinking ngắn của writer (chỉ wording 1 move, không reasoning dài).
      Verify:
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" ^
        src/tests/test_public_turn_runtime.py src/tests/test_public_writer_recovery_v6.py -q
      ```
      Kỳ vọng: PASS (hoặc giữ nguyên trạng thái base — xem bước Regression). Vì default là build-time
      kwargs khó assert trực tiếp, bổ sung kiểm nhanh bằng lệnh một dòng (ghi file rồi đọc):
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -c "import ast,io; s=open('src/runtime/conversation/runtime_writer.py',encoding='utf-8').read(); assert 'runtime_context.get(\"thinking_mode\", \"enabled\")' in s; print('OK thinking default enabled')"
      ```
      Kỳ vọng stdout: `OK thinking default enabled`.

- [ ] 3. Hạ tỉ lệ đuôi `ですね`: đổi CẢ HAI literal `0.55` trong `_signature_ending_policy` về `0.25`.
      Files: `src/runtime/speech_persona_polish.py`, hàm `_signature_ending_policy` (dòng ~245-283).
      Đổi:
      - `rate = _runtime_float("signature_ending_rate", 0.55)` → `... 0.25)`
      - `rate = round(_clamp01(rate, 0.55), 3)` → `rate = round(_clamp01(rate, 0.25), 3)`
      GIỮ NGUYÊN mode-gating: `technical/boundary` disable; `soft` `+0.08` (min 0.58); `dry` cap 0.24;
      fragment `<8` cap 0.12. KHÔNG đổi hành vi khác, KHÔNG đổi `_runtime_float`/`_clamp01`.
      Verify — thêm test vào `src/tests/test_eloquence_public_prompt.py` (hoặc file mới
      `src/tests/test_eloquence_signature_rate.py`), bắt chước pattern monkeypatch của
      `test_architecture_c_runtime_regressions.py` (dùng `runtime_float` trả default):
      * monkeypatch `runtime.runtime_settings_store.runtime_float` để trả default khi hỏi
        `signature_ending_rate` (tức đi theo literal mới), hoặc đơn giản gọi `_signature_ending_policy`
        với mode `"neutral"` và câu declarative dài ≥8, rồi assert `rate` trả về == 0.25
        (±0.001, vì có `round(_,3)`), KHÔNG phải 0.55.
      * Thêm 1 case `mode="dry"` vẫn ≤0.24, `mode="technical"` trả `(ending, False, 0.0)` — chứng minh
        gating không đổi.
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" ^
        src/tests/test_eloquence_signature_rate.py ^
        src/tests/test_architecture_c_runtime_regressions.py -q
      ```
      Kỳ vọng: test mới PASS; test cũ speech_persona (dòng 687-862) giữ trạng thái base.

- [ ] 4. Tắt drop_if_busy mặc định cho `surface`: bỏ `"surface"` khỏi set droppable mặc định.
      Files: `src/llm/deepseek_workers.py` dòng 420.
      Đổi: `self.worker_role in {"inner", "seed", "surface"},` → `self.worker_role in {"inner", "seed"},`
      Giữ env override `ERIS_DS_SURFACE_DROP_IF_BUSY` vẫn hoạt động (first arg của `_env_flag` không đổi).
      GHI NHẬN rủi ro trong report: dưới tải nặng lượt user có thể chờ thêm vài giây (tối đa
      `_actor_acquire_timeout`, default 2s, luôn ≤ request timeout ≤ deadline 24s) thay vì rơi fallback.
      Verify:
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -c "import os; [os.environ.pop(k,None) for k in list(os.environ) if k.startswith('ERIS_DS_')]; from llm.deepseek_workers import JsonlWorkerClient as W; import inspect; src=inspect.getsource(W.__init__); assert '{\"inner\", \"seed\"}' in src and 'surface' not in src.split('_drop_if_busy')[1].split(')')[0]; print('OK surface not droppable by default')" 2>&1
      ```
      Nếu lệnh inspect khó dựng client thật, thay bằng kiểm nguồn tĩnh:
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -c "s=open('src/llm/deepseek_workers.py',encoding='utf-8').read(); i=s.index('self._drop_if_busy'); seg=s[i:i+200]; assert 'surface' not in seg and '{\"inner\", \"seed\"}' in seg; print('OK')"
      ```
      Kỳ vọng stdout: `OK`. Cộng chạy regression nhẹ nếu có test deepseek_workers:
      ```
      c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" src/tests -k "deepseek_worker or drop_if_busy or worker" -q
      ```

---

## Regression tổng (bắt buộc sau cả 4 việc, báo số pass/fail THẬT từ stdout)

Chạy toàn bộ các nhóm liên quan. Ghi output ra file rồi đọc để tránh nhiễu terminal:
```
c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" ^
  src/tests/conversation ^
  src/tests/test_v38_infj_voice_contract.py ^
  src/tests/test_v39_affective_voice_state.py ^
  src/tests/test_architecture_c_runtime_regressions.py ^
  src/tests/test_public_turn_runtime.py ^
  src/tests/test_public_writer_recovery_v6.py ^
  src/tests/test_public_turn_trace_v97.py ^
  src/tests/test_eloquence_public_prompt.py ^
  src/tests/test_eloquence_signature_rate.py ^
  -q > c:\Users\Gtvkun\Documents\GitHub\eris\.agents\tasks\eloquence-impl\pytest_regression.txt 2>&1
```
Rồi đọc file đó. (Nếu `src/tests/conversation` không tồn tại dạng thư mục, thay bằng
`src/tests -k conversation`.) Chạy từ cwd = worktree root.

### Caveat test fail PRE-EXISTING
Nếu có test fail KHÔNG liên quan 4 việc (vd `test_root_session_bootstrap` preflight cần host/env),
PHẢI chứng minh nó fail CẢ trên base HEAD `cb4e51dc` trước khi quy cho thay đổi này:
```
git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence stash
c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe -m pytest -o addopts="" <test_fail_đó> -q
git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence stash pop
```
Nêu rõ trong report: test nào fail, fail cả trên base (pre-existing) hay do thay đổi (phải sửa).

## Commit (mỗi việc một commit riêng, message rõ, KHÔNG 'qq')

Dùng `git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eloquence`, stage ĐÚNG file từng việc:
1. `feat(voice): rewrite public writer prompt to human, INFJ-first naturalness`
   — add `src/runtime/ai_orchestrated/model_router.py`, `src/tests/test_eloquence_public_prompt.py`.
   (new_prompt.txt nằm trong `.agents/` NGOÀI worktree — không commit.)
2. `feat(writer): enable thinking by default for public surface writer`
   — add `src/runtime/conversation/runtime_writer.py`.
3. `feat(tts): lower ですね signature ending default rate 0.55 -> 0.25`
   — add `src/runtime/speech_persona_polish.py`, test signature rate.
4. `fix(workers): drop surface from default drop_if_busy set so user turn waits`
   — add `src/llm/deepseek_workers.py`.
KHÔNG push.

## Gaps / giả định
- Không chạy app end-to-end; chất lượng giọng văn mới do user duyệt qua `new_prompt.txt` (lý do bắt
  buộc dán nguyên văn). Plan chỉ bảo đảm prompt vẫn là `str` hợp lệ, giữ hằng/field bắt buộc, và
  thỏa các regression assertion đã biết.
- Deadline 24s cho writer thinking: dựa trên clamp code; nếu thực tế time out dưới tải, cân nhắc
  env `ERIS_PUBLIC_WRITER_DEADLINE_SEC` (không đổi code) — ghi nhận, không làm trong gói này.
