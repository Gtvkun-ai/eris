# Báo cáo chấm điểm Eris theo TIÊU CHÍ ĐÁNH GIÁ Hackathon SGU 2026–2027

Ngày đánh giá: 2026-11 (đánh giá tĩnh codebase, READ-ONLY).
Repo: `c:\Users\Gtvkun\Documents\GitHub\eris`.
Phạm vi: đọc source/tài liệu/cấu hình thật trong repo. **Không chạy build, không chạy test, không chạy live.**

---

## 0. Tóm tắt kết luận (đọc trước)

Eris là một **AI companion desktop tiếng Việt** (bong bóng chat tiếng Việt + giọng nói Nhật/Việt, nhân vật Live2D), kiến trúc 3 lớp: **frontend Godot 4 + C#/.NET** (Live2D, các panel settings/memory/tutor), **backend runtime Python** (agent loop, memory, TTS, guards) giao tiếp qua UDP, và **gateway Go `whale2api`** đứng trước DeepSeek. Đây là một codebase **rất lớn và trưởng thành về mặt kỹ thuật runtime** (hàng trăm module Python, nhiều lớp guard, pool key, circuit breaker, harness eval).

Tuy nhiên, chiếu theo bộ tiêu chí Hackathon, dự án có **ba khoảng trống nghiêm trọng về mặt "đưa đi thi"**:

1. **KHÔNG có CI/CD** — không tìm thấy `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile` (ảnh hưởng III.4-liên-quan và IV.4).
2. **KHÔNG có triển khai cloud AWS/GCP công khai** — không có terraform/cloudformation/app.yaml/cloudbuild/serverless. Chỉ có Dockerfile/compose *local* cho `whale2api` và `gemini_vision_docker`, và theo tri thức runtime các container này **giữ dừng, chưa deploy live** (ảnh hưởng VII, gần như bằng 0).
3. **Chất lượng đầu ra/kiểm thử chưa có "test report có chỉ số" đóng gói** — có harness đo accuracy/latency/calibration nhưng tri thức runtime ghi nhận nhiều suite đang có lỗi và nhiều kết luận "xanh" là cục bộ; Golden Mentor V85 đạt **2/20**.

Ngoài ra, bản thân sản phẩm theo chính tài liệu của repo **chưa có xác nhận chạy live ổn định**: tri thức runtime liên tục ghi "chưa nghe audio live", "chưa mở phiên chat sau khi sửa", và ghi nhận các lỗi runtime thật (mất text, trễ 60–98s, cắt audio khi đổi ngôn ngữ). Đây là desktop app, không phải web service, nên tiêu chí VII (cloud) gần như không áp dụng được cho hình thái sản phẩm hiện tại.

**Tổng điểm đề xuất (các phần chấm được, I–VII, bỏ VIII): ~41–47 / 90.**
Chi tiết và dải điểm ở BẢNG TỔNG HỢP cuối báo cáo.

> Lưu ý phương pháp: mọi nhận định dưới đây phân biệt rõ 4 mức bằng chứng — (a) yêu cầu sản phẩm, (b) nguyên tắc thiết kế, (c) trạng thái lịch sử trong tài liệu, (d) quan sát live. Hầu hết bằng chứng ở đây là **"đọc source tĩnh"**; không có quan sát live nào do task là READ-ONLY. Việc một module tồn tại/được import **không** chứng minh nó chạy đúng trong production.

---

## I. Tính sáng tạo & đổi mới — Đề xuất: 7/10

- **Bằng chứng:**
  - `src/README_VI.md`: kiến trúc "Unified Agent + Tutor + Conversation Pacing V2" — tách 3 nhịp (reasoning rhythm / pedagogical rhythm / conversation rhythm), ý tưởng "nghĩ dài nhưng nói theo nhịp người nghe", `deferred_threads`, speech budget tách khỏi token budget.
  - Kiến trúc nhân vật sống: `src/runtime/` có hàng loạt module cá tính/cảm xúc (`affective_dynamics_runtime.py`, `micro_reflex_system.py`, `banter_arbiter.py`, `nervous_system_v103_final.py`, `private_mind_loop.py`, Live2D affect bridge).
  - Companion tiếng Việt với bong bóng VI + voice JA/VI, Live2D (`asset/Resource/Monika.tscn`), chuyển ngôn ngữ live (tri thức runtime mục 11).
- **Mức bằng chứng:** đọc source tĩnh + tài liệu thiết kế. Chưa xác nhận trải nghiệm live.
- **Giải thích:** Ý tưởng một AI companion có "nội tâm", pacing hội thoại giống người, voice song ngữ và Live2D là **mới lạ và có chiều sâu** so với mặt bằng chatbot. Trừ điểm vì: (1) nhiều ý tưởng ở tầng thiết kế/chưa chứng minh tạo khác biệt live; (2) thành phần AI cốt lõi là wrapper quanh DeepSeek qua gateway, phần "đổi mới" nằm ở orchestration chứ không ở mô hình.

## II. Tính thực tiễn & khả năng áp dụng — Đề xuất: 5/10

- **Bằng chứng:**
  - Sản phẩm có đối tượng rõ: người dùng cá nhân muốn một companion/tutor tiếng Việt (tutor role: `src/runtime/tutor/`, `engineering_mentor.py`, `pedagogical_*`).
  - Có launcher thực tế: `run_eris.bat`, `installer/`, `eris_setup.py`, build scripts (`build_release_clean.bat`, `_fullbuild.py`), export Godot (`export_presets.cfg`).
- **Mức bằng chứng:** đọc source tĩnh. Khả năng vận hành live **chưa kiểm chứng**.
- **Giải thích:** Có đối tượng người dùng và đường đóng gói desktop. Nhưng tính "khả thi khi đưa vào vận hành" bị hạ mạnh bởi chính tài liệu runtime: `docs/knowledge/2026-10-14-eris-runtime-lessons.md` ghi nhận **lỗi vận hành thực tế** — độ trễ 60–98 giây trước khi ra tiếng (mục 1, 19, 25), mất text/không hiện chữ (mục 21), cắt audio khi đổi ngôn ngữ trễ 29–33s (mục 22), writer_failed do 429/401 (mục 8). Một companion realtime mà mất ~70s/lượt và rớt tiếng thì **chưa sẵn sàng vận hành thực tế**.

## III. Dữ liệu & mô hình (20đ)

### III.1 Dữ liệu — Đề xuất: 3.5/5

- **Bằng chứng:**
  - Hệ memory có provenance/admission rõ: `src/memory/claim_provenance.py`, `memory_admission.py`, `provenance_policy.py`, `memory/living_user/` (profile/dream/actions), `canonical_long_term.py`, `episodic_memory.py`, `belief_store.py`.
  - Embedding **local MiniLM**: `src/paraphrase-multilingual-MiniLM-L12-v2/`, dùng trong `memory/embedding_index.py` (nguồn dữ liệu nội bộ, không gửi text ra ngoài để embed).
  - Guard nguồn: `src/runtime/source_grounding.py` phân loại nguồn trả lời và cap confidence theo độ chắc của nguồn.
- **Mức bằng chứng:** đọc source tĩnh.
- **Giải thích:** Provenance/admission/scope là điểm mạnh thực sự. Nhưng tri thức runtime (mục 28–31) ghi nhận **lỗi chất lượng dữ liệu thật**: "tôi tự hỏi…" bị biến thành commitment active (0.92), câu giả định thành goal, `snapshot()` lấy theo trust/recency chứ không theo relevance, nhiều evidence `session_turn:<n>` không định danh phiên. Tức là có cơ chế minh bạch nhưng **chất lượng admission còn sai**. Không có mô tả "nguồn gốc/tính hợp pháp" của một bộ dữ liệu huấn luyện riêng — vì dự án không train model, chỉ tích lũy memory người dùng.

### III.2 Mô hình — Đề xuất: 2/5

- **Bằng chứng:**
  - Routing/role: `src/runtime/model_budget_policy.py` (tách cognitive_lane / backend / resource_class), `llm/deepseek_workers.py`, `runtime/ai_orchestrated/model_router.py`.
  - Gateway chỉ quảng bá một model: `tools/whale2api/internal/config/models.go` → chỉ `deepseek-flash`, `GetModelConfig` trả `search=false`.
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime (đã đính chính).
- **Giải thích:** Dự án **không tự xây/huấn luyện mô hình**; nó orchestrate DeepSeek (+ MiniLM embedding local). "Lý do chọn mô hình" có ngầm (model rẻ, pool key free tier) nhưng **không có thiết kế thực nghiệm/đánh giá mô hình đúng nghĩa khoa học, không có khả năng tái lập kết quả mô hình**. Tri thức runtime còn đính chính nhiều kết luận routing cũ là sai ("companion route Flash/Pro mỗi lượt" → thực tế policy không được gọi trên live path; "có Flash-search thật" → bị bác). Vì tiêu chí này đòi lý do chọn mô hình + phương pháp thực nghiệm + tái lập + quản lý rủiro mô hình, mà bằng chứng chỉ ở mức orchestration, nên điểm thấp.

### III.3 Kiểm soát rủi ro, An toàn AI & Thiên lệch — Đề xuất: 3/5

- **Bằng chứng (có cơ chế trong code):**
  - **Secret redaction thật:** `src/runtime/secure_redaction.py` — regex ẩn api_key/token/secret/password/bearer/connection_string, ẩn PII (email), ẩn đường dẫn nội bộ, chỉ giữ fingerprint; `GLOBAL_SECURE_REDACTOR`.
  - **Grounding/evidence gate:** `src/runtime/grounding_surface_gate.py` chỉ cho claim tri giác/hành động khi có evidence tương ứng; `source_grounding.py` cap confidence; `capability_claim_guard.py`, `structured_evidence.py`, `public_causal_receipt.py`.
  - **Language guard / single-speaker:** `src/runtime/stage_contracts.py` (giữ bản JP gốc cho language guard độc lập), `test_v57_live_behavior_simulation.py::test_v57_1_language_guard_catches_cjk_drift`; single-speech authority design (`docs/superpowers/specs/2026-10-01-single-speech-authority-design.md`), `final_speech_authority.py`.
  - **Chống hallucination/claim giả:** `src/memory/claim_entailment.py`, `claim_extractor.py`, `semantic_authority_v95.py`, verifier harness `src/tools/verifier_research.py`.
- **KHÔNG tìm thấy:** `prompt injection guardrails`, `toxicity filter` theo tên (grep `prompt.?injection|toxicity|jailbreak|sensitive.?data.?mask` → **không có match**).
- **Mức bằng chứng:** đọc source tĩnh (cơ chế tồn tại); **chưa verify hiệu quả live**.
- **Giải thích:** Phần grounding/evidence/secret-redaction/single-speaker/language là **điểm mạnh thật và khá hiếm** ở mức này. Nhưng tiêu chí nêu đích danh *prompt injection guardrails + toxicity filtering + sensitive data mask*: chỉ có **sensitive data mask** (redaction) và một phần **data mask PII**; **không có prompt-injection guard và toxicity filter** theo tên. Về bias: có xử lý admission/provenance nhưng không có module xử lý "thiên lệch dữ liệu/mô hình" theo đúng nghĩa fairness. Vì vậy chấm giữa khung.
  - **Rủi ro ngược:** tri thức runtime mục 9 ghi gateway từng *tự chèn* một "Output integrity note" yêu cầu detector bỏ qua kiểm tra (nay đã bỏ). Đây là tín hiệu cần nêu khi phản biện trước giám khảo.

### III.4 Chất lượng đầu ra & Kiểm thử mô hình — Đề xuất: 2/5

- **Bằng chứng:**
  - Harness eval có chỉ số: `src/tools/verifier_research.py` (accuracy, false_pass_rate, false_reject_rate, latency p50/p95), `src/tools/run_eris_character_eval.py` + `score_eris_character_eval.py` (latency_ms_p50/p95, model_calls), `src/tools/learner_benchmark.py` (accuracy, Brier/reliability, schema_valid_rate), `src/experiments/v57_simulation/` (relevance/coherence/naturalness/continuity/repair + latency).
  - Golden replay: `src/evals/run_mentor_eval_v85.py` + `mentor_golden_v85.json` (offline, deterministic).
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime (trạng thái lịch sử).
- **Giải thích:** Có **hạ tầng đo** tốt (accuracy/latency/calibration), nhưng:
  - **Không thấy BLEU/ROUGE/Retrieval Precision/F1** theo tên (grep không ra; chỉ có accuracy/latency/calibration).
  - **Không có "test report" đóng gói, minh bạch** như một tài liệu kết quả chạy — các con số nằm trong harness, chưa thấy báo cáo kết quả chính thức.
  - Tri thức runtime ghi kết quả **không ổn định/nhiều lỗi**: Golden Mentor V85 **2/20** (mục 13), các suite "xanh" thường là cục bộ và kèm chú thích "baseline có lỗi độc lập", README_VI ghi "full suite không thể dùng làm green gate".
  - Độ ổn định edge case: tri thức runtime cho thấy nhiều lỗi biên thật (cancel bị tính thành provider failure, budget localizer thay cả câu bằng filler `えっと…`). Đây là bằng chứng **chưa ổn định**.

**Tổng III (đề xuất): 3.5 + 2 + 3 + 2 = 10.5/20.**

---

## IV. Cấu trúc, chất lượng triển khai & độ hoàn thiện (20đ)

### IV.1 Cấu trúc dự án — Đề xuất: 2.5/3

- **Bằng chứng:** `src/` phân tách module rõ theo domain: `runtime/`, `llm/`, `memory/`, `memory_core/`, `embedding` (trong memory), `parser_grounding/`, `live2d_body/`, `powers/`, `telemetry/`, `settings/`, `transport/`, `vision.py`, `evals/`, `experiments/`, `tests/`. `pyproject.toml`, `pytest.ini` có mặt. Backend Python / FE Godot-C# / gateway Go tách tầng rõ.
- **Mức bằng chứng:** đọc source tĩnh.
- **Giải thích:** Phân tách module/tầng **tốt và nhất quán**. Trừ nhẹ: số lượng module runtime rất lớn (200+ file trong `src/runtime/`) với nhiều phiên bản (`_v95/_v98/_v99/_v100/_v101/_v102/_v103`), tri thức runtime nhiều lần nhắc tên class/comment cũ không phản ánh production — dấu hiệu nợ kỹ thuật/trùng lặp ảnh hưởng khả năng mở rộng.

### IV.2 Kiến trúc FE, UI/UX — Đề xuất: 2/3

- **Bằng chứng:** Godot 4 + C#/.NET (`Eris.sln`, `Eris.csproj`, `project.godot`), Live2D (`asset/Resource/Monika.tscn`), panel tách component qua partial class C#: `src/body/UdpListener.TutorPanel.cs`, `UdpListener.StructuredOutput.cs`, `src/integration/body_contracts/UdpListener.SettingsPanel.cs`, `UdpListener.MemoryPanel.cs`; preview UI riêng `tools/ui-preview/`. Dropdown ngôn ngữ live + settings bubble (tri thức runtime mục 11).
- **Mức bằng chứng:** đọc source tĩnh. **Chưa quan sát UI live** (đẹp/mượt/responsive không kiểm chứng được tĩnh).
- **Giải thích:** FE tổ chức component mạch lạc (partial class theo panel), có Live2D + chuyển ngôn ngữ live. Không thể xác nhận "đẹp mắt, mượt, responsive" từ source; "responsive" ít ý nghĩa với desktop Godot. Giữ mức khá dựa trên tổ chức code.

### IV.3 Kiến trúc BE & Hiệu suất — Đề xuất: 2.5/5

- **Bằng chứng:**
  - BE không phải REST/GraphQL cổ điển: giao tiếp **UDP** FE↔BE (`src/body/udpListener.tscn`, `UdpListener.*.cs`), gateway Go HTTP OpenAI-compatible (`tools/whale2api`), service HTTP cho vision/memory (`tools/gemini_vision_docker/server.py` cổng 8000).
  - DB/persistence: SQLite atomic state store (README_VI nhắc `SQLiteAtomicStateStore`), JSON stores (`memory/json_store_io.py`), ledger/persistence nhiều nơi.
  - Tối ưu tài nguyên: `model_budget_policy.py` (lock inference, queue priority, unload VRAM), embedding index nạp nền.
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime.
- **Giải thích:** Có thiết kế backend nghiêm túc và cơ chế quản tài nguyên. NHƯNG tiêu chí nhấn mạnh **"tốc độ phản hồi nhanh, tối ưu truy vấn"** — và đây là điểm yếu được chính tài liệu ghi nhận: latency chat **15–73 giây**, `memory_context_ms ≈ 30s`, cold embedding query **~22 giây** (mục 20, 25), prompt Self từng **1.29 triệu ký tự** (87% là concept graph, mục 25) — đã gỡ graph (mục 26) nhưng **chưa đo lại live**. API là UDP/HTTP nội bộ, không phải "RESTful/GraphQL chuẩn mực" theo nghĩa tiêu chí. Hiệu suất thực tế chưa đạt.

### IV.4 CI/CD & Pipeline Deploy — Đề xuất: 0.5/3

- **Bằng chứng (KHÔNG tìm thấy):** không có `.github/workflows/`, không có `.gitlab-ci.yml`, không có `Jenkinsfile`. Tìm kiếm toàn repo đều rỗng.
  - Thứ thay thế: build scripts thủ công (`build_dev_fast.bat`, `build_release_clean.bat`, `_fullbuild.py`, `run_tests.py`), Dockerfile cho `whale2api`/`gemini_vision_docker` (chạy local), compose local.
- **Mức bằng chứng:** đọc source tĩnh (xác nhận vắng mặt).
- **Giải thích:** **Không có tự động hóa tích hợp/phân phối** (không auto build/lint/test/deploy qua CI). Có script build cục bộ nên không chấm 0 tuyệt đối, nhưng gần như không đáp ứng tiêu chí.

### IV.5 Bảo mật & độ tin cậy — Đề xuất: 1.5/3

- **Bằng chứng:**
  - Bảo vệ dữ liệu: `secure_redaction.py` (ẩn secret/PII trong log/telemetry/bề mặt công khai), resolver secrets `src/eris_secrets.py`, `config/secrets.json`, secret versioning `src/secret_versions.py`.
  - Độ tin cậy: `tts_circuit_breaker.py`, `provider_health.py`, `subsystem_supervisor.py`, `loop_guard.py`, `hardening_*` (baseline/canary/verifier/rollout).
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime.
- **Giải thích:** Có nền bảo mật log/secret tốt và nhiều cơ chế hardening. Nhưng "hệ thống vận hành ổn định và tin cậy" bị hạ bởi loạt lỗi runtime thật trong tri thức (rớt tiếng, mất text, trễ lớn, breaker nuốt exception do unpack sai 5-phần/4-phần — mục 8). Secret được giữ trong `config/secrets.json` local (pool key) — hợp lý cho desktop nhưng cần lưu ý rủi ro lộ key khi đóng gói.

### IV.6 Độ hoàn thiện sản phẩm — Đề xuất: 1.5/3

- **Bằng chứng:** Có đóng gói/triển khai desktop (`installer/`, `eris_setup.py`, Godot export, PyInstaller Manager build — tri thức runtime mục 17 ghi "Godot Windows debug export và PyInstaller Manager build exit 0"). Có `run_smoke_test.bat`, `run_doctor.bat`.
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime (lịch sử).
- **Giải thích:** Đóng gói bài bản. Nhưng "chạy thực tế ổn định, không lỗi nghiêm trọng khi demo" **không được bảo đảm**: tài liệu runtime liên tục kết thúc bằng "chưa mở phiên chat/nghe audio live sau khi sửa", và nhiều lỗi nghiêm trọng (mất tiếng/mất chữ/trễ 70s) có thể lộ ngay khi demo. Rủi ro demo cao.

**Tổng IV (đề xuất): 2.5 + 2 + 2.5 + 0.5 + 1.5 + 1.5 = 10.5/20.**

---

## V. Đóng góp & tính cộng đồng — Đề xuất: 4/10

- **Bằng chứng:** Companion/tutor tiếng Việt, hỗ trợ học tập (tutor role, `LearningService`, mastery/FSRS shadow — `docs/learning-canvas/`), embedding đa ngôn ngữ local (riêng tư, không gửi text đi embed), có hướng accessibility qua voice.
- **Mức bằng chứng:** đọc source tĩnh + tài liệu.
- **Giải thích:** Có tiềm năng tác động (hỗ trợ học, companion tiếng Việt). Nhưng **không tìm thấy bằng chứng về phương án nhân rộng, license mở, hay kế hoạch cộng đồng** (chưa thấy LICENSE cộng đồng rõ, `THIRD_PARTY_NOTICES.md` chỉ là notice). Là app desktop cá nhân một người dùng, khả năng nhân rộng/tiếp cận cộng đồng hiện còn hạn chế và chưa được chứng minh.

## VI. Sử dụng AI tiết kiệm chi phí & hiệu quả — Đề xuất: 6/10

- **Bằng chứng (điểm mạnh thật):**
  - **Pool key xoay vòng free-tier:** `src/llm/key_pool.py` (một index chung cho nhiều mạch, đánh dấu key "chết" khi 429/413/5xx, tự hồi sau cooldown), `elevenlabs_pool_db.py`/`elevenlabs_pool_server.py`, `cloud_keys_pool_db.py`, UI pool (`run_deepseek_pool_ui.bat`, `run_elevenlabs_pool_ui.bat`).
  - **Model rẻ + local:** gateway chỉ dùng `deepseek-flash` (`models.go`); embedding **MiniLM local** (không tốn API); vision qua service local.
  - **Circuit breaker / budget / fallback:** `tts_circuit_breaker.py`, `model_budget_policy.py` (queue/priority/unload VRAM, veto theo CPU/RAM/VRAM), `token_budget.py`, `tts_budget.py`, `provider_health.py`, `speech_provider_chain.py` (fallback TTS ElevenLabs→local).
  - Log `self_component_chars`/`request_size` (token heuristic chars/3) để theo dõi kích thước prompt (mục 31–33).
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime.
- **Giải thích:** Đây là tiêu chí Eris mạnh nhất tương đối: chiến lược "buff free tier" qua pool nhiều key, model rẻ, embedding local, breaker/budget đều **hiện diện thật trong code**. Trừ điểm vì: (1) **không có đo lường chi phí bằng tiền thật** — các con số là heuristic ký tự/token, tri thức runtime nhấn mạnh "không phải usage billing" (mục 25, 27, 31); (2) prompt từng phình tới 1.3M ký tự/lượt (lãng phí token nghiêm trọng) mới được xử lý và **chưa đo lại live**; (3) không có dashboard/report chi phí.

## VII. Ứng dụng công nghệ AWS hoặc Google — Đề xuất: 0.5/10

- **Bằng chứng:**
  - **KHÔNG** có terraform/cloudformation/app.yaml/cloudbuild/serverless (tìm kiếm rỗng).
  - Chỉ có container **local**: `tools/whale2api/{Dockerfile,docker-compose.yml}`, `tools/gemini_vision_docker/{Dockerfile,docker-compose.yml}`.
  - Tri thức runtime mục 9/17: hai container Compose `whale2api`/`poolui` được tạo lại nhưng **"giữ dừng như trước; chưa thử hội thoại live upstream"**.
  - Có đụng Google: `gemini_vision_docker` (Gemini Web), nhưng mục 17 ghi user yêu cầu **bỏ Gemini/Gemma/Groq**, sau đó mục 30 nối lại Gemini Web cho memory qua service local `127.0.0.1:8000`. Đây là gọi API, **không phải deploy app lên GCP**.
- **Mức bằng chứng:** đọc source tĩnh + tri thức runtime (đã đính chính nhiều lần).
- **Giải thích:** **Không có triển khai lên AWS/GCP, không có domain/IP công khai, không cấu hình production cloud, không HTTPS/security group cloud.** Sản phẩm là desktop app chạy localhost. Cho 0.5 vì có container hoá local (tiền đề để deploy) nhưng thực chất **chưa deploy cloud** → gần như không đạt tiêu chí.

## VIII. Làm việc nhóm, thuyết trình, phản biện — KHÔNG CHẤM

- **Không áp dụng cho đánh giá tĩnh codebase.** Tiêu chí này chấm trực tiếp khi thi (teamwork, trình bày, phản biện trước giám khảo), không thể suy từ repo. Không tự chấm; không cộng vào tổng.

---

## BẢNG TỔNG HỢP ĐIỂM

| Phần | Tiêu chí | Đề xuất | Tối đa | Mức bằng chứng |
|---|---|---:|---:|---|
| I | Sáng tạo & đổi mới | 7 | 10 | source tĩnh + thiết kế |
| II | Thực tiễn & khả năng áp dụng | 5 | 10 | source tĩnh (live chưa đạt) |
| III.1 | Dữ liệu | 3.5 | 5 | source tĩnh |
| III.2 | Mô hình | 2 | 5 | source tĩnh (orchestration) |
| III.3 | Rủi ro/An toàn AI/Bias | 3 | 5 | source tĩnh (chưa verify live) |
| III.4 | Chất lượng đầu ra & kiểm thử | 2 | 5 | source + lịch sử (nhiều lỗi) |
| **III** | **Dữ liệu & mô hình** | **10.5** | **20** | |
| IV.1 | Cấu trúc dự án | 2.5 | 3 | source tĩnh |
| IV.2 | FE/UI/UX | 2 | 3 | source tĩnh (UI live chưa rõ) |
| IV.3 | BE & hiệu suất | 2.5 | 5 | source + lịch sử (latency kém) |
| IV.4 | CI/CD & deploy pipeline | 0.5 | 3 | **không có CI** |
| IV.5 | Bảo mật & độ tin cậy | 1.5 | 3 | source + lịch sử |
| IV.6 | Độ hoàn thiện sản phẩm | 1.5 | 3 | source + lịch sử (demo rủi ro) |
| **IV** | **Cấu trúc & hoàn thiện** | **10.5** | **20** | |
| V | Đóng góp & cộng đồng | 4 | 10 | source tĩnh |
| VI | AI tiết kiệm chi phí | 6 | 10 | source tĩnh (không đo $ thật) |
| VII | Cloud AWS/GCP | 0.5 | 10 | **chưa deploy cloud** |
| VIII | Teamwork/thuyết trình | — | (10) | KHÔNG CHẤM (chấm khi thi) |
| **TỔNG (I–VII)** | | **~43.5** | **90** | dải hợp lý **41–47** |

> Dải điểm 41–47/90 phản ánh bất định của đánh giá tĩnh (một số mục như UI/UX, trải nghiệm live có thể cao hơn khi demo thật, hoặc thấp hơn nếu lỗi runtime lộ ra). Nếu quy về thang 100 có cả VIII, cần cộng điểm phần thi trực tiếp (tối đa 10).

---

## ĐIỂM MẠNH

1. **Kiến trúc guard/an toàn nội dung hiếm có:** secret/PII redaction dùng chung (`secure_redaction.py`), grounding/evidence gate chống overclaim, single-speaker authority, language guard chống trôi ngôn ngữ. Đây là thứ phần lớn dự án hackathon không có.
2. **Tối ưu chi phí AI thực chất:** pool key xoay free-tier, model rẻ `deepseek-flash`, embedding MiniLM local, circuit breaker + model budget + fallback.
3. **Phân tách module/tầng tốt:** Python runtime / Godot-C# FE / Go gateway, memory có provenance/admission/scope.
4. **Ý tưởng sản phẩm có chiều sâu:** companion song ngữ VI/JA + Live2D, pacing hội thoại "nghĩ dài nói theo nhịp", tutor role.
5. **Hạ tầng eval có chỉ số:** accuracy/false-pass/false-reject, latency p50/p95, calibration/Brier, golden replay offline.

## ĐIỂM YẾU / RỦI RO CHẤM ĐIỂM

1. **Không có CI/CD** (IV.4) và **không deploy cloud AWS/GCP** (VII) — hai phần đáng ~13 điểm gần như mất trắng. Đây là hai mục dễ mất điểm nhất.
2. **Hiệu suất/độ tin cậy live kém theo chính tài liệu:** latency 15–73s, rớt tiếng, mất chữ, cắt audio. Rủi ro demo cao.
3. **Chưa có test report minh bạch có chỉ số đóng gói;** nhiều suite đang lỗi, Golden Mentor 2/20, "full suite không là green gate".
4. **Thiếu prompt-injection guard và toxicity filter** theo đúng tên tiêu chí III.3 (chỉ có redaction/mask).
5. **Không train/đánh giá mô hình riêng** (III.2) — chỉ orchestrate DeepSeek; khó chứng minh "tái lập kết quả mô hình".
6. **Khả năng nhân rộng cộng đồng chưa chứng minh;** là app desktop đơn người dùng.
7. **Lưu ý minh bạch/phản biện:** gateway từng tự chèn "output integrity note" (đã bỏ) — nếu giám khảo soi, cần giải thích rõ.

## KHUYẾN NGHỊ CẢI THIỆN NHANH TRƯỚC KHI THI

1. **Thêm CI tối thiểu (ưu tiên cao nhất, rẻ):** tạo `.github/workflows/ci.yml` chạy `ruff`/lint + một subset test xanh ổn định (ví dụ suite speech/memory đã pass) + `go test ./...` cho `whale2api`. Chỉ cần badge "build passing" cũng gỡ được phần lớn IV.4.
2. **Deploy một thành phần lên cloud để lấy điểm VII:** đóng gói gateway `whale2api` (đã có Dockerfile) lên **Google Cloud Run** hoặc **AWS ECS/Lambda** với HTTPS + domain công khai. Đây là phần container-ready sẵn, chi phí thấp, lấy được tới 10 điểm VII mà hiện gần như bằng 0.
3. **Viết test report có chỉ số (III.4):** chạy `src/tools/verifier_research.py` + `run_eris_character_eval.py` và xuất một `REPORT.md`: accuracy, false-pass/false-reject, latency p50/p95, retrieval precision; nêu rõ edge cases. Bổ sung một metric retrieval (precision@k) cho memory recall.
4. **Bổ sung prompt-injection guard + toxicity filter (III.3):** thêm một lớp lọc input (phát hiện "ignore previous instructions", role-injection) và một bộ lọc toxicity trước khi public — dù đơn giản cũng khớp đúng chữ trong tiêu chí.
5. **Chuẩn hóa hiệu suất demo (IV.3/IV.6):** đo lại latency sau khi gỡ concept graph; đặt mục tiêu thời-gian-ra-tiếng < vài giây cho demo; chuẩn bị kịch bản demo tránh các path lỗi đã biết (đổi ngôn ngữ giữa lúc đọc, input dồn dập).
6. **Đóng gói chứng minh dữ liệu (III.1):** một trang mô tả nguồn/provenance/admission của memory + khẳng định embedding local (không gửi dữ liệu ra ngoài) để trả lời tiêu chí "minh bạch thu thập/xử lý dữ liệu".
7. **Cộng đồng (V):** thêm LICENSE mở + README hướng dẫn cài đặt + nêu kế hoạch nhân rộng (companion học tập tiếng Việt) để lấy điểm V.

---

## PHỤ LỤC: Danh mục bằng chứng chính (đường dẫn)

- An toàn/guard: `src/runtime/secure_redaction.py`, `grounding_surface_gate.py`, `source_grounding.py`, `capability_claim_guard.py`, `final_speech_authority.py`, `stage_contracts.py`; `src/memory/claim_entailment.py`, `claim_provenance.py`, `memory_admission.py`.
- Chi phí/model: `src/llm/key_pool.py`, `elevenlabs_pool_db.py`, `cloud_keys_pool_db.py`, `src/runtime/model_budget_policy.py`, `tts_circuit_breaker.py`, `token_budget.py`, `speech_provider_chain.py`; `tools/whale2api/internal/config/models.go`.
- Eval/test: `src/evals/run_mentor_eval_v85.py` + `mentor_golden_v85.json`, `src/tools/verifier_research.py`, `run_eris_character_eval.py`, `score_eris_character_eval.py`, `learner_benchmark.py`, `src/experiments/v57_simulation/`.
- Dữ liệu/memory: `src/memory/` (living_user/, embedding_index.py, episodic_memory.py, belief_store.py), `src/paraphrase-multilingual-MiniLM-L12-v2/`.
- FE/UI: `Eris.sln`, `project.godot`, `asset/Resource/Monika.tscn`, `src/body/UdpListener.*.cs`, `src/integration/body_contracts/UdpListener.SettingsPanel.cs`, `tools/ui-preview/`.
- Cấu trúc/build: `src/README_VI.md`, `pyproject.toml`, `pytest.ini`, `installer/`, `eris_setup.py`, build `.bat`.
- CI/Cloud (VẮNG MẶT): không có `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, terraform/cloudformation/app.yaml/cloudbuild/serverless. Container local: `tools/whale2api/`, `tools/gemini_vision_docker/`.
- Tri thức runtime (đối chiếu lịch sử + đính chính): `docs/knowledge/2026-10-14-eris-runtime-lessons.md` (mục 8, 9, 11, 13, 17, 19–33), `AGENTS.md`.

*Mọi nhận định dựa trên đọc source/tài liệu tĩnh tại thời điểm đánh giá; không chạy build/test/live. Nội dung đã được diễn giải lại để tuân thủ nguyên tắc bằng chứng của repo.*
