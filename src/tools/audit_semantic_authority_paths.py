# -*- coding: utf-8 -*-
"""Audit cú pháp/marker cho single semantic authority."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_MARKER = "ERIS_AUDIT_FORBIDDEN_SEMANTIC_AUTHORITY"


def audit(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    parse_errors: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    scanned = 0
    for path in sorted(base.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".pytest_cache", "paraphrase-multilingual-MiniLM-L12-v2"} for part in path.parts):
            continue
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
        except Exception as exc:
            parse_errors.append({"path": str(path.relative_to(base)), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if path.resolve() != Path(__file__).resolve() and _MARKER in source:
            findings.append({"path": str(path.relative_to(base)), "rule": "forbidden_semantic_authority_marker"})
    return {"scanned_files": scanned, "parse_errors": parse_errors, "findings": findings, "passed": not parse_errors and not findings}


__all__ = ["audit"]
