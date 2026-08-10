# Eris UIAccess broker

Broker này chỉ dành cho accessibility cross-integrity. Core Eris **không** cần chạy Administrator.

Điều kiện triển khai:

1. Build `eris-uiaccess-broker.exe` với manifest `uiAccess="true"`.
2. Ký executable bằng code-signing certificate hợp lệ.
3. Cài vào `Program Files` hoặc vị trí protected tương ứng policy Windows.
4. Cấp `ERIS_UIACCESS_BROKER_AUTHKEY` qua launcher/process environment.
5. Chỉ bật `ERIS_UIACCESS_BROKER_ENABLED=1` khi broker đã cài đúng.

Broker không có OCR, memory, LLM, clipboard plaintext hay command execution. API hiện chỉ có `ping`, `window_metadata`, `accessibility_metadata`; password control là hard block.
