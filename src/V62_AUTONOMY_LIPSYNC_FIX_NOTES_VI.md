# V62 — Autonomous Surface Recovery + Live2D Mouth Liveness

## Vì sao sửa

Log thực tế `eris_run_20260812_220139.txt` cho thấy startup V61 đã sống lại và Eris có thể tự nói. Tuy nhiên có hai lỗi hành vi còn rõ:

1. **Autonomous hay im và UI trông như báo lỗi**: candidate/urge mới được tạo, Neuro chọn `SPEAK`, nhưng Surface đôi lúc trả lại nguyên câu autonomous cũ. Bộ chống lặp chặn câu đó và lifecycle phát `DEGRADED`, khiến Body hiển thị như một lỗi runtime dù đây chỉ là một lượt wording thất bại.
2. **Một số đoạn có tiếng nhưng miệng đóng**: audio playback đã bắt đầu nhưng mouth probe có thể nhận `ratio=0`, `ParamMouthOpenY≈-1`. Envelope lỗi/sparse trước đây vẫn có thể được tin chỉ vì có một peak đơn độc.

## Sửa autonomous

- Surface được phép **rewrite đúng một lần** khi output đầu bị phát hiện trùng public line gần nhất.
- Rewrite vẫn dùng **chính Surface worker**. Không cho companion/critic giả làm Surface, không dùng câu canned local.
- Request retry mang `rewrite_required`, intent hiện tại, rejected text và nonce riêng để tránh proxy/cache trả lại nguyên response cũ.
- Nếu retry vẫn trùng, V61 suppression/cooldown vẫn hoạt động. Không loop vô hạn.
- Dedupe, grounding veto và utterance safety veto giờ kết thúc lifecycle bằng `DONE` thay vì `DEGRADED`. Đây là **im có chủ đích**, không phải cognition chết.
- Body phân biệt transient autonomous Surface failure với runtime error thật; hiển thị `Lời chủ động hụt một nhịp, sẽ thử lại` thay vì báo lỗi đỏ.
- Cadence mặc định bớt ì: post-chat grace 10s (min 5s), autonomous schedule 18/28/42/60s; suppressed schedule 8/12/18/26s. InitiativeController vẫn là cổng chống chen ngang/spam.

## Sửa mouth / lip-sync

- Envelope audio không còn được tin chỉ vì có một peak.
- Kiểm thêm tỷ lệ frame voiced và độ khớp giữa số frame với audio duration.
- Envelope quá sparse hoặc metadata duration lệch mạnh sẽ bị bỏ, pseudo-viseme theo text tiếp quản.
- Mouth probe được re-arm tại `audio_playback_started` thật và lấy ba mẫu 0.18s / 0.45s / 0.90s, tránh chụp đúng leading silence rồi tưởng môi chết.

## Không thay đổi

- `src/body` được **giữ nguyên vị trí** theo cấu trúc project hiện tại của chủ dự án.
- Không bật cross-worker Surface fallback mặc định.
- Không ép Eris nói khi boundary/interruption gate bảo nên im.
- Không ép môi mở liên tục trong khoảng silence thật của audio.

## Kiểm tra

Chạy:

```bat
run_v62_runtime_probe.bat "C:\path\to\eris_run_....txt"
```

Log mới nên xuất hiện `duplicate rewrite recovered` nếu Surface lần đầu lặp nhưng tự cứu được. Khi TTS chạy, `[Live2D][Mouth]` sẽ có nhiều mẫu cho mỗi đoạn thay vì chỉ một mẫu sớm.
