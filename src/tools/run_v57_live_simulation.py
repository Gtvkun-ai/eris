# -*- coding: utf-8 -*-
"""CLI chạy behavioral simulation bằng provider/runtime thật.

Ví dụ:
    python tools/run_v57_live_simulation.py --scenario correction_repair
    python tools/run_v57_live_simulation.py --scenario all --strict

Nếu máy không có provider/API key thật, lệnh trả PROVIDER_UNAVAILABLE và --strict
exit khác 0. Không có chế độ mock được phép giả danh một realism run.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Cho phép chạy trực tiếp `python tools/run_v57_live_simulation.py` từ source root.
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from experiments.v57_simulation.report import write_report
from experiments.v57_simulation.runner import LiveSimulationRunner
from experiments.v57_simulation.scenarios import build_soak_scenario, select_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="V57.1: chạy Eris thật và chấm chính câu Eris nói")
    parser.add_argument("--scenario", action="append", default=[], help="scenario id; dùng all để chạy toàn bộ")
    parser.add_argument("--run-root", type=Path, default=Path(".v57_runs"), help="persistent root cô lập cho simulation")
    parser.add_argument("--output", type=Path, default=Path("v57_reports"), help="thư mục report JSON/Markdown")
    parser.add_argument("--soak-turns", type=int, default=0, help="thêm live soak N turn (mỗi turn gọi AI thật và được chấm)")
    parser.add_argument("--restart-every", type=int, default=10, help="với soak: dựng lại runtime sau mỗi N turn; 0=tắt")
    parser.add_argument("--strict", action="store_true", help="exit 2 nếu run không phải real PASS")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scenarios = list(select_scenarios(tuple(args.scenario) or ("all",)))
    if args.soak_turns > 0:
        scenarios.append(build_soak_scenario(turns=args.soak_turns, restart_every=args.restart_every))
    if not scenarios:
        raise SystemExit("Không tìm thấy scenario được chọn")
    report = LiveSimulationRunner(run_root=args.run_root).run(scenarios)
    json_path, md_path = write_report(report, args.output)
    print(json.dumps({
        "run_id": report.run_id,
        "validity": report.validity.value,
        "passed": report.passed,
        "provider": report.provider,
        "model": report.model,
        "judge_provider": report.judge_provider,
        "judge_model": report.judge_model,
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, ensure_ascii=False, indent=2))
    if args.strict and not report.passed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
