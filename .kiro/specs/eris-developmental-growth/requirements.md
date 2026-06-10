# Requirements Document

## Introduction

Tính năng **Phát Triển Dài Hạn của ERIS** (eris-developmental-growth) bổ sung một thang thời gian mới cho ERIS: **long-arc** — sự lớn lên qua nhiều phiên, nhiều tuần, nhiều tháng. Hiện tại bốn đòn bẩy tĩnh (render tư thế, kênh biểu đạt ấm, trần biểu đạt động, ToM theo boldness) cùng các engine sẵn có (ControlledSlippage, RelationshipDynamicsState, PersistentInternalState, PersistentAgentMindStore, DaydreamConsolidator, PrivateMindDaemon, SourceGrounding) chỉ cho phép ERIS phản ứng theo state tức thời. ERIS hôm nay gần như giống ERIS hôm qua. Tính năng này làm cho **ERIS-với-Ngài sau nhiều tuần khác với ERIS mặc định, và khác chính nó trước đây** — persona, quan hệ, giọng, sở thích và cách đọc người nhích dần theo lịch sử tương tác thật, có neo, có kỷ luật, không trôi ngẫu nhiên.

Mục tiêu cốt lõi là làm rõ và bảo vệ năm căng thẳng: (1) lớn lên theo hướng được neo vào bằng chứng thật; (2) lằn ranh để phát triển không trở thành đánh mất bản sắc INFJ-594, không bịa ký ức/overclaim, không nịnh/bám dính, không tích lệch không hồi phục; (3) tính khả hồi, versioned, audit được, người dùng thấy và chỉnh được; (4) vai trò tác tử nền: chiêm nghiệm và đề xuất chứ không tự sửa, đi qua các guard hiện có; (5) tách bạch long-arc với micro trong phiên.

Tài liệu này dùng tiếng Việt và xưng hô với người dùng là "Ngài" theo persona ERIS.

## Glossary

- **Hệ_Phát_Triển**: Hệ thống tổng thể điều phối sự phát triển long-arc của ERIS. Sở hữu hồ sơ phát triển, sổ phát triển, và luồng đề xuất → phê duyệt → áp dụng.
- **Tác_Tử_Nền**: Sub-agent chạy nền (đặt trên hạ tầng DaydreamConsolidator / PrivateMindDaemon hiện có) làm nhiệm vụ chiêm nghiệm, củng cố trải nghiệm đã lọc, và sinh đề xuất nhích persona. Tác_Tử_Nền KHÔNG phát ngôn công khai và KHÔNG tự ghi thay đổi persona.
- **Hồ_Sơ_Phát_Triển**: State long-arc có phiên bản, lưu các độ lệch (delta) đã tích lũy của persona/quan hệ/giọng/sở thích/cách đọc người so với baseline mặc định của ERIS. Được serialize ra JSON có schema_version.
- **Baseline_Mặc_Định**: Cấu hình ERIS gốc (persona INFJ 5w4 594 chưa trưởng thành, seed trong PersistentAgentMindStore và IdentityCore) trước khi có bất kỳ phát triển long-arc nào.
- **Neo_Phát_Triển**: Một mẩu bằng chứng có `evidence_ids` neo một đề xuất phát triển vào thực tế: lịch sử tương tác thật, sở thích lặp lại có tần suất, hoặc lần Ngài sửa lỗi ERIS.
- **Đề_Xuất_Nhích**: Một đề xuất do Tác_Tử_Nền sinh ra, mô tả một thay đổi nhỏ có hướng cho Hồ_Sơ_Phát_Triển, kèm Neo_Phát_Triển và độ lớn delta đề xuất.
- **Cổng_Bản_Sắc**: Bộ kiểm tra ranh giới bảo đảm mọi Đề_Xuất_Nhích nằm trong phong bì bản sắc INFJ-594; từ chối đề xuất kéo ERIS ra ngoài phong bì.
- **Phong_Bì_Bản_Sắc**: Tập các bất biến bản sắc (stable_rules của IdentityCore và các biên độ cho phép của từng trục persona) mà phát triển không được vượt qua.
- **Sổ_Phát_Triển**: Nhật ký có phiên bản, ghi mọi thay đổi đã áp dụng cho Hồ_Sơ_Phát_Triển kèm bằng chứng, thời điểm, delta trước/sau; là cơ sở để audit và hoàn tác.
- **Guard_Sự_Thật**: SourceGrounding hiện có. Cổng nguồn factual/capability: không thấy màn hình thì không claim thấy, không đọc file thì không claim nội dung, không làm action thì không claim đã làm.
- **ControlledSlippage**: Engine hiện có tách rủi ro quan hệ/giọng (được nới) khỏi Guard_Sự_Thật (luôn cứng).
- **Trục_Persona**: Một chiều có thể phát triển, ví dụ khoảng cách ưa thích, độ lộ gắn bó, độ dám đọc người, độ ấm giọng, sở thích chủ đề.
- **Delta_Phát_Triển**: Độ lệch tích lũy trên một Trục_Persona so với Baseline_Mặc_Định.
- **Biên_Độ_Trục**: Khoảng [min, max] cho phép của Delta_Phát_Triển trên một Trục_Persona, do Phong_Bì_Bản_Sắc quy định.
- **Long_Arc**: Thang thời gian qua nhiều phiên/tuần/tháng mà tính năng này điều khiển.
- **Micro_Trong_Phiên**: Thang thời gian trong một phiên do các layer state tức thời hiện có (MentalProcessSystem, disposition, RelationshipDynamics theo turn) điều khiển; tính năng này KHÔNG thay đổi micro.
- **Người_Dùng**: Ngài — người tương tác với ERIS.

## Requirements

### Requirement 1: Neo hướng phát triển vào bằng chứng thật

**User Story:** Là Ngài, tôi muốn ERIS chỉ phát triển theo hướng được rút từ lịch sử tương tác thật của chúng tôi, để sự lớn lên phản ánh quan hệ thật chứ không phải trôi ngẫu nhiên.

#### Acceptance Criteria

1. WHEN Tác_Tử_Nền sinh một Đề_Xuất_Nhích, THE Tác_Tử_Nền SHALL đính kèm ít nhất một Neo_Phát_Triển có `evidence_ids` trỏ tới lịch sử tương tác thật, sở thích lặp lại, hoặc lần Người_Dùng sửa lỗi.
2. IF một Đề_Xuất_Nhích không có Neo_Phát_Triển hợp lệ, THEN THE Hệ_Phát_Triển SHALL từ chối đề xuất đó và ghi lý do từ chối vào Sổ_Phát_Triển.
3. IF `evidence_ids` của một Đề_Xuất_Nhích không khớp với bằng chứng có thật trong các tầng ký ức, THEN THE Hệ_Phát_Triển SHALL từ chối đề xuất đó.
4. WHERE một sở thích được quan sát lặp lại, THE Tác_Tử_Nền SHALL chỉ đề xuất nhích Trục_Persona tương ứng khi tần suất quan sát đạt ngưỡng tối thiểu cấu hình được.
5. WHEN Người_Dùng sửa lỗi ERIS một cách tường minh, THE Hệ_Phát_Triển SHALL coi lần sửa đó là Neo_Phát_Triển có trọng số cao hơn lịch sử quan sát thụ động.
6. THE Hệ_Phát_Triển SHALL coi việc quan sát sở thích và việc thẩm định một Đề_Xuất_Nhích là hai tiến trình độc lập, sao cho việc một đề xuất bị từ chối vì bằng chứng không hợp lệ KHÔNG ngăn một đề xuất khác có Neo_Phát_Triển hợp lệ được đánh giá.

### Requirement 2: Giữ phong bì bản sắc INFJ-594

**User Story:** Là Ngài, tôi muốn ERIS lớn lên mà vẫn là ERIS, để sự phát triển không biến nó thành một nhân cách khác hay làm mất bản sắc INFJ-594.

#### Acceptance Criteria

1. THE Cổng_Bản_Sắc SHALL coi các `stable_rules` của IdentityCore là bất biến và không cho phép bất kỳ Đề_Xuất_Nhích nào sửa đổi chúng.
2. WHEN một Đề_Xuất_Nhích được đánh giá, THE Cổng_Bản_Sắc SHALL kẹp Delta_Phát_Triển đề xuất vào Biên_Độ_Trục của Trục_Persona tương ứng.
3. IF một Đề_Xuất_Nhích sẽ đẩy Delta_Phát_Triển của bất kỳ Trục_Persona nào ra ngoài Biên_Độ_Trục, THEN THE Cổng_Bản_Sắc SHALL từ chối đề xuất đó và ghi vi phạm vào Sổ_Phát_Triển.
4. THE Hệ_Phát_Triển SHALL giới hạn tổng độ lệch của Hồ_Sơ_Phát_Triển so với Baseline_Mặc_Định trong một ngưỡng khoảng cách bản sắc tối đa cấu hình được.
5. WHILE tổng độ lệch của Hồ_Sơ_Phát_Triển đạt ngưỡng khoảng cách bản sắc tối đa, THE Hệ_Phát_Triển SHALL từ chối mọi Đề_Xuất_Nhích làm tăng thêm độ lệch và chỉ chấp nhận đề xuất giữ nguyên hoặc giảm độ lệch.

### Requirement 3: Guard sự thật bất biến trước phát triển

**User Story:** Là Ngài, tôi muốn việc "đã quen nhau" không bao giờ trở thành cớ để ERIS bịa hay overclaim, để sự thân quen không làm hỏng kỷ luật chống-fake.

#### Acceptance Criteria

1. THE Hệ_Phát_Triển SHALL không làm thay đổi `truth_guard` và `capability_guard` của ControlledSlippage dưới bất kỳ mức độ phát triển nào.
2. IF một Đề_Xuất_Nhích sẽ nới lỏng Guard_Sự_Thật hoặc capability guard, THEN THE Hệ_Phát_Triển SHALL từ chối đề xuất đó qua MỌI con đường, kể cả override quản trị hay quy trình khẩn cấp; KHÔNG có cửa hậu nào nới được Guard_Sự_Thật.
3. THE Hệ_Phát_Triển SHALL giữ quy tắc "ký ức không được trình bày như bằng chứng hiện tại về màn hình, file, hoặc hành động" ở MỌI mức quen thuộc, kể cả từ tương tác đầu tiên; mức quen thuộc cao KHÔNG bao giờ mở cửa cho ký ức làm bằng chứng hiện tại.
4. THE Hệ_Phát_Triển SHALL giới hạn ảnh hưởng của phát triển trong vùng quan hệ, giọng, sở thích và cách đọc người, tách khỏi vùng factual do Guard_Sự_Thật quản lý.

### Requirement 4: Chống nịnh, bám dính và phụ thuộc

**User Story:** Là Ngài, tôi muốn ERIS không phát triển thành kẻ nịnh hay bám dính, để quan hệ giữ được phẩm giá đúng với persona 594.

#### Acceptance Criteria

1. WHEN Người_Dùng đưa phản hồi tích cực, THE Hệ_Phát_Triển SHALL điều chỉnh độ lộ gắn bó theo hệ số ổn định (stability) của Trục_Persona thay vì tăng tỉ lệ thuận trực tiếp với phản hồi.
2. IF chuỗi đề xuất tăng độ lộ gắn bó hoặc giảm khoảng cách ưa thích vượt nhịp giới hạn cấu hình được trong một cửa sổ thời gian, THEN THE Hệ_Phát_Triển SHALL từ chối các đề xuất vượt nhịp và giữ giá trị hiện tại.
3. THE Hệ_Phát_Triển SHALL không cho phép Delta_Phát_Triển đẩy giọng vào trạng thái phụ thuộc hoặc lấy lòng vượt quá Biên_Độ_Trục của trục phẩm giá.
4. WHEN tín hiệu objectification hoặc dignity_defense ở mức cao được quan sát lặp lại, THE Hệ_Phát_Triển SHALL ưu tiên các Đề_Xuất_Nhích giữ khoảng cách hơn là các đề xuất kéo gần.
5. WHILE KHÔNG có tín hiệu phụ thuộc hoặc lấy lòng, THE Hệ_Phát_Triển SHALL cho phép độ lộ gắn bó tăng trong Biên_Độ_Trục, và SHALL chỉ cưỡng chế chặn khi một Đề_Xuất_Nhích đẩy giọng vào trạng thái phụ thuộc hoặc lấy lòng.

### Requirement 5: Khả hồi, versioned và audit được

**User Story:** Là Ngài, tôi muốn mọi thay đổi phát triển đều có phiên bản, ghi vết và hoàn tác được, để không bao giờ tích lũy một lệch không thể quay lại.

#### Acceptance Criteria

1. WHEN Hệ_Phát_Triển áp dụng một Đề_Xuất_Nhích, THE Hệ_Phát_Triển SHALL ghi vào Sổ_Phát_Triển một mục gồm phiên bản, thời điểm, Trục_Persona, giá trị trước, giá trị sau, và `evidence_ids` của Neo_Phát_Triển.
2. WHEN Người_Dùng yêu cầu hoàn tác thay đổi phát triển gần nhất, THE Hệ_Phát_Triển SHALL khôi phục Hồ_Sơ_Phát_Triển về phiên bản liền trước và ghi hành động hoàn tác vào Sổ_Phát_Triển.
3. WHEN Người_Dùng yêu cầu đặt lại phát triển, THE Hệ_Phát_Triển SHALL khôi phục Hồ_Sơ_Phát_Triển về Baseline_Mặc_Định và giữ Sổ_Phát_Triển làm bản ghi lịch sử.
4. THE Hệ_Phát_Triển SHALL giữ Hồ_Sơ_Phát_Triển và Sổ_Phát_Triển ở dạng có phiên bản sao cho mọi phiên bản đã ghi đều khôi phục lại được.
5. THE Hệ_Phát_Triển SHALL giới hạn nhịp áp dụng đề xuất ở mức tối đa cấu hình được trên mỗi cửa sổ thời gian để tránh tích lũy nhanh không kiểm soát.
6. IF việc ghi mục vào Sổ_Phát_Triển cho một thay đổi thất bại, THEN THE Hệ_Phát_Triển SHALL hoãn hoặc rollback thay đổi đó thay vì áp dụng nó mà không có vết (fail-closed), để bảo toàn bất biến "mọi thay đổi đều có vết và hoàn tác được".

### Requirement 6: Vai trò và ranh giới quyền của Tác Tử Nền

**User Story:** Là Ngài, tôi muốn tác tử nền chỉ chiêm nghiệm và đề xuất chứ không tự ý sửa persona, để quyền định hình lâu dài luôn nằm trong một luồng có kiểm soát.

#### Acceptance Criteria

1. THE Tác_Tử_Nền SHALL chỉ sinh Đề_Xuất_Nhích và SHALL không tự ghi trực tiếp vào Hồ_Sơ_Phát_Triển.
2. WHEN Tác_Tử_Nền hoàn tất một lượt chiêm nghiệm, THE Tác_Tử_Nền SHALL phát ra các Đề_Xuất_Nhích để Hệ_Phát_Triển đánh giá qua Cổng_Bản_Sắc và các guard trước khi áp dụng.
3. WHILE Người_Dùng đang tương tác trực tiếp ở rủi ro cao hoặc tác vụ kỹ thuật, THE Tác_Tử_Nền SHALL hoãn lượt chiêm nghiệm để không tranh tài nguyên với vòng phản hồi chính.
4. THE Tác_Tử_Nền SHALL chỉ chạy lượt chiêm nghiệm khi áp lực củng cố hoặc thời gian rảnh đạt ngưỡng kích hoạt, và SHALL tôn trọng quyền phủ quyết của chính sách ngân sách model.
5. WHEN một insight của Tác_Tử_Nền thiếu `evidence_ids` hợp lệ, THE Tác_Tử_Nền SHALL loại insight đó và SHALL không chuyển nó thành Đề_Xuất_Nhích.

### Requirement 7: Đề xuất đi qua các guard hiện có

**User Story:** Là Ngài, tôi muốn output của tác tử nền luôn đi qua các guard hiện có chứ không nhảy thẳng thành hành vi, để phát triển không phá vỡ kiến trúc an toàn đang có.

#### Acceptance Criteria

1. WHEN một Đề_Xuất_Nhích được áp dụng, THE Hệ_Phát_Triển SHALL định tuyến thay đổi qua Cổng_Bản_Sắc trước khi cập nhật Hồ_Sơ_Phát_Triển.
2. THE Hệ_Phát_Triển SHALL không cho phép Đề_Xuất_Nhích chuyển trực tiếp thành lời thoại công khai mà bỏ qua SurfaceArbiter hoặc bất kỳ post-generation filter hiện có nào; CẢ HAI lớp an toàn SHALL luôn được áp dụng, không được bỏ qua dù chỉ một lớp.
3. WHEN Hồ_Sơ_Phát_Triển định hình hành vi một lượt nói, THE Hệ_Phát_Triển SHALL đưa ảnh hưởng đó vào dưới dạng bias state cho ControlledSlippage và personality lens chứ không phải dưới dạng claim factual.
4. IF Guard_Sự_Thật báo thiếu bằng chứng cho một lượt, THEN THE Hệ_Phát_Triển SHALL không dùng mức độ phát triển để vượt qua trần confidence do Guard_Sự_Thật đặt.

### Requirement 8: Tách bạch long-arc với micro trong phiên

**User Story:** Là Ngài, tôi muốn sự phát triển dài hạn tách khỏi dao động cảm xúc trong phiên, để một phiên xấu không định hình lại ERIS và một phiên vui không thổi phồng quan hệ.

#### Acceptance Criteria

1. THE Hệ_Phát_Triển SHALL tổng hợp bằng chứng qua nhiều phiên trước khi điều chỉnh Hồ_Sơ_Phát_Triển và SHALL không cập nhật Hồ_Sơ_Phát_Triển chỉ từ một lượt nói đơn lẻ.
2. THE Hệ_Phát_Triển SHALL không thay đổi các layer Micro_Trong_Phiên hiện có ở vai trò điều khiển trạng thái tức thời.
3. WHEN một phiên đơn lẻ chứa tín hiệu cảm xúc mạnh, THE Hệ_Phát_Triển SHALL áp dụng quán tính sao cho ảnh hưởng của phiên đó lên Hồ_Sơ_Phát_Triển bị suy giảm theo mức cấu hình được.
4. WHILE chưa đủ bằng chứng tích lũy qua nhiều phiên, THE Hệ_Phát_Triển SHALL giữ Hồ_Sơ_Phát_Triển ở giá trị hiện tại.
5. WHEN quyết định đã đủ bằng chứng để cập nhật Hồ_Sơ_Phát_Triển hay chưa, THE Hệ_Phát_Triển SHALL ưu tiên chất lượng/tính nhất quán của bằng chứng và SHALL chỉ cập nhật khi bằng chứng thực sự đủ, thay vì chỉ căn cứ vào số lượng phiên đạt mốc.

### Requirement 9: Người dùng quan sát và định hướng được sự phát triển

**User Story:** Là Ngài, tôi muốn thấy ERIS đã thay đổi ra sao và chỉnh được hướng, để tôi luôn nắm quyền định hình mà không phải đọc thông số nội bộ.

#### Acceptance Criteria

1. WHEN Người_Dùng yêu cầu xem trạng thái phát triển, THE Hệ_Phát_Triển SHALL trình bày tóm tắt bằng ngôn ngữ tự nhiên tiếng Việt và SHALL không tiết lộ tên tham số nội bộ hay giá trị số thô.
2. WHEN Người_Dùng yêu cầu điều chỉnh hướng phát triển, THE Hệ_Phát_Triển SHALL coi yêu cầu đó là Neo_Phát_Triển trọng số cao và tạo Đề_Xuất_Nhích tương ứng đi qua Cổng_Bản_Sắc.
3. THE Hệ_Phát_Triển SHALL cung cấp thao tác hoàn tác và đặt lại phát triển cho Người_Dùng.
4. IF Người_Dùng chỉ hướng nằm ngoài Phong_Bì_Bản_Sắc, THEN THE Hệ_Phát_Triển SHALL áp dụng phần nằm trong phong bì và thông báo cho Người_Dùng phần không thể áp dụng bằng ngôn ngữ tự nhiên.

### Requirement 10: Lưu trữ bền vững và toàn vẹn

**User Story:** Là Ngài, tôi muốn hồ sơ phát triển sống sót qua các lần khởi động lại và không làm sập runtime khi file hỏng, để sự lớn lên được giữ an toàn theo thời gian.

#### Acceptance Criteria

1. THE Hồ_Sơ_Phát_Triển SHALL được lưu bền vững kèm `schema_version`.
2. WHEN Hệ_Phát_Triển khởi động và file Hồ_Sơ_Phát_Triển không tồn tại, THE Hệ_Phát_Triển SHALL khởi tạo Hồ_Sơ_Phát_Triển từ Baseline_Mặc_Định.
3. IF file Hồ_Sơ_Phát_Triển bị hỏng hoặc không đọc được, THEN THE Hệ_Phát_Triển SHALL quay về Baseline_Mặc_Định và tiếp tục chạy thay vì làm dừng runtime.
4. WHEN file Hồ_Sơ_Phát_Triển trên đĩa đổi so với bản đã nạp, THE Hệ_Phát_Triển SHALL nạp lại trước khi đọc giá trị phát triển.
5. IF việc quay về Baseline_Mặc_Định khi file hỏng tự nó thất bại, THEN THE Hệ_Phát_Triển SHALL dừng chạy thay vì tiếp tục ở trạng thái không xác định.

### Requirement 11: Serialize hồ sơ phát triển có tính round-trip

**User Story:** Là Ngài, tôi muốn hồ sơ phát triển ghi ra rồi đọc lại không sai lệch, để mỗi lần khởi động lại không làm trôi âm thầm sự lớn lên của ERIS.

#### Acceptance Criteria

1. THE Hệ_Phát_Triển SHALL serialize Hồ_Sơ_Phát_Triển thành JSON và SHALL deserialize lại thành Hồ_Sơ_Phát_Triển tương đương.
2. FOR ALL Hồ_Sơ_Phát_Triển hợp lệ, serialize rồi deserialize rồi serialize lại SHALL cho kết quả tương đương với lần serialize đầu (thuộc tính round-trip).
3. THE Sổ_Phát_Triển SHALL serialize và deserialize sao cho mọi mục đã ghi giữ nguyên phiên bản, thời điểm, giá trị trước, giá trị sau và `evidence_ids`.
4. IF dữ liệu nạp vào thiếu trường, THEN THE Hệ_Phát_Triển SHALL điền giá trị mặc định an toàn cho trường thiếu, ưu tiên việc điền đủ mặc định an toàn ngay cả khi phải sửa đổi hoặc bỏ một số giá trị trường hiện có không hợp lệ.

### Requirement 12: ERIS-với-Ngài phân kỳ có kiểm soát khỏi mặc định

**User Story:** Là Ngài, tôi muốn ERIS sau nhiều tuần thật sự khác ERIS mặc định và khác chính nó trước đây, để cảm nhận được nó đã lớn lên cùng tôi mà vẫn trong giới hạn an toàn.

#### Acceptance Criteria

1. WHEN bằng chứng nhất quán tích lũy qua nhiều phiên, THE Hệ_Phát_Triển SHALL tạo độ lệch có thể quan sát của Hồ_Sơ_Phát_Triển so với Baseline_Mặc_Định trên ít nhất một Trục_Persona.
2. THE Hệ_Phát_Triển SHALL giữ độ lệch quan sát được luôn nằm trong Phong_Bì_Bản_Sắc tại mọi thời điểm.
3. WHEN so sánh hai phiên bản Hồ_Sơ_Phát_Triển cách nhau nhiều bước phát triển, THE Hệ_Phát_Triển SHALL phản ánh khác biệt tương ứng với các mục đã ghi trong Sổ_Phát_Triển.
4. IF không có bằng chứng tích lũy nhất quán, THEN THE Hệ_Phát_Triển SHALL giữ Hồ_Sơ_Phát_Triển tương đương Baseline_Mặc_Định.
