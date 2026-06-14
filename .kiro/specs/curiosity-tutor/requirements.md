# Requirements Document

## Introduction

ERIS hiện đã có máy phát hiện sai số dự đoán (`SituationModel.observe_and_update` →
`expose_violation()`), nhưng vi phạm kỳ vọng là một **ngõ cụt**: nó được phơi ra cho
downstream đọc rồi thôi. Tò mò không có cửa ra. Đồng thời `SituationModel._make_prediction`
chỉ sinh dự đoán heuristic thuần ("Ngài tiếp tục: <activity>"), nên ERIS không có
*kiến thức thế giới* để dự đoán cho ra hồn — nó bị bất ngờ một cách vô nghĩa và không
học được gì từ cái bất ngờ đó.

Tính năng **Curiosity Tutor (Gia sư Tò mò)** đóng vòng học còn thiếu:
*bị bất ngờ → muốn biết → đi hỏi → tiêu hóa → lần sau hiểu hơn*. Khi một lỗ hiểu biết
(Knowledge_Gap) đủ đáng quan tâm, ERIS hình thành một câu hỏi, **mở một cửa sổ trình
duyệt thật** tới `gemini.google.com` bằng một hồ sơ Google đã đăng nhập sẵn, gõ câu hỏi
*như một con người đang hỏi*, đọc câu trả lời, rồi **chưng cất** câu trả lời thành các
claim đưa vào trí nhớ ngữ nghĩa sẵn có. Body diễn cảnh "ERIS đang hỏi gia sư" để người
xem thấy được hành vi tìm hiểu này.

Hai nguyên tắc bất di bất dịch:

1. **Tiêu hóa, không nhại lại.** Câu trả lời của gia sư KHÔNG bao giờ được ERIS đọc lại
   nguyên văn. Nó đi qua đường commit claim hiện có và chỉ làm giàu *hiểu biết*; tiếng
   nói của ERIS vẫn sinh ra từ cognition của chính nó.
2. **Cô lập khỏi hot path.** Toàn bộ Tutor chạy bất đồng bộ ở một daemon riêng. Lõi chu
   kỳ nhận thức (`CognitivePipeline`/`SituationModel`) giữ nguyên tính tất định; thứ duy
   nhất chảy ngược về là các claim đã được commit.

> **Lựa chọn nền tảng đã chốt:** dùng tự động hóa trình duyệt thật trên
> `gemini.google.com` với tài khoản Google đăng nhập sẵn (không dùng API). Người dùng
> đã chấp nhận rủi ro ToS/khóa tài khoản; các requirement dưới đây *giảm thiểu* rủi ro
> đó (đăng nhập tay một lần, giới hạn nhịp, nhịp gõ giống người, xử lý captcha/hết phiên
> êm) chứ không thể loại bỏ hoàn toàn.

## Glossary

- **Curiosity_Tutor**: Toàn bộ hệ thống đóng vòng tò mò: phát hiện lỗ → cổng tò mò →
  hình thành câu hỏi → hỏi gia sư web → tiêu hóa thành claim → diễn cảnh → phản hồi vào
  dự đoán.
- **Knowledge_Gap**: Một lỗ hiểu biết cụ thể của ERIS, dẫn xuất từ một Expectation_Violation
  (của `SituationModel`) hoặc từ phân loại `unknown` của `BackgroundObserver`
  (`focus_kind="unknown"` / `activity_intent="unknown"`). Gồm: mô tả lỗ, ngữ cảnh tình
  huống, mức liên quan tới stake, và dấu thời gian.
- **Curiosity_Gate**: Bộ quyết định một Knowledge_Gap có đáng đem đi hỏi gia sư hay
  không, dựa trên drive nội sinh, stake relevance, ngân sách và trạng thái rảnh/bận.
- **Tutor_Question**: Câu hỏi văn bản ERIS hình thành từ một Knowledge_Gap để hỏi gia sư.
- **Tutor_Backend**: Lớp trừu tượng đưa Tutor_Question đi và trả Tutor_Answer về. Bản
  hiện thực duy nhất ở phạm vi tính năng này là Gemini_Web_Backend.
- **Gemini_Web_Backend**: Bản hiện thực Tutor_Backend dùng tự động hóa trình duyệt
  (Playwright) điều khiển `gemini.google.com` qua một Browser_Profile đã đăng nhập.
- **Browser_Profile**: Thư mục hồ sơ trình duyệt bền vững (user-data-dir) chứa phiên đăng
  nhập Google, được người dùng đăng nhập **tay một lần**; không bao giờ chứa hay log
  mật khẩu/email trong mã nguồn hay record.
- **Tutor_Answer**: Văn bản câu trả lời ERIS đọc được từ gia sư, kèm nguồn/trích dẫn nếu
  trang có.
- **Knowledge_Claim**: Một mệnh đề tri thức rút từ Tutor_Answer, đưa vào trí nhớ ngữ nghĩa
  qua đường commit claim hiện có, gắn provenance `source="tutor"`.
- **Tutor_Episode**: Một lượt hoàn chỉnh từ lúc chọn Knowledge_Gap đến lúc commit
  Knowledge_Claim (hoặc kết thúc do lỗi/bỏ qua). Đơn vị để log và rate-limit.
- **Tutor_Daemon**: Tiến trình/luồng nền chạy vòng Tutor_Episode, tách khỏi
  `CognitivePipeline`. Họ hàng với `private_mind_daemon`, `private_life_daemon`,
  `background_memory_digest`.
- **Tutor_Stage**: Trạng thái diễn tiến của một Tutor_Episode mà body dùng để vẽ popup:
  một trong {`forming`, `opening`, `asking`, `reading`, `digesting`, `done`, `failed`}.
- **Popup_Event**: Gói UDP runtime→body (cổng 4242) báo Tutor_Stage để body diễn cảnh
  ERIS đang hỏi gia sư.
- **Master_Switch**: Cờ cấu hình tổng bật/tắt toàn bộ Curiosity_Tutor, **mặc định TẮT**.
- **Captcha_Or_Expired**: Trạng thái khi gia sư web yêu cầu captcha, xác minh, hoặc phiên
  đăng nhập đã hết hạn — Gemini_Web_Backend không thể tự vượt qua.
- **Learning_Highlight**: Bản tóm tắt ngắn (gist) điều ERIS vừa học được từ một
  Tutor_Episode — diễn đạt lại của ERIS, KHÔNG phải nguyên văn Tutor_Answer — dùng làm hạt
  giống để ERIS có thể tự nhiên "khoe" qua cognition thường.
- **Share_Impulse**: Một xung nhẹ đẩy Learning_Highlight vào dòng suy nghĩ/agenda nội bộ,
  để vòng autonomous có thể chọn nói về điều vừa học bằng giọng của ERIS.

## Requirements

### Requirement 1: Phát hiện lỗ hiểu biết (Knowledge Gap)

**User Story:** Là người phát triển ERIS, tôi muốn vi phạm kỳ vọng và các tình huống
"không hiểu" được biến thành lỗ hiểu biết cụ thể, để tò mò có một đối tượng rõ ràng để
đi hỏi.

#### Acceptance Criteria

1. WHEN `SituationModel.expose_violation()` trả về một Expectation_Violation, THE Curiosity_Tutor SHALL tạo một Knowledge_Gap gồm mô tả lỗ, ngữ cảnh (prediction kỳ vọng + percept thực tế), và dấu thời gian.
2. WHEN `BackgroundObserver` phát ra một ObserverFrame có `focus_kind="unknown"` HOẶC `activity_intent="unknown"` với `ambiguity` lớn hơn hoặc bằng một ngưỡng cấu hình (mặc định 0.6), THE Curiosity_Tutor SHALL tạo một Knowledge_Gap mô tả tình huống chưa phân loại được.
3. THE Curiosity_Tutor SHALL gắn cho mỗi Knowledge_Gap một giá trị Stake_Relevance trong khoảng đóng [0,1] dẫn xuất từ stake/đột biến liên quan tới lỗ đó.
4. WHERE đã tồn tại một Knowledge_Gap chưa giải quyết có nội dung tương đương ngữ nghĩa với lỗ mới, THE Curiosity_Tutor SHALL gộp (dedupe) thay vì tạo bản trùng, và cập nhật dấu thời gian của lỗ đang tồn tại.
5. THE Curiosity_Tutor SHALL giới hạn hàng đợi Knowledge_Gap ở tối đa một số phần tử cấu hình (mặc định 50), loại bỏ phần tử cũ nhất/ít liên quan nhất khi vượt.

### Requirement 2: Cổng tò mò (Curiosity Gate)

**User Story:** Là người phát triển ERIS, tôi muốn không phải lỗ nào cũng đem đi hỏi, để
ERIS chỉ hỏi khi đáng và khi rảnh, tránh ồn ào và tránh đập vào tài khoản Google liên tục.

#### Acceptance Criteria

1. THE Curiosity_Gate SHALL chỉ cho phép một Tutor_Episode khởi động khi ERIS đang ở trạng thái rảnh (không trong lượt chat chủ động với người dùng).
2. THE Curiosity_Gate SHALL áp một khoảng cách tối thiểu giữa hai Tutor_Episode liên tiếp (rate-limit), giá trị cấu hình mặc định không nhỏ hơn 120 giây.
3. THE Curiosity_Gate SHALL áp một trần số Tutor_Episode mỗi giờ, giá trị cấu hình mặc định không lớn hơn 20.
4. WHEN nhiều Knowledge_Gap cùng đủ điều kiện, THE Curiosity_Gate SHALL chọn lỗ có điểm ưu tiên cao nhất, trong đó điểm ưu tiên là hàm không giảm theo Stake_Relevance và theo độ lớn prediction error của lỗ.
5. IF không Knowledge_Gap nào vượt ngưỡng tò mò cấu hình (mặc định 0.5), THEN THE Curiosity_Gate SHALL không khởi động Tutor_Episode nào trong chu kỳ đó.
6. WHEN một drive nội sinh liên quan (ví dụ `endogenous_drive`/`appetite_system`) ở mức thấp, THE Curiosity_Gate SHALL hạ điểm ưu tiên tương ứng để ERIS không hỏi khi "không buồn tò mò".

### Requirement 3: Hình thành câu hỏi (Tutor Question)

**User Story:** Là người phát triển ERIS, tôi muốn lỗ hiểu biết được chuyển thành một câu
hỏi rõ ràng, để gia sư trả lời trúng cái ERIS thực sự chưa hiểu.

#### Acceptance Criteria

1. WHEN một Knowledge_Gap được Curiosity_Gate chọn, THE Curiosity_Tutor SHALL hình thành đúng một (1) Tutor_Question dạng văn bản có độ dài từ 1 đến 400 ký tự.
2. THE Curiosity_Tutor SHALL hình thành Tutor_Question bằng model nội bộ (local LLM) hoặc heuristic, KHÔNG dùng Tutor_Backend cho việc hình thành câu hỏi.
3. THE Tutor_Question SHALL không chứa thông tin định danh tài khoản (email/tên đăng nhập Google) và không chứa nội dung nhạy cảm của người dùng vượt quá phạm vi cần để hỏi.
4. IF không hình thành được Tutor_Question hợp lệ (rỗng/quá dài/lỗi model), THEN THE Curiosity_Tutor SHALL bỏ qua Knowledge_Gap đó, ghi lý do, và không mở trình duyệt.

### Requirement 4: Gia sư web — tự động hóa Gemini

**User Story:** Là người phát triển ERIS, tôi muốn ERIS mở trình duyệt thật và hỏi
`gemini.google.com` bằng tài khoản đăng nhập sẵn, như một con người đang hỏi, để hành vi
tìm hiểu là thật chứ không phải giả lập.

#### Acceptance Criteria

1. THE Gemini_Web_Backend SHALL dùng một Browser_Profile bền vững (user-data-dir cấu hình) để giữ phiên đăng nhập Google qua các lần chạy, và SHALL KHÔNG lưu hay log mật khẩu, cookie thô, hay địa chỉ email vào bất kỳ record/log nào.
2. WHEN nhận một Tutor_Question, THE Gemini_Web_Backend SHALL điều hướng tới `gemini.google.com`, nhập câu hỏi vào ô nhập, gửi, và đọc Tutor_Answer khi nội dung trả lời đã ổn định (không còn thay đổi trong một khoảng chờ cấu hình).
3. THE Gemini_Web_Backend SHALL nhập câu hỏi theo nhịp giống người (gõ có độ trễ giữa các ký tự + độ trễ ngẫu nhiên có giới hạn trước/sau khi gửi) nhằm giảm khả năng bị nhận diện là tự động.
4. THE Gemini_Web_Backend SHALL áp một timeout tổng cho mỗi Tutor_Episode (mặc định 90 giây); khi vượt timeout, SHALL hủy lượt, trả kết quả thất bại có lý do, và KHÔNG để tiến trình treo.
5. IF gặp Captcha_Or_Expired, THEN THE Gemini_Web_Backend SHALL dừng lượt, KHÔNG thử vượt qua tự động, phát một tín hiệu "cần đăng nhập lại/cần can thiệp", và tạm ngưng các Tutor_Episode mới cho tới khi được người dùng giải quyết hoặc hết một khoảng tạm ngưng cấu hình.
6. THE Gemini_Web_Backend SHALL dùng các selector trang có thể cấu hình (không hardcode rải rác) để khi giao diện Gemini đổi thì chỉnh ở một chỗ.
7. WHILE Master_Switch ở trạng thái tắt, THE Gemini_Web_Backend SHALL không khởi động trình duyệt và không thực hiện bất kỳ truy cập mạng nào.

### Requirement 5: Tiêu hóa tri thức (không nhại lại)

**User Story:** Là người phát triển ERIS, tôi muốn câu trả lời của gia sư được chưng cất
thành hiểu biết của ERIS, để ERIS *biết thêm* chứ không biến thành cái loa phát lại Gemini.

#### Acceptance Criteria

1. WHEN nhận một Tutor_Answer, THE Curiosity_Tutor SHALL trích các Knowledge_Claim qua đường commit claim hiện có (`claim_extractor` → trí nhớ ngữ nghĩa → consolidator), KHÔNG tạo đường lưu trí nhớ song song mới.
2. THE Curiosity_Tutor SHALL gắn cho mỗi Knowledge_Claim provenance `source="tutor"` kèm tham chiếu tới Tutor_Question và (nếu có) trích dẫn nguồn từ Tutor_Answer.
3. THE Curiosity_Tutor SHALL KHÔNG phát Tutor_Answer (nguyên văn hay gần nguyên văn) ra kênh nói public; mọi phát ngôn liên quan phải đi qua cognition thường của ERIS như mọi nội dung khác.
4. WHEN một Tutor_Episode commit thành công ít nhất một Knowledge_Claim, THE Curiosity_Tutor SHALL đánh dấu Knowledge_Gap tương ứng là đã giải quyết và gỡ khỏi hàng đợi.
5. IF Tutor_Answer rỗng hoặc không trích được claim hợp lệ, THEN THE Curiosity_Tutor SHALL kết thúc Tutor_Episode mà không commit gì, giữ Knowledge_Gap ở trạng thái chưa giải quyết, và ghi lý do.

### Requirement 6: Diễn cảnh hỏi gia sư (Body Popup)

**User Story:** Là người dùng, tôi muốn thấy ERIS hiện một cửa sổ nhỏ và đi hỏi gia sư
như con người, để hành vi tò mò có hình hài chứ không chỉ là log.

#### Acceptance Criteria

1. WHEN một Tutor_Episode chuyển Tutor_Stage, THE Curiosity_Tutor SHALL gửi một Popup_Event qua UDP cổng 4242 cho body, gồm Tutor_Stage hiện tại và (khi phù hợp) Tutor_Question rút gọn.
2. THE Popup_Event SHALL nằm trong giới hạn payload UDP hiện có (không vượt `MAX_UDP_PAYLOAD_BYTES`) và mang một định danh loại (ví dụ `parse_mode="tutor_event"`) để body phân biệt với decision nói thường.
3. THE Popup_Event SHALL KHÔNG chứa email/định danh tài khoản Google.
4. WHEN Tutor_Stage đạt `done` hoặc `failed`, THE Curiosity_Tutor SHALL gửi một Popup_Event kết thúc để body đóng/ẩn popup.
5. IF body không phản hồi hoặc UDP gửi lỗi, THEN THE Curiosity_Tutor SHALL vẫn tiếp tục Tutor_Episode (diễn cảnh là phụ, không chặn việc học) và ghi cảnh báo.

### Requirement 7: Phản hồi vào dự đoán

**User Story:** Là người phát triển ERIS, tôi muốn tri thức học được làm dự đoán giàu hơn,
để vòng học thực sự khép: lần sau gặp lại tình huống đó ERIS dự đoán có nội dung thay vì
"Ngài tiếp tục...".

#### Acceptance Criteria

1. WHERE tồn tại Knowledge_Claim liên quan tới tình huống hiện tại trong trí nhớ ngữ nghĩa, THE SituationModel SHALL được phép dùng tri thức đó để sinh mô tả Prediction giàu hơn heuristic mặc định, qua một hook tùy chọn không phá tính tất định của lõi.
2. THE cơ chế phản hồi SHALL chỉ đọc các Knowledge_Claim đã commit (state bền vững), KHÔNG gọi Tutor_Backend hay local LLM bên trong lõi `observe_and_update`.
3. IF không có Knowledge_Claim liên quan, THEN THE SituationModel SHALL giữ nguyên hành vi sinh Prediction heuristic hiện tại.

### Requirement 8: Cô lập lỗi, an toàn và điều khiển

**User Story:** Là người phát triển ERIS, tôi muốn Tutor không bao giờ làm chết runtime
hay đập vào tài khoản ngoài ý muốn, để có thể bật/tắt và quay lui an toàn.

#### Acceptance Criteria

1. THE Curiosity_Tutor SHALL chạy hoàn toàn trong Tutor_Daemon tách khỏi `CognitivePipeline`; một lỗi bất kỳ của Tutor SHALL KHÔNG làm gián đoạn chu kỳ nhận thức, vòng autonomous, hay chat.
2. THE Master_Switch SHALL mặc định TẮT; khi tắt, không Knowledge_Gap nào được xử lý, không daemon nào khởi động trình duyệt.
3. IF Master_Switch vắng mặt hoặc có giá trị không hợp lệ, THEN THE Curiosity_Tutor SHALL coi như TẮT và ghi cảnh báo.
4. THE Tutor_Daemon SHALL có thao tác dừng (stop) sạch: đóng trình duyệt/profile và giải phóng tài nguyên trong một khoảng cấu hình, không để tiến trình con treo.
5. THE Curiosity_Tutor SHALL KHÔNG ghi email, mật khẩu, cookie thô hay nội dung trang đăng nhập vào bất kỳ log/record nào.
6. WHEN Gemini_Web_Backend gặp lỗi liên tiếp vượt một ngưỡng cấu hình (mặc định 3 lần), THE Curiosity_Tutor SHALL tự tạm ngưng các Tutor_Episode mới trong một khoảng cooldown cấu hình và ghi cảnh báo, thay vì thử lại vô hạn.

### Requirement 9: Khả năng quan sát (Observability)

**User Story:** Là người phát triển ERIS, tôi muốn log kể được mỗi lượt gia sư đã hỏi gì,
học được gì, để chẩn đoán hành vi tò mò.

#### Acceptance Criteria

1. WHEN một Tutor_Episode kết thúc, THE Curiosity_Tutor SHALL ghi một record gồm: Knowledge_Gap nguồn, Tutor_Question, kết quả (số Knowledge_Claim commit / lý do bỏ qua), và tổng thời gian — KHÔNG kèm dữ liệu định danh tài khoản.
2. WHEN một Tutor_Episode đổi Tutor_Stage, THE Curiosity_Tutor SHALL ghi mốc chuyển trạng thái để dựng lại được tiến trình.
3. IF một Tutor_Episode thất bại, THEN THE Curiosity_Tutor SHALL ghi nguyên nhân thuộc tập phân loại {timeout, captcha_or_expired, selector_miss, network_error, empty_answer, formulation_failed, gate_rejected}.
4. THE Curiosity_Tutor SHALL phơi một thao tác serialize trạng thái hàng đợi Knowledge_Gap + thống kê episode gần đây cho debug.

### Requirement 10: Chia sẻ điều mới học (Eris khoe)

**User Story:** Là người dùng, tôi muốn thỉnh thoảng nghe ERIS hào hứng kể điều nó vừa
học được, để thấy nó *sống* và *lớn lên*, chứ không chỉ âm thầm tích trữ tri thức.

#### Acceptance Criteria

1. WHEN một Tutor_Episode commit thành công ít nhất một Knowledge_Claim, THE Curiosity_Tutor SHALL tạo một Learning_Highlight là bản diễn đạt lại ngắn (1 đến 200 ký tự) điều vừa học, KHÔNG phải nguyên văn hoặc gần nguyên văn Tutor_Answer.
2. THE Curiosity_Tutor SHALL đẩy Learning_Highlight vào dòng suy nghĩ/agenda nội bộ hiện có (thought stream / internal agenda) dưới dạng một Share_Impulse, KHÔNG phát trực tiếp ra kênh nói public.
3. WHEN vòng autonomous chọn nói về một Share_Impulse, THE phát ngôn SHALL được sinh bởi cognition thường của ERIS (giọng của ERIS), và SHALL KHÔNG chứa nguyên văn hoặc gần nguyên văn Tutor_Answer.
4. THE Curiosity_Tutor SHALL gắn cho mỗi Share_Impulse một mức ưu tiên/độ mới dẫn xuất từ độ liên quan tới stake và độ mới của tri thức so với những gì ERIS đã biết, để tri thức tầm thường hoặc đã biết không tạo xung khoe.
5. THE Curiosity_Tutor SHALL giới hạn tần suất khoe ở tối đa một số lần mỗi cửa sổ thời gian cấu hình (mặc định không quá 1 lần mỗi 10 phút), để ERIS không biến thành kẻ khoe kiến thức liên tục.
6. IF không tạo được Learning_Highlight hợp lệ (rỗng/quá dài/lỗi sinh), THEN THE Curiosity_Tutor SHALL bỏ qua việc khoe cho Tutor_Episode đó mà không ảnh hưởng tới việc đã commit claim.
7. WHILE Master_Switch tắt, THE Curiosity_Tutor SHALL không tạo Share_Impulse nào.

### Requirement 11: Hỏi theo yêu cầu / khi cognition "không chắc"

**User Story:** Là người dùng, tôi muốn khi Eris gặp câu hỏi factual mà nó tự thấy không
chắc (hoặc tôi bảo tra cứu), nó chủ động đi hỏi anh Gemini thay vì bịa tại chỗ.

#### Acceptance Criteria

1. THE Curiosity_Tutor SHALL phơi một API công khai (ví dụ `request_tutor_lookup(topic, *, context, kind_hint, stake)`) để tầng cognition đẩy một Knowledge_Gap "epistemic_uncertainty".
2. WHEN một Knowledge_Gap được đánh dấu `force`, THE Curiosity_Gate SHALL chọn nó để chạy ngay, bỏ qua điều kiện idle và rate-limit, nhưng VẪN tôn trọng tạm ngưng của Risk_Guard (captcha/cooldown).
3. WHEN nhiều Knowledge_Gap `force` cùng tồn tại, THE Curiosity_Gate SHALL chọn cái có điểm ưu tiên cao nhất.
4. THE Curiosity_Tutor SHALL KHÔNG yêu cầu tín hiệu "không chắc" phải đến từ một nguồn cố định; bất kỳ tầng cognition nào gọi API đều kích hoạt được (seam mở).

### Requirement 12: Phân loại tri thức và định tuyến

**User Story:** Là người phát triển ERIS, tôi muốn câu trả lời gia sư được phân loại để
định tuyến đúng: kiến thức xịn thì lưu (embedding), đoán ngữ cảnh/chuyện vui thì chỉ nói
cho vui chứ không nhồi vào trí nhớ dài hạn.

#### Acceptance Criteria

1. WHEN nhận một Tutor_Answer hợp lệ, THE Curiosity_Tutor SHALL phân loại nó thành đúng một KnowledgeKind: `durable`, `context`, hoặc `banter`.
2. WHERE KnowledgeKind là `durable`, THE Curiosity_Tutor SHALL lưu claim vào trí nhớ ngữ nghĩa (có embedding) qua đường commit hiện có và CÓ THỂ khoe như điều đã học.
3. WHERE KnowledgeKind là `context` hoặc `banter`, THE Curiosity_Tutor SHALL KHÔNG lưu vào trí nhớ dài hạn; thay vào đó SHALL đẩy một câu ngắn (diễn đạt lại, không nguyên văn) vào dòng suy nghĩ để Eris nói cho vui / khịa hoặc nêu phỏng đoán ngữ cảnh.
4. WHERE Knowledge_Gap đến từ `observer_unknown`, THE Curiosity_Tutor SHALL mặc định phân loại `context`.
5. IF không có bộ phân loại được cấp, THEN THE Curiosity_Tutor SHALL mặc định coi là `durable` (giữ hành vi cũ).
6. THE bộ phân loại SHALL dùng local LLM với heuristic fallback, KHÔNG dùng Tutor_Backend để phân loại.

### Requirement 13: Không hiểu thì TỰ HỌC; chỉ hỏi lại Ngài khi mơ hồ cá nhân

**User Story:** Là người dùng, tôi KHÔNG muốn phải giải thích kiến thức chung cho Eris
(vd "INTP 538", "Rust"). Nó nên tự tra mà hiểu. Chỉ khi tôi ám chỉ điều riêng tư/mơ hồ
mà không nguồn ngoài nào biết, nó mới nên hỏi lại tôi.

#### Acceptance Criteria

1. WHEN một tin nhắn chat (≥ 3 từ) khiến cognition không phân loại/không hiểu được (meaning rỗng hoặc intent unknown), THE Curiosity_Tutor SHALL mặc định TỰ HỌC: hỏi Gemini âm thầm ở thread nền (có throttle), KHÔNG bắt user giải thích, và Eris vẫn trả lời tự nhiên lượt đó.
2. WHERE tin nhắn là một tham chiếu CÁ NHÂN/mơ hồ ngắn mà chỉ Ngài giải đáp được (ví dụ chứa "vụ đó/cái đó/hôm qua/lúc nãy/ý m là sao" và ngắn), THE Curiosity_Tutor SHALL hỏi lại Ngài: câu trả lời lượt đó thành câu hỏi làm rõ ngắn (giọng Eris), KHÔNG mở trình duyệt.
3. THE nhánh tự-học-Gemini và nhánh hỏi-lại-Ngài SHALL loại trừ nhau cho cùng một tin nhắn.
4. THE việc hỏi Gemini SHALL chạy nền và KHÔNG chặn câu trả lời chat; tri thức học được commit vào trí nhớ (có embedding) để lần sau hiểu mà không phải hỏi lại.
5. WHILE Master_Switch tắt, THE hành vi chat SHALL giữ nguyên như trước (không tự học, không clarify).

