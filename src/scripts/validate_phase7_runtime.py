# -*- coding: utf-8 -*-
"""Kiểm tra nhanh log thực chiến Autonomous VTuber Phase 7.

Cách dùng (PowerShell, đứng ở thư mục src):
    python scripts/validate_phase7_runtime.py ../logs/eris_run_YYYYMMDD_HHMMSS.txt

Script không sửa project, không gọi API và không đọc secrets. Nó chỉ kiểm tra
các dấu hiệu integration quan trọng trong log: cycle có bị mất, permit có đi tới
trạng thái cuối, TTS còn tự bóp bằng lane budget hay không, và session ritual có
văng NameError cũ không.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


CYCLE_RE = re.compile(
    r"\[autonomous cycle\]\s+id=(?P<id>\S+)\s+status=(?P<status>\S+)(?:\s+reason=(?P<reason>\S+))?"
)
STAGE_RE = re.compile(
    r"\[autonomous stage\].*?opportunity=(?P<opp>\S+).*?permit=(?P<allowed>True|False)/(?P<mode>\S+)"
)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1258", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def analyze(text: str) -> tuple[list[str], list[str], list[str]]:
    critical: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    cycles: dict[str, list[str]] = defaultdict(list)
    reasons: dict[str, list[str]] = defaultdict(list)
    for match in CYCLE_RE.finditer(text):
        cycle_id = match.group("id")
        cycles[cycle_id].append(match.group("status"))
        if match.group("reason"):
            reasons[cycle_id].append(match.group("reason"))

    stage_rows = list(STAGE_RE.finditer(text))
    permit_true = sum(1 for row in stage_rows if row.group("allowed") == "True")
    permit_false = len(stage_rows) - permit_true
    final_states = {"spoken", "suppressed", "cancelled", "failed", "expired"}

    if not cycles:
        critical.append("Không thấy log '[autonomous cycle]': patch Phase 7 có thể chưa được nạp.")
    else:
        orphaned = [
            cycle_id for cycle_id, states in cycles.items()
            if not any(state in final_states for state in states)
        ]
        if orphaned:
            critical.append(
                f"Có {len(orphaned)} cycle chưa có trạng thái cuối: " + ", ".join(orphaned[:8])
            )
        frozen = sum(1 for states in cycles.values() if "frozen" in states)
        spoken = sum(1 for states in cycles.values() if "spoken" in states)
        notes.append(
            f"Cycles={len(cycles)}; frozen={frozen}; spoken={spoken}; permit_true={permit_true}; permit_false={permit_false}."
        )
        if permit_true > 0 and spoken == 0:
            critical.append(
                "Có permit=True nhưng không cycle nào kết thúc spoken. Kiểm tra đường Candidate → Stage → public output."
            )

    if "TTS segment vượt lane budget" in text:
        critical.append("Vẫn còn lỗi 'TTS segment vượt lane budget'; TTS Phase 7 chưa chạy đúng file mới.")
    if "name 'public_text' is not defined" in text or "NameError: name 'public_text'" in text:
        critical.append("Session ritual vẫn gặp NameError public_text.")
    if "autonomous_stage.v6" in text and "autonomous_stage.v7" not in text:
        warnings.append("Log chỉ thấy contract v6; có thể patch chưa ghi đè đúng runtime.")
    if "[surface_arbiter] output" in text and "should_speak=True" in text:
        warnings.append(
            "Legacy SurfaceArbiter vẫn tự phát lời. Kiểm tra ERIS_AUTONOMOUS_STAGE_EXCLUSIVE_PUBLIC_SPEECH=1."
        )
    if "PERMISSION_DENIED" in text or "403" in text:
        warnings.append(
            "Có lỗi quyền provider. Phase 7 sẽ loại key khỏi riêng lane TTS, nhưng project/key đó vẫn cần kiểm tra trên Google AI Studio."
        )
    if "tts_http_429" in text or "RESOURCE_EXHAUSTED" in text:
        warnings.append("Có rate limit TTS; key pool đã xoay nhưng chất lượng thực chiến vẫn phụ thuộc quota.")

    counts = Counter(match.group("status") for match in CYCLE_RE.finditer(text))
    if counts:
        notes.append("Trạng thái cycle: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return critical, warnings, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra log Eris Autonomous VTuber Phase 7")
    parser.add_argument("log_file", type=Path, help="Đường dẫn file eris_run_*.txt")
    args = parser.parse_args()

    if not args.log_file.exists():
        print(f"[LỖI] Không tìm thấy file: {args.log_file}")
        return 2

    critical, warnings, notes = analyze(_read_text(args.log_file))
    print("=== ERIS AUTONOMOUS VTUBER PHASE 7 VALIDATION ===")
    for note in notes:
        print(f"[INFO] {note}")
    for warning in warnings:
        print(f"[CẢNH BÁO] {warning}")
    for item in critical:
        print(f"[LỖI] {item}")

    if critical:
        print(f"KẾT QUẢ: FAIL ({len(critical)} lỗi integration quan trọng)")
        return 1
    print(f"KẾT QUẢ: PASS ({len(warnings)} cảnh báo cần theo dõi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
