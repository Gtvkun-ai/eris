# -*- coding: utf-8 -*-
"""Đọc log V62 và tóm tắt sức sống autonomous + Live2D mouth.

Tool này chỉ đọc log public/runtime, không đọc chain-of-thought. Mục tiêu là để
một lần chạy lỗi không bắt người phải lội vài trăm dòng như khảo cổ học số.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

_MOUTH_RE = re.compile(r"\[Live2D\]\[Mouth\].*?ratio=([0-9.]+).*?open=(-?[0-9.]+)")


def analyze(text: str) -> dict[str, object]:
    lines = text.splitlines()
    mouth = []
    for line in lines:
        match = _MOUTH_RE.search(line)
        if match:
            mouth.append((float(match.group(1)), float(match.group(2))))
    return {
        "autonomous_spoke": sum("[ai autonomous] spoke" in line for line in lines),
        "autonomous_silence": sum("[ai autonomous] silence" in line for line in lines),
        "surface_duplicate": sum("surface_duplicate_recent_utterance" in line for line in lines),
        "surface_rewrite_recovered": sum("duplicate rewrite recovered" in line for line in lines),
        "surface_duplicate_suppressed": sum("duplicate-suppressed" in line for line in lines),
        "provider_circuit_open": sum("[PROVIDER CIRCUIT] open" in line for line in lines),
        "runtime_degraded": sum("recv=degraded" in line for line in lines),
        "mouth_samples": len(mouth),
        "mouth_open_samples": sum(ratio > 0.04 and opened > -0.90 for ratio, opened in mouth),
        "mouth_closed_samples": sum(ratio <= 0.01 or opened <= -0.95 for ratio, opened in mouth),
        "mouth_peak_ratio": max((ratio for ratio, _ in mouth), default=0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phân tích autonomous/lip-sync từ Eris run log")
    parser.add_argument("log", help="Đường dẫn file eris_run_*.txt")
    args = parser.parse_args()
    path = Path(args.log)
    if not path.is_file():
        print(f"[V62] Không thấy log: {path}")
        return 2
    result = analyze(path.read_text(encoding="utf-8", errors="replace"))
    print("=== V62 AUTONOMY + MOUTH PROBE ===")
    for key, value in result.items():
        print(f"{key:30s}: {value}")

    problems = []
    if result["provider_circuit_open"]:
        problems.append("provider circuit đã mở ít nhất một lần")
    if result["surface_duplicate"] and not result["surface_rewrite_recovered"]:
        problems.append("Surface còn lặp câu mà chưa có rewrite recovery")
    if result["mouth_samples"] and result["mouth_open_samples"] == 0:
        problems.append("mọi mouth probe đều đóng")
    if problems:
        print("\nCẢNH BÁO:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\nKhông thấy lỗi liveness cứng trong các tín hiệu được probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
