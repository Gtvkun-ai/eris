# Khả thi: Eris TRÌNH BÀY TOÁN đẹp như GPT (render LaTeX) thay vì đọc toán bằng lời

Ngày điều tra: 2026-11-02. Chế độ: **ĐỌC-ONLY** (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev); log live
`C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261101_160853.txt` (phiên 2026-11-01
16:09–16:22, chính là phiên "dạy phân số" user dán); và bốn báo cáo trước trong
`.agents/tasks/eris-tutor-routing/` + `docs/knowledge/2026-10-14-eris-runtime-lessons.md`.

Mỗi khẳng định có file:dòng. Phân tầng: **[CODE]** đọc source trực tiếp;
**[LIVE]** quan sát log phiên thật; **[SUY LUẬN]** suy từ code, chưa live.

---

## Tóm tắt câu trả lời (đọc trước)

**Đây là vấn đề PROMPT (model không chọn `presentation_blocks`), KHÔNG phải vấn đề
RENDERER.** Giống hệt bẫy routing Tutor và bẫy cadence đã điều tra: **cơ chế sống đủ,
model không gọi.**

1. **Kênh `presentation_blocks` hoạt động END-TO-END.** [CODE] Root khai báo block trong
   move (`agent.py:46-56`) → validate fail-soft (`presentation_p2.py:26-73`
   `normalize_presentation_blocks`) → giữ qua writer, tách khỏi `writer_brief`
   (`runtime_writer.py:321-328, 388-389`) → publish **sau** khi bubble đã gửi thật
   (`public_output_runtime.py:736-748` gọi `publish_committed_presentation`) → sidecar
   bundle bất biến (`presentation_p2.py:107-171`) → served qua HTTP → renderer
   `artifacts.js` dựng `\[latex\]` → `chat.js` chạy `MathJax.typesetPromise` → browser
   gửi receipt `renderer.feedback.v1 status=rendered`. Không có mắt xích đứt.

2. **Renderer LaTeX CÓ SẴN và HOẠT ĐỘNG — KHÔNG phải chỉ khai báo schema.** [CODE]
   MathJax được bundle local (`src/body/richchat/vendor/mathjax.js`, 12k+ ký tự
   minified), nạp qua `RichChatPortal` (`UdpListener.RichChatPortal.cs:71-74` liệt kê
   `vendor/mathjax.js`). `artifacts.js` render `kind==='math'` thành
   `<div class="math-block">\[...\]</div>` (dòng ~40-42) và trả `hasMath=true`.
   `chat.js` có `mathReady()` + `syncMath()` + `MathJax.typesetPromise([root])` và CHỈ
   báo `rendered` sau khi thấy `mjx-container` thật, báo `E_RENDER` nếu có `mjx-merror`
   (chat.js ~303-349). Có cả **E2E Chromium thật** xác nhận renderer:
   `test_p3_browser_e2e.py:77` `test_browser_reports_success_only_after_mathjax_svg`
   ("Exercises the real bundled MathJax/JS", dòng 4-5). → Renderer đủ sức vẽ phân số
   xếp tử/mẫu, bảng, code (Prism), chart. **Vấn đề KHÔNG nằm ở renderer.**

3. **TẠI SAO Root không phát `presentation_blocks`: thuần là model không chọn + prompt
   dạy quá mờ.** [CODE]+[LIVE]
   - KHÔNG có gate nào chặn: nhánh finalize `agent.py:336` giữ nguyên block model gửi
     (`NextConversationMove.from_mapping(raw)`), không điều kiện. [CODE]
   - ROOT_SYSTEM_CORE (`root_prompt_contract.py:15-16`) chỉ có MỘT câu mờ:
     "document_source/presentation_blocks dành cho nội dung nhìn; say là ý cần nói".
     KHÔNG có câu nào dạy "khi giảng toán nhiều bước, ĐƯA công thức vào block math thay
     vì đọc bằng lời". [CODE]
   - Chỉ dẫn chi tiết (math.content={latex}, "chọn block khi giúp giải thích") nằm trong
     **tool_guide `rich_chat`** (`tool_guides.py:7-22`) mà Root CHỈ thấy nếu nó chủ động
     `read_tool_guide=rich_chat` — và `_system_prompt` tĩnh, bỏ qua registry (đã chốt
     `tutor-gating-feasibility.md §1`, agent.py:642-645). [CODE]
   - **[LIVE] Phiên 16:09–16:22:** mọi lượt đều `action=move` finalize thẳng; **0**
     `use_capability`, **0** `read_tool_guide`, **0** `tutor`, **0** `presentation`,
     **0** `document_source`. Lượt dạy phân số (user 16:11) → chỉ
     `[public-text] sent ... chars=244` (log dòng 128), một bubble chữ, KHÔNG sidecar.
     Root chưa bao giờ đọc guide rich_chat nên không có đất biết cú pháp block.

4. **Loại thay đổi: (a) NUÔI CÁ TÍNH/PROMPT — nhẹ (S).** Không cần đụng renderer (đã
   chạy), không cần đụng pipeline P2 (đã chạy). Chỉ cần dạy Root trong ROOT_SYSTEM_CORE
   rằng khi trình bày toán/bước/bảng thì ĐƯA phần cần-nhìn vào `presentation_blocks`
   (math.content={latex}) và giữ `say` là lời nói ngắn — y khuôn "cadence là cá tính".
   Đây là **bias prompt (yếu)** nhưng đúng chỗ. Phương án mạnh hơn (soft-forcing) để
   dành nếu live chứng minh prompt không đủ.

5. **Tôn trọng hợp đồng:** `presentation_blocks` là **sidecar kênh nhìn, KHÔNG vào TTS**
   — XÁC NHẬN ĐÚNG. [CODE] `public_output_artifact.py:59-62` ("Sidecar trong process,
   không serialize vào gói Bubble/TTS"); writer tách block khỏi `writer_brief`
   (`runtime_writer.py:388-389`) nên TTS/localizer không bao giờ đọc latex thành lời.
   `say` vẫn là một writer duy nhất (single_writer), không tạo người quyết định nội dung
   thứ hai. Khuyến nghị dưới để **Root tự chọn** block (như cadence), không ép cơ học.

---

## Bằng chứng

### Q1. `presentation_blocks` đi từ Root đến Rich Chat NHƯ THẾ NÀO (end-to-end)

**Toàn bộ chuỗi tồn tại và liền mạch. [CODE]**

1. **Schema trong move:** `agent.py:46-56` — `presentation_blocks` là mảng `maxItems=6`,
   mỗi phần tử `{kind ∈ {math,table,code,chart,document}, title?, content:object}`.
   Nằm trong `NEXT_MOVE_SCHEMA.oneOf[0]` (nhánh move) nên Root được phép phát ngay khi
   finalize. Test xác nhận schema có đúng field: `test_eris02_root_agency.py:206-207`.
2. **Parse vào contract:** `contracts.py:103` `_parse_presentation_blocks` →
   `normalize_presentation_blocks` (`contracts.py:25-27`); `NextConversationMove`
   giữ field `presentation_blocks` (`contracts.py:78`).
3. **Validate fail-soft:** `presentation_p2.py:26-73` — validate bằng CÙNG P0 contract
   như artifact tool thật (`build_artifact`), loại block sai/`chart` thiếu dữ liệu/
   `document` giả mạo ảnh, giới hạn 24KB/block. "invalid LLM data never leaks into a
   sidecar, TTS or history" (docstring dòng 28).
4. **Finalize giữ nguyên:** `agent.py:331-337` nhánh move trả
   `replace(NextConversationMove.from_mapping(raw), tool_artifact_bundles=...)` — block
   của model được bảo toàn, KHÔNG có gate.
5. **Qua writer, tách kênh:** `runtime_writer.py:321-328` nếu move có
   `presentation_blocks` thì đính vào `prepared` (public output artifact);
   `runtime_writer.py:388-389` xây `writer_brief` LOẠI BỎ `presentation_blocks` và
   `document_source` → writer không đọc latex thành thoại.
6. **Publish SAU khi gửi bubble thật:** `public_output_runtime.py:736-748` — chỉ khi
   `prepared.presentation_blocks or prepared.tool_artifact_bundles`, sau
   `transport.send_json(body_payload)` (dòng 727), gọi `publish_committed_presentation`
   (turn_id, delivery_id, blocks, tool_bundles). Fail-soft nếu lỗi (dòng 747-748).
7. **Dựng sidecar bất biến:** `presentation_p2.py:107-171` — build artifact
   `source='root_presentation'`, `metadata.turn_binding='bound'`, ghi qua
   `write_bundle_sidecar` (giao thức P0/P1 có sẵn). Tool bundles (math_workspace/
   tutor_activity) nối từ receipt thật, không nhận ID do model bịa (docstring 3-6).
8. **Renderer browser:** `artifacts.js render()` —
   `kind==='math' && content.latex` → `<div class="math-block">\[latex\]</div>`;
   `code`→Prism, `table`→`<table>`, `chart`→`ErisRender.chartSvg`, `document`→markdown.
   Trả `hasMath`. `chat.js` `addArtifacts` gắn theo `turn_id` (dòng ~411-412),
   `reportArtifacts` chạy MathJax rồi POST `api/feedback` (dòng ~322-368).

**math.content={latex} render bằng gì:** **MathJax** (không phải KaTeX).
`vendor/mathjax.js` bundle local; `artifacts.js` xuất cú pháp `\[...\]`; `chat.js`
`MathJax.typesetPromise`. [CODE]

→ **Kết luận Q1:** cơ chế render LaTeX **CÓ SẴN và liền mạch end-to-end**, không chỉ
khai báo schema. Publish đúng kiến trúc (sau commit bubble, Root sở hữu, không presenter
độc lập).

### Q2. TẠI SAO Root không phát `presentation_blocks` khi giảng toán

**Thuần là model không chọn + prompt dạy mờ. KHÔNG có gate chặn. [CODE]+[LIVE]**

- **Không gate:** finalize `agent.py:336` không kiểm tra/không bắt buộc gì về block;
  model muốn gửi thì gửi. [CODE]
- **Prompt system (luôn thấy) chỉ mờ:** `root_prompt_contract.py:15-16` — một câu duy
  nhất "document_source/presentation_blocks dành cho nội dung nhìn; say là ý cần nói,
  hai kênh không bắt buộc trùng văn bản". Không ví dụ, không dạy "giảng toán → đưa công
  thức vào block math". Menu công cụ (dòng 4-5) chỉ nói "rich_chat trình bày nội dung"
  một cụm ngắn. [CODE]
- **Chi tiết cú pháp nằm ở guide phải chủ động đọc:** `tool_guides.py` mục `rich_chat`
  (dòng 7-22) mới nói rõ "P2: Root có thể tự chọn presentation_blocks… math.content=
  {latex}… Chỉ chọn block khi giúp giải thích". Nhưng `_system_prompt` tĩnh bỏ qua
  registry (agent.py:642-645, theo tutor-gating §1) → Root chỉ thấy guide này nếu phát
  `read_tool_guide=rich_chat`. [CODE]
- **[LIVE] phiên 16:09–16:22:** đếm toàn log:
  `presentation=0, tutor=0, read_tool_guide=0, use_capability/capability_result=0`.
  Tất cả lượt `action=move` finalize thẳng ở step=1 (log dòng 118, 150, 199, 250, 319,
  371, 413, 463, 493). Lượt dạy phân số (user 16:11) → `root-agent step=1
  event_kind=user_turn action=` rồi finalize, `public-text ... chars=244` (dòng 128).
  Root KHÔNG đọc guide rich_chat → không có đất biết cú pháp block → mặc định đọc toán
  bằng lời trong `say`.

→ **Kết luận Q2:** **không có điều kiện/gate chặn.** Nguyên nhân = (i) prompt system mờ
(1 câu, không ví dụ, không dạy giảng-toán-thì-vẽ), (ii) chi tiết bị chôn trong guide
phải chủ động đọc mà Root không đọc. Đây là **lựa chọn của model trong khoảng tự do
prompt cho phép** — cùng bản chất với bẫy routing/cadence.

### Q3. Renderer CÓ render được math/bảng/khung kết quả như GPT không

**CÓ, đầy đủ. Vấn đề KHÔNG ở renderer. [CODE]**

- **Math (phân số xếp tử/mẫu):** MathJax render LaTeX chuẩn → `\frac{a}{b}` ra phân số
  thật, `=` thẳng hàng, như ảnh GPT user dán. `artifacts.js` math-block + `chat.js`
  `typesetPromise`. Có kiểm chứng DOM (`mjx-container`, báo lỗi nếu `mjx-merror`).
- **Khung kết quả (card):** `artifacts.js render()` bọc mỗi artifact trong
  `<section class="artifact-card"><header>✧ <title> <small>kind</small></header>
  <div class="artifact-body">…</div></section>` → đúng "khung" như GPT.
- **Bảng:** `tableHtml(columns, rows)` → `<table><thead>…<tbody>…`. **Code:** Prism
  highlight. **Chart:** `ErisRender.chartSvg` bar/line.
- **Hiển thị:** artifact gắn DƯỚI lượt chat theo `turn_id` (`chat.js:411-412
  addArtifacts(item, artifacts.filter(a=>a.turn_id===msg.turnId))`), cũng có gallery
  "Bàn làm việc". Đây là **panel dưới bubble**, không inline trong bong bóng thoại —
  nhưng vẫn là "vẽ toán ra hình" như GPT, chỉ khác vị trí (card riêng, không trộn chữ).
- **Engine không thiếu:** build payload bắt buộc có MathJax
  (`test_build_payload_layout.py:24` liệt kê `body/richchat/vendor/mathjax.js` trong
  manifest), `RichChatPortal.cs:71-74` phục vụ nó. E2E Chromium thật tồn tại
  (`test_p3_browser_e2e.py`).

→ **Kết luận Q3:** renderer ĐỦ sức như GPT (phân số, khung, bảng, step). "bước xuống
bước" sẽ là nhiều block math/document trong một move (maxItems=6) hoặc document_source
Markdown/LaTeX nhiều dòng. **Không cần dựng/sửa renderer.**

### Q4. Bằng chứng live: có dòng nào phát presentation_blocks khi giảng toán không

**KHÔNG. Xác nhận Root chưa dùng kênh này live. [LIVE]**

Log `eris_run_20261101_160853.txt` (phiên user dán, 16:09–16:22):
- Grep toàn file: `presentation` = 0, `presentation-p2` = 0, `document_source` = 0,
  `root_presentation` = 0, `tutor` = 0, `activity` = 0, `artifact_bundle_id` = 0,
  `use_capability`/`capability_result` = 0, `read_tool_guide` = 0.
- Lượt dạy phân số và mọi lượt sau: chỉ có `[root-agent] ... action=move` +
  `[public-text] sent ... reason=audio_start chars=<nn>` (244, 249, 374, 497, 138,
  255, 174, 208 …). Không có log `[presentation-p2]` (sẽ xuất hiện nếu block được
  publish hoặc degrade — `public_output_runtime.py:748`).

→ **Kết luận Q4:** Root hoàn toàn không phát `presentation_blocks` trong phiên dạy toán
live. Toán bị đọc bằng lời trong `say`. Khớp với Q2.

### Q5. Loại thay đổi: nuôi cá tính/prompt (a) hay sửa renderer (b) hay cả hai (c)

- **(a) Nuôi cá tính/prompt — ĐÚNG, và là phần CHÍNH. Độ lớn S.** Renderer + pipeline P2
  đã chạy (Q1, Q3); chỉ thiếu việc Root CHỌN block. Sửa bằng cách dạy Root trong
  ROOT_SYSTEM_CORE: khi trình bày công thức/bước toán/bảng, đưa phần cần-nhìn vào
  `presentation_blocks` (math.content={latex}) và để `say` là lời nói ngắn. Bias prompt,
  rủi ro thấp, không đụng cơ chế. [CODE]+[SUY LUẬN]
- **(b) Sửa renderer — KHÔNG CẦN.** Renderer LaTeX đã đủ (MathJax, card, table, chart,
  E2E). Không có bằng chứng renderer thiếu/hỏng. [CODE]
- **(c) Cả hai — KHÔNG.** Chỉ cần (a).

→ **Kết luận Q5:** đây là **nuôi-cá-tính/prompt (a)**, không phải sửa renderer. Giống hệt
cadence và routing: cơ chế sống, dạy model dùng.

### Q6. Tôn trọng ràng buộc

- **Sidecar không vào TTS:** XÁC NHẬN. `public_output_artifact.py:59-62`
  ("Sidecar trong process, không serialize vào gói Bubble/TTS");
  `runtime_writer.py:388-389` tách `presentation_blocks`/`document_source` khỏi
  `writer_brief`. TTS/localizer chỉ nhận `say`. [CODE]
- **single_writer:** giữ nguyên — block đi kèm MỘT move, writer realize một lần
  (`runtime_writer.py:321-328`). Publish là bước cơ học sau commit, không phải LLM thứ
  hai (`presentation_p2.py` docstring 3-6: "No planner, watcher, second LLM"). [CODE]
- **Không người quyết định nội dung thứ hai:** publish chỉ chạy khi Root ĐÃ chọn block
  (`public_output_runtime.py:737-739`); không presenter nào tự suy ra/ghi đè. [CODE]
- Khuyến nghị dưới để **Root tự chọn** block qua prompt (soft), không ép cơ học — đúng
  tinh thần cadence.

---

## Kết luận & khuyến nghị

### (1) `presentation_blocks` end-to-end hoạt động tới đâu
**Toàn trình, liền mạch.** Schema (`agent.py:46-56`) → validate (`presentation_p2.py:26-73`)
→ writer tách kênh (`runtime_writer.py:321-328,388-389`) → publish sau commit
(`public_output_runtime.py:736-748`) → sidecar (`presentation_p2.py:107-171`) → renderer
`artifacts.js` → MathJax `chat.js` → receipt. Không mắt xích đứt.

### (2) Renderer LaTeX có sẵn không
**CÓ, và hoạt động.** MathJax bundle local (`vendor/mathjax.js`,
`RichChatPortal.cs:71-74`), `artifacts.js` math-block, `chat.js` `typesetPromise` +
kiểm chứng DOM, E2E Chromium (`test_p3_browser_e2e.py:77`). Vẽ được phân số, khung, bảng,
chart, code. **Không phải điểm sửa.**

### (3) Tại sao Root không dùng (prompt hay gate)
**PROMPT, không gate.** Không có điều kiện chặn (`agent.py:336`). Prompt system chỉ có 1
câu mờ (`root_prompt_contract.py:15-16`); chi tiết cú pháp nằm trong guide phải chủ động
đọc (`tool_guides.py:7-22`) mà Root không đọc (live: `read_tool_guide=0`). Model mặc định
đọc toán bằng lời.

### (4) Điểm sửa chính xác + độ lớn
**Chính (S): `src/runtime/conversation/root_prompt_contract.py` ROOT_SYSTEM_CORE.** Thêm
một chỉ dẫn cá tính kiểu: "Khi trình bày công thức, phép tính nhiều bước, bảng hay biểu
đồ, Eris ĐƯA phần cần-nhìn vào presentation_blocks (ví dụ math.content={latex} cho phân
số/phương trình) để người học THẤY công thức xếp đúng, còn say chỉ nói ý bằng giọng mình —
không đọc rời rạc '3 phần 4 cộng 5 phần 6' thành chữ." Đặt cạnh câu hiện có về
document_source/presentation_blocks (dòng 15-16). Giữ "hai kênh không bắt buộc trùng văn
bản" và KHÔNG thêm quota/max_sentences. Đây là bias prompt, phụ thuộc model tuân — nhưng
đủ để kích cơ chế đã có. **~2-4 câu prose. Độ lớn S.**

**Tùy chọn mạnh hơn (M) — chỉ nếu live chứng minh prompt không đủ:** soft-forcing quanh
finalize `agent.py:336` — khi `say` chứa mẫu toán rõ (ví dụ nhiều `a/b`, dấu `=`, phân số
đọc-bằng-lời) VÀ move KHÔNG có `presentation_blocks` VÀ chưa ép lần nào, append directive
vào `tool_results` gợi ý Root đưa công thức vào block rồi `continue`; fail-soft finalize
nếu model vẫn không thêm. CÙNG khuôn soft-forcing mà `tutor-gating-feasibility.md §2a` và
`streaming-cadence-feasibility.md §(2) tùy chọn` mô tả. Rủi ro: phát hiện "đang nói toán"
dễ false-positive; chỉ làm sau khi prompt chứng minh không đủ qua live.

**KHÔNG cần đụng:** renderer (`artifacts.js`/`chat.js`/MathJax), pipeline P2
(`presentation_p2.py`, `public_output_runtime.py`), writer, TTS, single_writer.

### (5) Là nuôi-cá-tính hay sửa renderer
**Nuôi-cá-tính/prompt.** Renderer đã đủ như GPT; thiếu sót duy nhất là Root chưa được dạy
đủ rõ để CHỌN kênh nhìn khi giảng toán. Giống cadence (đã sửa ở commit trước) và routing.

### (6) Ràng buộc kiểm chứng (bắt buộc)
Mọi thay đổi xác minh bằng **phiên live thật** (DeepSeek + delivery + mở Rich Chat), không
chỉ test fixture — bản chất là *lựa chọn của model* (bài học runtime mục 2/7). Live cần
cho thấy khi user hỏi câu toán: log có `[presentation-p2]` publish (hoặc ít nhất
`presentation_blocks` trong move trace), bubble `say` ngắn, và Rich Chat gửi
`renderer.feedback.v1 status=rendered` cho artifact math (MathJax dựng `mjx-container`).
Hiện log chỉ có `[public-text] sent ... chars=` — nên theo dõi thêm dòng
`[presentation-p2]` và receipt renderer khi test. Nếu sau sửa prompt mà live vẫn 0 block,
leo lên tùy chọn soft-forcing (M).

---

## Phân tầng bằng chứng
- *Đọc source (file:dòng):* agent.py:46-56 (schema presentation_blocks), 331-337
  (finalize giữ block, không gate), 642-645 (system prompt tĩnh bỏ registry, theo
  tutor-gating §1); contracts.py:25-27,78,103 (parse/field); presentation_p2.py:26-73
  (normalize/validate fail-soft), 75-104 (verified_tool_bundles từ receipt thật),
  107-171 (publish_committed_presentation sau commit, bound sidecar);
  runtime_writer.py:321-328 (đính block vào prepared), 388-389 (tách khỏi writer_brief);
  public_output_runtime.py:727 (send_json bubble), 736-748 (publish sau send, fail-soft);
  public_output_artifact.py:59-62 (sidecar không vào Bubble/TTS);
  root_prompt_contract.py:4-5 (menu rich_chat 1 cụm), 15-16 (1 câu mờ về block);
  tool_guides.py:7-22 (guide rich_chat chi tiết math.content={latex}, phải read_tool_guide);
  artifacts.js (render math `\[latex\]`, card, table, code, chart, hasMath);
  chat.js:303-349 (mathReady/syncMath/typesetPromise + kiểm mjx-container/mjx-merror +
  reportArtifacts receipt), 411-412 (gắn artifact theo turn_id);
  UdpListener.RichChatPortal.cs:71-74 (phục vụ mathjax.js/prism);
  vendor/mathjax.js (bundle MathJax local).
- *Test xác nhận:* test_eris02_root_agency.py:206-207 (schema field);
  test_p2_root_presentation.py:45-53,61-63,145-147 (Root chọn block, normalize loại sai);
  test_public_text_audio_commit.py:314-343 (publish_committed_presentation gọi sau commit);
  test_p3_browser_e2e.py:77 (Chromium + MathJax SVG thật);
  test_build_payload_layout.py:24 (mathjax.js trong manifest build).
- *[LIVE]* eris_run_20261101_160853.txt (phiên user dán): mọi lượt action=move finalize
  step=1; đếm presentation=0, tutor=0, read_tool_guide=0, use_capability=0; lượt dạy phân
  số → public-text chars=244 (dòng 128), không sidecar, không [presentation-p2].
- *Lịch sử đã đối chiếu:* tutor-gating §1/§5 (wiring sidecar đủ, bức tường chữ là lựa chọn
  model), streaming-cadence §(kết luận) (cơ chế sống model không gọi), persona-pedagogy
  (cadence là cá tính ở ROOT_SYSTEM_CORE) — báo cáo này KHÔNG mâu thuẫn, chỉ bổ sung: kênh
  NHÌN (presentation_blocks/MathJax) cũng sống end-to-end và cũng chỉ thiếu việc Root chọn,
  điểm sửa cùng chỗ (root_prompt_contract.py) và cùng loại (nuôi-cá-tính).
- *[SUY LUẬN]:* hiệu quả bias prompt phụ thuộc model tuân; cần live. Soft-forcing (M) là
  dự phòng đúng khuôn các báo cáo trước, không khuyến nghị làm trước.
