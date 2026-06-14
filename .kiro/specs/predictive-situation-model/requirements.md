# Requirements Document

## Introduction

Hiện tại ERIS không có "world model" thật. Cái đang được gọi là "novelty" trong `AttentionSalienceEngine._novelty_score()` chỉ là một bảng tra cứu dựa trên `repeat_count` và `age_seconds`: thứ gì chưa thấy gần đây thì điểm cao, thấy nhiều lần thì điểm thấp. "Mới" do đó chỉ có nghĩa là "tôi chưa gặp đúng fingerprint này gần đây", chứ KHÔNG có nghĩa "thực tế khác với điều tôi kỳ vọng" (prediction error). Một thay đổi có ý nghĩa nhưng vô tình trùng family đang tồn tại sẽ bị đè xuống.

`AttentionSalienceMemory` cố ý chỉ là rolling memory của fingerprint ("không phải long-term memory, không ghi fact vào đây"). Thứ duy nhất sống qua các chu kỳ là bộ đếm fingerprint. Đó là lý do `repetition=1.00` bị kẹt mãi trong log: không có model nào để bị vi phạm. `working_memory.py` và `global_workspace.py` đều là bộ chọn theo từng frame (`_collect_candidates(frame)` → `_select` → `_attach_to_frame`), dựng lại từ frame hiện tại mỗi chu kỳ và không mang trạng thái nào về sau.

Trong khi đó `event_semantics.py` đã có sẵn `EventClusterIndex`, `_cosine_similarity` và một embedding cache — nhưng hiện chỉ dùng để gom event thành "family", KHÔNG dùng để đo prediction error.

Tính năng này giới thiệu một **Situation Model** (còn gọi WorldState / SituationModel): một object bền vững được mang qua các chu kỳ, giữ trạng thái hiện tại, hình thành dự đoán về cái sắp tới, và mỗi chu kỳ đo prediction error giữa dự đoán và thực tế quan sát được. Salience sẽ được tính chủ yếu từ prediction error và mức liên quan tới stake, thay vì từ repeat_count. Habituation theo repeat_count trở thành một số hạng nhỏ thay vì toàn bộ tín hiệu. Khái niệm vi phạm kỳ vọng (expectation violation) trở thành động cơ của tò mò và phản ứng.

## Glossary

- **Situation_Model**: Object bền vững được mang qua các chu kỳ nhận thức (cognitive cycle), giữ trạng thái tình huống hiện tại của ERIS gồm activity hiện tại, content thread, xu hướng engagement của người dùng, các open loop, và dự đoán ngắn về cái sắp xảy ra. Tồn tại ở tầng engine, không bị dựng lại mỗi frame.
- **Cognitive_Cycle**: Một lần chạy `CognitivePipeline.run()` (Evidence → Attention/Salience → Budget → WorkingMemory → GlobalWorkspace). Tương đương "một chu kỳ" trong tài liệu này.
- **Percept**: Quan sát mới của một chu kỳ — tập EvidenceItem / AttentionCandidate đã chuẩn hóa từ frame hiện tại mà Situation_Model dùng làm "thực tế" (reality).
- **Prediction**: Dự đoán ngắn do Situation_Model tạo ở cuối chu kỳ N về percept mong đợi ở chu kỳ N+1 (ví dụ "Ngài sẽ xem tiếp", "Ngài sẽ trả lời câu tôi hỏi"). Mỗi Prediction gồm mô tả văn bản, embedding (nếu có), và một mức tin cậy (confidence).
- **Prediction_Error**: Khoảng cách ngữ nghĩa giữa Prediction (của chu kỳ trước) và Percept (của chu kỳ hiện tại), chuẩn hóa về [0,1], với 0 = thực tế khớp dự đoán, 1 = thực tế hoàn toàn trái dự đoán.
- **Stake_Relevance**: Mức một Percept chạm vào mối quan tâm thường trực của ERIS, lấy từ `StandingStakes` đã có (theme overlap, care_user_activity, care_user_mood, relational_pull), chuẩn hóa về [0,1].
- **Expectation_Violation**: Sự kiện khi Prediction_Error vượt một ngưỡng cấu hình, biểu thị thực tế khác đáng kể so với điều ERIS kỳ vọng.
- **Open_Loop**: Một mạch chưa khép trong Situation_Model (ví dụ câu hỏi ERIS đã hỏi nhưng chưa được trả lời, hoặc một việc Ngài đang làm dở), kèm trạng thái mở/đóng và thời điểm cập nhật.
- **Engagement_Trend**: Xu hướng tương tác của người dùng theo thời gian (ví dụ tăng / giảm / ổn định) mà Situation_Model duy trì qua các chu kỳ.
- **Content_Thread**: Chủ đề / mạch nội dung chính mà ERIS đang theo dõi (ví dụ "đang code module cortex", "đang xem video"), được mang qua các chu kỳ.
- **Habituation_Term**: Số hạng salience nhỏ vẫn dựa trên repeat_count để giảm trọng số cho tín hiệu lặp đi lặp lại, nhưng không còn là tín hiệu chính.
- **Embedding_Infrastructure**: Hạ tầng embedding/cosine đã có trong `event_semantics.py` (`EventEmbeddingCache`, `EventClusterIndex`, `_cosine_similarity`, `_normalize_vector`), được tái sử dụng để đo Prediction_Error.
- **Attention_Salience_Engine**: `AttentionSalienceEngine` trong `src/cortex/attention_salience.py`, tầng [03] của pipeline, nơi salience được tính.
- **Situation_Logger**: Thành phần ghi log/observability phát ra prediction, reality và prediction error mỗi chu kỳ.
- **Cold_Start**: Trạng thái chu kỳ đầu tiên (hoặc sau reset) khi Situation_Model chưa có Prediction nào của chu kỳ trước để so sánh.

## Requirements

### Requirement 1: Situation Model bền vững qua các chu kỳ

**User Story:** Là người phát triển ERIS, tôi muốn có một Situation_Model sống qua các chu kỳ nhận thức, để hệ thống mang trạng thái tình huống về phía trước thay vì dựng lại từ con số không mỗi frame.

#### Acceptance Criteria

1. THE Situation_Model SHALL duy trì các trường trạng thái: Content_Thread hiện tại, current activity, Engagement_Trend, danh sách Open_Loop với tối đa 100 phần tử, và Prediction gần nhất.
2. WHEN một Cognitive_Cycle hoàn tất, THE Situation_Model SHALL giữ lại trạng thái đã cập nhật để Cognitive_Cycle kế tiếp đọc được, đồng thời không làm mất hoặc thay đổi bất kỳ trường trạng thái nào không liên quan đến bản cập nhật của chu kỳ đó.
3. WHEN một Cognitive_Cycle mới bắt đầu và đã tồn tại trạng thái của chu kỳ trước, THE Situation_Model SHALL cung cấp trạng thái của chu kỳ trước cho bước tính toán của chu kỳ hiện tại.
4. IF một Cognitive_Cycle bắt đầu mà chưa tồn tại trạng thái của bất kỳ chu kỳ trước nào (chu kỳ đầu tiên), THEN THE Situation_Model SHALL cung cấp trạng thái khởi tạo gồm Content_Thread rỗng, current activity rỗng, Engagement_Trend ở mức trung tính, danh sách Open_Loop rỗng (0 phần tử), và Prediction rỗng.
5. THE Situation_Model SHALL tồn tại ở phạm vi engine bền vững, tương tự cơ chế persistence của `AttentionSalienceMemory`, thay vì ở phạm vi một frame.
6. WHEN thao tác reset được gọi, THE Situation_Model SHALL đặt Content_Thread về rỗng, current activity về rỗng, Engagement_Trend về mức trung tính, danh sách Open_Loop về rỗng (0 phần tử), và Prediction về rỗng.

### Requirement 2: Hình thành và mang dự đoán qua các chu kỳ

**User Story:** Là người phát triển ERIS, tôi muốn Situation_Model tạo dự đoán ngắn về cái sắp tới và mang dự đoán đó sang chu kỳ kế, để hệ thống có một kỳ vọng cụ thể để đối chiếu với thực tế.

#### Acceptance Criteria

1. WHEN một Cognitive_Cycle hoàn tất, THE Situation_Model SHALL tạo đúng một (1) Prediction về Percept mong đợi ở Cognitive_Cycle kế tiếp.
2. THE Situation_Model SHALL kèm theo mỗi Prediction một mô tả văn bản có độ dài từ 1 đến 280 ký tự và một giá trị confidence là số thực trong khoảng đóng [0,1].
3. WHERE Embedding_Infrastructure cung cấp được embedding cho mô tả Prediction, THE Situation_Model SHALL lưu embedding đó cùng Prediction và đánh dấu trạng thái embedding của Prediction là khả dụng để dùng cho việc đo Prediction_Error.
4. IF Embedding_Infrastructure không cung cấp được embedding cho mô tả Prediction, THEN THE Situation_Model SHALL vẫn lưu Prediction và đánh dấu trạng thái embedding của Prediction là không khả dụng.
5. WHEN một Cognitive_Cycle mới bắt đầu, THE Situation_Model SHALL nạp Prediction được tạo ở cuối chu kỳ liền trước làm kỳ vọng hiện hành.
6. WHILE Situation_Model ở trạng thái Cold_Start, THE Situation_Model SHALL bỏ qua bước đối chiếu dự đoán và đánh dấu Prediction_Error của chu kỳ là không xác định.
7. WHILE Situation_Model ở trạng thái Cold_Start, THE Situation_Model SHALL gán cho Prediction được tạo một giá trị confidence bằng 0.0.

### Requirement 3: Tính Prediction Error bằng hạ tầng embedding sẵn có

**User Story:** Là người phát triển ERIS, tôi muốn prediction error được đo bằng khoảng cách ngữ nghĩa qua hạ tầng embedding/cosine đã có, để "mới" mang nghĩa "khác kỳ vọng" thay vì "chưa thấy fingerprint này".

#### Acceptance Criteria

1. WHEN một Percept mới được quan sát trong một Cognitive_Cycle và tồn tại Prediction từ chu kỳ liền trước, THE Situation_Model SHALL tính Prediction_Error là khoảng cách ngữ nghĩa giữa Prediction của chu kỳ trước và Percept hiện tại, hoàn tất trong vòng 2 giây kể từ khi Percept được quan sát.
2. THE Situation_Model SHALL tái sử dụng Embedding_Infrastructure trong `event_semantics.py` (`_cosine_similarity`, `_normalize_vector`, `EventEmbeddingCache`) để đo khoảng cách ngữ nghĩa, không tạo cơ chế đo tương đồng mới.
3. THE Situation_Model SHALL chuẩn hóa Prediction_Error thành một giá trị số nằm trong khoảng đóng [0,1], trong đó giá trị bằng 0 biểu thị Percept khớp hoàn toàn Prediction, giá trị bằng 1 biểu thị Percept trái ngược hoàn toàn Prediction, và quan hệ giữa khoảng cách ngữ nghĩa với Prediction_Error là đơn điệu không giảm; mọi giá trị tính ra ngoài [0,1] SHALL bị kẹp (clamp) về biên gần nhất.
4. IF không lấy được embedding hợp lệ cho Prediction hoặc cho Percept (vector rỗng, chứa giá trị không phải số/không hữu hạn, hoặc phép đo tương đồng trả về giá trị không hợp lệ), THEN THE Situation_Model SHALL tính Prediction_Error bằng phương án dự phòng dựa trên token-overlap, chuẩn hóa kết quả về khoảng [0,1] theo cùng quy ước ở tiêu chí 3, và gắn cờ kết quả là degraded mà bên gọi quan sát được.
5. WHEN Prediction_Error lớn hơn hoặc bằng ngưỡng Expectation_Violation_Threshold cấu hình (giá trị trong khoảng [0,1], mặc định 0.5), THE Situation_Model SHALL ghi nhận một Expectation_Violation kèm tham chiếu tới Prediction và Percept liên quan.
6. IF không tồn tại Prediction từ chu kỳ liền trước (ví dụ chu kỳ đầu tiên), THEN THE Situation_Model SHALL bỏ qua việc tính Prediction_Error cho chu kỳ đó và không ghi nhận Expectation_Violation.

### Requirement 4: Salience dựa trên Prediction Error và Stake Relevance

**User Story:** Là người phát triển ERIS, tôi muốn salience được tính từ prediction error và mức liên quan tới stake, để phản ứng của ERIS được dẫn dắt bởi vi phạm kỳ vọng chứ không bởi bộ đếm lặp.

#### Acceptance Criteria

1. THE Attention_Salience_Engine SHALL tính số hạng novelty từ Prediction_Error (chuẩn hóa trong khoảng 0.0 đến 1.0) do Situation_Model cung cấp thay vì từ bảng tra cứu repeat_count.
2. THE Attention_Salience_Engine SHALL kết hợp Prediction_Error (0.0 đến 1.0) và Stake_Relevance (0.0 đến 1.0) thành một giá trị salience chuẩn hóa trong khoảng 0.0 đến 1.0 cho mỗi Percept.
3. WHEN Prediction_Error của một Percept tăng trong khi Stake_Relevance giữ nguyên, THE Attention_Salience_Engine SHALL tạo ra salience không giảm (lớn hơn hoặc bằng) so với giá trị tại Prediction_Error thấp hơn.
4. WHEN Stake_Relevance của một Percept tăng trong khi Prediction_Error giữ nguyên, THE Attention_Salience_Engine SHALL tạo ra salience không giảm (lớn hơn hoặc bằng) so với giá trị tại Stake_Relevance thấp hơn.
5. THE Attention_Salience_Engine SHALL giữ Habituation_Term dựa trên repeat_count như một số hạng phụ có trọng số nhỏ hơn nghiêm ngặt so với trọng số của số hạng Prediction_Error.
6. WHILE số lượng Percept đã quan sát nhỏ hơn ngưỡng tối thiểu có thể cấu hình (mặc định 5), tức trạng thái Cold_Start, THE Attention_Salience_Engine SHALL tính salience theo cơ chế dự phòng tương đương hành vi repeat_count hiện tại.
7. IF Prediction_Error là không xác định, THEN THE Attention_Salience_Engine SHALL chuyển sang cơ chế dự phòng tương đương hành vi repeat_count, phát chỉ báo cho biết đang dùng cơ chế dự phòng, và giữ nguyên dữ liệu Percept đầu vào.
8. WHEN một Percept có ý nghĩa trùng family đang tồn tại nhưng có Prediction_Error lớn hơn hoặc bằng ngưỡng Prediction_Error cao có thể cấu hình, THE Attention_Salience_Engine SHALL giữ salience của Percept đó không thấp hơn ngưỡng sàn salience (salience floor) có thể cấu hình.
9. IF Prediction_Error hoặc Stake_Relevance nằm ngoài khoảng 0.0 đến 1.0 hoặc không xác định, THEN THE Attention_Salience_Engine SHALL giới hạn giá trị về biên gần nhất hoặc dùng giá trị dự phòng, phát chỉ báo lỗi cho biết đầu vào không hợp lệ, và giữ nguyên dữ liệu Percept gốc.

### Requirement 5: Vi phạm kỳ vọng làm động cơ tò mò

**User Story:** Là người phát triển ERIS, tôi muốn vi phạm kỳ vọng được phơi bày cho các tầng phía sau, để tò mò và phản ứng của ERIS bắt nguồn từ "tôi tưởng Ngài sẽ tiếp tục code; Ngài lại không — tại sao?".

#### Acceptance Criteria

1. WHEN một Expectation_Violation được ghi nhận, THE Situation_Model SHALL phơi bày Prediction đã kỳ vọng, Percept thực tế và Prediction_Error qua một giao diện có thể đọc cho các tầng downstream, và SHALL giữ các giá trị này khả dụng cho đến khi chu kỳ kế tiếp ghi đè lên chúng.
2. WHEN Percept hiện tại được so sánh với Prediction, THE Situation_Model SHALL cập nhật trạng thái các Open_Loop tương ứng theo kết quả: nếu Prediction_Error nhỏ hơn ngưỡng Expectation_Violation thì coi là khớp, nếu Prediction_Error lớn hơn hoặc bằng ngưỡng Expectation_Violation thì coi là trái.
3. WHEN một Open_Loop được kỳ vọng khép lại nhưng Percept cho thấy nó vẫn mở, THE Situation_Model SHALL giữ Open_Loop ở trạng thái mở, đánh dấu là kỳ vọng bị vi phạm và cập nhật dấu thời gian cập nhật (update timestamp) của Open_Loop đó.
4. WHEN một chu kỳ hoàn tất, THE Situation_Model SHALL cập nhật Engagement_Trend dựa trên cửa sổ quan sát gồm N chu kỳ gần nhất (mặc định 3), với giá trị Engagement_Trend là một trong các giá trị: tăng, giảm, hoặc ổn định.
5. IF đang ở trạng thái Cold_Start hoặc Prediction_Error chưa được xác định, THEN THE Situation_Model SHALL bỏ qua việc cập nhật trạng thái Open_Loop và Engagement_Trend trong chu kỳ đó, giữ nguyên trạng thái trước đó và đánh dấu Engagement_Trend là ổn định cho đến khi đủ dữ liệu.

### Requirement 6: Tương thích ngược và di trú

**User Story:** Là người phát triển ERIS, tôi muốn tính năng tích hợp mà không phá vỡ pipeline hiện tại, để có thể triển khai dần và quay lui an toàn.

#### Acceptance Criteria

1. WHERE Situation_Model bị tắt qua cấu hình, THE Attention_Salience_Engine SHALL tính salience chỉ theo cơ chế `_novelty_score` dựa trên repeat_count hiện hành, và SHALL tạo ra giá trị salience trùng khớp với hành vi của phiên bản trước khi tích hợp Situation_Model cho cùng một đầu vào.
2. THE Situation_Model SHALL tích hợp vào `CognitivePipeline.run()` mà không thay đổi danh sách tham số, kiểu tham số và kiểu trả về của các chữ ký công khai `AttentionSalienceEngine.evaluate()`, `WorkingMemoryEngine.select()` và `GlobalWorkspaceEngine.broadcast()`.
3. IF khởi tạo hoặc cập nhật Situation_Model phát sinh lỗi trong một Cognitive_Cycle, THEN THE CognitivePipeline SHALL hoàn tất chu kỳ đó bằng cơ chế salience dự phòng `_novelty_score`, SHALL giữ nguyên (không thay đổi) trạng thái của Working_Memory và Global_Workspace có trước khi lỗi xảy ra, và SHALL ghi một bản ghi cảnh báo nêu rõ Cognitive_Cycle bị ảnh hưởng cùng nguyên nhân lỗi.
4. WHEN CognitivePipeline được khởi tạo, THE Situation_Model SHALL đọc một cờ cấu hình điều khiển việc dẫn dắt salience bằng prediction error, với giá trị mặc định là bật (enabled).
5. IF cờ cấu hình dẫn dắt salience bằng prediction error vắng mặt hoặc có giá trị không hợp lệ (khác true/false), THEN THE Situation_Model SHALL áp dụng giá trị mặc định bật (enabled) và SHALL ghi một bản ghi cảnh báo nêu rõ cờ cấu hình không hợp lệ.

### Requirement 7: Khả năng quan sát (Observability)

**User Story:** Là người phát triển ERIS, tôi muốn log thể hiện dự đoán, thực tế và prediction error mỗi chu kỳ, để chẩn đoán hành vi thay vì nhìn một dòng `repetition=1.00` phẳng lì.

#### Acceptance Criteria

1. WHEN một Cognitive_Cycle hoàn tất và tồn tại Prediction của chu kỳ trước, THE Situation_Logger SHALL ghi Prediction của chu kỳ trước, Percept hiện tại và giá trị Prediction_Error đã tính trong khoảng [0, 1].
2. IF một Cognitive_Cycle hoàn tất nhưng không tồn tại Prediction của chu kỳ trước (trường hợp Cold_Start), THEN THE Situation_Logger SHALL ghi một mục log nêu rõ trạng thái Cold_Start và Percept hiện tại thay vì ghi giá trị Prediction_Error.
3. WHEN một Expectation_Violation xảy ra, THE Situation_Logger SHALL ghi một mục log nêu rõ mô tả Prediction kỳ vọng, Percept thực tế và giá trị Prediction_Error đã vượt ngưỡng.
4. THE Situation_Model SHALL cung cấp một thao tác serialize trạng thái sang dạng dict cho debug, gồm các trường: Content_Thread, Engagement_Trend, Open_Loop, Prediction gần nhất và Prediction_Error gần nhất.
5. WHILE Prediction_Error ở trạng thái degraded hoặc không xác định, THE Situation_Logger SHALL ghi rõ nguyên nhân thuộc tập phân loại {Cold_Start, thiếu Prediction embedding, thiếu Percept embedding, không có Percept} thay vì ghi một giá trị tĩnh.
6. IF xảy ra lỗi trong quá trình serialize trạng thái hoặc ghi log, THEN THE Situation_Logger SHALL ghi nhận lỗi và cho phép Cognitive_Cycle tiếp tục mà không bị gián đoạn.

### Requirement 8: Vòng đời cập nhật mỗi chu kỳ

**User Story:** Là người phát triển ERIS, tôi muốn một vòng đời cập nhật rõ ràng mỗi chu kỳ, để thứ tự observe → so dự đoán → cập nhật → dự đoán lại được xác định và lặp lại được.

#### Acceptance Criteria

1. WHERE Situation_Model được bật, WHEN một Cognitive_Cycle chạy, THE Situation_Model SHALL thực hiện tuần tự đúng bốn bước, không đảo thứ tự và không bỏ bước: (1) quan sát Percept, (2) tính Prediction_Error so với Prediction của chu kỳ trước, (3) cập nhật trạng thái, (4) tạo Prediction mới; ngoại trừ trường hợp Cold_Start thì bước (2) được bỏ qua theo Requirement 2.
2. WHILE một Cognitive_Cycle đang chạy với Situation_Model được bật, THE Situation_Model SHALL cập nhật trạng thái đúng một lần — không bị bỏ qua và không quá một lần.
3. WHEN cùng một chuỗi Percept được áp dụng lại lên một Situation_Model có cùng trạng thái khởi đầu và không có nguồn ngẫu nhiên hay biến thiên theo thời gian, THE Situation_Model SHALL tạo ra trạng thái kết thúc và Prediction bằng nhau theo từng trường khi so sánh ở dạng serialize của Requirement 7.
4. IF một Cognitive_Cycle cung cấp tập Percept rỗng, THEN THE Situation_Model SHALL bỏ qua bước cập nhật trạng thái, giữ nguyên trạng thái trước đó, giữ lại Prediction trước làm kỳ vọng hiện hành, và đánh dấu Prediction_Error của chu kỳ là không xác định.
5. IF xảy ra lỗi ở giữa vòng đời cập nhật, THEN THE Situation_Model SHALL không thực hiện cập nhật một phần, giữ nguyên toàn bộ trạng thái trước đó, và phát tín hiệu lỗi cho cơ chế dự phòng của Requirement 6.
