# Chẩn đoán: voice ElevenLabs chậm, nghi "tool sync" lỗi, đổi sang JP "chết"/không sync liền

Phạm vi: điều tra read-only, chỉ đọc source + chạy test giả lập. KHÔNG sửa code, không restart, không đo được audio/latency live trong phiên này. Tất cả dẫn chứng là đường dẫn file + symbol trong checkout `c:\Users\Gtvkun\Documents\GitHub\eris`. Đối chiếu với tri thức dự án `docs/knowledge/2026-10-14-eris-runtime-lessons.md` (mục 8, 11) và `docs/knowledge/2026-10-18-elevenlabs-token-ipv6-latency.md`.

Phân tầng bằng chứng dùng trong báo cáo: **[SẢN PHẨM]** = yêu cầu/thiết kế; **[SOURCE]** = đọc code tĩnh; **[TEST]** = kết quả test giả lập; **[LIVE?]** = chưa kiểm chứng trên runtime thật.

---

## Tóm tắt trả lời trước

1. **Voice chậm (A):** Nguyên nhân khả dĩ nhất KHÔNG phải synth ElevenLabs (synth đo được 3–4s trong tài liệu 18/10), mà là **bước làm mới bearer token của pool chạy đồng bộ ngay trên critical path TTS**. `_get_elevenlabs_token` chọn account theo "nhiều quota nhất" chứ không theo "token còn hạn", nên thường rơi vào account có bearer đã hết hạn và phải gọi `GLOBAL_ELEVEN_POOL.sync_subscription()` ngay lúc đó. `sync_subscription` gọi `requests.post/get(timeout=12)` tới `securetoken.googleapis.com` và `api.elevenlabs.io`; host securetoken trả IPv6 trước, cả 8 địa chỉ IPv6 timeout nối tiếp (~12s/địa chỉ ≈ ~96s) rồi mới sang IPv4. Đây đúng cơ chế tài liệu 18/10 tái hiện (~98s chờ trước request). **Fix IPv4-first được tài liệu đề xuất CHƯA có trong code hiện tại** — `_get_elevenlabs_http_session()` vẫn dùng `HTTPAdapter` mặc định, và `sync_subscription` còn dùng `requests` trần (không qua session). [SOURCE/LIVE?]

2. **"Tool sync" lỗi (B):** "sync" sát nghĩa nhất với triệu chứng là **ElevenLabs pool subscription sync** (`sync_subscription` / `_run_one_auto_sync` / nút Sync trong pool UI :18888), không phải settings-ACK sync. Chính bước sync này là thứ đang chậm/timeout và kéo theo cả triệu chứng (1). Có ba cơ chế "sync" khác nhau trong hệ, liệt kê bên dưới; cơ chế pool là ứng viên lỗi rõ nhất. [SOURCE]

3. **Đổi JP "chết" + không sync liền (C):** Có HAI đường độc lập.
   - (c-chậm/câm) JA mode dùng `elevenlabs_voice_id_ja` mà **default rỗng** → `_voice("ja")` tụt xuống voice fallback cứng `fUjY9K2nAIwlALOwSiwc`. Nếu voice này không được account/pool cấp quyền, synth JA lỗi → fallback chain/breaker → trễ hoặc câm. VI mode có `elevenlabs_voice_id_vi` cấu hình sẵn nên không bị. [SOURCE/LIVE?]
   - (c-không-liền) Khi đổi language, runtime rebuild worker TTS đồng bộ dưới lock và hủy turn đang chạy (`refresh_configuration` → `supersede_all`), cộng với việc JA bật `stage_localize` kéo localizer vào luồng. Nếu localizer chậm/lỗi hoặc token refresh đang treo (xem A), lượt đổi-ngôn-ngữ đầu tiên có cảm giác "đơ/chết" và chưa phát được ngay. [SOURCE/LIVE?]
   - Alias `jp`→`ja`: phần lớn đường vào normalize đúng; có MỘT lỗ tiềm ẩn (payload nested gửi chuỗi `"jp"` thô sẽ bị enum từ chối), nhưng client Settings hiện tại đã tự chuẩn hóa `jp`→`ja` trước khi gửi, nên lỗ này **không phải** nguyên nhân thực tế của bản đang chạy. Chi tiết mục C.

Không có bằng chứng runtime tự crash process trong code đã đọc; "chết" nhiều khả năng là treo/trễ/câm một lượt chứ không phải tiến trình thoát.

---

## A. VOICE CHẬM

### Đường synth hiện tại
- `src/runtime/tts_engine.py` `_synthesize_elevenlabs_wav` chọn 1 trong 2 nhánh theo token: token bắt đầu `eyJ` → **Bearer** `POST https://api.us.elevenlabs.io/v1/text-to-dialogue/stream`; ngược lại → **xi-api-key** `POST {base}/v1/text-to-speech/{voice}/stream`. Cả hai `output_format=pcm_24000`, `stream=True`, `timeout=(15.0, _elevenlabs_timeout_seconds())`. [SOURCE: tts_engine.py ~921–1060]
- `_elevenlabs_timeout_seconds()` mặc định **120s** (clamp 20–300) qua `ERIS_ELEVENLABS_TIMEOUT_S`. Connect timeout 15s, read timeout 120s. [SOURCE: tts_engine.py ~448–453]
- Nhánh Bearer chỉ gửi `stability` + `use_speaker_boost`; nhánh xi-api-key gửi thêm `similarity_boost/style/speed` và `language_code`. (Trùng nhận định mục 12 tài liệu.) [SOURCE]

### Token/pool trên critical path = nguồn chậm chính
- `_get_elevenlabs_token` lặp tối đa 64 account; với mỗi account: nếu `bearer_token` còn hạn → trả ngay; nếu hết hạn → gọi **`GLOBAL_ELEVEN_POOL.sync_subscription(acc.id)` đồng bộ**. [SOURCE: tts_engine.py ~286–330]
- `get_active_account` sắp xếp `ORDER BY (character_limit - character_count) DESC, last_used_at ASC` — tức **ưu tiên account còn nhiều quota nhất, KHÔNG ưu tiên account có bearer còn hạn**. Hệ quả: dễ chọn trúng account có token hết hạn và phải sync ngay giữa lượt. [SOURCE: elevenlabs_pool_db.py ~235–288]
- `sync_subscription` thực hiện **hai** request nối tiếp, mỗi cái `timeout=12`: `requests.post(securetoken.googleapis.com/v1/token)` rồi `requests.get(api.elevenlabs.io/v1/user/subscription)`. [SOURCE: elevenlabs_pool_db.py ~392–455]
- Tài liệu 18/10 tái hiện: `securetoken.googleapis.com` trả 8 IPv6 trước 8 IPv4; 8 connect IPv6 timeout nối tiếp ≈ 96s trước khi tới IPv4. JWT `iat` của account khớp đúng thời điểm ~98s trước request synth trong trace. [SOURCE tài liệu]
- **Fix chưa áp:** `_get_elevenlabs_http_session()` chỉ tạo `requests.Session()` + `HTTPAdapter(pool_connections=5, pool_maxsize=10)`, KHÔNG có override ưu tiên IPv4 / `create_connection` tùy biến. `sync_subscription` còn không dùng session này (dùng `import requests; requests.post(...)` trần). Hướng sửa tài liệu đề xuất (adapter IPv4-first + tránh refresh nhiều account hết hạn nối tiếp trên critical path) vẫn chưa có trong code. [SOURCE: tts_engine.py ~272–283; elevenlabs_pool_db.py ~385–401]
- Có giảm nhẹ: `start_background_sync()` (interval mặc định 1800s, ngưỡng low-quota) refresh trước account sắp cạn ở nền; nhưng nó quét theo quota thấp, không bảo đảm account được `get_active_account` chọn đã có bearer còn hạn. [SOURCE: elevenlabs_pool_db.py ~479–588]

### Circuit breaker — ĐỐI CHIẾU mục 8 tài liệu (đã được sửa)
- `breaker_key` ElevenLabs là tuple **5 phần** `("elevenlabs", account_id, model, voice, locale)`; Gemini là 4 phần. [SOURCE: tts_engine.py ~907–914; ~1697]
- Lo ngại lịch sử "metric unpack cứng 4 phần nuốt exception" **không còn đúng với code hiện tại**: `tts_circuit_breaker._record_metric` lấy `key[0]` và `key[-1]`, kèm comment nói rõ "không bao giờ giải nén 4 cứng". [SOURCE: tts_circuit_breaker.py ~43–52]
- Lo ngại "cancellation bị tính thành provider failure" cũng **đã được xử lý**: trong `except Exception`, code kiểm `_tts_request_cancelled(...)`/`str(exc)=="tts_cancelled"` TRƯỚC, raise `TtsCancelledError` mà KHÔNG `record_failure`; `finally` chỉ gọi `record_cancelled` khi permit đang `half_open` (nhả đúng một slot, không mở breaker). [SOURCE: tts_engine.py ~1083–1125; tts_circuit_breaker.py `record_cancelled` ~122–140]
- Breaker có thể vẫn gây chậm/câm gián tiếp: khi OPEN → `allow()` trả not-allowed → `_synthesize_elevenlabs_wav` raise `RuntimeError("TTS circuit breaker open: ...")` (ElevenLabs không có fallback nội tuyến trong nhánh này — khác Gemini path có `_try_local_tts_fallback`). Nếu 3 lần fail thật cùng key → OPEN 45s (`ERIS_TTS_BREAKER_COOLDOWN_S`). [SOURCE: tts_engine.py ~915–919; tts_circuit_breaker.py build_default]
- **KHÔNG kiểm chứng được breaker có đang OPEN/HALF_OPEN trên máy user hay không** (không có log/trace live phiên này). [LIVE?]

### Fallback sang Gemini làm tăng trễ?
- Nhánh ElevenLabs (xi-api-key/bearer) không tự rơi sang Gemini; chỉ xoay account trong pool khi lỗi quota. Gemini TTS là đường synth riêng (`breaker_key` 4 phần) với fallback local Edge/SAPI. Nếu provider cấu hình là `elevenlabs` thì không có bước Gemini xen vào gây trễ. [SOURCE: tts_engine.py ~1068–1125, ~1696–1890]

### Phân biệt trễ mạng/provider vs pipeline
- Trễ provider synth thật: 3–4s (đo trong tài liệu, không phải phiên này). [LIVE? qua tài liệu]
- Trễ pipeline chính: **token/pool refresh IPv6** (~98s trong tài liệu). [SOURCE + tài liệu]
- Trễ pipeline phụ có thể cộng vào JA: localizer (`ERIS_TTS_LOCALIZER_TIMEOUT_SEC` ~45s), breaker cooldown 45s nếu OPEN. [SOURCE]
- **Không đo được latency live trong phiên điều tra này.** [LIVE?]

---

## B. "TOOL SYNC" LỖI — các cơ chế "sync" và cái nào khả nghi

Không xác định chắc user chỉ "sync" nào; liệt kê đủ ba cơ chế kèm bằng chứng:

1. **ElevenLabs pool subscription sync (KHẢ NGHI NHẤT).**
   - `ElevenPoolDB.sync_subscription(account_id)`: đổi refresh-token→bearer qua Firebase rồi lấy quota từ ElevenLabs. Hai request `timeout=12`, chịu phạt IPv6 (xem A). Nút "Sync" trên pool UI (`elevenlabs_pool_server.py` ~702–705, URL `http://127.0.0.1:18888`, mở từ `manager_gui.py ELEVENLABS_POOL_URL`) gọi đúng hàm này; `start_background_sync`/`_run_one_auto_sync` cũng vậy. [SOURCE]
   - Triệu chứng user ("tool sync bị lỗi") + "voice chậm" khớp với: khi sync token chậm/timeout, account không có bearer hợp lệ → hoặc chờ rất lâu, hoặc `get_active_account` loại hết account → `_get_elevenlabs_token` trả `("","",0)` → "Không có ElevenLabs account nào còn ≥100 quota" → câm/lỗi TTS. [SOURCE: tts_engine.py ~335–340, ~860]

2. **Settings runtime JSON ACK sync (settings bubble ↔ Brain).**
   - Client C# gửi UDP `{"type":"settings_update","scope":"tts","settings":{"tts":{...}}}` (`UdpListener.SettingsPanel.cs` ~2186–2213). Brain xử lý ở `settings_control_runtime._handle_settings_update` → `normalize_settings_message` → `store.apply_patch(..., materialize_env=False)` → trả `settings_update_ack`. [SOURCE]
   - Cơ chế này về cơ bản lành; rủi ro là field bị enum từ chối (mục C) hoặc ack chậm nếu `_refresh_runtime_after_settings` rebuild TTS trong lúc token refresh đang treo. Không có bằng chứng ACK channel tự hỏng. [SOURCE]

3. **Bootstrap env vs saved-language reconcile.**
   - `RuntimeSettingsStore.load()` dùng `has_saved_language` + `_apply_bootstrap_tts_language`: chỉ áp `ERIS_TTS_LANGUAGE` env khi **chưa có** language đã lưu. Lựa chọn đã lưu thắng env (mục 11 tài liệu). Reconcile này chạy lúc load/migrate, không phải "tool" user bấm; ít khả năng là "sync" user nói. [SOURCE: runtime_settings_store.py load ~ + `_apply_bootstrap_tts_language`]

**Kết luận B:** nếu "tool sync" = nút Sync pool / auto-sync quota → đó là cơ chế đang lỗi (timeout IPv6), và nó là gốc chung với triệu chứng A. Nếu user chỉ settings-sync → đường đó lành về logic; độ trễ cảm nhận chủ yếu vay từ TTS refresh/token. [SOURCE/LIVE?]

---

## C. ĐỔI SANG JP "CHẾT" + KHÔNG SYNC LIỀN

Lần theo luồng: `settings_protocol.normalize` → `settings_control_runtime._handle_settings_update` → `runtime_settings_store.apply_patch` → speech pipeline (`runtime_writer`, `speech_contract`, `tts_engine`).

### (a) Alias `jp` được normalize đúng ở MỌI điểm vào không? — Gần đủ, còn 1 lỗ tiềm ẩn KHÔNG kích hoạt ở bản hiện tại
- Client Settings C# `NormalizeSettingsTtsLanguage` map `jp/japanese/ja-jp/""/auto`→`ja` TRƯỚC khi gửi, và dropdown dùng metadata code `{"vi","ja","en"}` trực tiếp. Nên payload thực tế gửi xuống là `"ja"`, không phải `"jp"`. [SOURCE: UdpListener.SettingsPanel.cs ~2381–2393, ~1537, ~2491]
- Phía Brain, `normalize_settings_message`: với payload **nested Mapping** (đúng dạng client gửi: `settings={"tts":{...}}`), nhánh này **đi thẳng patch, KHÔNG gọi `_language()`**. Chỉ nhánh **flat legacy** (`msg["tts_language"]`) mới gọi `_language()` (có alias `jp`→`ja`). [SOURCE: settings_protocol.py `normalize_settings_message`, `_language`]
- `apply_patch` → `_coerce_setting` kiểm `tts.language` theo enum `{"vi","ja","en"}`, chỉ `.lower()`, **không alias `jp`**. [SOURCE: runtime_settings_store.py `_coerce_setting`, `enum_values["tts.language"]`]
- Lưu ý: `_normalize_tts_language` (có alias `jp`→`ja`) trong store CHỈ dùng cho `has_saved_language`/bootstrap/migrate, KHÔNG dùng trong `apply_patch`. [SOURCE: runtime_settings_store.py `_normalize_tts_language`, `load`]
- **Hệ quả:** nếu BẤT KỲ client/đường nào gửi nested `{"tts":{"language":"jp"}}` thô, field bị **rejected** (không apply), language không đổi → đúng kiểu "không sync liền". Hiện client chính đã chặn điều này ở phía C#, nên đây là **lỗ tiềm ẩn/đề phòng**, không phải nguyên nhân xác nhận. **Khuyến nghị:** cho `settings_protocol`/`_coerce_setting` alias `jp→ja` để phòng thủ nhiều lớp. [SOURCE]

### (b) has_saved_language/bootstrap có chặn đổi không? — Không chặn apply live
- `apply_patch` ghi thẳng `tts.language` vào store rồi `_atomic_save`, không qua guard bootstrap. Guard bootstrap chỉ chạy ở `load()` khi chưa có saved language. Test `test_saved_language_survives_restart_with_legacy_japanese_env` xác nhận saved thắng env. [TEST + SOURCE]
- NHƯNG `apply_patch(materialize_env=False)`: **không cập nhật `os.environ["ERIS_TTS_LANGUAGE"]` live**. Các đường đọc qua `runtime_text("tts","language")` (vd `configured_speech_language`, `_language_hint`, `public_output_runtime`, `orchestrator`) sẽ thấy giá trị mới ngay (đọc store). Nhưng đường nào đọc trực tiếp `os.environ["ERIS_TTS_LANGUAGE"]` (vd `startup_grounding.py` ~610, `speech_contract` đọc `ERIS_TTS_VOICE_FAMILY`) sẽ **lệch** cho tới restart. Đây là một nguồn "không đồng bộ ngay" cho các thành phần còn đọc env. [SOURCE]

### (c) Nhánh JA trong runtime_writer có kéo localizer gây "chết"?
- `_prelocalize_v03_speech`: nhánh VI ghi đè `speech_text = text` (dùng public Việt, KHÔNG gọi localizer Nhật). Nhánh JA: nếu transcript đã là kana/kanji thì giữ; nếu chưa, gọi `localizer.localize(..., strict=True)` tối đa 2 lần; hết retry dùng filler `えっと…`; cancellation raise `v03_speech_localization_cancelled`. [SOURCE: runtime_writer.py ~50–135]
- Rủi ro "chết"/trễ ở JA: localizer là call LLM có timeout riêng (~45s). Nếu localizer chậm/lỗi, lượt JA đầu tiên trễ rõ hoặc rơi về filler. VI không có bước này. Kết hợp với token refresh treo (A) → cảm giác "đổi sang JP là đơ". **Không đo được thời gian localizer live.** [SOURCE/LIVE?]
- `SpeechContractResolver.resolve`: khi `default_language == "ja"` thì **ép `language="ja"`** bất kể supplied (`if default_language=="ja" and language!="ja": language="ja"`). Đây là "ja pin toàn cục" mục tài liệu cảnh báo — hợp lý khi default là ja, nhưng nghĩa là ở mode mặc định (ja), mọi thứ bị ghim ja; không trực tiếp gây crash. [SOURCE: speech_contract.py ~86–100]

### (d) Có exception/unhandled nào làm crash runtime khi apply JP?
- `_handle_settings_update` bọc toàn bộ trong `try/except Exception` và trả ack `ok:false` khi lỗi — **không làm sập runtime loop**. `refresh_configuration` bọc shutdown worker/manager trong try/except. Không thấy đường raise thoát ra tới run-loop. [SOURCE: settings_control_runtime.py ~393–449; tts_engine.py refresh_configuration ~3142–3175]
- Kết luận: "chết" **không** khớp bằng chứng crash tiến trình; khớp hơn với treo/câm một lượt. [SOURCE]

### (e) Candidate/audio ngôn ngữ cũ có bị chặn gây kẹt?
- Có cơ chế chặn CHỦ ĐÍCH (đúng thiết kế mục 11): đổi language bump `_speech_epoch` + `supersede_all`; worker/adapter từ chối reply/epoch của ngôn ngữ cũ. Test chứng minh: `test_writer_rejects_reply_started_before_language_switch` (raise `speech_configuration_changed`), `test_prepared_old_language_is_rejected_before_body_dispatch`, `test_language_refresh_revokes_old_speech_epoch`, `test_new_vietnamese_worker_rejects_sealed_japanese_reply`. [TEST: 24 passed]
- Đây là reject có chủ đích để không phát nhầm giọng cũ, KHÔNG phải "kẹt". Nhưng nó có nghĩa: lượt đang chạy lúc đổi ngôn ngữ **bị bỏ** (phải nói lại) → người dùng thấy như "mất một lượt/không phản hồi ngay". [SOURCE/TEST]

### Voice JA rỗng — đường câm/chậm cụ thể của JP
- `_voice("ja")` lấy `tts.elevenlabs_voice_id_ja`; **default `""`** trong `_DEFAULT_SETTINGS` → tụt xuống `ERIS_ELEVENLABS_VOICE_ID` (env) hoặc `tts.elevenlabs_voice_id` (default `""`) hoặc hằng `fUjY9K2nAIwlALOwSiwc`. VI có `elevenlabs_voice_id_vi="aHC3XZOMg3HZuXVYK6hy"` cấu hình sẵn. [SOURCE: tts_engine.py `_voice` ~104–118; runtime_settings_store.py `_DEFAULT_SETTINGS["tts"]`]
- Nếu voice fallback cứng không được pool/account cấp quyền → synth JA lỗi → breaker đếm fail → có thể OPEN → câm/chậm. **Giả thuyết mạnh nhưng chưa kiểm chứng live** (cần thử synth JA thật với voice đang cấu hình). [SOURCE/LIVE?]

---

## Kết quả test đã chạy (giả lập, KHÔNG phải audio live)
- `python -m pytest src/tests/test_live_speech_language_switch.py` → **24 passed in 2.43s**. (Lưu `./.agents/tasks/eris-tts-slow-jp-switch/pytest_out.txt`.)
- **Chứng minh:** hợp đồng chuyển ngôn ngữ live đúng ở tầng logic — VI không gọi localizer JA và loại speech JA; `_voice()` chọn voice theo ngôn ngữ; epoch/worker reject reply ngôn ngữ cũ trước khi tới Body; saved language thắng env bootstrap.
- **KHÔNG chứng minh:** độ trễ thực, token refresh IPv6, breaker có OPEN trên máy user, voice JA rỗng có gây câm live, hay localizer có timeout live. Test dùng fake, chặn network. [TEST/LIVE?]

---

## Khuyến nghị (chưa triển khai — chỉ đề xuất)

Ưu tiên theo tác động:

1. **IPv4-first cho HTTP refresh/sync pool (gốc của A và B).** Thêm adapter ưu tiên IPv4 theo host (hoặc `urllib3` `allowed_gai_family`/override `create_connection`) cho `_get_elevenlabs_http_session`, và cho `sync_subscription` dùng chung session đó thay vì `requests` trần. Giảm connect timeout per-address (12s là quá dài khi có 8 địa chỉ IPv6 chết). [giải quyết ~98s chờ]
2. **Đưa token refresh ra khỏi critical path.** `get_active_account` nên ưu tiên (hoặc cân nhắc) account có `bearer_expires_at` còn hạn khi quota tương đương; hoặc để background sync bảo đảm account-ứng-viên luôn có bearer hợp lệ trước khi TTS cần. Tránh lặp `sync_subscription` nhiều account hết hạn nối tiếp trong một request.
3. **Cấu hình `elevenlabs_voice_id_ja`.** Đặt voice JA hợp lệ (được account/pool cấp quyền) để JA mode không rơi về voice fallback cứng. Giải quyết đường câm/chậm riêng của "đổi sang JP".
4. **Phòng thủ alias `jp`→`ja` nhiều lớp.** Cho `settings_protocol.normalize_settings_message` (nhánh nested) và/hoặc `_coerce_setting` alias `jp/japanese/ja-jp`→`ja` trước khi kiểm enum, để mọi client (kể cả client cũ/khác) đổi JP đều có hiệu lực.
5. **Materialize env khi apply TTS live (hoặc bỏ các đường đọc env trực tiếp).** Để thành phần còn đọc `os.environ["ERIS_TTS_LANGUAGE"]`/`ERIS_TTS_VOICE_FAMILY` không lệch tới restart; hoặc chuyển hẳn các điểm đó sang `runtime_text(...)`.

## Giới hạn điều tra
- Chỉ đọc source + test giả lập; không chạy runtime, không synth live, không bắt packet, không đọc log phiên user hiện tại. Các mục gắn [LIVE?] cần log/trace hoặc probe mạng có kiểm soát để xác nhận.
- Không đối chiếu checkout portable thứ hai trong phiên này; tài liệu 18/10 ghi các module TTS liên quan từng trùng byte với checkout dev, nhưng cần xác định lại process/executable đang phục vụ user trước khi kết luận fix có tới bản đang chạy.
- Đã đối chiếu kết luận lịch sử (mục 8 tài liệu) với code hiện tại: lo ngại "breaker unpack 4 phần nuốt exception" và "cancellation tính thành provider failure" **đã được sửa** trong source hiện tại; không coi báo cáo cũ là trạng thái hiện hành.
