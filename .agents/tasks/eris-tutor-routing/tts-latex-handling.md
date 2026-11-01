# Localizer/TTS xử lý LaTeX trong `say` — đường (b) có khả thi không?

Ngày điều tra: 2026-11-02. Chế độ: **READ-ONLY + PROBE OFFLINE THẬT** (gọi hàm
localizer/pre-localize/TTS-render bằng `.venv`, input chứa LaTeX; KHÔNG sửa
source/config, KHÔNG build, KHÔNG khởi động app Eris, KHÔNG gọi ElevenLabs/Gemini
synth thật, KHÔNG lưu/phát audio).

Phân tầng: **[CODE]** đọc source (file:dòng); **[PROBE]** kết quả gọi hàm offline
(input → output); **[SUY LUẬN]** suy từ bằng chứng.

---

## Tóm tắt câu trả lời (đọc trước)

1. **Localizer/pipeline KHÔNG strip LaTeX/markdown trước TTS.** `[PROBE]` xác nhận
   chuỗi `\(\frac{3}{4}\)`, `$...$`, `\[...\]` đi **nguyên vẹn** qua mọi stage và tới
   thẳng field `"text"` của request ElevenLabs. Ở mode Việt (mặc định), localizer
   `localize()` trả về `clean` không đổi; `_prelocalize_v03_speech` **copy display
   `text` thẳng vào `speech_text`**. Không có bước `strip_markdown`/`clean_for_tts`
   nào tồn tại.

2. **CÓ cơ chế tách display vs speech — nhưng KHÔNG phải tách trong `say`.** Hai field
   `text` (display) và `speech_text` (voice) tồn tại trên move, nhưng ở mode Việt
   chúng **cố ý được ép bằng nhau** (`speech_text = text`). Kênh tách thật khỏi TTS là
   **`presentation_blocks`** / `document_source` — sidecar "KHÔNG serialize vào gói
   Bubble/TTS" `[CODE public_output_artifact.py:59-60]`. Hợp đồng Root ghi rõ:
   "document_source/presentation_blocks dành cho nội dung **nhìn**; `say` là ý cần
   **nói**" `[CODE root_prompt_contract.py:15]`.

3. **Đường (b) [cho `say`/`text` mang LaTeX] SẼ LÀM HỎNG TIẾNG nếu không thêm bước
   strip-for-TTS.** Vì `speech_text == text` ở mode Việt, LaTeX đưa vào `text` để bubble
   render đẹp sẽ **đồng thời** thành transcript TTS. TTS khi đó đọc `\frac{3}{4}` thành
   chuỗi ký tự/chữ ("backslash frac ba bốn…") — đúng thảm họa âm thanh mà brief lo.
   Prompt Gemini còn chỉ thị "Read it in Vietnamese only… do not switch language"
   `[CODE tts_engine.py:566-570]`, không có lệnh bỏ ký hiệu toán.

4. **Để (b) an toàn cần MỘT trong hai điểm sửa** (độ lớn S–M):
   - **(b-strip)** Thêm bước strip-LaTeX-cho-TTS ở chỗ `_prelocalize_v03_speech`
     nhánh Việt (runtime_writer.py:65-71): thay vì `speech_text = text` thô, chạy
     `text` qua một hàm "xoá/đọc-hoá công thức" rồi gán vào `speech_text`, giữ `text`
     (display) nguyên LaTeX cho bubble. Tách hai field tại đúng junction đã có.
   - **(b-field)** Để writer/Root sinh `speech_text` RIÊNG (prose sạch) khác `text`
     (có LaTeX). Field đã tồn tại; chỉ cần bỏ ép-bằng-nhau ở nhánh Việt và dạy lane nói
     giữ hai bản. Tốn token hơn (model phải phát hai surface).

5. **(b) vs (a): (a) `presentation_blocks` an toàn tiếng hơn, (b-strip) rẻ token hơn.**
   (a) đã tách khỏi TTS sẵn (0 rủi ro đọc ký hiệu) nhưng tốn token/latency mỗi lượt
   toán (Root phát JSON block). (b-strip) 0 token thêm mỗi lượt + bubble đẹp, nhưng
   **phải** thêm bước strip (chi phí một lần, độ lớn S–M) và strip phải đủ tốt để không
   đọc nhầm. **Khuyến nghị: (b-strip)** nếu muốn bubble render MathJax rẻ nhất, với điều
   kiện bắt buộc có bước strip-for-TTS; nếu không muốn rủi ro strip, dùng (a).

**Một câu:** localizer/TTS **không** strip LaTeX (probe chứng minh ký hiệu tới thẳng
request synth), và ở mode Việt `speech_text == text`, nên đường (b) **hỏng tiếng** trừ
khi thêm bước tách-display/strip-cho-TTS tại `_prelocalize_v03_speech` — điểm sửa nhỏ,
đã có sẵn junction và field `speech_text`.

---

## Bằng chứng

### Q1. Đường đi của `say` → localizer → TTS: có strip LaTeX không?

**Junction `say`→`speech_text` [CODE `src/runtime/conversation/runtime_writer.py`]:**
- `realize()` gọi writer sinh payload có `text` (display) và optional `speech_text`,
  rồi chạy qua `_prelocalize_v03_speech(payload, language_hint=speech_language)`
  (dòng 305-308).
- `_prelocalize_v03_speech` **nhánh Việt** (dòng 65-71): khi `language_hint ∈
  {vi, vi-vn, vietnamese}`, lấy `vietnamese = speech_text or text` rồi
  `result.update(speech_text=vietnamese, speech_language='vi', tts_language='vi')`.
  → **Nếu writer không trả speech_text riêng, `speech_text` CHÍNH LÀ display `text`
  thô**, không qua bất kỳ sanitize nào. (dòng 68-70)
- Nhánh **Nhật** (dòng 93-151): nếu source chưa phải kana/kanji thì gọi
  `SpeechLocalizer.localize(..., 'ja', strict=True)` để DỊCH sang tiếng Nhật; dịch
  lỗi thì dùng filler Nhật. Đây là dịch nghĩa, không phải strip ký hiệu.
- `SurfaceEnvelope.speech_text = prepared.speech_text` (dòng 336) — bản này là nguồn
  TTS downstream.

**Localizer [CODE `src/runtime/speech_localizer.py`]:**
- `SpeechLocalizer.localize()` (dòng ~150): nếu `lang` không ∈ {ja,jp,japanese} thì
  `return clean` ngay (dòng ~168-170) — Việt/English **không được xử lý ký hiệu gì**.
- `_normalize_transcript()` (dòng ~470): chỉ gộp whitespace nội dòng + giữ line break.
  **Không đụng `\frac`, `$`, `\[`.**
- `_clean_translation_output()` (dòng ~485): chỉ trim quote và chuẩn hoá đuôi ký
  Nhật (ですね/だね/よね). Không strip LaTeX.
- Docstring file xác nhận localizer là "chuẩn hoá transcript trước khi đưa vào TTS"
  cho **ngôn ngữ** (VI bubble vs JA voice), không phải lớp làm sạch markup.

**TTS engine [CODE `src/runtime/tts_engine.py`]:**
- `_render_elevenlabs_text()` (dòng 691-722): chỉ thêm style tag + `_eleven_emphasize`
  + `_apply_voice_director_cue`. **Không strip ký hiệu toán.** Trả `body` (= text gốc)
  với tối đa một tag ở đầu.
- `_strip_tts_honorifics()` = `clean_public_addressing(text, surface="tts")`
  (dòng 1145). `clean_public_addressing`/`sanitize_legacy_addressing`
  `[CODE addressing_policy.py:193-271]` chỉ xử lý **xưng hô** (master/ご主人様, đại từ,
  vocative). Không chạm LaTeX/markdown.
- Payload ElevenLabs: `"text": rendered_text` (dòng 908, 920) — transcript đi thẳng.
- Gemini path `_build_tts_prompt()` (dòng 532-574): `tagged_text = f"{audio_tag}
  {text}"` — text gốc vào PERFORMANCE SCRIPT; nhánh VI chỉ dặn "Read it in Vietnamese
  only" (dòng 566-570), không có lệnh bỏ công thức. Docstring module (dòng 7-9):
  "Transcript UI/memory luôn sạch. Audio tags… chỉ tồn tại bên trong đường TTS" —
  "sạch" ở đây nghĩa là **không chèn tag vào UI**, KHÔNG phải strip markup khỏi TTS.

→ **Kết luận Q1:** KHÔNG có bước strip/chuyển LaTeX ở bất kỳ stage nào của đường
`say → localizer → TTS`. Mode Việt để nguyên; mode Nhật chỉ dịch nghĩa (vẫn sẽ dịch
`\frac{...}` như văn bản, không loại bỏ ký hiệu).

### Q2. PROBE OFFLINE THẬT — transcript đi vào TTS là gì?

Gọi trực tiếp các hàm bằng `.venv` (PYTHONPATH=src, `ERIS_TOKEN_BUDGET_ALL_LANES=0`),
KHÔNG gọi synth thật. Input:
- `LAT1 = "Ta co \(\frac{3}{4} + \frac{5}{6} = \frac{19}{12}\), vay ket qua lon hon 1."`
- `LAT2 = "Cong thuc: $\frac{a}{b} + \frac{c}{d}$ va block \[ \frac{19}{12} \] la ket qua."`

`[PROBE]` kết quả (ký hiệu `\frac`, `\(`, `\[`, `$`, `{}` còn nguyên = sẽ bị đọc):

| Stage gọi | LAT1 | LAT2 | LaTeX còn? |
|---|---|---|---|
| `localize(language_hint='vi')` | out == input | out == input | **CÒN** |
| `localize(language_hint='auto')` | out == input | out == input | **CÒN** |
| `_normalize_transcript` | chỉ gộp whitespace | như trái | **CÒN** |
| `_prelocalize_v03_speech(language_hint='vi')` → `speech_text` | `speech_text == text` | `speech_text == text` | **CÒN** (speech_language=vi, tts_language=vi) |
| `_strip_tts_honorifics` | không đổi | không đổi | **CÒN** |
| `_render_elevenlabs_text` (→ field `"text"` ElevenLabs) | không đổi | không đổi | **CÒN** |

Trích `[PROBE]` cuối đường (bản đi vào ElevenLabs `"text"`):
`'Ta co \\(\\frac{3}{4} + \\frac{5}{6} = \\frac{19}{12}\\), vay ket qua lon hon 1.'`

→ **Kết luận Q2:** transcript vào TTS **giữ nguyên toàn bộ ký hiệu LaTeX**. Nếu đưa
LaTeX vào `say`/`text`, TTS sẽ nhận `\frac{3}{4}` làm văn bản cần đọc. (Không gọi synth
thật; từ prompt VI "read in Vietnamese only" + không có bước phiên âm toán, `[SUY LUẬN]`
engine sẽ đọc các token này thành chữ/ký hiệu — thảm họa âm thanh như brief cảnh báo.)

### Q3. Có sẵn cơ chế tách display-text vs speech-text không?

**CÓ hai lớp tách, nhưng khác nhau:**

1. **Field `text` (display) vs `speech_text` (voice)** — tồn tại trên payload/SurfaceEnvelope
   `[CODE runtime_writer.py:336,500,516]`. NHƯNG ở **mode Việt** chúng bị **ép bằng nhau**:
   `_prelocalize_v03_speech` nhánh Việt gán `speech_text = speech_text or text`
   (runtime_writer.py:68-70). Nếu writer không chủ động sinh `speech_text` khác, hai
   bản trùng nhau. (Khớp runtime-lessons mục 12: nhánh Việt "ghi đè speech bằng public
   `text`", và probe 17/10 thấy 12/12 cặp `text`/`speech_text` giống nhau.)

2. **`presentation_blocks` / `document_source`** — kênh nội dung NHÌN, **đã tách khỏi
   TTS**:
   - `PublicOutputArtifact.presentation_blocks`: "Sidecar trong process, không serialize
     vào gói Bubble/TTS" `[CODE public_output_artifact.py:59-60]`.
   - Writer `writer_brief` loại `presentation_blocks`/`document_source` khỏi brief để
     "KHÔNG đọc nguyên tài liệu thành lời thoại" `[CODE runtime_writer.py:389]`.
   - Hợp đồng Root: "document_source/presentation_blocks dành cho nội dung nhìn; say là
     ý cần nói, hai kênh không bắt buộc trùng văn bản" `[CODE root_prompt_contract.py:15]`.
   - `normalize_presentation_blocks`: "invalid LLM data never leaks into a sidecar, TTS
     or history" `[CODE presentation_p2.py:28]`; format block `math.content={latex}`
     `[CODE tool_guides.py:9-12]`.

→ **Kết luận Q3:** Eris **đã** có kênh display-only tách khỏi TTS = `presentation_blocks`
(chính là đường (a)). Field `speech_text` vs `text` cũng tồn tại nhưng **hiện bị ép bằng
nhau ở mode Việt**, nên chưa phải một kênh tách sẵn sàng cho LaTeX; muốn dùng phải bỏ
ép hoặc chèn bước strip (xem Q4).

### Q4. Kết luận đường (b): an toàn hay hỏng tiếng?

**(b) = cho `say`/`text` mang LaTeX để bubble render đẹp, 0 token thêm.**

- Vì `speech_text == text` (mode Việt), LaTeX trong `text` **đồng thời** là transcript
  TTS → **HỎNG TIẾNG** (Q2 probe). (b) ở trạng thái hiện tại KHÔNG an toàn.
- Để (b) an toàn, cần tách kênh đọc khỏi kênh nhìn. Hai điểm sửa khả dĩ:

  **(b-strip) — khuyến nghị, độ lớn S–M.** Điểm sửa chính xác:
  `_prelocalize_v03_speech`, nhánh Việt, `src/runtime/conversation/runtime_writer.py:65-71`.
  Thay `vietnamese = speech_text or text` (dùng text thô) bằng: giữ `text` (display,
  có LaTeX) nguyên cho bubble, nhưng gán `speech_text = strip_math_for_speech(text)`
  — một hàm mới xoá/đọc-hoá `\(...\)`, `\[...\]`, `$...$`, `\frac{a}{b}` → "a trên b"
  (hoặc lược bỏ). Bubble (`display_text`) vẫn mang LaTeX để MathJax vẽ; TTS nhận bản
  sạch. Tận dụng đúng junction + field `speech_text` đã có; không đụng renderer/gateway.
  Rủi ro: chất lượng hàm strip (phải phủ các delimiter MathJax mà DeepSeek trả:
  `\(...\)`, `\[...\]` — theo deepseek-latex-probe.md Ping B).

  **(b-field) — độ lớn M, tốn token.** Dạy lane nói/`root_prompt_contract.py` sinh
  `speech_text` prose sạch TÁCH khỏi `text` có LaTeX, và bỏ ép-bằng-nhau ở nhánh Việt.
  Model phải phát hai surface mỗi lượt toán → tốn token hơn (b-strip).

- Lưu ý mode Nhật: kể cả (b-strip), nếu đưa LaTeX vào `text` rồi dịch sang Nhật, localizer
  dịch `\frac{...}` như văn bản. Strip phải chạy TRƯỚC nhánh dịch, hoặc dịch-rồi-bubble
  dùng hai nguồn khác nhau. Điểm sửa (b-strip) ở nhánh Việt; nhánh Nhật cần xử lý tương tự
  nếu bật voice Nhật cho nội dung toán.

### Q5. So sánh cuối: (b) vs (a)

| Tiêu chí | (a) `presentation_blocks` | (b-strip) `text` LaTeX + strip speech_text |
|---|---|---|
| Token mỗi lượt toán | **Tốn thêm** (dạy cú pháp block + Root phát JSON block) | **0 thêm** (bubble render sẵn) |
| Latency | +nhẹ (block publish sau commit) | **Thấp nhất** |
| An toàn tiếng | **An toàn sẵn** (đã tách khỏi TTS — public_output_artifact.py:59-60) | An toàn **chỉ sau khi** thêm strip; phụ thuộc chất lượng strip |
| Độ lớn sửa | S–M (`root_prompt_contract.py`, soft-force) | S–M (hàm strip + sửa junction runtime_writer.py:65-71) |
| Rủi ro còn lại | Root phải nhớ phát block mỗi lượt | Hàm strip bỏ sót delimiter → vẫn đọc ký hiệu |

→ **Khuyến nghị:** Nếu mục tiêu là **bubble đẹp + rẻ token nhất**, chọn **(b-strip)**:
cho `text` mang LaTeX (MathJax trong bubble vẽ — đã chứng minh ở deepseek-latex-probe.md
Q4), **bắt buộc** thêm bước strip-for-TTS tại `_prelocalize_v03_speech` nhánh Việt để
`speech_text` sạch. Nếu không muốn gánh rủi ro strip bỏ sót, chọn **(a)** vì nó đã tách
khỏi TTS bằng thiết kế. Cả hai điểm sửa gốc đều ở lớp Root/writer, không đụng renderer
bubble hay gateway.

---

## Kết luận & khuyến nghị

1. **Localizer/TTS KHÔNG strip LaTeX** — `[PROBE]` xác nhận ký hiệu tới thẳng request
   synth; không có hàm `strip_markdown`/`clean_for_tts` trong đường
   `say→localizer→TTS`.
2. **Có kênh tách display/speech:** `presentation_blocks` (đã tách khỏi TTS) = đường (a);
   field `speech_text` vs `text` tồn tại nhưng **bị ép bằng nhau ở mode Việt**.
3. **Đường (b) hiện HỎNG TIẾNG** vì `speech_text == text`: LaTeX trong `say` sẽ bị TTS
   đọc thành ký hiệu.
4. **Điểm sửa để (b) an toàn (độ lớn S–M):** thêm `strip_math_for_speech()` và áp tại
   `src/runtime/conversation/runtime_writer.py:65-71` (nhánh Việt của
   `_prelocalize_v03_speech`) để `speech_text` sạch còn `text`/bubble giữ LaTeX.
   KHÔNG đụng renderer bubble (chat.js) hay gateway.
5. **(b-strip) rẻ token nhất và nên làm** nếu chấp nhận viết+kiểm hàm strip cho các
   delimiter MathJax DeepSeek trả (`\(...\)`, `\[...\]`, `$...$`, `\frac`); ngược lại
   **(a)** an toàn-sẵn nhưng tốn token mỗi lượt.

**Cần xác minh cuối bằng phiên live** (ngoài phạm vi read-only này): sau khi thêm strip,
nghe một lượt toán thật để chắc TTS không đọc ký hiệu và bubble vẫn render MathJax.

---

## Phân tầng bằng chứng
- **[CODE]** `src/runtime/conversation/runtime_writer.py:65-71` (nhánh Việt ép
  speech_text=text), `:93-151` (nhánh Nhật dịch), `:305-308,336,389`;
  `src/runtime/speech_localizer.py` `localize()` (return clean cho non-ja),
  `_normalize_transcript`, `_clean_translation_output`;
  `src/runtime/tts_engine.py:691-722` (`_render_elevenlabs_text`), `:908,920`
  (payload `"text"`), `:532-574` (Gemini prompt VI), `:1145` (`_strip_tts_honorifics`),
  docstring `:7-9`; `src/runtime/addressing_policy.py:193-271` (chỉ xưng hô);
  `src/runtime/conversation/public_output_artifact.py:59-60` (presentation_blocks
  không vào Bubble/TTS); `src/runtime/conversation/root_prompt_contract.py:15`
  (say=nói, blocks=nhìn); `src/runtime/workspace/presentation_p2.py:28`;
  `src/runtime/conversation/tool_guides.py:9-12` (math.content={latex}).
- **[PROBE]** Gọi offline `.venv` các hàm `SpeechLocalizer.localize`,
  `_normalize_transcript`, `_prelocalize_v03_speech`, `_strip_tts_honorifics`,
  `_render_elevenlabs_text` với input LAT1/LAT2 → LaTeX còn nguyên ở mọi stage, bản
  cuối vào ElevenLabs `"text"` giữ `\(\frac{3}{4}\)...`. KHÔNG gọi synth thật, KHÔNG
  lưu audio. Script probe tạm đã xoá sau khi chạy.
- **[SUY LUẬN]** Engine sẽ phát âm ký hiệu LaTeX thành chữ (không gọi synth để tránh
  tốn quota/audio); điểm sửa (b-strip) và thứ tự strip-trước-dịch cho nhánh Nhật.
- Đối chiếu bổ sung, không mâu thuẫn:
  `.agents/tasks/eris-tutor-routing/deepseek-latex-probe.md` (bubble render MathJax +
  ràng buộc TTS chưa kiểm — báo cáo này giải đáp ràng buộc đó);
  `docs/knowledge/2026-10-14-eris-runtime-lessons.md` mục 12 (nhánh Việt ghi đè speech
  bằng public text; 12/12 cặp text/speech_text giống nhau).
