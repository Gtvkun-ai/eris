# -*- coding: utf-8 -*-
"""Count broad and silent exception handlers against a checked-in budget."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in {"Exception", "BaseException"}
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"} for item in handler.type.elts)
    return False


def _is_silent(handler: ast.ExceptHandler) -> bool:
    meaningful = [node for node in handler.body if not isinstance(node, ast.Pass)]
    if not meaningful:
        return True
    return all(isinstance(node, (ast.Continue, ast.Break)) for node in meaningful)


def scan(root: Path) -> dict[str, Any]:
    files = {}
    parse_errors = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in {"tests", "tools", "__pycache__", ".git", ".venv", "venv"} for part in relative.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append({"path": relative.as_posix(), "error": str(exc)})
            continue
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
        broad = sum(1 for handler in handlers if _is_broad(handler))
        silent = sum(1 for handler in handlers if _is_silent(handler))
        if broad or silent:
            files[relative.as_posix()] = {"broad": broad, "silent": silent}
    return {
        "schema_version": 1,
        "totals": {
            "broad": sum(item["broad"] for item in files.values()),
            "silent": sum(item["silent"] for item in files.values()),
        },
        "files": files,
        "parse_errors": parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = root / "config" / "exception_budget.json"
    current = scan(root)
    if current["parse_errors"]:
        print(json.dumps(current["parse_errors"], indent=2))
        return 1
    if args.write:
        current.pop("parse_errors", None)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
        return 0
    budget = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    for kind in ("broad", "silent"):
        actual = int(current["totals"][kind])
        allowed = int(budget.get("totals", {}).get(kind, 0))
        if actual > allowed:
            failures.append(f"{kind}: actual={actual} budget={allowed}")
    if failures:
        print("exception budget exceeded")
        print("\n".join(failures))
        return 1
    print(f"exception budget ok: {current['totals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
