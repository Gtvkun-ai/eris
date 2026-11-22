# ERIS Live Studio — P4–P7 | Triển khai source, ngày 21/11/2026

> **Trạng thái:** Đã thêm code Python + Godot C# + web UI, chạy được test offline. **Chưa build Godot .NET trên Windows, chưa đo TikTok/OBS/TTS thật.** Đây không phải lời khẳng định production-ready. Kế thừa P0–P3 được đóng gói trong ZIP tích hợp trước đó.

## 1. Phương án và nguyên tắc

Không thêm showmanship state machine, pin xã hội 30%, persona phụ hay AI streamer điều khiển Root. TikTok là nguồn dữ liệu **không đáng tin** đi qua `LiveIngress` → session công khai → ConversationKernel/RootAgent → Writer/public-output gate → TTS/Live2D. Chat và ký ức riêng của chủ không được đưa vào phiên live; bình luận ngoài không thể gọi capability, đọc memory hoặc điều khiển mục tiêu Root.

Panel điều khiển nằm trong **cùng portal Rich Chat của Eris** trên `127.0.0.1` với đường dẫn token ngẫu nhiên. Không tạo HTTP listener mới. Trình duyệt gửi cùng origin tới API của Godot, Godot chuyển `live_control` qua UDP nội bộ 4243; Python xử lý và trả `live_studio_status` tới UDP 4242. **HTTP 202 chỉ là “đã xếp hàng”; panel hiển thị thành công khi đã có ACK từ Cortex.**

## 2. Đã làm

### P4 — Live Control Center

- `src/body/richchat/live.html`, `live.css`, `live.js`: dashboard status, Connect TikTok room (chỉ nghe sự kiện phòng đã phát, không tự mở broadcast), Start Simulator, Stop, Emergency Stop, feed sự kiện, counters, lỗi/blocked reason, kiểm tra privacy, TTS và Root.
- `src/body/UdpListener.LiveStudioPortal.cs`: điều khiển qua hàng đợi main-thread, snapshot cache, lọc gói UDP chỉ nhận từ loopback, chỉ cho action nằm trong allowlist.
- `src/body/UdpListener.RichChatPortal.cs`: API `GET api/live/state`, `POST api/live/control` (token + Host + Origin; giới hạn size); bundle 6 asset web mới.
- `src/runtime/live/control.py`: xử lý `status`, `start_live`, `start_simulator`, `stop`, `emergency_stop`, `simulate`, `tick`, `validate`. `request_id` đi cùng ACK hoặc NACK. `start_live` không tuyên bố “connected” trước khi provider báo kết nối.
- 5 scenario không dùng TikTok: `conversation`, `crowd`, `gifts`, `support`, `injection`. Có thể nhập comment kiểm thử tối đa 300 ký tự. Simulator đi qua ingress thật, KHÔNG mô phỏng lời đáp của model.

### P5 — Voice, Live2D, OBS

- Giữ nguyên StageEventBus và Live2D hiện có; **không viết renderer hoặc TTS engine mới**.
- `src/runtime/public_output_runtime.py` ghi `on_audio_started(delivery_id)` vào runtime Live khi nhận `audio_start` của TTS; `audio_done/failed/cancelled` đã được cập nhật qua speech outcome trước đó. Dashboard phân biệt `delivery` (vào pipeline) với `audio_delivered` (đã có receipt).
- `src/body/richchat/live-overlay.html`, `.css`, `.js`: **phụ đề Browser Source nền trong suốt** cho OBS. Chỉ hiện khi phiên active, status còn mới và có `audio_start` phù hợp; tự ẩn khi audio kết thúc/hủy. Nội dung dùng `textContent`, không `innerHTML`.
- Nút **Sao chép URL Browser Source** trên Live Studio. URL chứa token local, chỉ dùng trong OBS trên cùng máy, không gửi cho người lạ.
- **Giới hạn cố ý:** Chưa có per-session voice override an toàn. Nếu TTS cài đặt hiện là `ja` thì start bị từ chối; cần đặt TTS `vi` trong Runtime Settings (không chỉ thay `language_hint`). Chưa tự điều khiển OBS, chọn thiết bị output hoặc kiểm chứng âm thanh sau mixer.

### P6 — Validation

- `src/runtime/live/validation.py` cung cấp 5 probe cô lập, không đụng phiên thật: 1.000 sự kiện/giới hạn queue, dedup, gift streak 1→5→20→50, invalidation epoch, persistence không rò tên/chat. Nút chạy offline ngay trên dashboard.
- `src/runtime/live/connector.py` sửa lỗi quan trọng: không đóng event loop ngay sau `await client.start()` kiểu non-blocking. Sử dụng `await client.connect()` (blocking) hoặc await returned task nếu bản SDK khác; hỗ trợ `ConnectEvent`, `DisconnectEvent`, `LiveEndEvent` khi SDK có. Thư viện TikTokLive là bên thứ ba **không chính thức**, có thể thay đổi theo giao thức TikTok.
- Các bài test mới tại `tests/live/test_live_studio_control.py`, `test_connector_async.py` và `src/body/richchat/tests/live_studio.test.cjs`.
- **Chưa xác nhận** kết nối TikTok thật, camera ảo OBS, nguồn âm thanh, FPS/độ trễ hoặc livestream công khai. Không được hiểu 5 probe là phép chứng nhận production.

### P7 — Social Adaptation evidence

- `src/runtime/live/learning.py` chỉ lưu **thống kê vận hành tổng hợp** sau một phiên (thời lượng, event, batch, Root attempts, no_reply, audio_delivered, lỗi). Không lưu chat raw, viewer ID, nickname, gifts value, memory riêng hay transcript; lưu tối đa 20 phiên và đưa tối đa 3 phiên gần nhất vào `discourse_context` của Root như **evidence**, không như reward.
- **Mặc định TẮT**, chỉ lưu nếu `ERIS_LIVE_LEARNING_ENABLED=1`; file tại `<ERIS_HOME>/logs/live_experience_aggregate.json`.
- Không có cơ chế tự phát hiện phong cách được yêu thích, reward shaping theo tim/quà hay chuyển tính cách kiểu ép buộc. P7 ở đây là **lớp bằng chứng và lưu trữ an toàn**, chưa phải học xã hội dài hạn đã được chứng minh.

## 3. Cách áp dụng (Windows)

1. Backup repo Eris, tạo branch mới (ví dụ `feat/eris-live-studio-p4-p7`). **Không xóa thư mục `src/assets/live2d/`, audio và model gốc.**
2. Giải nén `eris-live-studio-change-only-20261121.zip` đè đúng đường dẫn trên repo Eris hiện tại, hoặc dùng bản source tích hợp nếu bạn đang dùng snapshot tương ứng.
3. Trong môi trường Python của Eris:

   ```powershell
   py -m pip install TikTokLive
   ```

   Chỉ cần SDK khi nhận sự kiện từ TikTok thật; Simulator không dùng SDK.
4. Bật feature trước khi khởi động Cortex:

   ```powershell
   $env:ERIS_LIVE_ENABLED = '1'
   $env:ERIS_LIVE_AUTOSTART = '0'     # Khuyên dùng: điều khiển bằng panel
   $env:ERIS_LIVE_LEARNING_ENABLED = '0'  # Tùy chọn đổi 1 để lưu số liệu ẩn danh
   ```

5. Trong **Settings Eris**, đặt **TTS language = `vi`** rồi kiểm tra Live Studio hiển thị **Voice · Vietnamese**. Nguồn sự thật `runtime_settings.json` có thể ưu tiên hơn `$env:ERIS_TTS_LANGUAGE`; chỉ đặt biến môi trường không bảo đảm đổi được cài đặt đã lưu.
6. Khởi động Eris Cortex và Godot như bình thường. Cần rebuild project Godot .NET từ `Eris.csproj` để C# và web embedded resources mới có hiệu lực. Trong cửa sổ **Hội thoại** của Eris, chọn **Live Studio** trên thanh điều hướng.
7. Bắt đầu bằng **Simulator**, bấm các kịch bản, quan sát ACK/queue/Root/no_reply và chạy **5 kiểm tra offline**. Sau đó mới mở buổi phát trong TikTok Live Studio/OBS trước, nhập TikTok `@username` và bấm **Kết nối phòng**. Đây là kết nối nhận sự kiện, **không phải lệnh bắt đầu phát TikTok**.

### OBS / TikTok Live Studio

- Tạo scene dọc **1080×1920** trong OBS. Capture Live2D Eris theo kiểu Window Capture; kiểm chứng viền tóc trong suốt trên máy thực tế, vì transparent framebuffer không đảm bảo mọi capture method giữ alpha.
- Trong Live Studio, bấm **Sao chép URL Browser Source**, thêm **Browser Source** vào OBS; đặt width=1080, height=1920, source URL dùng 127.0.0.1 kèm token. Phụ đề nằm phía trên vùng chat dưới màn hình; chỉnh vị trí trong `live-overlay.css` nếu cần.
- Với tiếng nói, cấu hình **Audio Output Capture** hoặc đường audio riêng phù hợp với output TTS của Eris; nghe qua OBS mixer và TikTok Live Studio để tránh mất tiếng hoặc phát hai lần. Browser Source phụ đề **không mang audio**.
- Đảm bảo TikTok Live Studio nhận đúng scene OBS qua Virtual Camera hoặc luồng stream phù hợp tài khoản. Phần này chưa thể xác nhận trong môi trường tạo ZIP.

## 4. Các file quan trọng thay đổi

| Nhóm | File |
|---|---|
| Controller Python | `src/runtime/live/control.py`, `validation.py`, `learning.py` |
| Runtime Python | `src/runtime/live/bridge.py`, `connector.py`, `contracts.py` |
| Root/Output integration | `src/runtime/incoming_dispatcher.py`, `src/runtime/public_output_runtime.py`, `src/runtime/conversation/delivery_adapter.py` |
| Godot portal | `src/body/UdpListener.LiveStudioPortal.cs`, `src/body/UdpListener.RichChatPortal.cs`, `src/body/UdpListener.cs` |
| UI / OBS | `src/body/richchat/live.*`, `live-overlay.*`, `index.html` |
| Tests | `tests/live/test_live_studio_control.py`, `test_connector_async.py`, `src/body/richchat/tests/live_studio.test.cjs` |
| Config | `.env.example` |

## 5. Chạy test offline

```powershell
# Từ thư mục gốc Eris:
$env:PYTHONPATH = 'src'
py -m unittest discover -s tests/live -p 'test_*.py' -v
node --test src/body/richchat/tests/*.cjs
```

Trong môi trường build ZIP (Linux, Python 3.13, Node 22), **49/49 Python tests** và **29/29 Node tests** qua, cùng 5/5 probes. Không có `dotnet`/Godot .NET SDK nên **chưa compile C#**, không có tài khoản TikTok/OBS và thiết bị âm thanh để xác nhận end-to-end.

## 6. Rollback / lỗi có thể gặp

- `ERIS_LIVE_ENABLED` off: xem được panel, không start live; cần bật + restart Cortex.
- `tts_config_blocked`: Settings TTS đang không phải tiếng Việt. Sửa `tts.language` trong runtime settings, không bypass gate.
- `TikTokLive_sdk_not_installed`: cài đúng package vào đúng interpreter chạy Eris.
- `waiting for Cortex`: portal Godot đang mở nhưng Python UDP 4243 không xử lý; kiểm tra Cortex chạy và hai cổng 4242/4243.
- `reconnecting`: SDK/đường mạng/room chưa kết nối; không mặc định suy ra đang live.
- Không có subtitle dù có text: chỉ hiện khi playback đã báo `audio_start`; kiểm tra TTS, tuyến audio và StageEventBus trước khi sửa overlay.
- Kết thúc buổi live / emergency stop: `room_epoch` vô hiệu hóa các kết quả cũ. **Nút này không đóng OBS hay phòng TikTok bên ngoài ứng dụng.**
- Rollback: dừng live, reset branch/khôi phục backup. Không xoá trực tiếp dữ liệu chat/asset của Eris. File thống kê P7 có thể tự xóa nếu muốn (không phải file ký ức chính).

## 7. Công việc vẫn cần kiểm chứng trên máy của bạn

1. Build `.csproj` và mở web portal Live Studio thực tế.
2. Chạy thử Simulator với LLM/TTS đang hoạt động; kiểm chứng `NoReply` và stage receipts.
3. Capture OBS và kiểm tra alpha, latency phụ đề và audio theo thiết bị thật.
4. Thử phòng TikTok thực; kiểm tra phiên bản TikTokLive, Room LiveEndEvent, gift streak, disconnect/reconnect, giới hạn rate.
5. Theo dõi nhiều phiên để đánh giá liệu phần evidence P7 có cải thiện cách Root trò chuyện — hiện chưa có bằng chứng thực nghiệm.
