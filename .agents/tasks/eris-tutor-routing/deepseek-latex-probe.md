# DeepSeek Web probe: LaTeX/markdown trình bày toán + đường render vào Rich Chat

Ngày điều tra: 2026-11-02. Chế độ: **READ-ONLY + PING THẬT** (gọi endpoint bằng
credential user; KHÔNG sửa source/config, KHÔNG build, KHÔNG bật/tắt gateway,
KHÔNG khởi động app Eris).

Phạm vi: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev); config
runtime `config/secrets.json` + `.env`; raw trace live `C:\eris_debug\deepseek_raw\`;
ping thật tới gateway `http://127.0.0.1:5103/v1`.

Phân tầng: **[CODE]** đọc source (file:dòng); **[PING]** kết quả gọi endpoint thật;
**[LIVE]** raw trace phiên thật; **[SUY LUẬN]** suy từ bằng chứng.

Credential đã CHE: chỉ lưu tên biến + SHA-256[:8]. KHÔNG in giá trị key.

---

## Tóm tắt câu trả lời (đọc trước)

1. **Đường gọi thật:** Eris gọi DeepSeek Web qua một **gateway OpenAI-compatible đang
   CHẠY** tại `http://127.0.0.1:5103/v1` (whale2api chạy bằng **Docker Compose**, KHÔNG
   phải whale2api.exe). `[PING]` xác nhận gateway sống: `GET /v1/models` → 200, trả
   `deepseek-flash`. Auth = `Authorization: Bearer <ERIS_DS_COMPANION_API_KEY>`
   (fingerprint `4bb78ee5`). Payload là OpenAI chat-completions +
   `thinking:{type:...}` do client Eris chèn. **Đính chính giả định phiên trước**
   ("gateway không chạy, brain đi direct DeepSeek Web không qua gateway"): đúng là
   whale2api.exe không tồn tại, NHƯNG gateway vẫn phục vụ qua Docker trên :5103 và
   mọi worker DeepSeek của Eris trỏ vào đó.

2. **DeepSeek CÓ trả LaTeX/markdown — bằng chứng ping thật:**
   - Prompt toán mặc định ("Dạy tôi phân số… trình bày từng bước") → `[PING]` trả
     **Markdown giàu**: heading `#`/`##`, `**bold**`, **bảng Markdown** `|...|`,
     đường kẻ `---`, emoji, các bước xếp dọc. KHÔNG có LaTeX (`\frac`/`$`/`\[` đều
     False). 3.9s, `finish=stop`, 528 completion tokens.
   - Prompt yêu cầu rõ LaTeX → `[PING]` trả **LaTeX chuẩn**: `\(\frac{3}{4}\)` inline
     và `\[ \frac{...}{...} \]` block — ĐÚNG delimiter mà MathJax của Rich Chat đã
     render. (`\frac`=True, `\[`=True.)
   → Kết luận: brain thật **thừa sức** trình bày đẹp như GPT; mặc định nó dùng Markdown,
   và sẽ dùng LaTeX khi được yêu cầu/bối cảnh gợi.

3. **Eris GIỮ hay LÀM PHẲNG?** Markdown/LaTeX của DeepSeek **không bao giờ tới bubble
   như-nguyên-bản**, nhưng KHÔNG phải vì một sanitizer làm phẳng. Lý do kiến trúc:
   lane brain (`worker_role=executive`, `cognitive_lane=root_conversation`) trả **một
   move JSON** (Root chọn `say` = ý cần nói ngắn), KHÔNG trả thẳng câu trả lời Markdown
   dài. `[LIVE]` raw trace phiên 2026-11-01 (pid24164): 86 record, **0** hit
   `\frac/$$/\[/heading/bảng`. Bubble sau đó là lời persona do writer realize từ `say`,
   không phải markdown thô của model. **Không tìm thấy bước strip markdown** trong
   `public_output_runtime.py` (grep `strip/sanitize/flatten/plain_text` = 0 match) —
   nên nếu text chứa markdown/LaTeX thì nó sẽ tới bubble nguyên vẹn; vấn đề là text
   đó hiện KHÔNG chứa markdown/LaTeX.

4. **CÓ đường render THẲNG vào bubble (không cần presentation_blocks).** `[CODE]` Bubble
   Rich Chat (`chat.js:407` `content.innerHTML = ErisRender.render(displayedText)`) chạy
   text lời thoại qua một **renderer markdown+math đầy đủ**, rồi `syncMath()` gọi
   `MathJax.typesetPromise` (`chat.js:509, 303-304`). `ErisRender.render` nhận: heading,
   list, **bảng**, fenced code (Prism), **math block `$$`/`\[`**, **math inline
   `\(...\)`/`$...$`** → `math-block`/`math-inline` span cho MathJax
   (`chat.js:48-70, 186-205`). → **Bất kỳ LaTeX/markdown nào nằm trong text lời thoại
   đều render đẹp NGAY TRONG bong bóng chat**, không cần artifact card, không cần
   `presentation_blocks`.

5. **Đường rẻ nhất về token/latency:** **(b) cho markdown/LaTeX chạy thẳng vào bubble
   render MathJax** — rẻ hơn hẳn (a) dạy `presentation_blocks`. (a) tốn token prompt
   mỗi lượt (dạy cú pháp block + Root phải phát JSON block) đúng như lo của user; (b)
   **0 token thêm mỗi lượt** vì renderer đã sống sẵn, chỉ cần text lời thoại được phép
   mang markdown/LaTeX. Điểm sửa: cho phép/khuyến khích lane **nói** (say/writer) giữ
   markdown/LaTeX cho nội dung toán, thay vì ép thành prose phẳng.

6. **whale2api CÓ cần cho trình bày đẹp không?** KHÔNG. Gateway chỉ là **proxy/account
   pool** để gọi DeepSeek Web. Trình bày đẹp đến từ (i) model trả markdown/LaTeX +
   (ii) renderer bubble MathJax — cả hai độc lập với việc gateway là .exe hay Docker.
   Bật/tắt gateway không thêm/bớt khả năng trình bày.

**Đường rẻ nhất, một câu:** text lời thoại của Eris được phép mang markdown/LaTeX (bias
prompt ở lane nói, hoặc bỏ ép-prose), vì bubble + MathJax **đã** render sẵn — đây là thay
đổi **S**, không tốn token mỗi lượt, không đụng renderer/gateway.

---

## Bằng chứng

### Q1. Đường gọi DeepSeek Web thật

**Config [CODE/runtime]:**
- `.env`: `ERIS_REMOTE_PROVIDER=deepseek_web`, `ERIS_REMOTE_BASE_URL=http://127.0.0.1:5103/v1`,
  `ERIS_REMOTE_MODEL=deepseek-flash`, `ERIS_DS2API_ENABLED=1`, `ERIS_DS2API_PORTS=5103`,
  `ERIS_DS2API_BASE_URL=http://127.0.0.1:5103/v1`. Mọi
  `ERIS_DS_<ROLE>_BASE_URL` đều = `http://127.0.0.1:5103/v1`.
  `.env` comment xác nhận: whale2api chạy bằng **Docker compose** ở :5103, Eris KHÔNG
  spawn whale2api.exe (chỉ log cảnh báo rồi bỏ qua).
- `config/secrets.json`: `providers.deepseek.default/remote_main.base_url=http://127.0.0.1:5103/v1`,
  `model=deepseek-flash`; `api_keys.ERIS_DS_COMPANION_API_KEY` (và các role) = cùng một
  gateway key (fingerprint `4bb78ee5`, len 35).

**Resolver call site [CODE]:**
- `src/llm/deepseek_workers.py:122-190` `load_worker_spec(role)` dựng
  `DeepSeekWorkerSpec(api_key, base_url, model)`; base_url lấy từ
  `ERIS_DS_<ROLE>_BASE_URL` → `ERIS_DS2API_BASE_URL`/`ERIS_DS_BASE_URL`. Key: role key →
  shared `ERIS_DS2API_API_KEY`. Comment (dòng 405-413): worker **không phải model local
  4B**, là DeepSeek Web qua DS2API/Whale2API; `inference_backend="ds2api_deepseek_web"`.
- `src/llm/process_manager.py:60-157` provider `deepseek_web` → build companion worker
  (DS2API) làm main brain; nếu không có official key thì **không** nối fallback
  (dòng 138-144 "official fallback chua cau hinh"). Primary base_url/model lấy từ
  companion spec (:5103 / deepseek-flash).
- `src/llm/client.py:790-873` payload: `is_ds2api` = base_url không phải
  `api.deepseek.com` và chứa `6011|localhost|127.0.0.1` → đúng với :5103. Khi DS2API,
  client **ép** `thinking.mode` (localhost-force = "enabled"), rồi executive/surface có
  thể override về "disabled" (`ERIS_EXECUTIVE_THINKING_DISABLED=1`,
  `ERIS_SURFACE_THINKING_DISABLED=1` trong `.env`). Payload = OpenAI-compatible
  `{model, messages, thinking:{type}, max_tokens, temperature|reasoning_effort}`.
- Fallback khi proxy lỗi: `client.py:1257-1262` log "local DeepSeek Web proxy
  (Whale2API/DS2API) failed … falling back to Official API" — official chỉ là lưới dự
  phòng, không phải đường chính.

**Trạng thái process [runtime]:** `Get-NetTCPConnection` cho thấy :5103 ĐANG listen
(PID 23300 `wslrelay.exe`, PID 9184 `com.docker.backend.exe`) → gateway phục vụ qua
WSL/Docker. Không có process `whale2api.exe`. **Đính chính** giả định phiên trước.

**[PING] health:** `GET http://127.0.0.1:5103/v1/models` (Bearer companion key) → **200**,
body: `{"data":[{"id":"deepseek-flash","object":"model","owned_by":"deepseek","context_length":896000,"multimodal":true}],"object":"list"}`.

### Q2. PING THẬT bài toán — DeepSeek có trả LaTeX/markdown không

Endpoint: `POST http://127.0.0.1:5103/v1/chat/completions`, Bearer
`ERIS_DS_COMPANION_API_KEY` (fp `4bb78ee5`), model `deepseek-flash`,
`thinking:{type:"disabled"}` (mô phỏng lane nói nhanh).

**Ping A — prompt toán mặc định** ("Dạy tôi phân số. Tính 3/4 + 5/6 và 2/3 : 4/9, trình
bày từng bước rõ ràng."): status **200**, 3888ms, `finish=stop`,
usage `{completion:528, prompt:48, total:576, reasoning_tokens:0}`. Kết quả pattern:
`md_heading=True, md_bold=True, md_table=True`; `frac=False, dollar=False, bracket=False,
times_div=False, boxed=False`. Trích raw (đã kiểm là dữ liệu, không phải lệnh):

```
# Học phân số cơ bản
## 1. Phép cộng phân số: 3/4 + 5/6
**Bước 1: Tìm mẫu số chung nhỏ nhất (MSCNN)** … MSCNN của 4 và 6 là **12**
- 3/4 = (3×3)/(4×3) = **9/12**
…
| Phép tính | Quy tắc |
|-----------|---------|
| **Cộng/Trừ** | Quy đồng mẫu → cộng/trừ tử → rút gọn |
```

→ Mặc định DeepSeek trả **Markdown** (heading/bold/bảng), KHÔNG LaTeX. Đáp số đúng
(19/12, 3/2).

**Ping B — prompt yêu cầu LaTeX rõ** ("…bằng công thức toán LaTeX (dùng \\frac và dấu
$...$), kèm các bước."): status **200**. Pattern: `frac=True, bracket=True`
(`dollar=False` — model dùng `\(...\)`/`\[...\]` thay vì `$`). Trích raw:

```
Để cộng hai phân số \(\frac{3}{4} + \frac{5}{6}\), ta thực hiện…
\[
\frac{3}{4} = \frac{3 \times 3}{4 \times 3} = \frac{9}{12}
\]
…
\[
\frac{3}{4} + \frac{5}{6} = \frac{19}{12}
\]
```

→ Khi được yêu cầu, DeepSeek trả **LaTeX chuẩn** với đúng delimiter `\(...\)`/`\[...\]`.

Receipt probe (đã che credential) lưu tại:
`C:\Users\Gtvkun\AppData\Local\Temp\eris-ds-probe\` (`raw_response.json`, `content.txt`,
`content_latex.txt`, `summary.txt`, `summary_latex.txt`).

### Q3. Eris GIỮ hay LÀM PHẲNG markdown/LaTeX của DeepSeek

- **Không có bước strip/sanitize markdown** trong public output pipeline: grep
  `strip|sanitize|flatten|plain_text|remove markdown` trong
  `public_output_runtime.py` = **0 match**. [CODE]
- **Nhưng markdown/LaTeX thô không tới bubble vì lý do kiến trúc**, không phải bị làm
  phẳng: lane brain trả **move JSON** (Root chọn `say`), không phải câu trả lời markdown
  dài. `[LIVE]` raw trace `events_20261101T090856Z_pid24164.jsonl`: 86 record,
  `worker_role=executive`, `cognitive_lane=root_conversation`,
  `router_reason=eris_root_conversation_step_v12`, `model=deepseek-flash`; đếm
  `\frac/$$/\[/heading/bảng` = **0**. Response là JSON move (`response_chars≈565`), không
  phải markdown trình bày.
- Bubble cuối = lời persona do writer realize từ `say` (khớp
  `math-presentation-feasibility.md`: toán bị "đọc bằng lời" trong `say`). Vì vậy
  text tới bubble là prose thuần, renderer không có markdown/LaTeX để vẽ.

→ **Kết luận Q3:** Eris KHÔNG làm phẳng bằng sanitizer; nó đơn giản là **chưa bao giờ
đặt markdown/LaTeX vào text lời thoại**. Nếu text có, nó sẽ sống tới bubble (không bị
strip) và render được (Q4).

### Q4. Có đường render THẲNG vào bubble (không qua presentation_blocks) không — CÓ

**Bubble render markdown + MathJax đầy đủ. [CODE] `src/body/richchat/chat.js`:**
- Dòng 407: `content.innerHTML = ErisRender.render(displayedText)` — text lời thoại của
  MỖI message assistant đi qua `ErisRender.render`, KHÔNG phải `textContent` thuần.
- `render(text)` (block-level, dòng ~186+): nhận fenced code (Prism + chart/plot),
  **math block** `$$...$$` / `\[...\]` → `<div class="math-block">\[…\]</div>`,
  **heading** `#..######`, list, blockquote, **bảng** (`isTableSep`/`tableCells`),
  hr. [CODE chat.js:186-260]
- `inline/inlineText` (dòng 36-96): bảo vệ code, phát hiện **math inline**
  `\(...\)` / `$...$` / `$$...$$` / `\[...\]` → `math-inline`/`math-block` span; cộng
  bold/italic/strike/link. Chuẩn hóa delimiter double-escaped. [CODE]
- `syncMath()` = `MathJax.typesetPromise([root])` (dòng 303-304); `renderMessages`
  gọi `syncMath()` sau khi dựng bubble (dòng 509 `if(!pendingArtifacts.length)syncMath()`),
  và chạy lại sau khi MathJax startup xong (dòng 572). [CODE]
- Artifact card dùng CÙNG delimiter: `artifacts.js:19,38-39` `math-block \[latex\]`,
  `hasMath` (dòng 82) phát hiện `\[`/`\(`. → bubble và card đồng bộ engine. [CODE]

→ **Kết luận Q4:** đường render thẳng vào bong bóng chat **TỒN TẠI và hoạt động**. LaTeX
`\(\frac{3}{4}\)` / `\[...\]` của Ping B, hoặc Markdown (heading/bảng/bold) của Ping A,
nếu nằm trong text lời thoại sẽ render NGAY trong bubble — phân số xếp tử/mẫu, bảng,
đậm — đúng kiểu GPT, mà KHÔNG cần `presentation_blocks` hay artifact card.

### Q5. Đường rẻ nhất về token/latency để trình bày toán đẹp

| Đường | Token mỗi lượt | Latency | Độ lớn sửa | Điểm sửa |
|---|---|---|---|---|
| (a) Dạy Root dùng `presentation_blocks` (math.content={latex}) | **Tốn thêm** (dạy cú pháp block trong prompt + Root phát JSON block mỗi lượt toán) | +nhẹ (block publish sau commit) | S–M | `root_prompt_contract.py` + có thể soft-force (theo `math-presentation-feasibility.md`) |
| **(b) Markdown/LaTeX chạy thẳng vào bubble (render MathJax)** | **0 thêm** (renderer đã sống, không cần prompt cú pháp) | **Thấp nhất** | **S** | Cho lane nói giữ markdown/LaTeX; bỏ ép-prose cho nội dung toán |
| (c) Khác (ví dụ second-pass format) | Tốn (thêm 1 call LLM) | Cao | M–L | không khuyến nghị |

→ **Rẻ nhất = (b).** Lo của user (nhồi chỉ dẫn tool mỗi lượt = tốn token = chậm thêm)
đúng với (a). (b) tránh hẳn: không cần dạy cú pháp block, không cần lượt phát JSON block;
chỉ cần text lời thoại được phép mang `\(...\)`/`\[...\]` hoặc markdown. Renderer MathJax
+ markdown subset **đã có sẵn** trong bubble (Q4).

**Điểm sửa chính xác cho (b) [SUY LUẬN từ CODE]:** text đi vào bubble là `say` realize
qua writer. Hiện writer/Root ép prose thuần cho nội dung nói. Để (b) hoạt động, cần **cho
phép** nội dung toán giữ markdown/LaTeX trong text lời thoại — ví dụ bias ở
`root_prompt_contract.py` / lane nói: "khi trình bày công thức/bước toán, viết công thức
dạng LaTeX `\(...\)`/`\[...\]` hoặc bảng markdown ngay trong lời, vì giao diện tự vẽ".
Vì bubble đã render, KHÔNG cần đụng renderer, KHÔNG cần `presentation_blocks`.
**Lưu ý ràng buộc TTS:** text lời thoại cũng là nguồn cho localizer/TTS (khác với
`presentation_blocks` vốn tách khỏi TTS — `runtime_writer.py:388-389`). Nếu đưa LaTeX
vào `say`, phải chắc localizer/TTS không đọc `\frac{...}` thành chữ. Đây là điểm cần
kiểm trước khi chốt (b); nếu TTS đọc latex thô thì hoặc (b) cần tách kênh hiển thị khỏi
kênh đọc, hoặc quay lại (a). (Chưa kiểm localizer với input LaTeX trong probe này.)

### Q6. whale2api có cần cho trình bày đẹp không — KHÔNG

- Gateway = proxy/account-pool để truy cập DeepSeek Web; `deepseek_workers.py` comment
  (405-413) và `process_manager.py` đều coi nó là transport, không phải lớp định dạng.
- `[PING]` cho thấy markdown/LaTeX đến từ **chính model** (gateway chỉ chuyển tiếp).
  `[CODE]` cho thấy trình bày đẹp đến từ **renderer bubble + MathJax** (client Rich Chat).
  Cả hai độc lập với .exe vs Docker.
- Bật/tắt gateway không thêm/bớt năng lực trình bày. Mục 9 runtime-lessons: gateway đã
  bỏ chèn context .txt + "Output integrity note" — không liên quan định dạng toán.

→ Gateway chỉ là proxy pool; vô can với trình bày đẹp.

---

## Kết luận & khuyến nghị

1. **Đường gọi:** DeepSeek Web qua gateway OpenAI-compatible ĐANG CHẠY ở
   `http://127.0.0.1:5103/v1` (Docker, không .exe), model `deepseek-flash`, auth Bearer
   `ERIS_DS_COMPANION_API_KEY` (fp `4bb78ee5`), payload OpenAI + `thinking`. `[PING]` 200.
2. **DeepSeek trả LaTeX/markdown:** CÓ — `[PING]` xác nhận Markdown mặc định
   (heading/bold/bảng) và LaTeX `\(\frac\)`/`\[...\]` khi được yêu cầu.
3. **Giữ hay làm phẳng:** KHÔNG có sanitizer làm phẳng; markdown/LaTeX thô đơn giản
   chưa bao giờ nằm trong text lời thoại vì Root trả move JSON (`say` ngắn). Raw trace
   live = 0 hit markdown/LaTeX.
4. **Đường render thẳng vào bubble:** TỒN TẠI và hoạt động — `chat.js:407` + `render()`
   (markdown subset) + `syncMath()`/MathJax (`chat.js:303-304,509,572`). Bất kỳ
   LaTeX/markdown nào trong text lời thoại render ngay trong bong bóng, không cần
   `presentation_blocks`.
5. **Rẻ nhất:** phương án (b) — cho text lời thoại mang markdown/LaTeX, 0 token thêm
   mỗi lượt, độ lớn **S**. Điểm sửa: bias prompt ở lane nói/`root_prompt_contract.py`
   cho phép công thức LaTeX/bảng markdown trong lời; KHÔNG đụng renderer/gateway.
   **Chốt (b) cần kiểm trước:** localizer/TTS không được đọc LaTeX thô thành chữ
   (vì `say` là nguồn TTS). Nếu rủi ro TTS, cân nhắc (a) `presentation_blocks` (đã tách
   khỏi TTS) như `math-presentation-feasibility.md` khuyến nghị.
6. **whale2api:** chỉ là proxy pool; vô can với trình bày đẹp.

**So với báo cáo trước (`math-presentation-feasibility.md`):** không mâu thuẫn, bổ sung.
Báo cáo đó chốt kênh `presentation_blocks`/artifact-card render LaTeX end-to-end (đúng).
Báo cáo này thêm: **bubble chat cũng render markdown+LaTeX trực tiếp** (chat.js:407,
render(), syncMath) — nên có đường (b) rẻ hơn (a) về token/latency, miễn giải quyết ràng
buộc TTS. Hai báo cáo cùng điểm sửa gốc (`root_prompt_contract.py`, loại "nuôi-cá-tính",
không phải sửa renderer).

---

## Phân tầng bằng chứng
- **[CODE]** `.env` (ERIS_REMOTE_*/ERIS_DS2API_*/ERIS_DS_*_BASE_URL=:5103; comment Docker);
  `config/secrets.json` (providers.deepseek base_url :5103, model deepseek-flash, key env);
  `src/llm/deepseek_workers.py:122-190,405-413`; `src/llm/process_manager.py:60-157`;
  `src/llm/client.py:790-873,1257-1262`; `src/body/richchat/chat.js:303-304,407,509,572`
  (bubble render+MathJax), `:36-96,186-260` (inline/block markdown+math);
  `src/body/richchat/artifacts.js:19,38-39,82` (card math delimiter). Grep strip/sanitize
  trong `public_output_runtime.py` = 0.
- **[PING]** gateway :5103: `/v1/models` 200 (deepseek-flash); `/v1/chat/completions`
  Ping A 200 markdown (frac=False), Ping B 200 LaTeX (frac=True, bracket=True). Receipt
  che credential: `C:\Users\Gtvkun\AppData\Local\Temp\eris-ds-probe\`.
- **[LIVE]** `C:\eris_debug\deepseek_raw\events_20261101T090856Z_pid24164.jsonl`:
  worker_role=executive, root_conversation, deepseek-flash; 0 hit markdown/LaTeX.
- **[runtime]** :5103 listen qua PID 23300 wslrelay + 9184 com.docker.backend; không có
  whale2api.exe.
- **[SUY LUẬN]** điểm sửa (b) và ràng buộc TTS khi đưa LaTeX vào `say`; chưa ping
  localizer với input LaTeX.
