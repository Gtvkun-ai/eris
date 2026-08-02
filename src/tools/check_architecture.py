# -*- coding: utf-8 -*-
"""Check a few hard architectural budgets recorded in RELEASE_MANIFEST.json."""
from __future__ import annotations

import ast
import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    budget = manifest.get("architecture", {})
    coordinator = root / "runtime" / "coordinator.py"
    lines = len(coordinator.read_text(encoding="utf-8").splitlines())
    failures = []
    maximum = int(budget.get("coordinator_max_lines", 0) or 0)
    if maximum and lines > maximum:
        failures.append(f"runtime/coordinator.py has {lines} lines, budget is {maximum}")
    tree = ast.parse(coordinator.read_text(encoding="utf-8"), filename=str(coordinator))
    init_lines = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_lines = max(init_lines, int(item.end_lineno or item.lineno) - item.lineno + 1)
    init_max = int(budget.get("coordinator_init_max_lines", 0) or 0)
    if init_max and init_lines > init_max:
        failures.append(f"coordinator __init__ has {init_lines} lines, budget is {init_max}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"architecture budgets ok: coordinator={lines}, init={init_lines}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
