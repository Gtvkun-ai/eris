# -*- coding: utf-8 -*-
"""tools/package_client_release.py
Dong goi ban phan phoi sach (Eris Clean Client Pack) cho khach / nguoi dung cuoi.
Dam bao:
- Day du runtime, tools, engine Live2D (Eris.exe) va cac script khoi chay bat.
- TUYET DOI KHONG chua API key that, khong chua database (.db), khong chua tai khoan ca nhan.
- Loai bo cac thu muc nang khong can thiet (model cache 1GB, .git, .venv...).
"""

import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "exports"
OUTPUT_ZIP = OUTPUT_DIR / "Eris_Client_Pack.zip"

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

GUIDE_TEXT = """============================================================
              HƯỚNG DẪN CÀI ĐẶT & KHỞI CHẠY ERIS AI
============================================================

Chào bạn! Để chạy Eris AI mượt mà trên máy tính Windows, bạn làm theo
các bước đơn giản dưới đây:

BƯỚC 1: CÀI ĐẶT CÁC BỘ MÔI TRƯỜNG CƠ BẢN (CHỈ CẦN LÀM 1 LẦN)
------------------------------------------------------------
1. Visual C++ 2015-2022 (x64) [BẮT BUỘC]:
   - Tải về và cài đặt: https://aka.ms/vs/17/release/vc_redist.x64.exe
   - (Gói này để chạy Live2D, âm thanh sounddevice và miniaudio).

2. Python 3.12 (64-bit) [BẮT BUỘC]:
   - Tải tại: https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe
   - CỰC KỲ QUAN TRỌNG: Ở ngay màn hình cài đặt đầu tiên, bạn PHẢI TÍCH CHỌN:
     [x] "Add python.exe to PATH"
     (Nếu quên tích chọn, máy tính sẽ không nhận lệnh Python).

3. .NET Desktop Runtime 8.0 (x64) [DÀNH CHO GIAO DIỆN NHÂN VẬT]:
   - Tải tại: https://dotnet.microsoft.com/en-us/download/dotnet/8.0 (Chọn .NET Desktop Runtime x64).

BƯỚC 2: CÀI ĐẶT THƯ VIỆN TỰ ĐỘNG
------------------------------------------------------------
- Bạn bấm đúp chuột vào file: run_doctor.bat
- Cửa sổ sẽ tự động kiểm tra và hướng dẫn/cài đặt các thư viện Python cần thiết.

BƯỚC 3: QUẢN LÝ TÀI KHOẢN & TOOL (ACCOUNT HUB)
------------------------------------------------------------
- Bấm đúp chuột vào file: run_manager.bat
- Trình duyệt sẽ mở trang quản lý tại: http://127.0.0.1:9000
- Tại đây, bạn có thể kiểm tra trạng thái và nạp tài khoản AI (DeepSeek, Gemini...) của bạn.

BƯỚC 4: KHỞI ĐỘNG ERIS
------------------------------------------------------------
- Bấm đúp chuột vào file: run_eris.bat
- Eris sẽ bắt đầu thức tỉnh và đồng hành cùng bạn!
============================================================
"""

def is_safe_file(rel_path_str: str, file_name: str) -> bool:
    # Bo qua cac file trong sensitive pattern (ngoai tru template)
    if file_name.endswith(".template.csv") or file_name.endswith(".example.json"):
        return True
    
    # Khong cho secrets.json that vao zip
    if file_name.lower() == "secrets.json":
        return False
        
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

    print(f"[*] Dang tao ban dong goi: {OUTPUT_ZIP}")
    file_count = 0
    total_size = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. Ghi file HUONG_DAN_CHO_KHACH.txt
        zf.writestr("HUONG_DAN_CHO_KHACH.txt", GUIDE_TEXT.encode("utf-8"))
        print("  [+] Da them HUONG_DAN_CHO_KHACH.txt")

        # 2. Tao config/secrets.json sach (copy tu secrets.example.json)
        secrets_ex = ROOT / "config" / "secrets.example.json"
        if secrets_ex.exists():
            clean_secrets = secrets_ex.read_bytes()
            zf.writestr("config/secrets.json", clean_secrets)
            zf.writestr("config/secrets.example.json", clean_secrets)
            print("  [+] Da them config/secrets.json sach (template)")

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

if __name__ == "__main__":
    package()
