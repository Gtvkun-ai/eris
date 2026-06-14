# Requirements Document

## Introduction

`AppraisalEngine` (`src/cortex/appraisal.py`) hiện tạo *stance* — chế độ biểu đạt tiền-ngôn-ngữ của ERIS — bằng `_choose_stance()`: một thang `if/elif` chọn-một-người-thắng dựa trên hàng loạt ngưỡng cứng (`threat >= 0.66`, `jealousy_lite >= 0.32`, `tenderness >= 0.68`...). Cách này có ba điểm "khuôn thẳng":

1. **Một nhãn duy nhất.** Người thật hiếm khi chỉ "protective"; họ thường *vừa che chở, vừa mệt, vừa hơi mềm* cùng lúc. First-match làm phẳng pha trộn đó thành một từ.
2. **Nhảy giật ở ngưỡng.** Qua mốc 0.66 một chút là snap từ "tender" sang "protective". Đây là máy trạng thái hữu hạn mặc áo cảm xúc, không có quán tính.
3. **Magic number rải khắp.** Mỗi ngưỡng là một số hand-tuned, không có một knob ý nghĩa nào để chỉnh "độ dứt khoát" của tính cách.

Song song, `_event_affect()` đọc cảm xúc của sự-kiện bằng cách **đếm token** trong hai bảng lexicon không dấu (`_EVENT_NEG_TOKENS`, `_EVENT_POS_TOKENS`). Một cảnh hỗn hợp ("đậu phỏng vấn nhưng giờ lo sợ") bị triệt tiêu về trung tính vì đếm 1 pos / 1 neg.

Đáng chú ý: hạ tầng "đẹp" để sửa cả ba điểm trên ĐÃ tồn tại trong repo nhưng `appraisal` không dùng:
- `MentalProcessSystem` (`internal_state.py`) là hệ động lực phi tuyến có quán tính ở tầng process.
- `semantic_prototypes.py` + encoder cho "nghĩa bằng độ gần trong không gian vector".
- `affect_semantics.py` cho tín hiệu đa trục mềm.

Tính năng này thay biểu diễn stance rời rạc bằng **phân bố mềm trên các điểm hút (attractor) trong không gian affect**, thêm **quán tính cảm xúc (EMA inertia)** giữa các turn, và thay đếm-token bằng **phép chiếu prototype** khi đọc affect của sự-kiện. Cả ba quy về MỘT primitive duy nhất (`soft_assign`: khoảng cách → softmax → blend có quán tính), giảm số khái niệm thay vì tăng. PoC thuần đã có ở `src/cortex/affect_blend.py` và `tests/test_affect_blend.py`.

## Glossary

- **Affect_Vector**: Vector trên 12 trục của `CognitiveAppraisal` (valence, arousal, certainty, agency, controllability, intimacy, threat, protectiveness, jealousy_lite, amusement, fatigue, tenderness). `valence` ∈ [-1,1], còn lại ∈ [0,1].
- **Stance_Anchor**: Một điểm neo trong không gian Affect_Vector đại diện cho một stance (ví dụ `protective`, `tired`), chỉ khai báo các trục định nghĩa nó.
- **Stance_Blend**: Phân bố xác suất mềm trên tập stance (các trọng số ≥ 0, tổng = 1), thay cho một nhãn stance duy nhất.
- **Soft_Assign**: Primitive lõi gán một điểm vào Stance_Blend: similarity = −RMS_distance tới mỗi anchor → softmax theo Temperature → EMA với phân bố trước.
- **Temperature**: Tham số duy nhất điều khiển độ sắc của Stance_Blend; nhỏ → gần một stance, lớn → pha trộn nhiều. Thay cho toàn bộ ngưỡng cứng cũ.
- **Inertia**: Hệ số quán tính cảm xúc ∈ [0,1] dùng trong EMA giữa Stance_Blend của turn trước và turn hiện tại; cao → trôi chậm, ít flip-flop (hysteresis).
- **Previous_Stance_Blend**: Stance_Blend của chu kỳ/turn appraisal trước, được lưu bền vững để tạo Inertia.
- **Dominant_Stances**: Top-k stance trong Stance_Blend vượt một ngưỡng trọng số tối thiểu, dùng để dựng prompt guidance pha trộn.
- **Affect_Direction_Prototype**: Một prototype mô tả nghĩa-cảm-xúc của sự-kiện (ví dụ "ai đó đang lặng lẽ chật vật") kèm một Affect_Vector mục tiêu, dùng để đọc affect sự-kiện bằng phép chiếu thay vì đếm token.
- **Event_Affect**: Tín hiệu cảm xúc rút từ sự-kiện nổi bật (broadcast), gồm valence/tenderness/arousal, đã gate theo stake và surprise.
- **Stake_Gate**: Cổng nhân Event_Affect theo `care_user_mood` (stake) và surprise (prediction error so với nội trạng), giữ nguyên từ `_event_affect` hiện tại.
- **Appraisal_Engine**: `AppraisalEngine` trong `src/cortex/appraisal.py`.
- **Affect_Blend_Module**: Module `src/cortex/affect_blend.py` chứa primitive `soft_assign`, `blend_stance`, `StanceBlend`, `guidance_blend` (PoC đã tồn tại).
- **Legacy_Stance**: Giá trị `CognitiveAppraisal.stance: str` hiện tại; phải tiếp tục tồn tại = argmax của Stance_Blend để tương thích ngược.

## Requirements

### Requirement 1: Stance dạng phân bố mềm thay cho nhãn rời rạc

**User Story:** Là người phát triển ERIS, tôi muốn stance là một phân bố mềm trên nhiều điểm hút, để trạng thái biểu đạt phản ánh được pha trộn cảm xúc đồng thời thay vì một nhãn duy nhất.

#### Acceptance Criteria

1. THE Appraisal_Engine SHALL tạo một Stance_Blend từ Affect_Vector của lần đánh giá hiện tại bằng Soft_Assign trên tập Stance_Anchor.
2. THE Stance_Blend SHALL là một phân bố hợp lệ: mọi trọng số ≥ 0 và tổng các trọng số = 1 với sai số tuyệt đối ≤ 1e-6.
3. THE Stance_Blend SHALL chứa đúng tập tên stance bằng tập khóa của Stance_Anchor đang dùng.
4. WHEN một Affect_Vector trùng đúng một Stance_Anchor, THE Appraisal_Engine SHALL tạo Stance_Blend mà argmax là chính stance đó.
5. WHEN Affect_Vector kích hoạt nhiều trục thuộc nhiều stance khác nhau ở mức tương đương, THE Stance_Blend SHALL phân bổ trọng số cho ít nhất hai stance và SHALL KHÔNG gán cho bất kỳ stance đơn lẻ nào trọng số ≥ 0.9.
6. THE Appraisal_Engine SHALL phơi bày Stance_Blend qua trường mới `stance_blend` trên `CognitiveAppraisal` dưới dạng map tên-stance → trọng số đã làm tròn.

### Requirement 2: Tương thích ngược với `CognitiveAppraisal.stance`

**User Story:** Là người bảo trì pipeline, tôi muốn các downstream đang đọc `appraisal.stance` tiếp tục hoạt động, để thay đổi không phá vỡ recorder, test, và prompt hiện có.

#### Acceptance Criteria

1. THE `CognitiveAppraisal` SHALL tiếp tục có trường `stance: str`.
2. THE Appraisal_Engine SHALL đặt Legacy_Stance = argmax của Stance_Blend.
3. THE set giá trị khả dĩ của Legacy_Stance SHALL là tập con của các stance mà `_choose_stance` cũ có thể trả về (`protective`, `watchful`, `tender_under_cold`, `tired`, `dry_playful`, `soft_uncertain`, `grounded`).
4. WHERE một downstream chỉ đọc `appraisal.stance` (ví dụ `cognitive_frame_recorder.py`), THE thay đổi SHALL KHÔNG yêu cầu sửa downstream đó.
5. THE `CognitiveAppraisal.to_dict()` SHALL tiếp tục chứa khóa `stance` với cùng kiểu chuỗi như trước, và SHALL bổ sung khóa `stance_blend`.

### Requirement 3: Quán tính cảm xúc (EMA hysteresis) giữa các turn

**User Story:** Là người thiết kế nhân vật, tôi muốn trạng thái cảm xúc trôi dần thay vì nhảy giật, để ERIS có cái "dùng dằng" của người thật và không lật stance ở mỗi dao động nhỏ.

#### Acceptance Criteria

1. THE Appraisal_Engine SHALL lưu bền vững Previous_Stance_Blend qua các lần đánh giá, theo cùng cơ chế persistence với trạng thái nội tại hiện có.
2. WHEN tồn tại Previous_Stance_Blend, THE Appraisal_Engine SHALL áp EMA giữa Previous_Stance_Blend và Stance_Blend hiện tại với hệ số Inertia trước khi phát ra kết quả.
3. WHEN Inertia = 1, THE Stance_Blend phát ra SHALL bằng Previous_Stance_Blend (sau chuẩn hóa) với sai số tuyệt đối ≤ 1e-6 cho mỗi trọng số.
4. WHEN Inertia = 0, THE Stance_Blend phát ra SHALL bằng Stance_Blend tính từ Affect_Vector hiện tại (không chịu ảnh hưởng Previous_Stance_Blend).
5. WHEN Previous_Stance_Blend nghiêng mạnh về một stance và Affect_Vector hiện tại nghiêng mạnh về stance khác, với Inertia cao, THE stance cũ SHALL vẫn giữ trọng số lớn hơn so với khi dùng Inertia thấp ở cùng đầu vào.
6. WHEN cùng một Affect_Vector mới được áp lặp lại qua nhiều turn với Inertia < 1, THE argmax của Stance_Blend SHALL cuối cùng chuyển sang stance tương ứng Affect_Vector mới (quán tính làm chậm, không khóa cứng).
7. IF chưa tồn tại Previous_Stance_Blend (lần đánh giá đầu hoặc sau reset), THEN THE Appraisal_Engine SHALL dùng Stance_Blend tính trực tiếp từ Affect_Vector mà không áp EMA.

### Requirement 4: Đọc affect sự-kiện bằng phép chiếu prototype

**User Story:** Là người phát triển ERIS, tôi muốn affect của sự-kiện được đọc bằng độ gần ngữ nghĩa tới các prototype, để cảnh hỗn hợp hoặc diễn đạt lạ không bị triệt tiêu như khi đếm token.

#### Acceptance Criteria

1. THE Appraisal_Engine SHALL tính Event_Affect bằng phép chiếu văn bản sự-kiện lên tập Affect_Direction_Prototype thay vì đếm token lexicon.
2. THE Event_Affect SHALL là blend có trọng số của các Affect_Vector mục tiêu của prototype theo độ tương đồng, cho ra valence/tenderness/arousal.
3. THE Appraisal_Engine SHALL giữ nguyên Stake_Gate (nhân theo `care_user_mood` và surprise) trên Event_Affect như hành vi hiện tại.
4. WHEN văn bản sự-kiện chứa đồng thời tín hiệu tích cực và tiêu cực mạnh, THE Event_Affect SHALL phản ánh cả hai (không triệt tiêu về 0) bằng một valence pha trộn và tenderness > 0.
5. IF không có stake (`care_user_mood` ≤ 0) hoặc không có nội dung sự-kiện, THEN THE Appraisal_Engine SHALL trả Event_Affect rỗng, bảo toàn hành vi hiện tại.
6. WHERE encoder embedding không khả dụng tại runtime, THE Appraisal_Engine SHALL suy giảm an toàn về một đường dự phòng xác định mà không ném lỗi.

### Requirement 5: Prompt guidance phản ánh pha trộn

**User Story:** Là người thiết kế tầng ngôn ngữ, tôi muốn hướng dẫn bề mặt phản ánh pha trộn stance, để LLM diễn được "che chở nhưng mệt" thay vì chỉ một chế độ.

#### Acceptance Criteria

1. THE Appraisal_Engine SHALL dựng prompt guidance từ Dominant_Stances của Stance_Blend.
2. WHEN Stance_Blend có từ hai Dominant_Stances trở lên, THE prompt guidance SHALL chứa hướng dẫn của ít nhất hai stance đó kèm trọng số tương ứng.
3. WHEN Stance_Blend bị một stance áp đảo, THE prompt guidance SHALL tương đương về nội dung với hướng dẫn của stance đó như hệ thống cũ.
4. THE `render_prompt_context()` SHALL tiếp tục phát ra dòng `appraisal_stance` (dùng Legacy_Stance) để không phá khế ước prompt hiện tại.

### Requirement 6: Một knob cấu hình, không magic number rải rác

**User Story:** Là người tinh chỉnh tính cách, tôi muốn điều khiển "độ dứt khoát vs phân vân" bằng vài tham số có ý nghĩa, để khỏi dò hàng chục ngưỡng rời rạc.

#### Acceptance Criteria

1. THE Affect_Blend_Module SHALL phơi bày Temperature và Inertia như tham số cấu hình có giá trị mặc định.
2. WHEN Temperature giảm, THE trọng số lớn nhất của Stance_Blend (với cùng Affect_Vector) SHALL tăng và entropy của phân bố SHALL giảm.
3. THE Stance_Anchor SHALL được định nghĩa tập trung tại một nơi trong Affect_Blend_Module để chỉnh sửa không cần đụng logic phân nhánh.
4. THE việc thay `_choose_stance` SHALL KHÔNG đưa thêm ngưỡng so sánh cứng mới nào cho việc chọn stance ngoài Temperature và ngưỡng trọng số tối thiểu của Dominant_Stances.

### Requirement 7: Cờ bật/tắt và bảo toàn hành vi

**User Story:** Là người vận hành, tôi muốn có thể tắt cơ chế mới để quay về `_choose_stance` cũ, để giảm rủi ro khi tích hợp.

#### Acceptance Criteria

1. THE Appraisal_Engine SHALL hỗ trợ một cờ cấu hình bật/tắt đường stance dạng blend.
2. WHEN cờ tắt, THE Appraisal_Engine SHALL dùng `_choose_stance` cũ và SHALL cho cùng Legacy_Stance như trước thay đổi với cùng đầu vào.
3. WHEN cờ bật, THE Appraisal_Engine SHALL dùng đường blend và SHALL vẫn thỏa mọi tiêu chí tương thích ngược ở Requirement 2.
4. THE bộ test hiện có `tests/test_appraisal_engine.py` SHALL tiếp tục pass ở cả hai trạng thái cờ.
