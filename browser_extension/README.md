# ERIS Browser Bridge

Extension cho Brave/Chrome để cung cấp tab metadata, media state và visible text cho ERIS AI companion qua **Browser DOM Bridge (L4)** — không cần OCR, không cần screenshot.

## Cấu trúc

```
browser_extension/
├── manifest.json          # Extension manifest MV3
├── background.js          # Service worker (coordinator)
├── content.js             # Content script (đọc từng tab)
├── popup.html             # Status popup
├── icons/                 # Icon (tự tạo hoặc thay thế)
├── install.bat            # Cài đặt native host + registry
├── test_bridge.py         # Kiểm tra bridge đang hoạt động
└── native_host/
    ├── eris_bridge_host.py         # Python native messaging host
    ├── eris_bridge_host.bat        # Launcher (Chrome gọi .bat)
    └── com.eris.browser_bridge.json # Native host manifest
```

## Luồng dữ liệu

```
Tab (YouTube/Spotify/...) 
  → content.js (đọc Media Session API + DOM)
    → background.js (ghép + gửi qua Native Messaging)
      → eris_bridge_host.py (Python)
        → %LOCALAPPDATA%\ERIS\browser_dom_state.json
          → ERIS ContentMetadataCollector (L4 DOM Bridge)
```

## Cài đặt (chỉ làm 1 lần)

### Bước 1 — Load Extension vào Brave
1. Mở Brave → `brave://extensions`
2. Bật **Developer mode** (góc phải trên)
3. Nhấn **Load unpacked** → chọn thư mục `browser_extension/`
4. Ghi lại **Extension ID** (dạng 32 chữ cái, ví dụ: `abcdefghijklmnopabcdefghijklmnop`)

### Bước 2 — Cài Native Host
1. Chạy `install.bat` (không cần Admin)
2. Nhập Extension ID khi được hỏi
3. Restart Brave

### Bước 3 — Kiểm tra
```bash
python test_bridge.py
```
Nếu thấy URL và media state cập nhật mỗi 2-3 giây → hoạt động tốt.

## Output file

```json
{
  "timestamp": 1754000000.0,
  "source": "browser_dom",        // hoặc "media_session" nếu có media
  "confidence": 0.92,
  "url": "https://music.youtube.com/watch?v=xyz",
  "title": "Tên bài hát - YouTube Music",
  "media_title": "Tên bài hát",
  "creator": "Tên ca sĩ",
  "media_state": "playing",       // "playing" | "paused" | "stopped"
  "page_kind": "youtube_music",
  "visible_text": "...",
  "all_tabs": ["Tab 1", "Tab 2"]
}
```

## Domains được hỗ trợ đặc biệt
- **YouTube / YouTube Music**: đọc title, channel, playback state từ DOM
- **Spotify Web Player**: đọc track name, artist từ DOM
- **Tất cả trang khác**: đọc qua Media Session API (nếu trang hỗ trợ) + URL/title
