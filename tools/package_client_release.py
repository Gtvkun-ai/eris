# -*- coding: utf-8 -*-
"""tools/package_client_release.py
Dong goi ban phan phoi sach (Eris Clean Client Pack) cho khach / nguoi dung cuoi.
Dam bao:
- Day du runtime, tools, engine Live2D (Eris.exe) va cac script khoi chay bat.
- TUYET DOI KHONG chua API key that, khong chua database (.db), khong chua tai khoan ca nhan.
- Loai bo cac thu muc nang khong can thiet (model cache 1GB, .git, .venv...).
- Kem tai lieu tri thuc huong dan cai dat va khac phuc su co chi tiet nhat cho khach.
"""

import os
import re
import sys
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "exports"
OUTPUT_ZIP = OUTPUT_DIR / "Eris_Client_Pack.zip"
OUTPUT_DOC = OUTPUT_DIR / "HUONG_DAN_CAI_DAT_VA_KHAC_PHUC_SU_CO.md"

# Danh sach thu muc bo qua hoan toan
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "node_modules", "logs", "log", "cache", ".cache",
    ".eris_home", ".eris_state", ".v57_runs", "v57_reports", "scratch",
    "runtime_state", "state", "memory_core", "exports", "output", "tmp",
    "docker-data", ".tmp", "paraphrase-multilingual-MiniLM-L12-v2", "embedding_model",
    "data_cache", "build", "dist"
}

# Duoi file bo qua hoan toan
SKIP_EXTENSIONS = {
    ".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3",
    ".pyc", ".pyo", ".pyd", ".log", ".tmp", ".bak",
    ".pdb", ".vsix"
}

# Cac file nhay cam cam tuyet doi khong duoc dong goi
SENSITIVE_PATTERNS = [
    re.compile(r"accounts.*\.csv$", re.IGNORECASE), # chi giu template
    re.compile(r"elevenlabs_pool\.db$", re.IGNORECASE),
    re.compile(r"whale2api\.db.*", re.IGNORECASE),
    re.compile(r"gemini_credentials\.json$", re.IGNORECASE),
    re.compile(r"audit\.db$", re.IGNORECASE),
    re.compile(r"subject\.db$", re.IGNORECASE),
]

FULL_KNOWLEDGE_GUIDE = r"""# HƯỚNG DẪN CÀI ĐẶT, VẬN HÀNH & XỬ LÝ SỰ CỐ ERIS AI

Tài liệu này tổng hợp toàn bộ các bước thiết lập từ số 0, cách nạp tài khoản AI miễn phí và cách khắc phục mọi lỗi thường gặp khi chạy Eris AI trên hệ điều hành Windows.

---

## MỤC LỤC
1. [Yêu Cầu Môi Trường (Cài 1 lần duy nhất)](#1-yêu-cầu-môi-trường-cài-1-lần-duy-nhất)
2. [Quy Trình Khởi Động Chuẩn Thứ Tự](#2-quy-trình-khởi-động-chuẩn-thứ-tự)
3. [Hướng Dẫn Nạp DeepSeek Web Pool (Whale2API)](#3-hướng-dẫn-nạp-deepseek-web-pool-whale2api)
4. [Hướng Dẫn Nạp ElevenLabs Voice Pool (TTS Giọng Nói)](#4-hướng-dẫn-nạp-elevenlabs-voice-pool-tts-giọng-nói)
5. [Khắc Phục Sự Cố Thường Gặp (Troubleshooting)](#5-khắc-phục-sự-cố-thường-gặp-troubleshooting)
   - [Lỗi 1: Eris Live2D bị hộp chữ nhật nền đen](#lỗi-1-eris-live2d-bị-hộp-chữ-nhật-nền-đen-không-trong-suốt)
   - [Lỗi 2: Lỗi thiếu secret key / API Key](#lỗi-2-báo-lỗi-thiếu-api-key-khi-mở-visionpy)
   - [Lỗi 3: Ping DeepSeek báo thiếu mật khẩu](#lỗi-3-bấm-ping-deepseek-báo-thiếu-mật-khẩu-缺少密码)
   - [Lỗi 4: Lỗi Firebase 400 INVALID_REFRESH_TOKEN](#lỗi-4-lỗi-đổi-token-từ-firebase-400-invalid_refresh_token)

---

## 1. YÊU CẦU MÔI TRƯỜNG (CÀI 1 LẦN DUY NHẤT)

Trước khi khởi chạy, máy tính của bạn cần cài đặt 4 gói phần mềm nền tảng sau:

1. **Microsoft Visual C++ 2015-2022 Redistributable (x64) [BẮT BUỘC]:**
   - Link tải trực tiếp: https://aka.ms/vs/17/release/vc_redist.x64.exe
   - *Tác dụng:* Chạy thư viện đồ họa Live2D, âm thanh miniaudio và sounddevice.

2. **Python 3.12 (64-bit) [BẮT BUỘC]:**
   - Link tải trực tiếp: https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe
   - ⚠️ **LƯU Ý CỰC KỲ QUAN TRỌNG:** Ở màn hình cài đặt đầu tiên, bạn **PHẢI TÍCH CHỌN** ô:
     `[x] Add python.exe to PATH`
     *(Nếu không tích, Windows sẽ không nhận lệnh python khi chạy các file .bat)*.

3. **.NET Desktop Runtime 8.0 (x64) [BẮT BUỘC]:**
   - Link tải: https://dotnet.microsoft.com/en-us/download/dotnet/8.0 (Chọn mục **.NET Desktop Runtime x64**).
   - *Tác dụng:* Chạy giao diện nhân vật tương tác Godot (`Eris.exe`).

4. **Docker Desktop [KHUYẾN NGHỊ ĐỂ CHẠY DEEPSEEK WEB & VISION]:**
   - Link tải: https://www.docker.com/products/docker-desktop/
   - Cài đặt với tùy chọn WSL2. Sau khi cài, mở Docker Desktop lên và chờ biểu tượng góc trái dưới đáy chuyển sang màu xanh lá cây (**Engine running**).

---

## 2. QUY TRÌNH KHỞI ĐỘNG CHUẨN THỨ TỰ

Để hệ thống vận hành trơn tru không bị thiếu dịch vụ, bạn thực hiện theo 4 bước sau:

* **Bước 1: Cài đặt thư viện tự động (Chỉ làm lần đầu tiên)**
  - Bấm đúp chuột vào file: `run_doctor.bat`
  - Hệ thống sẽ tự động tạo môi trường ảo Python (`.venv`) và tải tất cả các thư viện cần thiết.

* **Bước 2: Khởi động các cổng kết nối AI ngầm**
  - Bấm đúp chuột vào file: `start_all_tools.bat`
  - Script sẽ tự động bật Docker (DeepSeek Whale2API + Gemini Vision) và mở trang web quản lý tài khoản **Account Hub** tại địa chỉ: `http://127.0.0.1:9000`.

* **Bước 3: Nạp tài khoản AI vào Hub**
  - Mở trình duyệt tại `http://127.0.0.1:9000`.
  - Nạp token DeepSeek (để suy nghĩ) và token ElevenLabs (để nói chuyện) theo hướng dẫn ở Phần 3 & Phần 4 bên dưới.

* **Bước 4: Đánh thức Eris**
  - Bấm đúp chuột vào file: `run_eris.bat`
  - Eris sẽ xuất hiện trên màn hình desktop và bắt đầu trò chuyện cùng bạn.

* **Khi muốn tắt hoàn toàn hệ thống:**
  - Đóng cửa sổ Eris.
  - Bấm đúp chuột vào file: `stop_all_tools.bat` để dừng toàn bộ containers Docker, giải phóng hoàn toàn RAM cho máy tính.

---

## 3. HƯỚNG DẪN NẠP DEEPSEEK WEB POOL (WHALE2API)

Whale2API giúp bạn kết nối tài khoản DeepSeek Web miễn phí để làm "bộ não" cho Eris mà không cần nạp thẻ visa mua API trả phí.

### Các bước lấy Cookie Token:
1. Mở trình duyệt Google Chrome hoặc Edge, truy cập: https://chat.deepseek.com và đăng nhập tài khoản của bạn.
2. Nhấn phím `F12` (hoặc chuột phải chọn **Inspect / Kiểm tra**) để mở Developer Tools.
3. Chuyển sang tab **Application** (Ứng dụng) ở thanh trên cùng.
4. Ở cột danh mục bên trái, mở mục **Storage** -> **Cookies** -> bấm vào `https://chat.deepseek.com`.
5. Trong bảng danh sách cookie bên phải:
   - Tìm dòng có cột `Name` là `userToken`.
   - Bấm đúp vào ô `Value` của dòng đó và nhấn `Ctrl + C` để copy chuỗi token (dạng chuỗi ký tự dài).
6. Mở **Account Hub** (`http://127.0.0.1:9000`) -> Chọn mục **DeepSeek Pool**.
7. Dán token vừa copy vào ô **Session Token / Cookie** -> Đặt nhãn (tùy chọn) -> Bấm **Thêm tài khoản**.
8. Trạng thái tài khoản sẽ hiện **Hoạt động** (màu xanh lá cây). Eris đã được kết nối tự động với key nội bộ `sk-H5KkH2IcH6haET8mUSoYgu0mzwvts-Tp`.

---

## 4. HƯỚNG DẪN NẠP ELEVENLABS VOICE POOL (TTS GIỌNG NÓI)

ElevenLabs cung cấp giọng lồng tiếng siêu tự nhiên cho Eris.

### Các bước lấy Firebase Token:
1. Mở trình duyệt, truy cập: https://elevenlabs.io và đăng nhập tài khoản.
2. Nhấn phím `F12` để mở Developer Tools.
3. Chọn tab **Application** (Ứng dụng).
4. Ở cột bên trái, mở mục **Storage** -> **IndexedDB** -> **firebaseLocalStorageDb** -> bấm vào **firebaseLocalStorage**.
5. Ở bảng bên phải sẽ xuất hiện các bản ghi tài khoản:
   - Click chọn dòng tài khoản đầu tiên.
   - Nhìn xuống ô hiển thị chi tiết bên dưới, bạn sẽ thấy chuỗi JSON ở mục `value` (bắt đầu bằng `{"uid":...}`).
   - Copy **TOÀN BỘ CHUỖI JSON** đó (hoặc chỉ copy chuỗi ký tự `refreshToken` bắt đầu bằng `AMf-...`).
6. ⚠️ **CẢNH BÁO QUAN TRỌNG:**
   - **TUYỆT ĐỐI KHÔNG COPY** mã `apiKey: "AIzaSy..."`. Đó là Google Firebase API Key chung, không phải token cá nhân! Nếu paste mã đó hệ thống sẽ báo lỗi `INVALID_REFRESH_TOKEN (400)`.
7. Mở **Account Hub** (`http://127.0.0.1:9000`) -> Chọn mục **ElevenLabs Pool**.
8. Dán toàn bộ chuỗi JSON hoặc `AMf-...` vào ô nhập -> Bấm **Thêm Token**.
9. Bấm nút **Sync** bên cạnh tài khoản để hệ thống tự động đồng bộ danh sách Voice ID và hạn mức ký tự.

---

## 5. KHẮC PHỤC SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING)

### Lỗi 1: Eris Live2D bị hộp chữ nhật nền đen (không trong suốt)
* **Triệu chứng:** Bong bóng chat trong suốt bình thường, nhưng xung quanh người Eris bị dính một khung hình chữ nhật màu đen xì.
* **Nguyên nhân:** Xảy ra trên các máy tính **Laptop có 2 GPU (Card Onboard Intel/AMD + Card rời NVIDIA)**. Card rời NVIDIA khi xuất hình ảnh OpenGL không viền qua Windows DWM bị lỗi mất kênh trong suốt (Alpha channel).
* **Cách xử lý:**
  - **Cách 1 (Nhanh nhất - 3 giây):** Click chuột phải vào người Eris -> Menu hiện lên -> Bấm chọn **"Chuyển về 2D"**. Eris sẽ chuyển sang chế độ Sprite 2D gốc của Godot: **nền trong suốt 100% tuyệt đối**, nói chuyện chớp mắt bình thường.
  - **Cách 2 (Giữ Live2D):** Ép Python chạy bằng GPU Onboard:
    1. Nhấn phím Windows, gõ tìm kiếm **Graphics Settings** (Cài đặt đồ họa) và mở lên.
    2. Ở mục *Add an app* (Thêm ứng dụng), chọn **Desktop app** -> Bấm **Browse**.
    3. Trỏ tới file: `F:\Eris_Client_Pack\.venv\Scripts\python.exe` (hoặc `python\python.exe`).
    4. Bấm vào mục **Python** vừa thêm -> Chọn **Options** (Tùy chọn).
    5. Tích chọn **Power saving** (Tiết kiệm nguồn điện / GPU tích hợp Intel/AMD) -> Bấm **Save**.
    6. Mở lại Eris bằng `run_eris.bat`. Nền đen sẽ biến mất thành trong suốt hoàn toàn!

### Lỗi 2: Báo lỗi thiếu API Key khi mở `vision.py`
* **Triệu chứng:** `RuntimeError: DS2API enabled nhung chua co ERIS_DS_COMPANION_API_KEY...`
* **Xử lý:** Bản Clean Client Pack đã điền sẵn key mặc định cục bộ `sk-H5KkH2IcH6haET8mUSoYgu0mzwvts-Tp` trong file `config/secrets.json`. Bạn chỉ cần khởi động Docker qua `start_all_tools.bat` là hệ thống tự khớp lệnh.

### Lỗi 3: Bấm "Ping" DeepSeek báo thiếu mật khẩu (`缺少密码`)
* **Triệu chứng:** Trong Account Hub, danh sách DeepSeek hiện nút "Ping", khi bấm vào hiện thông báo đỏ `缺少密码`.
* **Xử lý:** Đây là tính năng phụ dùng cho ai đăng nhập bằng Email/Password. Khi bạn nạp bằng Cookie Session Token, token đó **đã đang hoạt động bình thường** (thể hiện bằng nhãn xanh "Hoạt động"). Bạn có thể bỏ qua nút Ping này.

### Lỗi 4: Lỗi đổi token từ Firebase `[400]: INVALID_REFRESH_TOKEN`
* **Triệu chứng:** Thêm tài khoản ElevenLabs bị báo lỗi 400.
* **Xử lý:** Bạn đã copy nhầm đoạn `apiKey` (`AIzaSy...`). Hãy đọc lại **Phần 4**, copy toàn bộ khối JSON bắt đầu từ `{"uid":...}` hoặc đoạn `AMf-...` trong `stsTokenManager.refreshToken`.
"""

def is_safe_file(rel_path_str: str, file_name: str) -> bool:
    # Khong cho secrets.json that vao zip (secrets.example.json da ghi o buoc 2)
    if file_name.lower() in ("secrets.json", "secrets.example.json"):
        return False

    # Cho phep cac template khac
    if file_name.endswith(".template.csv") or file_name.endswith(".example.json"):
        return True
        
    for pat in SENSITIVE_PATTERNS:
        if pat.search(file_name):
            return False
            
    suffix = Path(file_name).suffix.lower()
    if suffix in SKIP_EXTENSIONS:
        return False
        
    return True

def package():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ZIP.exists():
        try:
            OUTPUT_ZIP.unlink()
        except Exception:
            pass

    # Luu tai lieu tri thuc vao thu muc exports de xem truc tiep ma khong can giai nen
    OUTPUT_DOC.write_text(FULL_KNOWLEDGE_GUIDE, encoding="utf-8")
    print(f"[*] Da tao tai lieu tri thuc: {OUTPUT_DOC}")

    print(f"[*] Dang tao ban dong goi: {OUTPUT_ZIP}")
    file_count = 0
    total_size = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. Ghi file HUONG_DAN_CAI_DAT_VA_KHAC_PHUC_SU_CO.md va HUONG_DAN_CHO_KHACH.txt vao goc zip
        guide_bytes = FULL_KNOWLEDGE_GUIDE.encode("utf-8")
        zf.writestr("HUONG_DAN_CAI_DAT_VA_KHAC_PHUC_SU_CO.md", guide_bytes)
        zf.writestr("HUONG_DAN_CHO_KHACH.txt", guide_bytes)
        print("  [+] Da them HUONG_DAN_CAI_DAT_VA_KHAC_PHUC_SU_CO.md & HUONG_DAN_CHO_KHACH.txt")

        # 2. Tao config/secrets.json sach voi gateway key san sang cho Whale2API
        secrets_ex = ROOT / "config" / "secrets.example.json"
        if secrets_ex.exists():
            sec_data = json.loads(secrets_ex.read_text(encoding="utf-8"))
            gateway_key = "sk-H5KkH2IcH6haET8mUSoYgu0mzwvts-Tp"
            api_keys = sec_data.setdefault("api_keys", {})
            api_keys["ERIS_DS2API_API_KEY"] = gateway_key
            api_keys["ERIS_DS_COMPANION_API_KEY"] = gateway_key
            api_keys["ERIS_DS_CRITIC_API_KEY"] = gateway_key
            api_keys["ERIS_DS_INNER_API_KEY"] = gateway_key
            api_keys["ERIS_DS_OBSERVER_API_KEY"] = gateway_key
            api_keys["ERIS_DS_CURATOR_API_KEY"] = gateway_key
            api_keys["ERIS_DS_SEED_API_KEY"] = gateway_key
            api_keys["ERIS_DS_SURFACE_API_KEY"] = gateway_key
            api_keys["ERIS_DS_EXECUTIVE_API_KEY"] = gateway_key
            api_keys["ERIS_REMOTE_API_KEY"] = gateway_key
            api_keys["DEEPSEEK_API_KEY"] = gateway_key
            api_keys["ERIS_VISION_API_KEY"] = "local-key"
            
            clean_secrets = json.dumps(sec_data, indent=2, ensure_ascii=False).encode("utf-8")
            zf.writestr("config/secrets.json", clean_secrets)
            zf.writestr("config/secrets.example.json", secrets_ex.read_bytes())
            print("  [+] Da them config/secrets.json voi gateway key noi bo san sang")

        # 2b. Tao whale2api.db sach (Chi chua gateway key, KHONG chua tai khoan ca nhan)
        import sqlite3, tempfile
        tmp_fd, tmp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        try:
            conn = sqlite3.connect(tmp_db_path)
            conn.execute("""
            CREATE TABLE gateway_api_keys (
                api_key TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """)
            conn.execute("""
            CREATE TABLE pool_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL DEFAULT '',
                token TEXT NOT NULL DEFAULT '',
                discarded INTEGER NOT NULL DEFAULT 0,
                discard_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                mute_until TEXT NOT NULL DEFAULT '',
                device_id TEXT NOT NULL DEFAULT '',
                device_id_updated_at TEXT
            )
            """)
            conn.execute("CREATE TABLE pool_bindings (api_key TEXT, account_id INTEGER, position INTEGER, PRIMARY KEY (api_key, account_id))")
            conn.execute("CREATE TABLE pool_account_test_jobs (api_key TEXT PRIMARY KEY, status TEXT, total INTEGER, done INTEGER, ok_count INTEGER, failed_count INTEGER, skipped_count INTEGER, results TEXT, updated_at TEXT)")
            conn.execute("INSERT INTO gateway_api_keys (api_key, name, remark, enabled) VALUES ('sk-H5KkH2IcH6haET8mUSoYgu0mzwvts-Tp', 'Eris_Deepseek', '', 1)")
            conn.commit()
            conn.close()
            with open(tmp_db_path, "rb") as f:
                zf.writestr("tools/whale2api/docker-data/whale2api/whale2api.db", f.read())
            print("  [+] Da them whale2api.db sach (0 tai khoan, co san gateway key)")
        finally:
            try:
                if os.path.exists(tmp_db_path):
                    os.remove(tmp_db_path)
            except Exception:
                pass

        # 3. Duyet toan bo repo
        for root_dir, dirs, files in os.walk(ROOT):
            # Loc bo thu muc cam
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

            rel_root = Path(root_dir).relative_to(ROOT)
            parts = rel_root.parts

            # Bo qua neu nam trong thu muc cam
            if any(p in SKIP_DIRS for p in parts):
                continue

            for f in files:
                rel_file = rel_root / f
                rel_str = str(rel_file).replace("\\", "/")

                # Kiem tra file an toan
                if not is_safe_file(rel_str, f):
                    continue

                full_path = Path(root_dir) / f

                # Bo qua file output zip dang ghi
                if full_path.resolve() == OUTPUT_ZIP.resolve():
                    continue

                try:
                    zf.write(full_path, arcname=rel_str)
                    file_count += 1
                    total_size += full_path.stat().st_size
                except Exception as e:
                    print(f"  [!] Bo qua {rel_str}: {e}")

    zip_size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    orig_size_mb = total_size / (1024 * 1024)
    print(f"\n[OK] Hoan thanh dong goi Eris Clean Client Pack!")
    print(f"  - So file: {file_count}")
    print(f"  - Dung luong goc: {orig_size_mb:.2f} MB")
    print(f"  - Dung luong file zip: {zip_size_mb:.2f} MB")
    print(f"  - Vi tri: {OUTPUT_ZIP}")
    print(f"  - Tai lieu kem theo: {OUTPUT_DOC}")

if __name__ == "__main__":
    package()
