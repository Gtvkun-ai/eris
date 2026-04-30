from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cortex.se import SeLens  # noqa: E402


DESKTOP_TRAIN_DIR = SRC_DIR / "datasets_clean" / "train" / "desktop"
OUTPUT_PATH = SRC_DIR / "datasets_clean" / "train" / "se" / "se_supervision.jsonl"


def build_raw_telemetry(machine_context: dict) -> dict:
    # luôn đảm bảo có app/cửa sổ hoạt động và ép bằng string 
    active_app = str(machine_context.get("active_app", "") or machine_context.get("active_window", "") or "Desktop")
    # đồng nhất kiểu số thực cho thời gian idle
    idle_seconds = float(machine_context.get("idle_seconds", 0.0) or 0.0)
    return {
        "captured_at": str(machine_context.get("time", "") or machine_context.get("captured_at", "") or ""),
        "active_window": active_app,
        "active_app": active_app,
        "browser_url": str(machine_context.get("browser_url", "") or ""),
        "browser_tabs": list(machine_context.get("browser_tabs", ()) or ()),
        "open_windows": list(machine_context.get("open_windows", (active_app,)) or (active_app,)),
        "cpu_percent": float(machine_context.get("cpu_percent", 0.0) or 0.0),
        "ram_percent": float(machine_context.get("ram_percent", 0.0) or 0.0),
        "mood_score": int(machine_context.get("mood_score", 50) or 50),
        "inferred_pos_x": float(machine_context.get("inferred_pos_x", 0.5) or 0.5),
        "idle_seconds": idle_seconds,
        "recent_events": list(machine_context.get("recent_events", ()) or ()),
        "user_signals": dict(machine_context.get("user_signals", {}) or {}),
        "evidence": list(machine_context.get("evidence", ()) or ()),
        "claim_style": str(machine_context.get("claim_style", "") or ""),
    }


def iter_desktop_rows():
    # Duyệt tất cả file .jsonl trong thư mục train desktop
    #Dùng DESKTOP_TRAIN_DIR.glob("*.jsonl"), rồi sorted(...) để thứ tự ổn định.
    for path in sorted(DESKTOP_TRAIN_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped) #Lọc các dòng trống và parse JSON
                machine_context = payload.get("machine_context") #Lấy machine_context và lọc kiểu
                if not isinstance(machine_context, dict):
                    continue
                # Nghĩa là không load toàn bộ vào RAM, mà phát từng record một cho 
                # vòng for bên ngoài dùng dần.
                yield path, line_number, machine_context

# Các prompt có thể được dùng để huấn luyện SE hoặc làm ví dụ cho 
#  về cách phản hồi dựa trên machine context.
def main() -> None:
    se_lens = SeLens() # Khởi tạo SeLens để chuẩn bị cho việc chuyển đổi raw telemetry thành normalized machine context
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        for source_path, line_number, machine_context in iter_desktop_rows():
            raw_telemetry = build_raw_telemetry(machine_context)
            normalized_machine_context = se_lens.build_machine_context(raw_telemetry)
            record = {
                "source_file": source_path.name,
                "source_line": line_number,
                "raw_telemetry": raw_telemetry,
                "normalized_machine_context": normalized_machine_context,
            }
            json.dump(record, handle, ensure_ascii=False)
            handle.write("\n")
            rows_written += 1

    print(f"Wrote {rows_written} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
