# -*- coding: utf-8 -*-
"""Kiểm tra 32 file WAV greeting trước khi chạy Eris.

Chạy từ thư mục repo:
    python tools/check_greeting_audio.py

Exit code 0 khi đủ và hợp lệ; exit code 1 nếu còn thiếu/hỏng.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "assets" / "tts" / "greetings" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    invalid: list[str] = []
    valid: list[str] = []

    for item in payload.get("presets", []):
        path = repo_root / str(item.get("audio_asset", ""))
        if not path.is_file():
            missing.append(str(path.relative_to(repo_root)))
            continue
        data = path.read_bytes()
        if len(data) < 44 or data[:4] not in {b"RIFF", b"RF64"}:
            invalid.append(str(path.relative_to(repo_root)))
            continue
        valid.append(str(path.relative_to(repo_root)))

    print(f"Hợp lệ: {len(valid)}/32")
    if missing:
        print(f"Thiếu: {len(missing)}")
        for item in missing:
            print(f"  - {item}")
    if invalid:
        print(f"Hỏng/sai định dạng: {len(invalid)}")
        for item in invalid:
            print(f"  - {item}")
    return 0 if len(valid) == 32 else 1


if __name__ == "__main__":
    raise SystemExit(main())
