# Đánh giá episode mờ dần — 02/11/2026

Cập nhật sau khi user duyệt triển khai: xem
[báo cáo v1](../../../docs/knowledge/2026-11-02-episode-fading-memory-v1.md).
Các đoạn “chưa triển khai/chưa test” dưới đây là trạng thái tại lúc đánh giá,
được thay thế trong phạm vi nêu ở báo cáo v1; không phải xác nhận đã deploy.

Phạm vi: đọc source checkout và báo cáo cũ; không sửa runtime/canonical memory,
không gọi Gemini, chạy GC, test hay deploy. Đã đọc bài học runtime theo AGENTS.md.
Các ngưỡng dưới đây là đề xuất thử nghiệm, chưa phải cấu hình đã được đo tối ưu.

## Kết luận

Hướng giữ episode mới rõ, quá khứ thành recap ngắn là hợp lý. Tuy nhiên rolling
recap, episode→profile và episodic→semantic là ba nghiệp vụ riêng. Lưu recap không
tự sửa dedup của hai nghiệp vụ còn lại. Không cần thêm agent loop; dùng service,
maintenance worker và lane Gemini hiện có với một hợp đồng rollup riêng.

## Bằng chứng source và đính chính báo cáo cũ

| Nguồn | Hiện trạng và hệ quả |
|---|---|
| `src/memory/living_user/dreamer.py:38,89` | Tạo ProfileOperation rồi apply profile, không tạo rolling recap |
| `src/memory/living_user/service.py:448,548` | dream đọc recent 12; summary cấp 8 episode cho snapshot; cần sửa cả đường summary |
| `src/memory/memory_cognition.py:502` và `src/runtime/conversation/root_session.py:35` | Self nhận living_user.summary qua memory_state; chỉ sửa context_compiler không đủ |
| `src/runtime/conversation/self_prompt_view.py:91,115` | Projection bỏ timestamp thô, chưa thay bằng nhãn thời gian |
| `src/memory/living_user/context_compiler.py:121,140` | Search tối đa 4 episode; kiểm budget profile trước phần episode, chưa bảo đảm budget tổng |
| `src/memory/living_user/episode_store.py:27` | Merge cùng session/scope dưới ID cũ; nội dung có thể thay mà ID không đổi |
| `src/memory/living_user/episode_store.py:123,196` | compact xóa bản được gộp; trim giữ tối đa 240 theo importance/recency; chưa bảo đảm mọi nguồn tồn tại lâu dài |
| `src/memory/living_user/episode_store.py:177` | scrub_evidence hiện xóa episode; summary mới phải tham gia forget/correction |
| `src/memory/memory_ai_curator.py:172,252` | Kho episodic khác → semantic, đọc tag distilled nhưng chưa ghi sau commit |

Giữ kết luận của curator-distill-persist-report.md rằng output profile/semantic
đã có đường persist và nguồn chưa có checkpoint tương ứng. Thay các diễn giải sau:

- Không gộp lịch chạy cả hai hệ thành mỗi GC khoảng 10 phút. MemoryGCService gọi
  trực tiếp MemoryMaintenanceRunner (`src/runtime/memory_gc_service.py:387`),
  không tự đi qua MemoryKernel.maintain để gọi living_user.dream. Dream có đường
  riêng qua kernel (`src/memory/memory_kernel.py:499`) từ worker digest nền
  (`src/runtime/background_memory_digest_kernel.py:465`, interval mặc định 300s,
  có gate queue/idle/input/remote) và đường session. Chưa đo tần suất/call live.
- Không dùng một cờ consolidated chung cho recap/profile/semantic. Coverage cần
  riêng theo consumer để recap không vô tình chặn việc học profile.
- Không xem mark nguồn là đủ bảo đảm không mất lịch sử: compact/trim có loại
  bản gốc; source_turns cũng chỉ là cửa sổ giới hạn. Nguồn legacy thiếu lời gốc
  vẫn là secondary; không dựng lại bằng suy đoán.

## Thiết kế thực thi đề xuất

1. Thêm thao tác rollup riêng ở LivingUserMemoryService, được gọi từ maintenance
   worker hiện có qua kernel. Không gọi model từ summary/compile_context/Root.
   Tái dùng GeminiWebUserProfileAdapter và lane lock, thêm prompt/schema recap;
   không biến recap thành UserEpisode đặc biệt dễ bị merge/search/trim nhầm.
2. Lưu projection riêng, ví dụ living_user_episode_rollups.json: entry theo
   exact scope.identity, gồm narrative, revision, time anchors, schema/prompt
   version và coverage map episode_id→content_hash. Đây là metadata trên đĩa,
   không đưa toàn bộ vào Root. Giữ coverage recap khác coverage profile/semantic.
3. Commit narrative và coverage trong cùng một atomic snapshot. Không ghi
   summary một file rồi mark nguồn ở file khác. Không chỉ dùng timestamp cursor
   vì episode có thể đến trễ/đổi nội dung. Không có delta thì không gọi Gemini,
   kể cả sau restart. Single-flight cùng scope để tránh gọi model trùng.
4. Chụp revision/hash rồi nhả lock trước khi gọi Gemini. Khi commit kiểm lại
   revision, nguồn và authority/tombstone dưới lock; candidate cũ không được ghi
   đè thay đổi mới. Timeout/output sai/write failure giữ checkpoint trước để
   retry có backoff. Atomic_write_json chỉ giải quyết ghi file, không tự giải
   quyết stale read/modify/write hay transaction nhiều file.
5. Thường ngày gửi recap đã lưu + episode mới đủ điều kiện. Episode cũ đổi,
   correction hoặc forget phải thay/dựng lại phần bị ảnh hưởng từ nguồn hợp lệ;
   không chỉ nối thêm ý mới lên diễn giải sai. Không tách được phần bị quên thì
   vô hiệu recap của scope và dựng lại, không tiếp tục phát bản cũ.
6. Refresh host memory snapshot sau commit. Cùng projection policy áp vào Self
   summary và context compiler. Default chỉ cửa sổ mới + recap; hỏi cụ thể thì
   search nguồn cũ rồi đưa chi tiết liên quan trở lại có budget, tránh lặp recap
   ở cả Self và runtime context. Recap là diễn giải thứ cấp, không phải receipt
   hoàn tất hành động hay evidence mới để tự reinforce profile.
7. Trên đĩa giữ mốc chuẩn cho từng phần kể; khi render mới đổi thành “mấy hôm
   trước”, “tuần trước”, “cuối tháng 10/2026” theo timezone người dùng. Không
   persist “tuần trước” thiếu anchor; một generated_at cho toàn đoạn cũng không
   đủ gán tuổi cho nhiều sự kiện. Có thể lưu đoạn/anchor nội bộ rồi ghép thành
   một đoạn tự nhiên. Không gọi Gemini chỉ để đổi nhãn ngày.
8. Không xóa nguồn vì đã recap. Nếu cam kết truy lại, phải archive bền trước
   compact/trim và có lookup ID/evidence. Forget/hard-delete áp cả archive/recap;
   không tạo kho miễn trừ việc quên. Không trộn project/private vào recap global.
9. Open loop không tự completed hoặc biến mất do tuổi. Giữ trạng thái trong
   episode/action continuity và chọn lọc khi đưa prompt; không tự nâng mọi câu
   xã giao thành commitment hoặc pin toàn episode vô hạn vì có open_loop.

## Ngưỡng bắt đầu thử nghiệm

| Tham số | Đề xuất v1 |
|---|---|
| Chi tiết mặc định | Tối đa 4 episode mới nhất trong 7 ngày, ưu tiên session đang hoạt động |
| Tập cũ | Ngoài cửa sổ chi tiết hoặc quá 7 ngày; chỉ snapshot ổn định, chưa rollup bản đang tiếp tục ghi |
| Trường chi tiết | title, summary, open_loops; outcome cần thiết cho trạng thái; nhãn thời gian tự nhiên |
| Recap | Khoảng 600 token tổng cho các scope được phép đưa vào một prompt |
| Batch | Tối đa 8 episode/lần, backfill từ cũ tới mới rồi tiếp tục vòng nền sau |
| Budget mặc định | Thử trần 3.000 token phần episode mới + recap; giảm số episode nếu không vừa, không cắt ngang ý |
| Recall chủ đích | Tối đa 2 episode nguồn liên quan với budget rõ và loại nội dung trùng |

Session lâu mà vẫn ghi cần checkpoint ổn định hoặc cách chia episode, không bỏ
khỏi rollup mãi vì session_id không đổi. Budget trên không phải budget toàn Self.
Đo bằng tokenizer/payload thật; count episode và chars/3 không chứng minh token.

## Nghiệm thu trước khi áp vào ký ức thật

- Restart/maintenance không delta: 0 model call rollup và recap không đổi.
- Thêm nguồn mới chỉ gửi recap cũ + delta; cùng ID đổi nội dung phải được nhận ra.
- Crash/write failure/concurrent add/correct/forget không gây checkpoint giả,
  mất cập nhật hoặc ghi đè candidate cũ; retry không commit hai lần.
- Qua ngày/tuần/tháng nhãn thời gian đúng, không thêm model call vì đồng hồ.
- Scope/forget/hard-delete áp cả recap và archive; lookup nguồn còn tồn tại.
- Nhiều vòng rollup giữ phủ định, correction, attribution, lời đùa và trạng thái
  chưa xong trong fixture có kiểm nội dung; không coi test schema là đủ.
- Request Root cho thấy cửa sổ mới + recap có budget, refresh qua bootstrap/delta,
  không còn 8 episode cũ lặp qua Self. Đo token và model call riêng trước/sau.
- Dedup MemoryAICurator kho episodic được sửa/kiểm riêng. Không tuyên bố hết
  re-distill toàn hệ chỉ vì recap Living User đã pass.

Chưa chạy các nghiệm thu trên hoặc kiểm portable trùng source trong lượt này.
