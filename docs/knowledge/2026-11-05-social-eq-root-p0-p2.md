# Eris EQ — triển khai gộp P0/P1/P2 tại Root (05/11/2026)

## Mục đích và phạm vi

Yêu cầu hiện tại: Eris mang cá tính INFJ/Fe phụ cần chú ý đến trải nghiệm
của người đang kể và quyết định cách tham gia có ngữ cảnh. **Không** tạo bảng
`buồn → an ủi`, `bực → không hỏi`; cũng không cần thêm EQ agent, social planner,
model call hoặc trường suy nghĩ bắt buộc trong JSON.

Bản này **thay trạng thái “chưa triển khai P0–P2 cho social judgment”** của cuộc
trao đổi thiết kế ngày 05/11 bằng trạng thái: **đã sửa source, có test offline;
chưa build/deploy portable và chưa có đối chứng inference live sau sửa**.
Nó không phủ định các phép thử live lịch sử, và không chứng minh EQ thực tế
đã tăng.

## Những gì đã sửa

- **P0 — Cấp đúng bằng chứng hiện tại:** `conversation_handoff.py` ghi nhận
  một số *lời sửa trực tiếp về cách Eris hỏi* dưới nhãn `approach_feedback`,
  thay vì mặc định đó là user không hiểu. Đây chỉ là observation, không có
  quyền chọn câu tiếp theo. `context_assembler.py` dùng đúng snapshot của
  StateReducer, không để biến handoff che mất mind state. Trường hợp handoff
  của lượt trước không được đóng vai bằng chứng cho lượt hiện tại.
- **P0 — Tách factual grounding khỏi social response:** `source_grounding.py`
  vẫn giữ giới hạn chống bịa file, screen, web và nguyên nhân kỹ thuật. Nhưng
  *được phép* probe không đồng nghĩa *phải* probe. Lời tự thuật của user cho
  phép Eris tham gia câu chuyện, không chứng minh nguyên nhân bên ngoài.
- **P1 — Thay đổi lựa chọn của chính Root:** `root_prompt_contract.py` thêm
  khung `SOCIAL_JUDGMENT_PROMPT`, được gắn ở `agent.py`. Root cân nhắc
  trải nghiệm, quan hệ, mục đích hiện tại và gánh nặng lời đáp trước khi
  finalize `intent/say`; không thêm schema, critic, chấm EQ hay vòng LLM.
  Khi user yêu cầu giải quyết việc thật, hỏi kỹ thuật vẫn hợp lý.
- **P2 — Đưa trường hợp đã học trở lại Root:** module mới
  `conversation/social_situation.py` đọc `IdentityProfile.strategies[*].experiences`
  đã được `StateReducer` và hậu kỳ observer xác nhận có phản ứng user,
  chỉ lấy tối đa 2 trường hợp có provenance/confidence phù hợp. Ưu tiên cùng
  phiên; khác phiên được gắn nhãn để Root không biến chúng thành sở thích
  toàn cục. Không học từ lời *pending* hoặc output chưa phát. Chọn hay không
  chọn cách nói vẫn do Root.

`ERIS_ROOT_INTERACTION_CHOICES` **vẫn mặc định tắt**; không đổi JSON move hiện
hành. Đường lưu `pending_strategy → reaction → observer consequence → experiences`
đã có sẵn từ bản trước, nên không tạo thêm bảng memory EQ trùng chức năng.

## Ranh giới

1. Những từ khóa handoff chỉ phát hiện *lời phản hồi tường minh về cách trò
   chuyện*, **không** phân loại trạng thái cảm xúc và **không** ra lệnh ứng xử.
2. `social_situation_evidence` là *evidence-only*; observer hậu kỳ vẫn có thể
   hiểu sai hậu quả. Một trường hợp không trở thành chính sách cho các lượt sau.
3. Delivery `pending/delivering/failed/cancelled` không phải lời hoàn tất;
   tình huống cũ vẫn có thể được đọc từ public history kèm trạng thái.
4. Không thay đổi quyền Root, phát ngôn TTS, memory authority, API/tool
   registry, portable hay logic hủy/preempt cũ.

## Kiểm tra đã chạy (môi trường Python offline)

- 38/38 bài test trọng tâm mới và liên quan đạt.
- Regression rộng: **608 đạt, 7 lỗi**. Chạy lại đúng 7 bài trên *ZIP gốc*
  cho kết quả lỗi giống hệt; không kết luận chúng do patch gây ra. Các lỗi
  nền thuộc action claim gate, memory degraded test, public claim gate và
  đường dẫn `body/UdpListener.SettingsDanger.cs` thiếu trong ZIP.
- `compileall` trên các file Python sửa: đạt.
- Không có kết quả live A/B từ model/DeepSeek/Gemini, không kiểm voice/TTS
  hay GUI. Không sử dụng số test để khẳng định EQ tăng.

## Khi thử bằng Eris chạy thật

Giữ cùng model, cùng system suffix/schema, tham số generation và bộ tình huống;
đo không chỉ một câu say mà ít nhất hai lượt tiếp. So bản ZIP gốc với bản mới
ở những cảnh: xả bực Kiro, sửa cách Eris hỏi, đùa, nhờ debug, kể rồi chuyển
sang nhờ giúp, và bất đồng. Chấm riêng: (1) hiểu tình huống, (2) lựa chọn
ứng xử, (3) lời nói thực tế, (4) phản ứng user, (5) JSON parsing/delivery.
Câu hỏi không mặc định là thất bại; đánh giá gánh nặng, timing và lời sửa.
