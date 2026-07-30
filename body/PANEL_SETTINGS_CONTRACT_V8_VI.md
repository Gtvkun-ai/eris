# Panel Settings Contract v8

## Nguồn sự thật

| Nhóm | Owner | Nơi lưu / giao thức | Cách áp dụng |
|---|---|---|---|
| Giao diện Body | `body_local` | `user://eris_settings.json` | Lưu ngay trong Body |
| Policy runtime | `brain_runtime` | `runtime_settings.json` do Brain sở hữu | `settings_health` / `settings_update` |
| Route khởi động và credential | `bootstrap_credentials` | `config/secrets.json`, provider profile và bốn biến `ERIS_REMOTE_*` trong `.env` | Lưu rồi restart Brain |
| Tác vụ nguy hiểm | `maintenance` | Maintenance protocol | ACK riêng theo action |

Body không ghi trực tiếp `runtime_settings.json`. Tab Advanced và Voice dựng control từ catalog mà Brain trả về, không tự đoán schema.

## Tab

- **Basic**: trạng thái process, thao tác start/stop/restart, TTS nhanh và state cửa sổ. Nút lưu chỉ ghi state Body.
- **Giọng nói**: toàn bộ `tts.*` theo schema Brain, gồm provider, ElevenLabs Voice ID/model, Gemini voice, chất lượng, voice director và speech persona.
- **Kết nối & dữ liệu**: route Main Brain và credential. Có bốn owner độc lập: `main`, `gemini`, `groq`, `elevenlabs`.
- **Advanced**: toàn bộ section runtime ngoài `tts.*`; hiển thị raw path, giá trị hiệu lực, default, kiểu input, range/enum và dấu cần restart.
- **Danger Zone**: action maintenance. Policy `danger_zone.*` vẫn là runtime setting và xuất hiện trong Advanced.

## Credential mapping

- `main`: `DEEPSEEK_API_KEY`, `ERIS_REMOTE_API_KEY`, `ERIS_REMOTE_FALLBACK_API_KEYS`, cùng `providers.<provider>.remote_main`.
- `gemini`: `GEMINI_API_KEY`, `ERIS_PRIVATE_MIND_API_KEY`, các fallback Gemini/private mind.
- `groq`: `ERIS_GROQ_API_KEY`, `ERIS_GROQ_FALLBACK_API_KEYS`.
- `elevenlabs`: `ELEVENLABS_API_KEY` hoặc alias `ERIS_ELEVENLABS_API_KEY`. Runtime hiện dùng một key ưu tiên.

Panel không gửi hoặc hiển thị raw key trong health ACK. Chỉ fingerprint SHA-256 rút gọn được dùng để ghép trạng thái runtime với dòng credential.
