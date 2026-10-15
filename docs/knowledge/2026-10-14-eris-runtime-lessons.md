# Tri thức Eris: bài học từ điều tra runtime và gói rescue

Ngày tổng hợp: **15/10/2026**. Cuộc điều tra được thuật lại chủ yếu liên quan
đến phiên và thay đổi ngày **14/10/2026**.

Mục đích: giúp người/agent tiếp theo hiểu quyết định đã chốt, tránh lặp lại
chẩn đoán sai và biết cần kiểm chứng gì trước khi sửa. Đây là tri thức dự án,
không phải xác nhận Eris đang chạy tốt ở thời điểm đọc.

## 1. Yêu cầu sản phẩm và ưu tiên cần giữ

- **Eris phải có âm thanh khi nói.** User trực tiếp bác phương án chỉ hiện text
  khi dịch lỗi (nguồn dòng 603). Kênh hiển thị tiếng Việt và kênh TTS tiếng Nhật
  có hợp đồng riêng; fallback cần tôn trọng giọng/ngôn ngữ downstream.
- **Giữ cá tính:** hài khô, trêu nhẹ, tự giễu, dỗi nhẹ và quan điểm có chỗ trong
  nhân vật. Đánh giá chúng theo ngữ cảnh và ranh giới thật, tránh tự động gọt
  thành câu trung tính. Điều này không miễn trừ kiểm chứng fact, receipt hoặc
  yêu cầu cụ thể của user.
- **Thinking là lựa chọn theo vai trò và nhiệm vụ.** User quan tâm chiều sâu
  suy nghĩ; gói rescue chọn tối ưu surface writer, không yêu cầu tắt thinking
  toàn hệ thống. Hiệu quả và chất lượng cần đo trên đường chạy thật.
- **Ngôn ngữ chat rất đa dạng:** thiếu dấu, viết hoa, tiếng lóng, teencode,
  tiếng Anh xen tiếng Việt. Search web cũng là năng lực user coi trọng;
  đừng suy ra có search chỉ vì câu trả lời đúng.
- **Giữ phần Live2D theo audio TTS.** User nêu ưu tiên này ở dòng 1901.
  Việc cho phép undo trong lần hợp nhất cũ không phải quyền xóa thay đổi tương
  lai. Quyết định cuối của lần đó giữ Live2D không xung đột rescue tại chỗ.

## 2. Bài học kiến trúc có thể dùng lại

### Lần theo đường chạy thật trước khi sửa prompt

Cá tính, độ trễ và khả năng phát tiếng là kết quả của cả pipeline:
Root → writer → localization → prepare/guards → delivery/TTS, cộng state và
feedback nền. Prompt ủng hộ cá tính vẫn có thể bị verifier một chiều, affect
cold-start hoặc sanitizer làm phẳng. Không suy từ một trace sang kết luận
mọi prompt đều vô can hoặc chỉ có một nguyên nhân.

Phân biệt **vai trò lane**, **model ID**, **thinking** và **search**. Nhiều lane
có thể dùng cùng model. Module được import, config có trường, hay test fixture
có model không chứng minh chức năng được gọi trong production. Kiểm call site,
role thực tế, payload sau override và khả năng gateway đang phục vụ.

### Giữ quyền quyết định và quyền diễn đạt rõ ràng

Root sở hữu ý/hành động của lượt; surface writer diễn đạt move đã chọn.
Localizer chuyển transcript cho TTS. Tối ưu writer không nên âm thầm tạo một
người quyết định nội dung thứ hai hoặc một lane phát lời thứ hai.

Bỏ **root self-verify** khác với bỏ mọi verification. Quyết định rescue là
finalize move trực tiếp, vẫn kiểm preemption/generation và giữ các biên
grounding, action claims, secret redaction, ngôn ngữ và single-speaker.
Observer nhìn lại sau hành động có thể nuôi lượt sau; nó không chặn được câu
sai đã phát ra. Cần kiểm cả đường ghi feedback lẫn đường đọc feedback, không
chỉ thấy observer trả `status=success`.

### Bằng chứng phải độc lập với sự tự tin của model

Không dùng sự tự tin hoặc việc model tự gắn cờ “cần verify” làm lưới duy nhất.
Claim “đã làm” cần receipt thành công của đúng action/run/generation. Fact và
memory cần nguồn đúng scope. Ref tồn tại chỉ chứng minh provenance; vẫn cần
xem nguồn có hỗ trợ chính claim hay không. `claim_manifest=[]` cũng không
chứng minh nội dung cuối không chứa claim.

Ví dụ: evidence `user_statement` chứng minh user **đã nói X**, không tự chứng
minh **X đã xảy ra**. Root.say hoặc văn bản model tự tạo không tự trở thành
receipt. Việc bỏ một verifier chỉ hợp lý sau khi hiểu phần bảo vệ bị mất và
phần nào thực sự được lớp khác đảm nhiệm.

### Fail-soft phải giữ hợp đồng downstream

Trong rescue, localization được chọn theo thứ tự: dịch → retry một lần →
filler Nhật trung tính `えっと…` nếu vẫn lỗi. Cancellation/preemption vẫn dừng
candidate, không retry thành câu cũ. Cần đồng bộ transcript ở cả field phẳng
và nested trước prepare; kiểm output thực tế đi vào TTS.

Filler giữ khả năng có tiếng cho nhánh fallback; **không có nghĩa toàn bộ nội
dung display đã được đọc**, không bảo đảm TTS/delivery luôn thành công. Chỉ
đổi language trong một payload cũng không đủ nếu resolver ép `ja` toàn cục.

### Chẩn đoán và kiểm chứng theo triệu chứng

- Đo từng stage và deadline/budget cha; thời gian tổng writer không phải thời
  gian localizer. Tăng timeout con chưa chứng minh deadline cha cho phép nó.
- Xác định checkout, process/executable và bản runtime đang chạy. Sửa source
  dev không chứng minh bản người dùng mở đã nhận thay đổi.
- Khi quyết định theo role trong async code, kiểm nguồn role production dùng.
  Transcript phát hiện attribute `worker_role` khác ContextVar
  `active_worker_role()`; chép một carve-out cũ có thể tạo fix không tác dụng.
- “Không trả lời” có thể là trễ intake, backchannel bị nuốt, prepare reject,
  preempt hoặc delivery/TTS lỗi. Cần event/trace gốc để phân biệt; đừng vá
  collision guard chỉ vì tên nó có vẻ liên quan.
- Không trộn test counts từ phạm vi khác nhau. Test với fake router chứng minh
  contract được test, chưa chứng minh latency, cảm giác cá tính hay audio live.
- Background lane chạy xong không chứng minh nội dung đúng. Điều tra
  inner/observer/curator theo triệu chứng, thay vì mặc định chúng lỗi hoặc khỏe.
- Bảo vệ thay đổi đang dở. `git diff` và danh sách `status` không lưu nội dung
  file untracked; staged changes và file nhị phân cũng cần cách backup phù hợp.
  Chỉ nói backup đầy đủ khi đã kiểm chứng phạm vi và khả năng khôi phục.

## 3. Bản đồ vai trò để định hướng

Bản đồ sau được tổng hợp từ transcript; cần kiểm lại entry point khi làm việc.
Các tên gọi là vai trò, không phải cam kết model/thinking hiện tại.

| Vai trò/lane | Công việc được mô tả | Điều cần kiểm |
|---|---|---|
| Root / executive | Quyết ý, hành động và lifecycle của lượt | Client, role, payload và preempt thực tế |
| Writer / surface | Diễn đạt move ra lời công khai | Wording giữ intent; thinking sau override |
| Localizer | Chuẩn bị tiếng Nhật cho TTS | Transcript cuối, cancellation và fallback |
| Observer / post_observer | Phân tích kết quả lượt, nuôi feedback | Kết quả được ghi và dùng ở lượt sau |
| Inner | Sinh nội tâm/nhật ký | Chất lượng và cách nội tâm ảnh hưởng lượt sau |
| Seed | Sinh mầm ý/đề xuất nền | Proposal tới Root, không tự có quyền phát lời |
| Critic / deep | Phản biện hoặc suy luận sâu | Call site và nhiệm vụ thực tế |
| Curator | Xây Living User Memory | Admission, provenance và recall đúng |
| Companion routing | Policy chọn năng lực/model dự kiến | Có được gọi và điều khiển request hay chưa |

Trục Root → Writer → Localizer nối tiếp; không diễn giải “nhiều lane” thành
“mọi lane đều chạy song song”. Policy vẫn có thể chọn thinking/tool với một
model; không kết luận companion chỉ có ích khi có nhiều model.

## 4. Trạng thái lịch sử và đối chiếu source ngày tổng hợp

**Báo cáo trong transcript:** rescue có ba commit `ac2a4979`, `14a88d34`,
`8ba9a3b7`; cuối cùng merge dev và copy ba file lõi sang bản chạy. Output test
ba file rescue ghi `16 passed in 1.71s` (1689–1696). Các bộ rộng hơn còn hai lỗi
được báo cáo tái hiện trên base; chưa có user xác nhận chạy thật sau rescue.
Đây là kết quả lịch sử, không phải test đã chạy lại trong lần tổng hợp này.

**Đã đọc source trong checkout hiện tại ngày 15/10/2026, chưa chạy live:**

| Quan sát tĩnh | Nguồn trong repo | Giới hạn |
|---|---|---|
| Root trả `NextConversationMove` trực tiếp sau `still_active()` | [agent.py](../../src/runtime/conversation/agent.py), nhánh finalize | Không chứng minh mọi lượt đã giữ cá tính |
| Writer default thinking disabled; client surface carve-out dùng attribute hoặc ContextVar, env default `1` | [runtime_writer.py](../../src/runtime/conversation/runtime_writer.py), [client.py](../../src/llm/client.py) | Executive carve-out còn đọc attribute; không khẳng định Root OFF live |
| Localize có hai lần thử; cancellation raise; hết retry dùng `えっと…` | [runtime_writer.py](../../src/runtime/conversation/runtime_writer.py), `_prelocalize_v03_speech` | Không xác nhận audio/delivery live; guard kiểm script không chứng minh chất lượng dịch |
| Gateway source chỉ quảng bá `deepseek-flash`, `GetModelConfig` trả search=false | [models.go](../../tools/whale2api/internal/config/models.go) | Không chứng minh gateway binary/process đang chạy trùng checkout |

Phạm vi tổng hợp gồm transcript và đối chiếu một số điểm source. Grounding và
các lane vẫn cần được kiểm tra riêng khi có mục tiêu hoặc triệu chứng cụ thể.

## 5. Những kết luận đã bị sửa hoặc không đủ bằng chứng

| Kết luận cũ | Cách dùng tri thức về sau |
|---|---|
| “Companion đang route Flash/Pro mỗi lượt” | Báo cáo sau nói policy không được gọi trên live chat path; kiểm call site trước |
| “Có Flash-search thật; trả lời đúng PokeMMO chứng minh có search” | Test fixture và câu trả lời đúng không chứng minh có retrieval/citation |
| “Executive chắc chắn thinking OFF” | Phát hiện role ContextVar làm carve-out attribute không hoạt động; không lưu bảng OFF cũ như fact |
| “Gateway ép thinking” | Điều tra sửa thành client Eris ép localhost; kiểm cả payload client và gateway |
| “Localizer mất 11,9s nên vượt timeout 8s” | Đó là thời gian pipeline, chưa phải số đo sub-call |
| “Verify riêng khi model nhận ra fact-claim là đủ” | Model có thể bỏ sót; cần bằng chứng và kiểm nội dung cuối độc lập |
| “Bỏ root self-verify là bỏ toàn bộ lưới chống bịa” | Tách root quality check khỏi các biên public/evidence/action |
| “Fallback đọc Việt / chỉ hiện text là phương án đã chốt” | User bác text-only; phương án cuối giữ JA với retry và filler |
| “Nhanh 1,5–2 lần, hết câm, cá tính trở lại” | Ước lượng/kỳ vọng, chưa có so sánh latency hoặc live confirmation |
| “Thiếu env surface flag thì fix chưa bật” | Source ngày tổng hợp dùng default `1`; vẫn kiểm role và process thực tế |
| “Backup mọi uncommitted đủ 100%” | Lệnh transcript chỉ lưu tracked diff và status; chưa chứng minh lưu untracked |
| “Live2D đã bị undo toàn bộ” | Kế hoạch cuối giữ Live2D không xung đột tại chỗ |
| “Observer success nên khỏe; inner hỏng không ảnh hưởng” | Chưa audit nội dung hoặc downstream impact |
| “Đọc log/sửa inline miễn phí; credit đủ X lượt sửa” | Không phải bằng chứng billing, không lưu như cam kết chi phí |

## 6. Việc còn mở theo bàn giao

Những mục này được transcript để lại, **chưa xác nhận vẫn còn lỗi**:

1. Affect cold-start: đo đầu phiên và phiên đã ấm trước khi tăng sàn playfulness
   hoặc tách quyền hài khô khỏi playful_safety.
2. Companion policy và hằng model mặc định: kiểm đường gọi và gateway capability
   trước khi dọn code hoặc nối routing.
3. Search web: cần khả năng gateway/upstream và request thực tế, không chỉ thêm
   một flag ở client.
4. Inner/observer/curator: chưa audit; chọn điều tra khi có triệu chứng hoặc mục
   tiêu cụ thể, đồng thời kiểm feedback/memory được dùng đúng.
5. Chạy live và đo latency/audio/cá tính: transcript kết thúc trước xác nhận
   này. Kiểm endpoint/process đang phục vụ trước khi kết luận rescue thành công.

Các báo cáo hiện có để tra sâu:

- [Cá tính và flattening](../../.agents/tasks/eris-personality/flattening-report.md).
- [Model routing thực tế](../../.agents/tasks/eris-routing/model-routing-reality.md).
- [Writer/localization failure](../../.agents/tasks/eris-writer-fail/writer-localize-fail-report.md).
- [Intake và lượt bị cho là bỏ qua](../../.agents/tasks/eris-dropped-turn/dropped-user-turn-report.md).
- [Lane và các điểm nối](../../.agents/tasks/eris-lane-map/lane-map-report.md).

Đọc các báo cáo với bảng đính chính ở trên; chúng có thể phản ánh trạng thái
trước rescue. Dev và bản chạy từng là `Documents/GitHub/eris` và
`Documents/eris`; vị trí này là bối cảnh lịch sử, cần xác định lại khi dùng.

## 7. Nguồn và quy tắc cập nhật

Nguồn chính là file user dán, 2.307 dòng:
`C:/Users/Gtvkun/.codex/attachments/a6f2c937-d409-462d-b34b-e4ae52d68139/Văn bản đã dán.txt`.

SHA-256:
`1827B26FD5D3FAAC46456288BA6D2D9A809EAF89E10C778EE3ADCA0EB906F40B`.

Các đoạn nguồn quan trọng: self-verify và phản biện evidence (1–213); writer
fail và yêu cầu audio (418–686); routing bị đính chính (1198–1235); role và JA
fallback (1551–1639); test rescue (1689–1696); giữ thay đổi đang dở và phạm vi
backup (1901–1992); bàn giao và giới hạn live verification (2102–2307).

Khi cập nhật, ghi ngày, nguồn/trace/test mới và kết luận bị thay thế. Giữ
phân biệt: yêu cầu user → quyết định thiết kế → đọc source → test giả lập →
quan sát live. Không nâng một tầng bằng chứng thành tầng cao hơn chỉ vì lời
giải thích nghe chắc chắn.

## 8. Bằng chứng mới: phiên 00:19–00:33 ngày 15/10/2026

Đã đối chiếu run log `eris_run_20261015_001956.txt`, 976 record observability
của phiên và raw wire PID 26564 với source portable `Documents/eris/src`
(các file liên quan trùng byte checkout dev). Chi tiết và giới hạn:
[điều tra agent loop/TTS](2026-10-15-run-agent-loop-tts-audit.md).

- **Thay thế trạng thái “chưa có quan sát live sau rescue” ở mục 4/6 trong
  phạm vi phiên này:** 7 public delivery hoàn tất, 3 bị hủy; có một user turn
  writer_failed do Root local 429 → official 401, surface local cũng 429.
  Không khẳng định rescue thành công toàn diện hoặc không còn lỗi.
- Đoạn cuối Root vẫn `step=1/action=move`. Câu tự nói thêm về tiền điện là
  continuation sau `after=may_continue`; giọng nghiêm của lượt kế tiếp cũng
  do Root chọn. Không có bằng chứng runaway nhiều step hay process tự crash.
- Ba delivery cuối bị hủy trước playback khi message mới được xử lý. “ô”
  không nằm trong backchannel whitelist và pure local probe xác nhận nó hủy
  audio; log `enter_chat_mode` không đủ phân biệt mở ô nhập với xử lý message.
- ElevenLabs có một disconnect thật, Gemini fallback phát xong. **Không nâng
  filler JA của rescue thành bảo đảm mọi câu đều có tiếng:** TTS cancellation
  vẫn bị tính sai thành provider failure trong code; probe xác nhận ba lần
  hủy cùng key có thể mở breaker. Chưa xác nhận breaker mở live trong phiên.
  Metric breaker còn nuốt exception vì key ElevenLabs 5 phần, unpack 4 phần.
- Tám warning `PROVIDER CIRCUIT` về sau thuộc curator timeout khoảng 8s,
  không chứng minh circuit Root chat bị chặn. Raw trace xác nhận Root thinking
  enabled/high, surface disabled. Độ trễ chat 32–37s cuối phiên chưa bao gồm
  tiếng đầu tiên; không quy toàn thời gian đó cho localizer.
- Receipt pending → cancelled làm history projection đổi, gây reconcile lại
  16 entries và phình payload. **Chưa chứng minh** việc này làm lệch câu trả
  lời/cá tính; raw reply vẫn bám input mới. `public_turns=16` không phải 16
  phát ngôn mới hay 16 vòng runaway.

**Bổ sung khi đánh giá cách sửa, nguồn là đọc source ngày 15/10:**
thêm alias backchannel đơn lẻ chưa đủ vì ChatCycle chưa nhận cancel_generation;
bỏ failure khi cancel phải nhả HALF_OPEN permit đúng một lần. Root medium/low
được deepseek.py map thành high, nên đổi knob chưa chứng minh đổi request.
Curator required/concurrency=1 có regression bảo vệ; defer/coalesce cần giữ
evidence, không chuyển thành optional rồi bỏ việc. Degraded Root vẫn nhờ writer
generate nên thay `say` thành câu báo lỗi chưa tự tạo fail-soft độc lập LLM.
Chi tiết nằm trong mục 6 của báo cáo điều tra. Các nhận định này bổ sung giới
hạn của hướng sửa, chưa thay thế quan sát live bằng test hoặc phỏng đoán.

Đây là cập nhật tri thức/chẩn đoán; chưa sửa hoặc triển khai runtime mới.

## 9. Thay đổi transport/prompt DeepSeek ngày 15/10/2026

Theo yêu cầu mới của user, source gateway `tools/whale2api` đã bỏ hai hành vi:

- Tự đưa context hội thoại vào file `.txt`, rồi thay phần chat bằng câu tiếp tục
  tổng quát. Chat Completions và Responses nay giữ toàn bộ system, user,
  assistant và tool history trong `prompt` dạng text trực tiếp, kể cả khi
  cấu hình cũ `current_input_file.enabled=true`. Bỏ cả upload lại context khi
  đổi account và khoản token dự phòng cho file context tự tạo. File do caller
  chủ động gửi vẫn theo đường upload riêng. Kết quả tool trong prompt giữ
  `name`/`tool_call_id` nếu có, để kết quả liền nhau vẫn nhận diện được.
- Tự chèn toàn bộ `Output integrity note`, gồm câu yêu cầu detector bỏ qua kiểm
  tra và đoạn hướng dẫn output đi kèm. System prompt của caller và định dạng
  role/tool vẫn được giữ; không lọc/xóa các câu tương tự do caller tự gửi.

Nguồn: diff source gateway và regression test trực tiếp payload upstream.
Đây là quyết định sản phẩm mới, thay thế hành vi transport/prefix trước đó;
không phải bằng chứng các chẩn đoán về cá tính, latency hoặc TTS đã được sửa.
Test giả lập không xác nhận phản hồi live của DeepSeek.

Kiểm chứng sau sửa: `go test ./... -count=1` trong `tools/whale2api` qua toàn bộ;
regression bao gồm stream/nonstream, legacy config bật, file caller chủ động
gửi và nhiều kết quả tool khác thứ tự. Đã biên dịch mới hai binary Linux từ
source này, đóng gói trên base image local cũ và kiểm SHA-256 trùng binary
trong image. Smoke container với `--network none` trả `/healthz` status `ok`.
Hai container Compose `whale2api`/`poolui` đã được tạo lại với image mới và giữ
dừng như trước; chưa thử hội thoại live upstream. Image cũ được giữ tại tag
`eris-whale2api-backup:before-plain-text-20261015` để có thể khôi phục.

## 10. Bằng chứng mới: phiên 16:47–16:54 ngày 15/10/2026

Đối chiếu run log `eris_run_20261015_164726.txt`, 350 record observability
(dòng 494361–494710) và raw HTTP PID 6980. Chi tiết:
[điều tra agent loop phiên 16:47](2026-10-15-1647-agent-loop-audit.md).

- **Xác nhận lỗi tiến độ trong phiên này:** user yêu cầu năm chủ đề/năm lượt;
  chỉ lượt 1/5 delivered. Root vẫn sinh lần lượt 2/5, 3/5, 4/5, 5/5 dù cả bốn
  writer candidate đều bị prepare từ chối. Câu “Hết 5 lượt” nằm trong bản
  định nói, không phải lời đã phát thành công.
- **Xác định thêm đường gây câm sau localization:** cả sáu raw writer reply
  đã có speech Nhật. `IntentionObserver` gộp whitespace/cắt display còn 360
  ký tự nhưng trả `rewritten=False`. Stage nhánh autonomous thấy text khác
  và ghi đè speech bằng bản Việt; prepare sau đó chặn language mismatch.
  Lời chào cũng hỏng cùng cách; lượt chat bỏ qua nhánh đó nên thành công.
  Probe offline với sáu payload thật: chat qua 6/6, autonomous bị chặn 6/6;
  source liên quan đã đối chiếu trùng byte bản portable.
- Root session lưu quyết định move trước writer/delivery, nhưng các request
  tiếp theo không có feedback về lỗi prepare vừa xảy ra. Delta delivery lấy
  từ public history nên không bao phủ lỗi trước dispatch. Cần phân biệt
  quyết định định nói với lượt delivered khi theo dõi kế hoạch nhiều lượt.
- Đây là các `autonomous_signal` từ timer với `step=1`, tất cả move dùng
  `after=wait_user`; không phải chuỗi `continuation_due` hay nhiều step
  runaway trong một run. `wait_user` hủy continuation lease, không tự chứng
  minh autonomous timer bị dừng. Ba timer đầu chọn chờ, rồi Root tự đổi sang
  nói tiếp dù không có user turn mới.
- Format `attempt=1/2` còn sót; writer hiện chỉ generate một lần. Không dùng
  dòng này làm bằng chứng có retry writer. Retry localization là cơ chế khác.

**Kết luận được bổ sung/thu hẹp:** không áp nguyên nhân cancellation/429 của
phiên 00:19 lên phiên mới, và không coi fail-soft localizer là bảo đảm toàn
pipeline có tiếng. Phiên này có Root/surface HTTP 200, một audio phát xong;
năm failure nằm trước delivery. Không có bằng chứng process crash hoặc
gateway plain-text gây lỗi này. Đây vẫn là cập nhật chẩn đoán, chưa sửa hay
triển khai runtime.
