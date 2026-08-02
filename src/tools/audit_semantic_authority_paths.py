# -*- coding: utf-8 -*-
"""Static guard for removed shadow semantic authorities and legacy live classifiers."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_BANNED_NAMES = {
    "is_recent_user_turn_recall",
    "is_short_repair_request",
    "_build_conversation_continuity_decision",
    "_conversation_repair_fallback_text",
}


def audit(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    parse_errors = []
    findings = []
    for path in sorted(base.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv", "tests", "tools"} for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append({"path": str(path.relative_to(base)), "error": str(exc)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _BANNED_NAMES:
                findings.append({"path": str(path.relative_to(base)), "line": node.lineno, "reason": f"legacy_semantic_authority:{node.name}"})
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [alias.name for alias in getattr(node, "names", [])]
                if module == "runtime.semantic_shadow" or "runtime.semantic_shadow" in names:
                    findings.append({"path": str(path.relative_to(base)), "line": node.lineno, "reason": "semantic_shadow_import"})
    return {"schema": "eris.semantic_authority_audit.v1", "parse_errors": parse_errors, "findings": findings, "passed": not parse_errors and not findings}


__all__ = ["audit"]
