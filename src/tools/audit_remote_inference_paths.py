"""AST audit for accidental remote-model calls outside the inference boundary."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_APPROVED_PATH_PARTS = {
    ("llm", "client.py"),
    ("runtime", "inference_broker.py"),
    ("runtime", "ai_orchestrated", "model_router.py"),
}
_REMOTE_METHODS = {"chat", "complete", "completions", "generate_content", "responses", "invoke_model"}


def _approved(relative: Path) -> bool:
    parts = relative.parts
    return any(len(parts) >= len(suffix) and tuple(parts[-len(suffix):]) == suffix for suffix in _APPROVED_PATH_PARTS)


def audit(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    parse_errors: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in {".git", ".venv", "venv", "tests", "tools", "__pycache__"} for part in relative.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_errors.append({"path": str(relative), "error": str(exc)})
            continue
        if _approved(relative):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _REMOTE_METHODS:
                continue
            chain = []
            cursor: ast.AST = node.func
            while isinstance(cursor, ast.Attribute):
                chain.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                chain.append(cursor.id)
            rendered = ".".join(reversed(chain))
            if any(token in rendered.lower() for token in ("openai", "anthropic", "gemini", "client.chat", "client.responses")):
                findings.append({
                    "path": str(relative),
                    "line": int(getattr(node, "lineno", 0)),
                    "call": rendered,
                    "rule": "remote_call_outside_inference_boundary",
                })
    return {"parse_errors": parse_errors, "findings": findings, "passed": not parse_errors and not findings}


__all__ = ["audit"]
