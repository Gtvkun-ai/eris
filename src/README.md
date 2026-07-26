# ERIS Runtime

ERIS là runtime companion AI theo kiến trúc AI-orchestrated, tập trung vào **engagement dài hạn**: chơi cờ, pair programming, học có hướng dẫn, luyện tập, theo dõi build/deployment và các hoạt động nền khác. Chat và autonomous runtime dùng chung lifecycle, evidence binding, interaction contract, attention policy, persistence và event delivery.

## Trạng thái V36

- `RuntimeCoordinator` giữ vai trò composition root, còn **136 dòng**; `__init__` 26 dòng.
- Bootstrap chia thành sáu pha có health, cleanup và failure classification riêng.
- Engagement domain dùng profile registry, không cần sửa detector core khi thêm loại hoạt động mới.
- Engagement tự chuyển lifecycle theo evidence: active, waiting, paused, completed hoặc cancelled.
- Event stream dùng cursor toàn cục, hash chain chống sửa âm thầm và checkpoint theo consumer.
- Adapter state có thể replay từ event history để audit hoặc sửa projection khi lịch sử còn đầy đủ.
- Consumer delivery có lease, retry/backoff, dead-letter, poison-event isolation và durable commit receipt.
- Snapshot registry có digest; persistence có **journal hai thế hệ** gồm primary và last-known-good backup.
- Journal phát hiện primary bị sửa, bị tráo, rollback về revision cũ hoặc metadata/cursor không khớp.
- Khi primary hỏng nhưng backup còn nguyên, runtime tự fallback và có thể repair primary theo policy typed.
- Runtime diagnostics schema v6 hiển thị journal health, readiness, receipt integrity, recovery audit, SLO và incident history.
- Runtime settings schema v13 cấu hình snapshot journal và auto-repair cùng các delivery policy trước đó.
- Source ZIP được tạo reproducible; verifier chặn path traversal, symlink, duplicate entry, encryption và compression bomb.
- CI khóa architecture, exception debt, release manifest và runtime branch coverage tối thiểu **36,0%**.


## DeepSeek mặc định

Não chính hiện dùng DeepSeek qua endpoint OpenAI-compatible chính thức:

```env
ERIS_REMOTE_PROVIDER=deepseek
DEEPSEEK_API_KEY=PASTE_DEEPSEEK_API_KEY_HERE
ERIS_REMOTE_BASE_URL=https://api.deepseek.com
ERIS_REMOTE_MODEL=deepseek-v4-flash
ERIS_DEEPSEEK_THINKING=disabled
```

ShopAIKey và các biến `ERIS_AGGREGATOR_*` đã bị loại khỏi runtime. DeepSeek được
dùng cho text, JSON và escalation; image caption vẫn đi qua vision local hoặc
một endpoint multimodal riêng được cấu hình rõ ràng. V36 thêm companion-aware
routing: Flash xử lý lượt rõ và nhanh; Pro xử lý hàm ý, trừu tượng, chiều sâu
quan hệ và yêu cầu văn phong. Thiếu dữ kiện bắt buộc thì Eris hỏi lại thay vì
dùng Pro để đoán. Xem `DEEPSEEK_MIGRATION.md`, `DEEPSEEK_COMPANION_ROUTING_V36.md`
và `config/deepseek.env.example`.

## Kiểm tra nhanh

```bash
python tools/check_architecture.py
python tools/audit_exception_boundaries.py --check
python tools/check_release_manifest.py
python -m pytest --cov=runtime --cov-branch --cov-fail-under=36.0 -q
```

Đóng gói và kiểm tra cả source lẫn chính file ZIP:

```bash
python tools/verify_release.py --archive ../eris_runtime_release.zip
```

Kiểm tra trực tiếp một archive đã tồn tại mà không chạy source tree trước:

```bash
python tools/verify_release.py --verify-existing ../eris_runtime_release.zip
```

Verifier kiểm tra cấu trúc ZIP trước khi giải nén, giới hạn kích thước và compression ratio, giải nén an toàn vào thư mục tạm, rồi chạy compile, architecture/exception/manifest gates, toàn bộ test và coverage.

## Cấu trúc runtime chính

```text
RuntimeCoordinator
├── CoordinatorBootstrapMixin
├── ModelMemoryRuntimeMixin
├── PublicOutputRuntimeMixin
├── UserControlRuntimeMixin
├── CoordinatorShutdownMixin
├── AutonomousLoopRuntimeMixin
├── ObserverPrivateRuntimeMixin
├── CognitiveEventRuntimeMixin
├── MentalProcessRuntimeMixin
├── IncomingProtocolRuntimeMixin
├── SettingsControlRuntimeMixin
├── TutorResearchRuntimeMixin
├── ScreenVisionRuntimeMixin
└── ProviderActionRuntimeMixin
```

Logic domain mới phải đi vào boundary, service hoặc engagement profile riêng. Architecture audit sẽ từ chối việc nhét method trở lại coordinator hoặc làm mất durability, delivery, snapshot journal và readiness contracts.

## Chỉ số release

- Project version: `0.36.0`
- Test: **363 pass**
- Runtime branch coverage: **36,42%**
- Broad exception handlers: **1.085**
- Silent exception handlers: **162**
- Settings schema: **v13**
- Engagement snapshot schema: **v7**
- Engagement snapshot journal schema: **v1**
- Runtime diagnostics schema: **v6**
- Machine-readable metrics: `RELEASE_MANIFEST.json`

## Tài liệu

- `DEEPSEEK_MIGRATION.md`: cấu hình và hành vi DeepSeek.
- `DEEPSEEK_COMPANION_ROUTING_V36.md`: policy Flash/Pro cho companion chat.
- `DEEP_STABILIZATION_RELEASE_V35.md`: release chuyển provider lịch sử.
- `DEEP_STABILIZATION_RELEASE_V34.md`: release V31-V34 lịch sử.
- `DEEP_STABILIZATION_RELEASE_V30.md`: release V27-V30 lịch sử.
- `DEEP_STABILIZATION_RELEASE_V26.md`: release V23-V26 lịch sử.
- `DEEP_STABILIZATION_RELEASE_V22.md`: release V19-V22 lịch sử.
- `DEEP_STABILIZATION_RELEASE_V18.md`: release V15-V18 lịch sử.
- `DEEP_STABILIZATION_RELEASE_V14.md`: release V10-V14 lịch sử.
- `DEEP_STABILIZATION_RELEASE.md`: release V5-V9 lịch sử.
- `ENGAGEMENT_IMPLEMENTATION.md`: engagement kernel và adapter.
- `STABILIZATION_IMPLEMENTATION.md`: harness và health registry.
- `ERIS_REPO_AUDIT_VI.md`: audit ban đầu và nợ kỹ thuật.
