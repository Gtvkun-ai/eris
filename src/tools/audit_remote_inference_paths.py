# -*- coding: utf-8 -*-
"""Static audit for obvious provider calls that bypass the inference broker."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_APPROVED_PARTS = {
    "inference_broker.py",
    "client.py",
    "service.py",
    "deepseek.py",
    "dds.py",
    "tutor_backend.py",
    "elevenlabs_client.py",
    "tts_engine.py",
    "process_manager.py",
    "elevenlabs_pool_db.py",
    "private_mind_model_adapter.py",
    "speech_localizer.py",
}
_PROVIDER_MARKERS = ("api.openai.com", "api.anthropic.com", "api.deepseek.com", "api.elevenlabs.io")


def audit(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    parse_errors = []
    findings = []
    for path in sorted(base.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append({"path": str(path.relative_to(base)), "error": str(exc)})
            continue
        if path.name in _APPROVED_PARTS or "tests" in path.parts or "tools" in path.parts:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                if any(marker in lowered for marker in _PROVIDER_MARKERS):
                    findings.append({
                        "path": str(path.relative_to(base)),
                        "line": getattr(node, "lineno", 0),
                        "reason": "provider_url_outside_approved_adapter",
                    })
    return {"schema": "eris.remote_inference_audit.v1", "parse_errors": parse_errors, "findings": findings, "passed": not parse_errors and not findings}


__all__ = ["audit"]
