# ERIS × TikTok LIVE — TÍCH HỢP VÀO CODE (21/11/2026)

> **Cơ sở:** snapshot `eris-ai-20261121_130732_514.zip`, không có toàn bộ binary/model/asset của repo local.
> **Bản này là triển khai có test offline, CHƯA được xác nhận qua TikTok thật/OBS/audio/DeepSeek thật.**
> Mục tiêu: **Một Root quyết định, nhiều audience session**; TikTok không có quyền đọc memory/chỉ đạo công cụ.

## 1. Đã thực sự code

| Pha | Nội dung | Trạng thái |
|---|---|---|
| P0 | Event schema, normalize, bounded queue, duplicate/TTL, gộp gift streak, like, comment | Đã code và có unit test offline |
| P1 | Public session, Root one-shot không dùng Self bootstrap cá nhân, cấm public tools/recall, tách history/diary, guard cũ, âm thanh receipt | Đã code và có test integration offline |
| P2 | Adapter TikTokLive tùy chọn, autostart opt-in, tích hợp Kernel→Writer→body/stage hiện có, kiểm tra tiếng Việt, shutdown | Code có, **chưa kết nối livestream thật** |
| P3 | Ghi thống kê phản ứng sau `audio_done`, chỉ aggregate trong RAM; Root có thể xem như bằng chứng không khẳng định nhân quả | Có nền tảng tối thiểu; **chưa tự học persona lâu dài** |

Không bổ sung `showmanship_runtime.py`, bốn trạng thái mặt nạ hoặc bộ SocialBattery cố định. `RootAgent` vẫn là thẩm quyền semantic duy nhất.

## 2. Cách chạy nhanh trên Windows

**Quan trọng:** dùng bản *change-only* chép vào repo Eris đang chạy (giữ nguyên mô hình, texture, preset, credential riêng). ZIP full là **snapshot đã lọc asset**, không thể thay thế toàn bộ repo production.

### Cài phụ thuộc TikTok (tùy chọn)

```powershell
cd C:\Users\<user>\Documents\GitHub\eris
py -m pip install TikTokLive
```

TikTokLive là thư viện **không chính thức**, dễ thay đổi schema, không có cam kết uptime hoặc quyền truy cập cho mọi tài khoản. Đọc điều khoản TikTok trước khi dùng; không dùng bot để né giới hạn.

### Bật live

Trước tiên, vào **Settings → TTS → Language**, chọn **Tiếng Việt (`vi`)**. Nếu setting vẫn `ja`, Live sẽ báo `tts_config_blocked` trước khi gọi Root/DeepSeek (không cố dịch hoặc âm thầm bật tiếng Nhật).

Với PowerShell mở tại thư mục repo:

```powershell
$env:ERIS_LIVE_ENABLED = '1'
$env:ERIS_LIVE_AUTOSTART = '1'
$env:ERIS_LIVE_UNIQUE_ID = '@YOUR_TIKTOK_USERNAME'
$env:ERIS_LIVE_BATCH_SECONDS = '5'
.\run_eris.bat
```

Nếu dùng `.env`, cần chắc chắn launcher của bạn thực sự nạp các biến vào `os.environ`. Cách PowerShell ở trên chắc chắn truyền cho process con.

Để **chạy offline không nối TikTok**:

```powershell
$env:PYTHONPATH='src'
py -m unittest discover -s tests/live -v
py tools/eris_live_smoke_offline.py
```

### Điều khiển khi runtime đang chạy

```python
# Trong Python host process (không phải một process bên ngoài):
from runtime.live import ensure_live_runtime
live = ensure_live_runtime(host)
live.start('@YOUR_TIKTOK_USERNAME', connect=True)  # đã opt-in và TTS vi
print(live.status())
live.stop()  # chủ sở hữu dừng; comment TikTok không thể gọi stop()
```

Hiện chưa có nút Start/Stop riêng trên giao diện web/Godot; có thể dùng cấu hình tự khởi động hoặc gọi từ host control layer. Không khuyên gửi lệnh dừng qua công khai chat TikTok.

### OBS / TikTok Live Studio

1. Mở mô hình Live2D trong repo local đầy đủ asset; tạo scene OBS dọc 1080×1920.
2. Window Capture đúng cửa sổ Live2D, kiểm tra nền alpha trên Windows; **không mặc định alpha luôn đúng**.
3. Bố trí model và phụ đề trong vùng tránh nút/khung comment, kiểm tra trực tiếp trên thiết bị.
4. Định tuyến **âm thanh TTS riêng** vào OBS/TikTok Live Studio (Virtual Camera chỉ mang video); kiểm tra lip-sync và âm thanh.
5. Chạy practice/offline trước, chỉ bật live thật khi kiểm tra được đường TTS/OBS/TikTok.

**Không có code tự mở OBS, tự cấu hình Virtual Audio Cable, bảo đảm 60 FPS hoặc bảo đảm được quyền stream key** trong bản này. Các bước trên phải làm trên PC thực tế.

## 3. Dataflow thực tế

```text
TikTokLive SDK (optional)
  -> connector.py handler (NO LLM)
  -> normalize.py
  -> intake.py (TTL + bounded queue + dedup)
  -> batcher.py (gift streak final; comments newest; likes aggregate)
  -> bridge.py (room_epoch, owner priority, speech floor, TTS vi check)
  -> public_context (ONLY allowlisted fields; optional numeric affect)
  -> ConversationKernel.handle_event(kind=live_signal, session=public_live:...)
  -> RuntimeModelRootAgent.decide (ONE-SHOT public, NO private RootSession)
  -> RuntimeConversationWriter (existing)
  -> RuntimeConversationDeliveryAdapter (public gate, NO owner history/journal)
  -> _send_decision_to_body() (body/stage; NO private panel, no private observation)
  -> TTS/StageEventBus/Live2D (existing; actual device unverified)
  -> audio_done -> live.session history + experience aggregate
```

### Cơ chế bảo mật chính

- **Trước model**: live context không gọi `ConversationContextAssembler` hay `_read_self` của owner. `RootConversationSession._prime` luôn bị bỏ qua trong public session. Cấm toàn bộ memory recall/capability/guide/batch cho public turn; nếu model vẫn đề xuất chúng, trả `NoReply`.
- **Trong kernel**: live không phải `user_turn`, không thay generation riêng tư; owner đang bận thì live hoãn. Lúc owner bắt đầu nói, `__live_guard` không cho live result cũ được commit.
- **Trước dispatch**: kiểm tra active room/epoch, `configured_speech_language() == 'vi'`, validate text/segments chống dạng token rõ ràng, guard tương tranh với STOP.
- **Sau dispatch**: không append `host.chat_history`, không ghi private journal, private behavior observation, private panel projection, hoặc `last_text` chung; chỉ room history nhận sau `audio_done`.
- **Khi STOP**: tăng room epoch, preempt kernel live session, xóa queue/history/aggregate. Nếu đang phát audio do live sở hữu, thử hủy riêng qua voice manager. Không tự cắt audio owner.
- **Caveat**: regex/allowlist KHÔNG chứng minh an toàn nội dung tuyệt đối. Cần review live output và privacy canary trên máy thật trước public launch.

## 4. Các file mới

```text
src/runtime/live/
  __init__.py
  contracts.py       typed LiveEvent / AudienceScope / counters
  normalize.py       giới hạn kích thước, provider field mapping
  intake.py          bounded + TTL + dedup
  batcher.py         comment/like/gift streak aggregation
  scope.py           public-only projection + output gate + safe affect
  session.py         public room history in RAM + delivery receipts
  lifecycle.py       active room epoch lease
  experience.py      P3 reception counters sau audio_done, không viewer ID
  connector.py       TikTokLive adapter optional + reconnect
  bridge.py          tích hợp ConversationKernel / owner priority

tests/live/
  test_ingress.py
  test_bridge.py
  test_root_scope.py
  test_delivery_integration.py
  test_experience.py
```

### File hiện có đã chỉnh

- `src/runtime/conversation/agent.py`: one-shot public + cấm tools, memory, continuation.
- `src/runtime/conversation/kernel.py`: live guard trước/giữa Root; không nạp work lane owner.
- `src/runtime/conversation/delivery_adapter.py`: tách sink, privacy/output gate, vi voice, room dispatch guard.
- `src/runtime/conversation/speech_outcome.py`: audio receipt tới session live riêng.
- `src/runtime/public_output_runtime.py`: không gửi private panel/plan/journal sang body live.
- `src/runtime/coordinator_bootstrap.py`: feature flag + autostart khi opt-in.
- `src/runtime/coordinator_shutdown.py`: STOP trước khi teardown các subsystem.
- `.env.example`: env config không chứa credential.

## 5. Kiểm thử đã chạy trong sandbox

```bash
PYTHONPATH=src python -m unittest discover -s tests/live -v
python -m compileall -q src/runtime/live src/runtime/conversation
```

Các ca kiểm: 1.000 sự kiện, queue overflow, dedup, TTL, gift 1→5→20→50→final, cùng msg_id qua streak, comment spam, like aggregation, room X/Y, owner impersonation, fail-closed khi không có provider, cấm `recall_memory`/`use_capability`, public Self không load, `NoReply` không dispatch, private canary vắng trong prompt live, owner history không bị ghi, `audio_done` mới làm lịch sử live trở thành delivered, STOP trong lúc Writer không phát stale, TTS ja bị chặn trước Root, regex secret gate.

**Không chạy DeepSeek Web test hay spam requests** vì nguy cơ Shumei của proxy người dùng. Chưa có phép đo FPS, TTS latency, RAM 10 phút thực, audio OBS hay quyền TikTok.

## 6. Hạn chế và việc còn phải xác nhận trên PC thật

1. **SDK event shape**: TikTokLive thay đổi theo phiên bản; phải test comment/gift/streak thật rồi chỉnh normalize field nếu cần. Code chỉ dùng import lazy, tránh bẻ app khi không cài SDK.
2. **Voice**: bản này dùng **cài đặt `vi` toàn cục**, không override giọng per-session. Nếu bạn muốn private Japanese trong khi live Vietnamese đồng thời, cần xây `SpeechContract` per-session xuyên suốt Stage/TTS trước khi bật hai kênh cùng lúc.
3. **Media**: snapshot source không có đầy đủ Live2D binaries/textures, không thể thực nghiệm render/OBS trong môi trường này.
4. **Control UI**: chưa có nút quản lý phòng live trong Settings web/Godot; autostart opt-in và `.stop()` của runtime đã có.
5. **P3**: đã có reception evidence của lời thực sự nói; chưa có learning profile lâu dài, viewer opt-in, approval/TTL persistence. **Không** tự cập nhật Identity từ likes/gifts chỉ để có vẻ chủ động.
6. **Live shutdown**: stop preempts các future delivery và cố hủy active live audio floor; không bảo đảm audio đã buffer ngoài hệ thống hoặc OBS không trễ thêm một đoạn trên tất cả máy.
7. **Integration rộng**: 35+ test offline đã chạy. Các full repo tests có thể thiếu vì snapshot export đã lọc phần lớn test/media. Cần chạy full test của repo local trước merge production.

## 7. Cách rollback

- Đặt `ERIS_LIVE_ENABLED=0`, `ERIS_LIVE_AUTOSTART=0`, restart — module optional không mở kết nối.
- Vì thay đổi có sửa các core file, nếu muốn rollback **code** thì dùng Git hoặc áp lại file từ backup/repo gốc; chỉ xóa `src/runtime/live/` là không đủ để trả mọi core diff.
- Trước khi chép đè, tạo nhánh `feat/eris-public-live` và commit snapshot đang chạy. Đừng ghi đè folder `src/assets/live2d/` bằng export thiếu binary.
