# -*- coding: utf-8 -*-
"""Audit broad exception handlers and prevent silent-error growth.

This is a regression budget, not a declaration that the current count is
beautiful. Existing debt can decrease incrementally; CI rejects accidental
increases while the team pays it down instead of breeding more invisible fires.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "config" / "exception_budget.json"
EXCLUDED_PARTS = {".git", ".venv", "venv", "__pycache__", "assets", "live2d_body"}


@dataclass(frozen=True, slots=True)
class FileExceptionStats:
    broad: int = 0
    silent: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"broad": self.broad, "silent": self.silent}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in {"Exception", "BaseException"}
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"} for item in handler.type.elts)
    return False


def _is_none_literal(node: ast.AST | None) -> bool:
    return node is None or (isinstance(node, ast.Constant) and node.value is None)


def _is_silent(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    if not body:
        return True
    meaningful = []
    for node in body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Continue):
            continue
        if isinstance(node, ast.Return) and _is_none_literal(node.value):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        meaningful.append(node)
    return not meaningful


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        yield path


def scan(root: Path = ROOT) -> dict[str, FileExceptionStats]:
    result: dict[str, FileExceptionStats] = {}
    for path in iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        broad = 0
        silent = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not _is_broad(node):
                continue
            broad += 1
            if _is_silent(node):
                silent += 1
        if broad or silent:
            result[path.relative_to(root).as_posix()] = FileExceptionStats(broad=broad, silent=silent)
    return result


def summarize(stats: dict[str, FileExceptionStats]) -> dict[str, object]:
    broad = sum(item.broad for item in stats.values())
    silent = sum(item.silent for item in stats.values())
    top = sorted(stats.items(), key=lambda pair: (pair[1].silent, pair[1].broad), reverse=True)[:20]
    return {
        "schema_version": 1,
        "totals": {"broad": broad, "silent": silent},
        "files": {name: item.to_dict() for name, item in sorted(stats.items())},
        "top_offenders": [
            {"path": name, "broad": item.broad, "silent": item.silent}
            for name, item in top
        ],
    }


def check(current: dict[str, object], baseline: dict[str, object]) -> list[str]:
    errors: list[str] = []
    current_totals = current.get("totals", {}) if isinstance(current, dict) else {}
    base_totals = baseline.get("totals", {}) if isinstance(baseline, dict) else {}
    for key in ("broad", "silent"):
        now = int(current_totals.get(key, 0) or 0)
        allowed = int(base_totals.get(key, 0) or 0)
        if now > allowed:
            errors.append(f"total {key} handlers increased: {now} > {allowed}")

    current_files = current.get("files", {}) if isinstance(current, dict) else {}
    base_files = baseline.get("files", {}) if isinstance(baseline, dict) else {}
    if isinstance(current_files, dict) and isinstance(base_files, dict):
        for path, values in current_files.items():
            if not isinstance(values, dict):
                continue
            base = base_files.get(path, {}) if isinstance(base_files.get(path, {}), dict) else {}
            for key in ("broad", "silent"):
                now = int(values.get(key, 0) or 0)
                allowed = int(base.get(key, 0) or 0)
                if now > allowed:
                    errors.append(f"{path}: {key} handlers increased: {now} > {allowed}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    report = summarize(scan())
    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.baseline}")
        return 0

    print(json.dumps({"totals": report["totals"], "top_offenders": report["top_offenders"][:10]}, ensure_ascii=False, indent=2))
    if args.check:
        if not args.baseline.exists():
            print(f"missing baseline: {args.baseline}")
            return 2
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        errors = check(report, baseline)
        if errors:
            for error in errors[:50]:
                print(f"ERROR: {error}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
