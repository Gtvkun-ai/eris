"""Static audit for retired phrase-routing authority in production modules."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_RETIRED_SYMBOLS = {
    "ActionRouter",
    "render_capability_registry_prompt",
    "capability_surface_keywords",
    "semantic_shadow",
}
_PRODUCTION_ROOTS = {"actions", "runtime", "llm", "cortex"}


def audit(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    parse_errors: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if not relative.parts or relative.parts[0] not in _PRODUCTION_ROOTS:
            continue
        if any(part in {"tests", "__pycache__"} for part in relative.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_errors.append({"path": str(relative), "error": str(exc)})
            continue
        for node in ast.walk(tree):
            symbol = ""
            if isinstance(node, (ast.Name, ast.Attribute)):
                symbol = node.id if isinstance(node, ast.Name) else node.attr
            if symbol in _RETIRED_SYMBOLS:
                findings.append({
                    "path": str(relative),
                    "line": int(getattr(node, "lineno", 0)),
                    "symbol": symbol,
                    "rule": "retired_semantic_authority_symbol",
                })
    return {"parse_errors": parse_errors, "findings": findings, "passed": not parse_errors and not findings}


__all__ = ["audit"]
