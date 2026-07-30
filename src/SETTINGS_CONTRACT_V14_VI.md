# Runtime Settings Contract v14

Brain là authority duy nhất cho policy runtime. `RuntimeSettingsStore.defaults()` định nghĩa schema; `runtime/settings_catalog.py` xuất catalog không chứa credential cho Body.

## Catalog

- 24 section.
- 196 path runtime.
- 19 field enum.
- 56 field có giới hạn số lấy từ validator thật.
- Mỗi field có: `path`, `section`, `key`, `label`, `kind`, `default`, `value`, `owner`, `surface`, `restart_required` và constraint nếu có.

## Scope

- `scope=tts`: chỉ nhận `tts.*`.
- `scope=advanced`: nhận mọi section runtime ngoài `tts.*`, gồm `danger_zone.*` policy.
- `scope=personality`: chỉ nhận `personality.*`.
- `scope=runtime`: dành cho internal/full runtime control.

Field sai scope được đưa vào `rejected`; Body không được tự ghi file store để lách protocol.

## Health ACK

`settings_health_ack` trả:

- snapshot hiệu lực và catalog;
- Main Brain provider/model/fingerprint;
- pool `main`, `gemini`, `groq`;
- credential health tổng hợp của `elevenlabs`, chỉ có fingerprint;
- TTS provider, language, voice, ElevenLabs voice/model, quality, volume, speed và trạng thái engine.

Credential không nằm trong runtime settings catalog hoặc snapshot.
